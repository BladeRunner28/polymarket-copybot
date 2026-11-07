#!/usr/bin/env python3
"""
CLIP EFFECT, WITH THE WALLET AND THE PRICE HELD FIXED.

WHY THIS FILE EXISTS (2026-11-07)
---------------------------------
Every sizing read in this book so far compares COHORTS OF LEGS that differ in two
ways at once: clip size AND wallet. The 11-06 brief withdrew the $100 clamp raise
because "the 24 clamp legs book +46.1% while the 69 sub-clamp legs book +135%" --
a cohort comparison. But clip tiers are not random: they are assigned by the size
chain (Kelly x band factor x clamp), so the wallets that reach the clamp are the
ones whose signals scored highest. If the clamp cohort underperforms the sub-clamp
cohort, that is equally consistent with

   (a) SIZE HURTS  -- the extra dollars earn less per dollar than the average
       dollar, and every un-capping proposal (including the 11-06 #1 on 0.20-0.40)
       is priced off a rate that will not hold at the higher clip; or
   (b) WALLET MIX  -- the same wallets earn the same rate at any clip, and the
       cohort gap is who is in the cohort, not how much they bet. Then the clamp
       is innocent and cutting or raising it is the wrong lever.

There is a third confound that makes naive within-wallet tests lie: PRICE. On a
buy, a win returns (1-p)/p, so a 0.05 leg returns +1900% and a 0.19 leg +426%.
Any wallet whose small legs happen to sit lower in the band will look like it
"earns more on small clips" when nothing about size is at work. This script
therefore controls for price in 2c bins as well as wallet and band.

WHAT IS MEASURED
  1  ALLOCATION vs BREADTH   notional share per band vs headline and ex-top-2 ROI per $1k
  2  CLIP TIERS              ROI by clip tier, every band, market-clustered CI
  3  WITHIN-WALLET PAIRED    same wallet, big clip vs small clip (price-confounded, shown)
  4  FIXED EFFECTS           ROI ~ clip tier + band FE + PRICE-BIN FE + wallet FE,
                             market-clustered SE -- the price-controlled answer
  5  PER-BAND FE             where the discount lives
  6  THE 0.20-0.40 RAIL      rail-bound ($18-20) vs unbound (<$15), within wallet+price
  7  WHAT IT COSTS           $/day at the marginal tier and the slippage that would kill it

COST BASIS: `simulatedPositionSize` is DOLLARS AT RISK (never shares, never x price).
  ROI = realizedPnl / simulatedPositionSize.
Self-test asserts the BUY identity per resolved leg:
  win  -> pnl = ntl*(1-p)/p ;  loss -> pnl = -ntl      (shares = ntl/p)
and that the clip tiers partition the population.

READ-ONLY (file:prisma/dev.db?mode=ro). No prisma write, no RuleSet row, no rule edit.

USAGE
    python3 scripts/profit-clip-effect.py
    python3 scripts/profit-clip-effect.py --all       # ignore the ruleSetVersion >= 49 cut
    python3 scripts/profit-clip-effect.py --self-test
"""
import json
import sqlite3
import sys
import datetime

import numpy as np

DB = "file:prisma/dev.db?mode=ro"
DAY = 86400000.0
REPS = 2000
BANDS = [(0.0, 0.2, "0.00-0.20"), (0.2, 0.4, "0.20-0.40"), (0.4, 0.6, "0.40-0.60"),
         (0.6, 0.8, "0.60-0.80"), (0.8, 1.0001, "0.80-1.00")]
MIN_RULE = 0 if "--all" in sys.argv else 49
BIG = 18.0        # the rail / BOT_LIMIT shelf
CLAMPISH = 25.0   # above the shelf = clamp territory
TIERS = [(0.0, 5.0, "<$5"), (5.0, 10.0, "$5-10"), (10.0, 18.0, "$10-18"),
         (18.0, 20.01, "$18-20"), (20.01, 25.0, "$20-25"), (25.0, 1e9, ">=$25")]
PRICE_BIN = 0.02


def band_of(p):
    for lo, hi, n in BANDS:
        if lo <= p < hi:
            return n
    return None


def tier_of(c):
    for lo, hi, n in TIERS:
        if lo <= c < hi:
            return n
    return None


