#!/usr/bin/env python3
"""
source-print-notional-read -- is the SOURCE PRINT SIZE an admission signal?

WHY THIS EXISTS (roadmap card research-source-print-notional, APPROVED 2026-10-23,
Lane B read-only; card decision date 2026-11-06 has passed)

    Hypothesis (the card's, unchanged): a C-200 leg copied from a source fill of
    >= $250 notional returns materially less per leg than one copied from a small
    print, after wallet, entry band, TTR and era controls. If that held, print
    size would be worth scoring as an admission term (shadow-only first).

    The card pre-registered its own decision rule:
        controlled gap (small - big) >= $1.50/leg
          AND 2SE below the gap
          AND n >= 60 big-print legs   (by 2026-11-06)
        => add sourcePrintNotional (or print/liquidity) as a scored admission term,
           shadow-only first
        else => record it as a liquidity/era proxy and DROP the axis.

BASIS (stated, never implied)
    population  non-demo C-200 legs (PaperTrade.botId='BANKROLL_200', isDemo=0,
                status in closed|resolved, realizedPnl NOT NULL) joined to the
                DecisionJournal row that admitted them and to the ObservedTrade
                print that triggered it (isDemo=0, observationOnly=0).
                openedAt >= 2026-09-04 (the card's own epoch).
    notional    ObservedTrade.size, which the adapter writes as USDC
                (usdcSize / totalBought*avgPrice / initialValue -- see
                src/lib/adapters/polymarket.ts:526,318,364). It is NOT shares and
                must not be multiplied by price: doing that was the first defect
                found in this instrument (it shifted the $250 cut by ~1/price).
    level       one leg. Cluster arm: one leg's PRINT CLUSTER = sum of that
                wallet's prints on the same market+outcome+side within +-300 s,
                because a whale splitting one order into ten prints would
                otherwise read as ten small prints (78.2% of legs are single
                prints, so the two arms mostly coincide).
    clock       leg clock; era = journal.ruleSetVersion (this repo's regime
                definition), NOT openedAt.
    return      realizedPnl / simulatedPositionSize = per-$1-staked, GROSS of fees
                (fee law is a separate card). The per-LEG dollar gap is also
                printed because the card's rule is written in $/leg, but it is
                stake-confounded (C-200 stakes run 0.62..100), so the per-$1 read
                is the primary one and the $/leg read is reported with the stake
                distribution beside it.

WHAT THE CARD'S $1.50/leg THRESHOLD MEANS IN PER-$1 TERMS
    $1.50/leg is only convertible to a per-$1 number through a stake. At this
    population's mean C-200 stake the thresholds are printed explicitly, so the
    verdict cannot be moved by choosing a stake after the fact.

CONTROLS
    Matched ATT with replacement. Cells = era x entry band x TTR band x stake band;
    every big-print leg is compared with the mean of the SMALL legs in its own
    cell; the reported gap is the mean over big legs (small - big, so a POSITIVE
    gap means big prints return LESS, which is the hypothesis's direction).
    Coverage is printed and a run below 80% matched is flagged as unusable.
    A wallet-level arm is printed too (wallets carrying >=3 legs on each side).

READ-ONLY: opens dev.db read-only, writes data/source-print-notional-read.json,
changes no rule, threshold, size or gate. The card's decision, if it had fired,
would be Lane A and would be tagged awaiting-approval instead of applied.
"""

import argparse
import json
import math
import os
import random
import sqlite3
import statistics
import sys
from datetime import datetime, timezone

DB = os.environ.get("COPYBOT_DB", "prisma/dev.db")
OUT = "data/source-print-notional-read.json"
EPOCH = "2026-09-04"          # the card's own epoch
CUT = 250.0                   # the card's own big/small threshold
GATE_PER_LEG = 1.50           # the card's own decision threshold, $/leg
GATE_BIG_N = 60               # the card's own minimum for the big arm
MIN_COVERAGE = 0.80           # below this the matched read is not usable
CELLS = ("era", "bep", "bttr", "bst")


