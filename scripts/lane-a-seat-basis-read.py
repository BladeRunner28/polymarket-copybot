#!/usr/bin/env python3
"""lane-a-seat-basis-read.py — card t_b98c4591, Lane-A proposal instrument (READ-ONLY).

WHY
  The copy universe (25 `track` seats) is scored from the adapter's 100-row PROFILING TAIL
  SAMPLE (50 best + 50 worst closed positions + 100 open), not from the wallet's record.
  Wallet 0x17dd123a… bought a seat on that basis (stored roi30d 1.6333 = the sample's 1.6479)
  while its full venue record reads +17.5% and the band it feeds our cohort loses money.
  This instrument prices the two proposed repairs on the SAME population the scan sees:

    (A) ROI basis  — score roi30d on the wallet's whole closed-position record, and
                     de-saturate the ROI term (clamp(40+90*roi) pins every roi>=0.67 at 100).
    (B) Floor      — a seat requires >=30 venue-SETTLED legs whose ROI CI excludes zero
                     on the positive side, measured on the band a copier would actually hold.

WHAT IT MEASURES
  1. venue records    — full CLOSED position walk for all 25 seats (+ a bounded challenger
                        pool of non-demo `watch` wallets that out-score the 25th seat), with
                        the fields settlement needs (current_price, end_date, condition_id).
  2. basis counterfactual — seat-by-seat before/after for (A), per curve variant.
  3. floor            — settled-leg ROI + market-clustered bootstrap CI per wallet, per SCOPE
                        (all settled legs / rich band >=0.95 / copyable band >=0.80), pass/fail.
  4. composition      — the 25-seat set under (A), (B), (A+B) vs today; vacated seats; the
                        challenger pool that would fill them.
  5. replay           — 7-day journal admissions attributable to wallets each option drops
                        (measured) and the observed flow of wallets each option promotes.
  6. turnover         — copy-eligible flips over 30d from ObservedTrade.observationOnly, plus
                        the scan-rotation lag (a basis fix lands only when a wallet is re-scanned).
  7. refusal test     — re-cut of the subject's flood-window legs at TODAY's settlement state.

SETTLEMENT BASIS (per position/token, no dependence on our label cache)
  settled  = position status CLOSED, end_date < now, and the venue's current_price on that
             token is terminal (0 or 1 within 0.005).
  primary  = HOLD-TO-SETTLEMENT: pnl = size*(settle - avg_price), cost = size*avg_price —
             what a copier who holds to resolution would earn on that entry.
  secondary= venue realized_pnl on the same settled rows (what the wallet actually booked,
             including any early exit).

READ-ONLY on prisma/dev.db (SELECT only). Keyless venue reads (data-api v2 positions).
Writes data/wallet-seat-positions.json (raw cache, gitignored) and
       data/lane-a-seat-basis-read.json (committed read artifact).

Run: python3 scripts/lane-a-seat-basis-read.py [--fetch-venue] [--boot 3000]
     [--candidates N] [--candidate-pages P] [--refetch]
Without --fetch-venue the cache in data/ is used.
"""
from __future__ import annotations

import json
import math
import os
import random
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
OUT = ROOT / "data" / "lane-a-seat-basis-read.json"
POS = ROOT / "data" / "wallet-seat-positions.json"

W_SUBJECT = "0x17dd123a0ad9675e6ed3155724a92b4632af944c"
DATA_API = "https://data-api.polymarket.com"
UA = {"accept": "application/json", "user-agent": "copybot-research/0.1 (paper-trading-only)"}
SETTLE_TOL = 0.005
MAX_TRACKED = 25
FLOOD_CUT_MS = 1793979610 * 1000  # 2026-11-06T15:40:10Z (first journaled decision)
RICH_BAND = 0.95
COPY_BAND = 0.80
MIN_SETTLED_LEGS = 30
SEED = 17

# fields kept in the raw cache (parallel arrays). Everything the analysis needs, nothing else.
FIELDS = ["condition_id", "token_id", "outcome", "total_size", "avg_price", "realized_pnl",
          "current_price", "end_date", "redeemable", "first_entry_at", "last_event_at"]


# ---------------------------------------------------------------- helpers
def now_ms():
    return int(time.time() * 1000)


def nrm(v):
    return re.sub(r"[^a-z0-9]", "", str(v or "").lower())


def iso(ms):
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000.0, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_json(url, tries=5):
    for a in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                return json.loads(r.read().decode())
        except Exception:  # noqa: BLE001
            if a == tries - 1:
                return None
            time.sleep(1.5 * (a + 1))
    return None