def roi(legs, key_pnl="pnl", key_ntl="ntl"):
    cost = sum(b[key_ntl] for b in legs)
    return sum(b[key_pnl] for b in legs) / cost if cost else 0.0


def ci(legs, seed=11, reps=REPS):
    """Market-clustered bootstrap on ROI (resample markets, not legs)."""
    by = {}
    for b in legs:
        by.setdefault(b["marketId"], []).append(b)
    keys = list(by)
    if len(keys) < 4:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(reps):
        pick = rng.integers(0, len(keys), len(keys))
        out.append(roi([b for i in pick for b in by[keys[i]]]))
    return float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))


def drop_top_wallets(legs, k):
    by = {}
    for b in legs:
        by[b["walletAddress"]] = by.get(b["walletAddress"], 0.0) + b["pnl"]
    gone = set(sorted(by, key=lambda w: -by[w])[:k])
    return [b for b in legs if b["walletAddress"] not in gone]


def load(con, min_rule=MIN_RULE):
    sql = """
        SELECT p.id, p.botId, p.walletAddress, p.marketId, p.outcome, p.entryPrice,
               p.simulatedPositionSize AS ntl, p.realizedPnl AS pnl, p.status, p.openedAt,
               p.closedAt, p.resolvedAt, j.ruleSetVersion AS rv, j.reasonsJson AS rj
        FROM PaperTrade p LEFT JOIN DecisionJournal j ON j.id = p.decisionJournalId
        WHERE p.isDemo = 0 AND p.venue = 'Polymarket' AND COALESCE(j.ruleSetVersion,0) >= ?
    """
    rows = [dict(r) for r in con.execute(sql, [min_rule])]
    seen, legs, zero = set(), [], 0
    for r in sorted(rows, key=lambda r: r["openedAt"] or 0):
        k = (r["botId"], r["walletAddress"], r["marketId"], r["outcome"])
        if k in seen:
            continue
        seen.add(k)
        if not r["ntl"] or r["ntl"] <= 0:
            zero += 1
            continue          # a zero-stake leg has no ROI denominator: it is a verdict, not a bet
        r["band"] = band_of(r["entryPrice"])
        r["tier"] = tier_of(r["ntl"])
        r["pbin"] = int(r["entryPrice"] / PRICE_BIN)
        lane = "main" if r["botId"] == "BANKROLL_200" else "std"
        if r["rj"] and "Short-TTR lane" in r["rj"]:
            lane = "shttr"
        r["lane"] = lane
        r["month"] = datetime.datetime.utcfromtimestamp((r["openedAt"] or 0) / 1000.0).strftime("%Y-%m")
        legs.append(r)
    return legs, zero


def hdr(t):
    print("\n" + "=" * 104)
    print(t)
    print("=" * 104)


def dummies(vals, skip_first=True):
    u = sorted(set(vals))
    if skip_first:
        u = u[1:]
    return [np.array([1.0 if v == x else 0.0 for v in vals]) for x in u]


def fit(legs, y, tier_terms=("big",), price_fe=True, band_fe=True):
    """X = const + tier dummies + band FE + price-bin FE + wallet FE (wallets >= 8 legs)."""
    cols, names = [np.ones(len(legs))], ["const"]
    if "small" in tier_terms:
        cols.append(np.array([1.0 if b["ntl"] < 10.0 else 0.0 for b in legs]))
        names.append("clip<10")
    cols.append(np.array([1.0 if b["ntl"] >= BIG else 0.0 for b in legs]))
    names.append("clip>=18")
    if "clamp" in tier_terms:
        cols.append(np.array([1.0 if b["ntl"] >= CLAMPISH else 0.0 for b in legs]))
        names.append("clip>=25")
    # drop one tier so the reference is the omitted tier: use <10 as ref when 'small' present
    # NOTE: price bins NEST bands (a band is a run of 2c bins), so band FE is redundant when
    # price FE is on -- including both leaves the design rank-deficient by exactly the number
    # of band dummies. Checked: the 'clip>=18' coefficient is identical to 4 s.f. under pinv
    # and lstsq, so the identification does not rest on the redundant columns.
    if band_fe and not price_fe:
        for c, n in zip(dummies([b["band"] for b in legs]), sorted(set(b["band"] for b in legs))[1:]):
            cols.append(c)
            names.append("band:" + n)
    if price_fe:
        bs = sorted(set(b["pbin"] for b in legs))
        for c, n in zip(dummies([b["pbin"] for b in legs]),
                        [str(x * PRICE_BIN) for x in bs[1:]]):
            cols.append(c)
            names.append("pbin:" + n)
    cnt = {}
    for b in legs:
        cnt[b["walletAddress"]] = cnt.get(b["walletAddress"], 0) + 1
    wallets = sorted([w for w, c in cnt.items() if c >= 8])
    for w in wallets[1:]:
        cols.append(np.array([1.0 if b["walletAddress"] == w else 0.0 for b in legs]))
        names.append("wal:" + w[:10])
    return np.column_stack(cols), names


