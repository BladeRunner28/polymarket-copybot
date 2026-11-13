#!/usr/bin/env python3
"""
PROFIT-BAND-CLIP-PREFLIGHT -- what the proposed band-relative clip actually binds,
who it binds on, and what the cap BUYS (it does not earn).

WHY THIS FILE EXISTS (2026-11-11, Lane A proposal profit-band-clip-rebalance)
---------------------------------------------------------------------------
`profit-postfix-integrity.py --only=G,J` measures the EDGE (hit rate vs price paid)
and prices six sizing plans as a band-relative clip on realised legs. It answers
"how much PnL would the same legs have booked at a different clip". It does not
answer the four questions that decide whether the plan is a lever or a bet:

  1  DOES THE CAP BIND?  A $25 cap on 0.0-0.2 only touches legs already ABOVE $25.
     How many, in which lane, and what did they earn? A cap that trims 3% of the
     notional but 30% of the profit is a variance purchase, not an edge trade, and
     must be reported as one.
  2  DOES THE LIFT BIND?  A $25 floor on 0.2-0.4 only touches legs BELOW $25. Both
     lanes clamp downstream (BOT_LIMITS: STANDARD $20.00, BANKROLL_200 $20.00 legacy
     / kellyMaxSizeUsd for Kelly-sized), so a floor above the clamp binds on nothing.
     The lift is therefore scoped to whatever path can exceed $20 -- measure that,
     do not assume the whole band moves.
  3  IS THE DELTA A TAIL?  The lift arm's all-time CI excludes zero on a band whose
     whole edge is a handful of wins. Re-price it ex-top-1-wallet and ex-top-1-market
     in the same output; a delta that lives in one wallet is not a band effect.
  4  WHAT DOES THE CAP BUY?  If the point is risk, the currency is drawdown: the
     single worst local day and the max peak-to-trough of the closed-leg daily series,
     base vs plan, on the SAME legs.

BASIS (identical by contract to profit-postfix-integrity.py, imported, not copied)
  cost = simulatedPositionSize = DOLLARS at risk; dedupe = first leg per
  bot|wallet|market|outcome within status class; true price = wallet fill only for
  the INVERTED class; PnL scales linearly in size at a fixed price.

READ-ONLY. Opens the DB through COPYBOT_DB (use a `file:...?mode=ro` URI to prove
it); writes no row, no RuleSet, no file.

USAGE
    COPYBOT_DB="file:$PWD/prisma/dev.db?mode=ro" python3 scripts/profit-band-clip-preflight.py
"""
from __future__ import annotations

import importlib.util
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "ppi", os.path.join(HERE, "profit-postfix-integrity.py"))
assert _spec is not None and _spec.loader is not None, "cannot load profit-postfix-integrity.py"
ppi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ppi)

CAP = 25.0
LEGACY_CLAMP = 20.0   # BOT_LIMITS max for STANDARD and for the legacy C-200 path
REPS = 2000


def money(v):
    return f"{v:+,.2f}"


def pct(v):
    return f"{v:+.1f}%"


def plan_cap():
    return [{"band": "0.0-0.2", "cap": CAP}]


def plan_lift():
    return [{"band": "0.2-0.4", "lift": CAP}]


def plan_package():
    return [{"band": "0.0-0.2", "cap": CAP}, {"band": "0.2-0.4", "lift": CAP}]


def delta_of(legs, plan):
    """(delta $, old notional, new notional, per-market delta map)."""
    tot = 0.0
    n_old = n_new = 0.0
    by = {}
    for l in legs:
        po = ppi.true_pnl(l, l["trueP"]) or 0.0
        old = l["simulatedPositionSize"] or 0.0
        new = ppi._resize(l, plan) or 0.0
        pn = po * (new / old) if old > 0 else po
        n_old += old
        n_new += new
        tot += pn - po
        g = by.setdefault(l["marketId"], 0.0)
        by[l["marketId"]] = g + (pn - po)
    return tot, n_old, n_new, by


