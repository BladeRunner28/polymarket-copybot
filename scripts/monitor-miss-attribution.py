#!/usr/bin/env python3
"""monitor-miss-attribution.py — card t_4c9847c9 (LANE B, READ-ONLY measurement).

QUESTION
  The parent seat-evidence probe found 84 legs on `luciebot` where a BUY print existed on the
  venue tape AND a monitor sweep fell inside the 24 h lookback that should have carried it, but
  no ObservedTrade row was stored. The card's hypothesis is the monitor's page cap
  (`for (let page = 0; page < 4; page++)` in src/lib/adapters/polymarket.ts fetchRecentTrades =
  4 x 500 rows per wallet per sweep).

WHAT THIS DOES
  1. Reproduces the parent probe exactly (3,218 probed / 961 / 2,173 / 84) so the population under
     test is not re-derived by hand.
  2. Attributes each of the 84 legs to one cause, in the card's order:
        mask        a row already stored under this leg's identity (dedupe/pre-filter)
        cap         4 x 500 rows could not have reached the print at the first covering sweep
        not_swept   no sweep ran inside the print's 24 h carry window
        failure     the covering sweep logged a fetch failure for this wallet
        lag         the print only reached the feed after its 24 h window closed
        token_absent  no TRADE/BUY print exists on THIS LEG'S OWN TOKEN (the parent probe
                    matched the first event on the CONDITION, i.e. either token)
  3. Prices the miss: per-leg settlement, the wallet's own realised PnL, and what a copy would
     have been worth (nothing, when no print exists on the token).
  4. Measures the COPYABLE-side capture rate for the same wallet/window (venue prints on the
     token vs stored rows), which is the number the page cap would actually have to damage.
  5. Prices the page cap itself: daily TRADE-row volume (live venue probe), pages needed per
     24 h window vs 4, and the sweep-gap distribution that decides whether the cap can bind.

READ-ONLY: SQLite opened mode=ro, SELECT only; venue reads are GETs. No rule/gate/size change and
no change to the monitor's page size, lookback or dedupe.

RUN
  python3 scripts/monitor-miss-attribution.py                 # report off caches + DB + log
  python3 scripts/monitor-miss-attribution.py --fetch-volume  # + live per-day TRADE row counts
"""
from __future__ import annotations

import bisect
import importlib
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = Path(os.environ.get("COPYBOT_DB", str(ROOT / "prisma" / "dev.db")))
sys.path.insert(0, str(ROOT / "scripts"))
sec = importlib.import_module("seat-evidence-coverage")
nrm = sec.nrm
unpack = sec.unpack
iso = sec.iso
ts_parse = sec.ts_parse
load_truth = sec.load_truth

OUT = ROOT / "data" / "monitor-miss-attribution.json"
POS = ROOT / "data" / "wallet-seat-positions.json"
OPENP = ROOT / "data" / "seat-evidence-open-positions.json"
ACT = ROOT / "data" / "seat-evidence-activity.json"
LOG = ROOT / "logs" / "cron" / "copybot-monitor-score.log"

DATA_API = "https://data-api.polymarket.com"
UA = {"accept": "application/json", "user-agent": "copybot-research/0.1 (paper-trading-only)"}
MONITOR_HOURS = 24
PAGE_ROWS = 500      # src/lib/adapters/polymarket.ts fetchRecentTrades
PAGE_CAP = 4
SUBJECT = "0x17dd123a0ad9675e6ed3155724a92b4632af944c"  # luciebot
# Settlement basis for the reproduced probe. "oracle" is the parent's (CLOB closed flag first,
# wallet terminal mark as fallback); "mark" drops the oracle arm so the population is the wallet's
# own terminal marks only. Both are reported because the leg COUNT depends on it.
SETTLE_BASIS = "oracle"


def now_ms():
    return int(time.time() * 1000)


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


# ---------------------------------------------------------------- monitor log
RE_RUN = re.compile(r"^=== run (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}) ===")


def local_ts_to_ms(s):
    """`=== run` stamps are LOCAL wall clock; the DB stores epoch ms."""
    return int(datetime.strptime(s, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=None).timestamp() * 1000)


def read_runs(path=LOG):
    """Sweep starts from the cron log, plus the per-run completion/failure lines between them."""
    runs = []
    cur = None
    fail_re = re.compile(r"^Failures \((\d+)\):")
    with path.open("r", errors="replace") as fh:
        for line in fh:
            m = RE_RUN.match(line)
            if m:
                cur = {"start_ms": local_ts_to_ms(m.group(1)), "new_observed": None,
                       "failures": 0, "fail_lines": [], "failed_all": False}
                runs.append(cur)
                continue
            if cur is None:
                continue
            m = re.search(r"Trade monitor complete: (\d+) new observed trades", line)
            if m:
                cur["new_observed"] = int(m.group(1))
            m = fail_re.match(line)
            if m:
                cur["failures"] = int(m.group(1))
                cur["fail_lines"].append(line.strip()[:400])
            if "monitor:trades FAILED" in line or "All wallet activity fetches failed" in line:
                cur["failed_all"] = True
    return runs


