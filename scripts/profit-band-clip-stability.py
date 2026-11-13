#!/usr/bin/env python3
"""BAND CLIP STABILITY -- how much of the cap's measured delta any SINGLE leg carries,
what the clip tiers actually earn inside the two paying bands, and the forward cadence
that decides how long a pre-registered re-read has to wait.

WHY THIS FILE EXISTS (2026-11-12, Lane A proposal profit-band-clip-rebalance)
----------------------------------------------------------------------------
`profit-band-clip-preflight.py` prices the cap/lift arms and their clustered CIs. It
cannot say whether those CIs are stable: the cheap band books $50-100 clips at 5-19x
payoffs, so ONE resolution can move a regime delta by several hundred dollars -- and did,
between the 11-11 read and this one (cap regime delta +$790 -> +$476 after a single +$552
leg resolved). So this instrument reports, on the same basis:

  1  ALLOCATION      notional share vs PnL share per band, average clip per band
  2  CLIP TIERS      ROI by clip tier INSIDE each of the two paying bands (in-band test of
                     "the clip is inverse to the edge": if big clips earn MORE per dollar
                     inside the band, a cap is a variance trade, not an edge trade)
  3  BINDING LANE    which lane can exceed $25 in the cheap band at all
  4  LEAVE-ONE-OUT   the regime cap delta recomputed with each cap-touched leg removed --
                     the honest error bar on a 20-leg sample
  5  CADENCE         legs/day on the band, and the days a 150-leg forward read needs

BASIS (imported, not copied, from profit-postfix-integrity.py)
  cost = simulatedPositionSize = DOLLARS at risk; dedupe = first leg per
  bot|wallet|market|outcome within status class; true price = the wallet's fill only for
  the INVERTED price-side class; PnL scales linearly in size at a fixed price.

READ-ONLY. Opens the DB through COPYBOT_DB; pass a `file:...?mode=ro` URI to prove it.

USAGE
    COPYBOT_DB="file:$PWD/prisma/dev.db?mode=ro" python3 scripts/profit-band-clip-stability.py
"""
from __future__ import annotations

import datetime
import importlib.util
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "ppi", os.path.join(HERE, "profit-postfix-integrity.py"))
assert _spec is not None and _spec.loader is not None, "cannot load profit-postfix-integrity.py"
ppi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ppi)

CAP = 25.0
PLAN = [{"band": "0.0-0.2", "cap": CAP}]
READ_DAYS = 150


def money(v):
    return f"{v:+,.2f}"


def delta_of(legs, plan=PLAN):
    tot, by = 0.0, {}
    for l in legs:
        po = ppi.true_pnl(l, l["trueP"]) or 0.0
        old = l["simulatedPositionSize"] or 0.0
        new = ppi._resize(l, plan) or 0.0
        pn = po * (new / old) if old > 0 else po
        tot += pn - po
        by[l["marketId"]] = by.get(l["marketId"], 0.0) + (pn - po)
    return tot, by


def cluster_ci(legs, reps=2000, seed=11):
    """Market-clustered bootstrap on the delta sum (same shape as the preflight's)."""
    _, by = delta_of(legs)
    ks = list(by)
    if not ks:
        return None, None
    rnd = random.Random(seed)
    out = sorted(sum(by[ks[rnd.randrange(len(ks))]] for _ in range(len(ks))) for _ in range(reps))
    return out[int(0.025 * len(out))], out[int(0.975 * len(out)) - 1]


