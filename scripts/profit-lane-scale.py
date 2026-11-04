#!/usr/bin/env python3
"""LANE + EXIT READ -- the 2026-11-04 profit review instrument.

TWO QUESTIONS, ONE INSTRUMENT, because the second explains the first.

1. WHERE THE MONEY IS. Profit = edge x capital x turnover. Sections A-F price every
   lane x band cell on $/1k-capital-day, show what the per-bet clamp actually does, and
   say which cells clear their own market-clustered CI on the FULL basis.

2. WHY THE SHORT-TTR CELLS LOOK MUCH BETTER THAN THEY ARE -- the exit. Measured
   2026-11-04: the same cells read +23-25% if you restrict to status='resolved' and
   +4-5% if you include status='closed'. That is not a rounding difference, it is the
   book's own 24h adverse stop (staleExitHours=24, staleExitAdverseMove=-0.15,
   staleExitAdverseOnly=1, scripts/update-pnl.ts) booking -15% to -18% on 38% of the
   lane's bets. Section G prices the counterfactual (hold to settlement) on the legs
   that stop actually closed, with a market-clustered CI, an ex-top-N cut, and the
   won/lost split -- because "hold the losers too" is the obvious way to be wrong here.

COST BASIS (mandatory)
  cost = PaperTrade.simulatedPositionSize = DOLLARS AT RISK, never a share count and
  never multiplied by entryPrice. Bet level = first leg per (bot|wallet|market|outcome),
  mirroring scripts/profit-band-report.py load().

LANE ATTRIBUTION
  Authoritative: the scoring path stamps the lane into DecisionJournal.reasonsJson
  ("Short-TTR lane: resolves in Xh -- daily PnL channel", src/lib/scoring/trade.ts:411).
  A snapshot-TTR proxy (2h <= ttr <= 72h) is printed beside it as an agreement check,
  because a proxy that disagrees would silently move every cell number.

READ-ONLY: no prisma write, no RuleSet touched, nothing applied.

USAGE
  python3 scripts/profit-lane-scale.py              # 90d, all rule versions
  python3 scripts/profit-lane-scale.py --since-v49   # regime only (ruleSetVersion >= 49)
"""
import sqlite3
import sys
import time
import numpy as np

DB = "file:prisma/dev.db?mode=ro"
DAYS = 90
BANDS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0001)]
SHTTR_MIN, SHTTR_MAX = 2.0, 72.0
CAP_LEGACY = 20.00
SINCE_V49 = "--since-v49" in sys.argv


def band_name(lo, hi):
    return f"{lo:.1f}-{hi:.1f}" if hi <= 1 else "0.8-1.0"


BAND_NAMES = [band_name(lo, hi) for lo, hi in BANDS]


def band_of(p):
    for lo, hi in BANDS:
        if lo <= p < hi:
            return band_name(lo, hi)
    return None


def connect():
    con = sqlite3.connect(DB, uri=True)
    con.row_factory = sqlite3.Row
    return con


