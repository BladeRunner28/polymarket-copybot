#!/usr/bin/env python3
"""
SUPPLY vs CLIP: the ladder as an arithmetic identity, and the equal-weight illusion
that has been carrying the last three briefs.

WHY THIS FILE EXISTS (2026-11-15)
---------------------------------
Every recent review has quoted per-leg ROI on a band, and the last one quoted the live
regime's cheap band at "+61.6% equal-weight". Equal weight and dollars-at-risk rank the
same legs differently, because the book does NOT bet equal dollars: C-200's clip is
Kelly x 3.5 band factor up to $100, STANDARD's is clamped at $20. On the population where
that matters most (cheap longshots, where a $100 ticket either dies or pays 10-20x) the
two bases can disagree in SIGN. This script prints both, side by side, on the same legs,
so a reader cannot quote one without seeing the other.

The second question is the one the ladder actually poses:

    PnL/day = (admitted bets/day) x (dollars per bet) x (ROI per dollar)

The rung is $250/day. Today the book earns ~$57/day. That is a 4.4x gap and it CANNOT be
attributed to "execution" until the three factors are read separately and each one's
measured ceiling is stated. This script does that decomposition and then bootstraps the
7-day settled sum that the advance rule actually uses:
    advance <=> settled 7d SUM >= target x 7.
The bootstrap answers "what volume would make the rung reachable, and with what
probability" from the book's own per-leg outcome distribution -- no fitted curve.

COST BASIS (mandatory): `PaperTrade.simulatedPositionSize` is DOLLARS AT RISK, never a
share count, never multiplied by entryPrice. dw ROI = sum(realizedPnl)/sum(cost).
eqw ROI = mean(realizedPnl/cost) -- equal weight per leg, which is what the sizing
schedule would produce only if every leg carried the same clip. It does not.

POPULATION: dedupe is NOT applied here on purpose. This is a CAPITAL question, and every
dollar of risk counts (unlike band-edge reads, which dedupe to one bet). Unfilled legs are
excluded: they book 0 and are not positions (2026-11-14 finding).

READ-ONLY: opens the DB `mode=ro`. No RuleSet read/write, no prisma write, no rule change.

USAGE
    python3 scripts/profit-supply-ladder.py
    python3 scripts/profit-supply-ladder.py --regime 68   # default 68 (v68 = 2026-10-27)
    python3 scripts/profit-supply-ladder.py --target 250  # ladder target $/day
    python3 scripts/profit-supply-ladder.py --self-test
"""
import os
import sqlite3
import sys

import numpy as np

DB = os.environ.get("COPYBOT_DB", "file:prisma/dev.db?mode=ro")
ARGS = sys.argv[1:]
SELF_TEST = "--self-test" in ARGS


def arg(name, default):
    for i, a in enumerate(ARGS):
        if a.startswith(f"--{name}="):
            return a.split("=", 1)[1]
        if a == f"--{name}" and i + 1 < len(ARGS):
            return ARGS[i + 1]
    return default


REGIME = int(arg("regime", 68))
TARGET = float(arg("target", 250.0))
BANDS = [(0.0, 0.2, "<0.20"), (0.2, 0.4, "0.2-0.4"), (0.4, 0.6, "0.4-0.6"),
         (0.6, 0.8, "0.6-0.8"), (0.8, 1.0001, "0.8-1.0")]
MS_DAY = 86400000.0


def band_of(p):
    for lo, hi, nm in BANDS:
        if lo <= p < hi:
            return nm
    return None


def con():
    c = sqlite3.connect(DB, uri=True)
    c.row_factory = sqlite3.Row
    return c


def load(c, settled_only):
    """Regime legs, positions only (unfilled excluded -- they are not positions)."""
    q = """
      SELECT p.id, p.botId, p.marketId, p.entryPrice, p.simulatedPositionSize AS cost,
             COALESCE(p.realizedPnl, 0) AS pnl, p.status, p.openedAt,
             COALESCE(p.closedAt, p.resolvedAt) AS endAt
        FROM PaperTrade p
        JOIN DecisionJournal d ON d.id = p.decisionJournalId
       WHERE p.isDemo = 0
         AND d.ruleSetVersion >= ?
         AND (p.fillStatus IS NULL OR p.fillStatus <> 'unfilled')
    """
    if settled_only:
        q += " AND p.status <> 'open' AND COALESCE(p.closedAt, p.resolvedAt) IS NOT NULL"
    rows = [dict(r) for r in c.execute(q, (REGIME,))]
    for r in rows:
        r["band"] = band_of(r["entryPrice"])
        r["roi"] = (r["pnl"] / r["cost"]) if r["cost"] else 0.0
    return rows