def main():
    legs = ppi.load_legs()
    risk = ppi.risk_legs(ppi.dedupe([l for l in legs if l["status"] != "open"]))
    reg = [l for l in risk if l["openedTs"] >= ppi._ms(ppi.REGIME)]
    print(f"instrument: profit-band-clip-stability.py  (imports profit-postfix-integrity)")
    print(f"DB: {ppi.DB}")
    print(f"populations: all-time {len(risk):,} legs, regime {len(reg):,}\n")

    # ---------------------------------------------------------------- 1
    print("=" * 78)
    print("1. ALLOCATION -- notional share vs PnL share, and the average clip per band")
    print("=" * 78)
    tot_ntl = sum(l["simulatedPositionSize"] or 0 for l in risk)
    tot_pnl = sum(ppi.true_pnl(l, l["trueP"]) or 0 for l in risk)
    print(f"  {'band':>9} {'n':>5} {'avgclip':>8} {'ntl':>10} {'ntl%':>6} {'pnl':>10} {'pnl%':>6} {'roi':>8}")
    for lo, hi in ppi.BANDS:
        sub = [l for l in risk if lo <= l["trueP"] < hi]
        if not sub:
            continue
        ntl = sum(l["simulatedPositionSize"] or 0 for l in sub)
        pnl = sum(ppi.true_pnl(l, l["trueP"]) or 0 for l in sub)
        print(f"  {ppi.band_name(lo, hi):>9} {len(sub):>5} {ntl/len(sub):>8.2f} {ntl:>10,.0f} "
              f"{ntl/tot_ntl*100:>5.1f}% {pnl:>10,.0f} {pnl/tot_pnl*100:>5.1f}% "
              f"{pnl/ntl*100 if ntl else 0:>+7.1f}%")

    # ---------------------------------------------------------------- 2
    print("\n" + "=" * 78)
    print("2. CLIP TIERS INSIDE THE TWO PAYING BANDS -- is the clip inverse to the edge?")
    print("=" * 78)
    tiers = [(0, 10), (10, 15), (15, 20), (20, 25), (25, 1e9)]
    for lo, hi in ((0.0, 0.2), (0.2, 0.4)):
        print(f"  band {ppi.band_name(lo, hi)}")
        sub = [l for l in risk if lo <= l["trueP"] < hi]
        for a, b in tiers:
            s = [l for l in sub if a <= (l["simulatedPositionSize"] or 0) < b]
            label = f"${a}-{b:,}" if b < 1e9 else f"${a}+"
            if not s:
                print(f"    {label:>12}: (none)")
                continue
            ntl = sum(l["simulatedPositionSize"] or 0 for l in s)
            pnl = sum(ppi.true_pnl(l, l["trueP"]) or 0 for l in s)
            print(f"    {label:>12}: n={len(s):>4} ntl={ntl:>9,.0f} pnl={pnl:>9,.0f} "
                  f"roi={pnl/ntl*100:>+7.1f}%")

    # ---------------------------------------------------------------- 3
    print("\n" + "=" * 78)
    print("3. BINDING LANE -- who can exceed $25 in 0.0-0.2 at all")
    print("=" * 78)
    for lane in ("BANKROLL_200", "STANDARD"):
        s = [l for l in risk if l["botId"] == lane and l["trueP"] < 0.2]
        b = [l for l in s if (l["simulatedPositionSize"] or 0) > CAP]
        ntl = sum(l["simulatedPositionSize"] or 0 for l in b)
        pnl = sum(ppi.true_pnl(l, l["trueP"]) or 0 for l in b)
        mx = max((l["simulatedPositionSize"] for l in s), default=0.0)
        print(f"  {lane:<13} band n={len(s):>4}  >$25 n={len(b):>3}  ntl={ntl:>8,.0f}  "
              f"pnl={pnl:>+9,.0f}  roi={pnl/ntl*100 if ntl else 0:>+6.1f}%  maxclip=${mx:,.2f}")

    # ---------------------------------------------------------------- 4
    print("\n" + "=" * 78)
    print("4. LEAVE-ONE-OUT -- the regime cap delta with each cap-touched leg removed")
    print("=" * 78)
    base, _ = delta_of(reg)
    lo_ci, hi_ci = cluster_ci(reg)
    touched = [l for l in reg
               if (l["simulatedPositionSize"] or 0) > CAP and ppi.band_of(l["trueP"]) == "0.0-0.2"]
    print(f"  base delta {money(base)}  CI [{money(lo_ci)},{money(hi_ci)}]  touched legs={len(touched)}")
    print(f"  {'opened':>10} {'px':>6} {'clip':>6} {'pnl':>10} {'cap effect':>11}  wallet")
    for l, in ((x,) for x in sorted(touched, key=lambda y: y["openedTs"])):
        po = ppi.true_pnl(l, l["trueP"]) or 0.0
        eff = po * (CAP / (l["simulatedPositionSize"] or 1)) - po
        ts = datetime.datetime.utcfromtimestamp(l["openedTs"] / 1000).strftime("%Y-%m-%d")
        print(f"  {ts:>10} {l['trueP']:>6.3f} {l['simulatedPositionSize']:>6.0f} {po:>+10,.2f} "
              f"{eff:>+11,.2f}  {l['walletAddress'][:10]}")
    vals = []
    for l in touched:
        sub = [x for x in reg if x["id"] != l["id"]]
        vals.append(delta_of(sub)[0])
    print(f"\n  leave-one-out: min {money(min(vals))}  max {money(max(vals))}  "
          f"spread {money(max(vals)-min(vals))}")
    print("  read: a delta that moves by this much on ONE leg is a 20-leg sample, not a measurement.")

    # ---------------------------------------------------------------- 5
    print("\n" + "=" * 78)
    print("5. CADENCE -- how long a forward re-read has to wait")
    print("=" * 78)
    days = sorted({l["openedTs"] // 86400000 for l in reg})
    n_days = len(days)
    cb = [l for l in reg if ppi.band_of(l["trueP"]) == "0.0-0.2"]
    print(f"  regime opens 2026-10-26; {len(reg)} finished legs over {n_days} open days "
          f"= {len(reg)/n_days:.1f}/day")
    print(f"  cheap-band legs {len(cb)} = {len(cb)/n_days:.2f}/day -> "
          f"{READ_DAYS} legs in {READ_DAYS/(len(cb)/n_days):.0f} days")
    print(f"  cap-touched legs (>{CAP:,.0f}) {len(touched)} = {len(touched)/n_days:.2f}/day -> "
          f"{READ_DAYS} touched legs in {READ_DAYS/(len(touched)/n_days):.0f} days")

    # ---------------------------------------------------------------- 6
    print("\n" + "=" * 78)
    print("6. WAS THE CARD'S REGIME CI A TIME SLICE?  same statistic, earlier populations")
    print("=" * 78)
    print("  The 11-11 proposal (drafts/profit-band-clip-rebalance-20261111.md) quoted the cap's")
    print("  regime arm as +$790, CI +290..+1,324. If that is the same statistic on an earlier")
    print("  population, truncating the regime at that date reproduces it and the difference is")
    print("  FLOW, not method -- which is the whole question of whether the arm is measurable.")
    for cut in ("2026-11-11 00:00:00", "2026-11-11 12:00:00", "2026-11-12 00:00:00"):
        pop = [l for l in reg if l["openedTs"] < ppi._ms(cut)]
        d, _ = delta_of(pop)
        lo, hi = cluster_ci(pop)
        sub_cb = [l for l in pop if ppi.band_of(l["trueP"]) == "0.0-0.2"]
        t = [l for l in sub_cb if (l["simulatedPositionSize"] or 0) > CAP]
        print(f"  opened < {cut}  legs={len(pop):>4} cheap={len(sub_cb):>3} touched={len(t):>2} "
              f"delta={money(d):>9} CI [{money(lo)},{money(hi)}]")
    print("  read: the same instrument, same basis, moves the CI across zero in one day of flow.")


if __name__ == "__main__":
    main()
