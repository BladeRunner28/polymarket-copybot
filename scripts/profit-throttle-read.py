#!/usr/bin/env python3
"""THE THROTTLE READ -- 2026-11-05 profit review instrument.

The question this answers: the book is paid on edge x capital x turnover. Where does
each of the three actually bind, and which lever moves the most dollars?

Sections
  A  population, cost basis, the one-line book metric
  B  the band map on THREE bases: booked ROI, settlement-truth edge, and $ per
     $1k-capital-day (profit per unit of capital per unit of TIME)
  C  lane x band, same capital-day basis -- and the lane share of capital-time vs PnL
  D  the clip census: what the size levers actually do, read from the LIVE RuleSet
  E  shadow sizing: what different band factors would have booked, per band
  F  break-even slippage: how far the fill can worsen before the band's edge is gone
  G  residual breadth on the cheap band (ex-top-N hit rate + time split)
  H  the dead block (0.4-0.8): realised vs settlement, and why they disagree

COST BASIS (mandatory)
  cost = PaperTrade.simulatedPositionSize = DOLLARS AT RISK. Never shares, never
  multiplied by entryPrice. Bet level = first leg per (bot|wallet|market|outcome),
  mirroring scripts/profit-band-report.py load().
  ROI line labels: [booked] = closed+resolved, what the ledger books;
                   [resolved] = status='resolved' only, where PnL>0 iff the token won,
                   so ROI = hit*(1/p-1) - (1-hit) is exact and the hit-rate test is clean.
  Capital-days = simulatedPositionSize x (exit-open) summed / 1000, exit =
  COALESCE(resolvedAt, closedAt, openedAt). This is realised, not snapshot.

READ-ONLY: file:...?mode=ro, no prisma write, no RuleSet row touched.

USAGE
  python3 scripts/profit-throttle-read.py               # regime (ruleSetVersion >= 49)
  python3 scripts/profit-throttle-read.py --all         # every rule version
  python3 scripts/profit-throttle-read.py --self-test    # assert the payload identity
"""
import json
import sqlite3
import sys
import math
import numpy as np

DB = "file:prisma/dev.db?mode=ro"
BANDS = [(0.0, 0.2, "0.00-0.20"), (0.2, 0.4, "0.20-0.40"), (0.4, 0.6, "0.40-0.60"),
         (0.6, 0.8, "0.60-0.80"), (0.8, 1.0001, "0.80-1.00")]
MIN_RULE = 0 if "--all" in sys.argv else 49
DAY = 86400000.0

# live size levers, read from the active RuleSet in section D (defaults shown here)
CLAMP = 100.0        # kellyMaxSizeUsd
LEGACY = 20.0        # CAP_LEGACY / lane per-bet ceiling


def band_of(p):
    for lo, hi, n in BANDS:
        if lo <= p < hi:
            return n
    return None


def connect():
    con = sqlite3.connect(DB, uri=True)
    con.row_factory = sqlite3.Row
    return con


def load(con):
    sql = """
        SELECT p.id, p.botId, p.walletAddress, p.marketId, p.outcome, p.entryPrice,
               p.intentPrice, p.simulatedPositionSize AS ntl, p.realizedPnl AS pnl,
               p.status, p.openedAt, p.closedAt, p.resolvedAt, p.decisionJournalId AS jid,
               j.ruleSetVersion AS rv, j.reasonsJson AS rj
        FROM PaperTrade p
        LEFT JOIN DecisionJournal j ON p.decisionJournalId = j.id
        WHERE p.isDemo = 0 AND p.status IN ('closed','resolved')
          AND p.realizedPnl IS NOT NULL AND p.openedAt >= 0
          AND COALESCE(j.ruleSetVersion, 0) >= ?
    """
    rows = [dict(r) for r in con.execute(sql, [MIN_RULE])]
    seen, bets = set(), []
    for r in sorted(rows, key=lambda r: r["openedAt"] or 0):
        k = (r["botId"], r["walletAddress"], r["marketId"], r["outcome"])
        if k in seen:
            continue
        seen.add(k)
        r["band"] = band_of(r["entryPrice"])
        lane = "main" if r["botId"] == "BANKROLL_200" else "std"
        if r["rj"] and "Short-TTR lane" in r["rj"]:
            lane = "shttr"
        r["lane"] = lane
        end = r["resolvedAt"] or r["closedAt"] or r["openedAt"]
        r["hold"] = max(0.0, (end - r["openedAt"]) / DAY)
        r["cd"] = r["ntl"] * r["hold"] / 1000.0
        bets.append(r)
    return bets


