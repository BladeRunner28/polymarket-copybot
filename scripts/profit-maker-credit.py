#!/usr/bin/env python3
"""
PROFIT REVIEW INSTRUMENT -- 2026-10-30: what the 2c maker credit is actually worth.

WHY THIS FILE EXISTS (extend, don't fork -- and don't repeat a defect)
profit-band-report.py answers "what does each entry band earn". profit-velocity.py answers
"per capital-day". profit-sellside.py answers "is the exit copyable". NONE of them answers
the question this review needed: **how much of C-200's PnL is the 2c of price improvement
the sidecar books, and is that 2c worth more where we put our money?**

THE ARITHMETIC TRAP THIS FILE WAS WRITTEN TO AVOID. My first pass priced the credit per
share: `pnl_at_intent = pnl - shares*(intent - entry)`. That is WRONG, and wrong in a way
that flatters the finding. The correct identity, from pnl = n*((s/p) - 1) with n = dollars
at risk:

    s = p*(pnl + n)/n              (s = settlement 1/0 or exit price c)
    pnl_at_intent = n*(s/ip - 1) = p*(pnl + n)/ip - n

Two consequences, and the second is the whole point:

  1. A LOSING leg's credit is worth exactly ZERO. Buying at 0.48 instead of 0.50 loses the
     same $10 when the outcome settles 0. The per-share formula charged losers too.
  2. A winning leg's credit is worth n*(ip-p)/(p*ip), which is HYPERBOLIC in price: 4.2% of
     stake at p=0.48, 16.7% at p=0.12, 100% at p=0.02. So a flat 2c credit is a *band-shaped*
     subsidy, and its total value is set by how much notional sits in the cheap tail.

That is why C-200 (58% of its recent notional below 0.20) and STANDARD (no credit at all)
cannot be compared as-is, and why "the profitable lane" needs its credit re-priced before
any sizing decision cites it.

COST BASIS: simulatedPositionSize = DOLLARS AT RISK, never shares.

USAGE
    python3 scripts/profit-maker-credit.py
    python3 scripts/profit-maker-credit.py --selftest   # identity checks only

READ-ONLY. No prisma write, no RuleSet read-modify-write, no wire calls (no fetch at all:
the credit is a stored column pair, entryPrice and intentPrice).
"""
import sqlite3
import sys
import time

DB = "prisma/dev.db"
BANDS = [(0.0, 0.10, "0.00-0.10"), (0.10, 0.20, "0.10-0.20"), (0.20, 0.40, "0.20-0.40"),
         (0.40, 0.60, "0.40-0.60"), (0.60, 0.80, "0.60-0.80"), (0.80, 1.0001, "0.80-1.00")]
FLIP_MS = int(time.mktime(time.strptime("2026-10-28 00:00:00", "%Y-%m-%d %H:%M:%S")) * 1000)


def band(p):
    for lo, hi, nm in BANDS:
        if lo <= p < hi:
            return nm
    return None


def con():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def load(c, bot, since_ms=0):
    """Every finished leg. Dedupe = first leg per (wallet, market, outcome), the band-report
    convention, so this table is comparable to the band ROIs already quoted in drafts/."""
    rows = c.execute("""
        SELECT marketId, walletAddress, outcome, entryPrice px, intentPrice ip,
               simulatedPositionSize ntl, realizedPnl pnl, fillStatus fs,
               openedAt, COALESCE(resolvedAt, closedAt) endms, status
        FROM PaperTrade
        WHERE botId=? AND isDemo=0 AND status IN ('closed','resolved')
          AND realizedPnl IS NOT NULL AND simulatedPositionSize>0 AND entryPrice>0
          AND COALESCE(resolvedAt, closedAt) >= ?
        ORDER BY openedAt ASC""", (bot, since_ms)).fetchall()
    out, seen = [], set()
    for r in rows:
        k = (r["walletAddress"], r["marketId"], r["outcome"])  # band-report convention
        if k in seen:
            continue
        seen.add(k)
        out.append(dict(mkt=r["marketId"], px=r["px"], ip=r["ip"], ntl=r["ntl"],
                        pnl=r["pnl"], fs=r["fs"], endms=r["endms"], band=band(r["px"])))
    return out


def pnl_at(leg, entry):
    """PnL of the same position if it had been entered at `entry` instead of leg['px'].
    Derived from the PnL identity, NOT from a per-share adjustment: see header."""
    n, p, pnl = leg["ntl"], leg["px"], leg["pnl"]
    if entry <= 0 or p <= 0:
        return pnl
    return (p * (pnl + n) / entry) - n


