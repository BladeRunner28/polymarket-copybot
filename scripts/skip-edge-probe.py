#!/usr/bin/env python3
"""Skip-set edge probe — do the signals the gates REJECT carry a price-relative edge?

WHY: 82% of all decisions are `skip` (222k rows) and none of them carry a label, so the
ML-1 training set only ever sees the trades the current rules already chose. This probe
labels the skipped set counterfactually and measures the edge we walked away from.

METHOD (read-only against prisma/dev.db; no network, no live-path change)
  * entry price  = last MarketSnapshot at/before the decision time for that marketId
                   (NO leg -> 1 - yesPrice; the same binary relation the venue uses)
  * winner       = the LAST MarketSnapshot yesPrice for that market: >=0.98 => the YES
                   token won, <=0.02 => NO won, anything else = unresolved, excluded
  * VALIDATION   = the proxy is checked against ground truth first: settled
                   status='resolved' paper trades carry both an outcome label and a PnL
                   sign, so they say which leg really won. Binary legs only.
  * edge/share   = won - entry - fee_per_share(entry)
                   fee_per_share = rate * p * (1-p), rate by category keyword
                   (crypto .07 / politics+finance .04 / else .05, as in
                   scripts/build-decision-dataset.py)
  * CIs          = market-clustered bootstrap (decisions cluster inside markets: ~4.8
                   decisions per market here). Row-level CIs are meaningless on this data.

CAVEAT THIS PROBE CANNOT REMOVE: the skip side is exit-blind — it holds to resolution.
Live copies are additionally subject to the exit rules, and `closed` (early-exit) trades
are excluded from the copy-side comparison because their realizedPnl is not a resolution
outcome. The two sides are therefore not directly comparable; read each against its own
zero.

Usage:  python3 scripts/skip-edge-probe.py [--out data/skip-edge-probe-<date>.json]
"""
import argparse
import csv
import json
import sqlite3
import sys
import time
from bisect import bisect_right
from collections import defaultdict

import numpy as np

DB = "file:prisma/dev.db?mode=ro"
HYPOTHETICAL_SIZE = 10.0

FEE_CRYPTO, FEE_POLFIN, FEE_DEFAULT = 0.07, 0.04, 0.05
CRYPTO_KW = ("btc", "bitcoin", "eth", "ethereum", "solana", "crypto", "token", "airdrop", "fdv", "market cap")
POLFIN_KW = ("election", "president", "senate", "congress", "nominee", "parliament", "prime minister",
             "fed", "rate cut", "inflation", "cpi", "gdp", "recession", "tariff", "stock", "nasdaq",
             "s&p", "earnings", "shutdown", "impeach", "poll", "vote", "governor", "mayor")
PROXY_HI, PROXY_LO = 0.98, 0.02


def fee_rate(question):
    ql = (question or "").lower()
    if any(k in ql for k in CRYPTO_KW):
        return FEE_CRYPTO
    if any(k in ql for k in POLFIN_KW):
        return FEE_POLFIN
    return FEE_DEFAULT


def auc(score, target):
    """Rank AUC with tie handling."""
    o = np.argsort(score, kind="mergesort")
    s, t = score[o], target[o]
    r = np.empty(len(s))
    i = 0
    while i < len(s):
        j = i
        while j + 1 < len(s) and s[j + 1] == s[i]:
            j += 1
        r[i:j + 1] = (i + j) / 2.0 + 1.0
        i = j + 1
    npos, nneg = t.sum(), (1 - t).sum()
    if npos == 0 or nneg == 0:
        return float("nan")
    return float((r[t == 1].sum() - npos * (npos + 1) / 2.0) / (npos * nneg))


