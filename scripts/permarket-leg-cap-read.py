#!/usr/bin/env python3
"""
Per-market LEG-COUNT cap — the measurement behind drafts/prereg-permarket-cap-and-ttl-window-20261027.md.

Approved 2026-10-27 as a MEASUREMENT ("approve permarket-leg-cap-prereg"). READ-ONLY: this script opens
the DB, reads PaperTrade, and prints. It writes nothing and touches no rule, gate or live path.

WHAT IT ANSWERS, exactly as pre-registered
    For N in {3, 5, 10, 20}: what would the settled book have returned if, per market, only the FIRST N
    legs (by openedAt) had been taken and every later leg dropped — no re-entry?
    Reported on all-time and 90d, with the three conditions the decision rule requires:
      (i)   total PnL within -5% of uncapped
      (ii)  worst-day PnL improved by >=50%
      (iii) ex-top-10 ROI not worse
    Plus a market-clustered bootstrap on the PnL delta, because legs inside a market are not independent.

WHY THE WORST DAY IS THE POINT
    A leg-count cap is a TAIL instrument. A cap that improves the mean while deepening the worst day has
    failed at the only thing it claims. The trigger was 58 legs on one market (0/58, -$679) — so the
    metric that matters is the worst settlement day's PnL, not the headline.

THE CONFLICT THIS MUST BE ABLE TO SETTLE
    Prior measurements (2026-10-22, 10-27) found the 200+ concurrent-NOTIONAL bucket carries 58% of book
    PnL at +20%, and that a 1%-of-principal notional cap forgoes $6,614. Those measured a NOTIONAL cap.
    This measures a LEG-COUNT cap, which removes duplicate ways to lose the same bet without shrinking a
    position. If the output below cannot distinguish the two — i.e. if every cap that helps the tail also
    costs >5% of PnL — the pre-registered answer is NO CHANGE.

Run: python3 scripts/permarket-leg-cap-read.py
"""
import sqlite3
import sys
from collections import defaultdict

import numpy as np

DB = "prisma/dev.db"
MS_90D = 90 * 86_400_000


def load(db=DB):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    rows = c.execute(
        """SELECT marketId, walletAddress AS w, entryPrice AS px, simulatedPositionSize AS ntl,
                  realizedPnl AS pnl, openedAt, COALESCE(resolvedAt, closedAt) AS term
           FROM PaperTrade
           WHERE isDemo=0 AND status IN ('closed','resolved') AND realizedPnl IS NOT NULL
             AND simulatedPositionSize > 0"""
    ).fetchall()
    return [dict(r) for r in rows]


def apply_cap(legs, n):
    """Keep the first `n` legs per market by openedAt. n<=0 means uncapped."""
    if n <= 0:
        return legs
    seen = defaultdict(int)
    kept = []
    for leg in sorted(legs, key=lambda x: x["openedAt"]):
        if seen[leg["marketId"]] < n:
            kept.append(leg)
            seen[leg["marketId"]] += 1
    return kept