def roi(legs, field="pnl", size="ntl"):
    cost = sum(b[size] for b in legs)
    return sum(b[field] for b in legs) / cost if cost else 0.0


def cluster_ci(legs, reps=1500, seed=7):
    """Market-clustered bootstrap CI on ROI (resample markets, not legs)."""
    by = {}
    for b in legs:
        by.setdefault(b["marketId"], []).append(b)
    keys = list(by)
    if len(keys) < 3:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(reps):
        pick = rng.integers(0, len(keys), len(keys))
        sample = [b for i in pick for b in by[keys[i]]]
        out.append(roi(sample))
    return float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))


def hit_edge(legs, weighted=False):
    """Settlement truth: resolved legs only. edge = hit - mean entry price.

    weighted=True gives the DOLLAR-weighted version: a leg counts in proportion to its
    notional. The two disagree exactly when size is not proportional to edge -- that gap
    is the sizing problem, so both are printed.
    """
    res = [b for b in legs if b["status"] == "resolved"]
    if not res:
        return None
    n = len(res)
    if weighted:
        tot = sum(b["ntl"] for b in res)
        hit = sum(b["ntl"] for b in res if b["pnl"] > 0) / tot
        price = sum(b["ntl"] * b["entryPrice"] for b in res) / tot
        se = math.sqrt(max(hit * (1 - hit), 1e-12) / n)
        return dict(n=n, wins=sum(1 for b in res if b["pnl"] > 0), hit=hit, price=price,
                    edge=hit - price, z=(hit - price) / se if se else 0.0)
    wins = sum(1 for b in res if b["pnl"] > 0)
    hit = wins / n
    price = sum(b["entryPrice"] for b in res) / n
    se = math.sqrt(max(hit * (1 - hit), 1e-12) / n)
    return dict(n=n, wins=wins, hit=hit, price=price, edge=hit - price,
                z=(hit - price) / se if se else 0.0)


def hdr(t):
    print("\n" + "=" * 100)
    print(t)
    print("=" * 100)


def table(rows, cols, head):
    print("  ".join(h.format(*[str(c) for c in r]) if False else "" for h in []), end="")
    print(" | ".join(h for h in head))
    for r in rows:
        print(" | ".join(str(c) for c in r))