def load(con, since_ms=0, min_rule=0):
    sql = """
        SELECT p.id, p.botId, p.walletAddress, p.marketId, p.outcome, p.entryPrice,
               p.simulatedPositionSize AS ntl, p.realizedPnl AS pnl, p.status,
               p.openedAt, p.closedAt, p.resolvedAt, j.ruleSetVersion AS rv,
               j.reasonsJson AS rj
        FROM PaperTrade p
        LEFT JOIN DecisionJournal j ON p.decisionJournalId = j.id
        WHERE p.isDemo = 0 AND p.status IN ('closed','resolved')
          AND p.realizedPnl IS NOT NULL AND p.openedAt >= ?
    """
    params = [since_ms]
    if min_rule:
        sql += " AND j.ruleSetVersion >= ?"
        params.append(min_rule)
    sql += " ORDER BY p.openedAt ASC"
    seen, out, tcache = set(), [], {}
    for r in con.execute(sql, params):
        k = (r["botId"], r["walletAddress"], r["marketId"], r["outcome"])
        if k in seen:
            continue
        seen.add(k)
        px, ntl = r["entryPrice"], r["ntl"]
        if not px or px <= 0 or not ntl or ntl <= 0:
            continue
        end = r["resolvedAt"] or r["closedAt"]
        if not end:
            continue
        ck = (r["marketId"], r["openedAt"] // 3_600_000)
        if ck not in tcache:
            s = con.execute(
                """SELECT timeToResolution, liquidity FROM MarketSnapshot
                   WHERE marketId=? AND collectedAt<=? AND timeToResolution IS NOT NULL
                   ORDER BY collectedAt DESC LIMIT 1""",
                (r["marketId"], r["openedAt"] + 900_000)).fetchone()
            tcache[ck] = (s[0], s[1]) if s else (None, None)
        ttr, liq = tcache[ck]
        if r["botId"] != "BANKROLL_200":
            lane = "standard"
        elif r["rj"] and "Short-TTR lane" in r["rj"]:
            lane = "c200-shttr"
        else:
            lane = "c200-main"
        proxy = "c200-shttr" if (ttr is not None and SHTTR_MIN <= ttr <= SHTTR_MAX) else "c200-main"
        out.append({"id": r["id"], "bot": r["botId"], "lane": lane, "proxy": proxy,
                    "market": r["marketId"], "wallet": r["walletAddress"], "outcome": r["outcome"],
                    "band": band_of(px), "px": px, "ntl": ntl, "pnl": r["pnl"], "ttr": ttr,
                    "liq": liq, "status": r["status"], "ms": r["openedAt"], "rv": r["rv"],
                    "won": 1 if r["pnl"] > 0 else 0,
                    "hold": max((end - r["openedAt"]) / 86_400_000.0, 1.0 / 24)})
    return out


def roi(legs):
    n = sum(l["ntl"] for l in legs)
    return 100.0 * sum(l["pnl"] for l in legs) / n if n else 0.0


def _boot(legs, val, reps=1500, seed=7):
    by = {}
    for l in legs:
        by.setdefault(l["market"], []).append(l)
    keys = list(by)
    if len(keys) < 3:
        return (0.0, 0.0)
    rng = np.random.default_rng(seed)
    out = np.empty(reps)
    for i in range(reps):
        pick = rng.integers(0, len(keys), len(keys))
        s = 0.0
        for j in pick:
            s += sum(val(x) for x in by[keys[j]])
        out[i] = s
    return float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))


def cluster_ci(legs):
    return _boot(legs, lambda l: l["pnl"] if False else l["pnl"] / 0 if False else l["pnl"])


def roi_ci(legs):
    """Market-clustered CI on notional-weighted ROI (pct points)."""
    by = {}
    for l in legs:
        by.setdefault(l["market"], []).append(l)
    keys = list(by)
    if len(keys) < 3:
        return (0.0, 0.0)
    rng = np.random.default_rng(7)
    out = np.empty(1500)
    for i in range(1500):
        pick = rng.integers(0, len(keys), len(keys))
        sp = sn = 0.0
        for j in pick:
            for l in by[keys[j]]:
                sp += l["pnl"]
                sn += l["ntl"]
        out[i] = 100 * sp / sn if sn else 0.0
    return float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))


def ex_top(legs, k=5):
    s = sorted(legs, key=lambda l: -l["pnl"])[k:]
    return roi(s) if s else 0.0


def usd_per_1k_cd(legs):
    cd = sum(l["ntl"] * l["hold"] for l in legs)
    return 1000.0 * sum(l["pnl"] for l in legs) / cd if cd else 0.0


def slip_tolerance(legs):
    n = sum(l["ntl"] for l in legs)
    if not n:
        return 0.0
    avgp = sum(l["ntl"] * l["px"] for l in legs) / n
    return roi(legs) / 100.0 * avgp * 100.0  # cents of entry worsening to zero ROI


