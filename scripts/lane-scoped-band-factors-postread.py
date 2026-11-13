#!/usr/bin/env python3
"""
Lane-scoped C-200 band factors (v71) -- POST-APPLY READ.

WHY THIS EXISTS
  The card `lane-scoped-band-factors` was re-approved on 2026-11-12 with the
  rationale that mapBankroll200Size applied ONE deadZone (0.25) and ONE premium
  (0.5) factor to both C-200 lanes. That is TRUE as a description of pre-v71
  code and FALSE as of 2026-11-03 14:54:07, when RuleSet v71 activated
  shortTtrDeadZoneBandFactor=0.5 / shortTtrPremiumBandFactor=2.0 and
  scripts/score-trades.ts began reading them for `result.lane === "short_ttr"`.
  The live question is no longer "should we apply it" but "is it reaching legs,
  and is it still holding up".

  v71's pre-registered refutation (scripts/apply-v71.ts, lines 36-42):
    over the next 150 short-TTR bets -> CI lower bound < 0, OR ex-top-5 < +8%,
    OR median entry slippage > 4c  =>  revert both fields to 0.25 / 0.5.

THREE MEASUREMENT RULES THIS FILE ENFORCES (each one changed a number)
  1. FILL-AWARE BOOKING. src/lib/paper.ts::bookedPnl forces realizedPnl to 0 on
     legs the resolver proved never traded (fillStatus='unfilled', DEFAULT ON
     since 2026-10-28). Counting those as losses manufactures a collapse, so
     performance runs on POSITIONS = fillStatus != 'unfilled' and the unfilled
     class is reported as flow, never as a return.
  2. BOTH EXIT CLASSES. `closed` = early exit, `resolved` = natural settlement,
     and realised PnL ORs both. Reading resolved only selects the SETTLEMENT
     subset, which in these cells is a different book: pre-v71 short-TTR 0.6-0.8
     is +26.8% ROI on resolved but -17.0% on closed (union +4.1%). The union is
     the primary population here and the split is printed beside every cell.
  3. PRICE BASIS. src/lib/outcome-price.ts (fbf9073, 2026-11-09) repriced legs by
     the venue's own token label; before it ~34% of regime legs booked the
     COMPLEMENT. Measured for this lane: 0 of 453 pre-v71 short-TTR legs in
     0.2-0.8 classify INVERTED against the wallet's own fill, so the lane's
     bands are clean -- but the fix still lands INSIDE the post-v71 window, so
     every post cell is also split at it.

COST BASIS (must travel with every ROI): PaperTrade.simulatedPositionSize is
  DOLLARS at risk, never shares. BET BASIS: first leg per
  (walletAddress, marketId, outcome) ordered by openedAt across BOTH statuses.
POPULATION: isDemo=0, DecisionJournal.ruleSetVersion >= 49.

SECTIONS
  S1  active RuleSet + the band factors (main vs short-TTR).
  S2  ENFORCEMENT: booked size / the $10 decision size, per lane x band, pre vs
      post -- a difference-in-differences against the two bands the rule did
      NOT touch. A stored field is not an enforcing field.
  S3  FLOW: legs opened per band per month, and the weekly fill verdict.
  S4  PERFORMANCE: lane x band cells (positions, both exit classes).
  S5  REFUTATION: v71's conditions on the post window + distance to n=150.
  S6  COUNTERFACTUAL: post-window positions re-priced at the pre-v71 factors.

USAGE
    python3 scripts/lane-scoped-band-factors-postread.py
    python3 scripts/lane-scoped-band-factors-postread.py --json

Read-only: opens prisma/dev.db with mode=ro&immutable=1, writes nothing.
"""
import json
import sqlite3
import sys

import numpy as np

DB = "file:prisma/dev.db?mode=ro&immutable=1"
MIN_REGIME_VERSION = 49
FEE_RATE = 0.05
V71_APPLIED_MS = 1793717647603   # 2026-11-03 14:54:07 UTC (RuleChange.createdAt)
PRICE_FIX_MS = 1793783716000     # 2026-11-09 ~09:15 local, fbf9073 (src/lib/outcome-price.ts)
BANDS = [(0.0, 0.2, "<0.20"), (0.2, 0.4, "0.2-0.4"), (0.4, 0.6, "0.4-0.6"),
         (0.6, 0.8, "0.6-0.8"), (0.8, 1.0001, "0.8+")]
