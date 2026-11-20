#!/usr/bin/env python3
"""U2b - does ANY wallet-side feature work as a SELECTOR on the acted book?

CARD (ml-u2b-selector-search), verbatim question:
  "does ANY wallet-side feature separate on the acted book" - the card's promotion bar is
  pre-registered ("top-tercile selection beats price-only with a market-clustered 95% CI
  excluding zero", >=200 own forward legs) and price-only is the comparator.

WHY THIS INSTRUMENT EXISTS AT ALL - the card's three named "not yet priced at leg grain"
candidates were ALL measured before this run, and each answer is cited rather than re-derived:
  - wallet DEPTH          -> wallet-depth-field-clamp, wallet-depth-floor-reread,
                             wallet-depth-ceiling-300-finding (Done; the field is truthful now)
  - realised lag persist. -> wallet-lag-persistence-ranker (Done 2026-11-03: AUC 0.571, REFUTED)
  - per-band specialis.   -> polycopy-concentration-feature-test (Done; specialist vs generalist)
What was NEVER tested is the thing a live selector would actually consume: a wallet feature
computed CAUSALLY from the wallet's own prior resolved book at the leg's open time. Every stored
WalletProfile score is an as-of-print snapshot that overwrites itself, so the U2 read priced
wallet_quality_score with look-ahead baked in - and the lag-persistence card had to carry the same
caveat. This script removes the caveat by construction: a leg's feature value uses ONLY legs of the
same wallet whose terminal timestamp is strictly before that leg's openedAt.

WHAT IS MEASURED (Lane B, READ-ONLY: opens the DB read-only, writes only the JSON it is told to)
  population  PaperTrade legs, isDemo=0, status in (closed, resolved), realizedPnl not null,
              openedAt >= --from (default 2026-09-26, the card's forward clock). One row per leg.
  features    (all causal, same-lane priors, >= --min-prior terminal legs required)
                depth            count of the wallet's prior terminal legs
                prior_mean_pnl   mean realizedPnl per prior leg ($)
                prior_win_rate   share of prior legs with realizedPnl > 0
                prior_roi        sum(realizedPnl)/sum(simulatedPositionSize) on prior legs
                band_excess      wallet's prior mean PnL in THIS leg's entry-price band minus its
                                 prior mean overall (>= --min-band-prior legs in the band)
                recent_mean_pnl  mean of the wallet's last 20 prior legs
  comparator  entry price: copy-all (the whole arm population) AND the literal "price-only"
              selector (top tercile by entryPrice), as the gate text requires both.
  arm         top tercile by feature, cut at leg level AND at wallet level (the feature is a
              wallet attribute, so the wallet-level cut is the faithful reading).
  CI          1000-rep bootstrap clustered on marketId, seed fixed, percentile 2.5/97.5 on the
              difference in mean realizedPnl/leg. The market:leg ratio is printed because when it
              approaches 1 the cluster unit is degenerate and the CI is near-iid.
  verdict     PROMOTE only when, on BOTH tercile bases, (sel - copy-all) and (sel - price-top)
              lower CI bounds are BOTH > 0. Anything else = no selector.
  multiplicity 6 features x 4 contrasts are tested, so a 95% CI alone invites false promotions.
              Every arm's diff/CI is reported alongside a Bonferroni threshold and a
              Benjamini-Hochberg q on the feature-level min p (from the bootstrap share <= 0).
  concentration  median leg, 10%-trimmed mean, ex-top-10 leg sum - printed BEFORE any mean is
              called an edge, because this stack's repeated failure mode is a top-10 artifact.

LABELS: the target is realizedPnl on a leg - money, not a predicted outcome. No outcome label is
used anywhere in this instrument, so the EXIT-vs-SETTLEMENT basis split cannot bite here.

USAGE
  python3 scripts/u2b-selector-search.py                # forward C-200, since 2026-09-26
  python3 scripts/u2b-selector-search.py --bot STANDARD
  python3 scripts/u2b-selector-search.py --all-lanes --json data/u2b-selector-search.json
  python3 scripts/u2b-selector-search.py --self-test    # causality + bootstrap mutation arms
"""
from __future__ import annotations