def credit(leg):
    """The credit a leg actually received, in dollars of PnL. Zero when there is no intent."""
    if not leg["ip"] or leg["ip"] <= 0:
        return 0.0
    return pnl_at(leg, leg["px"]) - pnl_at(leg, leg["ip"])


def zeroed(leg):
    """The current booking rule (paper.ts bookedPnl): unfilled -> 0."""
    return 0.0 if leg["fs"] == "unfilled" else leg["pnl"]


def show(legs, label, pnlfn):
    ntl = sum(l["ntl"] for l in legs)
    p = sum(pnlfn(l) for l in legs)
    if not ntl:
        return
    s = sorted(legs, key=lambda l: -pnlfn(l))
    ex = s[10:]
    exr = 100 * sum(pnlfn(l) for l in ex) / sum(l["ntl"] for l in ex) if ex else 0.0
    print(f"   {label:26} n={len(legs):>5} ntl=${ntl:>9,.0f} pnl=${p:>+8,.0f} "
          f"ROI={100*p/ntl:>+7.1f}%  ex-top10={exr:>+7.1f}%")


def selftest(c):
    print("SELFTEST -- the re-pricing identity must reproduce stored PnL at the stored price.")
    worst = 0.0
    for bot in ("BANKROLL_200", "STANDARD"):
        for l in load(c, bot):
            worst = max(worst, abs(pnl_at(l, l["px"]) - l["pnl"]))
    print(f"   max |pnl_at(entry) - realizedPnl| = ${worst:.6f}  (rounding of the size column)")
    # a losing leg must have zero credit regardless of the price gap
    fake = dict(px=0.48, ip=0.50, ntl=10.0, pnl=-10.0)
    print(f"   losing leg  0.48 vs 0.50: credit ${credit(fake):+.4f} (must be 0)")
    fake = dict(px=0.48, ip=0.50, ntl=10.0, pnl=10/0.48 - 10)
    print(f"   winning leg 0.48 vs 0.50: credit ${credit(fake):+.4f} "
          f"= {100*credit(fake)/10:.1f}% of stake")
    fake = dict(px=0.12, ip=0.14, ntl=10.0, pnl=10/0.12 - 10)
    print(f"   winning leg 0.12 vs 0.14: credit ${credit(fake):+.4f} "
          f"= {100*credit(fake)/10:.1f}% of stake  <- same 2c, 4x the stake")
    return worst


