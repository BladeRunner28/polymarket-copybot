#!/usr/bin/env python3
"""
Lane x band robustness allocation -- the instrument behind drafts/profit-recs-20261103.md.

THE QUESTION IT ANSWERS: is the book's MONEY where its EDGE is, or where the edge is
merely LOUD? Every prior band table in this repo pools the two copy lanes, and the lanes
disagree in sign inside the same price band. Pooling them produced the two claims that
have been driving sizing ("<0.20 is the only +EV bucket", "0.4-0.6 is dead") -- both of
which are lane-dependent and neither of which survives the robustness tests below.

COST BASIS (must travel with every ROI in the draft):
  `PaperTrade.simulatedPositionSize` is DOLLARS at risk, never shares. A BUY of $n at p is
  n/p shares, so settlement at s realises n*(s/p - 1). Cost = simulatedPositionSize.
BET BASIS: first leg per (walletAddress, marketId, outcome), ordered by openedAt. The book
  has legacy duplicate stacks; leg-level counting inflates wins by the stack depth.
POPULATION: isDemo=0, DecisionJournal.ruleSetVersion >= 49 (the live regime), status
  'resolved' (natural settlement) as the primary; 'closed' (mark exit) printed alongside.
HURDLE: the break-even hit rate at price p with taker fee r is p*(1 + r*(1-p)), NOT p.
  Fee r = 0.05 (the repo's default; category rates 0.04/0.07 move it by +-0.2pp on these
  cells and cannot move a sign here).
KELLY: f* = (b*phat - (1-phat))/b with b = (1-p)/p. The band that matters is not f* at
  phat -- it is whether f* keeps its SIGN one and two standard errors below phat. A cell
  whose f* flips negative at phat-2SE cannot carry size, whatever its headline ROI says.
SLIPPAGE: for a $1 stake at p, expected payoff is the hit rate, so ROI=0 exactly when the
  effective entry price equals the hit rate. Break-even entry slippage = hit - p. That is
  the number that decides whether a thin-book boost is real (axis 5).

USAGE
    python3 scripts/profit-robustness-alloc.py             # full report
    python3 scripts/profit-robustness-alloc.py --selftest   # identity checks
    python3 scripts/profit-robustness-alloc.py --json       # machine readable

Read-only: opens prisma/dev.db with mode=ro (immutable), writes nothing.
"""
import json
import sqlite3
import sys
import numpy as np

DB = "file:prisma/dev.db?mode=ro&immutable=1"
MIN_REGIME_VERSION = 49
FEE_RATE = 0.05
NET_WORTH = 8323.0  # kelly-window-report 2026-11-03: cash 8160 + open 164 (main lane)
BANDS = [(0.0, 0.2, "<0.20"), (0.2, 0.4, "0.2-0.4"), (0.4, 0.6, "0.4-0.6"),
         (0.6, 0.8, "0.6-0.8"), (0.8, 1.0001, "0.8+")]
ARGS = sys.argv[1:]


def band_of(p):
    for lo, hi, name in BANDS:
        if lo <= p < hi:
            return name
    return None


def connect():
    c = sqlite3.connect(DB, uri=True)
    c.row_factory = sqlite3.Row
    return c


def load(status="resolved"):
    """Bet-level rows for one status population."""
    q = """
    WITH leg AS (
      SELECT pt.id, pt.walletAddress, pt.marketId, pt.outcome, pt.entryPrice,
             pt.simulatedPositionSize AS size, pt.realizedPnl AS pnl,
             pt.openedAt, pt.botId, dj.ruleSetVersion AS v,
             CASE WHEN dj.reasonsJson LIKE '%Short-TTR%' THEN 'shortttr' ELSE 'main' END AS lane
      FROM PaperTrade pt
      JOIN DecisionJournal dj ON dj.id = pt.decisionJournalId
      WHERE pt.isDemo = 0 AND pt.status = ? AND pt.realizedPnl IS NOT NULL
        AND dj.ruleSetVersion >= ?
    ), bet AS (
      SELECT *, ROW_NUMBER() OVER (
        PARTITION BY walletAddress, marketId, outcome ORDER BY openedAt
      ) AS rn
      FROM leg
    )
    SELECT * FROM bet WHERE rn = 1
    """
    rows = connect().execute(q, (status, MIN_REGIME_VERSION)).fetchall()
    out = []
    for r in rows:
        b = band_of(r["entryPrice"])
        if b is None:
            continue
        out.append({"lane": r["lane"], "band": b, "market": r["marketId"],
                    "wallet": r["walletAddress"], "px": r["entryPrice"],
                    "size": r["size"], "pnl": r["pnl"], "opened": r["openedAt"]})
    return out