import argparse
import calendar
import json
import math
import os
import random
import sqlite3
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "prisma", "dev.db")
OUT = os.path.join(ROOT, "data", "u2b-selector-search.json")
FROM_DATE = "2026-09-26T00:00:00Z"
BOOT_REPS = 1000
SEED = 20260926
BANDS = [(0.00, 0.20), (0.20, 0.40), (0.40, 0.60), (0.60, 0.80), (0.80, 1.01)]
FEATURES = [
    "depth",
    "prior_mean_pnl",
    "prior_win_rate",
    "prior_roi",
    "band_excess",
    "recent_mean_pnl",
]


# ---------------------------------------------------------------- data plumbing
def load_legs(db_path, bot):
    """Every terminal leg of one lane: needed BOTH as evaluation population and as prior history."""
    con = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
    try:
        cur = con.execute(
            """
            SELECT walletAddress, marketId, openedAt, closedAt, resolvedAt, realizedPnl,
                   entryPrice, simulatedPositionSize, status
              FROM PaperTrade
             WHERE isDemo = 0
               AND status IN ('closed', 'resolved')
               AND realizedPnl IS NOT NULL
               AND (? IS NULL OR botId = ?)
            """,
            (bot, bot),
        )
        rows = cur.fetchall()
    finally:
        con.close()
    legs = []
    for (wallet, market, opened, closed, resolved, pnl, price, size, status) in rows:
        if opened is None or pnl is None:
            continue
        terminal = resolved if resolved is not None else closed
        if terminal is None:
            terminal = opened
        legs.append({
            "wallet": (wallet or "?").lower(),
            "market": market or "?",
            "opened": int(opened),
            "terminal": int(terminal),
            "pnl": float(pnl),
            "price": float(price if price is not None else 0.0),
            "size": float(size if size is not None else 0.0),
            "status": status,
        })
    legs.sort(key=lambda r: r["opened"])
    return legs


def band_of(price):
    for lo, hi in BANDS:
        if lo <= price < hi:
            return "%0.2f-%0.2f" % (lo, hi)
    return "%0.2f-%0.2f" % BANDS[-1] if price >= BANDS[-1][0] else BANDS[0]


def attach_causal_features(legs, min_prior, min_band_prior):
    """For every leg, compute the wallet's prior-book statistics from STRICTLY earlier terminals.

    Causality is the whole point: `prior` is filtered by terminal < this leg's openedAt, so a leg
    can never see itself, a later leg, or a leg that resolved after it opened.
    """
    by_wallet = {}
    for r in legs:
        by_wallet.setdefault(r["wallet"], []).append(r)

    for r in legs:
        prior = [p for p in by_wallet[r["wallet"]] if p["terminal"] < r["opened"]]
        r["prior_n"] = len(prior)
        if len(prior) < min_prior:
            for f in FEATURES:
                r[f] = None
            r["prior_mean_pnl"] = None
            continue
        pnls = [p["pnl"] for p in prior]
        sizes = [p["size"] for p in prior]
        r["depth"] = float(len(prior))
        r["prior_mean_pnl"] = sum(pnls) / len(pnls)
        r["prior_win_rate"] = sum(1 for v in pnls if v > 0) / len(pnls)
        cost = sum(sizes)
        r["prior_roi"] = (sum(pnls) / cost) if cost > 0 else None
        recent = pnls[-20:]
        r["recent_mean_pnl"] = sum(recent) / len(recent)
        band = band_of(r["price"])
        in_band = [p["pnl"] for p in prior if band_of(p["price"]) == band]
        r["band_n"] = len(in_band)
        if len(in_band) >= min_band_prior:
            r["band_excess"] = (sum(in_band) / len(in_band)) - r["prior_mean_pnl"]
        else:
            r["band_excess"] = None
    return legs


# ------------------------------------------------------------------ statistics
def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def trimmed_mean(xs, frac=0.10):
    if not xs:
        return float("nan")
    ys = sorted(xs)
    k = int(len(ys) * frac)
    core = ys[k:len(ys) - k] if len(ys) > 2 * k else ys
    return mean(core)


def tercile_cuts(vals):
    vals = sorted(vals)
    n = len(vals)
    return vals[int(n / 3)], vals[int(2 * n / 3)]