# ---------------------------------------------------------------- DB
def load_rows(wallets):
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    con.row_factory = sqlite3.Row
    ph = ",".join("?" * len(wallets))
    out = defaultdict(list)
    for r in con.execute(
            "SELECT walletAddress, conditionId, marketId, marketQuestion, outcome, side, "
            "walletEntryPrice, detectedPrice, size, timestamp, createdAt, observationOnly "
            "FROM ObservedTrade WHERE isDemo=0 AND walletAddress IN (%s) ORDER BY timestamp" % ph,
            list(wallets)):
        out[r["walletAddress"]].append(dict(r))
    con.close()
    return out


def paper_decisions(market_ids):
    """Did the copy lane act on any of these markets? (read-only context, not part of the verdict)"""
    if not market_ids:
        return {}
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    con.row_factory = sqlite3.Row
    out = {}
    ph = ",".join("?" * len(market_ids))
    for r in con.execute(
            "SELECT marketId, COUNT(*) n, SUM(CASE WHEN decision='paper_copy' THEN 1 ELSE 0 END) copies "
            "FROM DecisionJournal WHERE marketId IN (%s) GROUP BY marketId" % ph, list(market_ids)):
        out[r["marketId"]] = {"journal": r["n"], "paper_copy": r["copies"] or 0}
    con.close()
    return out


# ---------------------------------------------------------------- parent probe (reproduced)
def key_state(vc, vo, truth, k, today):
    t = None if SETTLE_BASIS == "mark" else truth.get(k[0])
    if t and not t.get("error") and "closed" in t:
        return ("settled" if t.get("closed") else "open"), "oracle"
    r = vc.get(k)
    if r is not None:
        mark = sec.settle_price(r, today)
        if mark is not None and sec.end_passed(r.get("end_date"), today):
            return "settled", "mark"
        return "open", "mark_unsettled"
    if k in vo:
        return "open", "held"
    return "unknown", None


def probe_tokens(rows, cid, fe_s, want=None):
    """First activity row on `cid` (optionally on one token) at/after fe-120s."""
    for x in rows:
        if int(x.get("timestamp") or 0) < fe_s - 120:
            continue
        if want is not None and nrm(x.get("outcome")) != want:
            continue
        return x
    return None


def run_probe(seat_rows, vc_map, vo_map, truth, today, act_wallet):
    """Per-seat reproduction of the parent's activity probe, plus the token-matched arm."""
    a = act_wallet.get("address")
    rows_all = act_wallet.get("rows") or []
    by_cid = defaultdict(list)
    for r in rows_all:
        if r.get("condition_id"):
            by_cid[str(r["condition_id"])].append(r)
    for v in by_cid.values():
        v.sort(key=lambda r: int(r.get("timestamp") or 0))
    lo = int(ts_parse(act_wallet["window"][0]) / 1000)
    hi = int(ts_parse(act_wallet["window"][1]) / 1000)
    first = {}
    for r in seat_rows:
        if not r["conditionId"]:
            continue
        first.setdefault((r["conditionId"], nrm(r["outcome"])), r)
    vc, vo = vc_map, vo_map
    cts_all = sorted(r["createdAt"] for r in seat_rows)

    def swept_after(ts_ms):
        i = bisect.bisect_left(cts_all, ts_ms)
        return i < len(cts_all) and cts_all[i] <= ts_ms + MONITOR_HOURS * 3600000

    venue_settled = [k for k in vc if key_state(vc, vo, truth, k, today)[0] == "settled"]
    venue_unobs = [k for k in venue_settled if k not in first]
    res = {"in_window": 0, "no_print": 0, "missed": 0, "unwatched": 0,
           "tok_no_print": 0, "tok_missed": 0, "tok_unwatched": 0,
           "legs_missed": [], "legs_tok_missed": [], "labels_mismatch": 0}
    for k in venue_unobs:
        r = vc.get(k)
        fe = r.get("first_entry_at")
        try:
            fe_s = int(fe) if fe else None
        except (TypeError, ValueError):
            fe_s = None
        if fe_s is None or fe_s < lo or fe_s > hi:
            continue
        res["in_window"] += 1
        ev = probe_tokens(by_cid.get(k[0]) or [], k[0], fe_s)
        if ev is None:
            res["no_print"] += 1
        else:
            is_buy = str(ev.get("type")) == "TRADE" and str(ev.get("side")).upper() == "BUY"
            if not is_buy:
                res["no_print"] += 1
            elif swept_after(fe_s * 1000):
                res["missed"] += 1
                res["legs_missed"].append((k, fe_s, ev))
            else:
                res["unwatched"] += 1
        ev2 = probe_tokens(by_cid.get(k[0]) or [], k[0], fe_s, want=k[1])
        if ev2 is None:
            res["tok_no_print"] += 1
        else:
            is_buy2 = str(ev2.get("type")) == "TRADE" and str(ev2.get("side")).upper() == "BUY"
            if not is_buy2:
                res["tok_no_print"] += 1
            elif swept_after(fe_s * 1000):
                res["tok_missed"] += 1
                res["legs_tok_missed"].append((k, fe_s, ev2))
            else:
                res["tok_unwatched"] += 1
        # label-vocabulary check: does the leg's token label appear anywhere on this condition?
        labels = {nrm(x.get("outcome")) for x in (by_cid.get(k[0]) or [])}
        if k[1] not in labels:
            res["labels_mismatch"] += 1
    return res


