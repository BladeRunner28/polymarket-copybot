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

THREE INSTRUMENT DEFECTS REPAIRED 2026-10-28 (self-audit), none of which change the registered answer
    1. SHRINKING DENOMINATOR. (ii) was compared in ABSOLUTE dollars between the uncapped book and a
       capped book holding 47-83% of its notional. A cap that simply removes exposure earns a smaller
       worst day for free. Measured: cap 3 all-time reads +70% on dollars but +44% per dollar at risk —
       PASS becomes FAIL. The registered basis is still absolute (the prereg says "worst-day PnL"), so
       the verdict is unchanged and still NO CHANGE; both bases now print, and a cell where they
       disagree is flagged. Changing which basis DECIDES is a Lane A call, not an instrument repair.
    2. SIGN COLLISION. The per-market table printed the dropped legs' PnL as a POSITIVE number under a
       name (`dPnl@5`) all but identical to the main table's `dPnL`, which is capped-minus-base and
       therefore NEGATIVE for the same quantity. One report, two sign conventions, same-name columns.
    3. MISSING POPULATION. The prereg's Part A exists to bound risk on the OPEN book, but this read
       only ever loaded settled legs, so the concentration the cap would actually bind on was
       invisible. An open-book census is now printed.

    Also added: $/1k-capital-day, which the prereg's Measurement item 2 requires and which was never
    printed; and a window-structure block, because the "both windows" gate is doing less work than it
    looks like (see the block's own output).

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
DAY_MS = 86_400_000
MS_90D = 90 * DAY_MS


def _conn(db=DB):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    return c


def load(db=DB):
    rows = _conn(db).execute(
        """SELECT marketId, walletAddress AS w, entryPrice AS px, simulatedPositionSize AS ntl,
                  realizedPnl AS pnl, openedAt, COALESCE(resolvedAt, closedAt) AS term
           FROM PaperTrade
           WHERE isDemo=0 AND status IN ('closed','resolved') AND realizedPnl IS NOT NULL
             AND simulatedPositionSize > 0
             AND COALESCE(resolvedAt, closedAt) IS NOT NULL"""
    ).fetchall()
    return [dict(r) for r in rows]


def load_open(db=DB):
    """The open book: what a leg cap would actually bind on from today forward."""
    rows = _conn(db).execute(
        """SELECT marketId, simulatedPositionSize AS ntl
           FROM PaperTrade
           WHERE isDemo=0 AND status='open' AND simulatedPositionSize > 0"""
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
        by_day[l["term"] // DAY_MS] += l["pnl"]
    daily = np.array(list(by_day.values()))
    ordered = sorted(legs, key=lambda l: -l["pnl"])[10:]
    ex_ntl = sum(l["ntl"] for l in ordered)
    # capital-days: a leg occupies its notional for its realised holding period.
    cap_days = sum(l["ntl"] * max((l["term"] - l["openedAt"]) / DAY_MS, 0.0) for l in legs) / 1000.0
    return {
        "legs": len(legs),
        "markets": len({l["marketId"] for l in legs}),
        "ntl": ntl,
        "pnl": pnl,
        "roi": 100 * pnl / ntl if ntl else 0.0,
        "worst_day": float(daily.min()) if len(daily) else 0.0,
        "worst_day_pct_ntl": 100 * float(daily.min()) / ntl if ntl and len(daily) else 0.0,
        "days": len(daily),
        "ex10_roi": (100 * sum(l["pnl"] for l in ordered) / ex_ntl) if ex_ntl else 0.0,
        "cap_days": cap_days,
        "pnl_per_kd": (1000 * pnl / cap_days) if cap_days else 0.0,
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
        return [], []
    print("\n" + "=" * 132)
    print(f"{label} — {base['legs']:,} legs / {base['markets']:,} markets / ${base['ntl']:,.0f} notional "
          f"/ ${base['pnl']:+,.0f} pnl")
    print("=" * 132)
    print(f"  {'cap':>4} {'legs':>6} {'kept%':>6} {'ntl%':>6} {'pnl':>10} {'dPnL':>9} {'PnL%':>6} "
          f"{'ROI%':>6} {'worst$':>9} {'wd%ntl':>7} {'wdImp$':>7} {'wdImp%ntl':>9} {'ex10ROI':>8} {'$/1k-cd':>8}")
    print(f"  {'none':>4} {base['legs']:>6} {100.0:>5.0f}% {100.0:>5.0f}% {base['pnl']:>+10,.0f} "
          f"{0:>+9,.0f} {0:>+5.0f}% {base['roi']:>+5.1f}% {base['worst_day']:>+9,.0f} "
          f"{base['worst_day_pct_ntl']:>+6.3f}% {0:>+6.0f}% {0:>+8.0f}% {base['ex10_roi']:>+7.1f}% "
          f"{base['pnl_per_kd']:>+8.1f}")
    verdicts, verdicts_norm, diverged = {}, {}, []
    for n in (3, 5, 10, 20):
        capped_legs = apply_cap(legs, n)
        cap = summary(capped_legs)
        if cap is None:
            continue
        dpnl = cap["pnl"] - base["pnl"]
        dpct = 100 * dpnl / abs(base["pnl"]) if base["pnl"] else 0.0
        # worst day: how much SMALLER is the loss (positive = better)
        # SIGN: worst-day PnL is NEGATIVE, so an improvement means the capped worst day is LESS negative.
        # The first version computed (base - capped)/|base|, which reported a 70% improvement as -70%.
        wd = base["worst_day"]
        wd_improve = (100 * (cap["worst_day"] - wd) / abs(wd)) if wd else 0.0
        # DEFECT 1 (2026-10-28): the same improvement, per dollar actually at risk. A cap that removes
        # notional shrinks the absolute tail mechanically; this is the basis that cannot be bought by
        # simply holding less. Still not the deciding basis — see the header note.
        b_norm, c_norm = base["worst_day_pct_ntl"], cap["worst_day_pct_ntl"]
        wd_improve_norm = (100 * (c_norm - b_norm) / abs(b_norm)) if b_norm else 0.0
        ci = clustered_delta_pnl(legs, capped_legs)
        cis = f"[{ci[0]:>+8,.0f},{ci[1]:>+8,.0f}]" if ci else "-"
        print(f"  {n:>4} {cap['legs']:>6} {100*cap['legs']/base['legs']:>5.0f}% "
              f"{100*cap['ntl']/base['ntl']:>5.0f}% {cap['pnl']:>+10,.0f} {dpnl:>+9,.0f} "
              f"{dpct:>+5.0f}% {cap['roi']:>+5.1f}% {cap['worst_day']:>+9,.0f} "
              f"{cap['worst_day_pct_ntl']:>+6.3f}% {wd_improve:>+6.0f}% {wd_improve_norm:>+8.0f}% "
              f"{cap['ex10_roi']:>+7.1f}% {cap['pnl_per_kd']:>+8.1f}")
        ok_pnl = dpct >= -5.0
        ok_tail = wd_improve >= 50.0            # REGISTERED basis (absolute dollars)
        ok_tail_norm = wd_improve_norm >= 50.0  # reported basis, not deciding
        ok_ex = cap["ex10_roi"] >= base["ex10_roi"] - 0.5
        verdicts[n] = (ok_pnl, ok_tail, ok_ex)
        verdicts_norm[n] = (ok_pnl, ok_tail_norm, ok_ex)
        if ok_tail != ok_tail_norm:
            diverged.append((n, wd_improve, wd_improve_norm))
        flag = "  <-- basis disagreement" if ok_tail != ok_tail_norm else ""
        print(f"        (i) PnL>=-5%: {'PASS' if ok_pnl else 'FAIL'} ({dpct:+.0f}%)   "
              f"(ii) worst day >=50%: {'PASS' if ok_tail else 'FAIL'} on registered abs$ ({wd_improve:+.0f}%), "
              f"{'PASS' if ok_tail_norm else 'FAIL'} per $ at risk ({wd_improve_norm:+.0f}%){flag}   "
              f"(iii) ex-top-10 not worse: {'PASS' if ok_ex else 'FAIL'}")
        print(f"        market-clustered 95% CI on dPnL: {cis}")
    passing = [n for n, v in verdicts.items() if all(v)]
    passing_norm = [n for n, v in verdicts_norm.items() if all(v)]
    print(f"\n  => caps satisfying ALL THREE on the REGISTERED basis: {passing if passing else 'NONE'}")
    if diverged:
        print(f"  => on the per-dollar basis: {passing_norm if passing_norm else 'NONE'}   "
              f"(basis disagrees at N={[d[0] for d in diverged]})")
    return passing, passing_norm


def open_book_census(db=DB):
    """DEFECT 3 (2026-10-28): the cap binds on the OPEN book; the read never looked at it."""
    legs = load_open(db)
    print("\n" + "=" * 132)
    print("OPEN BOOK NOW — the population a leg cap would actually bind on (settled legs above are history)")
    print("=" * 132)
    if not legs:
        print("  no open legs — a cap would bind on nothing today.")
        return
    per = defaultdict(int)
    ntl_by = defaultdict(float)
    for l in legs:
        per[l["marketId"]] += 1
        ntl_by[l["marketId"]] += l["ntl"]
    tot_legs, tot_ntl = len(legs), sum(ntl_by.values())
    print(f"  open: {tot_legs:,} legs / {len(per):,} markets / ${tot_ntl:,.0f} notional")
    for n in (3, 5, 10, 20):
        over = {m: c for m, c in per.items() if c > n}
        legs_over = sum(over.values())
        ntl_over = sum(ntl_by[m] for m in over)
        refused = sum(c - n for c in over.values())
        print(f"  cap {n:>2}: {len(over):>3} markets exceed it -> {legs_over:>4} legs / "
              f"${ntl_over:>8,.0f} ({100*ntl_over/tot_ntl if tot_ntl else 0:>3.0f}% of open notional), "
              f"{refused:>3} legs would be refused")
    print("  worst offenders:")
    for m, c in sorted(per.items(), key=lambda kv: -kv[1])[:6]:
        print(f"    {m[:60]:60} legs={c:>3} ntl=${ntl_by[m]:>8,.0f}")


def heavy_markets(legs, n=5):
    """What the cap removes, with the SAME sign convention as the table above (capped - base)."""
    print("\n" + "=" * 132)
    print(f"WHAT THE CAP ACTUALLY REMOVES AT N={n} — per market contribution, signed capped-minus-base")
    print("=" * 132)
    print(f"  {'market':54} {'legs':>5} {'pnl':>10} {'ROI%':>7} {'dropped':>8} {'dPnl':>10}")
    per = defaultdict(list)
    for l in legs:
        per[l["marketId"]].append(l)
    for m, ls in sorted(per.items(), key=lambda kv: -len(kv[1]))[:8]:
        ls_sorted = sorted(ls, key=lambda x: x["openedAt"])
        dropped = ls_sorted[n:]
        ntl = sum(l["ntl"] for l in ls)
        # negative = capping this market gives up that much PnL (matches the main table's dPnL)
        print(f"  {m[:54]:54} {len(ls):>5} {sum(l['pnl'] for l in ls):>+10,.0f} "
              f"{100*sum(l['pnl'] for l in ls)/ntl if ntl else 0:>+6.1f}% {len(dropped):>8} "
              f"{-sum(l['pnl'] for l in dropped):>+10,.0f}")
    print("  (dPnl is signed capped-minus-base, so it sums with the main table: "
          "negative = capping this market gives up PnL, positive = the cap helps.)")


def window_structure(all_legs, recent, excluded, caps=(3, 5, 10, 20)):
    """The 'both windows' gate hides how little independent evidence it contains when the book is short."""
    print("\n" + "=" * 132)
    print("WINDOW STRUCTURE — is 'all-time AND 90d' two windows or one window plus a tail?")
    print("=" * 132)
    span = (max(l["term"] for l in all_legs) - min(l["term"] for l in all_legs)) / DAY_MS
    print(f"  the settled book covers {span:.0f} days in total; the 90d window is "
          f"{100*len(recent)/len(all_legs):.0f}% of its legs.")
    print(f"  all-time     {len(all_legs):>6,} legs  ${sum(l['pnl'] for l in all_legs):>+9,.0f}")
    print(f"  last 90d     {len(recent):>6,} legs  ${sum(l['pnl'] for l in recent):>+9,.0f}")
    print(f"  EXCLUDED      {len(excluded):>6,} legs  ${sum(l['pnl'] for l in excluded):>+9,.0f}   "
          f"<- the 90d cut's leavings: the only place the two windows can disagree")
    base_all = sum(l["pnl"] for l in all_legs)
    print(f"\n  {'cap':>4} {'all-time cost':>14} {'cost from EXCLUDED slice':>25} {'share':>7} "
          f"{'90d-only verdict':>17}")
    for n in caps:
        cost_all = sum(l["pnl"] for l in apply_cap(all_legs, n)) - base_all
        cost_exc = (sum(l["pnl"] for l in apply_cap(excluded, n))
                    - sum(l["pnl"] for l in excluded)) if excluded else 0.0
        share = 100 * cost_exc / cost_all if cost_all else 0.0
        # does the 90d window alone satisfy (i) PnL within -5%?
        r_base = sum(l["pnl"] for l in recent)
        r_cap = sum(l["pnl"] for l in apply_cap(recent, n))
        pct = 100 * (r_cap - r_base) / abs(r_base) if r_base else 0.0
        print(f"  {n:>4} {cost_all:>+14,.0f} {cost_exc:>+25,.0f} {share:>6.0f}% "
              f"{('(i) ' + ('PASS' if pct >= -5 else 'FAIL') + f' {pct:+.0f}%'):>17}")
    print("  Read the share column: the closer to 100%, the more the all-time veto is one vintage's story,")
    print("  not a property of the strategy. Whether that should still veto is a Lane A question.")


def main():
    import argparse

    ap = argparse.ArgumentParser(description="Per-market leg-cap read (read-only).")
    ap.add_argument("--db", default=DB, help="sqlite path (default: prisma/dev.db)")
    args = ap.parse_args()
    db = args.db

    legs = load(db)
    if not legs:
        print("no settled legs — nothing to read.")
        return 0
    print(f"settled legs loaded: {len(legs):,} (isDemo=0, status in closed/resolved, realizedPnl not null)")

    all_pass, all_pass_norm = report("ALL-TIME", legs)
    last_term = max(x["term"] for x in legs)
    recent = [l for l in legs if l["term"] >= last_term - MS_90D]
    excluded = [l for l in legs if l["term"] < last_term - MS_90D]
    recent_pass, recent_pass_norm = report("LAST 90 DAYS (by settlement, anchored on the newest settlement)", recent)

    open_book_census(db)
    heavy_markets(legs, 5)
    window_structure(legs, recent, excluded)

    print("\n" + "-" * 132)
    both = sorted(set(all_pass) & set(recent_pass))
    both_norm = sorted(set(all_pass_norm) & set(recent_pass_norm))
    if both:
        print(f"PRE-REGISTERED ANSWER: caps {both} satisfy all three on BOTH windows.")
        print("  -> bring this to the operator as the N to implement. Still Lane A: nothing applied here.")
    else:
        print("PRE-REGISTERED ANSWER: NO CHANGE.")
        print("  No cap satisfies all three conditions on both windows, so the prereg's first refutation")
        print("  clause fires: drop the proposal. Record the null and do not reopen for 90 days.")
        print("  NOTE ON WHAT THAT DOES AND DOES NOT SAY: the veto is the ALL-TIME gate. Cap cost is")
        print("  concentrated in the oldest vintage (see the WINDOW STRUCTURE share column) — this read")
        print("  does NOT establish that concentration is load-bearing for returns in the recent book;")
        print("  on the 90d window alone the answer is different. Name the window before quoting it.")
    if both and not both_norm:
        print("  BASIS DIVERGENCE: those caps pass on absolute dollars but NOT per dollar at risk —")
        print("  i.e. they shrink the book rather than improving its tail. Do not call that a tail win.")
    print("  Nothing here was applied; this script opens the DB read-only and writes nothing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