def cluster_bootstrap_diff(rows, sel, refs, reps=BOOT_REPS, seed=SEED):
    """Difference in mean pnl/leg (sel - ref) resampling MARKETS with replacement."""
    by_market = {}
    for r in rows:
        by_market.setdefault(r["market"], []).append(r)
    markets = list(by_market)
    rng = random.Random(seed)
    diffs = []
    for _ in range(reps):
        pick = [markets[rng.randrange(len(markets))] for _ in markets]
        picked = []
        for m in pick:
            picked.extend(by_market[m])
        a = [r["pnl"] for r in picked if sel(r)]
        b = [r["pnl"] for r in picked if refs(r)]
        if a and b:
            diffs.append(mean(a) - mean(b))
    if not diffs:
        return {"diff": float("nan"), "lo": float("nan"), "hi": float("nan"),
                "share_le0": float("nan"), "reps": 0}
    diffs.sort()
    lo = diffs[int(0.025 * len(diffs))]
    hi = diffs[int(0.975 * len(diffs)) - 1]
    return {
        "diff": mean([r["pnl"] for r in rows if sel(r)]) - mean([r["pnl"] for r in rows if refs(r)]),
        "lo": lo,
        "hi": hi,
        "share_le0": sum(1 for d in diffs if d <= 0) / len(diffs),
        "reps": len(diffs),
    }


def bh(pvals):
    """Benjamini-Hochberg q values, order preserved."""
    idx = sorted(range(len(pvals)), key=lambda i: pvals[i])
    m = len(pvals)
    q = [1.0] * m
    prev = 1.0
    for rank in range(m - 1, -1, -1):
        i = idx[rank]
        val = min(prev, pvals[i] * m / (rank + 1))
        q[i] = val
        prev = val
    return q