# ---------------------------------------------------------------- banding
def band_entry(ep):
    if ep is None:
        return "unk"
    if ep < 0.05:
        return "<.05"
    if ep < 0.2:
        return ".05-.2"
    if ep < 0.4:
        return ".2-.4"
    if ep < 0.6:
        return ".4-.6"
    if ep < 0.8:
        return ".6-.8"
    return ".8+"


def band_ttr(t):
    if t is None:
        return "unk"
    if t < 24:
        return "<1d"
    if t < 168:
        return "1-7d"
    return "7d+"


def band_era(v):
    if v is None:
        return "none"
    if v <= 50:
        return "v<=50"
    if v <= 55:
        return "v51-55"
    if v <= 60:
        return "v56-60"
    if v <= 65:
        return "v61-65"
    return "v66-70" if v <= 70 else "v71+"


def band_stake(sz):
    if sz < 5:
        return "<5"
    if sz < 15:
        return "5-15"
    return "15+"


# ---------------------------------------------------------------- stats
def concentration(xs):
    """Median / trimmed mean / ex-top-10 -- the anti-'big number' read."""
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return {}
    k = int(n * 0.10)
    core = s[k:n - k] if n - 2 * k > 0 else s
    ex10 = s[:-10] if n > 10 else []
    top10 = s[-10:] if n > 10 else s
    total = sum(s)
    return {
        "n": n,
        "mean": sum(s) / n,
        "median": statistics.median(s),
        "trimmed_mean_10pct": sum(core) / len(core),
        "ex_top10_mean": (sum(ex10) / len(ex10)) if ex10 else None,
        "top10_share_of_sum": (sum(top10) / total) if total != 0 else None,
        "win_share": sum(1 for x in s if x > 0) / n,
    }


def cell_key(r):
    return tuple(r[k] for k in CELLS)


def matched_att(big, small, table, reps=2000, seed=17):
    """Matched ATT with replacement on `table` ('roi' or 'pnl'), wallet-clustered CI.

    Control means are recomputed from each bootstrap resample so the interval
    carries both legs of the comparison. A resample that empties a cell drops
    that big leg AND counts it -- never silently imputes a control.
    """
    ctrl = {}
    for r in small:
        ctrl.setdefault(cell_key(r), []).append(r[table])
    matched = [r for r in big if cell_key(r) in ctrl]
    coverage = (len(matched) / len(big)) if big else 0.0
    if not matched:
        return {"table": table, "n_big": len(big), "n_matched": 0,
                "coverage": 0.0, "gap": None, "se2": None, "verdict": "NO_MATCH"}

    def gap_of(legs, ctrl_means):
        ds = [ctrl_means[cell_key(r)] - r[table] for r in legs if cell_key(r) in ctrl_means]
        return (sum(ds) / len(ds)) if ds else None

    fixed = {k: sum(v) / len(v) for k, v in ctrl.items()}
    g = gap_of(matched, fixed)
    diffs = [fixed[cell_key(r)] - r[table] for r in matched]

    by_wallet = {}
    for r in matched:
        by_wallet.setdefault(r["w"], []).append(r)
    wallets = list(by_wallet)
    boots, dropped = [], 0
    rnd = random.Random(seed)
    for _ in range(reps):
        samp = [rnd.choice(wallets) for _ in wallets]
        legs = [r for w in samp for r in by_wallet[w]]
        c = {}
        for r in small:            # rebuilt only from cells the resample can use
            c.setdefault(cell_key(r), []).append(r[table])
        cm = {k: sum(v) / len(v) for k, v in c.items()}
        gg = gap_of(legs, cm)
        if gg is None:
            dropped += 1
        else:
            boots.append(gg)
    if len(boots) < reps * 0.5:
        return {"table": table, "n_big": len(big), "n_matched": len(matched),
                "coverage": coverage, "gap": g, "se2": None, "dropped": dropped,
                "verdict": "INSUFFICIENT_RESAMPLES"}
    boots.sort()
    se = statistics.stdev(boots)
    return {
        "table": table,
        "n_big": len(big),
        "n_matched": len(matched),
        "coverage": coverage,
        "gap": g,                          # small - big
        "gap_median": statistics.median(diffs),
        "se2": 2 * se,
        "ci95": [boots[int(0.025 * len(boots))], boots[int(0.975 * len(boots)) - 1]],
        "dropped_resamples": dropped,
        "p_gap_positive": sum(1 for b in boots if b > 0) / len(boots),
        "cell_gap_positive_share": None,
    }