# ---------------------------------------------------------------- attribution of one leg
def attribute_leg(cid, onrm, fe_s, print_ev, vc_row, stored, sweeps, act_by_cid, act_all=None):
    """Why is there no stored row for (cid, leg outcome)?"""
    pt = int(print_ev.get("timestamp") or 0)
    print_outcome = nrm(print_ev.get("outcome"))
    out = {
        "cid": cid, "leg_token": onrm, "print_ts": pt, "print_iso": iso(pt * 1000),
        "first_entry_at": fe_s, "print_outcome": print_outcome,
        "print_type": print_ev.get("type"), "print_side": print_ev.get("side"),
        "print_price": print_ev.get("price"), "print_size": print_ev.get("size"),
        "venue_outcome_label": vc_row.get("outcome"),
        "venue_total_size": vc_row.get("total_size"),
        "venue_avg_price": vc_row.get("avg_price"),
        "venue_current_price": vc_row.get("current_price"),
        "venue_realized_pnl": vc_row.get("realized_pnl"),
        "venue_end_date": vc_row.get("end_date"),
        "venue_slug": vc_row.get("slug"),
    }
    # --- (a) mask: is the leg's identity already stored?  mode=ro key, exact same shape the monitor uses
    same_token = [r for r in stored if r["conditionId"] == cid and nrm(r["outcome"]) == onrm]
    other_token = [r for r in stored if r["conditionId"] == cid and nrm(r["outcome"]) != onrm]
    out["stored_rows_same_token"] = len(same_token)
    out["stored_rows_other_token"] = len(other_token)
    out["stored_other_token_labels"] = sorted({r["outcome"] for r in other_token})[:6]
    out["stored_same_timestamp_other_token"] = sum(
        1 for r in other_token if int(r["timestamp"]) == pt * 1000)
    # --- the print the parent matched: is it even on the leg's token?
    out["print_on_leg_token"] = (print_outcome == onrm)
    # --- what, if anything, the venue ever printed ON THIS LEG'S OWN TOKEN
    rows_tok = [x for x in (act_by_cid.get(cid) or []) if nrm(x.get("outcome")) == onrm]
    types_tok = Counter(str(x.get("type")) + ("/" + str(x.get("side")).upper() if x.get("side") else "")
                        for x in rows_tok)
    out["own_token_rows"] = dict(types_tok)
    has_buy = any("TRADE/BUY" == k for k in types_tok)
    if has_buy:
        out["token_absent_kind"] = "buy_present"
    elif not rows_tok:
        out["token_absent_kind"] = "no_row"
    elif all(k.startswith("TRADE/SELL") for k in types_tok):
        out["token_absent_kind"] = "sell_only"
    elif all(not k.startswith("TRADE") for k in types_tok):
        out["token_absent_kind"] = "redeem_only"
    else:
        out["token_absent_kind"] = "other"
    # --- covering sweeps: start s with print inside [s-24h, s]  (the fetch window is (s-24h, s])
    covering = [s for s in sweeps if pt * 1000 + 1000 <= s["start_ms"] <= pt * 1000 + MONITOR_HOURS * 3600000]
    out["covering_sweeps"] = len(covering)
    if covering:
        s0 = covering[0]
        out["first_sweep_iso"] = iso(s0["start_ms"])
        out["first_sweep_lag_min"] = round((s0["start_ms"] - pt * 1000) / 60000.0, 1)
        out["first_sweep_failures"] = s0["failures"]
        out["first_sweep_failed_all"] = s0["failed_all"]
        # rank of the print in the newest-first feed at that sweep. The cap is WALLET-wide, so the
        # rank is every TRADE row of the wallet newer than the print, not just this condition's.
        src = act_all if act_all is not None else (act_by_cid.get(cid) or [])
        newer = [x for x in src
                 if str(x.get("type")) == "TRADE"
                 and pt * 1000 < int(x.get("timestamp") or 0) * 1000 <= s0["start_ms"]]
        out["rows_newer_at_first_sweep"] = len(newer)
        out["rows_newer_same_cid"] = sum(1 for x in (act_by_cid.get(cid) or [])
                                         if str(x.get("type")) == "TRADE"
                                         and pt * 1000 < int(x.get("timestamp") or 0) * 1000 <= s0["start_ms"])
        out["wallet_window_rows"] = sum(
            1 for x in src if str(x.get("type")) == "TRADE"
            and (s0["start_ms"] - MONITOR_HOURS * 3600000) <= int(x.get("timestamp") or 0) * 1000 <= s0["start_ms"])
    else:
        out["first_sweep_iso"] = None
        out["rows_newer_at_first_sweep"] = None
    # --- verdict
    if not out["print_on_leg_token"]:
        verdict = "token_absent"      # the BUY print the parent matched is on the OTHER token of the pair
    elif out["stored_rows_same_token"]:
        verdict = "mask"
    elif not covering:
        verdict = "not_swept"
    elif out["first_sweep_failed_all"] or out["first_sweep_failures"]:
        verdict = "failure"
    elif (out["rows_newer_at_first_sweep"] or 0) >= PAGE_ROWS * PAGE_CAP:
        verdict = "cap"
    elif not out["stored_rows_same_token"]:
        verdict = "lag"               # swept, no failure, inside the cap, still not on the tape we got
    else:
        verdict = "unexplained"
    out["verdict"] = verdict
    # --- price of the miss: settlement + what a copy would have been worth
    cp = vc_row.get("current_price")
    try:
        cp = float(cp) if cp is not None else None
    except (TypeError, ValueError):
        cp = None
    out["leg_won"] = (cp == 1.0) if cp is not None else None
    out["leg_settled"] = cp in (0.0, 1.0)
    # a copy is only placeable on a BUY print of this token
    out["copyable"] = bool(out["print_on_leg_token"] and str(print_ev.get("type")) == "TRADE"
                           and str(print_ev.get("side")).upper() == "BUY")
    return out