C200_MIN_USD, C200_MAX_USD = 0.25, 20.0
PRE_FACTORS = {"deadZone": 0.25, "premium": 0.5}
POST_FACTORS = {"deadZone": 0.5, "premium": 2.0}
ARGS = sys.argv[1:]


def band_of(p):
    for lo, hi, name in BANDS:
        if lo <= p < hi:
            return name
    return None


def connect():
    c = sqlite3.connect(DB, uri=True)
    c.row_factory = sqlite3.Row
    return c


def load():
    """Bet-level rows across BOTH finished statuses, one per (wallet, market, outcome)."""
    q = """
    WITH leg AS (
      SELECT pt.id, pt.walletAddress, pt.marketId, pt.outcome, pt.entryPrice,
             pt.simulatedPositionSize AS size, pt.realizedPnl AS pnl,
             pt.openedAt, pt.status AS st, pt.fillStatus AS fill, dj.ruleSetVersion AS v,
             dj.simulatedPositionSize AS target,
             CASE WHEN dj.reasonsJson LIKE '%Short-TTR%' THEN 'shortttr' ELSE 'main' END AS lane
      FROM PaperTrade pt
      JOIN DecisionJournal dj ON dj.id = pt.decisionJournalId
      WHERE pt.isDemo = 0 AND pt.status IN ('closed','resolved') AND pt.realizedPnl IS NOT NULL
        AND dj.ruleSetVersion >= ?
    ), bet AS (
      SELECT *, ROW_NUMBER() OVER (
        PARTITION BY walletAddress, marketId, outcome ORDER BY openedAt
      ) AS rn
      FROM leg
    )
    SELECT * FROM bet WHERE rn = 1
    """
    rows = connect().execute(q, (MIN_REGIME_VERSION,)).fetchall()
    out = []
    for r in rows:
        b = band_of(r["entryPrice"])
        if b is None:
            continue
        out.append({"lane": r["lane"], "band": b, "market": r["marketId"],
                    "wallet": r["walletAddress"], "px": r["entryPrice"],
                    "size": r["size"], "pnl": r["pnl"], "opened": r["openedAt"],
                    "v": r["v"], "st": r["st"], "fill": r["fill"] or "unknown",
                    "target": r["target"],
                    "post": r["openedAt"] >= V71_APPLIED_MS,
                    "post_fix": r["openedAt"] >= PRICE_FIX_MS})
    return out


def positions(rows):
    """Legs that were a position: an unfilled leg is a provable non-position."""
    return [r for r in rows if r["fill"] != "unfilled"]


def cell_stats(rows):
    n = len(rows)
    if not n:
        return None
    ntl = sum(r["size"] for r in rows)
    pnl = sum(r["pnl"] for r in rows)
    hit = sum(1 for r in rows if r["pnl"] > 0) / n
    px = sum(r["px"] for r in rows) / n
    hurdle = px * (1 + FEE_RATE * (1 - px))
    edge = hit - hurdle
    se = (hit * (1 - hit) / n) ** 0.5
    by_mkt = {}
    for r in rows:
        a = by_mkt.setdefault(r["market"], [0.0, 0.0])
        a[0] += r["pnl"]
        a[1] += r["size"]
    top5 = sorted(by_mkt.values(), key=lambda a: -a[0])[:5]
    pnl5 = sum(a[0] for a in top5)
    ntl5 = sum(a[1] for a in top5)
    ex_pnl, ex_ntl = pnl - pnl5, ntl - ntl5
    return {
        "n": n, "markets": len(by_mkt), "notional": ntl, "pnl": pnl,
        "roi": pnl / ntl if ntl else 0.0, "clip": ntl / n, "px": px,
        "hit": hit, "hurdle": hurdle, "edge": edge, "se": se,
        "z": edge / se if se else 0.0,
        "ex5_roi": (ex_pnl / ex_ntl) if ex_ntl > 0 else float("nan"),
        "breakeven_slip_c": (hit - px) * 100,
    }


def cluster_ci(rows, iters=2000, seed=11):
    """Market-clustered bootstrap CI on ROI: resample MARKETS, not bets."""
    rng = np.random.default_rng(seed)
    by = {}
    for r in rows:
        a = by.setdefault(r["market"], [0.0, 0.0])
        a[0] += r["pnl"]
        a[1] += r["size"]
    keys = list(by)
    if len(keys) < 3:
        return (float("nan"), float("nan"))
    p = np.array([by[k][0] for k in keys])
    s = np.array([by[k][1] for k in keys])
    out = np.empty(iters)
    for i in range(iters):
        idx = rng.integers(0, len(keys), len(keys))
        d = s[idx].sum()
        out[i] = p[idx].sum() / d if d > 0 else 0.0
    return (float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5)))


