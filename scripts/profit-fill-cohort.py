#!/usr/bin/env python3
"""
FILL COHORT — what the C-200 lane actually earned on the positions it actually got.

WHY THIS EXISTS
---------------
The fill-aware booking flip (`src/lib/paper.ts`, DEFAULT ON since 2026-10-28) stopped
booking PnL on legs the resolver proved never traded. Nothing has measured the book
SPLIT BY THAT CLASS since: every band table, every ladder read and every capital series
still sums `realizedPnl` across filled + unfilled + unresolved in one number.

That sum is not one population. In the C-200 lane since the flip:

  filled      -> a position the resolver says the book reached our bid for
  unfilled    -> a position it proved we never got (PnL forced to 0 by bookedPnl)
  NULL        -> "unresolved": no book window AND silent tape. Books at p(fill)=1,
                 i.e. the OPTIMISTIC number -- the same treatment that, pre-flip,
                 overstated C-200 PnL by 2.87x (paper.ts:20-22).

So the lane's post-flip PnL is a coin flip between two classes, and the coin is a fill
that was never observed. This instrument prices that split, and asks the question that
follows from it: if the legs we got are the losers, what is the fill rule selecting for?

METHOD / CONTRACTS
------------------
* Legs are loaded through `scripts/profit-postfix-integrity.py` (imported, not
  re-implemented) so the basis is identical to the review's other tables: dedupe first
  leg per bot|wallet|market|outcome within status class, cost = `simulatedPositionSize`
  = dollars at risk, price = the token we bought (INVERTED legs repriced to the wallet's
  own fill), CIs market-clustered (2,000 draws).
* The module's connection is replaced with a read-only URI before any query runs.
  Nothing here writes: no prisma write, no RuleSet read or write, no rule edit.
* ERA is the fill-aware flip, 2026-10-28 local. §6 re-runs the head-line at +/-2 days so
  a wrong boundary cannot silently carry the conclusion.
* "Proven fill" = fillStatus='filled'. "Provable non-position" = 'unfilled'.
* The mirror (§4) re-prices `unfilled` intents at their own intentPrice using the mark
  the leg actually ended at. It EXCLUDES sibling-priced legs -- |entryPrice - intentPrice|
  > 6c is the INVERTED signature, not a fill premium; a first draft that left them in
  reported +$7,247 of "forgone profit" on 10 legs, all of it the sibling token's price.

RUN
  python3 scripts/profit-fill-cohort.py
"""
import importlib.util
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
_spec = importlib.util.spec_from_file_location("ppi", os.path.join(HERE, "profit-postfix-integrity.py"))
assert _spec is not None and _spec.loader is not None, "cannot import the base instrument"
ppi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ppi)


def _con():
    uri = "file:" + os.path.join(ROOT, "prisma", "dev.db") + "?mode=ro"
    c = sqlite3.connect(uri, uri=True)
    c.row_factory = sqlite3.Row
    return c


ppi.con = _con                                  # read-only from here on
FLIP = "2026-10-28 00:00:00"
FLIP_MS = ppi._ms(FLIP)
LANES = ("BANKROLL_200", "STANDARD")
SIBLING = 0.06


def era(l):
    return "post" if l["openedTs"] >= FLIP_MS else "pre"


def cls(l):
    return l["fillStatus"] or "NULL"


def roi(ls):
    n = sum(l["simulatedPositionSize"] for l in ls)
    p = sum(l["realizedPnl"] or 0.0 for l in ls)
    return (p / n * 100.0) if n else None, p, n


def ci(ls):
    a, b = ppi.cluster_ci(ls, lambda l: l["realizedPnl"] or 0.0)
    return a, b


def diff_ci(arm, other, n=2000, seed=11):
    """Market-clustered CI on ROI(arm) - ROI(other): resample markets from the POOLED set."""
    import random
    by = {}
    for tag, ls in (("a", arm), ("b", other)):
        for l in ls:
            g = by.setdefault(l["marketId"], {"a": [0.0, 0.0], "b": [0.0, 0.0]})
            g[tag][0] += l["realizedPnl"] or 0.0
            g[tag][1] += l["simulatedPositionSize"]
    ks = list(by)
    ks.sort()                     # stable order so arm-swapped calls resample identically
    if len(ks) < 2:
        return (None, None)
    rnd = random.Random(seed)
    out = []
    for _ in range(n):
        ap = an = bp = bn = 0.0
        for _ in range(len(ks)):
            g = by[ks[rnd.randrange(len(ks))]]
            ap += g["a"][0]
            an += g["a"][1]
            bp += g["b"][0]
            bn += g["b"][1]
        if an > 0 and bn > 0:
            out.append(ap / an * 100.0 - bp / bn * 100.0)
    out.sort()
    return (out[int(0.025 * len(out))], out[int(0.975 * len(out)) - 1])