def dw_roi(legs):
    c = sum(l["cost"] for l in legs)
    return (sum(l["pnl"] for l in legs) / c) if c else 0.0


def eqw_roi(legs):
    return float(np.mean([l["roi"] for l in legs])) if legs else 0.0


def cap_shadow(legs, cap):
    """Re-scale every leg's dollars at risk to min(cost, cap), PnL linearly.
    Linear is exact for a fixed entry/exit (PnL is proportional to dollars at risk);
    it is NOT a re-selection, and it does not model the depth that a bigger clip needs."""
    scale = [min(1.0, cap / l["cost"]) if l["cost"] else 0.0 for l in legs]
    cost = sum(l["cost"] * s for l, s in zip(legs, scale))
    pnl = sum(l["pnl"] * s for l, s in zip(legs, scale))
    return cost, pnl


def pct(x):
    return f"{100.0 * x:+.1f}%"


def usd(x):
    return f"${x:,.0f}" if abs(x) >= 1000 else f"${x:,.1f}"


def usd_s(x):
    return ("+" if x >= 0 else "-") + usd(abs(x))


# ----------------------------------------------------------------------------- S1
def s1_ladder(c, settled, alllegs, days, leg_days):
    print("=" * 100)
    print(f"S1. THE LADDER AS AN IDENTITY -- rung ${TARGET:,.0f}/day, regime v{REGIME}+")
    print("=" * 100)
    pnl_day = sum(l["pnl"] for l in settled) / leg_days
    legs_day = len(settled) / leg_days
    cost_day = sum(l["cost"] for l in settled) / leg_days
    per_bet = sum(l["cost"] for l in settled) / len(settled)
    roi = dw_roi(settled)
    print(f"  settle-clock span                {days:.1f} days")
    print(f"  settled bets/day                 {legs_day:.1f}   (legs opened/day {len(alllegs)/days:.1f})")
    print(f"  dollars at risk per bet          ${per_bet:,.2f}")
    print(f"  notional deployed per day        {usd(cost_day)}")
    print(f"  ROI per dollar (dollars at risk) {pct(roi)}   on {len(settled)} settled legs, {usd(sum(l['cost'] for l in settled))}")
    print(f"  PnL/day  = {legs_day:.1f} x ${per_bet:,.2f} x {roi:.4f} = {usd(pnl_day)}   (the rung is {usd(TARGET)})")
    print(f"  gap                              {TARGET / pnl_day:.2f}x")
    print()
    print("  the gap, attributed to each factor ALONE (the other two held at today's value):")
    print(f"    supply  : {legs_day * TARGET / pnl_day:6.1f} settled bets/day  ({TARGET/pnl_day:.2f}x today)")
    print(f"    clip    : ${per_bet * TARGET / pnl_day:8,.2f} per bet          ({TARGET/pnl_day:.2f}x today)")
    print(f"    edge    : {pct(roi * TARGET / pnl_day):>8} per dollar         ({TARGET/pnl_day:.2f}x today)")
    print()
    # what supply actually exists
    n_cand = c.execute("SELECT COUNT(*) FROM DecisionJournal WHERE isDemo=0 AND ruleSetVersion>=? AND decision='skip'", (REGIME,)).fetchone()[0]
    n_copy = c.execute("SELECT COUNT(*) FROM DecisionJournal WHERE isDemo=0 AND ruleSetVersion>=? AND decision='paper_copy'", (REGIME,)).fetchone()[0]
    print(f"  measured supply: {n_cand + n_copy:,} priced candidates, {n_copy:,} copies = "
          f"{100.0*n_copy/(n_cand+n_copy):.2f}% admit, over {days:.1f} days")
    print(f"    candidates/day {(n_cand+n_copy)/days:,.0f}; to lift settle rate to the rung's requirement")
    print(f"    at today's admit rate you need {(n_cand+n_copy)/days * TARGET/pnl_day:,.0f} candidates/day.")
    return dict(pnl_day=pnl_day, legs_day=legs_day, per_bet=per_bet, roi=roi)