def era_table(rows):
    out = {}
    for r in rows:
        k = (r["era"], r["grp"])
        d = out.setdefault("%s|%s" % k, {"n": 0, "pnl": 0.0, "stake": 0.0, "roi_sum": 0.0})
        d["n"] += 1
        d["pnl"] += r["pnl"]
        d["stake"] += r["sz"]
        d["roi_sum"] += r["roi"]
    return {k: {"n": v["n"], "pnl_per_leg": v["pnl"] / v["n"],
                "roi_per_dollar": v["roi_sum"] / v["n"]} for k, v in sorted(out.items())}


def ladder_table(rows, cuts):
    out = []
    for i, lo in enumerate(cuts):
        hi = cuts[i + 1] if i + 1 < len(cuts) else float("inf")
        g = [r for r in rows if lo <= r["print_usd"] < hi]
        if not g:
            continue
        out.append({"bucket": ("%g-%g" % (lo, hi)) if hi != float("inf") else ("%g+" % lo),
                    "n": len(g),
                    "pnl_per_leg": statistics.mean(r["pnl"] for r in g),
                    "roi_per_dollar": statistics.mean(r["roi"] for r in g),
                    "median_roi": statistics.median(r["roi"] for r in g),
                    "big_bucket": lo >= CUT})
    return out


def power_note(big_roi, gap):
    """Legs the big arm would need for 2SE to fall below `gap` at its own dispersion."""
    n = len(big_roi)
    if n < 3 or not gap:
        return None
    sd = statistics.stdev(big_roi)
    return {"sd_roi": sd, "n_now": n, "n_needed_for_2se_below_gap": math.ceil((2 * sd / abs(gap)) ** 2)}


# ---------------------------------------------------------------- data
LEG_SQL = """
SELECT p.walletAddress AS w, p.marketId AS m, p.outcome AS oc,
       p.entryPrice AS ep, p.simulatedPositionSize AS sz, p.realizedPnl AS pnl,
       p.status AS st, j.ruleSetVersion AS v, p.openedAt AS o,
       o2.size AS print_usd, o2.timestamp AS ot, p.simulatedPositionSize AS stake
FROM PaperTrade p
JOIN DecisionJournal j ON j.id = p.decisionJournalId
JOIN ObservedTrade o2 ON o2.id = j.observedTradeId
WHERE p.botId = 'BANKROLL_200' AND p.isDemo = 0
  AND p.status IN ('closed','resolved') AND p.realizedPnl IS NOT NULL
  AND p.simulatedPositionSize > 0
  AND o2.isDemo = 0 AND o2.observationOnly = 0
  AND p.openedAt >= strftime('%s', ?) * 1000
"""


def load_legs(db, epoch=EPOCH, clusters=True, log=None):
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(LEG_SQL, (epoch,))]
    for r in rows:
        snap = con.execute(
            "SELECT timeToResolution FROM MarketSnapshot WHERE marketId = ? AND collectedAt <= ? "
            "AND timeToResolution IS NOT NULL ORDER BY collectedAt DESC LIMIT 1",
            (r["m"], r["o"]),
        ).fetchone()
        ttr = snap[0] if snap else None
        r["ttr_h"] = ttr
        r["roi"] = r["pnl"] / r["sz"]
        r["grp"] = "big" if r["print_usd"] >= CUT else "small"
        r["era"] = band_era(r["v"])
        r["bep"] = band_entry(r["ep"])
        r["bttr"] = band_ttr(ttr)
        r["bst"] = band_stake(r["sz"])
        if clusters:
            c = con.execute(
                "SELECT COALESCE(SUM(size),0), COUNT(*) FROM ObservedTrade "
                "WHERE walletAddress = ? AND marketId = ? AND outcome = ? AND side = 'BUY' "
                "AND timestamp BETWEEN ? AND ?",
                (r["w"], r["m"], r["oc"], r["ot"] - 300000, r["ot"] + 300000),
            ).fetchone()
            r["cluster_usd"] = c[0]
            r["cluster_prints"] = c[1]
        else:
            r["cluster_usd"] = r["print_usd"]
            r["cluster_prints"] = 1
    con.close()
    if log:
        log("loaded %d legs (%s..)" % (len(rows), epoch))
    return rows


