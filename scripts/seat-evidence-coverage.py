#!/usr/bin/env python3
"""seat-evidence-coverage.py — card t_52219682 (LANE B, READ-ONLY measurement).

QUESTION
  The 25 copy seats are scored off their VENUE record, but a copy can only be placed on a leg
  this bot OBSERVED (ObservedTrade). 12 of 25 seats have <30 observed settled keys, 2 have zero.
  This instrument decomposes WHY, per seat, into four populations that the "12/25" headline blends:

    (a) observed, but the market has NOT settled yet            -> calendar
    (b) observed AND settled                                    -> the usable evidence base
    (c) venue legs never observed at all                        -> coverage / rotation
    (d) observed keys with no venue position to settle against   -> matching

  and then prices the two policy levers that could in principle thicken (b):
  the OBSERVE rotation (MAX_OBSERVE=40 / cycle, 7d eligibility) and the monitor's trailing window
  (MONITOR_HOURS=24, sweep every ~11 min for a track seat).

READ-ONLY: SQLite opened mode=ro, SELECT only. No rule/gate/size/tracking change. Writes only
data/ caches + data/seat-evidence-coverage.json.

CACHES (resumable)
  data/wallet-seat-positions.json      venue CLOSED positions for 25 seats + challengers (parent card)
  data/seat-evidence-open-positions.json  venue OPEN positions for the 25 seats (this card)
  data/seat-evidence-market-truth.json    conditionId -> {closed, end, tokens[]} (CLOB, this card)

RUN
  python3 scripts/seat-evidence-coverage.py --fetch-open --fetch-truth
  python3 scripts/seat-evidence-coverage.py            # report off the caches
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if not (ROOT / "package.json").exists():
    ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get("COPYBOT_DB", str(ROOT / "prisma" / "dev.db")))
OUT = ROOT / "data" / "seat-evidence-coverage.json"
POS = ROOT / "data" / "wallet-seat-positions.json"
OPENP = ROOT / "data" / "seat-evidence-open-positions.json"
TRUTH = ROOT / "data" / "seat-evidence-market-truth.json"
NEARCERT = ROOT / "data" / "nearcert-market-meta.json"
TRUTH0 = ROOT / "data" / "market-truth-clob.json"

DATA_API = "https://data-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"
UA = {"accept": "application/json", "user-agent": "copybot-research/0.1 (paper-trading-only)"}
MAX_TRACKED = 25
MAX_OBSERVE = 40
MONITOR_HOURS = 24
SETTLE_TOL = 0.005
CYCLE_MIN = 11.0  # measured median monitor cycle (see rotation section)


def now_ms():
    return int(time.time() * 1000)


def iso(ms):
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000.0, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def nrm(v):
    return re.sub(r"[^a-z0-9]", "", str(v or "").lower())


def ts_parse(s):
    """ISO-8601 Z string -> epoch ms."""
    return int(datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp() * 1000)


def get_json(url, tries=4, timeout=40):
    for a in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception:  # noqa: BLE001
            if a == tries - 1:
                return None
            time.sleep(1.2 * (a + 1))
    return None


# ---------------------------------------------------------------- venue walks
def walk_positions(wallet, status, max_pages=40, page_limit=50):
    """Cursor-paged venue position walk for one status (CLOSED|OPEN)."""
    cur, out, pages, end = None, [], 0, None
    while pages < max_pages:
        url = ("%s/v2/positions?user=%s&status=%s&limit=%d&sort_by=REALIZED_PNL&sort_direction=DESC"
               % (DATA_API, wallet, status, page_limit))
        if cur:
            url += "&cursor=" + urllib.parse.quote(str(cur))
        payload = get_json(url)
        if payload is None:
            end = "error"
            break
        rows = payload.get("data") if isinstance(payload, dict) else payload
        rows = rows or []
        pages += 1
        out.extend(rows)
        cur = None
        if isinstance(payload, dict):
            # v2 wire shape: {"data": [...], "pagination": {"next_cursor": ..., "has_more": ...}}
            pag = payload.get("pagination") or {}
            cur = pag.get("next_cursor") or payload.get("next_cursor")
            if cur is None and pag.get("has_more") and rows:
                # cursor-less continuation is not supported by this surface: say so, do not loop
                end = "no_cursor_but_more"
                break
        if isinstance(cur, dict):
            cur = cur.get("cursor") or cur.get("next_cursor")
        if not cur or not rows:
            end = "end"
            break
        time.sleep(0.12)
    if end is None:
        end = "capped"
    return out, pages, end


FIELDS = ["condition_id", "token_id", "outcome", "total_size", "current_size", "avg_price",
          "realized_pnl", "current_price", "end_date", "redeemable", "first_entry_at",
          "last_event_at", "title", "slug"]


def pack(rows):
    return [[r.get(f) for f in FIELDS] for r in rows]


def unpack(rec):
    flds = rec.get("fields") or FIELDS
    rows = rec.get("rows")
    if rows is None:
        rows = rec.get("closed") or []
    return [dict(zip(flds, r)) for r in rows]


def settle_price(row, today):
    """Terminal price of the token this position holds, or None when not settled."""
    cp = row.get("current_price")
    if cp is None:
        return None
    try:
        cp = float(cp)
    except (TypeError, ValueError):
        return None
    if abs(cp) <= SETTLE_TOL:
        return 0.0
    if abs(cp - 1.0) <= SETTLE_TOL:
        return 1.0
    return None


def end_passed(end_date, today):
    if not end_date:
        return False
    return str(end_date)[:10] < today


# ---------------------------------------------------------------- market truth
def load_truth():
    truth = {}
    if TRUTH0.exists():
        try:
            truth.update(json.loads(TRUTH0.read_text()).get("markets") or {})
        except Exception:  # noqa: BLE001
            pass
    if TRUTH.exists():
        try:
            truth.update(json.loads(TRUTH.read_text()).get("markets") or {})
        except Exception:  # noqa: BLE001
            pass
    return truth


# ---------------------------------------------------------------- venue activity (capture probe)
ACT = ROOT / "data" / "seat-evidence-activity.json"


def read_activity(wallet, max_pages=10, typed=False):
    """The venue's own activity feed, paged newest-first. typed=True reproduces what the monitor
    asks for (type=TRADE); typed=False returns the full event mix (REDEEM/CONVERSION/MERGE too),
    which is what a position book can be built from without any BUY print."""
    acc, cur, pages = [], None, 0
    while pages < max_pages:
        url = "%s/v2/activity?user=%s&limit=500" % (DATA_API, wallet) + ("&type=TRADE" if typed else "")
        if cur:
            url += "&cursor=" + urllib.parse.quote(str(cur))
        p = get_json(url)
        if not isinstance(p, dict):
            break
        data = p.get("data") or []
        acc.extend(data)
        pages += 1
        cur = (p.get("pagination") or {}).get("next_cursor")
        if not cur or not data:
            break
        time.sleep(0.12)
    return acc, pages


def fetch_activity(wallets, max_pages=10):
    store = {}
    if ACT.exists():
        try:
            store = json.loads(ACT.read_text()).get("wallets") or {}
        except Exception:  # noqa: BLE001
            store = {}
    for i, a in enumerate(wallets):
        rows, pages = read_activity(a, max_pages=max_pages)
        keep = [{k: r.get(k) for k in ("type", "side", "condition_id", "outcome", "timestamp",
                                       "price", "size")} for r in rows]
        ts = [int(r["timestamp"]) for r in keep if r.get("timestamp")]
        store[a] = {"rows": keep, "pages": pages,
                    "window": [iso(min(ts) * 1000), iso(max(ts) * 1000)] if ts else None,
                    "truncated": bool(rows) and pages >= max_pages}
        print("  activity %s pages %d rows %d window %s" % (a[:10], pages, len(keep),
                                                            store[a]["window"]), flush=True)
        if i % 5 == 4:
            ACT.write_text(json.dumps({"generated_at": iso(now_ms()), "wallets": store}))
    ACT.write_text(json.dumps({"generated_at": iso(now_ms()), "wallets": store}))
    return store


def clob_market(cid):
    m = get_json("%s/markets/%s" % (CLOB_API, cid), tries=3, timeout=20)
    if not isinstance(m, dict) or "closed" not in m:
        return None
    toks = []
    for t in (m.get("tokens") or []):
        toks.append([t.get("outcome"), bool(t.get("winner"))])
    return {"closed": bool(m.get("closed")), "end": m.get("end_date_iso") or m.get("end_date"),
            "tokens": toks}


def fetch_truth(cids, pause=0.0, verbose=True, workers=8):
    truth = load_truth()
    store = {}
    if TRUTH.exists():
        try:
            store = json.loads(TRUTH.read_text()).get("markets") or {}
        except Exception:  # noqa: BLE001
            store = {}
    todo = [c for c in cids if c not in truth]
    if verbose:
        print("truth: %d unknown conditionIds to fetch (%d already cached)" % (len(todo), len(cids) - len(todo)),
              flush=True)
    if not todo:
        return store
    from concurrent.futures import ThreadPoolExecutor, as_completed
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(clob_market, c): c for c in todo}
        for fut in as_completed(futs):
            c = futs[fut]
            try:
                got = fut.result()
            except Exception:  # noqa: BLE001
                got = None
            store[c] = got if got is not None else {"error": True}
            done += 1
            if done % 100 == 0:
                TRUTH.write_text(json.dumps({"generated_at": iso(now_ms()), "markets": store}))
                print("  truth %d/%d" % (done, len(todo)), flush=True)
            if pause:
                time.sleep(pause)
    TRUTH.write_text(json.dumps({"generated_at": iso(now_ms()), "markets": store}))
    if verbose:
        print("truth written: %s (%d entries)" % (TRUTH, len(store)), flush=True)
    return store


# ---------------------------------------------------------------- DB
def load_db():
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    con.row_factory = sqlite3.Row
    seats = [dict(r) for r in con.execute(
        "SELECT address,label,status,sourceRank,roi30d,consistencyScore,copyabilityScore,"
        "oneHitWonderPenalty,globalScore,tradeCount30d,resolvedTradeCount30d,winRate30d,"
        "lastScannedAt,lastTrackedAt,lastObservedAt FROM WalletProfile "
        "WHERE status='track' AND isDemo=0 ORDER BY globalScore DESC, address ASC LIMIT ?", (MAX_TRACKED,))]
    obs = defaultdict(list)
    addrs = [s["address"] for s in seats]
    ph = ",".join("?" * len(addrs))
    for r in con.execute(
            "SELECT walletAddress,conditionId,outcome,side,walletEntryPrice,detectedPrice,size,"
            "timestamp,createdAt,observationOnly,marketId FROM ObservedTrade WHERE isDemo=0 "
            "AND walletAddress IN (%s) ORDER BY walletAddress, createdAt" % ph, addrs):
        obs[r["walletAddress"]].append(dict(r))
    # monitor-run cadence over the WHOLE tape, computed in SQL (6.5M rows never enter python)
    runs = con.execute(
        "SELECT createdAt, CASE WHEN createdAt - lag(createdAt) OVER (ORDER BY createdAt) > 120000 "
        "OR lag(createdAt) OVER (ORDER BY createdAt) IS NULL THEN 1 ELSE 0 END AS newrun "
        "FROM ObservedTrade WHERE isDemo=0").fetchall()
    pool = con.execute(
        "SELECT COUNT(*) n FROM WalletProfile WHERE status!='track' AND isDemo=0 AND lastTrackedAt IS NOT NULL "
        "AND lastTrackedAt >= ?", (now_ms() - 7 * 86400000,)).fetchone()["n"]
    ever_tracked = con.execute(
        "SELECT COUNT(*) n FROM WalletProfile WHERE status!='track' AND isDemo=0 AND lastTrackedAt IS NOT NULL"
    ).fetchone()["n"]
    watch = con.execute("SELECT COUNT(*) n FROM WalletProfile WHERE status='watch' AND isDemo=0").fetchone()["n"]
    never_tracked = con.execute(
        "SELECT COUNT(*) n FROM WalletProfile WHERE isDemo=0 AND lastTrackedAt IS NULL").fetchone()["n"]
    rules_version = con.execute(
        "SELECT version FROM RuleSet WHERE active=1 ORDER BY version DESC LIMIT 1").fetchone()[0]
    con.close()
    return {"seats": seats, "obs": obs, "pool": pool, "ever_tracked": ever_tracked,
            "watch": watch, "never_tracked": never_tracked, "rules_version": rules_version,
            "runs": [(r[0], r[1]) for r in runs]}


# ---------------------------------------------------------------- monitor cadence
def ingest_runs(obs_rows_all, gap_s=120):
    """Group every stored row into monitor runs by ingest-time gap."""
    cts = sorted(r["createdAt"] for rs in obs_rows_all.values() for r in rs)
    runs = []
    for c in cts:
        if not runs or c - runs[-1][1] > gap_s * 1000:
            runs.append([c, c, 1])
        else:
            runs[-1][1] = c
            runs[-1][2] += 1
    gaps = [(runs[i + 1][0] - runs[i][0]) / 60000.0 for i in range(len(runs) - 1)]
    return runs, gaps


def main():
    argv = sys.argv[1:]
    fetch_open = "--fetch-open" in argv
    fetch_truth_flag = "--fetch-truth" in argv
    fetch_act = "--fetch-activity" in argv
    act_pages = int(argv[argv.index("--activity-pages") + 1]) if "--activity-pages" in argv else 10
    pause = float(argv[argv.index("--pause") + 1]) if "--pause" in argv else 0.0

    db = load_db()
    seats = db["seats"]
    obs = db["obs"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    pos_cache = json.loads(POS.read_text()) if POS.exists() else {}
    open_cache = json.loads(OPENP.read_text()) if OPENP.exists() else {}
    if fetch_open:
        for i, s in enumerate(seats):
            a = s["address"]
            if a in open_cache and not argv.count("--refetch"):
                continue
            rows, pages, end = walk_positions(a, "OPEN", max_pages=60)
            open_cache[a] = {"fields": FIELDS, "rows": pack(rows), "pages": pages, "end": end,
                             "fetched_at": iso(now_ms())}
            print("  open walk %s pages %d (%s) rows %d" % (a[:10], pages, end, len(rows)), flush=True)
            if i % 5 == 4:
                OPENP.write_text(json.dumps(open_cache))
        OPENP.write_text(json.dumps(open_cache))

    vclosed, vopen = {}, {}
    for s in seats:
        vclosed[s["address"]] = unpack(pos_cache.get(s["address"]) or {})
        vopen[s["address"]] = unpack(open_cache.get(s["address"]) or {})

    act_cache = {}
    if ACT.exists():
        try:
            act_cache = json.loads(ACT.read_text()).get("wallets") or {}
        except Exception:  # noqa: BLE001
            act_cache = {}
    if fetch_act:
        act_cache = fetch_activity([s["address"] for s in seats], max_pages=act_pages)

    # residual observed conditionIds that neither the closed nor the open walk covers need a
    # settlement read; collect them before fetching truth.
    need = set()
    for s in seats:
        a = s["address"]
        have = set()
        for r in vclosed[a] + vopen[a]:
            if r.get("condition_id"):
                have.add((r["condition_id"], nrm(r.get("outcome"))))
        for r in obs.get(a) or []:
            cid = r["conditionId"]
            if not cid:
                continue
            if (cid, nrm(r["outcome"])) in have:
                continue
            need.add(cid)
    truth = load_truth()
    print("observed conditionIds needing a settlement read: %d (of which cached: %d)"
          % (len(need), len(need & set(truth))))
    if fetch_truth_flag:
        fetch_truth(sorted(need), pause=pause)
        truth = load_truth()
    print("truth cache: %d" % len(truth))

    # ---------------------------------------------------------------- per-seat decomposition
    rows_out = []
    for s in seats:
        a = s["address"]
        o = obs.get(a) or []
        # observed keys: first observation per (conditionId, outcome) — the moment a copy would fire
        first = {}
        sideways = Counter()
        for r in o:
            cid = r["conditionId"]
            if not cid:
                continue
            k = (cid, nrm(r["outcome"]))
            if k not in first:
                first[k] = r
            sideways[r["side"]] += 1
        # closed-walk keys, dedupe; keep the best (largest) leg per key
        vc = {}
        for r in vclosed[a]:
            cid = r.get("condition_id")
            if not cid:
                continue
            k = (cid, nrm(r.get("outcome")))
            prev = vc.get(k)
            if prev is None or float(r.get("total_size") or 0) > float(prev.get("total_size") or 0):
                vc[k] = r
        vo = {}
        for r in vopen[a]:
            cid = r.get("condition_id")
            if not cid:
                continue
            vo[(cid, nrm(r.get("outcome")))] = r

        settled_v = {k: r for k, r in vc.items() if settle_price(r, today) is not None}
        open_marks = {k: r for k, r in vc.items() if settle_price(r, today) is None}

        # ---- settlement state per KEY. Order of authority: the market oracle (CLOB closed flag) when
        # we have it; otherwise the wallet's own venue leg when its mark is terminal AND its end_date
        # has passed (the parent card's basis, kept so the two reads reconcile).
        def key_state(k):
            t = truth.get(k[0])
            if t and not t.get("error") and "closed" in t:
                return "settled" if t.get("closed") else "open", "oracle"
            r = vc.get(k)
            if r is not None:
                mark = settle_price(r, today)
                if mark is not None and end_passed(r.get("end_date"), today):
                    return "settled", "mark"
                return "open", "mark_unsettled"
            if k in vo:
                return "open", "held"
            return "unknown", None

        # observed keys: (a) unsettled / (b) settled / (d) settled but no venue position to settle to
        b_mark, b_oracle, a_keys, d_keys, unk_keys = [], [], [], [], []
        for k in first:
            st, how = key_state(k)
            if st == "settled":
                if k in settled_v and how == "mark" or (k in vc and settle_price(vc[k], today) is not None
                                                        and end_passed(vc[k].get("end_date"), today)):
                    b_mark.append(k)
                else:
                    b_oracle.append(k)
            elif st == "open":
                a_keys.append(k)
            else:
                unk_keys.append(k)
        settled_obs = b_mark + b_oracle
        # (d): observed a fill in a settled market with no venue position of any status
        d_keys = [k for k in b_oracle if k not in vc and k not in vo]
        b_oracle = [k for k in b_oracle if k not in d_keys]

        observed_set = set(first)
        venue_settled_keys = {k for k in vc if key_state(k)[0] == "settled"}
        venue_unobs = [k for k in venue_settled_keys if k not in observed_set]

        # ---- attribution of (c): the clock that matters is when the wallet FIRST ENTERED the leg,
        # because that is the only moment a copy could have been placed.
        cts_all = sorted(r["createdAt"] for r in o)
        copyable_cts = sorted(r["createdAt"] for r in o if not r["observationOnly"])
        first_ingest = cts_all[0] if cts_all else None
        last_ingest = cts_all[-1] if cts_all else None
        first_copyable = copyable_cts[0] if copyable_cts else None

        def nearest_h(ts, arr):
            if not arr or ts is None:
                return None
            import bisect
            i = bisect.bisect_left(arr, ts)
            best = None
            for j in (i - 1, i):
                if 0 <= j < len(arr):
                    d = abs(arr[j] - ts) / 3600000.0
                    best = d if best is None else min(best, d)
            return best

        def swept_after(ts, arr, window_h=MONITOR_HOURS):
            """True when a sweep happened inside the lookback window that would still have carried
            this fill: a stored row at t' with t <= t' <= t + MONITOR_HOURS."""
            if not arr or ts is None:
                return False
            import bisect
            i = bisect.bisect_left(arr, ts)
            return i < len(arr) and arr[i] <= ts + window_h * 3600000

        c_pre, c_miss, c_unswept, c_undated = 0, 0, 0, 0
        for k in venue_unobs:
            fe = vc[k].get("first_entry_at")
            try:
                fe_ms = int(fe) * 1000 if fe else None
            except (TypeError, ValueError):
                fe_ms = None
            if fe_ms is None:
                c_undated += 1
            elif first_ingest is None or fe_ms < first_ingest:
                c_pre += 1
            elif swept_after(fe_ms, cts_all):
                c_miss += 1      # a sweep landed inside the lookback window: this leg was missable-and-missed
            else:
                c_unswept += 1   # no sweep within the lookback: the wallet was outside the sweep set

        # ---- weekly coverage: venue settled legs entered per ISO week vs legs we saw at all
        #      (and saw within 3 days of entry — the copyable window at an 11-min cadence)
        weekly = defaultdict(lambda: {"venue_entered": 0, "observed_ever": 0, "observed_3d": 0})
        for k in venue_settled_keys:
            r = vc[k]
            fe = r.get("first_entry_at")
            try:
                fe_ms = int(fe) * 1000 if fe else None
            except (TypeError, ValueError):
                fe_ms = None
            if fe_ms is None:
                continue
            wk = iso(fe_ms)[:10]
            wk = wk[:8] + ("%02d" % ((int(wk[8:10]) - 1) // 7 * 7 + 1))
            w = weekly[wk]
            w["venue_entered"] += 1
            if k in first:
                w["observed_ever"] += 1
                d = nearest_h(fe_ms, cts_all)
                if d is not None and d <= 72:
                    w["observed_3d"] += 1

        # ---- capture rate while the wallet WAS being swept: of the venue legs entered within a day
        #      of a stored row, what share did we actually see?
        obs_near = 0
        for k in first:
            r = settled_v.get(k)
            if not r:
                continue
            fe = r.get("first_entry_at")
            try:
                fe_ms = int(fe) * 1000 if fe else None
            except (TypeError, ValueError):
                fe_ms = None
            if fe_ms is None:
                continue
            d = nearest_h(fe_ms, cts_all)
            if d is not None and d <= 24:
                obs_near += 1
        capture_rate = round(obs_near / (obs_near + c_miss), 4) if (obs_near + c_miss) else None

        # ---- 7-day venue flow: legs first entered in the last 7 days (settled or not, so the number
        #      is what a 7-day pre-admission observation window would have had a chance to see)
        week_cut = now_ms() - 7 * 86400000
        day14_cut = now_ms() - 14 * 86400000
        v7 = 0
        for r in list(vc.values()) + list(vo.values()):
            fe = r.get("first_entry_at")
            try:
                fe_ms = int(fe) * 1000 if fe else None
            except (TypeError, ValueError):
                fe_ms = None
            if fe_ms is not None and fe_ms >= week_cut:
                v7 += 1
        # of the settled legs, how many were FIRST ENTERED in the last 7 / 14 days — the settled yield
        # a 7- or 14-day pre-admission observation window would have produced, at the same capture rate
        settled_7d = settled_14d = 0
        for k in venue_settled_keys:
            fe = vc[k].get("first_entry_at")
            try:
                fe_ms = int(fe) * 1000 if fe else None
            except (TypeError, ValueError):
                fe_ms = None
            if fe_ms is None:
                continue
            if fe_ms >= week_cut:
                settled_7d += 1
                settled_14d += 1
            elif fe_ms >= day14_cut:
                settled_14d += 1

        # ---- capture probe on the venue's own activity feed (bounded window, newest first):
        #      of the legs we never observed that were entered inside that window, how many even
        #      HAD a copyable BUY print on the venue tape? A position opened by REDEEM/CONVERSION/
        #      MERGE has no fill to copy, so it is not missing evidence — it is not evidence.
        act = act_cache.get(a) or {}
        act_rows = act.get("rows") or []
        act_first_mix, act_type_mix = Counter(), Counter()
        act_window = act.get("window")
        unobs_in_window = 0
        c_no_print = c_print_missed = c_print_unwatched = 0
        # TOKEN-MATCHED arm (card t_4c9847c9, Lane B): the block above classifies the FIRST row on
        # the CONDITION, so on a two-token market it counts a BUY of the OTHER token as this leg's
        # print. MEASURED on luciebot 2026-11-10..11-12: all 84 "print-present-and-not-stored" legs
        # were legs whose own token had NO BUY print at all, while the paired token carried the
        # prints (all of them stored). The card's basis is kept above and unchanged; this arm names
        # the token-corrected counts so a reader can tell the two apart.
        c_no_print_tok = c_print_missed_tok = c_print_unwatched_tok = 0
        act_first_mix_tok = Counter()
        if act_rows and act_window:
            lo = int(ts_parse(act_window[0]) / 1000)
            hi = int(ts_parse(act_window[1]) / 1000)
            by_cid = defaultdict(list)
            for r in act_rows:
                act_type_mix[str(r.get("type"))] += 1
                if r.get("condition_id"):
                    by_cid[str(r["condition_id"])].append(r)
            for v in by_cid.values():
                v.sort(key=lambda r: int(r.get("timestamp") or 0))
            for k in venue_unobs:
                r = vc.get(k)
                fe = r.get("first_entry_at") if r else None
                try:
                    fe_s = int(fe) if fe else None
                except (TypeError, ValueError):
                    fe_s = None
                if fe_s is None or fe_s < lo or fe_s > hi:
                    continue
                unobs_in_window += 1
                # --- the card's basis: FIRST row on the CONDITION, either token.
                ev = next((x for x in (by_cid.get(k[0]) or [])
                           if int(x.get("timestamp") or 0) >= fe_s - 120), None)
                if ev is None:
                    act_first_mix["no_row"] += 1
                    c_no_print += 1
                else:
                    tag = "%s/%s" % (str(ev.get("type")), str(ev.get("side") or "-"))
                    act_first_mix[tag] += 1
                    is_buy_print = str(ev.get("type")) == "TRADE" and str(ev.get("side")).upper() == "BUY"
                    if not is_buy_print:
                        c_no_print += 1          # position born of REDEEM/CONVERSION/MERGE: nothing to copy
                    elif swept_after(fe_s * 1000, cts_all):
                        c_print_missed += 1      # a BUY print we should have stored, and did not
                    else:
                        c_print_unwatched += 1   # a BUY print nobody was watching for: coverage, not capture
                # --- token-matched twin: same three buckets, but the row must be on THIS leg's
                # token, which is the side a copy would have to cross. Runs unconditionally, so a
                # condition with no rows at all lands in the same bucket in both arms.
                ev_t = next((x for x in (by_cid.get(k[0]) or [])
                             if int(x.get("timestamp") or 0) >= fe_s - 120
                             and nrm(x.get("outcome")) == k[1]), None)
                if ev_t is None:
                    act_first_mix_tok["no_row_on_token"] += 1
                    c_no_print_tok += 1
                else:
                    tag_t = "%s/%s" % (str(ev_t.get("type")), str(ev_t.get("side") or "-"))
                    act_first_mix_tok[tag_t] += 1
                    is_buy_t = str(ev_t.get("type")) == "TRADE" and str(ev_t.get("side")).upper() == "BUY"
                    if not is_buy_t:
                        c_no_print_tok += 1
                    elif swept_after(fe_s * 1000, cts_all):
                        c_print_missed_tok += 1
                    else:
                        c_print_unwatched_tok += 1

        # ---- ingest cadence for this seat
        days = Counter(iso(c)[:10] for c in cts_all) if cts_all else Counter()
        span_days = ((cts_all[-1] - cts_all[0]) / 86400000.0) if len(cts_all) > 1 else 0.0
        gaps_h = [(cts_all[i + 1] - cts_all[i]) / 3600000.0 for i in range(len(cts_all) - 1)]
        # coverage holes: consecutive ingest gaps > 24h (a seat that dropped out of the sweep set,
        # or a monitor outage) — the periods in which a venue leg could not be seen at all
        holes = [(round(gaps_h[i], 1), iso(cts_all[i]), iso(cts_all[i + 1]))
                 for i in range(len(gaps_h)) if gaps_h[i] > 24]
        coverage_hours = sum(gaps_h) if gaps_h else 0.0
        covered_hours = sum(g for g in gaps_h) - sum(h[0] for h in holes)

        rows_out.append({
            "address": a, "label": s["label"], "global_score": s["globalScore"],
            "stored_roi30d": s["roi30d"], "tradeCount30d": s["tradeCount30d"],
            "resolvedTradeCount30d": s["resolvedTradeCount30d"],
            "last_tracked_at": iso(s["lastTrackedAt"]), "last_observed_at": iso(s["lastObservedAt"]),
            "observed_rows": len(o),
            "observed_rows_copy_eligible": len(copyable_cts),
            "observed_keys": len(first),
            "observed_keys_settled": len(b_mark),
            "observed_keys_settled_oracle_extra": len(b_oracle),
            "observed_keys_settled_all": len(settled_obs),
            "observed_keys_unsettled": len(a_keys),
            "observed_keys_unmatched": len(d_keys),
            "observed_keys_unknown": len(unk_keys),
            "venue_positions": len(vc), "venue_positions_settled": len(venue_settled_keys),
            "venue_settled_unobserved": len(venue_unobs),
            "c_pre_observation": c_pre, "c_capture_miss": c_miss, "c_not_swept": c_unswept,
            "c_undated": c_undated,
            "capture_rate_in_coverage": capture_rate,
            "venue_legs_entered_7d": v7,
            "venue_settled_entered_7d": settled_7d,
            "venue_settled_entered_14d": settled_14d,
            "activity_window": act_window,
            "activity_rows": len(act_rows),
            "activity_truncated": bool(act.get("truncated")),
            "activity_type_mix": dict(act_type_mix),
            "unobserved_legs_in_activity_window": unobs_in_window,
            "unobserved_first_event": dict(act_first_mix),
            "c_no_copy_print": c_no_print,
            "c_print_not_stored": c_print_missed,
            "c_print_unwatched": c_print_unwatched,
            "capture_miss_rate": round(c_print_missed / unobs_in_window, 3) if unobs_in_window else None,
            # token-matched arm (card t_4c9847c9): what is left of the three buckets once the row
            # must sit on THIS leg's own token. Same three names, suffixed, so no reader can quote
            # one basis as the other.
            "unobserved_first_event_token": dict(act_first_mix_tok),
            "c_no_copy_print_token": c_no_print_tok,
            "c_print_not_stored_token": c_print_missed_tok,
            "c_print_unwatched_token": c_print_unwatched_tok,
            "first_ingest": iso(first_ingest), "last_ingest": iso(last_ingest),
            "first_copyable_ingest": iso(first_copyable),
            "coverage_holes_gt_24h": len(holes),
            "coverage_hole_hours": round(sum(h[0] for h in holes), 1),
            "coverage_holes_top": holes[:5],
            "weekly": {k: v for k, v in sorted(weekly.items())},
            "ingest_span_days": round(span_days, 1), "ingest_days": len(days),
            "rows_per_ingest_day": round(len(o) / max(1, len(days)), 1) if days else 0.0,
            "median_ingest_gap_h": round(sorted(gaps_h)[len(gaps_h) // 2], 2) if gaps_h else None,
            "p90_ingest_gap_h": round(sorted(gaps_h)[int(len(gaps_h) * 0.9)], 2) if gaps_h else None,
            "keys_per_day_observed": round(len(first) / span_days, 2) if span_days > 0 else None,
            "settled_keys_per_day": round(len(b_mark) / span_days, 3) if span_days >= 0.5 else None,
            "days_to_30_settled_own_flow": (round(30.0 / (len(b_mark) / span_days), 1)
                                            if span_days >= 0.5 and b_mark else None),
            "side_mix": dict(sideways),
            "_debug": {"a_keys": [k[0][:12] for k in a_keys[:5]], "d_keys": [k[0][:12] for k in d_keys[:5]]},
        })

    # ---------------------------------------------------------------- rotation arithmetic
    runs = []
    for c, newrun in db["runs"]:
        if newrun:
            runs.append([c, c, 1])
        else:
            runs[-1][1] = c
            runs[-1][2] += 1
    gaps = [(runs[i + 1][0] - runs[i][0]) / 60000.0 for i in range(len(runs) - 1)]
    gaps_sorted = sorted(gaps)
    cycle_stat = {
        "runs": len(runs),
        "first_run": iso(runs[0][0]) if runs else None,
        "last_run": iso(runs[-1][0]) if runs else None,
        "gap_median_min": round(gaps_sorted[len(gaps_sorted) // 2], 1) if gaps else None,
        "gap_p90_min": round(gaps_sorted[int(len(gaps_sorted) * 0.9)], 1) if gaps else None,
        "gap_max_min": round(gaps_sorted[-1], 1) if gaps else None,
        "monitor_hours": MONITOR_HOURS,
    }
    pool = db["pool"]
    rotation = {
        "max_observe": MAX_OBSERVE,
        "eligible_pool_now": pool,
        "cycles_to_cover_pool": -(-pool // MAX_OBSERVE),
        "sweep_period_h": round((-(-pool // MAX_OBSERVE)) * cycle_stat["gap_median_min"] / 60.0, 2)
        if cycle_stat["gap_median_min"] else None,
        "observe_lookback_days": 7,
        "sweeps_per_wallet_in_eligibility": None,
        "watch_wallets": db["watch"],
        "ever_tracked_non_seat": db["ever_tracked"],
        "never_tracked_wallets": db["never_tracked"],
    }
    if rotation["sweep_period_h"]:
        rotation["sweeps_per_wallet_in_eligibility"] = round(
            7 * 24.0 / rotation["sweep_period_h"], 1)

    # ---------------------------------------------------------------- zero-evidence diagnostics
    # Computed from the caches (venue books + activity feed) so the two seats the card names are
    # reproducible without a separate probe script.
    zero_diag = []
    for r in rows_out:
        if r["observed_keys"] and r["observed_keys_settled"]:
            continue
        a = r["address"]
        act = act_cache.get(a) or {}
        arows = act.get("rows") or []
        now_s = now_ms() / 1000.0
        ts = [int(x["timestamp"]) for x in arows if x.get("timestamp")]
        trade_ts = [int(x["timestamp"]) for x in arows
                    if x.get("timestamp") and str(x.get("type")) == "TRADE"]
        pos = vclosed[a] + vopen[a]
        fe = sorted(int(p["first_entry_at"]) for p in pos if p.get("first_entry_at"))
        ed = sorted(str(p.get("end_date"))[:10] for p in pos if p.get("end_date"))
        zero_diag.append({
            "address": a, "label": r["label"],
            "observed_rows": r["observed_rows"], "observed_keys": r["observed_keys"],
            "observed_keys_settled": r["observed_keys_settled"],
            "venue_positions": len({(p.get("condition_id"), nrm(p.get("outcome"))) for p in pos}),
            "venue_settled_legs": r["venue_positions_settled"],
            "venue_settled_unobserved": r["venue_settled_unobserved"],
            "activity_rows_total": len(arows),
            "activity_trade_rows": len(trade_ts),
            "activity_rows_24h": sum(1 for t in ts if now_s - t <= 86400),
            "activity_rows_7d": sum(1 for t in ts if now_s - t <= 7 * 86400),
            "activity_rows_30d": sum(1 for t in ts if now_s - t <= 30 * 86400),
            "trade_rows_24h": sum(1 for t in trade_ts if now_s - t <= 86400),
            "trade_rows_7d": sum(1 for t in trade_ts if now_s - t <= 7 * 86400),
            "trade_rows_30d": sum(1 for t in trade_ts if now_s - t <= 30 * 86400),
            "activity_type_mix": {k: sum(1 for x in arows if str(x.get("type")) == k)
                                  for k in sorted({str(x.get("type")) for x in arows})},
            "activity_first": iso(min(ts) * 1000) if ts else None,
            "activity_last": iso(max(ts) * 1000) if ts else None,
            "last_trade": iso(max(trade_ts) * 1000) if trade_ts else None,
            "position_first_entry_span": [iso(fe[0] * 1000), iso(fe[-1] * 1000)] if fe else None,
            "position_end_date_span": [ed[0], ed[-1]] if ed else None,
            "mean_position_size": round(sum(float(p.get("total_size") or 0) for p in pos) / len(pos), 1)
            if pos else None,
            "first_ingest": r["first_ingest"],
            "verdict": ("dead seat: no TRADE print in the trailing 30 days — it cannot accumulate "
                        "observed evidence without new flow"
                        if not trade_ts or now_s - max(trade_ts) > 30 * 86400 else
                        "live seat whose observed legs have not settled yet; its settled legs predate "
                        "the first observation"),
        })

    # ---------------------------------------------------------------- time-to-evidence
    flows = [r["settled_keys_per_day"] for r in rows_out if r["settled_keys_per_day"]]
    flows_sorted = sorted(flows)
    median_flow = flows_sorted[len(flows_sorted) // 2] if flows_sorted else None
    days30 = sorted(r["days_to_30_settled_own_flow"] for r in rows_out if r["days_to_30_settled_own_flow"])
    tte = {
        "median_settled_keys_per_observed_day": median_flow,
        "days_to_30_settled_at_median": round(30.0 / median_flow, 1) if median_flow else None,
        "days_to_30_distribution": {"p25": days30[len(days30) // 4] if days30 else None,
                                    "median": days30[len(days30) // 2] if days30 else None,
                                    "p75": days30[int(len(days30) * 0.75)] if days30 else None,
                                    "max": days30[-1] if days30 else None},
        "seats_reaching_30_within_7d_of_observation": sum(1 for d in days30 if d <= 7),
        "seats_reaching_30_within_30d_of_observation": sum(1 for d in days30 if d <= 30),
        "seats_that_never_reach_30_at_own_flow": sum(1 for r in rows_out
                                                     if r["days_to_30_settled_own_flow"] is None),
        "per_seat_days_to_30": {r["address"]: r["days_to_30_settled_own_flow"] for r in rows_out},
        "structural_note": ("a wallet that has never held status=track is outside observeWhere() "
                            "(status!='track' AND lastTrackedAt within 7d), so it accumulates ZERO "
                            "observed keys until it is admitted; its time-to-evidence is unbounded "
                            "however fast its flow, which is why the measured days-to-30 below is a "
                            "POST-admission number and not an age an admission rule can check first"),
    }

    # ---------------------------------------------------------------- summary counts
    thin = [r for r in rows_out if r["observed_keys_settled"] < 30]
    zero = [r for r in rows_out if r["observed_keys"] == 0]
    tot = Counter()
    for r in rows_out:
        for k in ("observed_keys", "observed_keys_settled", "observed_keys_settled_all",
                  "observed_keys_unsettled", "observed_keys_unmatched", "observed_keys_unknown",
                  "venue_positions_settled", "venue_settled_unobserved", "c_pre_observation",
                  "c_capture_miss", "c_not_swept", "c_undated", "venue_legs_entered_7d",
                  "unobserved_legs_in_activity_window", "c_no_copy_print", "c_print_not_stored",
                  "c_print_unwatched", "venue_settled_entered_7d", "venue_settled_entered_14d",
                  "c_no_copy_print_token", "c_print_not_stored_token", "c_print_unwatched_token"):
            tot[k] += r[k]

    # what an admissibility floor would see at admission under a pre-admission observation window:
    # the trailing settled yield instead of a post-hoc observed population
    pre_adm = {
        "seats_with_30plus_settled_entered_in_7d": sum(
            1 for r in rows_out if r["venue_settled_entered_7d"] >= 30),
        "seats_with_30plus_settled_entered_in_14d": sum(
            1 for r in rows_out if r["venue_settled_entered_14d"] >= 30),
        "seats_with_30plus_observed_settled_today": sum(
            1 for r in rows_out if r["observed_keys_settled"] >= 30),
        "settled_entered_7d_total": tot["venue_settled_entered_7d"],
        "settled_entered_14d_total": tot["venue_settled_entered_14d"],
        "note": ("a 7-day pre-admission observation window would hand an admission rule the trailing "
                 "settled yield shown here for each wallet; today the same wallets are admitted on a "
                 "100-row profile sample and their observed-settled population is measured afterwards"),
    }

    # aggregate weekly coverage: venue settled legs first entered per week vs how many of those
    # the bot ever saw, and how many it saw within 3 days (i.e. could have copied)
    agg_weekly = defaultdict(lambda: {"venue_entered": 0, "observed_ever": 0, "observed_3d": 0})
    for r in rows_out:
        for wk, v in (r["weekly"] or {}).items():
            for k2, n in v.items():
                agg_weekly[wk][k2] += n
    weekly_agg = {}
    for wk in sorted(agg_weekly):
        v = agg_weekly[wk]
        weekly_agg[wk] = dict(v, coverage_ever=round(v["observed_ever"] / v["venue_entered"], 3)
                              if v["venue_entered"] else None,
                              coverage_3d=round(v["observed_3d"] / v["venue_entered"], 3)
                              if v["venue_entered"] else None)

    # seat tenure: how long has each seat actually been inside the sweep set (copy-eligible rows)
    tenure = sorted((r["first_copyable_ingest"] or "9999") for r in rows_out)
    seat_age = {
        "seats_with_copy_eligible_rows": sum(1 for r in rows_out if r["first_copyable_ingest"]),
        "first_copyable_ingest_min": tenure[0] if tenure else None,
        "first_copyable_ingest_median": tenure[len(tenure) // 2] if tenure else None,
        "seats_first_copyable_within_7d": sum(1 for r in rows_out if r["first_copyable_ingest"]
                                              and r["first_copyable_ingest"] >= iso(now_ms() - 7 * 86400000)),
        "seats_first_copyable_within_30d": sum(1 for r in rows_out if r["first_copyable_ingest"]
                                               and r["first_copyable_ingest"] >= iso(now_ms() - 30 * 86400000)),
        "seats_with_gt24h_holes": sum(1 for r in rows_out if r["coverage_holes_gt_24h"] > 0),
        "median_coverage_hole_hours": sorted(r["coverage_hole_hours"] for r in rows_out)[len(rows_out) // 2],
    }

    # zero / near-zero diagnostics (the two seats the card names, plus any seat with 0 settled)
    diagnostics = []
    for r in rows_out:
        if r["observed_keys"] == 0 or r["observed_keys_settled"] == 0:
            diagnostics.append({
                "address": r["address"], "label": r["label"],
                "observed_rows": r["observed_rows"], "observed_keys": r["observed_keys"],
                "observed_keys_settled": r["observed_keys_settled"],
                "venue_positions": r["venue_positions"], "venue_positions_settled": r["venue_positions_settled"],
                "venue_settled_unobserved": r["venue_settled_unobserved"],
                "c_pre_observation": r["c_pre_observation"], "c_capture_miss": r["c_capture_miss"],
                "c_not_swept": r["c_not_swept"],
                "first_ingest": r["first_ingest"], "first_copyable_ingest": r["first_copyable_ingest"],
                "last_tracked_at": r["last_tracked_at"], "last_observed_at": r["last_observed_at"],
                "tradeCount30d": r["tradeCount30d"], "resolvedTradeCount30d": r["resolvedTradeCount30d"],
            })

    summary = {
        "seats": len(rows_out),
        "seats_under_30_observed_settled": len(thin),
        "seats_under_30_if_oracle_settlement_counts": sum(
            1 for r in rows_out if r["observed_keys_settled_all"] < 30),
        "seats_zero_observed": len(zero),
        "seats_zero_observed_settled": sum(1 for r in rows_out if r["observed_keys_settled"] == 0),
        "totals": dict(tot),
        "thin_seats": [{"address": r["address"], "label": r["label"],
                        "observed_keys": r["observed_keys"],
                        "settled": r["observed_keys_settled"],
                        "settled_all": r["observed_keys_settled_all"],
                        "unsettled": r["observed_keys_unsettled"],
                        "unmatched": r["observed_keys_unmatched"],
                        "unknown": r["observed_keys_unknown"],
                        "first_copyable_ingest": r["first_copyable_ingest"],
                        "days_to_30": r["days_to_30_settled_own_flow"]} for r in thin],
        "weekly_coverage": weekly_agg,
        "seat_age": seat_age,
        "pre_admission_window": pre_adm,
        "zero_and_near_zero": diagnostics,
        "zero_evidence_diagnostics": zero_diag,
    }

    out = {
        "generated_at": iso(now_ms()),
        "instrument": "scripts/seat-evidence-coverage.py",
        "lane": "B — read-only measurement (no rule/gate/size/tracking change)",
        "rules_version": db["rules_version"],
        "constants": {"MAX_TRACKED": MAX_TRACKED, "MAX_OBSERVE": MAX_OBSERVE,
                      "MONITOR_HOURS": MONITOR_HOURS, "settle_tol": SETTLE_TOL},
        "summary": summary,
        "rotation": rotation,
        "time_to_evidence": tte,
        "cycle_stats": cycle_stat,
        "seats": rows_out,
        "cache": {"positions": str(POS.name), "open": str(OPENP.name), "truth": str(TRUTH.name),
                  "truth_entries": len(truth)},
    }
    OUT.write_text(json.dumps(out, indent=1))
    print("\nwrote %s" % OUT)
    print("seats <30 observed settled: %d of %d ; zero observed: %d"
          % (summary["seats_under_30_observed_settled"], len(rows_out), summary["seats_zero_observed"]))
    print("totals: %s" % json.dumps(summary["totals"]))
    print("activity probe — CONDITION basis (the card's, first row on either token): "
          "no_print=%d print_unwatched=%d print_not_stored=%d"
          % (summary["totals"]["c_no_copy_print"], summary["totals"]["c_print_unwatched"],
             summary["totals"]["c_print_not_stored"]))
    print("activity probe — TOKEN-MATCHED basis (the leg's own token; card t_4c9847c9): "
          "no_print=%d print_unwatched=%d print_not_stored=%d"
          % (summary["totals"]["c_no_copy_print_token"], summary["totals"]["c_print_unwatched_token"],
             summary["totals"]["c_print_not_stored_token"]))
    for r in sorted(rows_out, key=lambda x: x["observed_keys_settled"]):
        print("%-46s ks=%5d settled=%5d +oracle=%4d unsett=%4d unm=%3d unk=%3d | vsettled=%5d unobs=%5d "
              "(pre=%5d miss=%4d notswept=%5d) cap=%s v7=%d"
              % (r["address"], r["observed_keys"], r["observed_keys_settled"],
                 r["observed_keys_settled_oracle_extra"], r["observed_keys_unsettled"],
                 r["observed_keys_unmatched"], r["observed_keys_unknown"],
                 r["venue_positions_settled"], r["venue_settled_unobserved"],
                 r["c_pre_observation"], r["c_capture_miss"], r["c_not_swept"],
                 r["capture_rate_in_coverage"], r["venue_legs_entered_7d"]))


if __name__ == "__main__":
    main()
