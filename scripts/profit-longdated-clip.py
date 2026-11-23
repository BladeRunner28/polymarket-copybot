#!/usr/bin/env python3
"""
RESIDUAL CHEAP LONG-DATED CLIP — re-measurement of the card's own cell, and what a cap buys.

WHY THIS EXISTS
---------------
Card `profit-residual-cheap-longdated-clip` proposes capping C-200 at $40 where a 24h TTR floor
cannot reach: px<0.20 AND ttr>=168h. The card's basis was scripts/profit-clip-tier.py S4, and S4's
row is cut on CLIP x TENOR only — it does not apply the price filter the card's title names. Read
naively, the card quotes a 13-leg / mean-price-0.16 row as if it were the px<0.20 cell.

This instrument does four things the card could not:

  S1  states the cell the card NAMES (px<0.20) beside the row it QUOTED (all prices), so the
      13-vs-12 and 0.16-vs-0.107 discrepancies are visible rather than inherited;
  S2  opens the cell leg by leg — funding path, resolved vs early exit, and mark-to-today beside
      realised, which is how you tell a forecast failure from an exit artefact;
  S3  prices the ARM LADDER (cap $40 / $25 / $20 / full skip) with a market-clustered CI on the
      DELTA, not on the ROI, because the delta is the quantity a cap actually buys;
  S4  tests whether the tenor boundary is structural: staleExitHardHours is 168h, so a leg whose
      ttr exceeds it CANNOT resolve inside the hold by construction — the boundary is the exit's
      own horizon, and the cohort behind it is priced as a mark trade.

BASIS (same as profit-clip-tier.py, stated once)
------------------------------------------------
population : PaperTrade isDemo=0, settled (closed|resolved), DecisionJournal.ruleSetVersion >= 68,
             deduped to the first leg per bot|wallet|market|outcome.
cost       : simulatedPositionSize = DOLLARS AT RISK. ROI = PnL / notional.
price      : the booked entry (break-even hit rate of a YES leg is its own price).
tenor      : MarketSnapshot.timeToResolution at dispatch (hours) via profit-tenor.ttr_for.
CIs        : market-clustered bootstrap (resample marketId), 2000 draws.
READ-ONLY  : DB mode=ro. No RuleSet read or write, no prisma write, no apply-v*.

RUN
  python3 scripts/profit-longdated-clip.py
  python3 scripts/profit-longdated-clip.py --selftest
"""
import argparse
import importlib.util
import os
import random
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.environ.get("COPYBOT_DB") or os.path.join(ROOT, "prisma", "dev.db")
if DB.startswith("file:") and "mode=ro" not in DB:
    DB = DB + "?mode=ro"

FAIL = []


def _mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


pct = _mod("pct", os.path.join(HERE, "profit-clip-tier.py"))

MIN_RULE = 68
CAPS = (40.0, 25.0, 20.0)