# ---------------------------------------------------------------- live volume probe
def fetch_trades_with_tokens(wallet, until_ms, max_pages=12):
    """The venue's own TRADE rows back to `until_ms`, newest-first, WITH token_id.

    The parent's activity cache dropped `token_id`, so its probe matched outcome TEXT. This read
    keeps the token identity, which is the only label-free way to ask "is this print on the leg's
    own token?".
    """
    acc, cur, pages = [], None, 0
    while pages < max_pages:
        url = "%s/v2/activity?user=%s&type=TRADE&limit=500" % (DATA_API, wallet)
        if cur:
            url += "&cursor=" + urllib.parse.quote(str(cur))
        p = get_json(url)
        if not isinstance(p, dict):
            break
        data = p.get("data") or []
        acc.extend(data)
        pages += 1
        cur = (p.get("pagination") or {}).get("next_cursor")
        ts = [int(x.get("timestamp") or 0) for x in data if x.get("timestamp")]
        if not cur or not data or (ts and min(ts) * 1000 < until_ms):
            break
        time.sleep(0.12)
    return acc, pages


def count_day_trades(wallet, day_start_s, max_pages=14):
    """Count TRADE rows in [day_start, day_start+24h] with the venue's own paging."""
    rows, pages = fetch_day_trades(wallet, day_start_s, max_pages=max_pages)
    return len(rows), pages


def fetch_day_trades(wallet, day_start_s, max_pages=14):
    """Every TRADE row the venue holds for [day_start, day_start+24h], with token_id."""
    acc, cur, pages = [], None, 0
    end = day_start_s + 86400
    while pages < max_pages:
        url = ("%s/v2/activity?user=%s&type=TRADE&limit=500&start=%d&end=%d"
               % (DATA_API, wallet, day_start_s, end))
        if cur:
            url += "&cursor=" + urllib.parse.quote(str(cur))
        p = get_json(url)
        if not isinstance(p, dict):
            break
        data = p.get("data") or []
        acc.extend(data)
        pages += 1
        cur = (p.get("pagination") or {}).get("next_cursor")
        if not cur or not data or len(data) < 500:
            break
        time.sleep(0.12)
    return acc, pages