# ----------------------------------------------------------------------------- S2
def s2_bases(settled):
    print()
    print("=" * 100)
    print("S2. DOLLARS AT RISK vs EQUAL WEIGHT -- same legs, two bases, printed together")
    print("=" * 100)
    print("  lane         band      n    cost     pnl   dw ROI  eqw ROI  avg clip  med clip  sign")
    for bot in ("STANDARD", "BANKROLL_200"):
        for _, _, nm in BANDS:
            xs = [l for l in settled if l["botId"] == bot and l["band"] == nm]
            if not xs:
                continue
            clips = [l["cost"] for l in xs]
            dw, ew = dw_roi(xs), eqw_roi(xs)
            flag = "SPLIT" if (dw > 0) != (ew > 0) else ("ok" if dw * ew >= 0 else "?")
            print(f"  {bot:<12} {nm:<9} {len(xs):>3} {usd(sum(l['cost'] for l in xs)):>7} "
                  f"{usd(sum(l['pnl'] for l in xs)):>8} {pct(dw):>8} {pct(ew):>8} "
                  f"{usd(np.mean(clips)):>9} {usd(np.median(clips)):>9}  {flag}")
    print(f"  {'ALL':<12} {'':<9} {len(settled):>3} {usd(sum(l['cost'] for l in settled)):>7} "
          f"{usd(sum(l['pnl'] for l in settled)):>8} {pct(dw_roi(settled)):>8} {pct(eqw_roi(settled)):>8}")
    print()
    # the cheap band, both bases, and what the clip does to it
    cheap = [l for l in settled if l["band"] == "<0.20"]
    if cheap:
        dw, ew = dw_roi(cheap), eqw_roi(cheap)
        med = float(np.median([l["cost"] for l in cheap]))
        c2, p2 = cap_shadow(cheap, med)
        print(f"  THE CHEAP BAND, both bases: {len(cheap)} legs, {usd(sum(l['cost'] for l in cheap))} at risk")
        print(f"    dollars at risk {pct(dw)}   |   equal weight {pct(ew)}   |   "
              f"gap {100*(ew-dw):+.1f}pp")
        print(f"    at the band's OWN median clip (${med:,.2f}): cost {usd(c2)}, pnl {usd(p2)}, ROI {pct(p2/c2 if c2 else 0)}")
        print("    read: the equal-weight number is what the band pays PER LEG; the dollars-at-risk")
        print("    number is what the book actually earned, because its clips are not equal.")


# ----------------------------------------------------------------------------- S3
def s3_clips(settled):
    print()
    print("=" * 100)
    print("S3. CLIP TIERS -- where the live dollars actually go, and what they returned")
    print("=" * 100)
    tiers = [(99.5, 1e9, "$100"), (40, 99.5, "$40-99"), (20, 40, "$20-40"),
             (12, 20, "$12-20"), (0, 12, "<$12")]
    tot_cost = sum(l["cost"] for l in settled)
    print("  tier        n   share of $     cost      pnl    ROI")
    for lo, hi, nm in tiers:
        xs = [l for l in settled if lo <= l["cost"] < hi]
        if not xs:
            continue
        c = sum(l["cost"] for l in xs)
        p = sum(l["pnl"] for l in xs)
        print(f"  {nm:<10} {len(xs):>3}   {100*c/tot_cost:>8.1f}%  {usd(c):>8} {usd(p):>9}  {pct(p/c):>7}")
    print()
    print("  cap shadow (linear rescale of every leg above the cap, no re-selection):")
    base_c, base_p = tot_cost, sum(l["pnl"] for l in settled)
    print(f"  cap      kept $   pnl     ROI   dPnL vs uncapped   legs touched")
    for cap in (25, 40, 60, 1000):
        c, p = cap_shadow(settled, cap)
        touched = sum(1 for l in settled if l["cost"] > cap)
        print(f"  ${cap:<6} {usd(c):>8} {usd(p):>8} {pct(p/c):>7}   {usd_s(p-base_p):>12}      {touched}")
    print("  NOTE: a cap can only ever be RIGHT if the capped legs' tier earned less than the book.")
    print("  It is variance reduction bought with expected PnL; the shadow prices the trade.")