def cluster_ci_delta(legs, plan, seed=11):
    """Market-clustered bootstrap on the DELTA per $1,000 of notional."""
    tot, n_old, _, by = delta_of(legs, plan)
    ks = list(by)
    if not ks or n_old <= 0:
        return None, None
    rnd = random.Random(seed)
    out = []
    for _ in range(REPS):
        s = 0.0
        for _ in range(len(ks)):
            s += by[ks[rnd.randrange(len(ks))]]
        out.append(s)
    out.sort()
    lo, hi = out[int(0.025 * len(out))], out[int(0.975 * len(out)) - 1]
    # express as dollars on THIS population's notional (the CI is on the delta sum)
    return lo, hi


def ex_wallet(legs, k):
    by = {}
    for l in legs:
        by[l["walletAddress"]] = by.get(l["walletAddress"], 0.0) + (ppi.true_pnl(l, l["trueP"]) or 0.0)
    gone = set(sorted(by, key=lambda w: -by[w])[:k])
    return [l for l in legs if l["walletAddress"] not in gone]


def ex_market(legs, k):
    by = {}
    for l in legs:
        by[l["marketId"]] = by.get(l["marketId"], 0.0) + (ppi.true_pnl(l, l["trueP"]) or 0.0)
    gone = set(sorted(by, key=lambda m: -by[m])[:k])
    return [l for l in legs if l["marketId"] not in gone]


def plan_lift20():
    """The lift with NO clamp change: 0.2-0.4 to the $20 BOT_LIMITS ceiling."""
    return [{"band": "0.2-0.4", "lift": LEGACY_CLAMP}]


def plan_package20():
    return [{"band": "0.0-0.2", "cap": CAP}, {"band": "0.2-0.4", "lift": LEGACY_CLAMP}]


def plan_implementable_lift():
    """Lift each 0.2-0.4 leg only as far as its own observed ceiling proves it can go.

    A leg already booked above $20 came through a path that can exceed the $20
    BOT_LIMITS clamp (the C-200 Kelly path, kellyMaxSizeUsd = the active RuleSet's
    100); it can reach $25. A leg at or below $20 may be legacy-clamped (C-200
    legacy $20.00, STANDARD $20.00), where a $25 floor would be clamped straight
    back to $20 -- so it is lifted to $20, which needs no clamp change at all.
    """
    return [{"band": "0.2-0.4", "lift": None}]  # handled per leg in _resize_impl


def _resize_impl(l):
    old = l["simulatedPositionSize"] or 0.0
    if ppi.band_of(l["trueP"]) != "0.2-0.4":
        return old
    target = CAP if old > LEGACY_CLAMP else LEGACY_CLAMP
    return max(old, target)


def delta_of_impl(legs):
    tot = 0.0
    n_old = n_new = 0.0
    by = {}
    for l in legs:
        po = ppi.true_pnl(l, l["trueP"]) or 0.0
        old = l["simulatedPositionSize"] or 0.0
        new = _resize_impl(l)
        pn = po * (new / old) if old > 0 else po
        n_old += old
        n_new += new
        tot += pn - po
        by[l["marketId"]] = by.get(l["marketId"], 0.0) + (pn - po)
    return tot, n_old, n_new, by


def cluster_ci_impl(legs, seed=11):
    tot, n_old, _, by = delta_of_impl(legs)
    ks = list(by)
    if not ks or n_old <= 0:
        return None, None
    rnd = random.Random(seed)
    out = []
    for _ in range(REPS):
        s = 0.0
        for _ in range(len(ks)):
            s += by[ks[rnd.randrange(len(ks))]]
        out.append(s)
    out.sort()
    return out[int(0.025 * len(out))], out[int(0.975 * len(out)) - 1]


def day_series(legs, plan=None):
    """Per-local-day PnL of finished legs, optionally re-priced by a plan."""
    out = {}
    for l in legs:
        end = l["closedAt"] or l["resolvedAt"]
        if not end:
            continue
        d = ppi.market_day(ppi._ms(end))
        po = ppi.true_pnl(l, l["trueP"]) or 0.0
        if plan:
            old = l["simulatedPositionSize"] or 0.0
            new = ppi._resize(l, plan) or 0.0
            po = po * (new / old) if old > 0 else po
        out[d] = out.get(d, 0.0) + po
    return out