def walk_closed(wallet, max_pages=300):
    """Full CLOSED position walk, cursor-paged, de-duplicated on token_id."""
    cur, out, pages, seen = None, [], 0, set()
    while pages < max_pages:
        url = ("%s/v2/positions?user=%s&status=CLOSED&limit=50&sort_by=REALIZED_PNL&sort_direction=DESC"
               % (DATA_API, wallet))
        if cur:
            url += "&cursor=" + urllib.parse.quote(cur)
        j = get_json(url)
        if j is None:
            return out, pages, "error"
        rows = (j or {}).get("data") or []
        for r in rows:
            k = r.get("token_id")
            if k in seen:
                continue
            seen.add(k)
            out.append([r.get(f) for f in FIELDS])
        cur = ((j or {}).get("pagination") or {}).get("next_cursor")
        pages += 1
        if not cur or not rows:
            return out, pages, "done"
        time.sleep(0.08)
    return out, pages, "capped"


def cluster_boot(clusters, n_boot=3000, seed=SEED):
    """ROI = sum(pnl)/sum(cost), resampling whole markets (condition_id) with replacement.
    numpy when available (a 32k-cluster wallet is 0.6s there, minutes in pure python)."""
    keys = list(clusters)
    if not keys:
        return None, None
    pnl = [clusters[k][0] for k in keys]
    cost = [clusters[k][1] for k in keys]
    n = len(keys)
    out = []
    try:
        import numpy as np  # noqa: PLC0415
        rng = np.random.default_rng(seed)
        pa = np.asarray(pnl, dtype="float64")
        ca = np.asarray(cost, dtype="float64")
        out = []
        for _ in range(n_boot):
            idx = rng.integers(0, n, n)
            c = ca[idx].sum()
            if c > 0:
                out.append(float(pa[idx].sum()) / float(c))
    except Exception:  # noqa: BLE001
        rng = random.Random(seed)
        out = []
        for _ in range(n_boot):
            p = c = 0.0
            for _ in range(n):
                k = rng.randrange(n)
                p += pnl[k]
                c += cost[k]
            if c > 0:
                out.append(p / c)
    if not out:
        return None, None
    out.sort()
    return out[int(0.025 * len(out))], out[int(0.975 * len(out)) - 1]


def arm(legs, n_boot):
    """legs: list of (cluster_key, cost, pnl)."""
    cost = sum(x[1] for x in legs)
    pnl = sum(x[2] for x in legs)
    cl = defaultdict(lambda: [0.0, 0.0])
    for k, c, p in legs:
        cl[k][0] += p
        cl[k][1] += c
    lo, hi = cluster_boot(cl, n_boot)
    return {
        "n_legs": len(legs),
        "n_clusters": len(cl),
        "cost": round(cost, 2),
        "pnl": round(pnl, 2),
        "roi": (pnl / cost) if cost else None,
        "roi_ci": [lo, hi],
        "win_rate": (sum(1 for x in legs if x[2] > 0) / len(legs)) if legs else None,
    }


# ---------------------------------------------------------------- scoring curves
def clamp(v, lo=0.0, hi=100.0):
    return min(hi, max(lo, v))


CURVES = {
    # shipped: 40 + 90*roi, clamped — pins every roi >= 0.67 at 100
    "linear_clamp": lambda roi: clamp(40 + 90 * roi),
    # Michaelis-Menten: same 90/unit slope at roi=0, asymptote 100, half-saturation at roi=2
    "michaelis": lambda roi: clamp(40 + 90 * roi / (1 + roi / 2.0)),
    # atan: slope 90/unit at roi=0, asymptote 100, no flat region anywhere
    "atan": lambda roi: clamp(40 + (60.0 * 2.0 / math.pi) * math.atan(math.pi * roi / 2.0)),
}


def global_from(roi, cons, copy, penalty, resolved, rules, curve="linear_clamp"):
    """globalScore with the ROI term read on `curve`. cons/copy/penalty are held at their
    STORED values (they come from the 30d activity sample, which this card does not touch)."""
    fn = CURVES[curve]
    roi_score = fn(roi if roi is not None else 0.0)
    g = roi_score * rules["weightRoi"] + cons * rules["weightConsistency"] + copy * rules["weightCopyability"]
    g = g * (1 - (penalty / 100.0) * 0.6)
    if resolved < rules["minResolvedTrades"]:
        g = min(g, 40.0)
    return round(clamp(g), 1), round(roi_score, 1)


# ---------------------------------------------------------------- position maths
def pos_cost(r):
    return float(r.get("total_size") or 0) * float(r.get("avg_price") or 0)


def pos_pnl(r):
    return float(r.get("realized_pnl") or 0)


def band_of(p):
    for lo, hi in [(0, 0.05), (0.05, 0.20), (0.20, 0.40), (0.40, 0.60), (0.60, 0.80),
                   (0.80, 0.95), (0.95, 1.01)]:
        if lo <= p < hi:
            return "%.2f-%.2f" % (lo, hi)
    return "other"