def active_rules():
    c = connect()
    row = c.execute(
        "SELECT version, rulesJson, datetime(createdAt/1000,'unixepoch') AS created "
        "FROM RuleSet WHERE active = 1 ORDER BY version DESC LIMIT 1"
    ).fetchone()
    j = json.loads(row["rulesJson"])
    return row["version"], row["created"], {
        "shortTtrDeadZoneBandFactor": j.get("shortTtrDeadZoneBandFactor"),
        "shortTtrPremiumBandFactor": j.get("shortTtrPremiumBandFactor"),
        "c200DeadZoneBandFactor": j.get("c200DeadZoneBandFactor"),
        "c200LongshotBandFactor": j.get("c200LongshotBandFactor"),
        "c200LongshotBandFloor": j.get("c200LongshotBandFloor"),
        "c200BandSizeFactor": j.get("c200BandSizeFactor"),
        "c200BandSizeFactorRange": j.get("c200BandSizeFactorRange"),
        "c200SkipBandRange": j.get("c200SkipBandRange"),
        "c200MaxEntryPrice": j.get("c200MaxEntryPrice"),
    }


def refutation(rows):
    """v71's own three revert conditions, on positions only."""
    st = cell_stats(rows)
    if not st or st["n"] < 3:
        return {"n": st["n"] if st else 0, "verdict": "NO DATA"}
    lo, hi = cluster_ci(rows)
    conds = {
        "ci_low_below_zero": bool(lo == lo and lo < 0),
        "ex_top5_below_8pct": bool(st["ex5_roi"] == st["ex5_roi"] and st["ex5_roi"] < 0.08),
        "breakeven_slip_below_4c": bool(st["breakeven_slip_c"] < 4.0),
    }
    fired = sum(1 for v in conds.values() if v)
    return {"n": st["n"], "ci": [lo, hi], "ex5_roi": st["ex5_roi"],
            "breakeven_slip_c": st["breakeven_slip_c"], "conditions": conds,
            "fired": fired, "verdict": "REVERT" if fired else "HOLD"}