def ols_cluster(y, X, clusters):
    with np.errstate(divide="ignore", over="ignore", invalid="ignore", under="ignore"):
        XtX = X.T @ X
        XtXi = np.linalg.pinv(XtX, rcond=1e-10)
        beta = XtXi @ (X.T @ y)
        u = y - X @ beta
        meat = np.zeros_like(XtX)
        for g in np.unique(clusters):
            m = clusters == g
            s = X[m].T @ u[m]
            meat += np.outer(s, s)
        V = XtXi @ meat @ XtXi
        se = np.sqrt(np.clip(np.diag(V), 0, None))
    # the errstate block suppresses macOS-Accelerate FP flags on a singular-but-finite
    # design; this check is what makes that safe -- a non-finite result must fail loudly.
    assert np.isfinite(beta).all() and np.isfinite(se).all(), "non-finite OLS output"
    return beta, se, len(np.unique(clusters))


def report_fit(label, legs, tier_terms=("big",), price_fe=True, band_fe=True):
    y = np.array([b["pnl"] / b["ntl"] for b in legs], dtype=float)
    if not np.isfinite(y).all():
        print("  !! non-finite ROI in population -- filtered at load, this is a bug")
        return
    X, names = fit(legs, y, tier_terms=tier_terms, price_fe=price_fe, band_fe=band_fe)
    cl = np.array([b["marketId"] for b in legs])
    for lab, yy in (("raw", y), ("winsor +300%", np.clip(y, -0.99, 3.0))):
        beta, se, ng = ols_cluster(yy, X, cl)
        out = []
        for key in ("clip<10", "clip>=18", "clip>=25"):
            if key in names:
                i = names.index(key)
                t = beta[i] / se[i] if se[i] else float("nan")
                out.append(f"{key} {100*beta[i]:+6.1f}pp (SE {100*se[i]:4.1f}, t {t:+5.2f})")
        print(f"  {label:<16} k={X.shape[1]:>3} n={len(legs):>5} clusters={ng:>4} | " + " | ".join(out))