def cell_stats(rows):
    n = len(rows)
    if not n:
        return None
    ntl = sum(r["size"] for r in rows)
    pnl = sum(r["pnl"] for r in rows)
    hit = sum(1 for r in rows if r["pnl"] > 0) / n
    px = sum(r["px"] for r in rows) / n
    hurdle = px * (1 + FEE_RATE * (1 - px))
    edge = hit - hurdle
    se = (hit * (1 - hit) / n) ** 0.5
    # ex-top-5 MARKETS: drop the five markets that contributed most PnL
    by_mkt = {}
    for r in rows:
        a = by_mkt.setdefault(r["market"], [0.0, 0.0])
        a[0] += r["pnl"]
        a[1] += r["size"]
    top5 = sorted(by_mkt.values(), key=lambda a: -a[0])[:5]
    pnl5 = sum(a[0] for a in top5)
    ntl5 = sum(a[1] for a in top5)
    ex_pnl, ex_ntl = pnl - pnl5, ntl - ntl5
    b = (1 - px) / px if px > 0 else 0.0
    return {
        "n": n, "markets": len(by_mkt), "wallets": len({r["wallet"] for r in rows}),
        "notional": ntl, "pnl": pnl, "roi": pnl / ntl,
        "clip": ntl / n, "px": px, "hit": hit, "hurdle": hurdle, "edge": edge, "se": se,
        "z": edge / se if se else 0.0, "b": b,
        "ex5_roi": (ex_pnl / ex_ntl) if ex_ntl > 0 else float("nan"),
        "ex5_keep": (ex_pnl / pnl) if pnl else float("nan"),
        "best_share": (top5[0][0] / pnl) if pnl else float("nan"),
        "breakeven_slip_c": (hit - px) * 100,
    }


def kelly(c, hit):
    """f* at the given hit rate, on the cell's mean price."""
    b = c["b"]
    if b <= 0:
        return 0.0
    return (b * hit - (1 - hit)) / b


def cluster_ci(rows, iters=2000, seed=11):
    """Market-clustered bootstrap CI on ROI: resample MARKETS, not bets."""
    rng = np.random.default_rng(seed)
    by = {}
    for r in rows:
        a = by.setdefault(r["market"], [0.0, 0.0])
        a[0] += r["pnl"]
        a[1] += r["size"]
    keys = list(by)
    if len(keys) < 3:
        return (float("nan"), float("nan"))
    p = np.array([by[k][0] for k in keys])
    s = np.array([by[k][1] for k in keys])
    out = np.empty(iters)
    for i in range(iters):
        idx = rng.integers(0, len(keys), len(keys))
        d = s[idx].sum()
        out[i] = p[idx].sum() / d if d > 0 else 0.0
    return (float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5)))