def cluster_boot(x, cluster, n=800, seed=11):
    """95% CI of the mean, resampling CLUSTERS (markets), not rows."""
    rng = np.random.default_rng(seed)
    groups = defaultdict(list)
    for i, c in enumerate(cluster):
        groups[c].append(i)
    keys = list(groups)
    vals = []
    for _ in range(n):
        pick = rng.choice(len(keys), len(keys), replace=True)
        idx = np.concatenate([groups[keys[k]] for k in pick])
        vals.append(x[idx].mean())
    v = np.array(vals)
    return float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB,
                    help="sqlite URI or path; point at a snapshot copy to avoid lock waits")
    ap.add_argument("--cache", help="optional CSV cache path for the built rows")
    ap.add_argument("--out", default="data/skip-edge-probe.json")
    args = ap.parse_args()

    db_uri = args.db if args.db.startswith("file:") else f"file:{args.db}?mode=ro"
    c = sqlite3.connect(db_uri, uri=True, timeout=600)
    q = c.execute
    # The live bot writes to this DB (monitor every 10 min, PnL hourly), so a read can hit
    # SQLITE_BUSY mid-run. Wait on the writer, and retry the query if it still loses.
    q("PRAGMA busy_timeout=600000")

    def fetch(sql, params=()):
        last = None
        for attempt in range(6):
            try:
                return q(sql, params).fetchall()
            except sqlite3.OperationalError as e:      # database is locked
                last = e
                print(f"    [retry {attempt+1}] {e}", flush=True)
                time.sleep(5 * (attempt + 1))
        raise RuntimeError(f"query kept failing: {last}")

    summary = {}

    # ---------------------------------------------------------- validate the proxy
    print("=== validating the terminal-price resolution proxy ===")
    gt = fetch("""SELECT t.marketId, t.outcome, t.realizedPnl FROM PaperTrade t
                  WHERE t.isDemo=0 AND t.status='resolved' AND t.realizedPnl IS NOT NULL
                    AND t.entryPrice>0 AND t.entryPrice<1""")
    by_market = defaultdict(list)
    for mid, outcome, pnl in gt:
        by_market[mid].append((str(outcome).strip().upper(), float(pnl)))
    term = {mid: yp for mid, yp in fetch("""
        SELECT m.marketId, m.yesPrice FROM MarketSnapshot m
        JOIN (SELECT marketId, MAX(collectedAt) c FROM MarketSnapshot GROUP BY marketId) t
          ON t.marketId=m.marketId AND t.c=m.collectedAt""")}
    agree = disagree = 0
    for mid, legs in by_market.items():
        tp = term.get(mid)
        if tp is None or not (tp >= PROXY_HI or tp <= PROXY_LO):
            continue
        winners = [lbl for lbl, pnl in legs if pnl > 0]
        if len(winners) != 1 or winners[0] not in ("YES", "NO"):
            continue
        pred = "YES" if tp >= PROXY_HI else "NO"
        agree += pred == winners[0]
        disagree += pred != winners[0]
    print(f"  settled trades {len(gt)} | markets {len(by_market)} | binary ground truth: agree {agree}, disagree {disagree}")
    summary["proxy_validation"] = {"agree": agree, "disagree": disagree}
    if disagree:
        print("  WARNING: proxy disagrees with ground truth — do not trust the labels below", file=sys.stderr)

    # ------------------------------------------------------------ build skip rows
    print("=== building skip rows (per-market snapshot bisect) ===")
    dec = fetch("""SELECT d.id, d.marketId, d.createdAt, d.walletAddress, d.copyScore, d.confidence,
                      d.walletQualityScore, d.roiScore, d.consistencyScore, d.copyabilityScore,
                      d.categoryFitScore, d.entryTimingScore, d.spreadScore, d.liquidityScore,
                      d.thesisScore, d.ruleSetVersion,
                      o.outcome, o.detectedPrice, o.marketQuestion
               FROM DecisionJournal d JOIN ObservedTrade o ON o.id=d.observedTradeId
               WHERE d.decision='skip'""")
    groups = defaultdict(list)
    for r in dec:
        groups[r[1]].append(r)
    print(f"  skip decisions {len(dec)} across {len(groups)} markets")

    rows = []
    t0 = time.time()
    for i, (mid, drows) in enumerate(groups.items()):
        snaps = fetch("SELECT collectedAt, yesPrice FROM MarketSnapshot WHERE marketId=? ORDER BY collectedAt", (mid,))
        if not snaps:
            continue
        ts = [s[0] for s in snaps]
        px = [s[1] for s in snaps]
        last = px[-1]
        for r in drows:
            (did, _m, created, wallet, cscore, conf, wq, roi, cons, copyab, catfit, timing,
             spread, liq, thesis, rv, outcome, detpx, question) = r
            j = bisect_right(ts, created) - 1
            if j < 0 or px[j] is None:
                continue
            lbl = str(outcome or "").strip().upper()
            entry = px[j] if lbl == "YES" else (1.0 - px[j] if lbl == "NO" else None)
            rows.append({"decision_id": did, "market_id": mid, "wallet": wallet, "outcome": lbl,
                         "entry": entry, "terminal_yes": last,
                         "copy_score": cscore, "confidence": conf, "wallet_quality": wq, "roi_score": roi,
                         "consistency": cons, "copyability": copyab, "category_fit": catfit,
                         "entry_timing": timing, "spread_score": spread, "liquidity_score": liq,
                         "thesis_score": thesis, "rule_set_version": rv, "detected_price": detpx,
                         "fee_rate": fee_rate(question)})
        if (i + 1) % 10000 == 0:
            print(f"    {i+1}/{len(groups)} markets, {len(rows)} rows, {time.time()-t0:.0f}s", flush=True)
    print(f"  built {len(rows)} rows in {time.time()-t0:.0f}s")
    summary["rows_built"] = len(rows)

    if args.cache:
        with open(args.cache, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            for r in rows:
                w.writerow({k: ("" if v is None else v) for k, v in r.items()})
        print(f"  cached -> {args.cache}")

    # ------------------------------------------------------------------ labeling
    skip, dropped, named, undecided = [], [], 0, 0
    for r in rows:
        if r["entry"] is None:
            named += 1
            continue
        tp = r["terminal_yes"]
        if tp is None or not (tp >= PROXY_HI or tp <= PROXY_LO):
            undecided += 1
            continue
        won = 1.0 if ((r["outcome"] == "YES" and tp >= PROXY_HI) or (r["outcome"] == "NO" and tp <= PROXY_LO)) else 0.0
        e = r["entry"]
        rate = r["fee_rate"]
        rec = dict(r, won=won, edge=won - e - rate * e * (1 - e))
        (skip if 0.005 <= e <= 0.995 else dropped).append(rec)

    print("\n=== coverage ===")
    print(f"  rows built                     : {len(rows)}")
    print(f"  named-token legs (need labels) : {named}")
    print(f"  binary but terminal undecided  : {undecided}")
    print(f"  decisive binary                : {len(skip)+len(dropped)}")
    print(f"    usable 0.005<=price<=0.995   : {len(skip)}")
    print(f"    already-decided at entry     : {len(dropped)}")
    summary["coverage"] = {"rows": len(rows), "named_token_legs": named,
                           "terminal_undecided": undecided, "usable": len(skip),
                           "already_decided_at_entry": len(dropped)}

    E = np.array([r["edge"] for r in skip]); W = np.array([r["won"] for r in skip])
    P = np.array([r["entry"] for r in skip]); M = [r["market_id"] for r in skip]
    RV = np.array([r["rule_set_version"] if r["rule_set_version"] is not None else -1 for r in skip], float)
    lo, hi = cluster_boot(E, M)
    print("\n=== SKIP SET (exit-blind, held to resolution) ===")
    print(f"  n={len(E)} markets={len(set(M))} wallets={len({r['wallet'] for r in skip})}")
    print(f"  win rate {W.mean():.4f} | mean entry {P.mean():.4f}")
    print(f"  mean edge/share {E.mean():+.5f}  95% CI [{lo:+.5f}, {hi:+.5f}] (market-clustered)")
    print(f"  hypothetical ${HYPOTHETICAL_SIZE:.0f}/trade: {HYPOTHETICAL_SIZE*E.mean():+.3f}")
    summary["skip_set"] = {"n": len(E), "win_rate": float(W.mean()), "mean_entry": float(P.mean()),
                           "edge_per_share": float(E.mean()), "ci": [lo, hi],
                           "per_10usd": float(HYPOTHETICAL_SIZE * E.mean())}

    # ------------------------------------------------------------- copy comparison
    copies = fetch("""SELECT t.entryPrice, t.realizedPnl, t.marketId FROM PaperTrade t
                      WHERE t.isDemo=0 AND t.status='resolved' AND t.realizedPnl IS NOT NULL
                        AND t.entryPrice>0 AND t.entryPrice<1""")
    C = np.array([(1.0 if p > 0 else 0.0) - e - FEE_DEFAULT * e * (1 - e) for e, p, _ in copies])
    CP = np.array([e for e, _, _ in copies])
    clo, chi = cluster_boot(C, [m for _, _, m in copies])
    print("\n=== TAKEN SET (copies, status='resolved' — same resolution semantics, early exits excluded) ===")
    print(f"  n={len(C)}  win rate {np.mean([1.0 if p>0 else 0.0 for _, p, _ in copies]):.4f}  mean entry {CP.mean():.4f}")
    print(f"  mean edge/share {C.mean():+.5f}  95% CI [{clo:+.5f}, {chi:+.5f}]")
    print("  NOTE: resolved-only is winner-enriched (losers get cut to status='closed'), so this is an upper bound.")
    summary["taken_set"] = {"n": len(C), "edge_per_share": float(C.mean()), "ci": [clo, chi],
                            "mean_entry": float(CP.mean()),
                            "caveat": "resolved-only is winner-enriched by the early-exit rule"}

    # ----------------------------------------------------------------- calibration
    print("\n=== skip-set calibration by price band ===")
    print(f"  {'band':>11} {'n':>8} {'mkt':>6} {'winrate':>8} {'price':>7} {'edge/sh':>9} {'CI':>20} {'$10':>7}")
    bands_out = []
    for a, b in ((0.0, .05), (.05, .10), (.10, .20), (.20, .35), (.35, .50),
                 (.50, .65), (.65, .80), (.80, .90), (.90, .95), (.95, 1.0)):
        sel = np.where((P >= a) & (P < b if b < 1.0 else P <= b))[0]
        if len(sel) < 30:
            continue
        sub = E[sel]; blo, bhi = cluster_boot(sub, [M[i] for i in sel])
        mk = len({M[i] for i in sel})
        print(f"  {a:.2f}-{b:.2f} {len(sel):>8,} {mk:>6,} {W[sel].mean():>8.3f} {P[sel].mean():>7.3f} "
              f"{sub.mean():>+9.4f} [{blo:+.4f},{bhi:+.4f}] {HYPOTHETICAL_SIZE*sub.mean():>+7.2f}")
        bands_out.append({"band": [a, b], "n": int(len(sel)), "markets": mk, "win_rate": float(W[sel].mean()),
                          "mean_entry": float(P[sel].mean()), "edge_per_share": float(sub.mean()),
                          "ci": [blo, bhi]})
    summary["bands"] = bands_out

    # ------------------------------------------------------------------------ eras
    print("\n=== by rule era (the live regime is v49+) ===")
    eras = {}
    for lo_, hi_, lbl in ((0, 48, "v1-v48 (pre-live)"), (49, 999, "v49+ (live regime)")):
        sel = np.where((RV >= lo_) & (RV <= hi_))[0]
        if len(sel) < 30:
            continue
        sub = E[sel]; elo, ehi = cluster_boot(sub, [M[i] for i in sel])
        print(f"  {lbl:20} n={len(sel):>7,} winrate {W[sel].mean():.3f} price {P[sel].mean():.3f} "
              f"edge/sh {sub.mean():+.4f} CI [{elo:+.4f},{ehi:+.4f}] $10 {HYPOTHETICAL_SIZE*sub.mean():+.2f}")
        eras[lbl] = {"n": int(len(sel)), "win_rate": float(W[sel].mean()), "mean_entry": float(P[sel].mean()),
                     "edge_per_share": float(sub.mean()), "ci": [elo, ehi]}
    summary["eras"] = eras

    # ----------------------------------------------------- does anything rank edge?
    print("\n=== within the skips, does the composite rank what we passed up? (AUC vs won) ===")
    feats = ["copy_score", "wallet_quality", "roi_score", "consistency", "copyability", "category_fit",
             "entry_timing", "spread_score", "liquidity_score", "thesis_score", "confidence"]
    rankers = {}
    for k in feats:
        v = np.array([r[k] if r[k] is not None else np.nan for r in skip], float)
        ok = ~np.isnan(v)
        a_ = auc(v[ok], W[ok])
        rankers[k] = a_
        print(f"  {k:16} AUC {a_:.3f}")
    price_auc = auc(P, W)
    print(f"  {'entry_price':16} AUC {price_auc:.3f}  (the market's own probability)")
    summary["rankers"] = {k: float(v) for k, v in rankers.items()}
    summary["rankers"]["entry_price"] = float(price_auc)

    # --------------------------------------------------------------------- wallet
    by_w = defaultdict(list)
    for i, r in enumerate(skip):
        if RV[i] >= 49:                       # live regime only — the gate that is running
            by_w[r["wallet"]].append(i)
    stats = [(w, len(v), float(E[v].mean())) for w, v in by_w.items() if len(v) >= 150]
    stats.sort(key=lambda x: -x[2])
    print(f"\n=== wallets in the live regime (>=150 labelled skips): {len(stats)} ===")
    for w, n, m_ in stats:
        print(f"  {w[:20]}… n={n:>6}  edge/sh {m_:+.4f}  $10 {HYPOTHETICAL_SIZE*m_:+.2f}")
    summary["live_regime_wallets"] = [{"wallet": w, "n": n, "edge_per_share": m_} for w, n, m_ in stats]
    summary["live_regime_wallets_note"] = ("small-n candidates, not conclusions: no per-wallet CI here, "
                                           "and the discovery window is the same window")

    # ----------------------------------------------------------------------- bands
    sel = np.where((RV >= 49) & (P >= 0.50) & (P < 0.65))[0]
    if len(sel) >= 30:
        sub = E[sel]; blo, bhi = cluster_boot(sub, [M[i] for i in sel])
        print(f"\n=== the live-regime pocket: v49+ & 0.50-0.65 ===")
        print(f"  n={len(sel):,} markets={len({M[i] for i in sel}):,} winrate {W[sel].mean():.3f} "
              f"price {P[sel].mean():.3f} edge/sh {sub.mean():+.4f} CI [{blo:+.4f},{bhi:+.4f}] "
              f"$10 {HYPOTHETICAL_SIZE*sub.mean():+.2f}")
        summary["live_band_pocket"] = {"band": [0.50, 0.65], "n": int(len(sel)),
                                       "markets": len({M[i] for i in sel}),
                                       "win_rate": float(W[sel].mean()), "mean_entry": float(P[sel].mean()),
                                       "edge_per_share": float(sub.mean()), "ci": [blo, bhi],
                                       "note": "in-sample on the discovery window — forward test required"}

    drop_edge = float(np.mean([r["edge"] for r in dropped])) if dropped else None
    if dropped:
        summary["already_decided"] = {"n": len(dropped), "edge_per_share": drop_edge,
                                      "mean_entry": float(np.mean([r["entry"] for r in dropped]))}
        print(f"\n  already-decided-at-entry rows: n={len(dropped):,} mean entry "
              f"{summary['already_decided']['mean_entry']:.3f} edge/sh {drop_edge:+.5f} "
              f"(copying into a decided market is a wash)")

    with open(args.out, "w") as fh:
        json.dump(summary, fh, indent=2)
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