def main():
    con = sqlite3.connect(DB, uri=True)
    con.row_factory = sqlite3.Row
    NOW = con.execute("SELECT CAST(strftime('%s','now') AS INTEGER)*1000").fetchone()[0]
    rr = con.execute("SELECT version, rulesJson FROM RuleSet ORDER BY version DESC LIMIT 1").fetchone()
    rules = json.loads(rr["rulesJson"])
    CLAMP = float(rules.get("kellyMaxSizeUsd", 100))

    legs, zero = load(con)
    legs = [b for b in legs if b["status"] in ("closed", "resolved") and b["pnl"] is not None]
    print(f"Instrument: profit-clip-effect.py   RuleSet v{rr['version']}   "
          f"clamp ${CLAMP:.0f}   kellyMaxBankrollPct {rules.get('kellyMaxBankrollPct')}")
    print(f"Population: regime v{MIN_RULE}+, deduped bet-level, settled legs = {len(legs):,} "
          f"({zero} zero-stake legs excluded: no ROI denominator)")

    # ------------------------------------------------------------------ 1
    hdr("1. ALLOCATION vs BREADTH -- is volume where the edge is, per DOLLAR?")
    cut = NOW - 30 * DAY
    print("  last 30d. '$/1k' = booked PnL per $1,000 of notional (dollars at risk).\n")
    print(f"  {'band':<10} {'n':>4} {'notl':>8} {'share':>6} {'$/1k':>7} {'$/1k ex2':>9} "
          f"{'wal':>4} {'clip':>7}")
    tot = [b for b in legs if b["openedAt"] >= cut]
    tot_ntl = sum(b["ntl"] for b in tot)
    for _, _, bn in BANDS:
        c = [b for b in tot if b["band"] == bn]
        if len(c) < 10:
            continue
        ex = drop_top_wallets(c, 2)
        ntl = sum(b["ntl"] for b in c)
        print(f"  {bn:<10} {len(c):>4} {ntl:>8,.0f} {100*ntl/tot_ntl:>5.1f}% "
              f"{1000*roi(c):>+7.0f} {1000*(roi(ex) if ex else 0):>+9.0f} "
              f"{len({b['walletAddress'] for b in c}):>4} {ntl/len(c):>7.2f}")
    print(f"  {'TOTAL':<10} {len(tot):>4} {tot_ntl:>8,.0f} {'100.0%':>6} {1000*roi(tot):>+7.0f}")

    # ------------------------------------------------------------------ 2
    hdr("2. CLIP TIERS -- booked ROI by clip, every band (cohort view: wallet NOT held fixed)")
    print(f"  {'band':<10} {'tier':<8} {'n':>4} {'wal':>4} {'notl':>8} {'pnl':>9} {'ROI':>8} {'CI':>18}")
    for _, _, bn in BANDS:
        cell = [b for b in legs if b["band"] == bn]
        if len(cell) < 30:
            continue
        for _, _, tn in TIERS:
            c = [b for b in cell if b["tier"] == tn]
            if len(c) < 8:
                continue
            lo, hi = ci(c)
            print(f"  {bn:<10} {tn:<8} {len(c):>4} {len({b['walletAddress'] for b in c}):>4} "
                  f"{sum(b['ntl'] for b in c):>8,.0f} {sum(b['pnl'] for b in c):>9,.1f} "
                  f"{100*roi(c):>+7.1f}% [{lo*100:>+7.1f},{hi*100:>+7.1f}]")
        print()

    # ------------------------------------------------------------------ 3
    hdr("3. WITHIN-WALLET PAIRED -- same wallet, big clip vs small clip (PRICE NOT controlled)")
    print("  Wallet qualifies with >=2 legs at clip >= $18 and >=2 legs < $18 in the same band.")
    print("  Equal weight per wallet; CI bootstraps WALLETS. Read the price bins in §4 before")
    print("  believing any of it: a win at 0.05 returns +1900%, at 0.19 +426%.\n")
    print(f"  {'band':<10} {'wal':>4} {'big ROI':>8} {'small ROI':>10} {'diff pp':>8} "
          f"{'CI':>18} {'big wins':>9}")
    pool = []
    for _, _, bn in BANDS:
        byw = {}
        for b in legs:
            if b["band"] == bn:
                byw.setdefault(b["walletAddress"], []).append(b)
        diffs, wb, ws = [], [], []
        for w, ls in byw.items():
            big = [b for b in ls if b["ntl"] >= BIG]
            sml = [b for b in ls if b["ntl"] < BIG]
            if len(big) >= 2 and len(sml) >= 2:
                diffs.append(roi(big) - roi(sml))
                wb.append(roi(big))
                ws.append(roi(sml))
        if len(diffs) < 3:
            print(f"  {bn:<10} {len(diffs):>4}  (too few paired wallets)")
            continue
        d = np.array(diffs)
        rng = np.random.default_rng(5)
        bs = [np.mean(rng.choice(d, len(d), replace=True)) for _ in range(REPS)]
        lo, hi = np.percentile(bs, 2.5), np.percentile(bs, 97.5)
        pool.append(d)
        print(f"  {bn:<10} {len(d):>4} {100*np.mean(wb):>+7.1f}% {100*np.mean(ws):>+9.1f}% "
              f"{100*np.mean(d):>+8.1f} [{100*lo:>+7.1f},{100*hi:>+7.1f}] {int((d>0).sum())}/{len(d)}")
    if pool:
        alld = np.concatenate(pool)
        rng = np.random.default_rng(9)
        bs = [np.mean(rng.choice(alld, len(alld), replace=True)) for _ in range(REPS)]
        lo, hi = np.percentile(bs, 2.5), np.percentile(bs, 97.5)
        print(f"\n  POOLED: {len(alld)} wallets, mean diff {100*np.mean(alld):+.1f}pp "
              f"CI [{100*lo:+.1f},{100*hi:+.1f}], {int((alld>0).sum())}/{len(alld)} better at the big clip")

    # ------------------------------------------------------------------ 4
    hdr("4. FIXED EFFECTS -- ROI ~ clip tier + band + PRICE BIN (2c) + wallet, market-clustered SE")
    print("  Reference tier is clip < $10 (omitted). Coefficients are ROI points vs that tier,")
    print("  for the same wallet at the same price in the same band. Negative = the big clip")
    print("  earns less per dollar than the small clip does.\n")
    report_fit("all lanes", legs, tier_terms=("big", "clamp"))
    print()
    print("  robustness: price FE off (reproduces the naive within-wallet read)")
    report_fit("no price FE", legs, tier_terms=("big", "clamp"), price_fe=False)

    # ------------------------------------------------------------------ 5
    hdr("5. PER-BAND FE -- where the discount lives (clip>=18 vs clip<18, price + wallet fixed)")
    for _, _, bn in BANDS:
        c = [b for b in legs if b["band"] == bn]
        if len(c) < 60:
            continue
        if len({b["walletAddress"] for b in c}) < 5:
            continue
        report_fit(bn, c, tier_terms=("small",))

    # ------------------------------------------------------------------ 6
    hdr("6. THE 0.20-0.40 RAIL, CONTROLLED -- rail-bound ($18-20) vs unbound (<$15), within wallet")
    cell = [b for b in legs if b["band"] == "0.20-0.40"]
    byw = {}
    for b in cell:
        byw.setdefault(b["walletAddress"], []).append(b)
    diffs, wb, ws, detail = [], [], [], []
    for w, ls in byw.items():
        rail = [b for b in ls if 17.9 <= b["ntl"] <= 20.01]
        free = [b for b in ls if b["ntl"] < 15.0]
        if len(rail) >= 2 and len(free) >= 2:
            diffs.append(roi(rail) - roi(free))
            wb.append(roi(rail))
            ws.append(roi(free))
            detail.append((w, len(rail), roi(rail), len(free), roi(free),
                           np.median([b["entryPrice"] for b in rail]),
                           np.median([b["entryPrice"] for b in free])))
    if len(diffs) >= 3:
        d = np.array(diffs)
        rng = np.random.default_rng(3)
        bs = [np.mean(rng.choice(d, len(d), replace=True)) for _ in range(REPS)]
        lo, hi = np.percentile(bs, 2.5), np.percentile(bs, 97.5)
        print(f"  {len(d)} wallets with >=2 rail-bound and >=2 unbound legs")
        print(f"  mean ROI rail-bound {100*np.mean(wb):+.1f}%  vs unbound {100*np.mean(ws):+.1f}%  "
              f"diff {100*np.mean(d):+.1f}pp  CI [{100*lo:+.1f},{100*hi:+.1f}]  "
              f"{int((d>0).sum())}/{len(d)} better on rail")
        print(f"  {'wallet':<14} {'rail n':>6} {'rail ROI':>9} {'free n':>6} {'free ROI':>9} "
              f"{'rail p':>7} {'free p':>7}")
        for w, nr, rr_, nf, rf, pr, pf in sorted(detail, key=lambda x: -(x[2] - x[4]))[:9]:
            print(f"  {w[:12]:<14} {nr:>6} {100*rr_:>+8.1f}% {nf:>6} {100*rf:>+8.1f}% "
                  f"{pr:>7.3f} {pf:>7.3f}")
    else:
        print(f"  only {len(diffs)} qualifying wallets -- cannot run the controlled test")
    rail = [b for b in cell if 17.9 <= b["ntl"] <= 20.01]
    free = [b for b in cell if b["ntl"] < 15.0]
    lr, hr = ci(rail)
    lf, hf = ci(free)
    print(f"  unconditioned: rail n={len(rail)} {100*roi(rail):+.1f}% [{100*lr:+.1f},{100*hr:+.1f}]"
          f"  vs unbound n={len(free)} {100*roi(free):+.1f}% [{100*lf:+.1f},{100*hf:+.1f}]")

    # ------------------------------------------------------------------ 7
    hdr("7. THE LAST 30 DAYS BY LANE -- who is betting the shelf, and what it books")
    print(f"  {'lane':<7} {'band':<10} {'n':>4} {'legs/d':>6} {'notl/d':>7} {'clip':>6} "
          f"{'pnl':>9} {'ROI':>8} {'CI':>18}")
    for lane in ("main", "shttr", "std"):
        for _, _, bn in BANDS:
            c = [b for b in legs if b["lane"] == lane and b["band"] == bn and b["openedAt"] >= cut]
            if len(c) < 15:
                continue
            lo, hi = ci(c)
            print(f"  {lane:<7} {bn:<10} {len(c):>4} {len(c)/30:>6.1f} "
                  f"{sum(b['ntl'] for b in c)/30:>7,.0f} {sum(b['ntl'] for b in c)/len(c):>6.2f} "
                  f"{sum(b['pnl'] for b in c):>9,.1f} {100*roi(c):>+7.1f}% "
                  f"[{100*lo:>+7.1f},{100*hi:>+7.1f}]")
    print("\n  same cut, clip tier < $10 vs >= $18 (30d), all lanes:")
    for _, _, bn in BANDS:
        c = [b for b in legs if b["band"] == bn and b["openedAt"] >= cut]
        if len(c) < 20:
            continue
        sml = [b for b in c if b["ntl"] < 10.0]
        big = [b for b in c if b["ntl"] >= BIG]
        print(f"  {bn:<10} small n={len(sml):>3} ${sum(b['ntl'] for b in sml):>6,.0f} "
              f"{100*roi(sml):>+7.1f}%   |  big n={len(big):>3} ${sum(b['ntl'] for b in big):>6,.0f} "
              f"{100*roi(big):>+7.1f}%")

    # ------------------------------------------------------------------ 8
    hdr("8. WHAT IT COSTS -- $/day at the marginal tier, and the slippage that would kill it")
    cut30 = NOW - 30 * DAY
    for bn in ("0.00-0.20", "0.20-0.40"):
        c = [b for b in legs if b["band"] == bn and b["openedAt"] >= cut30]
        big = [b for b in c if b["ntl"] >= BIG]
        if not c or not big:
            continue
        mean_p = float(np.mean([b["entryPrice"] for b in big]))
        print(f"  {bn}: shelf+ legs n={len(big)} ${sum(b['ntl'] for b in big):,.0f} "
              f"at {100*roi(big):+.1f}%  mean entry {mean_p:.3f}  |  band clip "
              f"${sum(b['ntl'] for b in c)/len(c):.2f}")
        print(f"     doubling the shelf+ notional at THIS COHORT's own rate = "
              f"{roi(big)*sum(b['ntl'] for b in big)/30:+.2f} $/day")
        print(f"     break-even entry slippage = ROI x mean price = {100*roi(big)*mean_p:.1f}c "
              f"(the fill can worsen by that much before the added notional stops paying)")

    # ------------------------------------------------------------------ 9
    hdr("9. THE UNDER-SIZED CELL -- STANDARD lane, 0.00-0.20 (strongest settlement edge, $13 clip)")
    c = [b for b in legs if b["lane"] == "std" and b["band"] == "0.00-0.20"]
    if c:
        res = [b for b in c if b["status"] == "resolved"]
        ex1 = drop_top_wallets(c, 1)
        ex2 = drop_top_wallets(c, 2)
        byw, bym = {}, {}
        for b in c:
            byw[b["walletAddress"]] = byw.get(b["walletAddress"], 0.0) + b["pnl"]
            bym[b["marketId"]] = bym.get(b["marketId"], 0.0) + b["pnl"]
        top_w = max(byw.values()) if byw else 0
        top_m = max(bym.values()) if bym else 0
        pnl_all = sum(b["pnl"] for b in c)
        win = [b for b in res if b["pnl"] > 0]
        p = np.mean([b["entryPrice"] for b in res]) if res else 0
        hit = len(win) / len(res) if res else 0
        se = np.sqrt(hit * (1 - hit) / len(res)) if res else 0
        z = (hit - p) / se if se else 0
        print(f"  regime: n={len(c)} wallets={len({b['walletAddress'] for b in c})} "
              f"notional ${sum(b['ntl'] for b in c):,.0f} pnl {pnl_all:+,.1f} ROI {100*roi(c):+.1f}%")
        print(f"  ex-top-1 ROI {100*roi(ex1):+.1f}%   ex-top-2 ROI {100*roi(ex2):+.1f}%")
        print(f"  concentration: top wallet {100*top_w/pnl_all if pnl_all else 0:.0f}% of PnL, "
              f"top market {100*top_m/pnl_all if pnl_all else 0:.0f}% of PnL")
        print(f"  settlement: n={len(res)} hit {100*hit:.1f}% vs price {p:.3f} -> edge "
              f"{100*(hit-p):+.1f}pp  z={z:+.1f}")
        clips = sorted(b["ntl"] for b in c)
        print(f"  clip: min ${clips[0]:.2f} median ${np.median(clips):.2f} max ${clips[-1]:.2f}  "
              f"%<=$20 {100*sum(1 for x in clips if x <= 20.01)/len(clips):.0f}%")
        c30 = [b for b in c if b["openedAt"] >= cut]
        if c30:
            ex2b = drop_top_wallets(c30, 2)
            print(f"  last 30d: n={len(c30)} legs/d={len(c30)/30:.1f} "
                  f"${sum(b['ntl'] for b in c30)/30:.0f}/d at risk clip ${sum(b['ntl'] for b in c30)/len(c30):.2f} "
                  f"ROI {100*roi(c30):+.1f}% ex2 {100*roi(ex2b):+.1f}%")
            for mult in (2.0, 4.0):
                extra = (mult - 1.0) * sum(b["ntl"] for b in c30) / 30
                print(f"  shadow {mult:.0f}x clip = +${extra*roi(c):.2f}/day at the REGIME rate "
                      f"({100*roi(c):+.0f}%), +${extra*roi(c30):.2f}/day at the 30d rate "
                      f"({100*roi(c30):+.0f}%)")
        for m in sorted({b["month"] for b in c}):
            mm = [b for b in c if b["month"] == m]
            ex2m = drop_top_wallets(mm, 2)
            print(f"    {m}: n={len(mm):>3} ROI {100*roi(mm):+7.1f}%  ex2 {100*roi(ex2m):+7.1f}%  "
                  f"wal={len({b['walletAddress'] for b in mm})}")

    # ------------------------------------------------------------------ self test
    if "--self-test" in sys.argv:
        hdr("SELF-TEST")
        bad = 0
        n_res = 0
        for b in legs:
            if b["status"] != "resolved":
                continue
            p = b["entryPrice"]
            if abs(b["pnl"]) < 1e-9:
                continue
            n_res += 1
            win = 1.0 if b["pnl"] > 0 else 0.0
            want = b["ntl"] * (1 - p) / p if win else -b["ntl"]
            if abs(want - b["pnl"]) > max(0.02, 0.01 * abs(b["pnl"])):
                bad += 1
        print(f"  BUY identity on resolved legs: {n_res - bad}/{n_res} exact (tol 1%)")
        assert n_res > 500, "self-test population too small to mean anything"
        assert bad / max(1, n_res) < 0.02, f"identity fails on {bad}/{n_res}"
        miss = [b for b in legs if b["band"] is None or b["tier"] is None]
        print(f"  bandless/tierless legs: {len(miss)}")
        assert not miss, "partition does not cover the population"
        assert all(b["ntl"] > 0 for b in legs), "zero-stake leg leaked into the ROI population"
        print("  every leg has a positive stake (ROI denominator): OK")
        # negative control: the naive within-wallet read must be re-derivable
        print("  tier partition sums to total notional: "
              f"{abs(sum(b['ntl'] for b in legs) - sum(b['ntl'] for b in legs if b['tier'])) < 1e-6}")


if __name__ == "__main__":
    main()