def main():
    print("=" * 78)
    print("LANE x BAND ROBUSTNESS ALLOCATION — profit review 2026-11-03")
    print(f"population: isDemo=0, ruleSetVersion>={MIN_REGIME_VERSION}, status=resolved, "
          f"bet-level dedupe (wallet,market,outcome)")
    print(f"cost basis: simulatedPositionSize = DOLLARS at risk | fee rate {FEE_RATE}")
    print("=" * 78)

    res = load("resolved")
    closed = load("closed")
    print(f"\n§0 population: {len(res)} resolved bets / ${sum(r['size'] for r in res):,.0f} "
          f"notional  |  closed-legs cross-check: {len(closed)} bets / "
          f"${sum(r['size'] for r in closed):,.0f} / "
          f"{sum(r['pnl'] for r in closed)/max(1e-9,sum(r['size'] for r in closed))*100:+.1f}% ROI")
    span_a = min(r["opened"] for r in res)
    span_b = max(r["opened"] for r in res)
    days = (span_b - span_a) / 86400000.0
    print(f"   regime span: {span_a/1000:.0f} -> {span_b/1000:.0f} (unix s) = {days:.1f} days of entries")

    cells = {}
    for lane in ("main", "shortttr"):
        for _, _, band in BANDS:
            rows = [r for r in res if r["lane"] == lane and r["band"] == band]
            s = cell_stats(rows)
            if s:
                cells[(lane, band)] = (s, rows)

    print("\n§1 CELL TABLE (resolved bets). hurdle = p*(1+r*(1-p)); z = edge/SE(hit)")
    hdr = (f"{'lane':9} {'band':8} {'n':>4} {'mkts':>4} {'clip$':>6} {'notl$':>7} "
           f"{'pnl$':>8} {'roi':>7} {'px':>5} {'hit':>5} {'hurdle':>6} {'edge':>6} {'z':>5} "
           f"{'ex5roi':>7} {'keep':>5}")
    print(hdr)
    for key in sorted(cells, key=lambda k: (k[0], [b[2] for b in BANDS].index(k[1]))):
        s = cells[key][0]
        print(f"{key[0]:9} {key[1]:8} {s['n']:4d} {s['markets']:4d} {s['clip']:6.2f} "
              f"{s['notional']:7.0f} {s['pnl']:8.2f} {s['roi']*100:+6.1f}% {s['px']:5.3f} "
              f"{s['hit']:5.3f} {s['hurdle']:6.3f} {s['edge']*100:+5.1f}pp {s['z']:5.2f} "
              f"{s['ex5_roi']*100:+6.1f}% {s['ex5_keep']*100:4.0f}%")

    print("\n§2 KELLY SIGN STABILITY (b=(1-p)/p; f* at phat, phat-1SE, phat-2SE; half-Kelly $ on "
          f"net worth ${NET_WORTH:,.0f})")
    print(f"{'lane':9} {'band':8} {'b':>6} {'f*':>7} {'f*-1se':>7} {'f*-2se':>8} "
          f"{'halfK$':>8} {'clip$':>6} {'gap':>7}")
    for key in sorted(cells, key=lambda k: (k[0], [b[2] for b in BANDS].index(k[1]))):
        s = cells[key][0]
        f0 = kelly(s, s["hit"])
        f1 = kelly(s, s["hit"] - s["se"])
        f2 = kelly(s, s["hit"] - 2 * s["se"])
        half = max(0.0, f0) * 0.5 * NET_WORTH
        gap = half / s["clip"] if s["clip"] else float("nan")
        print(f"{key[0]:9} {key[1]:8} {s['b']:6.2f} {f0*100:+6.1f}% {f1*100:+6.1f}% "
              f"{f2*100:+7.1f}% {half:8.0f} {s['clip']:6.2f} {gap:6.0f}x")

    print("\n§3 MARKET-CLUSTERED 95% CI ON ROI (2000 resamples of MARKETS, not bets)")
    for key in sorted(cells, key=lambda k: (k[0], [b[2] for b in BANDS].index(k[1]))):
        s, rows = cells[key]
        lo, hi = cluster_ci(rows)
        flag = "excludes 0" if lo > 0 else ("includes 0" if hi > 0 else "excludes 0 (neg)")
        print(f"{key[0]:9} {key[1]:8} n={s['n']:4d} roi={s['roi']*100:+6.1f}%  "
              f"CI [{lo*100:+6.1f}%, {hi*100:+6.1f}%]  {flag}")

    print("\n§4 BREAK-EVEN ENTRY SLIPPAGE (hit - p, cents per share) — axis 5")
    for key in sorted(cells, key=lambda k: (k[0], [b[2] for b in BANDS].index(k[1]))):
        s = cells[key][0]
        print(f"{key[0]:9} {key[1]:8} p={s['px']:.3f} hit={s['hit']:.3f}  "
              f"tolerates {s['breakeven_slip_c']:+5.1f}c of worse entry before ROI=0  "
              f"(${s['notional']:,.0f} notional at risk)")

    # ---------------- counterfactuals ----------------
    total_ntl = sum(s["notional"] for s, _ in cells.values())
    total_pnl = sum(s["pnl"] for s, _ in cells.values())

    print("\n§5 ALLOCATION COUNTERFACTUALS (linear rescale of each bet's size; NOT a market-impact "
          "model — see draft §5 for the caveat)")
    print(f"  baseline: ${total_ntl:,.0f} notional, ${total_pnl:,.2f} PnL, "
          f"{total_pnl/days:+.2f} $/day over the {days:.1f}-day regime")

    def realloc(scale):
        pnl = 0.0
        ntl = 0.0
        for key, (s, _) in cells.items():
            k = scale.get(key, 1.0)
            pnl += s["pnl"] * k
            ntl += s["notional"] * k
        return ntl, pnl

    flips = {
        "(a) robust cells 4x, main <0.20 at 0.4x": {
            ("shortttr", "0.4-0.6"): 4.0, ("shortttr", "0.6-0.8"): 4.0,
            ("main", "<0.20"): 0.4},
        "(a') REC #1 as proposed: st 0.4-0.6 x2, st 0.6-0.8 x4": {
            ("shortttr", "0.4-0.6"): 2.0, ("shortttr", "0.6-0.8"): 4.0},
        "(a'') REC #1 + REC #2: as (a'), main <0.20 x0.237": {
            ("shortttr", "0.4-0.6"): 2.0, ("shortttr", "0.6-0.8"): 4.0, ("main", "<0.20"): 0.237},
        "(b) robust cells 4x only": {("shortttr", "0.4-0.6"): 4.0, ("shortttr", "0.6-0.8"): 4.0},
        "(c) main <0.20 at 0.4x only": {("main", "<0.20"): 0.4},
        "(d) robustness-weighted: cells with ex5roi<=0 zeroed, rest pro-rata to ex5roi": None,
    }
    for name, scale in flips.items():
        if name.startswith("(d)"):
            w = {}
            for key, (s, _) in cells.items():
                w[key] = max(0.0, s["ex5_roi"])
            tot = sum(w.values())
            for key in w:
                w[key] = w[key] / tot * total_ntl / cells[key][0]["notional"]
            ntl, pnl = realloc(w)
        else:
            ntl, pnl = realloc(scale)
        print(f"  {name}: ${ntl:,.0f} notional, ${pnl:,.2f} PnL, {pnl/days:+.2f} $/day, "
              f"delta {pnl-total_pnl:+.2f} vs baseline")

    print("\n§6 WHERE THE ROBUSTNESS LIVES (ex-top-5 ROI vs headline, sorted by z)")
    ranked = sorted(cells.items(), key=lambda kv: -kv[1][0]["z"])
    for (lane, band), (s, _) in ranked:
        verdict = ("ROBUST" if s["z"] >= 2 and s["ex5_keep"] >= 0.5 else
                   "tail-only" if s["ex5_keep"] < 0.5 else "weak")
        print(f"  {lane:9} {band:8} z={s['z']:+5.2f} ex5 keeps {s['ex5_keep']*100:3.0f}% "
              f"of PnL, clip ${s['clip']:.2f}  -> {verdict}  "
              f"(best market = {s['best_share']*100:5.0f}% of cell PnL)")

    # ---------------- §7 fill verdicts (C-200 stamping, 2026-10-28 onward) ----------------
    con = connect()
    f = con.execute("""
      SELECT fillStatus, COUNT(*) n, SUM(simulatedPositionSize) ntl,
             SUM(CASE WHEN status != 'open' THEN 1 ELSE 0 END) done_n,
             SUM(CASE WHEN status != 'open' THEN realizedPnl ELSE 0 END) pnl,
             AVG(entryPrice) px,
             AVG(CASE WHEN status != 'open' THEN (CASE WHEN realizedPnl > 0 THEN 1.0 ELSE 0.0 END) END) win
      FROM PaperTrade
      WHERE isDemo = 0 AND fillResolvedAt IS NOT NULL
      GROUP BY fillStatus
    """).fetchall()
    print("\n§7 FILL VERDICTS (PaperTrade.fillStatus, stamped 2026-10-28+; resolver window = OUR L2 "
          "book window, 5 min after dispatch)")
    print(f"{'verdict':10} {'legs':>5} {'notl$':>8} {'settled':>7} {'pnl$':>9} {'roi':>7} "
          f"{'px':>5} {'hit':>5}")
    tot_n = tot_ntl = tot_pnl = 0
    for r in f:
        roi = (r["pnl"] or 0) / r["ntl"] if r["ntl"] else 0.0
        print(f"{str(r['fillStatus']):10} {r['n']:5d} {r['ntl']:8.0f} {r['done_n']:7d} "
              f"{(r['pnl'] or 0):9.2f} {roi*100:+6.1f}% {r['px']:5.3f} {(r['win'] or 0):5.3f}")
        tot_n += r["n"]; tot_ntl += r["ntl"]; tot_pnl += (r["pnl"] or 0)
    un = next((r for r in f if r["fillStatus"] == "unfilled"), None)
    if un:
        print(f"  reach rate = {1 - un['n']/tot_n:.1%} of legs / "
              f"{1 - un['ntl']/tot_ntl:.1%} of notional; phantom (never-a-position) PnL = "
              f"${un['pnl'] or 0:,.2f} of ${tot_pnl:,.2f} booked")
    print("  NOTE: 'unfilled' = the maker level was NOT reachable inside our 5-minute book window. "
          "A resting bid could still fill later; 5 min is the horizon over which the copy edge exists.")

    # ---------------- §8 open book composition ----------------
    o = con.execute("""
      SELECT pt.botId, (CASE WHEN dj.ruleSetVersion >= 49 THEN 'v49+' ELSE 'pre-v49' END) era,
             COUNT(*) legs, SUM(pt.simulatedPositionSize) ntl, SUM(pt.unrealizedPnl) upnl,
             AVG((strftime('%s','now')*1000 - pt.openedAt)/86400000.0) age_d
      FROM PaperTrade pt LEFT JOIN DecisionJournal dj ON dj.id = pt.decisionJournalId
      WHERE pt.isDemo = 0 AND pt.status = 'open'
      GROUP BY 1, 2 ORDER BY 1, 2
    """).fetchall()
    print("\n§8 OPEN BOOK COMPOSITION (age in days) — the 'stranded capital' claim, re-read")
    for r in o:
        print(f"{r['botId']:13} {r['era']:8} {r['legs']:5d} legs  ${r['ntl']:8.0f}  "
              f"mark {r['upnl']:+8.2f}  age {r['age_d']:5.1f}d")

    if "--json" in ARGS:
        print(json.dumps({f"{k[0]}|{k[1]}": {kk: vv for kk, vv in v[0].items()}
                          for k, v in cells.items()}, indent=1))
    return cells