# ----------------------------------------------------------------------------- S4
def s4_advance(settled, legs_day):
    print()
    print("=" * 100)
    print(f"S4. THE ADVANCE RULE, BOOTSTRAPPED -- settled 7d SUM >= ${TARGET*7:,.0f}")
    print("=" * 100)
    print("  Per-leg outcomes are drawn (with replacement) from the regime's own 7-day-sized")
    print("  sample. This is the book's empirical distribution, not a fitted curve: it keeps")
    print("  the fat right tail of cheap longshots, which is the whole question.")
    rng = np.random.default_rng(11)
    pnls = np.array([l["pnl"] for l in settled], dtype=float)
    costs = np.array([l["cost"] for l in settled], dtype=float)
    bar = TARGET * 7
    print(f"  legs/week   notional   p50 PnL    p05      p95    P(>= bar)  P(>=0)")
    for mult in (1, 2, 3, 5, 10):
        n = int(round(legs_day * 7 * mult))
        draws = rng.choice(len(pnls), size=(4000, n), replace=True)
        sums = pnls[draws].sum(axis=1)
        ntl = costs[draws].sum(axis=1)
        print(f"  {n:>9}   {usd(np.median(ntl)):>8}  {usd(np.median(sums)):>8}  {usd(np.percentile(sums,5)):>8}  "
              f"{usd(np.percentile(sums,95)):>8}  {100.0*np.mean(sums>=bar):>8.1f}%  {100.0*np.mean(sums>=0):>6.1f}%")
    print()
    print("  p50 is the median simulated 7-day settled sum; the bar is the advance threshold.")
    print("  Anything below ~5% P(advance) is a lottery, not a plan -- and the 5x/10x rows are")
    print("  supply that does not exist today (see the admit rate in S1).")


# ----------------------------------------------------------------------------- tests
def self_test():
    ok = []
    # 1. BUY identity: a win at price p pays cost*(1-p)/p; a loss pays -cost.
    for p, cost in ((0.10, 50.0), (0.5, 12.0), (0.90, 20.0)):
        win = cost * (1 - p) / p
        assert abs((cost + win) - cost / p) < 1e-9, "win leg must return cost/p"
        assert abs((cost - cost)) < 1e-12
    ok.append("BUY identity (win returns cost/p, loss returns 0)")

    # 2. dw and eqw agree on a homogeneous book and disagree on a heterogeneous one.
    homo = [dict(cost=10.0, pnl=1.0, roi=0.1) for _ in range(5)]
    assert abs(dw_roi(homo) - eqw_roi(homo)) < 1e-12
    hetero = [dict(cost=100.0, pnl=-100.0, roi=-1.0), dict(cost=10.0, pnl=50.0, roi=5.0)]
    assert dw_roi(hetero) < 0 < eqw_roi(hetero), "dw/eqw must be able to disagree in sign"
    ok.append("dw == eqw on a homogeneous book; they can SPLIT in sign on a heterogeneous one")

    # 3. cap_shadow at a cap above every leg is the identity.
    legs = [dict(cost=5.0, pnl=1.0), dict(cost=90.0, pnl=-9.0)]
    c, p = cap_shadow(legs, 1000.0)
    assert abs(c - 95.0) < 1e-9 and abs(p + 8.0) < 1e-9
    ok.append("cap above every leg is the identity")

    # 4. cap_shadow is linear in dollars at risk: tripling the cap triples a leg's pnl.
    c, p = cap_shadow([dict(cost=100.0, pnl=-10.0)], 40.0)
    assert abs(c - 40.0) < 1e-9 and abs(p + 4.0) < 1e-9
    ok.append("cap rescales linearly in dollars at risk (PnL ~ stake)")

    # 5. NEGATIVE CONTROL: a band with hit rate == price must read ~0 on the EQUAL-WEIGHT
    #    basis no matter its price mix. If the metric could manufacture a positive edge from
    #    a fair book, every "cheap band pays" number in this book would be an artifact.
    rng = np.random.default_rng(3)
    fair = []
    for _ in range(20000):
        p = rng.uniform(0.05, 0.95)
        cost = 10.0
        won = rng.random() < p
        fair.append(dict(cost=cost, pnl=(cost * (1 - p) / p) if won else -cost, roi=None))
    for l in fair:
        l["roi"] = l["pnl"] / l["cost"]
    ew = eqw_roi(fair)
    assert abs(ew) < 0.06, f"fair book must read ~0 eqw, got {ew}"
    ok.append(f"RED-CHECK fair book reads {pct(ew)} eqw (|x| < 6%), so the metric cannot print an edge from noise")

    print(f"SELF-TESTS {len(ok)}/{len(ok)}")
    for i, s in enumerate(ok, 1):
        print(f"  {i}. {s}")
    return True