def main():
    c = con()
    if "--selftest" in sys.argv:
        selftest(c)
        return
    print("=" * 104)
    print("MC. MAKER CREDIT -- what the 2c is worth, where, and why the lanes are not comparable")
    print("=" * 104)
    selftest(c)

    print("\nMC.1 CREDIT DISTRIBUTION by month (C-200 only; STANDARD has no intent price at all)")
    rows = c.execute("""SELECT strftime('%Y-%m', openedAt/1000,'unixepoch') m, entryPrice px,
                               intentPrice ip FROM PaperTrade
                        WHERE botId='BANKROLL_200' AND isDemo=0 AND intentPrice IS NOT NULL""").fetchall()
    print(f"   {'month':8} {'legs':>5} {'exactly 2.00c':>14} {'mean c':>8} {'min c':>7} {'max c':>7}")
    mon = {}
    for r in rows:
        mon.setdefault(r["m"], []).append(r["ip"] - r["px"])
    for m in sorted(mon):
        g = mon[m]
        ex = sum(1 for g2 in g if abs(g2 - 0.02) < 1e-9)
        print(f"   {m:8} {len(g):>5} {ex:>9}/{len(g):<4} {100*sum(g)/len(g):>8.2f} "
              f"{100*min(g):>7.2f} {100*max(g):>7.2f}")
    print("   A flat 2.00c column is the MODELLED credit; a spread is the measured one.")

    for label, days in (("90d", 90), ("30d", 30), ("all-time", 36500)):
        since = int((time.time() - days * 86400) * 1000) if days < 36500 else 0
        print(f"\nMC.2 {label} -- booked vs current-rule vs intent-priced vs both")
        for bot in ("BANKROLL_200", "STANDARD"):
            legs = load(c, bot, since)
            if not legs:
                continue
            print(f"\n  {bot}")
            show(legs, "as booked", lambda l: l["pnl"])
            show(legs, "current rule (unfilled=0)", zeroed)
            show(legs, "entry at intent price", lambda l: pnl_at(l, l["ip"]) if l["ip"] else l["pnl"])
            print(f"   credit total = ${sum(credit(l) for l in legs):+,.2f} on "
                  f"{sum(1 for l in legs if l['ip'])} intent-stamped legs")

    print("\nMC.3 WHERE THE CREDIT LANDS -- credit as % of stake per leg, by band (90d)")
    since = int((time.time() - 90 * 86400) * 1000)
    for bot in ("BANKROLL_200", "STANDARD"):
        legs = load(c, bot, since)
        print(f"\n  {bot}")
        print(f"   {'band':10} {'legs':>5} {'ntl':>9} {'credit$':>9} {'credit%stake':>13} "
              f"{'ROI booked':>11} {'ROI@intent':>11}")
        for lo, hi, nm in BANDS:
            b = [l for l in legs if l["band"] == nm]
            if len(b) < 5:
                continue
            ntl = sum(l["ntl"] for l in b)
            cr = sum(credit(l) for l in b)
            pb = sum(l["pnl"] for l in b)
            pi = sum(pnl_at(l, l["ip"]) if l["ip"] else l["pnl"] for l in b)
            print(f"   {nm:10} {len(b):>5} {ntl:>9,.0f} {cr:>+9,.0f} {100*cr/ntl:>12.1f}% "
                  f"{100*pb/ntl:>+10.1f}% {100*pi/ntl:>+10.1f}%")

    print("\nMC.4 THE FILL FLIP -- does the 2026-10-28 rule verify clean, and what did it cost")
    rows = c.execute("""SELECT fillStatus fs, realizedPnl pnl, simulatedPositionSize ntl,
                               COALESCE(resolvedAt, closedAt) endms, status
                        FROM PaperTrade WHERE botId='BANKROLL_200' AND isDemo=0
                          AND fillStatus IS NOT NULL""").fetchall()
    pre = [r for r in rows if (r["endms"] or 0) < FLIP_MS]
    post = [r for r in rows if (r["endms"] or 0) >= FLIP_MS]
    for lab, g in (("ended before flip", pre), ("ended on/after flip", post)):
        un = [r for r in g if r["fs"] == "unfilled"]
        bad = [r for r in un if (r["pnl"] or 0) != 0]
        print(f"   {lab:20} unfilled={len(un):>4} (${sum(r['ntl'] for r in un):>8,.0f})  "
              f"nonzero-PnL violations={len(bad):>3} (${sum(r['pnl'] or 0 for r in bad):>+8,.0f})")
    print("   Violations after the flip would mean the rule is not landing. Zero = it is.")

    print("\nMC.5 WHAT THIS DOES TO THE LANE COMPARISON (90d, both lanes on the current rule + intent)")
    print("   C-200's headline includes 2c of assumed price improvement on 100% of its legs and")
    print("   PnL on legs a fill-aware book would zero. STANDARD has neither. Quote them apart.")
    for bot in ("BANKROLL_200", "STANDARD"):
        legs = load(c, bot, since)
        def both(l):
            return 0.0 if l["fs"] == "unfilled" else (pnl_at(l, l["ip"]) if l["ip"] else l["pnl"])
        show(legs, f"{bot} current+intent", both)

    print("\nMC.6 BREAKEVEN ENTRY SLIPPAGE -- the axis-5 number, per band (90d, current rule)")
    print("   'slippage cents' = how much worse the fill can be before that band's realised PnL")
    print("   reaches zero. Solved on the PnL identity, so a leg's own outcome is preserved.")
    for bot in ("BANKROLL_200", "STANDARD"):
        legs = load(c, bot, since)
        print(f"\n  {bot}")
        print(f"   {'band':10} {'legs':>5} {'ntl':>9} {'ROI':>7} {'breakeven c':>12} {'ROI@+1c':>9}")
        for lo, hi, nm in BANDS:
            b = [l for l in legs if l["band"] == nm and l["fs"] != "unfilled"]
            if len(b) < 10:
                continue
            ntl = sum(l["ntl"] for l in b)
            base = sum(l["pnl"] for l in b)
            # solve sum(pnl_at(px+d)) = 0 by bisection on d in [0, 0.95]. Monotone non-increasing:
            # winners' payoff falls with d, losers' loss is already capped at the stake.
            lo_d, hi_d, found = 0.0, 0.95, None
            if sum(pnl_at(l, l["px"] + hi_d) for l in b) <= 0 <= sum(pnl_at(l, l["px"]) for l in b):
                for _ in range(60):
                    mid = (lo_d + hi_d) / 2
                    if sum(pnl_at(l, l["px"] + mid) for l in b) > 0:
                        lo_d = mid
                    else:
                        hi_d = mid
                found = (lo_d + hi_d) / 2
            plus1 = sum(pnl_at(l, l["px"] + 0.01) for l in b)
            print(f"   {nm:10} {len(b):>5} {ntl:>9,.0f} {100*base/ntl:>+6.1f}% "
                  f"{(f'{100*found:.1f}' if found is not None else '    none'):>12} "
                  f"{100*plus1/ntl:>+8.1f}%")

    print("\nMC.8 THE CHEAP TAIL IS TWO POPULATIONS -- split at 0.10, market-clustered CI, ex-top-N")
    print("   A 3.5x longshot factor and a 1.0 factor both treat 'under 0.20' as one thing.")
    print("   Payoff asymmetry says the bands differ by an order of magnitude: breakeven hit rate")
    print("   is p, so 0.05 tolerates 14pp of model error and 0.15 tolerates 44pp.")
    import random
    for bot in ("BANKROLL_200", "STANDARD"):
        legs = load(c, bot, since)
        print(f"\n  {bot}")
        for nm, lo, hi in (("0.00-0.10", 0.0, 0.10), ("0.10-0.20", 0.10, 0.20), ("<0.20", 0.0, 0.20)):
            b = [l for l in legs if lo <= l["px"] < hi and l["fs"] != "unfilled"]
            if len(b) < 10:
                continue
            ntl = sum(l["ntl"] for l in b)
            p = sum(l["pnl"] for l in b)
            s = sorted(b, key=lambda l: -l["pnl"])
            def roi_of(xs):
                n2 = sum(l["ntl"] for l in xs)
                return 100 * sum(l["pnl"] for l in xs) / n2 if n2 else 0.0
            # market-clustered bootstrap
            by = {}
            for l in b:
                by.setdefault(l["mkt"], []).append(l)
            keys = list(by)
            rnd = random.Random(11)
            vals = []
            for _ in range(1500):
                tot_n = 0.0
                tot_p = 0.0
                for _ in keys:
                    for l in by[keys[rnd.randrange(len(keys))]]:
                        tot_n += l["ntl"]
                        tot_p += l["pnl"]
                if tot_n:
                    vals.append(100 * tot_p / tot_n)
            vals.sort()
            print(f"   {nm:9} n={len(b):>4} mkts={len(keys):>4} ntl=${ntl:>7,.0f} ROI={100*p/ntl:>+7.1f}% "
                  f"CI[{vals[37]:>+7.1f},{vals[1462]:>+7.1f}] ex5={roi_of(s[5:]):>+7.1f}% ex10={roi_of(s[10:]):>+7.1f}% "
                  f"hitR={100*sum(1 for l in b if l['pnl']>0)/len(b):>4.1f}% avgPx={sum(l['px']*l['ntl'] for l in b)/ntl:.3f}")

    print("\nMC.7 THROUGHPUT -- the ladder is a flow equation, not a capital one")
    for days in (30, 7):
        since2 = int((time.time() - days * 86400) * 1000)
        for bot in ("BANKROLL_200", "STANDARD"):
            rows = c.execute("""SELECT count(*) n, sum(simulatedPositionSize) ntl
                                FROM PaperTrade WHERE botId=? AND isDemo=0 AND openedAt>=?""",
                             (bot, since2)).fetchone()
            if rows["n"]:
                print(f"   {bot:13} last {days:>2}d: {rows['n']:>5} legs, "
                      f"${rows['ntl'] or 0:>8,.0f} notional = ${(rows['ntl'] or 0)/days:>7,.0f}/day")
    finished = c.execute("""SELECT sum(simulatedPositionSize) ntl, sum(realizedPnl) p
                            FROM PaperTrade WHERE isDemo=0 AND status IN ('closed','resolved')""").fetchone()
    openb = c.execute("""SELECT count(*) n, sum(simulatedPositionSize) ntl FROM PaperTrade
                         WHERE isDemo=0 AND status='open'""").fetchone()
    print(f"   open book: {openb['n']} legs, ${openb['ntl']:,.0f}")
    print("   $5,000/day at 1.11% per capital-day needs $449,000 of capital held at all times.")
    print("   With 76-day holds that is ~$5,900/day of NEW notional sustained. Compare the line above.")


if __name__ == "__main__":
    main()