def selftest():
    """Identities that must hold before any number above is quoted."""
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        print(f"  {'PASS' if cond else 'FAIL'}  {name} {detail}")
        ok = ok and cond

    # 1. hurdle algebra: at the hurdle hit rate, net ROI is exactly zero.
    p, r = 0.314, 0.05
    hit = p * (1 + r * (1 - p))
    roi = (hit * (1 / p) - 1) - r * (1 - p)  # win pays 1/p - 1 net of entry fee
    check("hurdle p*(1+r*(1-p)) zeroes net ROI", abs(roi) < 1e-12, f"roi={roi:.2e}")
    # 2. breakeven slippage identity: ROI=0 when effective price == hit rate
    check("breakeven slip = hit - p", abs((hit - p) - (p * r * (1 - p))) < 1e-12)
    # 3. Kelly at f* leaves zero expected log growth edge (f*=0 boundary at hit=p)
    b = (1 - p) / p
    check("f*=0 when hit==p", abs((b * p - (1 - p)) / b) < 1e-12)
    # 4. band partition covers [0,1) with no gap
    covered = sum(hi - lo for lo, hi, _ in BANDS)
    check("bands partition [0,1.0001)", abs(covered - 1.0001) < 1e-9, f"covered={covered}")
    # 5. live DB is readable and the regime population is non-empty
    rows = load("resolved")
    check("regime population loads", len(rows) > 500, f"n={len(rows)}")
    print("selftest:", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in ARGS:
        sys.exit(selftest())
    main()