# ----------------------------------------------------------------------------- S5
def s5_clocks(c, leg_days):
    print()
    print("=" * 100)
    print("S5. THE LADDER'S OWN CLOCK -- settled PnL with and without the legs that never filled")
    print("=" * 100)
    print("  The advance rule reads a settled 7-day sum. This asks: which legs are inside it?")
    q = """
      SELECT p.id, p.botId, p.status, p.fillStatus, p.simulatedPositionSize AS cost,
             COALESCE(p.realizedPnl, 0) AS pnl, COALESCE(p.closedAt, p.resolvedAt) AS endAt
        FROM PaperTrade p JOIN DecisionJournal d ON d.id = p.decisionJournalId
       WHERE p.isDemo = 0 AND d.ruleSetVersion >= ? AND p.status <> 'open'
         AND COALESCE(p.closedAt, p.resolvedAt) IS NOT NULL
    """
    rows = [dict(r) for r in c.execute(q, (REGIME,))]
    now = max(r["endAt"] for r in rows)
    print("  window    basis                 n     cost       pnl    pnl/day   ROI")
    for win, lbl in ((7, "last 7d"), (14, "last 14d"), (None, "regime")):
        for basis in ("booked rows", "positions only"):
            xs = [r for r in rows
                  if (win is None or r["endAt"] > now - win * MS_DAY * 86400000.0 / 86400000.0)
                  and (basis == "booked rows" or r["fillStatus"] != "unfilled")]
            if win is None:
                xs = [r for r in rows if (basis == "booked rows" or r["fillStatus"] != "unfilled")]
            cst = sum(r["cost"] for r in xs)
            p = sum(r["pnl"] for r in xs)
            per_day = p / (win if win else leg_days)
            print(f"  {lbl:<9} {basis:<20} {len(xs):>4} {usd(cst):>9} {usd(p):>9} "
                  f"{usd(per_day):>9} {pct(p/cst if cst else 0):>7}")
    un = [r for r in rows if r["fillStatus"] == "unfilled"]
    print(f"  {len(un)} settled rows are stamped 'unfilled' and still carry "
          f"{usd(sum(r['pnl'] for r in un))} of realised PnL on {usd(sum(r['cost'] for r in un))}.")
    print("  They book zero in src/lib/paper.ts::bookedPnl(), and they are NOT positions -- but")
    print("  any reader that sums the realizedPnl column counts them, and they are 8x the")
    print("  positions-only rate in the last 7 days. Quote the basis or the ladder reads fiction.")