def settle_price(r, today):
    """Terminal venue mark for this position's token, or None if not settled yet."""
    ed = r.get("end_date")
    if not ed or str(ed)[:10] >= today:
        return None
    cp = r.get("current_price")
    try:
        cp = float(cp)
    except (TypeError, ValueError):
        return None
    if abs(cp - round(cp)) > SETTLE_TOL:
        return None
    return round(cp)


def wallet_record(rows, today, n_boot):
    """Everything the two options price, for one wallet's CLOSED position walk."""
    n = len(rows)
    all_legs = [(r.get("condition_id") or "?", pos_cost(r), pos_pnl(r)) for r in rows]
    full = arm(all_legs, n_boot) if rows else None
    # full-record ROI can be dominated by one absurd leg; keep the cost weighted read only.

    settled_rows, unsettled, early_cost, settled_cost = [], 0, 0.0, 0.0
    for r in rows:
        sp = settle_price(r, today)
        if sp is None:
            unsettled += 1
            continue
        settled_rows.append((r, sp))
        c = pos_cost(r)
        settled_cost += c
        # an early exit means realized PnL, not the terminal payoff, is what the wallet booked;
        # hold-to-settlement still prices what a copier who HOLDS would earn, but the gap matters.
        lea = (r.get("last_event_at") or 0) * 1000
        end_ms = None
        try:
            end_ms = int(datetime.strptime(str(r.get("end_date"))[:10], "%Y-%m-%d")
                         .replace(tzinfo=timezone.utc).timestamp() * 1000)
        except Exception:  # noqa: BLE001
            end_ms = None
        if end_ms and lea and lea < end_ms - 86400 * 1000:
            early_cost += c

    def legs_for(pred):
        out = []
        for r, sp in settled_rows:
            p = float(r.get("avg_price") or 0)
            if not pred(p):
                continue
            size = float(r.get("total_size") or 0)
            cost = size * p
            out.append((r.get("condition_id") or "?", cost, size * (sp - p)))
        return out

    hold_all = arm(legs_for(lambda p: True), n_boot)
    hold_rich = arm(legs_for(lambda p: p >= RICH_BAND), n_boot)
    hold_copy = arm(legs_for(lambda p: p >= COPY_BAND), n_boot)
    # realized basis on the same settled rows (what the wallet actually booked, exits included)
    real_all = arm([(r.get("condition_id") or "?", pos_cost(r), pos_pnl(r)) for r, _ in settled_rows], n_boot)
    real_rich = arm([(r.get("condition_id") or "?", pos_cost(r), pos_pnl(r))
                     for r, _ in settled_rows if float(r.get("avg_price") or 0) >= RICH_BAND], n_boot)
    real_copy = arm([(r.get("condition_id") or "?", pos_cost(r), pos_pnl(r))
                     for r, _ in settled_rows if float(r.get("avg_price") or 0) >= COPY_BAND], n_boot)

    bands = {}
    for r, sp in settled_rows:
        p = float(r.get("avg_price") or 0)
        size = float(r.get("total_size") or 0)
        b = bands.setdefault(band_of(p), [0.0, 0.0, 0, 0, 0.0])
        b[0] += size * p
        b[1] += size * (sp - p)
        b[2] += 1
        b[3] += 1 if sp > p else 0
        b[4] += pos_pnl(r)
    band_out = {}
    for k, v in sorted(bands.items()):
        band_out[k] = {"cost": round(v[0], 2), "hold_pnl": round(v[1], 2),
                       "hold_roi": (v[1] / v[0]) if v[0] else None,
                       "realized_pnl": round(v[4], 2),
                       "realized_roi": (v[4] / v[0]) if v[0] else None,
                       "legs": v[2], "wins": v[3]}

    return {
        "n_positions": n,
        "n_settled": len(settled_rows),
        "n_unsettled": unsettled,
        "settled_cost": round(settled_cost, 2),
        "early_exit_cost_share": round(early_cost / settled_cost, 4) if settled_cost else None,
        "full_record": full,
        "hold_all": hold_all,
        "hold_rich_095": hold_rich,
        "hold_copy_080": hold_copy,
        "realized_on_settled": real_all,
        "realized_rich_095": real_rich,
        "realized_copy_080": real_copy,
        "settled_bands": band_out,
        "position_median_cost": (sorted(pos_cost(r) for r in rows)[n // 2] if n else None),
    }


def observed_legs(obs_rows, oracle, n_boot):
    """The legs this bot could actually have copied from a wallet.

    For every (market, outcome) key the wallet was seen trading, keep the FIRST observation —
    that is the moment a copy would have been placed — and settle it at the venue's terminal
    price for that token (oracle, built from the wallet's own closed positions). Two entry
    bases (the wallet's own price, our detected mid) and two windows (all observed history,
    the flood window only) so the read can be reconciled with the upstream card's arms.
    """
    seen = set()
    keys = []
    for r in obs_rows:
        k = (r["conditionId"], nrm(r["outcome"]))
        if k in seen or not r["conditionId"]:
            continue
        seen.add(k)
        keys.append(r)

    def legs_for(subset):
        out = {"wallet_entry": [], "detected_mid": []}
        for r in subset:
            sp = oracle.get((r["conditionId"], nrm(r["outcome"])))
            if sp is None:
                continue
            size = float(r["size"] or 0)
            we = float(r["walletEntryPrice"] or 0)
            dm = float(r["detectedPrice"] or 0)
            if we > 0:
                out["wallet_entry"].append((r["conditionId"], size * we, size * (sp - we)))
            if dm > 0:
                out["detected_mid"].append((r["conditionId"], size * dm, size * (sp - dm)))
        return out

    def pack(subset, label):
        a = legs_for(subset)
        return {"label": label,
                "n_keys_observed": len(subset),
                "n_keys_settled": len(a["wallet_entry"]),
                "at_wallet_entry": arm(a["wallet_entry"], n_boot),
                "at_detected_mid": arm(a["detected_mid"], n_boot)}

    flood = [r for r in keys if (r["timestamp"] or 0) >= FLOOD_CUT_MS]
    pre = [r for r in keys if (r["timestamp"] or 0) < FLOOD_CUT_MS]
    out = pack(keys, "all_observed")
    out["flood_window"] = pack(flood, "flood_window")
    out["pre_flood"] = pack(pre, "pre_flood")
    return out


def floor_verdict(a, scope):
    """(pass, reason) for the admissibility floor on one scope arm."""
    if not a or a["n_legs"] < MIN_SETTLED_LEGS:
        return False, "insufficient settled legs (%d<%d)" % (a["n_legs"] if a else 0, MIN_SETTLED_LEGS)
    lo, hi = a["roi_ci"]
    if lo is None:
        return False, "no CI"
    if lo > 0:
        return True, "CI lower bound %+.2f%%>0" % (lo * 100)
    return False, "CI [%+.2f%%,%+.2f%%] does not exclude 0" % (lo * 100, hi * 100)


# ---------------------------------------------------------------- main
def main():
    argv = sys.argv[1:]
    fetch = "--fetch-venue" in argv
    refetch = "--refetch" in argv
    n_boot = int(argv[argv.index("--boot") + 1]) if "--boot" in argv else 3000
    n_cand = int(argv[argv.index("--candidates") + 1]) if "--candidates" in argv else 20
    cand_pages = int(argv[argv.index("--candidate-pages") + 1]) if "--candidate-pages" in argv else 80
    non_demo = "isDemo=0"

    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    con.row_factory = sqlite3.Row
    rules = json.loads(con.execute(
        "SELECT rulesJson FROM RuleSet WHERE active=1 ORDER BY version DESC LIMIT 1").fetchone()[0])
    rules_version = con.execute(
        "SELECT version FROM RuleSet WHERE active=1 ORDER BY version DESC LIMIT 1").fetchone()[0]

    seats = [dict(r) for r in con.execute(
        "SELECT address,label,status,sourceRank,roi30d,consistencyScore,copyabilityScore,"
        "oneHitWonderPenalty,globalScore,tradeCount30d,resolvedTradeCount30d,winRate30d,"
        "lastScannedAt,lastTrackedAt FROM WalletProfile WHERE status='track' AND %s "
        "ORDER BY globalScore DESC, address ASC LIMIT ?" % non_demo, (MAX_TRACKED,))]
    if len(seats) != MAX_TRACKED:
        print("  WARNING: %d seats, expected %d" % (len(seats), MAX_TRACKED))
    cut = seats[-1]["globalScore"]

    # challenger pool: non-demo `watch` wallets that already out-score the 25th seat.
    cands = [dict(r) for r in con.execute(
        "SELECT address,label,status,roi30d,consistencyScore,copyabilityScore,oneHitWonderPenalty,"
        "globalScore,tradeCount30d,resolvedTradeCount30d,lastScannedAt FROM WalletProfile "
        "WHERE status='watch' AND %s AND globalScore > ? ORDER BY globalScore DESC LIMIT ?" % non_demo,
        (cut, n_cand))]

    # ---------- venue walks
    cache = {}
    if POS.exists():
        cache = json.loads(POS.read_text())
    todo = [s["address"] for s in seats] + [c["address"] for c in cands]
    if fetch:
        for i, a in enumerate(todo):
            cap = 700 if any(s["address"] == a for s in seats) else cand_pages
            have = cache.get(a) or {}
            if have.get("closed") is not None and not refetch and have.get("end") != "capped":
                continue
            rows, pages, end = walk_closed(a, max_pages=cap)
            cache[a] = {"closed": rows, "pages": pages, "end": end, "fields": FIELDS,
                        "fetched_at": iso(now_ms())}
            print("  walked %s pages %d (%s) rows %d" % (a[:10], pages, end, len(rows)), flush=True)
            if i % 5 == 4:
                POS.write_text(json.dumps(cache))
        POS.write_text(json.dumps(cache))
        print("  cache written: %s" % POS, flush=True)
    if not cache:
        raise SystemExit("no position cache; run with --fetch-venue")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def rows_of(a):
        rec = cache.get(a) or {}
        flds = rec.get("fields") or FIELDS
        return [dict(zip(flds, r)) for r in (rec.get("closed") or [])]

    # ---------- 1. per-wallet records
    seat_rows, cand_rows = [], []
    A_KEYS = ("address", "label", "sourceRank", "roi30d", "consistencyScore", "copyabilityScore",
              "oneHitWonderPenalty", "globalScore", "tradeCount30d", "resolvedTradeCount30d",
              "winRate30d", "lastScannedAt")

    def obs_for(addr):
        out = []
        for r in con.execute(
                "SELECT conditionId, outcome, walletEntryPrice, detectedPrice, size, timestamp, "
                "observationOnly FROM ObservedTrade WHERE walletAddress=? AND isDemo=0 "
                "ORDER BY timestamp", (addr,)):
            out.append({"conditionId": r["conditionId"], "outcome": r["outcome"],
                        "walletEntryPrice": r["walletEntryPrice"], "detectedPrice": r["detectedPrice"],
                        "size": r["size"], "timestamp": r["timestamp"],
                        "observationOnly": r["observationOnly"]})
        return out

    for bucket, src in ((seat_rows, seats), (cand_rows, cands)):
        for s in src:
            rows = rows_of(s["address"])
            rec = wallet_record(rows, today, n_boot)
            rec.update({k: s[k] for k in A_KEYS if k in s})
            rec["walk"] = {k: (cache.get(s["address"]) or {}).get(k) for k in ("pages", "end")}
            # settlement oracle + the legs we actually observed (see observed_legs())
            oracle = {}
            for r in rows:
                sp = settle_price(r, today)
                if sp is not None:
                    oracle[(r.get("condition_id"), nrm(r.get("outcome")))] = sp
            rec["observed"] = observed_legs(obs_for(s["address"]), oracle, n_boot)
            bucket.append(rec)

    # ---------- 2. (A) basis counterfactual, per curve
    basis = {}
    for curve in CURVES:
        table = []
        for r in seat_rows:
            roi_full = (r["full_record"] or {}).get("roi")
            g, rs = global_from(roi_full, r["consistencyScore"], r["copyabilityScore"],
                                r["oneHitWonderPenalty"], r["resolvedTradeCount30d"], rules, curve)
            table.append({"address": r["address"], "label": r["label"],
                          "stored_global": r["globalScore"], "roi_full": roi_full,
                          "roi_score": rs, "global_full_roi": g})
        order = sorted(table, key=lambda x: (-x["global_full_roi"], x["address"]))
        for i, t in enumerate(order):
            t["seat_after"] = i + 1
        stored_order = sorted(table, key=lambda x: (-x["stored_global"], x["address"]))
        for i, t in enumerate(stored_order):
            t["seat_before"] = i + 1
        moved = sum(1 for t in table if t["seat_after"] != t["seat_before"])
        top10_changed = sorted(t["address"] for t in table if t["seat_before"] <= 10) != \
            sorted(t["address"] for t in table if t["seat_after"] <= 10)
        subj = next((t for t in table if t["address"] == W_SUBJECT), None)
        sat = sum(1 for t in table if t["roi_score"] >= 99.95)
        basis[curve] = {
            "rows": sorted(table, key=lambda x: x["seat_before"]),
            "seats_moving": moved,
            "top10_set_changed": top10_changed,
            "roi_saturated_seats": sat,
            "subject": subj,
            "subject_keeps_seat": bool(subj and subj["seat_after"] <= MAX_TRACKED),
        }

    # ---------- 3. (B) floor, per scope
    # Two families, because they answer different questions:
    #   venue_*    — the wallet's own venue-settled record. `hold` = what a copier who HOLDS
    #                would earn on its book; `realized` = what the wallet actually booked (exits
    #                included). They disagree in sign for a market maker, which is the point.
    #   observed_* — the legs this bot actually saw it trade, settled at the venue's terminal
    #                price: the population the copy lane can price.
    scopes = {
        "venue_hold_all": "hold_all",
        "venue_realized_all": "realized_on_settled",
        "venue_hold_rich": "hold_rich_095",
        "venue_realized_rich": "realized_rich_095",
        "venue_hold_copy": "hold_copy_080",
        "venue_realized_copy": "realized_copy_080",
        "observed_wallet_entry": "observed.at_wallet_entry",
        "observed_detected_mid": "observed.at_detected_mid",
        "observed_flood_wallet": "observed.flood_window.at_wallet_entry",
        "observed_flood_detected": "observed.flood_window.at_detected_mid",
    }

    def arm_of(r, key):
        cur = r
        for part in key.split("."):
            cur = (cur or {}).get(part)
        return cur

    floor = {}
    for name, key in scopes.items():
        rows_out = []
        for r in seat_rows:
            a = arm_of(r, key)
            ok, why = floor_verdict(a, key)
            rows_out.append({"address": r["address"], "label": r["label"], "pass": ok, "why": why,
                             "n_legs": (a or {}).get("n_legs"),
                             "roi": (a or {}).get("roi"),
                             "roi_ci": (a or {}).get("roi_ci")})
        cand_pass, cand_fail = [], []
        for r in cand_rows:
            a = arm_of(r, key)
            ok, why = floor_verdict(a, key)
            (cand_pass if ok else cand_fail).append(
                {"address": r["address"], "label": r["label"], "why": why,
                 "roi": (a or {}).get("roi"), "roi_ci": (a or {}).get("roi_ci"),
                 "n_legs": (a or {}).get("n_legs")})
        floor[name] = {
            "seats_pass": sum(1 for x in rows_out if x["pass"]), "seats_total": len(rows_out),
            "seats_failing": [x for x in rows_out if not x["pass"]],
            "rows": rows_out,
            "candidates_tested": len(cand_rows), "candidates_pass": cand_pass,
            "candidates_failing": cand_fail,
        }

    # ---------- 4. composition under each option
    def compose(basis_key, floor_scope):
        """Seat set after (A) re-rank (basis_key=None keeps today's STORED scores), dropping
        wallets that fail the floor; refill from the challenger pool up to 25."""
        scored = []
        for r, src in [(x, "seat") for x in seat_rows] + [(x, "challenger") for x in cand_rows]:
            if basis_key is None:
                g = r["globalScore"]
            else:
                roi_full = (r["full_record"] or {}).get("roi")
                g, _ = global_from(roi_full, r["consistencyScore"], r["copyabilityScore"],
                                   r["oneHitWonderPenalty"], r["resolvedTradeCount30d"], rules, basis_key)
            scored.append({"address": r["address"], "label": r["label"], "global": g,
                           "source": src, "in_floor": None})
        byaddr = {x["address"]: x for x in scored}
        if floor_scope:
            for r in seat_rows + cand_rows:
                ok, _ = floor_verdict(arm_of(r, scopes[floor_scope]), scopes[floor_scope])
                byaddr[r["address"]]["in_floor"] = ok
        kept = [x for x in scored if (floor_scope is None or x["in_floor"])]
        kept.sort(key=lambda x: (-x["global"], x["address"]))
        top = kept[:MAX_TRACKED]
        names = {y["address"] for y in top}
        return {
            "seats_filled": len(top),
            "seats_vacated_vs_today": [x["address"] for x in seat_rows if x["address"] not in names],
            "entrants": [x for x in top if x["source"] == "challenger"],
            "cut_score": top[-1]["global"] if top else None,
            "subject_tracked": any(x["address"] == W_SUBJECT for x in top),
            "subject_rank_in_pool": next((i + 1 for i, x in enumerate(kept) if x["address"] == W_SUBJECT), None),
            "table": top,
        }

    composition = {
        "today": {"seats_filled": len(seats), "cut_score": cut,
                  "subject_tracked": any(s["address"] == W_SUBJECT for s in seats)},
        "A_linear_basis_only": compose("linear_clamp", None),
        "A_michaelis": compose("michaelis", None),
        "A_atan": compose("atan", None),
        "B_only_venue_realized_all": compose(None, "venue_realized_all"),
        "B_only_venue_hold_all": compose(None, "venue_hold_all"),
        "B_only_observed_detected": compose(None, "observed_detected_mid"),
        "B_only_observed_flood": compose(None, "observed_flood_detected"),
        "A_atan_plus_B_venue_realized": compose("atan", "venue_realized_all"),
        "A_atan_plus_B_observed_detected": compose("atan", "observed_detected_mid"),
        "A_atan_plus_B_observed_flood": compose("atan", "observed_flood_detected"),
    }

    # ---------- 5. replay: journal admissions attributable to dropped seats (7d)
    dropped = sorted({x for comp in ("A_atan", "A_atan_plus_B_venue_realized")  # type: ignore[arg-type]
                      for x in composition[comp]["seats_vacated_vs_today"]})
    replay = {}
    win_ms = now_ms() - 7 * 86400 * 1000
    for a in dropped:
        jr = con.execute(
            "SELECT COUNT(*) n, SUM(CASE WHEN decision='paper_copy' THEN 1 ELSE 0 END) copies, "
            "MIN(createdAt) mn FROM DecisionJournal WHERE walletAddress=? AND isDemo=0 AND createdAt>=?",
            (a, win_ms)).fetchone()
        pt = con.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(realizedPnl),0) pnl, COALESCE(SUM(simulatedPositionSize),0) sz "
            "FROM PaperTrade WHERE walletAddress=? AND isDemo=0 AND openedAt>=?",
            (a, win_ms)).fetchone()
        obs = con.execute(
            "SELECT COUNT(*) n FROM ObservedTrade WHERE walletAddress=? AND observationOnly=1 AND timestamp>=?",
            (a, win_ms)).fetchone()
        replay[a] = {"journal_decisions_7d": jr["n"], "paper_copies_7d": jr["copies"] or 0,
                     "first_decision": iso(jr["mn"]),
                     "paper_trades_7d": pt["n"], "paper_realized_pnl_7d": round(pt["pnl"] or 0, 2),
                     "paper_size_7d": round(pt["sz"] or 0, 2),
                     "observed_untracked_rows_7d": obs["n"]}
    promoted = sorted({x["address"] for comp in ("A_atan", "A_atan_plus_B_venue_realized")  # type: ignore[arg-type]
                       for x in composition[comp]["entrants"]})
    promoted_out = {}
    for a in promoted:
        obs = con.execute(
            "SELECT COUNT(*) n, COUNT(DISTINCT marketId) m FROM ObservedTrade WHERE walletAddress=? "
            "AND observationOnly=1 AND timestamp>=?", (a, win_ms)).fetchone()
        promoted_out[a] = {"observed_rows_7d": obs["n"], "observed_markets_7d": obs["m"]}

    # ---------- 6. turnover (30d) from the observationOnly flag + scan rotation
    t30 = now_ms() - 30 * 86400 * 1000
    flips = con.execute(
        "SELECT walletAddress, MIN(CASE WHEN observationOnly=0 THEN timestamp END) first_copyable, "
        "MAX(CASE WHEN observationOnly=0 THEN timestamp END) last_copyable, COUNT(*) n "
        "FROM ObservedTrade WHERE timestamp>=? AND isDemo=0 GROUP BY walletAddress", (t30,)).fetchall()
    promoted_30d = [dict(r) for r in flips if r["first_copyable"] and r["first_copyable"] >= t30]
    demoted_30d = [dict(r) for r in flips
                   if r["last_copyable"] and r["last_copyable"] < now_ms() - 86400 * 1000]
    seat_tenure = []
    for s in seats:
        f = con.execute("SELECT MIN(timestamp) m FROM ObservedTrade WHERE walletAddress=? AND observationOnly=0",
                        (s["address"],)).fetchone()
        seat_tenure.append({"address": s["address"], "label": s["label"],
                            "first_copyable": iso(f["m"]),
                            "days_seated": (round((now_ms() - (f["m"] or now_ms())) / 86400000.0, 1)
                                            if f["m"] else None),
                            "last_scanned": iso(s["lastScannedAt"])})
    scan_age = con.execute(
        "SELECT COUNT(*) n, SUM(CASE WHEN lastScannedAt>=? THEN 1 ELSE 0 END) fresh6h, "
        "SUM(CASE WHEN lastScannedAt>=? THEN 1 ELSE 0 END) fresh7d "
        "FROM WalletProfile WHERE isDemo=0", (now_ms() - 6 * 3600 * 1000, win_ms)).fetchone()

    # ---------- 7. refusal test: subject's flood-window legs at TODAY's settlement
    subj_rows = [r for r in rows_of(W_SUBJECT) if (r.get("first_entry_at") or 0) * 1000 >= FLOOD_CUT_MS]
    subj_win = wallet_record(subj_rows, today, n_boot) if subj_rows else None

    # how far the stored (tail-sample) ROI is from the full-record ROI, across the seats
    dev = []
    for r in seat_rows:
        fr = (r["full_record"] or {}).get("roi")
        if fr is None:
            continue
        dev.append({"address": r["address"], "label": r["label"], "stored": r["roi30d"],
                    "full": fr, "ratio_full_over_stored": (fr / r["roi30d"]) if r["roi30d"] else None})
    dev_sorted = sorted(dev, key=lambda x: (x["ratio_full_over_stored"] if x["ratio_full_over_stored"] is not None else 9))
    sample_err = {
        "seats": len(dev),
        "stored_overstates": sum(1 for x in dev if x["full"] < x["stored"]),
        "stored_understates": sum(1 for x in dev if x["full"] > x["stored"]),
        "median_ratio_full_over_stored": (dev_sorted[len(dev_sorted) // 2]["ratio_full_over_stored"]
                                          if dev_sorted else None),
        "worst_overstatement": dev_sorted[0] if dev_sorted else None,
        "rows": dev,
    }

    out = {
        "generated_at": iso(now_ms()),
        "instrument": "scripts/lane-a-seat-basis-read.py",
        "lane": "A (proposal only — nothing applied)",
        "rules_version": rules_version,
        "subject": W_SUBJECT,
        "sample_error_A": sample_err,
        "rules_weights": {k: rules[k] for k in ("weightRoi", "weightConsistency", "weightCopyability",
                                                "minWalletGlobalScore", "minResolvedTrades")},
        "settlement_basis": {
            "settled": "CLOSED position, end_date<today, venue current_price terminal (0/1 +/- 0.005)",
            "primary": "hold-to-settlement: size*(settle-avg_price) on cost size*avg_price",
            "secondary": "venue realized_pnl on the same settled rows",
            "clustering": "bootstrap resamples whole markets (condition_id), 95% percentile",
            "today": today,
        },
        "seats": {"n": len(seats), "cut_score": cut, "rows": seat_rows},
        "challengers": {"n": len(cand_rows), "rows": cand_rows},
        "basis_A": basis,
        "floor_B": floor,
        "composition": composition,
        "replay_7d": {"dropped_seats": replay, "promoted_wallets": promoted_out, "window_ms": win_ms},
        "turnover_30d": {
            "promoted_30d": len(promoted_30d),
            "demoted_30d": len(demoted_30d),
            "seed_details": sorted(promoted_30d, key=lambda r: r["first_copyable"])[:30],
            "seat_tenure": seat_tenure,
            "scan_freshness": {"profiles": scan_age["n"], "scanned_6h": scan_age["fresh6h"],
                               "scanned_7d": scan_age["fresh7d"]},
        },
        "refusal_test_subject_flood_window": subj_win,
        "cache": {"pages_total": sum((cache.get(a) or {}).get("pages") or 0 for a in todo),
                  "wallets_cached": len([a for a in todo if a in cache])},
    }
    OUT.write_text(json.dumps(out, indent=1))
    print("  wrote %s" % OUT)
    summary(out)


def summary(o):
    print("\n== seats: %d, cut %.1f, rules v%s" % (o["seats"]["n"], o["seats"]["cut_score"], o["rules_version"]))
    hdr = ("wallet", "stored", "roi30d", "roi_full", "real_all", "hold_all", "obs_w", "obs_d", "nlegs", "settled", "obs_key")
    print("%-12s %6s %6s %8s %8s %8s %7s %7s %6s %7s %7s" % hdr)
    for r in o["seats"]["rows"]:
        ob = r["observed"]
        f = lambda a, k="roi": (("%+.3f" % a[k]) if a and a.get(k) is not None else "n/a")
        fw = ob["flood_window"]
        print("%-12s %6.1f %6.2f %8s %8s %8s %7s %7s %7s %6d %6d" % (
            (r["label"] or r["address"])[:12], r["globalScore"], r["roi30d"],
            f(r["full_record"]), f(r["realized_on_settled"]), f(r["hold_all"]),
            f(ob["at_wallet_entry"]), f(ob["at_detected_mid"]), f(fw["at_detected_mid"]),
            r["n_positions"], r["n_settled"]))
    print("\n== (A) basis, per curve")
    for c, b in o["basis_A"].items():
        s = b["subject"] or {}
        print("  %-13s moving %2d/25  top10 changed %-5s  roi_saturated %2d/25  subject roi_full %.3f -> g %s (seat %s)" % (
            c, b["seats_moving"], b["top10_set_changed"], b["roi_saturated_seats"],
            s.get("roi_full") or 0, s.get("global_full_roi"), s.get("seat_after")))
    print("\n== (B) floor")
    for k, f in o["floor_B"].items():
        subj = next((x for x in f["rows"] if x["address"] == o["subject"]), None)
        print("  %-22s seats pass %2d/%d  challengers %2d/%d  subject %-4s (%s)" % (
            k, f["seats_pass"], f["seats_total"], len(f["candidates_pass"]), f["candidates_tested"],
            "PASS" if (subj and subj["pass"]) else "FAIL", (subj or {}).get("why")))
    print("\n== composition")
    for k, c in o["composition"].items():
        print("  %-24s filled %2s cut %-6s subject %-5s vacated %2s entrants %s" % (
            k, c.get("seats_filled"), c.get("cut_score"), c.get("subject_tracked"),
            len(c.get("seats_vacated_vs_today") or []), len(c.get("entrants") or [])))
    rt = o["refusal_test_subject_flood_window"]
    if rt:
        a = rt["hold_all"]
        print("\n== refusal re-cut (subject flood-window positions, today's settlement): legs %d roi %s ci %s" % (
            a["n_legs"], a["roi"], a["roi_ci"]))


if __name__ == "__main__":
    main()