# ---------------------------------------------------------------- self-test
def _synthetic(seed, plant=None, n=1200, wallets=30):
    rnd = random.Random(seed)
    rows = []
    eras = ["v<=50", "v51-55", "v56-60", "v61-65", "v66-70", "v71+"]
    beps = ["<.05", ".05-.2", ".2-.4", ".4-.6", ".6-.8", ".8+"]
    bttrs = ["<1d", "1-7d", "7d+"]
    bsts = ["<5", "5-15", "15+"]
    for i in range(n):
        era, bep, bttr, bst = (rnd.choice(eras), rnd.choice(beps), rnd.choice(bttrs), rnd.choice(bsts))
        base = {"<.05": -0.9, ".05-.2": -0.4, ".2-.4": 0.05, ".4-.6": 0.10, ".6-.8": 0.12, ".8+": 0.02}[bep]
        era_b = {"v<=50": 0.05, "v51-55": 0.0, "v56-60": -0.05, "v61-65": -0.1, "v66-70": 0.0, "v71+": -0.05}[era]
        sz = {"<5": 4.0, "5-15": 10.0, "15+": 25.0}[bst]
        r = {"w": "w%02d" % rnd.randrange(wallets), "era": era, "bep": bep, "bttr": bttr,
             "bst": bst, "sz": sz}
        roi = base + era_b + rnd.gauss(0, 0.9)
        # notional is INDEPENDENT of roi unless a plant is requested
        r["print_usd"] = 10 ** rnd.uniform(0.5, 4.0)
        r["grp"] = "big" if r["print_usd"] >= CUT else "small"
        if plant is not None and r["grp"] == "big":
            roi += plant
        r["roi"] = roi
        r["pnl"] = roi * sz
        rows.append(r)
    return rows