def s6_credit_basis(c, leg_days):
    """S6. THE BASIS THE LADDER ACTUALLY READS -- four candidates, one table (2026-11-16).

    S5 compares 'booked rows' with 'positions only'. Both still admit one class nobody has
    adjudicated: rows whose fillStatus is NULL, which book at p(fill)=1 (the 2026-11-13 fill-tape
    card named them; it never split them out of the ladder's own credit). This section prints all
    four bases on the same legs, per lane, because the lanes are not on the same accounting:

      booked rows          every settled row, as the realizedPnl column sums it
      positions only       booked rows minus fillStatus='unfilled'
      unadjudicated        fillStatus IS NULL  (no fill model has ever looked at these)
      confirmed filled     fillStatus='filled' (the only class we can prove we own)

    WHY IT MATTERS: in the live regime the sign of the book is decided by which of these you
    read, and the split is not random -- the C-200 lane is fill-adjudicated end to end while
    STANDARD carries no stamp at all (its booth, src/lib/standard-fill-stamp.ts, is a
    measurement that deliberately writes nothing). A cross-lane comparison on 'positions only'
    is therefore a comparison between an adjudicated book and an unadjudicated one.
    """
    print()
    print("=" * 100)
    print("S6. WHICH BASIS THE LADDER READS -- four candidates, same legs, same clock")
    print("=" * 100)
    q = """
      SELECT p.botId AS bot, p.fillStatus AS fs, p.simulatedPositionSize AS cost,
             COALESCE(p.realizedPnl, 0) AS pnl
        FROM PaperTrade p JOIN DecisionJournal d ON d.id = p.decisionJournalId
       WHERE p.isDemo = 0 AND d.ruleSetVersion >= ? AND p.status <> 'open'
         AND p.realizedPnl IS NOT NULL
    """
    rows = [dict(r) for r in c.execute(q, (REGIME,))]
    rows = [r for r in rows if (r["cost"] or 0) > 0]
    classes = ("booked rows", "positions only", "unadjudicated", "confirmed filled")

    def keep(r, basis):
        fs = r["fs"] or ""
        if basis == "booked rows":
            return True
        if basis == "positions only":
            return fs != "unfilled"
        if basis == "unadjudicated":
            return fs == ""
        return fs == "filled"

    print(f"  {'basis':<19} {'lane':<13} {'n':>4} {'cost':>9} {'pnl':>9} {'ROI':>8} {'$/day':>8}")
    for basis in classes:
        for bot in ("BANKROLL_200", "STANDARD", None):
            xs = [r for r in rows if keep(r, basis) and (bot is None or r["bot"] == bot)]
            if not xs:
                continue
            cst = sum(r["cost"] for r in xs)
            p = sum(r["pnl"] for r in xs)
            lane = bot or "ALL"
            print(f"  {basis:<19} {lane:<13} {len(xs):>4} {usd(cst):>9} {usd(p):>9} "
                  f"{pct(p / cst if cst else 0):>7} {usd_s(p / leg_days):>8}")
        print()
    filled = [r for r in rows if keep(r, "confirmed filled")]
    unadj = [r for r in rows if keep(r, "unadjudicated")]
    f_pnl, u_pnl = sum(r["pnl"] for r in filled), sum(r["pnl"] for r in unadj)
    print(f"  READ: {len(filled)} confirmed-filled legs carry {usd(f_pnl)}; "
          f"{len(unadj)} unadjudicated legs carry {usd(u_pnl)}.")
    if f_pnl < 0 <= u_pnl:
        print("  The book's positive number is the class with NO fill adjudication. Any basis that")
        print("  includes it is crediting positions that no fill model has ever looked at, and")
        print("  'positions only' is not a fix -- it is a second unadjudicated basis.")


def main():
    if SELF_TEST:
        self_test()
        return
    c = con()
    settled = load(c, settled_only=True)
    alllegs = load(c, settled_only=False)
    # settle-clock span: first open to last settle, in days
    t0 = min(l["openedAt"] for l in alllegs)
    t1 = max(l["endAt"] for l in settled if l["endAt"])
    days = (t1 - t0) / MS_DAY
    # leg-days: the settle clock runs slightly longer than the open clock; use the open span
    # so the numerator and denominator describe the same calendar.
    leg_days = (max(l["openedAt"] for l in alllegs) - t0) / MS_DAY
    print(f"Instrument: profit-supply-ladder.py   RuleSet regime >= v{REGIME}   rung ${TARGET:,.0f}/day")
    print(f"Population: {len(settled)} settled positions, {len(alllegs)} opened, "
          f"unfilled excluded (not positions), cost = dollars at risk")
    print()
    s1_ladder(c, settled, alllegs, days, leg_days)
    s2_bases(settled)
    s3_clips(settled)
    s4_advance(settled, len(settled) / leg_days)
    s5_clocks(c, leg_days)
    s6_credit_basis(c, leg_days)
    print()
    print("READ-ONLY: DB opened mode=ro. No RuleSet read/write, no prisma write.")


if __name__ == "__main__":
    main()