# ---------------------------------------------------------------------- the read
def run(legs, args, label):
    pop = [r for r in legs if r["opened"] >= args.from_ms]
    covered = [r for r in pop if r.get("prior_mean_pnl") is not None]

    out = {
        "label": label,
        "basis": {
            "population": "PaperTrade legs isDemo=0 status in (closed,resolved) realizedPnl not null",
            "clock": "openedAt UTC >= %s" % args.from_date,
            "level": "one leg",
            "target": "realizedPnl USD on the leg (money, not an outcome label)",
            "features": "causal: same-wallet legs with terminalAt < this leg's openedAt",
            "min_prior_legs": args.min_prior,
            "min_band_prior_legs": args.min_band_prior,
        },
        "n_legs": len(pop),
        "n_markets": len({r["market"] for r in pop}),
        "n_wallets": len({r["wallet"] for r in pop}),
        "n_covered": len(covered),
        "coverage_pct": 100.0 * len(covered) / len(pop) if pop else 0.0,
        "date_range": [],
        "book": {},
        "arms": {},
    }
    if pop:
        out["date_range"] = [
            time.strftime("%Y-%m-%d", time.gmtime(min(r["opened"] for r in pop) / 1000)),
            time.strftime("%Y-%m-%d", time.gmtime(max(r["opened"] for r in pop) / 1000)),
        ]
        pnls = [r["pnl"] for r in pop]
        out["book"] = {
            "mean_pnl_per_leg": mean(pnls),
            "median_pnl_per_leg": statistics.median(pnls),
            "trimmed_mean_10pct": trimmed_mean(pnls),
            "sum_pnl": sum(pnls),
            "ex_top10_sum": sum(sorted(pnls)[:-10]) if len(pnls) > 10 else float("nan"),
            "win_rate": sum(1 for v in pnls if v > 0) / len(pnls),
            "markets_per_leg": (len({r["market"] for r in pop}) / len(pop)) if pop else float("nan"),
        }
    if len(covered) < args.min_legs:
        out["verdict"] = "UNDERPOWERED: %d covered legs < %d required" % (len(covered), args.min_legs)
        return out

    price_hi, _ = tercile_cuts([r["price"] for r in covered])
    price_top = lambda r: r["price"] >= price_hi
    copy_all = lambda r: True
    out["price_top_cut"] = price_hi
    out["reference_arms"] = {
        "copy_all": mean([r["pnl"] for r in covered]),
        "top_tercile_entry_price": mean([r["pnl"] for r in covered if price_top(r)]),
        "n_price_top": sum(1 for r in covered if price_top(r)),
    }

    pvals = []
    for feat_idx, feat in enumerate(FEATURES):
        rows = [r for r in covered if r.get(feat) is not None]
        if len(rows) < args.min_legs:
            out["arms"][feat] = {"skipped": "n=%d below min-legs %d" % (len(rows), args.min_legs),
                                 "n": len(rows)}
            pvals.append(1.0)
            continue
        cut_lo, cut_hi = tercile_cuts([r[feat] for r in rows])
        wvals = {}
        for r in rows:
            wvals.setdefault(r["wallet"], []).append(r[feat])
        wmean = {w: mean(v) for w, v in wvals.items()}
        if len(wmean) >= 3:
            _, w_hi = tercile_cuts(list(wmean.values()))
        else:
            w_hi = float("inf")

        top = lambda r, c=cut_hi: r[feat] >= c
        wtop = lambda r, c=w_hi, wm=wmean: wm.get(r["wallet"], float("-inf")) >= c
        g = {}
        g["leglevel_vs_copy_all"] = cluster_bootstrap_diff(rows, top, copy_all, seed=SEED + feat_idx)
        g["leglevel_vs_price_top"] = cluster_bootstrap_diff(rows, top, price_top, seed=SEED + 100 + feat_idx)
        g["walletlevel_vs_copy_all"] = cluster_bootstrap_diff(rows, wtop, copy_all, seed=SEED + 200 + feat_idx)
        g["walletlevel_vs_price_top"] = cluster_bootstrap_diff(rows, wtop, price_top, seed=SEED + 300 + feat_idx)
        sel_pnls = [r["pnl"] for r in rows if top(r)]
        promote = (g["leglevel_vs_copy_all"]["lo"] > 0 and g["leglevel_vs_price_top"]["lo"] > 0
                   and g["walletlevel_vs_copy_all"]["lo"] > 0
                   and g["walletlevel_vs_price_top"]["lo"] > 0)
        min_p = min(g[k]["share_le0"] for k in g)
        pvals.append(min_p)
        out["arms"][feat] = {
            "n": len(rows),
            "n_wallets": len(wmean),
            "n_top_leglevel": len(sel_pnls),
            "n_top_walletlevel": sum(1 for r in rows if wtop(r)),
            "cut_hi": cut_hi,
            "cut_lo": cut_lo,
            "wallet_cut_hi": w_hi if math.isfinite(w_hi) else None,
            "mean_top": mean(sel_pnls),
            "median_top": statistics.median(sel_pnls) if sel_pnls else float("nan"),
            "trimmed_top": trimmed_mean(sel_pnls),
            "ex_top10_top": (sum(sorted(sel_pnls)[:-10]) if len(sel_pnls) > 10 else float("nan")),
            "gates": g,
            "promote": bool(promote),
            "min_p": min_p,
        }

    qs = bh(pvals)
    bonferroni = 0.05 / len(FEATURES)
    for feat, q in zip(FEATURES, qs):
        if feat in out["arms"]:
            out["arms"][feat]["bh_q"] = q
    out["multiplicity"] = {
        "features_tested": len(FEATURES),
        "contrasts_per_feature": 4,
        "bonferroni_alpha": bonferroni,
        "bonferroni_significant": [f for f, q in zip(FEATURES, qs) if q <= 0.05],
        "note": "q is BH over each feature's min bootstrap share<=0; a single 95% CI is not evidence at this width",
    }
    out["promote_any"] = any(v.get("promote") for v in out["arms"].values())
    out["verdict"] = ("PROMOTE %s" % [f for f, v in out["arms"].items() if v.get("promote")]
                      if out["promote_any"] else "NO SELECTOR")
    return out