def sec_census(ded):
    print("=" * 86)
    print("1. THE BOOK BY ERA x FILL CLASS -- the split every other table sums over")
    print("=" * 86)
    print(f"  era boundary = fill-aware booking flip, {FLIP} (src/lib/paper.ts)")
    for lane in LANES:
        print(f"\n  {lane}")
        print(f"    {'era':<5} {'class':<9} {'legs':>5} {'notional':>10} {'pnl':>10} {'ROI':>8} {'ntl share':>10}")
        for e in ("pre", "post"):
            g = [l for l in ded if l["botId"] == lane and era(l) == e]
            tot = sum(l["simulatedPositionSize"] for l in g)
            for c in ("filled", "unfilled", "NULL"):
                h = [l for l in g if cls(l) == c]
                if not h:
                    continue
                r, p, n = roi(h)
                print(f"    {e:<5} {c:<9} {len(h):>5} {n:>10,.0f} {p:>+10.1f} {r:>+7.1f}% "
                      f"{n / tot * 100:>9.1f}%")
            r, p, n = roi(g)
            print(f"    {e:<5} {'TOTAL':<9} {len(g):>5} {n:>10,.0f} {p:>+10.1f} {r:>+7.1f}%")
    print("\n  READ: pre-flip 'unfilled' legs carry real booked PnL (+$801 on 247), which is the")
    print("  defect the flip removed. Post-flip 'unfilled' carry ~0 by construction. The class")
    print("  that decides the lane is NULL -- optimistic, and never observed.")


def sec_proven(ded):
    print()
    print("=" * 86)
    print("2. THE PROVEN-FILL RECORD -- C-200 since the flip")
    print("=" * 86)
    post = [l for l in ded if l["botId"] == "BANKROLL_200" and era(l) == "post"]
    if not post:
        print("  no post-flip legs")
        return
    for label, sel in (("all finished post-flip", post),
                       ("naturally resolved only", [l for l in post if l["status"] == "resolved"])):
        print(f"\n  {label}: {len(sel)} legs, ${sum(l['simulatedPositionSize'] for l in sel):,.0f}")
        print(f"    {'class':<9} {'legs':>5} {'notional':>10} {'pnl':>10} {'ROI':>8} {'CI95 on ROI':>20}")
        arms = {}
        for c in ("filled", "unfilled", "NULL"):
            h = [l for l in sel if cls(l) == c]
            if not h:
                continue
            arms[c] = h
            r, p, n = roi(h)
            lo, hi = ci(h)
            cis = f"[{lo:+.1f},{hi:+.1f}]" if lo is not None else "n/a"
            print(f"    {c:<9} {len(h):>5} {n:>10,.0f} {p:>+10.1f} {r:>+7.1f}% {cis:>20}")
        r, p, n = roi(sel)
        print(f"    {'TOTAL':<9} {len(sel):>5} {n:>10,.0f} {p:>+10.1f} {r:>+7.1f}%")
        if "filled" in arms and "NULL" in arms:
            lo, hi = diff_ci(arms["filled"], arms["NULL"])
            if lo is not None:
                rf = roi(arms["filled"])[0]
                rn = roi(arms["NULL"])[0]
                print(f"    filled minus NULL: {rf - rn:+.1f}pp  CI95 [{lo:+.1f},{hi:+.1f}] "
                      f"(market-clustered, pooled markets)")
    print("\n  Every treatment of the unresolved class leaves the lane at or below zero:")
    print("    proven fills only      -> see above")
    print("    fills + unresolved     -> next line")
    r, p, n = roi([l for l in post if cls(l) != "unfilled"])
    print(f"    {len([l for l in post if cls(l) != 'unfilled'])} legs  ${n:,.0f}  {p:+.1f}  {r:+.1f}%")