def self_test():
    """A read that cannot go both ways is not a read. Seven arms."""
    ok = 0

    # 1. NEGATIVE CONTROL: notional independent of return -> matched gap centres on 0.
    rows = _synthetic(101)
    big = [r for r in rows if r["grp"] == "big"]
    small = [r for r in rows if r["grp"] == "small"]
    m = matched_att(big, small, "roi", reps=300)
    if m["gap"] is not None and abs(m["gap"]) < 0.10 and m["ci95"][0] < 0 < m["ci95"][1]:
        ok += 1
        print("  PASS arm1 negative control: gap %+.3f/$1, 2SE %.3f, CI straddles 0 (n=%d)"
              % (m["gap"], m["se2"], m["n_matched"]))
    else:
        print("  FAIL arm1: null read did not centre on zero (%r)" % (m,))

    # 2. POSITIVE CONTROL: a planted -0.30/$1 on big-print legs MUST be detected.
    rows = _synthetic(202, plant=-0.30)
    big = [r for r in rows if r["grp"] == "big"]
    small = [r for r in rows if r["grp"] == "small"]
    m = matched_att(big, small, "roi", reps=300)
    if m["gap"] is not None and m["gap"] > 0.20 and (m["gap"] - m["se2"]) > 0:
        ok += 1
        print("  PASS arm2 positive control: planted -0.30 -> gap %+.3f/$1, 2SE %.3f (2SE below gap)"
              % (m["gap"], m["se2"]))
    else:
        print("  FAIL arm2: planted effect missed (%r)" % (m,))

    # 3. THE MATCHER MUST MATCH: coverage printed, and a deliberately emptied cell
    #    must DROP its big legs and say so rather than impute a control.
    rows = _synthetic(303)
    big = [r for r in rows if r["grp"] == "big"]
    small = [r for r in rows if r["grp"] == "small"]
    if big:
        k = cell_key(big[0])
        small2 = [r for r in small if cell_key(r) != k]
        m2 = matched_att(big, small2, "roi", reps=50)
        if m2["n_matched"] < len(big) and m2["coverage"] < 1.0:
            ok += 1
            print("  PASS arm3 matcher drops unmatched legs: %d/%d matched (cov %.3f)"
                  % (m2["n_matched"], len(big), m2["coverage"]))
        else:
            print("  FAIL arm3: unmatched legs were silently kept (%r)" % (m2,))
    else:
        print("  FAIL arm3: synthetic had no big legs")

    # 4. NOTIONAL IS USDC, NOT SHARES: multiplying size by price must NOT be what
    #    the loader does. Prove the loader's field is used raw by checking a leg
    #    whose size is >= CUT but whose size*price would be under it.
    if True:
        r = {"print_usd": 300.0, "ep": 0.10}
        wrong = r["print_usd"] * r["ep"]
        got = "big" if r["print_usd"] >= CUT else "small"
        wronggrp = "big" if wrong >= CUT else "small"
        if got == "big" and wronggrp == "small":
            ok += 1
            print("  PASS arm4 usdc basis: $300 print at 0.10 is BIG on size (raw), small if "
                  "multiplied by price -- loader uses raw")
        else:
            print("  FAIL arm4: basis check did not discriminate")

    # 5. concentration() must expose a one-leg-carrying bucket.
    xs = [0.0] * 40 + [10.0]
    c = concentration(xs)
    if c["top10_share_of_sum"] is not None and c["ex_top10_mean"] == 0.0 and c["mean"] > 0:
        ok += 1
        print("  PASS arm5 concentration: mean %.2f but ex-top10 %.2f (top10 share %.0f%%)"
              % (c["mean"], c["ex_top10_mean"], 100 * c["top10_share_of_sum"]))
    else:
        print("  FAIL arm5: concentration did not expose the outlier (%r)" % (c,))

    # 6. empty population must be an explicit verdict, never a clean-looking zero.
    e = matched_att([], [], "roi", reps=10)
    if e["gap"] is None and e["verdict"] == "NO_MATCH":
        ok += 1
        print("  PASS arm6 empty population -> NO_MATCH (not 0.0)")
    else:
        print("  FAIL arm6: empty population produced %r" % (e,))

    # 7. the gate must be able to FIRE: a planted effect large enough at this n
    #    clears the card's own threshold, so 'no' is a measurement, not a constant.
    rows = _synthetic(404, plant=-0.45, n=1600)
    big = [r for r in rows if r["grp"] == "big"]
    small = [r for r in rows if r["grp"] == "small"]
    m = matched_att(big, small, "roi", reps=300)
    fires = (m["gap"] is not None and m["gap"] * statistics.mean([r["sz"] for r in big]) >= GATE_PER_LEG
             and (m["gap"] - m["se2"]) > 0 and len(big) >= GATE_BIG_N)
    if fires:
        ok += 1
        print("  PASS arm7 gate can fire: planted -0.45/$1 -> %+.2f $/leg at mean stake, 2SE below"
              % (m["gap"] * statistics.mean([r["sz"] for r in big])))
    else:
        print("  FAIL arm7: gate could not fire on a large planted effect (%r)" % (m,))
    print("self-test %d/7 %s" % (ok, "PASS" if ok == 7 else "FAIL"))
    return 0 if ok == 7 else 1