def drawdown(series):
    days = sorted(series)
    cum = peak = 0.0
    mdd = 0.0
    worst_day, worst_day_v = None, 0.0
    for d in days:
        v = series[d]
        if v < worst_day_v:
            worst_day, worst_day_v = d, v
        cum += v
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    return worst_day, worst_day_v, mdd, cum


def hdr(t):
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


def main():
    print(f"instrument: profit-band-clip-preflight.py  (imports profit-postfix-integrity)")
    print(f"DB: {ppi.DB}")
    legs = ppi.load_legs()
    fin = ppi.dedupe([l for l in legs if l["status"] != "open"])
    risk = ppi.risk_legs(fin)
    reg_from = ppi._ms(ppi.REGIME)
    clean_from = ppi._ms(ppi.FIX_EPOCH)
    reg = [l for l in risk if l["openedTs"] >= reg_from]
    clean = [l for l in risk if l["openedTs"] >= clean_from]
    print(f"populations: all-time {len(risk):,} legs, regime {len(reg):,}, pre-fix repair cohort {len(clean):,}")

    # ---------------------------------------------------------------- 1
    hdr("1. DOES THE CAP BIND?  legs ABOVE $25 in 0.0-0.2, by lane")
    print(f"  {'pop':<10} {'lane':<14} {'n':>4} {'n>25':>5} {'ntl':>9} {'ntl>25':>9} "
          f"{'pnl>25':>10} {'ROI>25':>8} {'share of band pnl':>18}")
    for label, pop in (("ALL-TIME", risk), ("REGIME", reg), ("PRE-FIX", clean)):
        band = [l for l in pop if ppi.band_of(l["trueP"]) == "0.0-0.2"]
        if not band:
            continue
        band_pnl = sum((ppi.true_pnl(l, l["trueP"]) or 0.0) for l in band)
        for lane in ("BANKROLL_200", "STANDARD", "ALL"):
            c = band if lane == "ALL" else [l for l in band if l["botId"] == lane]
            if not c:
                continue
            over = [l for l in c if (l["simulatedPositionSize"] or 0) > CAP]
            ntl = sum(l["simulatedPositionSize"] for l in c)
            nontl = sum(l["simulatedPositionSize"] for l in over)
            npnl = sum((ppi.true_pnl(l, l["trueP"]) or 0.0) for l in over)
            print(f"  {label:<10} {lane:<14} {len(c):>4} {len(over):>5} {ntl:>9,.0f} "
                  f"{nontl:>9,.0f} {money(npnl):>10} "
                  f"{(npnl / nontl * 100 if nontl else 0):>+7.1f}% "
                  f"{(npnl / band_pnl * 100 if band_pnl else 0):>17.0f}%")
        print()
    clipmax = max((l["simulatedPositionSize"] for l in risk if ppi.band_of(l["trueP"]) == "0.0-0.2"),
                  default=0)
    print(f"  largest 0.0-0.2 clip in the whole book: ${clipmax:,.2f}")

    # ---------------------------------------------------------------- 2
    hdr("2. DOES THE LIFT BIND?  legs BELOW $25 in 0.2-0.4, by lane + downstream clamps")
    print("  BOT_LIMITS: STANDARD max $20.00 | BANKROLL_200 legacy max $20.00 |")
    print("  BANKROLL_200 Kelly legs clamp at kellyMaxSizeUsd instead. A $25 floor cannot")
    print("  move a leg whose lane clamp is $20 -- so measure who is under the floor AND")
    print("  who can legally reach $25.\n")
    print(f"  {'pop':<10} {'lane':<14} {'n':>4} {'n<25':>5} {'missing $ to reach 25':>22} "
          f"{'pnl of <25 legs':>16} {'ROI':>8}")
    for label, pop in (("ALL-TIME", risk), ("REGIME", reg)):
        band = [l for l in pop if ppi.band_of(l["trueP"]) == "0.2-0.4"]
        for lane in ("BANKROLL_200", "STANDARD", "ALL"):
            c = band if lane == "ALL" else [l for l in band if l["botId"] == lane]
            if not c:
                continue
            under = [l for l in c if (l["simulatedPositionSize"] or 0) < CAP]
            missing = sum(CAP - l["simulatedPositionSize"] for l in under)
            p_ = sum((ppi.true_pnl(l, l["trueP"]) or 0.0) for l in under)
            ntl = sum(l["simulatedPositionSize"] for l in under)
            print(f"  {label:<10} {lane:<14} {len(c):>4} {len(under):>5} {missing:>22,.0f} "
                  f"{money(p_):>16} {(p_ / ntl * 100 if ntl else 0):>+7.1f}%")
        print()
    over = [l for l in risk if ppi.band_of(l["trueP"]) == "0.2-0.4"
            and (l["simulatedPositionSize"] or 0) >= CAP]
    print(f"  legs ALREADY >= $25 in 0.2-0.4 (a floor cannot change them): {len(over)}")
    by_lane = {}
    for l in over:
        by_lane[l["botId"]] = by_lane.get(l["botId"], 0) + 1
    print(f"    by lane: {by_lane or '{}'}")

    # ---------------------------------------------------------------- 3
    hdr("3. THE THREE ARMS PER LANE, with a market-clustered CI on the DELTA")
    print(f"  {'pop':<10} {'lane':<14} {'arm':<14} {'delta $':>10} {'CI $ (clustered)':>22} "
          f"{'ntl old->new':>18}")
    for label, pop in (("ALL-TIME", risk), ("REGIME", reg), ("PRE-FIX", clean)):
        for lane in ("BANKROLL_200", "STANDARD", "ALL"):
            c = pop if lane == "ALL" else [l for l in pop if l["botId"] == lane]
            if len(c) < 20:
                continue
            for arm, plan in (("cap $25", plan_cap()), ("lift $25", plan_lift()),
                              ("lift $20", plan_lift20()), ("pkg cap25+lift20", plan_package20()),
                              ("package", plan_package())):
                d, no, nn, _ = delta_of(c, plan)
                lo, hi = cluster_ci_delta(c, plan)
                cis = f"[{money(lo)},{money(hi)}]" if lo is not None else "n/a"
                print(f"  {label:<10} {lane:<14} {arm:<14} {money(d):>10} "
                      f"{(d / no * 100 if no else 0):>+6.1f}pp {cis:>22} "
                      f"{no:>8,.0f}->{nn:<8,.0f}")
            print()

    # ---------------------------------------------------------------- 4
    hdr("4. IS THE DELTA A TAIL?  ex-top wallet / ex-top market, same arms")
    for label, pop in (("ALL-TIME", risk), ("REGIME", reg)):
        for arm, plan, bn in (("LIFT 0.2-0.4", plan_lift(), "0.2-0.4"),
                              ("CAP 0.0-0.2", plan_cap(), "0.0-0.2")):
            band = [l for l in pop if ppi.band_of(l["trueP"]) == bn]
            if len(band) < 20:
                continue
            print(f"  {label} {bn} ({arm}): n={len(band)} "
                  f"pnl {money(sum((ppi.true_pnl(l, l['trueP']) or 0.0) for l in band))}")
            for k in (0, 1, 2, 5):
                c = ex_wallet(band, k) if k else band
                d, no, nn, _ = delta_of(c, plan)
                cm = ex_market(band, k) if k else band
                dm, _, _, _ = delta_of(cm, plan)
                print(f"    ex-top-{k} wallet: n={len(c):>3} delta {money(d):>9} | "
                      f"ex-top-{k} market: n={len(cm):>3} delta {money(dm):>9}")
            print()

    # ---------------------------------------------------------------- 5
    hdr("5. WHAT DOES THE CAP BUY?  worst day and max drawdown, same legs, base vs plan")
    print(f"  {'pop':<10} {'arm':<10} {'cum pnl':>11} {'worst day':>12} {'when':>12} "
          f"{'max DD':>10}")
    for label, pop in (("ALL-TIME", risk), ("REGIME", reg)):
        for arm, plan in (("base", None), ("cap $25", plan_cap()), ("package", plan_package())):
            s = day_series(pop, plan)
            wd, wdv, mdd, cum = drawdown(s)
            print(f"  {label:<10} {arm:<10} {money(cum):>11} {money(wdv):>12} "
                  f"{str(wd):>12} {money(mdd):>10}")
        print()

    # ---------------------------------------------------------------- 7
    hdr("7. WHAT CAN ACTUALLY EXECUTE?  the lift is bounded by each lane's clamp")
    print("  Active RuleSet read: kellyMaxSizeUsd is the only ceiling above $20; the legacy")
    print("  path and STANDARD stop at BOT_LIMITS $20.00. So the card's lift ($25 on every")
    print("  0.2-0.4 leg) is an UPPER BOUND. Arm 7b lifts each leg only as far as its own")
    print("  booked clip proves it can go (legs booked >$20 -> $25; the rest -> $20).\n")
    print(f"  {'pop':<10} {'lane':<14} {'arm':<22} {'delta $':>10} {'pp':>8} "
          f"{'CI $ (clustered)':>22} {'ntl old->new':>18}")
    for label, pop in (("ALL-TIME", risk), ("REGIME", reg), ("PRE-FIX", clean)):
        for lane in ("BANKROLL_200", "STANDARD", "ALL"):
            c = pop if lane == "ALL" else [l for l in pop if l["botId"] == lane]
            if len(c) < 20:
                continue
            d, no, nn, _ = delta_of_impl(c)
            lo, hi = cluster_ci_impl(c)
            cis = f"[{money(lo)},{money(hi)}]" if lo is not None else "n/a"
            print(f"  {label:<10} {lane:<14} {'7b lift-to-own-ceiling':<22} {money(d):>10} "
                  f"{(d / no * 100 if no else 0):>+7.1f}pp {cis:>22} {no:>8,.0f}->{nn:<8,.0f}")
        print()

    hdr("8. KELLY CHECK -- what fraction of bankroll each band's OWN record justifies")
    print("  A buy at p wins (1-p)/p per unit staked (b) and loses 1, so")
    print("  f* = (h*b - (1-h))/b = h - (1-h)*p/(1-p).   f* < 0 = the band's own record")
    print("  says bet nothing. The book bets ~0.2% of bankroll, so nothing here is")
    print("  binding -- it RANKS the bands, which is the question this card turns on.\n")
    print(f"  {'basis':<10} {'band':<8} {'n':>4} {'hit':>6} {'avgP':>6} {'edge pp':>8} {'f*':>7}")
    for basis, pop in (("finished", risk),
                       ("resolved", [l for l in risk if l["status"] == "resolved"])):
        for lo, hi in ppi.BANDS:
            bn = ppi.band_name(lo, hi)
            g = [l for l in pop if ppi.band_of(l["trueP"]) == bn]
            if len(g) < 20:
                continue
            h = sum(1 for l in g if (ppi.true_pnl(l, l["trueP"]) or 0.0) > 0) / len(g)
            p = sum(l["trueP"] for l in g) / len(g)
            f = h - (1 - h) * p / (1 - p) if 0 < p < 1 else 0.0
            print(f"  {basis:<10} {bn:<8} {len(g):>4} {h * 100:>5.1f}% {p:>6.3f} "
                  f"{(h - p) * 100:>+7.1f} {f * 100:>+6.1f}%")
        print()

    # ---------------------------------------------------------------- 6
    hdr("6. WINDOW SHAPE -- how many days and legs the regime claim rests on")
    days = sorted({ppi.market_day(l["openedTs"]) for l in reg})
    print(f"  regime opens {ppi.REGIME[:10]}, legs {len(reg)}, distinct open days {len(days)} "
          f"({days[0]}..{days[-1]})")
    print(f"  legs/day {len(reg) / max(1, len(days)):.1f}; resolved share "
          f"{sum(1 for l in reg if l['status'] == 'resolved') / max(1, len(reg)) * 100:.0f}%")
    print(f"  pre-fix repair cohort: {len(clean)} legs, "
          f"{sum(1 for l in clean if l['status'] == 'resolved')} resolved")


if __name__ == "__main__":
    main()