def main():
    con = connect()
    bets = load(con)
    if not bets:
        print("no bets")
        return 1

    span = (max(b["openedAt"] for b in bets) - min(b["openedAt"] for b in bets)) / DAY
    ntl = sum(b["ntl"] for b in bets)
    pnl = sum(b["pnl"] for b in bets)
    cd = sum(b["cd"] for b in bets)

    hdr("A. POPULATION")
    print(f"  regime            : ruleSetVersion >= {MIN_RULE}  (--all to widen)")
    print(f"  bets (deduped)    : {len(bets):,}")
    print(f"  notional at risk  : ${ntl:,.0f}   (cost basis = simulatedPositionSize, DOLLARS)")
    print(f"  booked PnL        : ${pnl:,.2f}   [booked = closed+resolved]")
    print(f"  booked ROI        : {pnl/ntl*100:+.1f}%")
    print(f"  span              : {span:.1f} days  ->  ${pnl/span:,.2f}/day")
    print(f"  capital-days      : {cd:,.1f} x $1k   ->  avg notional in flight ${cd/span*1000:,.0f}")
    print(f"  PnL per $1k-cd    : ${pnl/cd:,.1f}")

    # ---- exposure headroom, from the live bankroll row + the v46 formula --------
    br = con.execute(
        "SELECT principal, cashBalance, realizedPnl FROM BotBankroll WHERE botId='BANKROLL_200'"
    ).fetchone()
    open_b200 = con.execute(
        "SELECT COUNT(*) n, COALESCE(SUM(simulatedPositionSize),0) s FROM PaperTrade "
        "WHERE botId='BANKROLL_200' AND isDemo=0 AND status='open'"
    ).fetchone()
    base = 1000.0
    try:
        rr = json.loads(con.execute("SELECT rulesJson FROM RuleSet ORDER BY version DESC LIMIT 1").fetchone()[0])
        base = float(rr.get("maxGrossExposureUsd", base))
    except Exception:
        rr = {}
    nw = float(br["principal"] or 0) + float(br["realizedPnl"] or 0)
    cap = base + 0.5 * max(0.0, nw - float(br["principal"] or 0))
    print(f"\n  exposure headroom : cap = ${base:,.0f} + 50% x (netWorth ${nw:,.0f} - principal "
          f"${float(br['principal'] or 0):,.0f}) = ${cap:,.0f}")
    print(f"                      cash ${float(br['cashBalance'] or 0):,.0f}; "
          f"open C-200 notional ${float(open_b200['s']):,.0f} "
          f"({float(open_b200['s'])/cap*100:.1f}% of cap); "
          f"avg in flight ${cd/span*1000:,.0f} = {cd/span*1000/cap*100:.1f}% of cap")

    # ---- B. band map ------------------------------------------------------------
    hdr("B. THE BAND MAP -- edge, booked result, and profit per unit of capital-TIME")
    print(f"  {'band':<10} {'n':>5} {'notional':>10} {'booked':>10} {'ROI%':>8} "
          f"{'settled n':>9} {'hit%':>6} {'price':>6} {'edge':>7} {'z':>5} "
          f"{'hit$w':>6} {'edge$w':>7} {'cd share':>8} {'$/1k-cd':>9}")
    for lo, hi, name in BANDS:
        legs = [b for b in bets if b["band"] == name]
        if not legs:
            continue
        e = hit_edge(legs)
        w = hit_edge(legs, weighted=True)
        cdshare = sum(b["cd"] for b in legs) / cd * 100
        print(f"  {name:<10} {len(legs):>5} {sum(b['ntl'] for b in legs):>10,.0f} "
              f"{sum(b['pnl'] for b in legs):>10,.1f} {roi(legs)*100:>+8.1f} "
              f"{e['n']:>9} {e['hit']*100:>6.1f} {e['price']:>6.3f} "
              f"{e['edge']*100:>+7.1f} {e['z']:>+5.1f} "
              f"{w['hit']*100:>6.1f} {w['edge']*100:>+7.1f} {cdshare:>7.1f}% "
              f"{sum(b['pnl'] for b in legs)/sum(b['cd'] for b in legs):>9.1f}")
    print("  hit% / edge = leg-weighted truth; hit$w / edge$w = the same in DOLLARS.")
    print("  A positive leg edge above a negative $-edge means the money is on the wrong legs.")

    # ---- C. lane x band ---------------------------------------------------------
    hdr("C. LANE x BAND -- lane share of capital-TIME vs share of PnL")
    for lane in ("main", "shttr", "std"):
        legs = [b for b in bets if b["lane"] == lane]
        print(f"\n  {lane}: {len(legs)} bets, ${sum(b['ntl'] for b in legs):,.0f} notional, "
              f"${sum(b['pnl'] for b in legs):,.1f} booked, "
              f"{sum(b['cd'] for b in legs)/cd*100:.1f}% of capital-days, "
              f"${sum(b['pnl'] for b in legs)/sum(b['cd'] for b in legs):,.1f}/$1k-cd")
        for lo, hi, name in BANDS:
            sub = [b for b in legs if b["band"] == name]
            if not sub:
                continue
            print(f"    {name:<10} n={len(sub):>4} ntl=${sum(b['ntl'] for b in sub):>8,.0f} "
                  f"pnl=${sum(b['pnl'] for b in sub):>9,.1f} roi={roi(sub)*100:>+7.1f}% "
                  f"clip=${sum(b['ntl'] for b in sub)/len(sub):>6.1f} "
                  f"cd={sum(b['cd'] for b in sub)/cd*100:>5.1f}% "
                  f"$/1k-cd={sum(b['pnl'] for b in sub)/sum(b['cd'] for b in sub):>8.1f}")
    st = sum(b["pnl"] for b in bets if b["lane"] == "std")
    stcd = sum(b["cd"] for b in bets if b["lane"] == "std")
    print(f"\n  STANDARD share of capital-time {stcd/cd*100:.1f}%  vs share of PnL {st/pnl*100:.1f}%")
    print(f"  C-200 lanes share of capital-time {(cd-stcd)/cd*100:.1f}%  vs share of PnL "
          f"{(pnl-st)/pnl*100:.1f}%")

    print("\n  lane x band SETTLEMENT edge (resolved legs only, leg-weighted):")
    for lane in ("main", "shttr", "std"):
        for lo, hi, name in BANDS:
            sub = [b for b in bets if b["lane"] == lane and b["band"] == name]
            e = hit_edge(sub)
            if not e or e["n"] < 20:
                continue
            print(f"    {lane+'/'+name:<16} n={e['n']:>4} hit={e['hit']*100:>5.1f}% "
                  f"price={e['price']:.3f} edge={e['edge']*100:>+6.1f}pp z={e['z']:>+5.1f}")

    # ---- A2. live book + recent flow --------------------------------------------
    hdr("A2. THE LIVE BOOK AND THE LAST 14 DAYS OF FLOW")
    ob = con.execute(
        "SELECT botId, COUNT(*) n, COALESCE(SUM(simulatedPositionSize),0) s, "
        "COALESCE(SUM(unrealizedPnl),0) u, "
        "AVG((strftime('%s','now')*1000 - openedAt)/86400000.0) age "
        "FROM PaperTrade WHERE isDemo=0 AND status='open' GROUP BY botId"
    ).fetchall()
    for r in ob:
        print(f"  open {r['botId']:<13} {r['n']:>4} legs  ${r['s']:>8,.0f}  "
              f"MTM ${r['u']:>8,.1f}  avg age {r['age']:>5.1f}d")
    flow = con.execute(
        "SELECT p.botId, COUNT(*) n, COALESCE(SUM(p.simulatedPositionSize),0) s, "
        "SUM(CASE WHEN p.entryPrice<0.4 THEN 1 ELSE 0 END) cheap "
        "FROM PaperTrade p WHERE p.isDemo=0 AND p.openedAt > (strftime('%s','now')-14*86400)*1000 "
        "GROUP BY p.botId"
    ).fetchall()
    print("\n  opens in the last 14 days (are we still filling the dead block?):")
    for r in flow:
        print(f"  {r['botId']:<13} {r['n']:>4} legs  ${r['s']:>7,.0f}  "
              f"{r['cheap']/r['n']*100:>5.1f}% at entry < 0.40")
    dead = con.execute(
        "SELECT COUNT(*) n FROM PaperTrade WHERE isDemo=0 AND botId='STANDARD' "
        "AND entryPrice>=0.40 AND entryPrice<0.60 "
        "AND openedAt > (strftime('%s','now')-7*86400)*1000"
    ).fetchone()
    print(f"  STANDARD opens in 0.40-0.60 in the last 7 days: {dead['n']}")
    daily = con.execute(
        "SELECT date(COALESCE(resolvedAt,closedAt)/1000,'unixepoch') d, "
        "SUM(realizedPnl) p FROM PaperTrade WHERE isDemo=0 "
        "AND status IN ('closed','resolved') AND realizedPnl IS NOT NULL "
        "AND COALESCE(resolvedAt,closedAt) > (strftime('%s','now')-7*86400)*1000 GROUP BY 1 ORDER BY 1"
    ).fetchall()
    if daily:
        vals = [float(r["p"]) for r in daily]
        top2 = sum(sorted(vals)[-2:])
        print(f"\n  settled PnL by day, last 7: {len(vals)} days, total ${sum(vals):,.0f}, "
              f"${sum(vals)/len(vals):,.0f}/day; the two biggest days carry ${top2:,.0f} "
              f"({top2/sum(vals)*100:.0f}% of it)")
        for r in daily:
            print(f"    {r['d']}  ${float(r['p']):>8,.1f}")

    # ---- D. clip census ---------------------------------------------------------
    hdr("D. THE CLIP CENSUS -- what the size levers are set to, and who they bind")
    if rr:
        for k in ("c200LongshotBandFactor", "c200DeadZoneBandFactor",
                  "shortTtrDeadZoneBandFactor", "shortTtrPremiumBandFactor",
                  "kellyMaxSizeUsd", "maxGrossExposureUsd"):
            if k in rr:
                print(f"  live rule {k:<32} = {rr[k]}")
    print(f"\n  {'lane/band':<16} {'n':>5} {'avg clip':>9} {'at $100':>8} {'at $20':>7} {'median':>7} {'max':>7}")
    for lane in ("main", "shttr", "std"):
        for lo, hi, name in BANDS:
            sub = [b for b in bets if b["lane"] == lane and b["band"] == name]
            if len(sub) < 5:
                continue
            sizes = [b["ntl"] for b in sub]
            at100 = sum(1 for s in sizes if s >= 99.5) / len(sizes) * 100
            at20 = sum(1 for s in sizes if 19.5 <= s < 20.5) / len(sizes) * 100
            print(f"  {lane+'/'+name:<16} {len(sub):>5} {sum(sizes)/len(sizes):>9.1f} "
                  f"{at100:>7.1f}% {at20:>6.1f}% {sorted(sizes)[len(sizes)//2]:>7.1f} {max(sizes):>7.1f}")

    # does the clamp carry information? within the main lane's cheap band, clamped vs not.
    # NB the clamp is the SIZER's output, so this is "is the sizer ranking anything", not
    # "is big size lucky" -- and it is confounded with price (clamped legs skew cheaper).
    print("\n  clamp information (main lane, 0.05-0.20, booked basis):")
    mc = [b for b in bets if b["lane"] == "main" and 0.05 <= b["entryPrice"] < 0.20]
    hi_ = [b for b in mc if b["ntl"] >= 99.5]
    lo_ = [b for b in mc if b["ntl"] < 99.5]
    for lbl, g in (("at the $100 clamp", hi_), ("below the clamp", lo_)):
        if not g:
            continue
        print(f"    {lbl:<20} n={len(g):>3} ntl=${sum(b['ntl'] for b in g):>6,.0f} "
              f"pnl=${sum(b['pnl'] for b in g):>8,.1f} ROI={roi(g)*100:>+7.1f}% "
              f"avg clip ${sum(b['ntl'] for b in g)/len(g):>6.1f} "
              f"avg p {sum(b['entryPrice'] for b in g)/len(g):.3f}")

    # ---- E. shadow sizing -------------------------------------------------------
    hdr("E. SHADOW SIZING -- per band, what a different SIZE would have booked")
    print("  PER-LEG: new_size = min(clamp_then, old_size x mult); delta = pnl x (new/old - 1).")
    print("  A band factor alone is a NO-OP on legs already pinned at the clamp -- so the")
    print("  'linear' row below is the naive number and the clamp-aware rows are the real ones.")
    print("\n  naive (band factor only, as if the clamp did not exist):")
    for mult in (1.5, 2.0):
        tot = sum(sum(b["pnl"] for b in bets if b["band"] == n) * (mult - 1) for _, _, n in BANDS)
        print(f"    every band x{mult:<4} -> ${tot:+,.0f} over {span:.0f}d (${tot/span:+.1f}/day)")
    print("\n  clamp-aware, per band (clamp raised to CLAMP x mult):")
    for mult in (1.5, 2.0):
        print(f"    x{mult} with clamp ${CLAMP:,.0f} -> ${CLAMP*mult:,.0f}:")
        tot = 0.0
        for lo, hi, name in BANDS:
            legs = [b for b in bets if b["band"] == name]
            if not legs:
                continue
            d = 0.0
            for b in legs:
                new = min(CLAMP * mult, b["ntl"] * mult)
                d += b["pnl"] * (new / b["ntl"] - 1)
            tot += d
            print(f"      {name:<10} ${d:>+9,.0f}")
        print(f"      TOTAL      ${tot:>+9,.0f}  (${tot/span:+.1f}/day)")
    print("\n  clamp-aware, same multiplier with the clamp HELD at ${:,.0f} ".format(CLAMP) +
          "(what a band-factor-only change buys):")
    for mult in (1.5, 2.0):
        tot = 0.0
        per = []
        for lo, hi, name in BANDS:
            legs = [b for b in bets if b["band"] == name]
            d = sum(b["pnl"] * (min(CLAMP, b["ntl"] * mult) / b["ntl"] - 1) for b in legs)
            tot += d
            per.append(f"{name}:{d:+.0f}")
        print(f"    x{mult} -> ${tot:+,.0f} (${tot/span:+.1f}/day)   " + "  ".join(per))
    print("\n  the legacy $20 lane ceiling (binds the short-TTR and STANDARD lanes), split by lane:")
    for lane in ("shttr", "std"):
        for mult, cap in ((1.5, LEGACY * 1.5), (2.0, LEGACY * 2)):
            tot = 0.0
            for lo, hi, name in BANDS:
                legs = [b for b in bets if b["band"] == name and b["lane"] == lane]
                tot += sum(b["pnl"] * (min(cap, b["ntl"] * mult) / b["ntl"] - 1) for b in legs)
            print(f"    {lane:<6} ceiling ${LEGACY:,.0f} -> ${cap:,.0f} (x{mult})  "
                  f"-> ${tot:+,.0f} (${tot/span:+.1f}/day)")


    # ---- F. break-even slippage -------------------------------------------------
    hdr("F. BREAK-EVEN SLIPPAGE -- how far the fill can worsen before the edge is gone")
    print("  Settlement truth. A YES bought at p needs hit > p to break even, so the band")
    print("  can absorb a fill up to its own HIT RATE before its edge is zero.")
    print(f"  {'band':<10} {'hit%':>6} {'price':>6} {'edge pp':>8} {'cushion (c)':>12} {'cushion %':>10} "
          f"{'realised fill credit (c)':>24}")
    for lo, hi, name in BANDS:
        legs = [b for b in bets if b["band"] == name]
        e = hit_edge(legs)
        withint = [b for b in legs if b["intentPrice"]]
        credit = (sum(b["intentPrice"] - b["entryPrice"] for b in withint) / len(withint)
                  if withint else 0.0)
        print(f"  {name:<10} {e['hit']*100:>6.1f} {e['price']:>6.3f} {e['edge']*100:>+8.1f} "
              f"{e['edge']*100:>11.1f}c {e['edge']/e['price']*100:>+9.0f}% {credit*100:>+23.2f}c")
    print("  (cushion = hit - price in PRICE POINTS = the extra cents per $1 share we could pay")
    print("   on average and still break even. realised fill credit = intentPrice - entryPrice,")
    print("   positive = we filled BELOW intent.)")

    # ---- G. residual breadth ----------------------------------------------------
    hdr("G. IS THE CHEAP-BAND EDGE BROAD? ex-top-N hit-rate test + time split")
    cheap = [b for b in bets if b["entryPrice"] < 0.20]
    cheap = sorted(cheap, key=lambda b: -b["pnl"])
    for k in (0, 1, 5, 10, 20):
        by_mkt = {}
        for b in cheap:
            by_mkt[b["marketId"]] = by_mkt.get(b["marketId"], 0) + b["pnl"]
        drop = set(sorted(by_mkt, key=lambda m: -by_mkt[m])[:k])
        keep = [b for b in cheap if b["marketId"] not in drop]
        e = hit_edge(keep)
        print(f"  ex-top-{k:<3} markets: n={e['n']:>4} wins={e['wins']:>3} hit={e['hit']*100:>5.1f}% "
              f"breakeven={e['price']*100:>5.1f}% edge={e['edge']*100:>+6.1f}pp z={e['z']:>+5.1f}")
    print("\n  time split (by openedAt, settled legs only, 50/50):")
    res = sorted([b for b in cheap if b["status"] == "resolved"], key=lambda b: b["openedAt"])
    for lbl, part in (("early half", res[: len(res) // 2]), ("late half", res[len(res) // 2:])):
        e = hit_edge(part)
        print(f"    {lbl:<11} n={e['n']:>4} hit={e['hit']*100:>5.1f}% breakeven={e['price']*100:>5.1f}% "
              f"edge={e['edge']*100:>+6.1f}pp z={e['z']:>+5.1f}")

    # ---- H. the dead block ------------------------------------------------------
    hdr("H. THE DEAD BLOCK 0.40-0.80 -- realised vs settlement, and the disagreement")
    for lo, hi, name in BANDS[2:4]:
        legs = [b for b in bets if b["band"] == name]
        res = [b for b in legs if b["status"] == "resolved"]
        clo = [b for b in legs if b["status"] == "closed"]
        e = hit_edge(legs)
        print(f"  {name}: n={len(legs)} booked=${sum(b['pnl'] for b in legs):,.1f} "
              f"[booked ROI {roi(legs)*100:+.1f}%]  resolved n={len(res)} "
              f"ROI {roi(res)*100:+.1f}%  closed n={len(clo)} ROI {roi(clo)*100:+.1f}%  "
              f"settlement edge {e['edge']*100:+.1f}pp (z {e['z']:+.1f})")
        print(f"     capital-time share {sum(b['cd'] for b in legs)/cd*100:.1f}%  "
              f"hold {sum(b['hold'] for b in legs)/len(legs):.1f}d  "
              f"$/1k-cd ${sum(b['pnl'] for b in legs)/sum(b['cd'] for b in legs):.1f}")

    # ---- I. drawdown -----------------------------------------------------------
    hdr("I. DRAWDOWN -- what the 1.5x actually costs when the tail goes the other way")
    for label, pop in (("book", bets), ("cheap 0.00-0.20", [b for b in bets if b["band"] == "0.00-0.20"]),
                       ("main/0.00-0.20", [b for b in bets if b["band"] == "0.00-0.20" and b["lane"] == "main"])):
        if not pop:
            continue
        day = {}
        for b in pop:
            d = int((b["resolvedAt"] or b["closedAt"] or b["openedAt"]) // DAY)
            day[d] = day.get(d, 0.0) + b["pnl"]
        lo, hi = min(day), max(day)
        series = [day.get(d, 0.0) for d in range(lo, hi + 1)]
        worst_day = min(series)
        worst7 = min(sum(series[i:i + 7]) for i in range(max(1, len(series) - 6)))
        cum, peak, mdd = 0.0, 0.0, 0.0
        for v in series:
            cum += v
            peak = max(peak, cum)
            mdd = min(mdd, cum - peak)
        print(f"  {label:<16} worst day ${worst_day:>8,.1f} | worst 7d ${worst7:>8,.1f} | "
              f"max peak-to-trough ${mdd:>8,.1f}   -> at 1.5x: ${mdd*1.5:>8,.1f}")

    # ---- J. refusals ------------------------------------------------------------
    hdr("J. THE FUNNEL -- refusals in the last 7 days, and the three largest are correct")
    sk = con.execute(
        "SELECT COUNT(*) n FROM DecisionJournal WHERE isDemo=0 AND decision='skip' "
        "AND createdAt > (strftime('%s','now')-7*86400)*1000"
    ).fetchone()["n"]
    cp = con.execute(
        "SELECT COUNT(*) n FROM DecisionJournal WHERE isDemo=0 AND decision='paper_copy' "
        "AND createdAt > (strftime('%s','now')-7*86400)*1000"
    ).fetchone()["n"]
    print(f"  skips {sk:,}  vs  copies {cp:,}  in 7d")
    reasons = {}
    for r in con.execute(
        "SELECT risksJson FROM DecisionJournal WHERE isDemo=0 AND decision='skip' "
        "AND createdAt > (strftime('%s','now')-7*86400)*1000"
    ):
        try:
            rs = json.loads(r[0] or "[]")
        except Exception:
            continue
        if not isinstance(rs, list) or not rs:
            continue
        key = str(rs[0])
        # collapse the numeric payload so the census groups
        key = key.split(" since entry")[0].split(" (")[0][:60]
        reasons[key] = reasons.get(key, 0) + 1
    for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])[:8]:
        print(f"    {v:>5}  {k}")

    # ---- K. category ------------------------------------------------------------
    hdr("K. CATEGORY -- is the PnL a subject, or a price?")
    cat = {}
    cmap = {}
    for r in con.execute(
        "SELECT j.id jid, o.marketCategoryClass c FROM DecisionJournal j "
        "JOIN ObservedTrade o ON j.observedTradeId=o.id"
    ):
        cmap[r["jid"]] = r["c"]
    for b in bets:
        c = cmap.get(b["jid"]) or "(none)"
        d = cat.setdefault(c, dict(n=0, ntl=0.0, pnl=0.0, top=0.0))
        d["n"] += 1
        d["ntl"] += b["ntl"]
        d["pnl"] += b["pnl"]
        d["top"] = max(d["top"], b["pnl"])
    for c, d in sorted(cat.items(), key=lambda kv: -kv[1]["pnl"]):
        print(f"  {c:<10} n={d['n']:>4} ntl=${d['ntl']:>8,.0f} pnl=${d['pnl']:>9,.1f} "
              f"roi={d['pnl']/d['ntl']*100:>+7.1f}%  largest single leg ${d['top']:>8,.1f}")

    # ---- L. drift shadow, by band ----------------------------------------------
    hdr("L. DRIFT SHADOW BY BAND -- why its trailing cohort flips sign (composition, not decay)")
    try:
        cand, res = [], {}
        import os
        p = os.path.join(os.path.dirname(__file__), "..", "data", "drift-shadow.jsonl")
        for line in open(p):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("type") == "resolve":
                res[f"{r.get('marketId')}|{r.get('outcome')}"] = r.get("value")
            elif r.get("type") == "candidate":
                cand.append(r)
        sig = {}
        for c in cand:
            k = f"{c['marketId']}|{c['outcome']}|{c.get('wallet')}"
            if k not in sig or str(c["ts"]) < str(sig[k]["ts"]):
                sig[k] = c
        agg = {}
        for c in sig.values():
            v = res.get(f"{c['marketId']}|{c['outcome']}")
            e0 = float(c.get("currentPrice") or 0)
            if v is None or e0 <= 0 or e0 < 0.10:
                continue
            d = agg.setdefault(band_of(e0), dict(n=0, w=0, ps=0.0))
            d["n"] += 1
            d["ps"] += e0
            if v > 0:
                d["w"] += 1
        print(f"  signals {len(sig):,} of {len(cand):,} rows; settled and >=$0.10 entry:")
        for b in [n for _, _, n in BANDS]:
            d = agg.get(b)
            if not d or d["n"] < 20:
                continue
            hit, pr = d["w"] / d["n"], d["ps"] / d["n"]
            se = math.sqrt(max(hit * (1 - hit), 1e-12) / d["n"])
            print(f"    {b:<10} n={d['n']:>4} hit={hit*100:>5.1f}% price={pr:.3f} "
                  f"edge={(hit-pr)*100:>+6.1f}pp z={(hit-pr)/se:>+5.1f}")
        print("  (counterfactual = the price the gate BLOCKED at, not our booked entry.)")

        # post-fix population: the 2026-10-26 sign fix means a FAVOURABLE move can never be
        # skipped for drift, so from that date the feed should carry adverse rows almost only.
        # If it still carries bargains, the fix is not live; if adverse-only edge is ~0, there
        # is nothing left to relax.
        CUT = "2026-10-26T00:00:00"
        post = {}
        for c in sig.values():
            if str(c["ts"]) < CUT:
                continue
            v = res.get(f"{c['marketId']}|{c['outcome']}")
            e0 = float(c.get("currentPrice") or 0)
            we = float(c.get("walletEntryPrice") or 0)
            if v is None or e0 < 0.10 or we <= 0:
                continue
            kind = "adverse" if e0 > we else "favourable/cheap"
            d = post.setdefault(kind, dict(n=0, w=0, ps=0.0))
            d["n"] += 1
            d["ps"] += e0
            if v > 0:
                d["w"] += 1
        print("  post-sign-fix rows (>= 2026-10-26):")
        for k in ("adverse", "favourable/cheap"):
            d = post.get(k)
            if not d:
                print(f"    {k:<17} n=0")
                continue
            hit, pr = d["w"] / d["n"], d["ps"] / d["n"]
            se = math.sqrt(max(hit * (1 - hit), 1e-12) / d["n"])
            print(f"    {k:<17} n={d['n']:>4} hit={hit*100:>5.1f}% price={pr:.3f} "
                  f"edge={(hit-pr)*100:>+6.1f}pp z={(hit-pr)/se:>+5.1f}")
    except FileNotFoundError:
        print("  data/drift-shadow.jsonl not found")

    # ---- self-test --------------------------------------------------------------
    if "--self-test" in sys.argv:
        hdr("SELF-TEST")
        ok = True
        for name in [n for _, _, n in BANDS]:
            legs = [b for b in bets if b["band"] == name]
            if not legs:
                continue
            res = [b for b in legs if b["status"] == "resolved"]
            if not res:
                continue
            # fill-aware zero: bookedPnl() books exactly 0 on an UNFILLED leg, so these sit in
            # the population with full notional and no PnL -- counted, not asserted on.
            zero = [b for b in res if b["pnl"] == 0.0]
            res = [b for b in res if b["pnl"] != 0.0]
            # payoff identity on resolved legs, NOTIONAL-WEIGHTED (equal-weighting would
            # compare a mean of ratios with a ratio of sums and invent a gap):
            # win -> +ntl*(1-p)/p, loss -> -ntl. Must equal the booked resolved PnL exactly.
            implied = sum((b["ntl"] * (1 - b["entryPrice"]) / b["entryPrice"]) if b["pnl"] > 0
                          else -b["ntl"] for b in res) / sum(b["ntl"] for b in res)
            actual = roi(res)
            delta = abs(implied - actual)
            flag = "OK" if delta < 0.02 else "MISMATCH"
            if delta >= 0.02:
                ok = False
            e = hit_edge(legs)
            # resolved ROI including the unfilled zeros (the number that prices fill drag)
            resall = [b for b in legs if b["status"] == "resolved"]
            print(f"  {name:<10} implied {implied*100:+7.1f}% vs actual {actual*100:+7.1f}%  "
                  f"delta {delta*100:.1f}pp  {flag}  | unfilled-zero {len(zero)} legs "
                  f"${sum(b['ntl'] for b in zero):,.0f} | resolved ROI incl zeros "
                  f"{roi(resall)*100:+.1f}% vs filled {actual*100:+.1f}%")
        print(f"  partition check: sum(band n)={sum(1 for b in bets if b['band'])} of {len(bets)}")
        print("  RESULT:", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