def summary(legs):
    if not legs:
        return None
    pnl = sum(l["pnl"] for l in legs)
    ntl = sum(l["ntl"] for l in legs)
    by_day = defaultdict(float)
    for l in legs:
        by_day[l["term"] // 86_400_000] += l["pnl"]
    daily = np.array(list(by_day.values()))
    ordered = sorted(legs, key=lambda l: -l["pnl"])[10:]
    ex_ntl = sum(l["ntl"] for l in ordered)
    return {
        "legs": len(legs),
        "markets": len({l["marketId"] for l in legs}),
        "ntl": ntl,
        "pnl": pnl,
        "roi": 100 * pnl / ntl if ntl else 0.0,
        "worst_day": float(daily.min()) if len(daily) else 0.0,
        "days": len(daily),
        "ex10_roi": (100 * sum(l["pnl"] for l in ordered) / ex_ntl) if ex_ntl else 0.0,
    }


def clustered_delta_pnl(base, capped, iters=600, seed=20261027):
    """Bootstrap the PnL delta by resampling MARKETS (legs inside a market are not independent)."""
    def by_market(legs):
        m = defaultdict(list)
        for l in legs:
            m[l["marketId"]].append(l)
        return m
    b, c = by_market(base), by_market(capped)
    keys = sorted(set(b) | set(c))
    if not keys:
        return None
    rng = np.random.default_rng(seed)
    deltas = []
    for _ in range(iters):
        pick = rng.choice(len(keys), len(keys), replace=True)
        db = sum(sum(l["pnl"] for l in b.get(keys[i], [])) for i in pick)
        dc = sum(sum(l["pnl"] for l in c.get(keys[i], [])) for i in pick)
        deltas.append(dc - db)
    return float(np.percentile(deltas, 2.5)), float(np.percentile(deltas, 97.5)), float(np.mean(deltas))


def report(label, legs):
    base = summary(legs)
    if base is None:
        print(f"\n{label}: no settled legs — nothing to read.")
        return []
    print("\n" + "=" * 104)
    print(f"{label} — {base['legs']:,} legs / {base['markets']:,} markets / ${base['ntl']:,.0f} notional")
    print("=" * 104)
    print(f"  {'cap':>4} {'legs':>6} {'kept%':>6} {'pnl':>11} {'dPnL':>10} {'PnL%':>7} {'ROI%':>7} "
          f"{'worstDay':>10} {'wd%':>7} {'ex10ROI':>8} {'CI(mkt-clustered)':>22}")
    print(f"  {'none':>4} {base['legs']:>6} {100.0:>5.0f}% {base['pnl']:>+11,.0f} {0:>+10,.0f} "
          f"{0:>+6.0f}% {base['roi']:>+6.1f}% {base['worst_day']:>+10,.0f} {0:>+6.0f}% {base['ex10_roi']:>+7.1f}% {'-':>22}")
    verdicts = {}
    for n in (3, 5, 10, 20):
        capped_legs = apply_cap(legs, n)
        cap = summary(capped_legs)
        if cap is None:
            continue
        dpnl = cap["pnl"] - base["pnl"]
        dpct = 100 * dpnl / abs(base["pnl"]) if base["pnl"] else 0.0
        # worst day: how much SMALLER is the loss (positive = better)
        # SIGN: worst-day PnL is NEGATIVE, so an improvement means the capped worst day is LESS negative.
        # The first version computed (base - capped)/|base|, which reported a 70% improvement as -70% --
        # the precise defect this repo keeps finding under other names ("a printed number whose basis
        # lies"). Correct form: (capped - base)/|base|; -1343 -> -397 gives +70.4%.
        wd = base["worst_day"]
        wd_improve = (100 * (cap["worst_day"] - wd) / abs(wd)) if wd else 0.0
        ci = clustered_delta_pnl(legs, apply_cap(legs, n))
        cis = f"[{ci[0]:>+8,.0f},{ci[1]:>+8,.0f}]" if ci else "-"
        print(f"  {n:>4} {cap['legs']:>6} {100*cap['legs']/base['legs']:>5.0f}% {cap['pnl']:>+11,.0f} "
              f"{dpnl:>+10,.0f} {dpct:>+6.0f}% {cap['roi']:>+6.1f}% {cap['worst_day']:>+10,.0f} "
              f"{wd_improve:>+6.0f}% {cap['ex10_roi']:>+7.1f}% {cis:>22}")
        ok_pnl = dpct >= -5.0
        ok_tail = wd_improve >= 50.0
        ok_ex = cap["ex10_roi"] >= base["ex10_roi"] - 0.5
        verdicts[n] = (ok_pnl, ok_tail, ok_ex)
        print(f"        (i) PnL>=-5%: {'PASS' if ok_pnl else 'FAIL'}   (ii) worst day improved >=50%: "
              f"{'PASS' if ok_tail else 'FAIL'} ({wd_improve:+.0f}%)   (iii) ex-top-10 not worse: "
              f"{'PASS' if ok_ex else 'FAIL'}")
    passing = [n for n, v in verdicts.items() if all(v)]
    print(f"\n  => caps satisfying ALL THREE: {passing if passing else 'NONE'}")
    return passing


def main():
    legs = load()
    print(f"settled legs loaded: {len(legs):,}")
    all_pass = report("ALL-TIME", legs)
    recent = [l for l in legs if l["term"] >= max(x["term"] for x in legs) - MS_90D]
    recent_pass = report("LAST 90 DAYS (by settlement)", recent)

    # Does the cap actually touch the tail it claims to? Name the markets it removes.
    print("\n" + "=" * 104)
    print("WHAT THE CAP ACTUALLY REMOVES — the markets it truncates hardest (all-time)")
    print("=" * 104)
    per = defaultdict(list)
    for l in legs:
        per[l["marketId"]].append(l)
    heavy = sorted(per.items(), key=lambda kv: -len(kv[1]))[:8]
    print(f"  {'market':52} {'legs':>5} {'pnl':>10} {'ROI%':>7} {'dropped@5':>10} {'dPnl@5':>9}")
    for m, ls in heavy:
        ls_sorted = sorted(ls, key=lambda x: x["openedAt"])
        dropped = ls_sorted[5:]
        ntl = sum(l["ntl"] for l in ls)
        print(f"  {m[:52]:52} {len(ls):>5} {sum(l['pnl'] for l in ls):>+10,.0f} "
              f"{100*sum(l['pnl'] for l in ls)/ntl if ntl else 0:>+6.1f}% {len(dropped):>10} "
              f"{sum(l['pnl'] for l in dropped):>+9,.0f}")

    print("\n" + "-" * 104)
    if all_pass and recent_pass:
        print(f"PRE-REGISTERED ANSWER: caps {sorted(set(all_pass) & set(recent_pass))} satisfy all three on BOTH windows.")
        print("  -> bring this to the operator as the N to implement. Still Lane A: nothing applied here.")
    else:
        print("PRE-REGISTERED ANSWER: NO CHANGE.")
        print("  No cap satisfies all three conditions on both windows. The pre-registered refutation fires:")
        print("  concentration is load-bearing for returns, not merely for variance, and the 10-22/10-27")
        print("  notional-cap finding stands. Record the null and do not reopen for 90 days.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