# ------------------------------------------------------------------- self-test
def self_test():
    """Two arms that must hold, else the script's numbers mean nothing.

    A. CAUSALITY: a leg must never see its own PnL or a later leg's.
    B. MUTATION: a feature with a planted, real edge must PROMOTE; the same population with the
       feature shuffled must NOT. If B passes while A fails we are measuring luck.
    """
    fails = []
    base = 1600000000000
    day = 86400000

    # A. causality
    legs = [
        {"wallet": "w1", "market": "m1", "opened": base, "terminal": base + day, "pnl": 5.0,
         "price": 0.5, "size": 10.0, "status": "resolved"},
        {"wallet": "w1", "market": "m2", "opened": base + 2 * day, "terminal": base + 3 * day,
         "pnl": 1000.0, "price": 0.5, "size": 10.0, "status": "resolved"},
        {"wallet": "w1", "market": "m3", "opened": base + 2 * day, "terminal": base + 3 * day,
         "pnl": -1.0, "price": 0.5, "size": 10.0, "status": "resolved"},
    ]
    attach_causal_features(legs, 1, 1)
    if legs[1]["prior_mean_pnl"] != 5.0:
        fails.append("A: leg saw a same-instant sibling (prior_mean_pnl=%r)" % legs[1]["prior_mean_pnl"])
    if legs[0].get("prior_mean_pnl") is not None:
        fails.append("A: first leg got a prior it cannot have")

    # B. mutation - planted edge at wallet level
    rng = random.Random(7)
    syn = []
    for w in range(40):
        skill = 1.0 if w < 13 else -1.0
        for k in range(12):
            syn.append({"wallet": "w%02d" % w, "market": "m%d-%d" % (w, k),
                        "opened": base + (k + 1) * day, "terminal": base + (k + 1) * day + 3600000,
                        "pnl": skill + rng.gauss(0, 0.15), "price": 0.5, "size": 10.0,
                        "status": "resolved"})
    syn.sort(key=lambda r: r["opened"])
    attach_causal_features(syn, 1, 1)
    pop = [r for r in syn if r["prior_mean_pnl"] is not None]
    cut_lo, cut_hi = tercile_cuts([r["prior_mean_pnl"] for r in pop])
    top = lambda r, c=cut_hi: r["prior_mean_pnl"] >= c
    gate = cluster_bootstrap_diff(pop, top, lambda r: True, reps=200)
    if not (gate["lo"] > 0):
        fails.append("B: planted edge did not clear the gate (CI [%.3f,%.3f])" % (gate["lo"], gate["hi"]))
    rng2 = random.Random(11)
    keep = [r["prior_mean_pnl"] for r in pop]
    rng2.shuffle(keep)
    for r, v in zip(pop, keep):
        r["prior_mean_pnl"] = v
    _, cut_hi2 = tercile_cuts([r["prior_mean_pnl"] for r in pop])
    top2 = lambda r, c=cut_hi2: r["prior_mean_pnl"] >= c
    gate2 = cluster_bootstrap_diff(pop, top2, lambda r: True, reps=200)
    if gate2["lo"] > 0:
        fails.append("B: SHUFFLED feature still promoted - the gate is not reading the feature")

    print("SELF-TEST")
    print("  A causality: %s" % ("PASS" if not any(f.startswith("A") for f in fails) else "FAIL"))
    print("  B mutation : %s  (planted CI [%.3f,%.3f] / shuffled CI [%.3f,%.3f])"
          % ("PASS" if not any(f.startswith("B") for f in fails) else "FAIL",
             gate["lo"], gate["hi"], gate2["lo"], gate2["hi"]))
    for f in fails:
        print("  FAIL:", f)
    return 0 if not fails else 1


# ------------------------------------------------------------------------ main
def assert_coverage_plausible(legs, label):
    """Refuse to publish a 0% causal coverage when the lane plainly has prior history.

    The failure this guards against actually happened on the first run of this script (the feature
    attachment was not called), and it printed as UNDERPOWERED rather than as a bug. A selector read
    that silently finds no history states the OPPOSITE of the truth, so it is fatal here.
    """
    with_history = sum(1 for r in legs if r.get("prior_n", 0) > 0)
    if legs and with_history == 0:
        raise SystemExit(
            "FATAL: %s - %d legs loaded but 0 carry any prior history. The causal feature "
            "attachment did not run or the clock is wrong; refusing to publish a number." %
            (label, len(legs)))


def pct(v):
    return "n/a" if v is None or (isinstance(v, float) and math.isnan(v)) else "%+.3f" % v