# ---------------------------------------------------------------- main
def main():
    global SETTLE_BASIS
    argv = sys.argv[1:]
    fetch_volume = "--fetch-volume" in argv
    days = int(argv[argv.index("--days") + 1]) if "--days" in argv else 8
    if "--settlement" in argv:
        SETTLE_BASIS = argv[argv.index("--settlement") + 1]

    db = sec.load_db()
    seats = db["seats"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    pos_cache = json.loads(POS.read_text())
    open_cache = json.loads(OPENP.read_text())
    act_cache = json.loads(ACT.read_text())["wallets"]
    truth = load_truth()
    stored = load_rows([s["address"] for s in seats])
    sweeps = read_runs()

    # ---- 1. reproduce + token-matched arm, per seat
    per_seat = []
    tot = Counter()
    for s in seats:
        a = s["address"]
        aw = act_cache.get(a)
        if not aw:
            continue
        vc, vo = {}, {}
        for r in unpack(pos_cache.get(a) or {}):
            cid = r.get("condition_id")
            if not cid:
                continue
            k = (cid, nrm(r.get("outcome")))
            prev = vc.get(k)
            if prev is None or float(r.get("total_size") or 0) > float(prev.get("total_size") or 0):
                vc[k] = r
        for r in unpack(open_cache.get(a) or {}):
            if r.get("condition_id"):
                vo[(r["condition_id"], nrm(r.get("outcome")))] = r
        aw = dict(aw)
        aw["address"] = a
        r = run_probe(stored[a], vc, vo, truth, today, aw)
        r["label"] = s["label"]
        r["address"] = a
        r["legs_missed"] = None  # legs stay out of the per-seat record (key tuples only below)
        r["legs_tok_missed"] = None
        per_seat.append(r)
        for k in ("in_window", "no_print", "missed", "unwatched", "tok_no_print", "tok_missed",
                  "tok_unwatched", "labels_mismatch"):
            tot[k] += r[k]
    print("=== 1. probe reproduction (parent basis) vs token-matched basis")
    print('%-24s %7s %7s %7s %7s | %9s %8s %9s | %s' %
          ("seat", "inwin", "noPr", "miss", "unwt", "tok_noPr", "tok_miss", "tok_unwt", "lbl-mis"))
    for r in sorted(per_seat, key=lambda x: -x["in_window"]):
        print('%-24s %7d %7d %7d %7d | %9d %8d %9d | %d' %
              (r["label"][:24], r["in_window"], r["no_print"], r["missed"], r["unwatched"],
               r["tok_no_print"], r["tok_missed"], r["tok_unwatched"], r["labels_mismatch"]))
    print('%-24s %7d %7d %7d %7d | %9d %8d %9d | %d' % ("TOTAL", tot["in_window"], tot["no_print"],
          tot["missed"], tot["unwatched"], tot["tok_no_print"], tot["tok_missed"],
          tot["tok_unwatched"], tot["labels_mismatch"]))
    print("reproduces parent 3,218/961/2,173/84:",
          (tot["in_window"], tot["no_print"], tot["unwatched"], tot["missed"]) == (3218, 961, 2173, 84))

    # ---- 2. attribute the subject's missed legs
    subj = next(s for s in seats if s["address"] == SUBJECT)
    aw = dict(act_cache[SUBJECT])
    aw["address"] = SUBJECT
    vc = {}
    for r in unpack(pos_cache.get(SUBJECT) or {}):
        cid = r.get("condition_id")
        if not cid:
            continue
        k = (cid, nrm(r.get("outcome")))
        prev = vc.get(k)
        if prev is None or float(r.get("total_size") or 0) > float(prev.get("total_size") or 0):
            vc[k] = r
    vo = {(r["condition_id"], nrm(r.get("outcome"))): r
          for r in unpack(open_cache.get(SUBJECT) or {}) if r.get("condition_id")}
    r = run_probe(stored[SUBJECT], vc, vo, truth, today, aw)
    lo = int(ts_parse(aw["window"][0]) / 1000)
    hi = int(ts_parse(aw["window"][1]) / 1000)
    act_by_cid = defaultdict(list)
    for x in aw["rows"]:
        if x.get("condition_id"):
            act_by_cid[str(x["condition_id"])].append(x)
    for v in act_by_cid.values():
        v.sort(key=lambda x: int(x.get("timestamp") or 0))

    legs = []
    for k, fe_s, ev in r["legs_missed"]:
        legs.append(attribute_leg(k[0], k[1], fe_s, ev, vc[k], stored[SUBJECT], sweeps,
                                  act_by_cid, act_all=aw["rows"]))
    verdicts = Counter(x["verdict"] for x in legs)
    print("\n=== 2. the %d print-present legs the parent counted as instrument misses" % len(legs))
    print("verdicts:", dict(verdicts))
    print("what the venue printed on each leg's OWN token:", dict(Counter(
        x["token_absent_kind"] for x in legs)))
    print("print token vs leg token:", Counter(
        ("same" if x["print_on_leg_token"] else "OTHER (%s print, %s leg)" % (x["print_outcome"], x["leg_token"]))
        for x in legs))
    print("leg token label:", Counter(x["leg_token"] for x in legs),
          "| print token label:", Counter(x["print_outcome"] for x in legs))
    print("stored rows on the leg's own token:", sum(x["stored_rows_same_token"] for x in legs))
    print("stored rows on the OTHER token of the same condition:",
          sum(x["stored_rows_other_token"] for x in legs),
          "of which at the print's exact second:",
          sum(x["stored_same_timestamp_other_token"] for x in legs))
    print("covering sweeps (median):",
          sorted(x["covering_sweeps"] for x in legs)[len(legs) // 2] if legs else 0,
          "| first-sweep lag min (median):",
          sorted(x["first_sweep_lag_min"] for x in legs if x["first_sweep_lag_min"] is not None)[len(legs) // 2] if legs else 0)
    print("rows newer than the print at the first covering sweep: max =",
          max((x["rows_newer_at_first_sweep"] or 0) for x in legs) if legs else 0,
          "(wallet-wide) vs cap", PAGE_ROWS * PAGE_CAP,
          "| same condition only, max =",
          max((x.get("rows_newer_same_cid") or 0) for x in legs) if legs else 0)
    win_rows = [x.get("wallet_window_rows") for x in legs if x.get("wallet_window_rows")]
    if win_rows:
        win_rows.sort()
        print("24 h TRADE rows the covering sweep had to page: p50=%d max=%d (cap %d)"
              % (win_rows[len(win_rows) // 2], win_rows[-1], PAGE_ROWS * PAGE_CAP))
    print("sweeps with any logged failure in the window:",
          sum(1 for s in sweeps if s["failures"] and
              min(x["print_ts"] for x in legs) * 1000 <= s["start_ms"] <= (max(x["print_ts"] for x in legs) + 86400) * 1000)
          if legs else 0)
    won = Counter(x["leg_won"] for x in legs)
    pnl = sum(float(x["venue_realized_pnl"] or 0) for x in legs)
    print("leg settlement (venue mark terminal): won=%d lost=%d unsettled=%d | wallet realised PnL on them: %.4f"
          % (won[True], won[False], won[None], pnl))
    print("legs with a placeable BUY print on their own token:", sum(1 for x in legs if x["copyable"]))

    # ---- 2b. token-identity validation of the verdict (label-free)
    tok_rows, tok_pages = ([], 0)
    if "--fetch-tokens" in argv:
        tok_rows, tok_pages = fetch_trades_with_tokens(SUBJECT, lo * 1000)
        print("token-identity read: %d TRADE rows / %d pages back to %s"
              % (len(tok_rows), tok_pages, aw["window"][0]))
    tok_by_id = defaultdict(list)
    for x in tok_rows:
        if x.get("token_id"):
            tok_by_id[str(x["token_id"])].append(x)
    if tok_rows:
        hits = token_buys = 0
        sell_only_legs = 0
        for x in legs:
            tid = str((vc[(x["cid"], x["leg_token"])] or {}).get("token_id") or "")
            rows_tid = tok_by_id.get(tid) or []
            if rows_tid:
                hits += 1
            buys = sum(1 for y in rows_tid if str(y.get("side")).upper() == "BUY")
            token_buys += buys
            x["venue_token_id"] = tid
            x["token_rows_on_venue"] = len(rows_tid)
            if rows_tid and buys == 0:
                sell_only_legs += 1
        # control: the OTHER token of the same conditions must be where the prints live
        ctrl = []
        for x in legs:
            for (cid2, onrm2), r2 in vc.items():
                if cid2 == x["cid"] and onrm2 != x["leg_token"]:
                    ctrl.append(len(tok_by_id.get(str(r2.get("token_id") or "")) or []))
                    break
        print("token check: legs whose own token has ANY venue TRADE row: %d/%d | BUY prints on those tokens: %d"
              % (hits, len(legs), token_buys))
        print("control: the paired token of the same %d conditions carries %d TRADE rows (median %d)"
              % (len(ctrl), sum(ctrl), sorted(ctrl)[len(ctrl) // 2] if ctrl else 0))

        # 2c. a leg whose own token carries SELL prints only is an EXIT, not a missed entry:
        # ObservedTrade stores copy ENTRIES only, and SELLs go to the append-only sidecar by design
        # (src/lib/sell-log.ts). Prove those prints were kept rather than dropped.
        slug_by_cid = {}
        for r in stored[SUBJECT]:
            if r["conditionId"] and r["marketId"]:
                slug_by_cid[r["conditionId"]] = r["marketId"]
        want = {(slug_by_cid[x["cid"]], x["leg_token"]): x for x in legs if x["cid"] in slug_by_cid}
        sell_hits = defaultdict(int)
        sell_path = ROOT / "data" / "wallet-sells.jsonl"
        if sell_path.exists():
            with sell_path.open("r", errors="replace") as fh:
                for line in fh:
                    if SUBJECT not in line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:  # noqa: BLE001
                        continue
                    k = (str(rec.get("marketId")), nrm(rec.get("outcome")))
                    if k in want and str(rec.get("side")).upper() == "SELL":
                        sell_hits[k] += 1
        print("EXIT check: %d of %d legs have SELL-only prints on their own token; %d of those have the "
              "print kept in data/wallet-sells.jsonl (%d lines) — a SELL is not a copyable entry"
              % (sell_only_legs, len(legs), len(sell_hits), sum(sell_hits.values())))
        for x in legs:
            k = (slug_by_cid.get(x["cid"]), x["leg_token"])
            x["sell_prints_kept"] = sell_hits.get(k, 0)

    # ---- 3. copyable-side capture rate for the subject inside the activity window
    venue_buys = {}
    for x in aw["rows"]:
        if str(x.get("type")) != "TRADE" or str(x.get("side")).upper() != "BUY":
            continue
        t = int(x.get("timestamp") or 0)
        if not (lo <= t <= hi):
            continue
        venue_buys[(str(x.get("condition_id")), nrm(x.get("outcome")), t)] = x
    db_keys = {(r["conditionId"], nrm(r["outcome"]), int(r["timestamp"]) // 1000)
               for r in stored[SUBJECT] if r["conditionId"]}
    matched = sum(1 for k in venue_buys if k in db_keys)
    missing = [k for k in venue_buys if k not in db_keys]
    print("\n=== 3. copyable-side capture, %s .. %s" % (aw["window"][0], aw["window"][1]))
    print("venue BUY prints (distinct cid/token/second): %d | stored: %d | absent: %d (%.2f%%)"
          % (len(venue_buys), matched, len(missing), 100.0 * len(missing) / max(1, len(venue_buys))))
    miss_outcome = Counter(k[1] for k in missing)
    print("absent prints by token label:", dict(miss_outcome.most_common(6)))
    # rank/timing of the absent prints: was a sweep covering them?
    sw_starts = [s["start_ms"] for s in sweeps]
    rank_absent = []
    not_covered = 0
    for k in missing:
        pt_ms = k[2] * 1000
        i = bisect.bisect_left(sw_starts, pt_ms)
        if i >= len(sw_starts) or sw_starts[i] > pt_ms + MONITOR_HOURS * 3600000:
            not_covered += 1
            continue
        s0 = sw_starts[i]
        rank_absent.append(sum(1 for kk in venue_buys if pt_ms < kk[2] * 1000 <= s0))
    rank_absent.sort()
    print("absent prints: no covering sweep = %d | rank-at-first-sweep p50=%s p95=%s max=%s (cap %d)"
          % (not_covered,
             rank_absent[len(rank_absent) // 2] if rank_absent else None,
             rank_absent[int(len(rank_absent) * 0.95)] if rank_absent else None,
             rank_absent[-1] if rank_absent else None, PAGE_ROWS * PAGE_CAP))

    # ---- 4. page-cap pricing
    print("\n=== 4. page cap (4 x 500 = %d rows/wallet/sweep)" % (PAGE_ROWS * PAGE_CAP))
    # 4a. rank of the newest print at each sweep = how deep the monitor must page in steady state
    in_win = [s for s in sweeps if lo * 1000 <= s["start_ms"] <= hi * 1000]
    depth = []
    for s in in_win:
        s0 = s["start_ms"]
        depth.append(sum(1 for x in aw["rows"]
                         if str(x.get("type")) == "TRADE"
                         and (s0 - MONITOR_HOURS * 3600000) <= int(x.get("timestamp") or 0) * 1000 <= s0))
    depth.sort()
    if depth:
        print("24 h TRADE rows the sweep must page, measured on %d sweeps inside the cache window: "
              "p50=%d p95=%d max=%d | pages needed p50=%.1f max=%.1f of %d"
              % (len(depth), depth[len(depth) // 2], depth[int(len(depth) * 0.95)], depth[-1],
                 depth[len(depth) // 2] / 500.0, depth[-1] / 500.0, PAGE_CAP))
    gaps = [(sweeps[i + 1]["start_ms"] - sweeps[i]["start_ms"]) / 60000.0 for i in range(len(sweeps) - 1)]
    win_gaps = sorted(g for i, g in enumerate(gaps)
                      if min(x["print_ts"] for x in legs) * 1000 <= sweeps[i]["start_ms"] <= (max(x["print_ts"] for x in legs) + 86400) * 1000) if legs else []
    if win_gaps:
        print("sweep gaps across the card's window: p50=%.1f p95=%.1f max=%.1f min"
              % (win_gaps[len(win_gaps) // 2], win_gaps[int(len(win_gaps) * 0.95)], win_gaps[-1]))
    # 4b. live per-day volume
    day_rows = []
    if fetch_volume:
        now_s = int(time.time())
        midnight = now_s - (now_s % 86400)
        for d in range(1, days + 1):
            s0 = midnight - d * 86400
            n, pages = count_day_trades(SUBJECT, s0)
            day_rows.append({"day": iso(s0 * 1000)[:10], "trade_rows": n, "pages": pages,
                             "pages_needed_at_500": round(n / 500.0, 2)})
            print("  %s TRADE rows %5d (pages read %d, needs %.1f of 4)"
                  % (iso(s0 * 1000)[:10], n, pages, n / 500.0))
    if day_rows:
        mx = max(day_rows, key=lambda x: x["trade_rows"])
        print("max 24 h TRADE volume in the last %d days: %d rows on %s = %.1f pages of 500 (cap 2,000)"
              % (days, mx["trade_rows"], mx["day"], mx["pages_needed_at_500"]))

    # 4c. did the cap actually drop prints on a saturating day? (measure the burst day directly)
    day_arg = argv[argv.index("--day") + 1] if "--day" in argv else None
    day_capture = None
    if day_arg:
        d0 = int(datetime.strptime(day_arg, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
        vrows, vpages = fetch_day_trades(SUBJECT, d0)
        vbuys = {}
        for x in vrows:
            if str(x.get("side")).upper() == "BUY":
                vbuys[(str(x.get("condition_id")), str(x.get("token_id")),
                       int(x.get("timestamp") or 0))] = x
        # stored rows carry no token_id, so match on (conditionId, outcome identity, second)
        dbk = {(r["conditionId"], nrm(r["outcome"]), int(r["timestamp"]) // 1000)
               for r in stored[SUBJECT]}
        vlab = {(str(x.get("condition_id")), nrm(x.get("outcome")), int(x.get("timestamp") or 0))
                for x in vrows if str(x.get("side")).upper() == "BUY"}
        absent = sorted(k for k in vlab if k not in dbk)
        sw = [s["start_ms"] for s in sweeps]
        ranks, nocover = [], 0
        for k in absent:
            pt_ms = k[2] * 1000
            i = bisect.bisect_left(sw, pt_ms)
            if i >= len(sw) or sw[i] > pt_ms + MONITOR_HOURS * 3600000:
                nocover += 1
                continue
            ranks.append(sum(1 for x in vrows
                             if str(x.get("side")).upper() == "BUY"
                             and pt_ms < int(x.get("timestamp") or 0) * 1000 <= sw[i]))
        ranks.sort()
        day_capture = {"day": day_arg, "venue_trade_rows": len(vrows), "pages_read": vpages,
                       "venue_buy_prints_distinct": len(vbuys),
                       "absent_from_db": len(absent), "no_covering_sweep": nocover,
                       "rank_at_first_sweep": {"p50": ranks[len(ranks) // 2] if ranks else None,
                                               "max": ranks[-1] if ranks else None}}
        print("day capture %s: venue TRADE rows %d (%d pages), distinct BUY prints %d, absent from DB %d "
              "(no covering sweep %d) | rank at first sweep p50=%s max=%s (cap %d)"
              % (day_arg, len(vrows), vpages, len(vbuys), len(absent), nocover,
                 day_capture["rank_at_first_sweep"]["p50"], day_capture["rank_at_first_sweep"]["max"],
                 PAGE_ROWS * PAGE_CAP))

    # ---- 5. settlement / price summary of the missed legs
    print("\n=== 5. what the miss cost")
    print("placeable copies forgone: %d | settled outcome mix: %s | wallet PnL on the legs: %.4f"
          % (sum(1 for x in legs if x["copyable"]), dict(Counter(
              "won" if x["leg_won"] else ("lost" if x["leg_won"] is False else "unsettled") for x in legs)), pnl))
    # the OTHER token of the same conditions: did the copy lane act on those markets?
    cids = sorted({x["cid"] for x in legs})
    # the leg rows are the token the venue reports, which for these markets carries no slug; the
    # counterpart rows we DID store carry the marketId (slug) the copy lane keys on.
    slugs = sorted({r["marketId"] for r in stored[SUBJECT]
                    if r["conditionId"] in set(cids) and r["marketId"]})
    dec = paper_decisions(slugs or cids)
    print("of the %d conditions (%d slugs recovered from the stored counterpart rows), "
          "markets with a journal row: %d, with a paper_copy: %d"
          % (len(cids), len(slugs), sum(1 for v in dec.values() if v["journal"]),
             sum(1 for v in dec.values() if v["paper_copy"])))

    OUT.write_text(json.dumps({
        "generated_at": iso(now_ms()),
        "instrument": "scripts/monitor-miss-attribution.py",
        "lane": "B - read-only measurement (no rule/gate/size/tracking change)",
        "subject": SUBJECT,
        "settle_basis": SETTLE_BASIS,
        "reproduction": {"parent_basis": {"in_window": tot["in_window"], "no_print": tot["no_print"],
                                          "missed": tot["missed"], "unwatched": tot["unwatched"]},
                         "token_matched": {"no_print": tot["tok_no_print"], "missed": tot["tok_missed"],
                                           "unwatched": tot["tok_unwatched"]},
                         "matches_parent_3218_961_2173_84":
                             (tot["in_window"], tot["no_print"], tot["unwatched"], tot["missed"]) == (3218, 961, 2173, 84)},
        "per_seat": per_seat,
        "legs": legs,
        "leg_verdicts": dict(verdicts),
        "subject_activity_window": aw["window"],
        "page_cap": {"rows_per_page": PAGE_ROWS, "pages": PAGE_CAP, "cap_rows": PAGE_ROWS * PAGE_CAP,
                     "window_depth_in_cache": {"p50": depth[len(depth) // 2] if depth else None,
                                               "p95": depth[int(len(depth) * 0.95)] if depth else None,
                                               "max": depth[-1] if depth else None},
                     "daily_volume": day_rows, "day_capture": day_capture},
        "constants": {"MONITOR_HOURS": MONITOR_HOURS},
    }, indent=1))
    print("\nwrote %s" % OUT)


if __name__ == "__main__":
    main()