def hdr(t):
    print("\n" + "=" * 110)
    print(t)
    print("=" * 110)


def lane_band_table(legs):
    hdr("A. EDGE PER CAPITAL-DAY, lane x band (bet level, cost = $ at risk, closed+resolved)")
    print(f"{'lane':11} {'band':9} {'n':>5} {'notional':>10} {'PnL':>10} {'ROI%':>8} "
          f"{'95% CI':>19} {'ex-top5':>8} {'clip$':>7} {'medTTR':>7} {'$/1k-cd':>8} {'slip_c':>6}")
    cells = []
    for lane in ("standard", "c200-main", "c200-shttr"):
        for nm in BAND_NAMES:
            g = [l for l in legs if l["lane"] == lane and l["band"] == nm]
            if not g:
                continue
            ntl = sum(l["ntl"] for l in g)
            lo, hi = roi_ci(g)
            tt = sorted(l["ttr"] for l in g if l["ttr"] is not None)
            medt = tt[len(tt) // 2] if tt else float("nan")
            print(f"{lane:11} {nm:9} {len(g):>5} {ntl:>10,.0f} {sum(l['pnl'] for l in g):>+10,.0f} "
                  f"{roi(g):>+8.1f} [{lo:>+7.1f},{hi:>+7.1f}] {ex_top(g):>+8.1f} {ntl/len(g):>7.2f} "
                  f"{medt:>7.1f} {usd_per_1k_cd(g):>+8.2f} {slip_tolerance(g):>6.2f}")
            cells.append((lane, nm, g))
    return cells


def attribution_check(legs):
    hdr("A2. LANE ATTRIBUTION: journal label vs snapshot-TTR proxy")
    for lane in ("c200-main", "c200-shttr"):
        g = [l for l in legs if l["lane"] == lane]
        agree = sum(1 for l in g if l["proxy"] == lane)
        ntl = sum(l["ntl"] for l in g)
        print(f"   journal {lane:11} n={len(g):>4} ${ntl:>8,.0f}  proxy agrees on "
              f"{100*agree/max(len(g),1):>5.1f}% of legs, "
              f"${100*sum(l['ntl'] for l in g if l['proxy']==lane)/max(ntl,1):>5.1f}% of notional")
    miss = [l for l in legs if l["lane"] != "standard" and l["lane"] != l["proxy"]]
    if miss:
        print(f"   disagreement: {len(miss)} legs, ${sum(l['ntl'] for l in miss):,.0f}, "
              f"PnL {sum(l['pnl'] for l in miss):+,.2f}")


def cap_census(con, legs):
    hdr("B. PER-BET CEILING: what actually binds (BOT_LIMITS.BANKROLL_200.max = $20)")
    print(f"{'lane':11} {'band':9} {'n':>5} {'avg':>7} {'med':>7} {'share@20':>9} {'share@10':>9} {'share<6':>8}")
    for lane in ("standard", "c200-main", "c200-shttr"):
        for nm in BAND_NAMES:
            g = [l for l in legs if l["lane"] == lane and l["band"] == nm]
            if len(g) < 10:
                continue
            s = np.array([l["ntl"] for l in g])
            print(f"{lane:11} {nm:9} {len(g):>5} {s.mean():>7.2f} {np.median(s):>7.2f} "
                  f"{100*np.mean(np.abs(s-20) < .02):>8.0f}% {100*np.mean(np.abs(s-10) < .02):>8.0f}% "
                  f"{100*np.mean(s < 6):>7.0f}%")


def velocity(legs):
    hdr("F. TURNOVER: capital-days and the daily rate each lane sustains")
    print(f"{'lane':11} {'n':>5} {'notional':>10} {'PnL':>10} {'capital_days':>13} {'$/1k-cd':>9} "
          f"{'$/day':>8} {'PnL share':>10}")
    tot = sum(l["pnl"] for l in legs)
    tot_cd = 0.0
    for lane in ("standard", "c200-main", "c200-shttr"):
        g = [l for l in legs if l["lane"] == lane]
        if not g:
            continue
        cd = sum(l["ntl"] * l["hold"] for l in g)
        tot_cd += cd
        p = sum(l["pnl"] for l in g)
        print(f"{lane:11} {len(g):>5} {sum(l['ntl'] for l in g):>10,.0f} {p:>+10,.0f} {cd:>13,.0f} "
              f"{1000*p/cd if cd else 0:>+9.2f} {p/DAYS:>+8.2f} {100*p/tot if tot else 0:>9.1f}%")
    span = (max(l["ms"] for l in legs) - min(l["ms"] for l in legs)) / 86_400_000
    print(f"   notional continuously in flight = capital_days / span = ${tot_cd/span:,.0f} "
          f"(exposure cap ~$4,760; so the cap is {4760/(tot_cd/span):.1f}x away and size, not "
          f"capital, is the binding constraint)")


# --------------------------------------------------------------------- G
def exit_read(con, legs):
    """G1. The status split. G2. Hold-to-settlement counterfactual on stopped legs."""
    hdr("G1. THE SAME CELLS, SPLIT BY OUR OWN EXIT (this is the whole v71 gap)")
    print("   resolved = held to settlement by the bot; closed = the stale-exit block cut it")
    print("   (staleExitHours=24, staleExitAdverseMove=-0.15, adverseOnly=1 -> a -15% stop)")
    print(f"{'lane':11} {'band':9} {'status':8} {'n':>4} {'ntl':>8} {'PnL':>9} {'ROI%':>7} {'medHoldH':>8}")
    for lane in ("standard", "c200-main", "c200-shttr"):
        for nm in BAND_NAMES:
            for st in ("resolved", "closed"):
                g = [l for l in legs if l["lane"] == lane and l["band"] == nm and l["status"] == st]
                if len(g) < 8:
                    continue
                ntl = sum(l["ntl"] for l in g)
                holds = sorted(l["hold"] * 24 for l in g)
                print(f"{lane:11} {nm:9} {st:8} {len(g):>4} {ntl:>8,.0f} "
                      f"{sum(l['pnl'] for l in g):>+9,.0f} {100*sum(l['pnl'] for l in g)/ntl:>+7.1f} "
                      f"{holds[len(holds)//2]:>8.1f}")

    hdr("G2. COUNTERFACTUAL: hold the stopped legs to their market's final mark")
    print("   For each closed leg: booked PnL (actual) vs stake*(m/p - 1) at the market's LAST")
    print("   recorded mark for the held outcome. 'settled' = last mark >=0.995 or <=0.005, so")
    print("   the outcome is unambiguous and the delta needs no mark-to-market assumption.")
    print("   Delta is per-leg improvement; CI is market-clustered on delta/notional.")
    print(f"{'lane':11} {'band':9} {'n':>4} {'booked':>9} {'held':>9} {'delta':>9} "
          f"{'d/ntl%':>7} {'CI95':>18} {'ex-top5':>8} {'won':>4} {'lost':>4} {'dsettled':>9}")
    for lane in ("c200-main", "c200-shttr"):
        for nm in BAND_NAMES:
            g = [l for l in legs if l["lane"] == lane and l["band"] == nm and l["status"] == "closed"]
            if len(g) < 8:
                continue
            booked = sum(l["pnl"] for l in g)
            ntl = sum(l["ntl"] for l in g)
            ds = []
            won = lost = 0
            dsettled = 0.0
            for l in g:
                col = "yesPrice" if l["outcome"] == "YES" else "noPrice"
                s = con.execute(f"""SELECT {col} v FROM MarketSnapshot WHERE marketId=?
                                    ORDER BY collectedAt DESC LIMIT 1""", (l["market"],)).fetchone()
                m = s["v"] if s and s["v"] is not None else None
                if m is None:
                    ds.append({"market": l["market"], "ntl": l["ntl"], "d": 0.0})
                    continue
                held = l["ntl"] * (m / l["px"] - 1)
                d = held - l["pnl"]
                ds.append({"market": l["market"], "ntl": l["ntl"], "d": d})
                if m >= 0.995 or m <= 0.005:
                    dsettled += d
                    if (m >= 0.995) == (l["outcome"] == "YES"):
                        won += 1
                    else:
                        lost += 1
            tot_d = sum(x["d"] for x in ds)
            ex = sorted(ds, key=lambda x: -x["d"])[5:]
            lo, hi = _boot([{**x} for x in ds], lambda x: x["d"])
            print(f"{lane:11} {nm:9} {len(g):>4} {booked:>+9,.0f} {booked+tot_d:>+9,.0f} "
                  f"{tot_d:>+9,.0f} {100*tot_d/ntl:>+7.1f} [{lo:>+7.1f},{hi:>+7.1f}] "
                  f"{100*sum(x['d'] for x in ex)/ntl:>+7.1f}% {won:>4} {lost:>4} {dsettled:>+9,.0f}")

    hdr("G3. WHAT THE STOP WOULD TAKE NEXT CYCLE (open book right now)")
    now = int(time.time() * 1000)
    open_legs = con.execute("""
        SELECT p.id, p.marketId m, p.outcome o, p.entryPrice px, p.simulatedPositionSize n,
               p.currentPrice c, p.openedAt, j.reasonsJson rj
        FROM PaperTrade p LEFT JOIN DecisionJournal j ON p.decisionJournalId=j.id
        WHERE p.botId='BANKROLL_200' AND p.isDemo=0 AND p.status='open'""").fetchall()
    rows = []
    for r in open_legs:
        if not r["px"] or not r["c"] or not r["n"]:
            continue
        age = (now - r["openedAt"]) / 3.6e6
        move = (r["c"] - r["px"]) / r["px"] if r["o"] == "YES" else (r["px"] - r["c"]) / r["px"]
        lane = "shttr" if (r["rj"] and "Short-TTR lane" in r["rj"]) else "main"
        rows.append((lane, age, move, r["n"], r["m"]))
    for lane in ("main", "shttr"):
        q = [r for r in rows if r[0] == lane]
        fire = [r for r in q if r[1] >= 24 and r[2] <= -0.15]
        print(f"   {lane:6} open={len(q):>3}  past 24h={sum(1 for r in q if r[1] >= 24):>3}  "
              f"adverse<=-15%={sum(1 for r in q if r[2] <= -0.15):>3}  "
              f"WOULD STOP NEXT CYCLE={len(fire):>3} (${sum(r[3] for r in fire):,.2f} at risk)")


def pooled_band(legs, lo=0.20, hi=0.40):
    """H. The one band that carries volume AND edge -- and whether its breadth survives."""
    hdr(f"H. POOLED {lo:.2f}-{hi:.2f} ACROSS ALL LANES (the band that carries both volume and edge)")
    g = [l for l in legs if lo <= l["px"] < hi]
    if not g:
        print("   no legs")
        return
    ntl = sum(l["ntl"] for l in g)
    ci = roi_ci(g)
    bym = {}
    for l in g:
        bym.setdefault(l["market"], []).append(l)
    print(f"   {len(g)} bets, ${ntl:,.0f}, PnL ${sum(l['pnl'] for l in g):+,.2f}, ROI {roi(g):+.1f}%, "
          f"CI [{ci[0]:+.1f},{ci[1]:+.1f}], {len(bym)} markets ({len(g)/len(bym):.2f} bets/market)")
    order = sorted(bym.items(), key=lambda kv: -sum(x["pnl"] for x in kv[1]))
    print(f"   {'cut':8} {'n':>4} {'ntl':>8} {'pnl':>9} {'roi%':>7} {'CI':>20}")
    for k in (0, 1, 5, 10, 20):
        drop = {m for m, _ in order[:k]}
        keep = [x for x in g if x["market"] not in drop]
        if not keep:
            continue
        c = roi_ci(keep)
        print(f"   top-{k:<4} {len(keep):>4} {sum(x['ntl'] for x in keep):>8,.0f} "
              f"{sum(x['pnl'] for x in keep):>+9,.0f} {roi(keep):>+7.1f} [{c[0]:>+7.1f},{c[1]:>+7.1f}]")
    for st in ("resolved", "closed"):
        s = [x for x in g if x["status"] == st]
        if not s:
            continue
        c = roi_ci(s)
        print(f"   {st:9} n={len(s):>4} ${sum(x['ntl'] for x in s):>7,.0f} "
              f"${sum(x['pnl'] for x in s):>+8,.0f} {roi(s):>+6.1f}% CI[{c[0]:+.1f},{c[1]:+.1f}]")
    print(f"   median hold {np.median([x['hold']*24 for x in g]):.1f}h; "
          f"clip ${ntl/len(g):.2f}; $/1k-cd {usd_per_1k_cd(g):+.1f}; "
          f"slip tolerance {slip_tolerance(g):.2f}c")


# --------------------------------------------------------------------- I
def calibration(legs):
    """I. Settlement truth. On resolved legs PnL>0 iff the token won, so ROI must equal
    hit*(1/p - 1) - (1-hit). The identity is CHECKED on every row, not assumed."""
    hdr("I. CALIBRATION ON SETTLEMENT TRUTH (resolved legs only -- no stop, no marks)")
    print("   breakeven hit rate == entry price. edge_pp = hit% - p. z uses the binomial SE.")
    print("   implied column proves the identity holds: realized ROI == hit*(1/p-1)-(1-hit).")
    print(f"{'cell':22} {'n':>4} {'avgPx':>6} {'hit%':>6} {'edge_pp':>8} {'z':>5} {'ROI%':>8} {'implied':>8}")
    for lane in ("standard", "c200-main", "c200-shttr"):
        for lo, hi in BANDS[:4]:
            g = [l for l in legs if l["lane"] == lane and l["status"] == "resolved"
                 and lo <= l["px"] < hi]
            if len(g) < 8:
                continue
            n = len(g)
            hit = sum(l["won"] for l in g) / n
            ntl = sum(l["ntl"] for l in g)
            avgp = sum(l["px"] * l["ntl"] for l in g) / ntl
            edge = 100 * (hit - avgp)
            se = 100 * np.sqrt(hit * (1 - hit) / n)
            roi_ = 100 * sum(l["pnl"] for l in g) / ntl
            implied = 100 * sum(l["ntl"] * ((1 / l["px"] - 1) if l["won"] else -1) for l in g) / ntl
            print(f"{lane + ' ' + band_name(lo, hi):22} {n:>4} {avgp:>6.3f} {100*hit:>6.1f} "
                  f"{edge:>+8.1f} {edge/se if se else 0:>+5.1f} {roi_:>+8.1f} {implied:>+8.1f}")


# --------------------------------------------------------------------- J
def breadth(legs, lo=0.05, hi=0.20):
    """J. Is a cheap band's edge broad, or is it the biggest winners re-counted?

    The trap this exists to avoid: at a 0.12 entry a win pays ~8x, so ex-top-N ROI ALWAYS
    collapses once the ten biggest wins are removed -- that is the payoff structure, not the
    edge. The test that is not fooled is the HIT RATE: drop the top-N markets by PnL and ask
    whether the remaining bets still win more often than their own entry price. A residual at
    breakeven means the band earns its money in a handful of events and must not be sized up.
    """
    hdr(f"J. BREADTH OF THE {lo:.2f}-{hi:.2f} BAND (hit rate is the test, not ex-top-N ROI)")
    g = [l for l in legs if lo <= l["px"] < hi]
    bym = {}
    for l in g:
        bym.setdefault(l["market"], []).append(l)
    order = sorted(bym.items(), key=lambda kv: -sum(x["pnl"] for x in kv[1]))
    print(f"   {len(g)} bets on {len(bym)} markets; {len({l['market'] for l in g if l['won']})} "
          f"markets had a winning leg; {sum(l['won'] for l in g)} wins total")
    print(f"   {'cut':10} {'n':>4} {'wins':>5} {'hit%':>6} {'breakeven%':>11} {'edge_pp':>8} "
          f"{'z':>5} {'ROI%':>7}")
    for k in (0, 1, 5, 10, 20):
        drop = {m for m, _ in order[:k]}
        s = [x for x in g if x["market"] not in drop]
        n = len(s)
        if n < 10:
            continue
        w = sum(x["won"] for x in s)
        hit = w / n
        ntl = sum(x["ntl"] for x in s)
        avgp = sum(x["px"] * x["ntl"] for x in s) / ntl
        se = np.sqrt(hit * (1 - hit) / n)
        print(f"   top-{k:<5} {n:>4} {w:>5} {100*hit:>6.1f} {100*avgp:>11.1f} "
              f"{100*(hit-avgp):>+8.1f} {((hit-avgp)/se) if se else 0:>+5.1f} {roi(s):>+7.1f}")
    med = sorted(x["ms"] for x in g)[len(g) // 2]
    print("   time split (pre-registered, not outcome-selected):")
    for tag, s in (("early half", [x for x in g if x["ms"] < med]),
                   ("late half", [x for x in g if x["ms"] >= med])):
        n = len(s)
        hit = sum(x["won"] for x in s) / n
        ntl = sum(x["ntl"] for x in s)
        avgp = sum(x["px"] * x["ntl"] for x in s) / ntl
        se = np.sqrt(hit * (1 - hit) / n)
        print(f"     {tag:11} n={n:>3} hit={100*hit:>5.1f}% p={100*avgp:>5.1f}% "
              f"edge={100*(hit-avgp):>+6.1f}pp z={((hit-avgp)/se) if se else 0:>+5.1f} "
              f"ROI={roi(s):>+7.1f}%")
    print("   per lane:")
    for lane in ("standard", "c200-main", "c200-shttr"):
        s = [x for x in g if x["lane"] == lane]
        if len(s) < 8:
            continue
        n = len(s)
        hit = sum(x["won"] for x in s) / n
        ntl = sum(x["ntl"] for x in s)
        avgp = sum(x["px"] * x["ntl"] for x in s) / ntl
        print(f"     {lane:11} n={n:>3} hit={100*hit:>5.1f}% p={100*avgp:>5.1f}% "
              f"edge={100*(hit-avgp):>+6.1f}pp ROI={roi(s):>+7.1f}% clip=${ntl/n:>6.2f}")


def main():
    con = connect()
    since = int((time.time() - DAYS * 86400) * 1000)
    legs = load(con, since, min_rule=49 if SINCE_V49 else 0)
    span = (max(l["ms"] for l in legs) - min(l["ms"] for l in legs)) / 86_400_000
    print(f"POPULATION  {len(legs):,} bets, ${sum(l['ntl'] for l in legs):,.0f} at risk, "
          f"PnL ${sum(l['pnl'] for l in legs):+,.2f}, ROI {roi(legs):+.2f}%, span {span:.1f}d, "
          f"{DAYS}d lookback, dedup per bot|wallet|market|outcome, cost=$at-risk"
          f"{', ruleSetVersion>=49' if SINCE_V49 else ''}")
    lane_band_table(legs)
    attribution_check(legs)
    cap_census(con, legs)
    velocity(legs)
    exit_read(con, legs)
    pooled_band(legs)
    pooled_band(legs, 0.0, 0.20)
    calibration(legs)
    breadth(legs)


if __name__ == "__main__":
    main()