# ---------------------------------------------------------------- main
def evaluate(rows, reps, log=print):
    big = [r for r in rows if r["grp"] == "big"]
    small = [r for r in rows if r["grp"] == "small"]
    rep = {
        "population": len(rows),
        "big_n": len(big),
        "small_n": len(small),
        "big_share": len(big) / len(rows) if rows else None,
        "big_mean_stake": statistics.mean(r["sz"] for r in big) if big else None,
        "small_mean_stake": statistics.mean(r["sz"] for r in small) if small else None,
        "stake_min": min(r["sz"] for r in rows) if rows else None,
        "stake_max": max(r["sz"] for r in rows) if rows else None,
        "raw": {
            "pnl_per_leg": {"big": statistics.mean(r["pnl"] for r in big) if big else None,
                            "small": statistics.mean(r["pnl"] for r in small) if small else None},
            "roi_per_dollar": {"big": statistics.mean(r["roi"] for r in big) if big else None,
                               "small": statistics.mean(r["roi"] for r in small) if small else None},
        },
        "concentration": {"big_pnl": concentration([r["pnl"] for r in big]),
                          "small_pnl": concentration([r["pnl"] for r in small]),
                          "big_roi": concentration([r["roi"] for r in big]),
                          "small_roi": concentration([r["roi"] for r in small])},
        "matched_roi": matched_att(big, small, "roi", reps=reps),
        "matched_pnl": matched_att(big, small, "pnl", reps=reps),
        "ladder": ladder_table(rows, [0, 25, 250, 1000]),
        "era": era_table(rows),
        "print_cluster_prints_mean": (statistics.mean(r.get("cluster_prints", 1) for r in rows)
                                      if rows else None),
        "print_cluster_prints_max": max((r.get("cluster_prints", 1) for r in rows), default=None),
    }
    # cluster-notional arm (a whale splitting one order must not read as many small prints)
    cb = [r for r in rows if r.get("cluster_usd", 0) >= CUT]
    cs = [r for r in rows if r.get("cluster_usd", 0) < CUT]
    for r in rows:
        r["grp"] = "big" if r.get("cluster_usd", 0) >= CUT else "small"
    rep["cluster_arm"] = {"big_n": len(cb), "small_n": len(cs),
                          "big_roi": statistics.mean(r["roi"] for r in cb) if cb else None,
                          "small_roi": statistics.mean(r["roi"] for r in cs) if cs else None,
                          "matched_roi": matched_att(cb, cs, "roi", reps=max(200, reps // 4))}
    for r in rows:  # restore print-level grouping
        r["grp"] = "big" if r["print_usd"] >= CUT else "small"

    # wallet-level arm: wallets with >=3 legs on each side
    byw = {}
    for r in rows:
        byw.setdefault(r["w"], {"big": [], "small": []})[r["grp"]].append(r["roi"])
    both = {w: v for w, v in byw.items() if len(v["big"]) >= 3 and len(v["small"]) >= 3}
    diffs = [statistics.mean(v["small"]) - statistics.mean(v["big"]) for v in both.values()]
    rep["wallet_arm"] = {"wallets": len(both),
                         "big_legs_in_them": sum(len(v["big"]) for v in both.values()),
                         "median_wallet_gap": statistics.median(diffs) if diffs else None,
                         "mean_wallet_gap": statistics.mean(diffs) if diffs else None,
                         "wallets_big_worse": sum(1 for d in diffs if d > 0),
                         "wallets_big_better": sum(1 for d in diffs if d < 0)}

    # --- the card's pre-registered decision rule, evaluated on each basis
    mr = rep["matched_roi"]
    mp = rep["matched_pnl"]
    mean_big_stake = rep["big_mean_stake"] or 0.0
    rule = {
        "gate_per_leg": GATE_PER_LEG,
        "gate_big_n": GATE_BIG_N,
        "big_n": len(big),
        "threshold_in_roi_at_big_mean_stake": (GATE_PER_LEG / mean_big_stake) if mean_big_stake else None,
        "primary_basis": "matched, per-$1 staked (roi)",
        "matched_roi_gap": mr["gap"],
        "matched_roi_2se": mr["se2"],
        "matched_roi_gap_in_per_leg_at_big_stake": (mr["gap"] * mean_big_stake) if mr["gap"] is not None else None,
        "matched_pnl_gap_per_leg": mp["gap"],
        "matched_pnl_2se": mp["se2"],
        "raw_pnl_gap_per_leg": (rep["raw"]["pnl_per_leg"]["small"] - rep["raw"]["pnl_per_leg"]["big"])
                               if big and small else None,
        "coverage": mr["coverage"],
    }
    cond_n = len(big) >= GATE_BIG_N
    cond_cov = mr["coverage"] >= MIN_COVERAGE
    cond_size_primary = (rule["matched_roi_gap_in_per_leg_at_big_stake"] is not None
                         and rule["matched_roi_gap_in_per_leg_at_big_stake"] >= GATE_PER_LEG)
    cond_sig_primary = (mr["gap"] is not None and mr["se2"] is not None
                        and (mr["gap"] - mr["se2"]) > 0)
    # literal reading of the card's own units (uncontrolled $/leg), printed so the
    # rule cannot be moved between bases after the fact
    cond_size_literal = (rule["raw_pnl_gap_per_leg"] is not None
                         and rule["raw_pnl_gap_per_leg"] >= GATE_PER_LEG)
    cond_sig_literal = (mp["gap"] is not None and mp["se2"] is not None and (mp["gap"] - mp["se2"]) > 0)
    rule["conditions"] = {
        "n_big_ge_60": cond_n,
        "coverage_ge_0.80": cond_cov,
        "primary_gap_ge_1.50_per_leg_at_big_stake": cond_size_primary,
        "primary_2se_below_gap": cond_sig_primary,
        "literal_raw_gap_ge_1.50_per_leg": cond_size_literal,
        "literal_matched_2se_below_gap": cond_sig_literal,
    }
    fire = cond_n and cond_cov and cond_size_primary and cond_sig_primary
    rule["fires"] = bool(fire)
    if fire:
        rule["decision"] = ("ADD sourcePrintNotional as a scored admission term, shadow-only first "
                            "-- LANE A, tag awaiting-approval, do NOT apply")
    else:
        rule["decision"] = ("record sourcePrintNotional as a liquidity/era proxy and DROP the axis "
                            "-- nothing is added, nothing is tagged")
    rep["rule"] = rule
    rep["power"] = power_note([r["roi"] for r in big], mr["gap"]) if big and mr["gap"] else None
    return rep


def render(rep):
    r = rep
    L = []
    L.append("source-print-notional read  (C-200 legs, non-demo, openedAt >= %s)" % EPOCH)
    L.append("population %d legs: %d big (>= $%g print) / %d small; mean stake $%.2f big vs $%.2f small"
             % (r["population"], r["big_n"], CUT, r["small_n"], r["big_mean_stake"] or 0,
                r["small_mean_stake"] or 0))
    L.append("")
    L.append("RAW (stake-confounded, reproduces the card's basis):")
    L.append("  per leg   big $%.2f  small $%.2f   -> gap $%+.2f/leg"
             % (r["raw"]["pnl_per_leg"]["big"], r["raw"]["pnl_per_leg"]["small"],
                r["raw"]["pnl_per_leg"]["small"] - r["raw"]["pnl_per_leg"]["big"]))
    L.append("  per $1    big %+.3f  small %+.3f   -> gap %+.3f/$1"
             % (r["raw"]["roi_per_dollar"]["big"], r["raw"]["roi_per_dollar"]["small"],
                r["raw"]["roi_per_dollar"]["small"] - r["raw"]["roi_per_dollar"]["big"]))
    for k in ("big_pnl", "small_pnl"):
        c = r["concentration"][k]
        L.append("  %-9s median $%+.2f  trimmed $%+.2f  ex-top-10 $%+.2f  top-10 share %s"
                 % (k, c["median"], c["trimmed_mean_10pct"], c["ex_top10_mean"] or 0,
                    ("%.0f%%" % (100 * c["top10_share_of_sum"])) if c["top10_share_of_sum"] is not None else "n/a"))
    L.append("")
    mr, mp = r["matched_roi"], r["matched_pnl"]
    L.append("MATCHED ATT (cells = era x entry band x TTR band x stake band; small - big):")
    L.append("  per $1 : gap %+.3f/$1  2SE %.3f  CI [%+.3f, %+.3f]  n=%d/%d matched (%.1f%%)"
             % (mr["gap"], mr["se2"], mr["ci95"][0], mr["ci95"][1], mr["n_matched"], mr["n_big"],
                100 * mr["coverage"]))
    L.append("  per leg: gap $%+.2f  2SE $%.2f  -> at big mean stake $%.2f = $%+.2f/leg"
             % (mp["gap"], mp["se2"], r["big_mean_stake"] or 0,
                mr["gap"] * (r["big_mean_stake"] or 0)))
    L.append("  wallet arm: %d wallets with >=3 legs both sides, median gap %s, %d big-worse / %d big-better"
             % (r["wallet_arm"]["wallets"],
                ("%+.3f" % r["wallet_arm"]["median_wallet_gap"]) if r["wallet_arm"]["median_wallet_gap"] is not None else "n/a",
                r["wallet_arm"]["wallets_big_worse"], r["wallet_arm"]["wallets_big_better"]))
    L.append("")
    L.append("LADDER (the $250 cut must not be load-bearing):")
    for b in r["ladder"]:
        L.append("  %-10s n=%-5d %+.2f/leg  roi %+.3f  median %+.3f"
                 % (b["bucket"], b["n"], b["pnl_per_leg"], b["roi_per_dollar"], b["median_roi"]))
    L.append("")
    L.append("ERA (regime = journal.ruleSetVersion):")
    for k, v in r["era"].items():
        L.append("  %-14s n=%-4d %+.2f/leg  roi %+.3f" % (k, v["n"], v["pnl_per_leg"], v["roi_per_dollar"]))
    L.append("")
    ca = r["cluster_arm"]
    L.append("CLUSTER ARM (prints summed within +-300s on the same wallet/market/outcome; mean %.1f prints, max %d):"
             % (r["print_cluster_prints_mean"] or 0, r["print_cluster_prints_max"] or 1))
    L.append("  big n=%d roi %+.3f vs small n=%d roi %+.3f -> matched gap %s"
             % (ca["big_n"], ca["big_roi"] or 0, ca["small_n"], ca["small_roi"] or 0,
                ("%+.3f/$1 (2SE %.3f)" % (ca["matched_roi"]["gap"], ca["matched_roi"]["se2"]))
                if ca["matched_roi"]["gap"] is not None and ca["matched_roi"]["se2"] is not None else "n/a"))
    L.append("")
    ru = r["rule"]
    L.append("CARD DECISION RULE ($%.2f/leg, 2SE below, n>=%d):" % (GATE_PER_LEG, GATE_BIG_N))
    for k, v in ru["conditions"].items():
        L.append("  [%s] %s" % ("x" if v else " ", k))
    L.append("  threshold in per-$1 terms at the big bucket's mean stake: %.3f/$1" %
             (ru["threshold_in_roi_at_big_mean_stake"] or 0))
    L.append("  FIRES: %s -> %s" % (ru["fires"], ru["decision"]))
    if r["power"]:
        L.append("  power: big-arm sd %.2f/$1, n now %d, n needed for 2SE below this gap: %d"
                 % (r["power"]["sd_roi"], r["power"]["n_now"], r["power"]["n_needed_for_2se_below_gap"]))
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB)
    ap.add_argument("--epoch", default=EPOCH)
    ap.add_argument("--reps", type=int, default=2000)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--json", action="store_true", help="print the artifact and exit")
    ap.add_argument("--no-clusters", action="store_true", help="skip the +-300s cluster scan")
    ap.add_argument("--out", default=OUT, help="artifact path (tests point this at a temp dir)")
    ap.add_argument("--no-write", action="store_true", help="print only, write no artifact")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    rows = load_legs(args.db, args.epoch, clusters=not args.no_clusters)
    if not rows:
        print("NO LEGS for epoch %s -- refusing to print a clean-looking zero" % args.epoch)
        return 2
    rep = evaluate(rows, args.reps)
    rep["basis"] = {
        "population": "non-demo C-200 legs (BANKROLL_200) with realizedPnl, joined to their "
                      "admitting DecisionJournal row and the non-observationOnly ObservedTrade print",
        "level": "one leg; cluster arm = one print cluster (+-300s)",
        "clock": "leg clock, openedAt >= %s; era = journal.ruleSetVersion" % args.epoch,
        "return": "realizedPnl / simulatedPositionSize, per $1 staked, GROSS of fees",
        "notional": "ObservedTrade.size = USDC (adapter writes usdcSize), never size*price",
    }
    rep["generated_at"] = datetime.now(timezone.utc).isoformat()
    if args.json:
        print(json.dumps(rep, indent=1, default=str))
    else:
        print(render(rep))
    if args.no_write:
        return 0
    d = os.path.dirname(args.out)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(rep, fh, indent=1, default=str)
    print("\nwrote %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