def render(res):
    print("\n=== %s ===" % res["label"])
    b = res["basis"]
    print("BASIS: pop=%s | clock=%s | level=%s | target=%s" %
          ("PaperTrade acted legs", b["clock"], b["level"], "realizedPnl USD"))
    print("legs %d | markets %d (%.2f markets/leg) | wallets %d | %s..%s"
          % (res["n_legs"], res["n_markets"], res["n_markets"] / max(res["n_legs"], 1),
             res["n_wallets"], res["date_range"][0] if res["date_range"] else "?",
             res["date_range"][1] if res["date_range"] else "?"))
    bk = res.get("book") or {}
    if bk:
        print("book: mean %s/leg | median %s | trim10 %s | sum %s | ex-top10 %s | win %.3f"
              % (pct(bk["mean_pnl_per_leg"]), pct(bk["median_pnl_per_leg"]),
                 pct(bk["trimmed_mean_10pct"]), pct(bk["sum_pnl"]), pct(bk["ex_top10_sum"]),
                 bk["win_rate"]))
    print("causal coverage: %d/%d legs (%.1f%%) have a usable prior book"
          % (res["n_covered"], res["n_legs"], res["coverage_pct"]))
    if "verdict" in res and res["verdict"].startswith("UNDERPOWERED"):
        print(res["verdict"])
        return
    ref = res["reference_arms"]
    print("reference: copy-all %s/leg | top-tercile entry price %s/leg (n=%d, cut %.3f)"
          % (pct(ref["copy_all"]), pct(ref["top_tercile_entry_price"]), ref["n_price_top"],
             res["price_top_cut"]))
    print("%-16s %5s %8s %8s %8s  %-26s %-26s %s"
          % ("feature", "n", "top", "vs all", "vs px", "CI vs all", "CI vs px", "promote"))
    for feat in FEATURES:
        a = res["arms"].get(feat) or {}
        if "skipped" in a:
            print("%-16s %5d  skipped: %s" % (feat, a["n"], a["skipped"]))
            continue
        ga = a["gates"]["leglevel_vs_copy_all"]
        gb = a["gates"]["leglevel_vs_price_top"]
        print("%-16s %5d %8s %8s %8s  [%+8.3f,%+8.3f] [%+8.3f,%+8.3f] %s q=%.3f"
              % (feat, a["n"], pct(a["mean_top"]), pct(ga["diff"]), pct(gb["diff"]),
                 ga["lo"], ga["hi"], gb["lo"], gb["hi"],
                 "PROMOTE" if a["promote"] else "no", a["bh_q"]))
    print("VERDICT: %s" % res["verdict"])
    m = res["multiplicity"]
    print("multiplicity: %d features x %d contrasts | Bonferroni alpha %.4f | BH-significant: %s"
          % (m["features_tested"], m["contrasts_per_feature"], m["bonferroni_alpha"],
             m["bonferroni_significant"] or "none"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB)
    ap.add_argument("--bot", default="BANKROLL_200")
    ap.add_argument("--all-lanes", action="store_true")
    ap.add_argument("--from", dest="from_date", default=FROM_DATE)
    ap.add_argument("--min-prior", type=int, default=5)
    ap.add_argument("--min-band-prior", type=int, default=5)
    ap.add_argument("--min-legs", type=int, default=200)
    ap.add_argument("--json", default=None)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    t = time.strptime(args.from_date, "%Y-%m-%dT%H:%M:%SZ")
    args.from_ms = calendar.timegm(t) * 1000

    runs = []

    def read_lane(bot, label):
        legs = load_legs(args.db, bot)
        # DEFECT FIXED BEFORE FIRST REAL RUN (2026-11-19): the first version handed the RAW legs to
        # run() without attach_causal_features(), so every leg reported prior_mean_pnl=None and the
        # instrument printed "causal coverage 0/857 (0.0%)" -> UNDERPOWERED. A silent zero here
        # reads as "no wallet has a prior book", which is false; run() therefore now refuses to
        # answer on 0% coverage when the lane HAS prior history (see assert_coverage_plausible).
        legs = attach_causal_features(legs, args.min_prior, args.min_band_prior)
        assert_coverage_plausible(legs, label)
        return run(legs, args, label)

    if args.all_lanes:
        runs.append(read_lane(None, "forward ALL LANES, opened >= %s" % args.from_date))
    else:
        runs.append(read_lane(args.bot, "forward %s, opened >= %s" % (args.bot, args.from_date)))
        other = "STANDARD" if args.bot != "STANDARD" else "BANKROLL_200"
        runs.append(read_lane(other, "forward %s (secondary), opened >= %s" % (other, args.from_date)))
    for r in runs:
        render(r)

    out = args.json or OUT
    with open(out, "w") as fh:
        json.dump({"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "db": os.path.relpath(args.db, ROOT),
                   "bootstrap": {"unit": "marketId", "reps": BOOT_REPS, "seed": SEED},
                   "runs": runs}, fh, indent=1)
    print("\nwrote %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