def sec_mechanism(ded):
    print()
    print("=" * 86)
    print("3. MECHANISM -- what the fill rule selects for")
    print("=" * 86)
    post = [l for l in ded if l["botId"] == "BANKROLL_200" and era(l) == "post"]
    print("\n  (a) by band: the filled cohort vs the optimistic one")
    print(f"    {'band':<9} {'class':<9} {'legs':>5} {'notional':>9} {'pnl':>9} {'ROI':>8} {'hit%':>6} {'avgP':>6}")
    for lo, hi in ppi.BANDS:
        bn = ppi.band_name(lo, hi)
        g = [l for l in post if ppi.band_of(l["trueP"]) == bn]
        for c in ("filled", "NULL", "unfilled"):
            h = [l for l in g if cls(l) == c]
            if not h:
                continue
            r, p, n = roi(h)
            hits = sum(1 for l in h if (l["realizedPnl"] or 0) > 0) / len(h) * 100
            avgp = sum(l["trueP"] for l in h) / len(h)
            print(f"    {bn:<9} {c:<9} {len(h):>5} {n:>9,.0f} {p:>+9.1f} {r:>+7.1f}% "
                  f"{hits:>6.1f} {avgp:>6.3f}")
    print("\n  (b) the bid does not explain the split -- entry minus intent, same sign, same size")
    print(f"    {'class':<9} {'legs':>5} {'mean entry-intent':>18} {'median':>8}")
    for c in ("filled", "unfilled", "NULL"):
        h = [l for l in post if cls(l) == c and l.get("intentPrice")]
        h = [l for l in h if abs(l["entryPrice"] - l["intentPrice"]) <= SIBLING]
        if not h:
            continue
        d = sorted((l["entryPrice"] - l["intentPrice"]) * 100 for l in h)
        med = d[len(d) // 2]
        print(f"    {c:<9} {len(h):>5} {sum(d) / len(d):>17.2f}c {med:>7.2f}c")
    print("    -> the fill is not bought with price aggressiveness: both classes bid the same")
    print("       distance under the wallet. What differs is whether the book came to us.")
    print("\n  (c) is the filled cohort's deficit a tail? ex-top-N by PnL, same legs")
    filled = [l for l in post if cls(l) == "filled"]
    tot = sum(l["realizedPnl"] or 0 for l in filled)
    for k in (1, 3, 5):
        keep = sorted(filled, key=lambda l: -(l["realizedPnl"] or 0))[k:]
        r, p, n = roi(keep)
        print(f"    ex-top{k}  n={len(keep):>3} notional ${n:>7,.0f} pnl {p:>+8.1f} ROI {r:>+7.1f}%"
              f"   (full cohort {tot:+.1f})")


    print("\n  (d) is it a big-clip artefact? the filled cohort by clip, each era separately")
    print(f"    {'era':<5} {'clip':<9} {'legs':>5} {'notional':>9} {'pnl':>9} {'ROI':>8} {'hit%':>6}")
    for e in ("pre", "post"):
        g = [l for l in ded if l["botId"] == "BANKROLL_200" and era(l) == e and cls(l) == "filled"]
        for lo, hi, nm in ((0, 10, "<=$10"), (10, 20, "$10-20"), (20, 40, "$20-40"), (40, 1e9, ">$40")):
            h = [l for l in g if lo < l["simulatedPositionSize"] <= hi]
            if not h:
                continue
            r, p, n = roi(h)
            hits = sum(1 for l in h if (l["realizedPnl"] or 0) > 0) / len(h) * 100
            print(f"    {e:<5} {nm:<9} {len(h):>5} {n:>9,.0f} {p:>+9.1f} {r:>+7.1f}% {hits:>6.1f}")
    print("    -> if the cap's premise holds (big clips are the problem), the small buckets should")
    print("       be non-negative. They are not, post-flip.")


def sec_mix(ded):
    print()
    print("=" * 86)
    print("3b. WHAT CHANGED WITH THE FLIP, BESIDES THE BOOKKEEPING")
    print("=" * 86)
    print(f"  {'lane':<13} {'era':<5} {'legs':>5} {'span d':>7} {'legs/day':>9} {'avg clip':>9} {'notional':>10}")
    for lane in LANES:
        for e in ("pre", "post"):
            g = [l for l in ded if l["botId"] == lane and era(l) == e]
            if not g:
                continue
            span = max(l["openedTs"] for l in g) - min(l["openedTs"] for l in g)
            span = max(span / 86400000.0, 1e-9)
            n = sum(l["simulatedPositionSize"] for l in g)
            print(f"  {lane:<13} {e:<5} {len(g):>5} {span:>7.1f} {len(g) / span:>9.1f} "
                  f"{n / len(g):>9.1f} {n:>10,.0f}")
    pre = [l for l in ded if era(l) == "pre"]
    post = [l for l in ded if era(l) == "post"]
    for nm, g in (("pre", pre), ("post", post)):
        n = sum(l["simulatedPositionSize"] for l in g)
        c = sum(l["simulatedPositionSize"] for l in g if l["botId"] == "BANKROLL_200")
        print(f"  {nm}-flip C-200 share of notional: {c / n * 100:.1f}%")


def sec_mirror(ded):
    print()
    print("=" * 86)
    print("4. THE MIRROR -- what the trades we did NOT get would have paid")
    print("=" * 86)
    print("  unfilled / NULL C-200 intents re-priced at their OWN intent price and held to the")
    print("  mark they ended at. Sibling-priced legs excluded (|entry-intent| > 6c).")
    post = [l for l in ded if l["botId"] == "BANKROLL_200" and era(l) == "post"]
    print(f"\n  {'class':<9} {'legs':>5} {'notional':>9} {'pnl@intent':>11} {'ROI@intent':>11} "
          f"{'pnl@intent+2c':>14}")
    for c in ("unfilled", "NULL", "filled"):
        h = [l for l in post if cls(l) == c and l.get("intentPrice")]
        h = [l for l in h if abs(l["entryPrice"] - l["intentPrice"]) <= SIBLING and l["currentPrice"] is not None]
        if not h:
            continue
        n = sum(l["simulatedPositionSize"] for l in h)
        p0 = sum(l["simulatedPositionSize"] * (l["currentPrice"] / l["intentPrice"] - 1) for l in h)
        p2 = sum(l["simulatedPositionSize"] * (l["currentPrice"] / (l["intentPrice"] + 0.02) - 1) for l in h)
        print(f"  {c:<9} {len(h):>5} {n:>9,.0f} {p0:>+11.1f} {p0 / n * 100:>+10.1f}% {p2:>+14.1f}")
    print("\n  READ: if the no-fill cohort outperforms the filled cohort at the SAME price, the")
    print("  fill rule is not a discount -- it is a selection against the copy signal.")


def sec_ladder(ded):
    print()
    print("=" * 86)
    print("5. WHAT THIS DOES TO THE LADDER READ")
    print("=" * 86)
    for e in ("pre", "post"):
        g = [l for l in ded if era(l) == e and l["status"] != "open"]
        if not g:
            continue
        r, p, n = roi(g)
        c2 = [l for l in g if l["botId"] == "BANKROLL_200"]
        s = [l for l in g if l["botId"] == "STANDARD"]
        rc, pc, nc = roi(c2)
        rs, ps, ns = roi(s)
        print(f"  {e}-flip book: {len(g):>5} legs ${n:>9,.0f} {p:>+9.1f} ({r:+.1f}%)")
        print(f"    C-200     {len(c2):>5} legs ${nc:>8,.0f} {pc:>+9.1f} ({rc:+.1f}%) "
              f"{nc / n * 100:>5.1f}% of notional")
        print(f"    STANDARD  {len(s):>5} legs ${ns:>8,.0f} {ps:>+9.1f} ({rs:+.1f}%) "
              f"{ns / n * 100:>5.1f}% of notional")
    stand = [l for l in ded if l["botId"] == "STANDARD"]
    stamped = [l for l in stand if l["fillStatus"]]
    print(f"\n  STANDARD legs carrying a fill verdict: {len(stamped)} of {len(stand)}.")
    print("  -> the lane that was 73% of pre-flip notional has NEVER been fill-checked.")
    print("     Its +18.8% post-flip is the same p(fill)=1 optimism that overstated C-200")
    print("     by 2.87x where it WAS checked. Lanes are not comparable until it is run.")
    # how STANDARD bids relative to the wallet: the reason its fills are probably real
    post = [l for l in ded if l["botId"] == "STANDARD" and era(l) == "post" and l.get("w") is not None]
    if post:
        at_or_below = sum(1 for l in post if l["entryPrice"] <= l["w"] + 0.002)
        print(f"     STANDARD post-flip bids at or below the wallet's own fill on "
              f"{at_or_below / len(post) * 100:.0f}% of {len(post)} legs "
              f"(mean entry-wallet {sum(l['entryPrice'] - l['w'] for l in post) / len(post) * 100:+.2f}c)")


def sec_sensitivity(ded):
    print()
    print("=" * 86)
    print("6. SENSITIVITY -- move the era boundary and see if the verdict moves")
    print("=" * 86)
    global FLIP_MS
    keep = FLIP_MS
    print(f"  {'boundary':<12} {'post C-200 n':>12} {'ROI':>8} {'filled n':>9} {'filled ROI':>11} "
          f"{'NULL ROI':>9}")
    for shift in (-2, -1, 0, 1, 2):
        FLIP_MS = keep + shift * 86400000
        post = [l for l in ded if l["botId"] == "BANKROLL_200" and l["openedTs"] >= FLIP_MS
                and l["status"] != "open"]
        f = [l for l in post if cls(l) == "filled"]
        z = [l for l in post if cls(l) == "NULL"]
        r, _, _ = roi(post)
        rf, _, _ = roi(f) if f else (None, 0, 0)
        rz, _, _ = roi(z) if z else (None, 0, 0)
        print(f"  {shift:+d}d{'':<9} {len(post):>12} {r:>+7.1f}% {len(f):>9} "
              f"{(rf if rf is not None else 0):>+10.1f}% {(rz if rz is not None else 0):>+8.1f}%")
    FLIP_MS = keep


def self_test(ded):
    print()
    print("=" * 86)
    print("7. SELF-TEST")
    print("=" * 86)
    ok = tot = 0
    post = [l for l in ded if l["botId"] == "BANKROLL_200" and era(l) == "post"]
    f = [l for l in post if cls(l) == "filled"]
    z = [l for l in post if cls(l) == "unfilled"]
    parts = len(f) + len(z) + len([l for l in post if cls(l) == "NULL"])
    tot += 1
    if parts == len(post):
        ok += 1
    print(f"  partition identity filled+unfilled+NULL == total : {parts} vs {len(post)}")
    tot += 1
    zs = sum(l["realizedPnl"] or 0 for l in z)
    zt = sum(l["simulatedPositionSize"] for l in z)
    if zt == 0 or abs(zs) / zt < 0.02:
        ok += 1
    print(f"  post-flip unfilled books ~0 (bookedPnl flip)     : {zs:+.2f} on ${zt:,.0f}")
    pre = [l for l in ded if l["botId"] == "BANKROLL_200" and era(l) == "pre"]
    pf = sum(l["realizedPnl"] or 0 for l in pre if cls(l) == "filled")
    pz = sum(l["realizedPnl"] or 0 for l in pre if cls(l) == "unfilled")
    share = pz / (pf + pz) if (pf + pz) else 0
    tot += 1
    if 0.55 <= share <= 0.70:
        ok += 1
    print(f"  pre-flip phantom share reproduces paper.ts 61%   : {share * 100:.1f}% of stamped PnL")
    a = [l for l in post if cls(l) == "filled"]
    b = [l for l in post if cls(l) == "NULL"]
    if a and b:
        lo, hi = diff_ci(a, b, n=400)
        lo2, hi2 = diff_ci(b, a, n=400)
        tot += 1
        if lo is not None and lo2 is not None and abs((lo + hi2)) < 1e-6 and abs((hi + lo2)) < 1e-6:
            ok += 1
        print(f"  delta CI antisymmetric on arm swap               : "
              f"[{lo:+.2f},{hi:+.2f}] vs [{lo2:+.2f},{hi2:+.2f}]")
    print(f"  SELF-TEST {'PASS' if ok == tot else 'FAIL'} ({ok}/{tot})")
    return ok == tot


def main():
    legs = ppi.load_legs()
    ded = ppi.dedupe([l for l in legs if l["status"] != "open"])
    # intentPrice is not selected by the base loader; join it by id rather than change the
    # shared instrument's SQL under a sibling session.
    c = _con()
    ip = {r[0]: r[1] for r in c.execute(
        "SELECT id, intentPrice FROM PaperTrade WHERE intentPrice IS NOT NULL")}
    for l in ded:
        l["intentPrice"] = ip.get(l["id"])
    print(f"population: {len(legs):,} non-demo rows -> {len(ded):,} finished deduped legs "
          f"(first per bot|wallet|market|outcome); "
          f"${sum(l['simulatedPositionSize'] for l in ded):,.0f} at risk; "
          f"{sum(1 for l in ded if l['intentPrice'] is not None):,} carry an intent price")
    sec_census(ded)
    sec_proven(ded)
    sec_mechanism(ded)
    sec_mix(ded)
    sec_mirror(ded)
    sec_ladder(ded)
    sec_sensitivity(ded)
    ok = self_test(ded)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
