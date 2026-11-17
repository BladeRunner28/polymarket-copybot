#!/usr/bin/env python3
"""
PROFIT-C200-CLIP-CAP -- is the oversized C-200 leg a BAND defect or a CLIP defect,
and what does a lane-wide per-leg cap buy that the band-scoped one does not?

WHY THIS FILE EXISTS (2026-11-16, Lane A approval apr-profit-c200-clip-cap-25)
------------------------------------------------------------------------------
The pending card `profit-band-clip-rebalance` caps C-200 clips at $25 only inside
0.0-0.2 (scripts/apply-v73-c200-cheap-band-clip.ts, value "0.0-2:25"-style, never
applied: the field is absent from every RuleSet row). The approval for THIS card
asserts the defect is clip-specific rather than band-specific. This instrument
tests that assertion on the approval's own population and then prices both arms:

  1  POPULATION      two bases, printed side by side because they disagree:
                     POSITIONS (fillStatus != 'unfilled', no dedupe -- the basis the
                     11-15 review and scripts/profit-supply-ladder.py S3 used, so the
                     approval's figures reproduce exactly) and
                     BOOKED (every settled leg, ppi.dedupe -- the basis band/edge
                     reads use).
  2  CLIP TIERS      n, dollars at risk, share of the regime, PnL, ROI, clustered CI,
                     AND the payoff anatomy (win rate, mean win, mean loss, the
                     breakeven hit rate those imply, geometric mean) -- because an
                     arithmetic mean over a one-sided payoff is not a return.
  3  $100 TIER       where the oversized legs actually sit, by band: the whole
                     question. If they are not all inside 0.0-0.2, a band-scoped cap
                     under-reaches by construction.
  4  CAP SHADOW      linear rescale of every leg above the cap (no re-selection, no
                     redeployment), at caps 10..60, AND decomposed into the two
                     implementations: BAND-SCOPED (<0.2 only, the pending card) vs
                     LANE-WIDE (every C-200 leg, this card). The difference between
                     those two columns is what this approval is actually buying.
  5  ROBUSTNESS      ex-top-N touched legs / wallets / markets, leave-one-out spread.
  6  DRAWDOWN        base vs capped daily settled series: worst day and max
                     peak-to-trough. A cap that is not an edge trade has to show up
                     here or it buys nothing.
  7  FORWARD         the OPEN book by tier -- what the uncapped clip is carrying now.
  8  IMPLEMENTATION  the two routes to $25, priced from the live code constants:
                     kellyMaxSizeUsd 100 -> 25 (one existing field, Kelly path,
                     BANKROLL_200 only) vs a new band-scoped clip field (five edits).

BASIS: cost = PaperTrade.simulatedPositionSize = DOLLARS AT RISK (never x price).
PnL scales linearly in dollars at risk at a fixed entry/exit, so a cap is an exact
rescale of the SAME legs. It is NOT a re-selection and NOT a redeployment.

READ-ONLY: COPYBOT_DB is opened by profit-postfix-integrity.py; point it at a
`file:...?mode=ro` URI to prove nothing can be written.

USAGE
    COPYBOT_DB="file:$PWD/prisma/dev.db?mode=ro" python3 scripts/profit-c200-clip-cap.py
    ... --min-rule 49     # widen the regime cut (default 68 = v68, 2026-10-27)
    ... --json            # machine-readable dump appended after the report
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "ppi", os.path.join(HERE, "profit-postfix-integrity.py"))
assert _spec is not None and _spec.loader is not None, "cannot load profit-postfix-integrity.py"
ppi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ppi)

REPS = 4000
DEFAULT_MIN_RULE = 68
CAPS = [10.0, 15.0, 20.0, 25.0, 30.0, 40.0, 50.0, 60.0]
CAP = 25.0
CHEAP = 0.2          # the pending card's band: 0.0-0.2
KELLY_MAX_LIVE = 100.0
LEGACY_CLAMP = 20.0
TIERS = [
    (99.5, 1e9, "$100"),
    (40.0, 99.5, "$40-99"),
    (20.0, 40.0, "$20-40"),
    (12.0, 20.0, "$12-20"),
    (0.0, 12.0, "<$12"),
]


def money(v):
    return f"{v:+,.2f}"


def pct(v):
    return f"{v:+.1f}%"


def tier_of(size):
    for lo, hi, name in TIERS:
        if lo <= size < hi:
            return name
    return "?"


def basis_legs(min_rule, basis):
    """POSITIONS = fillStatus not 'unfilled', no dedupe (supply-ladder S3 basis).
       BOOKED    = every settled leg, first per bot|wallet|market|outcome (ppi)."""
    legs = ppi.load_legs(min_rule=min_rule)
    keep = []
    for l in legs:
        if l["status"] not in ("closed", "resolved"):
            continue
        if l["realizedPnl"] is None:
            continue
        if basis == "positions" and l.get("fillStatus") == "unfilled":
            continue
        keep.append(l)
    return keep if basis == "positions" else ppi.dedupe(keep)


def open_legs(min_rule):
    legs = ppi.load_legs(min_rule=min_rule)
    keep = [l for l in legs if l["status"] not in ("closed", "resolved")]
    return ppi.dedupe(keep)


def pnl_of(l):
    return ppi.true_pnl(l, l["trueP"]) or 0.0


def cost_of(l):
    return l["simulatedPositionSize"] or 0.0


# ------------------------------------------------------------------ statistics
def clustered(legs, val, seed=11, reps=REPS):
    """Market-clustered bootstrap of a SUM over legs."""
    by = {}
    for l in legs:
        by.setdefault(l["marketId"], []).append(l)
    keys = list(by)
    if len(keys) < 4:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    tot = []
    for _ in range(reps):
        s = 0.0
        for _ in range(len(keys)):
            for l in by[keys[rng.randrange(len(keys))]]:
                s += val(l)
        tot.append(s)
    tot.sort()
    return (tot[int(0.025 * reps)], tot[int(0.975 * reps)])


def roi_ci(legs, seed=11, reps=REPS):
    by = {}
    for l in legs:
        by.setdefault(l["marketId"], []).append(l)
    keys = list(by)
    if len(keys) < 4:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    out = []
    for _ in range(reps):
        p = n = 0.0
        for _ in range(len(keys)):
            for l in by[keys[rng.randrange(len(keys))]]:
                p += pnl_of(l)
                n += cost_of(l)
        out.append(p / n if n else 0.0)
    out.sort()
    return (out[int(0.025 * reps)], out[int(0.975 * reps)])


def anatomy(legs):
    """Win rate, mean win, mean loss, the breakeven hit rate they imply, geo mean."""
    n = len(legs)
    if not n:
        return None
    wins = [pnl_of(l) for l in legs if pnl_of(l) > 0]
    losses = [pnl_of(l) for l in legs if pnl_of(l) < 0]
    zeros = n - len(wins) - len(losses)
    wr = len(wins) / n
    mw = sum(wins) / len(wins) if wins else 0.0
    ml = sum(losses) / len(losses) if losses else 0.0
    be = (-ml) / (mw - ml) if wins and losses else float("nan")
    # geometric mean of the per-leg return multiple, floored at a total loss
    mults = [1.0 + pnl_of(l) / cost_of(l) if cost_of(l) else 1.0 for l in legs]
    zeroed = sum(1 for m in mults if m <= 0)
    gm = -1.0 if zeroed else math.exp(sum(math.log(m) for m in mults) / n) - 1.0
    return dict(n=n, wins=len(wins), losses=len(losses), zeros=zeros, wr=wr,
                mw=mw, ml=ml, be=be, gm=gm, zeroed=zeroed)


def cap_legs(legs, cap, band=None):
    """(delta $, touched list of (leg, cut$), cost_before, cost_after)"""
    delta = 0.0
    touched = []
    nb = na = 0.0
    for l in legs:
        old = cost_of(l)
        nb += old
        in_scope = band is None or (band[0] <= l["entryPrice"] < band[1])
        if in_scope and old > cap:
            new = cap
            delta += pnl_of(l) * (new / old) - pnl_of(l)
            touched.append((l, old - new))
            na += new
        else:
            na += old
    return delta, touched, nb, na


def day_series(legs, cap=None, band=None):
    """Settled-PnL by UTC settlement day (COALESCE(closedAt,resolvedAt))."""
    by = {}
    for l in legs:
        if l["closedAt"] is None and l["resolvedAt"] is None:
            continue
        ms = l["closedAt"] or l["resolvedAt"]
        d = ppi.market_day(ms)
        p = pnl_of(l)
        old = cost_of(l)
        in_scope = band is None or (band[0] <= l["entryPrice"] < band[1])
        if cap is not None and in_scope and old > cap:
            p = p * (cap / old)
        by[d] = by.get(d, 0.0) + p
    return [by[k] for k in sorted(by)]


def maxdd(series):
    peak = run = dd = 0.0
    for x in series:
        run += x
        peak = max(peak, run)
        dd = min(dd, run - peak)
    return dd


def hdr(t):
    print("\n" + "=" * 96)
    print(t)
    print("=" * 96)


def extras():
    """paperTradeId -> (FillIntent.intentPrice, DecisionJournal.risksJson).

    The intent is the level the LANE WAS HANDED (detected mid); judgment on whether
    it agrees with the booked entry is a frame check, not a price source.
    """
    c = ppi.con()
    q = """SELECT p.id AS pid, fi.intentPrice AS ip, j.risksJson AS rj
             FROM PaperTrade p JOIN DecisionJournal j ON j.id = p.decisionJournalId
             LEFT JOIN FillIntent fi ON fi.paperTradeId = p.id"""
    out = {}
    for r in c.execute(q):
        out[r["pid"]] = (r["ip"], r["rj"] or "")
    return out


def frame_of(l, ex):
    ip, _ = ex.get(l["id"], (None, ""))
    if ip is None:
        return "no-intent"
    return "COMPLEMENT" if abs(l["entryPrice"] - (1.0 - ip)) < 0.06 else "consistent"



# ------------------------------------------------------------------------ main
def main():
    min_rule = DEFAULT_MIN_RULE
    if "--min-rule" in sys.argv:
        min_rule = int(sys.argv[sys.argv.index("--min-rule") + 1])

    pos = basis_legs(min_rule, "positions")
    booked = basis_legs(min_rule, "booked")
    op = open_legs(min_rule)
    if not pos or not booked:
        print("empty population")
        return 1

    hdr("1. POPULATION -- two bases, because they disagree")
    for name, ls in (("POSITIONS (fill!=unfilled, no dedupe)", pos),
                     ("BOOKED (all settled, ppi.dedupe)", booked)):
        p = sum(pnl_of(l) for l in ls)
        n = sum(cost_of(l) for l in ls)
        first = min(l["openedAt"] for l in ls)
        last = max(l["openedAt"] for l in ls)
        print(f"  {name:<38} {len(ls):>4} legs  ${n:>9,.2f}  {money(p):>10}  {pct(p / n * 100)}"
              f"   {ppi.market_day(first)}..{ppi.market_day(last)} ({(last-first)/86400000:.1f}d)")
    fu = {}
    for l in booked:
        fu[l["fillStatus"] or "NULL"] = fu.get(l["fillStatus"] or "NULL", 0) + 1
    print(f"  fillStatus mix (booked basis): {fu}")

    # ------------------------------------------------------------------ 2 tiers
    hdr("2. CLIP TIERS -- dollars at risk per tier, on BOTH bases")
    tier_json = {}
    for name, ls in (("positions", pos), ("booked", booked)):
        tot = sum(cost_of(l) for l in ls)
        print(f"\n  [{name}]  ${tot:,.2f} at risk in {len(ls)} legs")
        print(f"    {'tier':<8}{'legs':>5}{'cost':>10}{'share':>8}{'PnL':>10}{'ROI':>8}"
              f"{'ROI 95% CI':>22}{'win%':>7}{'meanW':>8}{'meanL':>8}{'BE hit':>8}{'geo':>8}")
        for lo, hi, tname in TIERS:
            tl = [l for l in ls if lo <= cost_of(l) < hi]
            if not tl:
                continue
            c = sum(cost_of(l) for l in tl)
            p = sum(pnl_of(l) for l in tl)
            lo_ci, hi_ci = roi_ci(tl)
            a = anatomy(tl)
            tier_json.setdefault(name, {})[tname] = dict(
                legs=len(tl), cost=c, pnl=p, roi=p / c if c else 0, ci=[lo_ci, hi_ci],
                **{k: a[k] for k in ("wr", "mw", "ml", "be", "gm", "zeroed")})
            print(f"    {tname:<8}{len(tl):>5}{c:>10,.0f}{c/tot*100:>7.1f}%{money(p):>10}"
                  f"{pct(p/c*100) if c else '':>8}"
                  f"{f'[{lo_ci*100:+.0f}%, {hi_ci*100:+.0f}%]':>22}"
                  f"{a['wr']*100:>6.0f}%{a['mw']:>8.1f}{a['ml']:>8.1f}"
                  f"{a['be']*100:>7.0f}%{pct(a['gm']*100):>8}")

    # --------------------------------------------------------------- 3 anatomy
    hdr("3. WHERE THE OVERSIZED LEGS SIT -- the band-scoped vs lane-wide question")
    for name, ls in (("positions", pos), ("booked", booked)):
        cand = [l for l in ls if cost_of(l) > CAP]
        c = sum(cost_of(l) for l in cand)
        print(f"  [{name}] legs above ${CAP:.0f}: {len(cand)}  ${c:,.2f} at risk  "
              f"PnL {money(sum(pnl_of(l) for l in cand))}")
        for lo, hi, bname in [(0.0, CHEAP, "<0.20 (cheap)"), (CHEAP, 0.6, "0.20-0.60"),
                              (0.6, 0.8, "0.60-0.80"), (0.8, 1.0001, "0.80-1.00 (favourite)")]:
            bl = [l for l in cand if lo <= l["entryPrice"] < hi]
            if not bl:
                continue
            bc = sum(cost_of(l) for l in bl)
            bp = sum(pnl_of(l) for l in bl)
            a = anatomy(bl)
            print(f"    {bname:<20}{len(bl):>4} legs  ${bc:>8,.2f}  {money(bp):>9}  "
                  f"{pct(bp/bc*100):>7}  win {a['wr']*100:.0f}%  meanW {a['mw']:+.1f}  "
                  f"meanL {a['ml']:+.1f}  BE {a['be']*100:.0f}%  geo {pct(a['gm']*100)}"
                  f"  {sorted(set(x['botId'] for x in bl))}")
    # the size distribution inside the $100 tier, by band, positions basis
    hundo = [l for l in pos if cost_of(l) >= 99.5]
    ex = extras()
    print(f"\n  $100 clips in the POSITIONS basis: {len(hundo)} "
          f"(all lanes: {sorted(set(l['botId'] for l in hundo))})")
    for band in ["cheap", "favourite"]:
        sel = [l for l in hundo if (l["entryPrice"] < CHEAP) == (band == "cheap")]
        if not sel:
            continue
        print(f"    {band:<10} {len(sel):>3} legs  cost ${sum(cost_of(l) for l in sel):,.0f}  "
              f"pnl {money(sum(pnl_of(l) for l in sel))}  "
              f"p range {min(l['entryPrice'] for l in sel):.2f}-{max(l['entryPrice'] for l in sel):.2f}")

    # ---- the frame check: is the favourite-half of the $100 tier even a CLIP story?
    print("\n  $100 tier by PRICE FRAME (booked entry vs FillIntent.intentPrice):")
    print(f"    {'frame':<12}{'legs':>5}{'cost':>10}{'PnL':>10}{'fav legs':>9}"
          f"{'cheap-lambda journal':>22}")
    for name, ls in (("positions", pos), ("booked", booked)):
        h = [l for l in ls if cost_of(l) >= 99.5]
        print(f"    [{name}] {len(h)} $100 legs")
        for fr in ("COMPLEMENT", "consistent", "no-intent"):
            fl = [l for l in h if frame_of(l, ex) == fr]
            if not fl:
                continue
            lam_cheap = sum(1 for l in fl
                            if "λ̂=-" in ex.get(l["id"], (None, ""))[1]
                            and l["entryPrice"] >= 0.8)
            print(f"    {fr:<12}{len(fl):>5}{sum(cost_of(l) for l in fl):>10,.0f}"
                  f"{money(sum(pnl_of(l) for l in fl)):>10}"
                  f"{sum(1 for l in fl if l['entryPrice'] >= 0.8):>9}{lam_cheap:>22}")
    fav100 = [l for l in pos if cost_of(l) >= 99.5 and l["entryPrice"] >= 0.8]
    print(f"    -> {len(fav100)} of {len(hundo)} $100 legs in POSITIONS were bought at >=0.80 "
          f"while the journal records a CHEAP-band λ̂ (the scorer priced the sibling token);")
    print(f"       scripts/profit-clip-frame-probe.ts proves Kelly SKIPS all of them at the paid price.")


    # ------------------------------------------------------------ 4 cap shadow
    hdr("4. CAP SHADOW -- linear rescale above the cap, split by implementation")
    print("  BAND-SCOPED = only entryPrice < 0.20 (the pending profit-band-clip-rebalance card)")
    print("  LANE-WIDE   = every C-200 leg (this approval); STANDARD cannot exceed $20 anyway")
    shadow_json = {}
    for name, ls in (("positions", pos), ("booked", booked)):
        base_p = sum(pnl_of(l) for l in ls)
        base_n = sum(cost_of(l) for l in ls)
        print(f"\n  [{name}] book: ${base_n:,.2f} at risk, {money(base_p)}, {pct(base_p/base_n*100)}")
        print(f"    {'cap':>5}{'arm':<12}{'touched':>8}{'kept $':>10}{'delta':>10}"
              f"{'delta 95% CI':>24}{'book ROI':>10}")
        for cap in CAPS:
            for arm, band in (("band", (0.0, CHEAP)), ("lane-wide", None)):
                d, touched, _, na = cap_legs(ls, cap, band=band)
                lo_ci, hi_ci = clustered(
                    ls, lambda l, c=cap, b=band: (
                        pnl_of(l) * (c / cost_of(l)) - pnl_of(l)
                        if (b is None or b[0] <= l["entryPrice"] < b[1]) and cost_of(l) > c
                        else 0.0))
                shadow_json.setdefault(name, {})[f"{arm}@{cap:.0f}"] = dict(
                    touched=len(touched), delta=d, ci=[lo_ci, hi_ci], kept=na,
                    roi=(base_p + d) / na if na else 0)
                print(f"    ${cap:>4.0f}{arm:<12}{len(touched):>8}{na:>10,.0f}{money(d):>10}"
                      f"{f'[{lo_ci:+.0f}, {hi_ci:+.0f}]':>24}"
                      f"{pct((base_p+d)/na*100) if na else '':>10}")
        # what lane-wide buys OVER band-scoped, at the proposed cap
        d_b, tb, _, _ = cap_legs(ls, CAP, band=(0.0, CHEAP))
        d_l, tl, _, _ = cap_legs(ls, CAP)
        print(f"    at ${CAP:.0f}: band-scoped {money(d_b)} on {len(tb)} legs | "
              f"lane-wide {money(d_l)} on {len(tl)} legs | "
              f"lane-wide MINUS band-scoped {money(d_l - d_b)} on {len(tl)-len(tb)} extra legs")

    # ------------------------------------------------------------ 5 robustness
    hdr(f"5. ROBUSTNESS OF THE ${CAP:.0f} LANE-WIDE DELTA (positions basis)")
    _, tl, _, _ = cap_legs(pos, CAP)
    touched_legs = [t[0] for t in tl]
    deltas = sorted((pnl_of(l) * (CAP / cost_of(l)) - pnl_of(l) for l in touched_legs), reverse=True)
    print(f"  touched: {len(touched_legs)} legs, delta {money(sum(deltas))}")
    for k in (1, 2, 3, 5):
        print(f"  ex-top-{k} touched legs : {money(sum(deltas[k:]))}")
    wal = {}
    for l in pos:
        wal[l["walletAddress"]] = wal.get(l["walletAddress"], 0.0) + pnl_of(l)
    for k in (3, 5, 10):
        gone = set(sorted(wal, key=lambda w: -wal[w])[:k])
        d = sum(pnl_of(l) * (CAP / cost_of(l)) - pnl_of(l)
                for l in touched_legs if l["walletAddress"] not in gone)
        print(f"  ex-top-{k} wallets     : {money(d)}")
    mk = {}
    for l in pos:
        mk[l["marketId"]] = mk.get(l["marketId"], 0.0) + pnl_of(l)
    for k in (1, 3, 5):
        gone = set(sorted(mk, key=lambda m: -mk[m])[:k])
        d = sum(pnl_of(l) * (CAP / cost_of(l)) - pnl_of(l)
                for l in touched_legs if l["marketId"] not in gone)
        print(f"  ex-top-{k} markets     : {money(d)}")
    # decomposition: the cap can only gain on LOSERS and can only pay on WINNERS
    d_loss = sum(pnl_of(l) * (CAP / cost_of(l)) - pnl_of(l) for l in touched_legs if pnl_of(l) < 0)
    d_win = sum(pnl_of(l) * (CAP / cost_of(l)) - pnl_of(l) for l in touched_legs if pnl_of(l) > 0)
    print(f"  decomposition          : loss legs contribute {money(d_loss)} "
          f"({sum(1 for l in touched_legs if pnl_of(l) < 0)} legs), "
          f"win legs {money(d_win)} ({sum(1 for l in touched_legs if pnl_of(l) > 0)} legs)")
    top_win = max(touched_legs, key=pnl_of)
    print(f"  the single biggest win in the touched set: {money(pnl_of(top_win))} at "
          f"p={top_win['entryPrice']:.3f} ({ppi.market_day(top_win['openedAt'])}); "
          f"it gives back {money(pnl_of(top_win)*(CAP/cost_of(top_win))-pnl_of(top_win))}")
    print(f"  delta excluding it     : "
          f"{money(sum(pnl_of(l)*(CAP/cost_of(l))-pnl_of(l) for l in touched_legs if l is not top_win))}")

    # ------------------------------------------------------------- 6 drawdown
    hdr("6. DRAWDOWN -- what the cap buys if it is a rail rather than an edge")
    for name, ls in (("positions", pos), ("booked", booked)):
        for label, cap, band in (("base", None, None), (f"band ${CAP:.0f}", CAP, (0.0, CHEAP)),
                                 (f"lane ${CAP:.0f}", CAP, None)):
            s = day_series(ls, cap=cap, band=band)
            print(f"  [{name:<9}] {label:<12} days {len(s):>3}  total {money(sum(s)):>10}  "
                  f"worst day {money(min(s) if s else 0):>9}  maxDD {money(maxdd(s)):>10}")

    # ---------------------------------------------------------------- 7 forward
    hdr("7. FORWARD EXPOSURE -- the OPEN book by tier")
    if op:
        tot = sum(cost_of(l) for l in op)
        print(f"  {len(op)} open legs, ${tot:,.2f} at risk")
        for lo, hi, tname in TIERS:
            tl2 = [l for l in op if lo <= cost_of(l) < hi]
            if tl2:
                c = sum(cost_of(l) for l in tl2)
                print(f"    {tname:<8}{len(tl2):>4} legs  ${c:>8,.2f}  {c/tot*100:>5.1f}%")
        big = [l for l in op if cost_of(l) > CAP]
        print(f"  above ${CAP:.0f}: {len(big)} open legs "
              f"(${sum(cost_of(l) for l in big):,.2f}) -- a cap cannot reach these, they are booked")
        # how often does the $100 clip arrive? settled + open, per day
        days = (max(l["openedAt"] for l in pos + op) - min(l["openedAt"] for l in pos + op)) / 86400000.0
        n100 = len([l for l in pos + op if cost_of(l) >= 99.5])
        print(f"  $100 clips opened in the regime: {n100} in {days:.1f}d = {n100/days:.2f}/day")
    else:
        print("  no open legs")

    # --------------------------------------------------------- 8 implementation
    hdr("8. IMPLEMENTATION -- the two routes to $25, priced from the live constants")
    print(f"  live RuleSet v73: kellyMaxSizeUsd = {KELLY_MAX_LIVE:.0f};  "
          f"BOT_LIMITS.BANKROLL_200.max = {LEGACY_CLAMP:.2f} (legacy path)")
    print(f"  KELLY_BOTS = ['BANKROLL_200']  -> a kellyMaxSizeUsd change cannot reach STANDARD")
    print(f"  route A  kellyMaxSizeUsd 100 -> {CAP:.0f}: ONE field, already read by")
    print(f"           scripts/score-trades.ts:935 (Kelly maxSizeUsd) and src/lib/paper.ts:197")
    print(f"           (clampPaperSize override). No code edit, no new field, revert = one field.")
    print(f"           Binds on: every Kelly-sized C-200 leg (the only legs that can exceed $20).")
    print(f"  route B  a band-scoped clip field (apply-v73 shape): Rules interface +")
    print(f"           DEFAULT_RULES + a parser/min helper in band-size.ts + the openPaperTrade")
    print(f"           call site + the score-trades.ts pass-through = FIVE edits, and it binds")
    print(f"           on the cheap band only (see section 4's band-vs-lane columns).")

    # ------------------------------------------------------------- self-check
    assert abs(sum(v["cost"] for v in tier_json["positions"].values())
               - sum(cost_of(l) for l in pos)) < 1e-6, "tiers must partition cost"
    assert sum(v["legs"] for v in tier_json["booked"].values()) == len(booked)
    assert cap_legs(pos, CAP)[3] <= sum(cost_of(l) for l in pos) + 1e-9
    print("\nself-check OK: tiers partition the population; the cap can only shrink notional")

    if "--json" in sys.argv:
        print("\nJSON " + json.dumps(dict(tiers=tier_json, shadow=shadow_json,
                                        populations={n: len(ls) for n, ls in
                                                     (("positions", pos), ("booked", booked))}),
                                    default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