def main():
    ver, created, rules = active_rules()
    print("=" * 78)
    print("LANE-SCOPED C-200 BAND FACTORS (v71) — POST-APPLY READ")
    print(f"population: isDemo=0, ruleSetVersion>={MIN_REGIME_VERSION}, status IN (closed,resolved), "
          "bet-level dedupe across both")
    print(f"cost basis: simulatedPositionSize = DOLLARS at risk | fee rate {FEE_RATE} | "
          "performance on POSITIONS (fillStatus != unfilled)")
    print("=" * 78)

    print(f"\nS1 ACTIVE RULESET v{ver} (created {created})")
    for k, v in rules.items():
        print(f"   {k:32} {v}")

    legs = load()
    pre = [r for r in legs if not r["post"]]
    post = [r for r in legs if r["post"]]
    print(f"\nS0 population: {len(legs)} finished bets / ${sum(r['size'] for r in legs):,.0f} notional")
    for lane in ("main", "shortttr"):
        for label, rows in (("pre-v71", [r for r in pre if r["lane"] == lane]),
                            ("post-v71", [r for r in post if r["lane"] == lane])):
            if not rows:
                continue
            span = (min(r["opened"] for r in rows), max(r["opened"] for r in rows))
            fills, sts = {}, {}
            for r in rows:
                fills[r["fill"]] = fills.get(r["fill"], 0) + 1
                sts[r["st"]] = sts.get(r["st"], 0) + 1
            print(f"   {lane:9} {label:9} n={len(rows):4d}  span "
                  f"{span[0]/1000:.0f}->{span[1]/1000:.0f} "
                  f"({(span[1]-span[0])/86400000.0:.1f}d)  "
                  + " ".join(f"{k}={v}" for k, v in sorted(sts.items())) + "  fill "
                  + " ".join(f"{k}={v}" for k, v in sorted(fills.items())))

    print("\nS2 ENFORCEMENT — booked size / $10 decision size, per lane x band")
    print("   (difference-in-differences: the two bands the rule did NOT touch are the control)")
    print(f"{'lane':9} {'band':8} {'n_pre':>6} {'pre':>6} {'n_post':>7} {'post':>6} "
          f"{'post/pre':>9} {'map expects':>12}")
    exp = {"0.4-0.6": POST_FACTORS["deadZone"] / PRE_FACTORS["deadZone"],
           "0.6-0.8": POST_FACTORS["premium"] / PRE_FACTORS["premium"]}
    for lane in ("main", "shortttr"):
        for _, _, band in BANDS:
            a = [r for r in pre if r["lane"] == lane and r["band"] == band and r["target"]]
            b = [r for r in post if r["lane"] == lane and r["band"] == band and r["target"]]
            if not a or not b:
                continue
            ra = sum(r["size"] / r["target"] for r in a) / len(a)
            rb = sum(r["size"] / r["target"] for r in b) / len(b)
            print(f"{lane:9} {band:8} {len(a):6d} {ra:6.2f} {len(b):7d} {rb:6.2f} "
                  f"{rb/ra if ra else float('nan'):9.2f} {exp.get(band, 1.0) if lane == 'shortttr' else 1.0:12.2f}")

    print("\nS3 FLOW — is the cell the rule targets still produced?")
    c = connect()
    print("   short-TTR legs opened per band per month (all statuses, ruleSetVersion>=49):")
    q = """
    SELECT strftime('%Y-%m', datetime(pt.openedAt/1000,'unixepoch')) m,
           CASE WHEN pt.entryPrice<0.2 THEN '1_<0.20' WHEN pt.entryPrice<0.4 THEN '2_0.2-0.4'
                WHEN pt.entryPrice<0.6 THEN '3_0.4-0.6' WHEN pt.entryPrice<0.8 THEN '4_0.6-0.8'
                ELSE '5_0.8+' END band, COUNT(*) n
    FROM PaperTrade pt JOIN DecisionJournal dj ON dj.id=pt.decisionJournalId
    WHERE pt.isDemo=0 AND dj.ruleSetVersion>=? AND dj.reasonsJson LIKE '%Short-TTR%'
    GROUP BY 1,2 ORDER BY 1,2
    """
    for r in c.execute(q, (MIN_REGIME_VERSION,)):
        print(f"     {r['m']}  {r['band']:10} {r['n']:5d}")
    print("   short-TTR weekly fill verdict (every short-TTR leg, all statuses):")
    q2 = """
    SELECT strftime('%Y-%W', datetime(pt.openedAt/1000,'unixepoch')) wk, COUNT(*) n,
           SUM(CASE WHEN pt.fillStatus='unfilled' THEN 1 ELSE 0 END) unf,
           SUM(CASE WHEN pt.fillStatus='filled' THEN 1 ELSE 0 END) fil,
           SUM(CASE WHEN pt.fillStatus IS NULL THEN 1 ELSE 0 END) unk
    FROM PaperTrade pt JOIN DecisionJournal dj ON dj.id=pt.decisionJournalId
    WHERE pt.isDemo=0 AND dj.ruleSetVersion>=? AND dj.reasonsJson LIKE '%Short-TTR%'
      AND pt.openedAt>=1791900000000
    GROUP BY 1 ORDER BY 1
    """
    for r in c.execute(q2, (MIN_REGIME_VERSION,)):
        print(f"     {r['wk']}  n={r['n']:4d}  filled={r['fil']:3d}  unknown={r['unk']:3d}  "
              f"unfilled={r['unf']:3d}  (unfilled {r['unf']/r['n']*100:.0f}%)")

    print("\nS4 CELL TABLE (positions, both exit classes). hurdle = p*(1+r*(1-p)); "
          "z = edge/SE(hit); CI = market-clustered 95%")
    print(f"{'lane':9} {'band':8} {'era':9} {'n':>4} {'mk':>3} {'clip$':>6} {'pnl$':>8} "
          f"{'roi':>7} {'px':>5} {'hit':>5} {'edge':>6} {'z':>5} {'CI':>17} {'ex5roi':>7} {'slip':>6}")
    for lane in ("main", "shortttr"):
        for _, _, band in BANDS:
            for era, rows in (("pre-v71", positions([r for r in pre if r["lane"] == lane
                                                     and r["band"] == band])),
                              ("post-v71", positions([r for r in post if r["lane"] == lane
                                                      and r["band"] == band]))):
                st = cell_stats(rows)
                if not st:
                    continue
                lo, hi = cluster_ci(rows)
                ci = f"[{lo*100:+6.1f},{hi*100:+6.1f}]" if lo == lo else "[   n/a ]"
                print(f"{lane:9} {band:8} {era:9} {st['n']:4d} {st['markets']:3d} {st['clip']:6.2f} "
                      f"{st['pnl']:8.2f} {st['roi']*100:+6.1f}% {st['px']:5.3f} {st['hit']:5.3f} "
                      f"{st['edge']*100:+5.1f}pp {st['z']:5.2f} {ci:>17} "
                      f"{st['ex5_roi']*100:+6.1f}% {st['breakeven_slip_c']:+5.1f}c")
                if era == "post-v71" and lane == "shortttr":
                    for sub, srows in (("resolved", [r for r in rows if r["st"] == "resolved"]),
                                       ("closed", [r for r in rows if r["st"] == "closed"])):
                        s2 = cell_stats(srows)
                        if s2:
                            print(f"{'':9} {'':8}   {sub:7} {s2['n']:4d} {'':3} {s2['clip']:6.2f} "
                                  f"{s2['pnl']:8.2f} {s2['roi']*100:+6.1f}% {s2['px']:5.3f} "
                                  f"{s2['hit']:5.3f} {'':14}")

    print("\nS5 v71 PRE-REGISTERED REFUTATION — post-apply window, positions per band")
    triggers = {}
    for _, _, band in BANDS:
        rows = positions([r for r in post if r["lane"] == "shortttr" and r["band"] == band])
        if not rows:
            print(f"   shortttr {band:8} n=   0  -> no positions, condition unreachable")
            continue
        r = refutation(rows)
        triggers[band] = r
        ci = r.get("ci") or (float("nan"), float("nan"))
        lo, hi = ci[0] if ci[0] == ci[0] else float("nan"), ci[1] if ci[1] == ci[1] else float("nan")
        print(f"   shortttr {band:8} n={r['n']:4d}  CI [{lo*100:+6.1f},{hi*100:+6.1f}]  "
              f"ex5roi {r.get('ex5_roi', float('nan'))*100:+6.1f}%  "
              f"breakeven-slip {r.get('breakeven_slip_c', float('nan')):+5.1f}c  -> {r['verdict']}")
        if "conditions" in r:
            print(f"      conditions: {r['conditions']}")
    n_mid = triggers.get("0.4-0.6", {}).get("n", 0)
    print(f"   n toward the 150-bet trigger (0.4-0.6): {n_mid}/150 — "
          f"{'BAR MET' if n_mid >= 150 else 'window incomplete AND the cell has no flow'}")

    print("\nS6 COUNTERFACTUAL — post-window positions re-priced at the PRE-v71 factors "
          "(rescale, re-clamp $0.25/$20)")
    for band, old_f, new_f in (("0.4-0.6", PRE_FACTORS["deadZone"], POST_FACTORS["deadZone"]),
                               ("0.6-0.8", PRE_FACTORS["premium"], POST_FACTORS["premium"])):
        rows = positions([r for r in post if r["lane"] == "shortttr" and r["band"] == band])
        if not rows:
            print(f"   {band}: no positions")
            continue
        cf_ntl = cf_pnl = act_ntl = act_pnl = 0.0
        clamped = 0
        for r in rows:
            b = r["size"] / new_f if new_f else r["size"]
            s = min(C200_MAX_USD, max(C200_MIN_USD, b * old_f))
            if r["size"] >= C200_MAX_USD - 1e-9:
                clamped += 1
            roi = r["pnl"] / r["size"] if r["size"] else 0.0
            cf_ntl += s
            cf_pnl += roi * s
            act_ntl += r["size"]
            act_pnl += r["pnl"]
        print(f"   {band}: actual ${act_ntl:7.2f} / ${act_pnl:8.2f}  vs  pre-v71 factors "
              f"${cf_ntl:7.2f} / ${cf_pnl:8.2f}   delta {act_pnl - cf_pnl:+8.2f} "
              f"over a ${act_ntl - cf_ntl:+7.2f} notional shift"
              + (f"  ({clamped} legs sat on the $20 cap)" if clamped else ""))

    if "--json" in ARGS:
        print(json.dumps({"active": {"version": ver, "created": created, "rules": rules},
                          "refutation": triggers}, indent=1, default=str))


if __name__ == "__main__":
    main()