def chk(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAIL.append(label)
    return ok


def con():
    return sqlite3.connect(DB, uri=DB.startswith("file:"))


def rules(keys):
    c = con()
    c.row_factory = sqlite3.Row
    row = c.execute("select rulesJson from RuleSet where active=1").fetchone()
    import json
    js = json.loads(row["rulesJson"])
    return {k: js.get(k) for k in keys}


def rescale(l, cap):
    """PnL the same leg would have booked at min(size, cap). Linear by construction."""
    return l["pnl"] * (min(l["ntl"], cap) / l["ntl"])


def delta_ci(ls, fn, n=2000, seed=7):
    """Market-clustered bootstrap of sum(fn(l) - pnl). fn returns the arm's PnL for a leg."""
    by = {}
    for l in ls:
        by.setdefault(l["market"], []).append(l)
    ks = list(by)
    if len(ks) < 3:
        return (None, None)
    rnd = random.Random(seed)
    out = []
    for _ in range(n):
        s = 0.0
        for _ in range(len(ks)):
            for l in by[ks[rnd.randrange(len(ks))]]:
                s += fn(l) - l["pnl"]
        out.append(s)
    out.sort()
    return (out[int(0.025 * len(out))], out[int(0.975 * len(out)) - 1])


def arm(ls, fn):
    d = sum(fn(l) - l["pnl"] for l in ls)
    lo, hi = delta_ci(ls, fn)
    return d, lo, hi


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    legs = pct.load(MIN_RULE)
    days = pct.span_days(legs)
    c200 = [l for l in legs if l["bot"] == "BANKROLL_200"]
    big = [l for l in c200 if l["ntl"] >= 40.0]
    cfgr = rules(("staleExitHours", "staleExitAdverseMove", "staleExitHardHours",
                  "minTimeToResolutionHours", "kellyMaxSizeUsd", "longshotMaxPrice"))
    hard_h = cfgr["staleExitHardHours"]

    print(f"\nRESIDUAL CHEAP LONG-DATED CLIP — v{MIN_RULE}+, settled, deduped")
    print(f"  {len(legs)} legs / {len(set(l['market'] for l in legs))} markets / "
          f"{len(set(l['wallet'] for l in legs))} wallets / {days:.1f} days")
    print(f"  live exit knobs: staleExitHours={cfgr['staleExitHours']} "
          f"adverse={cfgr['staleExitAdverseMove']} hardHours={cfgr['staleExitHardHours']}")
    print(f"  live floor:      minTimeToResolutionHours={cfgr['minTimeToResolutionHours']} "
          f"(the 2->24h flip is NOT applied)")
    print(f"  live C-200 caps: kellyMaxSizeUsd={cfgr['kellyMaxSizeUsd']}, "
          f"BOT_LIMITS.BANKROLL_200.max=20.00\n")

    # ------------------------------------------------------------------ S1
    print("S1  THE CELL THE CARD NAMES vs THE ROW THE CARD QUOTED")
    tier = [l for l in big if l["ttr"] is not None and l["ttr"] >= 168]          # clip x tenor
    cell = [l for l in tier if l["px"] < 0.20]                                   # + the price filter
    pct.line("QUOTED: >=$40, 7d+", pct.cell(tier, days))
    pct.line("NAMED:  >=$40, 7d+, px<.2", pct.cell(cell, days))
    outside = [l for l in tier if l["px"] >= 0.20]
    pct.line("  outside the price filt", pct.cell(outside, days) if outside else None)
    print(f"  the quoted row carries {len(tier)} legs; {len(outside)} of them are NOT px<0.20 "
          f"and contribute {sum(l['pnl'] for l in outside):+,.2f} — they explain the "
          f"mean-price gap: {(sum(l['px'] for l in cell)+sum(l['px'] for l in outside))/max(len(tier),1):.3f} "
          f"vs {sum(l['px'] for l in cell)/max(len(cell),1):.3f}")
    print(f"  the cell's ttr range is {min(l['ttr'] for l in cell):.0f}h.."
          f"{max(l['ttr'] for l in cell):.0f}h — a floor at 24h cannot reach any of it")
    print()

    # ------------------------------------------------------------------ S2
    print("S2  THE CELL LEG BY LEG — funding path, exit type, mark-to-today")
    c = con()
    c.row_factory = sqlite3.Row
    print(f"  {'opened':<10} {'size':>5} {'px':>6} {'pnl':>8} {'now':>6} {'kind':<9} "
          f"{'funded':<7} {'ttr_h':>6}  market")
    import datetime as dt
    money = []
    nzero = nunf = nunf_all = nunf_loss = nkelly = 0
    mtm = 0.0
    for l in sorted(cell, key=lambda x: x["ms"]):
        r = c.execute("select currentPrice, resolvedAt, fillStatus from PaperTrade where id=?",
                      (l["id"],)).fetchone()
        kelly = l["ntl"] > 20.0  # only the Kelly path can exceed BOT_LIMITS.BANKROLL_200.max
        nkelly += 1 if kelly else 0
        stamp = (r["fillStatus"] or "") == "unfilled"
        nunf_all += 1 if stamp else 0
        if abs(l["pnl"]) < 1e-9:
            nzero += 1
            if stamp:
                nunf += 1
        else:
            money.append(l)
            nunf_loss += 1 if stamp else 0
            mtm += l["pnl"] if r["resolvedAt"] else ((r["currentPrice"] / l["px"] - 1.0) * l["ntl"]
                                                     if r["currentPrice"] else l["pnl"])
        print(f"  {dt.datetime.utcfromtimestamp(l['ms']/1000):%Y-%m-%d} {l['ntl']:>5.0f} "
              f"{l['px']:>6.3f} {l['pnl']:>+8.2f} "
              f"{(r['currentPrice'] if r['currentPrice'] is not None else -1):>6.3f} "
              f"{('resolved' if r['resolvedAt'] else 'early-exit'):<9} "
              f"{('KELLY' if kelly else 'legacy'):<7} {l['ttr']:>6.0f}  {l['market'][:40]}")
    realized = sum(l["pnl"] for l in cell)
    print(f"\n  {len(cell)} legs: {len(money)} carried risk, {nzero} booked exactly $0 "
          f"({nunf} of them fillStatus=unfilled)")
    print(f"  fillStatus='unfilled' is on {nunf_all}/{len(cell)} legs and is NOT a no-risk marker: "
          f"{nunf_loss} stamped legs booked real losses, so risk follows the $0.00 PnL, not the stamp "
          f"(the repo records that stamp at 29.3% false-negative)")
    marks = [l["pnl"] / l["ntl"] for l in money
             if l["pnl"] < 0 and abs(l["pnl"] + l["ntl"]) > 1e-9]
    if marks:
        print(f"  the {len(marks)} marked-down losers each lose {abs(max(marks))*100:.1f}%.."
              f"{abs(min(marks))*100:.1f}% of stake")
    print(f"  funded above the legacy ceiling: {nkelly}/{len(cell)} legs (only the Kelly path can)")
    worst = min(cell, key=lambda x: x["pnl"])
    wres = c.execute("select resolvedAt from PaperTrade where id=?", (worst["id"],)).fetchone()[0]
    print(f"  worst leg carries {worst['pnl']/realized*100:.1f}% of the loss "
          f"and it is {'RESOLVED' if wres else 'an early exit'}")
    print(f"  realised {realized:+,.2f}  vs  mark-to-today on the same legs {mtm:+,.2f}  "
          f"(delta {mtm-realized:+,.2f} = what holding would have changed SO FAR)")
    import math
    p_all = math.prod(1.0 - l["px"] for l in cell)
    p_mon = math.prod(1.0 - l["px"] for l in money)
    print(f"  NULL MODEL (fair pricing at each leg's own booked price): P(all {len(cell)} lose) = "
          f"{p_all:.3f};  P(all {len(money)} money legs lose) = {p_mon:.3f}")
    print(f"  (the card quoted 10.4% = 0.84^13, a price-blind mean of 0.16 that includes the "
          f"${100} px-0.81 leg — the scoped cell's null is 2.5x weaker)")
    print()

    # ------------------------------------------------------------------ S3
    print("S3  ARM LADDER — market-clustered CI on the DELTA (the thing a cap buys)")
    arms = [("cap $40 (THE CARD)", lambda l: rescale(l, 40.0), 40.0),
            ("cap $25", lambda l: rescale(l, 25.0), 25.0),
            ("cap $20 (legacy ceiling)", lambda l: rescale(l, 20.0), 20.0),
            ("skip the cell", lambda l: 0.0, 0.0)]
    for nm, fn, cap in arms:
        d, lo, hi = arm(cell, fn)
        binds = [l for l in cell if l["ntl"] > cap]
        print(f"  {nm:<26} binds {len(binds):>2}/{len(cell)} "
              f"({sum(1 for l in binds if abs(l['pnl']) > 1e-9)} carried risk)  "
              f"delta {d:+9,.2f}  CI [{lo:+9,.2f},{hi:+9,.2f}]  = {d/days:+5.2f}/day")
    print(f"  the cell is {'ALL' if all(l['ntl'] >= 40 for l in cell) else 'not all'} >=$40: a $40 cap here is a "
          f"cell-wide cap, not a tier cut")
    print()

    # ------------------------------------------------------------------ S4
    print("S4  IS THE TENOR BOUNDARY STRUCTURAL?  (ttr vs staleExitHardHours = "
          f"{cfgr['staleExitHardHours']}h)")
    for nm, ls in (("ttr <  hard exit", [l for l in c200 if l["ttr"] is not None and l["ttr"] < hard_h]),
                   ("ttr >= hard exit", [l for l in c200 if l["ttr"] is not None and l["ttr"] >= hard_h])):
        pct.line(nm, pct.cell(ls, days))
        ids = [l["id"] for l in ls]
        q = ",".join("?" * len(ids))
        nres = c.execute(f"select count(*) from PaperTrade where id in ({q}) and resolvedAt is not null",
                         ids).fetchone()[0]
        print(f"      reached resolution: {nres}/{len(ls)} = {nres/len(ls)*100:.1f}%")
    print()
    print("  the same cut inside the cheap band, both sides of the boundary:")
    for nm, ls in (("px<.20 ttr<h", [l for l in c200 if l["px"] < 0.20 and l["ttr"] is not None and l["ttr"] < hard_h]),
                   ("px<.20 ttr>=h", [l for l in c200 if l["px"] < 0.20 and l["ttr"] is not None and l["ttr"] >= hard_h])):
        pct.line(nm, pct.cell(ls, days))
    print()
    print("  ttr>=hard exit, by price band (is the loss only the cheap tail?):")
    longd = [l for l in c200 if l["ttr"] is not None and l["ttr"] >= hard_h]
    for lo_, hi_, nm in ((0.0, 0.20, "px<0.20"), (0.20, 0.40, "px 0.20-0.40"),
                         (0.40, 0.60, "px 0.40-0.60"), (0.60, 1.01, "px>=0.60")):
        pct.line(nm, pct.cell([l for l in longd if lo_ <= l["px"] < hi_], days)
                 if [l for l in longd if lo_ <= l["px"] < hi_] else None)
    print()

    # ------------------------------------------------------------------ S5
    print("S5  TENOR BOUNDARY SENSITIVITY (how much of the answer is the cut, not the class)")
    for X in (24, 72, hard_h, 336, 720, 2000):
        ls = [l for l in c200 if l["px"] < 0.20 and l["ttr"] is not None and l["ttr"] >= X]
        if not ls:
            continue
        cc = pct.cell(ls, days)
        print(f"  ttr>={X:>4}h  n={cc['n']:>3}  ${cc['cost']:>6,.0f}  {cc['pnl']:>+9,.2f}  "
              f"{cc['roi']:+6.1f}%  px {cc['avg_px']:.3f}   "
              f"a skip of this cut is worth {-cc['pnl']/days:+6.2f}/day")
    post = [l for l in c200 if l["px"] < 0.20 and l["ttr"] is not None and l["ttr"] >= 24]
    pbig = [l for l in post if l["ntl"] >= 40.0]
    psmall = [l for l in post if l["ntl"] < 40.0]
    if post:
        tail = (f"the remaining {len(psmall)} are ${psmall[0]['ntl']:.0f} clips booking "
                f"{sum(l['pnl'] for l in psmall):+,.2f}" if psmall else "no leg sits below $40")
        print(f"\n  post-floor population (px<.20, ttr>=24h): {len(post)} legs / "
              f"${sum(l['ntl'] for l in post):,.0f} / {sum(l['pnl'] for l in post):+,.2f}. "
              f"A cap at/below $40 binds the {len(pbig)} legs >=$40 "
              f"(${sum(l['ntl'] for l in pbig):,.0f}, {sum(l['pnl'] for l in pbig):+,.2f}); {tail}")
    print()

    # ------------------------------------------------------------------ S6
    print("S6  WHAT THE PENDING λ̂ REFIT CAN AND CANNOT DO TO THIS CLIP")
    print("  Kelly size = kellyFraction * (q - p)/(1 - p) * available, q = Φ(Φ⁻¹(p) - λ̂),")
    print("  clamped at kellyMaxSizeUsd. If the cap binds at every candidate λ̂, the refit is")
    print("  worth $0 on the clip and only this cap moves it.")
    try:
        from statistics import NormalDist
        nd = NormalDist()
    except Exception:
        print("  (statistics.NormalDist unavailable — skipped)")
        return report()
    avail = c.execute("select cashBalance from BotBankroll where botId='BANKROLL_200'").fetchone()[0]
    kfrac, kmax = 0.5, float(cfgr["kellyMaxSizeUsd"])
    for p in (0.107, 0.135):
        row = []
        for lam in (-0.680, -0.5308, -0.30, -0.28, -0.20, -0.112):
            q = nd.cdf(nd.inv_cdf(p) - lam)
            f = kfrac * (q - p) / (1 - p)
            size = min(kmax, max(0.0, f * (avail or 0)))
            row.append(f"λ̂{lam:+.3f}: q={q*100:4.1f}% size=${size:6.2f}")
        print(f"  p={p:.3f} avail=${avail:,.0f}")
        for s in row:
            print(f"    {s}")
    print()

    return report(legs, cell, tier, longd,
                  [l for l in c200 if l["ttr"] is not None and l["ttr"] < hard_h], days)


def report(legs=None, cell=None, tier=None, longd=None, shortd=None, days=1.0):
    print("S7  SELF-CHECKS")
    if cell is None:
        return 1 if FAIL else 0
    chk("dedupe: keys unique",
        len(legs) == len(set((l["bot"], l["wallet"], l["market"], l["outcome"]) for l in legs)))
    chk("the quoted row and the named cell carry the same PnL (the 13th leg is flat)",
        abs(sum(l["pnl"] for l in tier) - sum(l["pnl"] for l in cell)) < 1e-9,
        f"{sum(l['pnl'] for l in tier):+.2f} vs {sum(l['pnl'] for l in cell):+.2f}")
    chk("the two tenor halves partition C-200's dollars",
        abs(sum(l["ntl"] for l in longd) + sum(l["ntl"] for l in shortd)
            - sum(l["ntl"] for l in legs if l["bot"] == "BANKROLL_200")) < 1e-6)
    chk("every cell leg is >= $40 (so a $40 cap is cell-wide)",
        all(l["ntl"] >= 40.0 for l in cell))
    chk("arm ladder is monotone in the cap (lower cap saves more)",
        arm(cell, lambda l: rescale(l, 20.0))[0] >= arm(cell, lambda l: rescale(l, 25.0))[0]
        >= arm(cell, lambda l: rescale(l, 40.0))[0] >= 0.0)
    chk("a cap never changes the PnL of an unfilled/flat leg",
        all(rescale(l, 20.0) == l["pnl"] for l in cell if abs(l["pnl"]) < 1e-9))
    print(f"  {'ALL CHECKS PASS' if not FAIL else 'FAILED: ' + ', '.join(FAIL)}")
    return 1 if FAIL else 0


def selftest():
    print("\nSELF-TEST")
    l = dict(ntl=100.0, pnl=-20.0, market="m")
    chk("cap $40 rescales a $100 leg to 40%", abs(rescale(l, 40.0) - (-8.0)) < 1e-9)
    chk("a $20 leg under a $40 cap is untouched", abs(rescale(dict(ntl=20.0, pnl=-4.0), 40.0) - (-4.0)) < 1e-9)
    chk("cap $0 would remove the loss", abs(rescale(l, 0.0) - 0.0) < 1e-9)
    ls = [dict(ntl=100.0, pnl=-20.0, market="a"), dict(ntl=50.0, pnl=-10.0, market="b"),
          dict(ntl=100.0, pnl=+5.0, market="c")]
    d, lo, hi = arm(ls, lambda x: rescale(x, 40.0))
    chk("arm ladder sums per-leg rescales", abs(d - (12.0 + 2.0 - 3.0)) < 1e-9, f"{d:.2f}")
    d2, _, _ = arm(ls, lambda x: 0.0)
    chk("skip delta equals -sum(pnl)", abs(d2 - 25.0) < 1e-9, f"{d2:.2f}")
    chk("cap ordering monotone (20 >= 25 >= 40 >= 0 in dollars saved)",
        arm(ls, lambda x: rescale(x, 20.0))[0] >= arm(ls, lambda x: rescale(x, 25.0))[0]
        >= arm(ls, lambda x: rescale(x, 40.0))[0] >= 0)
    chk("CI brackets the point estimate", lo is not None and lo <= d <= hi, f"[{lo:.2f},{hi:.2f}]")
    print(f"  {'ALL CHECKS PASS' if not FAIL else 'FAILED: ' + ', '.join(FAIL)}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
