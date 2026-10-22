#!/usr/bin/env python3
"""
Band-ROI report with market-clustered CIs -- the instrument behind every band claim.

WHY THIS FILE EXISTS: the 2026-10-20 profit review quoted per-band ROIs, market-clustered
CIs and an ex-top-N concentration figure, committed the write-up, and committed NO SCRIPT.
Unreproducible numbers in a review are a Lane B defect, not a stylistic choice -- the first
independent re-run disagreed on two of its three load-bearing claims and was only settled
by writing this.

COST BASIS IS THE TRAP: `PaperTrade.simulatedPositionSize` is DOLLARS at risk (~$10-13 clip),
NOT a share count. Multiplying it by `entryPrice` understates cost on cheap legs and inflated
the 0.0-0.2 band from +47.8% to +407% on the first attempt. Cost = simulatedPositionSize.

USAGE
    python3 scripts/profit-band-report.py            # default: the 2026-10-20 reproduction
    python3 scripts/profit-band-report.py --v2       # 2026-10-21 additions (calibration,
                                                     # in-band concentration, era cut, wallet null)
    python3 scripts/profit-band-report.py --all

2026-10-21 ADDITIONS (--v2), each answering a question the 10-20 draft left open:

  A. CALIBRATION. Realised hit rate vs average entry price per band. For a BUY at p the
     payoff is (1-p) win / (-p) loss, so expected ROI = hitRate - p, and BREAKEVEN HIT RATE
     IS EXACTLY p. This read is basis-independent: it does not care about clip size, cost
     basis or notional weighting, so it is the cleanest possible test of "is there edge".
     Every leg in this DB is side=BUY (12,739/12,739), so the identity holds unqualified.

  B. IN-BAND CONCENTRATION. The 10-20 review showed the BOOK is 10 events. It never asked
     whether the <0.20 band -- the one it proposed up-weighting 2.5x -- is itself 10 events.
     Per band: ex-top-N ROI, distinct markets, distinct wallets, and the share of band PnL
     from its single best wallet. If the cheap band's edge is one wallet copying one event,
     the up-weight multiplies a tail, not an edge.

  C. ERA CUT. The 10-20 draft's own watch item: STANDARD 0.4-0.6 restricted to
     ruleSetVersion >= 58, which read -1.78% on n=116. Has n grown past the 300-leg
     decision threshold?

  D. WALLET NULL. Multiple-testing correction (axis 4, never run). 226 wallets were copied.
     A screen of 226 always surfaces big per-wallet ROIs by chance. Permutation null: shuffle
     realised PnL across legs, recompute the best-wallet ROI, and report where the observed
     best sits in that distribution. This is what separates "we can pick wallets" from
     "we kept the winners".
"""
import bisect
import sqlite3
import sys
import time
import numpy as np

DB = "prisma/dev.db"
BOTS = ["STANDARD", "BANKROLL_200"]
BANDS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0001)]
ARGS = sys.argv[1:]
V2 = "--v2" in ARGS or "--all" in ARGS
V3 = "--v3" in ARGS or "--all" in ARGS


def band_name(lo, hi):
    return f"{lo:.1f}-{hi:.1f}" if hi <= 1 else "0.8-1.0"


BAND_NAMES = [band_name(lo, hi) for lo, hi in BANDS]


def band_of(p):
    for lo, hi in BANDS:
        if lo <= p < hi:
            return band_name(lo, hi)
    return None


def load(bot, days: "int | None" = 90, min_rule=None):
    """Deduped first leg per (bot|wallet|market|outcome). cost basis = dollars at risk.
    days=None means all-time."""
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    since = int((time.time() - days * 86400) * 1000) if days else 0
    sql = """
        SELECT p.id, p.walletAddress, p.marketId, p.outcome, p.entryPrice,
               p.simulatedPositionSize, p.realizedPnl, p.openedAt, p.status,
               p.openedAt AS openedMs, j.ruleSetVersion
        FROM PaperTrade p
        LEFT JOIN DecisionJournal j ON p.decisionJournalId = j.id
        WHERE p.botId=? AND p.isDemo=0 AND p.status IN ('closed','resolved')
          AND p.openedAt >= ?
          AND p.realizedPnl IS NOT NULL
    """
    params = [bot, since]
    if min_rule is not None:
        sql += " AND j.ruleSetVersion >= ?"
        params.append(min_rule)
    sql += " ORDER BY p.openedAt ASC"
    rows = con.execute(sql, params).fetchall()
    seen = set()
    out = []
    for r in rows:
        k = (r["walletAddress"], r["marketId"], r["outcome"])
        if k in seen:
            continue
        seen.add(k)
        if not r["entryPrice"] or r["entryPrice"] <= 0:
            continue
        notional = r["simulatedPositionSize"] or 0
        if notional <= 0:
            continue
        out.append({"market": r["marketId"], "band": band_of(r["entryPrice"]),
                    "px": r["entryPrice"], "notional": notional,
                    "pnl": r["realizedPnl"], "wallet": r["walletAddress"],
                    "ms": r["openedMs"], "status": r["status"],
                    "won": 1 if r["realizedPnl"] > 0 else 0})
    return out


def roi(legs):
    n = sum(l["notional"] for l in legs)
    return (sum(l["pnl"] for l in legs) / n * 100) if n else 0.0


def pnl(legs):
    return sum(l["pnl"] for l in legs)


def cluster_ci(legs, reps=2000, seed=7):
    """Market-clustered bootstrap of notional-weighted ROI."""
    if not legs:
        return (0.0, 0.0)
    by = {}
    for l in legs:
        by.setdefault(l["market"], []).append(l)
    keys = list(by)
    rng = np.random.default_rng(seed)
    out = np.empty(reps)
    for i in range(reps):
        pick = rng.integers(0, len(keys), len(keys))
        s_p = s_n = 0.0
        for j in pick:
            for l in by[keys[j]]:
                s_p += l["pnl"]
                s_n += l["notional"]
        out[i] = (s_p / s_n * 100) if s_n else 0.0
    return (float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5)))


def hit_ci(legs, reps=2000, seed=11):
    """Market-clustered bootstrap CI on hit rate, in probability points."""
    if not legs:
        return (0.0, 0.0)
    by = {}
    for l in legs:
        by.setdefault(l["market"], []).append(l)
    keys = list(by)
    rng = np.random.default_rng(seed)
    out = np.empty(reps)
    for i in range(reps):
        pick = rng.integers(0, len(keys), len(keys))
        w = n = 0
        for j in pick:
            for l in by[keys[j]]:
                w += l["won"]
                n += 1
        out[i] = 100.0 * w / n
    return (float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5)))


# ---------------------------------------------------------------- default report
def default_report():
    for bot in BOTS:
        legs = load(bot)
        if not legs:
            print(f"\n{bot}: no legs"); continue
        tot_n = sum(l["notional"] for l in legs)
        print(f"\n=== {bot}  90d deduped: {len(legs)} legs, ${tot_n:,.0f} notional, "
              f"ROI {roi(legs):+.2f}% ===")
        print(f"{'band':9} {'legs':>6} {'notional':>11} {'%ntl':>6} {'ROI%':>8} {'95% CI':>20}")
        for lo, hi in BANDS:
            name = band_name(lo, hi)
            g = [l for l in legs if l["band"] == name]
            if not g:
                continue
            n_ = sum(l["notional"] for l in g)
            lo_ci, hi_ci = cluster_ci(g)
            print(f"{name:9} {len(g):>6} {n_:>11,.0f} {100*n_/tot_n:>5.1f}% "
                  f"{roi(g):>+8.2f} [{lo_ci:>+7.2f},{hi_ci:>+7.2f}]")

    alllegs = load("STANDARD") + load("BANKROLL_200")
    alllegs.sort(key=lambda l: -l["pnl"])
    for k in (0, 1, 3, 5, 10):
        sub = alllegs[k:]
        n_ = sum(l["notional"] for l in sub)
        print(f"\nALL LANES 90d deduped, ex-top-{k}: {len(sub)} legs, "
              f"${n_:,.0f} notional, ROI {roi(sub):+.2f}% (PnL ${pnl(sub):+,.2f})")


# ---------------------------------------------------------------- A. calibration
def calibration_report():
    print("\n" + "=" * 78)
    print("A. CALIBRATION -- realised hit rate vs entry price (breakeven hit rate == p)")
    print("   expected ROI = hitRate - p. Basis-independent: no notional, no clip size.")
    print("=" * 78)
    alllegs = load("STANDARD") + load("BANKROLL_200")
    print(f"{'band':9} {'legs':>6} {'avgPx':>7} {'hit%':>7} {'be%':>7} "
          f"{'edge_pp':>8} {'95% CI (pp)':>18}")
    for name in BAND_NAMES:
        g = [l for l in alllegs if l["band"] == name]
        if not g:
            continue
        px = sum(l["px"] * l["notional"] for l in g) / sum(l["notional"] for l in g)
        hit = 100.0 * sum(l["won"] for l in g) / len(g)
        loci, hici = hit_ci(g)
        print(f"{name:9} {len(g):>6} {px:>7.3f} {hit:>6.1f}% {100*px:>6.1f}% "
              f"{hit-100*px:>+8.1f} [{loci-100*px:>+7.1f},{hici-100*px:>+7.1f}]")
    # whole book
    px = sum(l["px"] * l["notional"] for l in alllegs) / sum(l["notional"] for l in alllegs)
    hit = 100.0 * sum(l["won"] for l in alllegs) / len(alllegs)
    print(f"{'ALL':9} {len(alllegs):>6} {px:>7.3f} {hit:>6.1f}% {100*px:>6.1f}% "
          f"{hit-100*px:>+8.1f}")

    print("\n   per lane (edge_pp = hit% - avgPx, >0 means the copied wallets are calibrated):")
    for bot in BOTS:
        legs = load(bot)
        if not legs:
            continue
        px = sum(l["px"] * l["notional"] for l in legs) / sum(l["notional"] for l in legs)
        hit = 100.0 * sum(l["won"] for l in legs) / len(legs)
        print(f"   {bot:14} n={len(legs):>5}  avgPx {px:.3f}  hit {hit:.1f}%  "
              f"edge {hit-100*px:+.1f}pp  ROI {roi(legs):+.2f}%")


# --------------------------------------------------- B. concentration inside bands
def inband_concentration():
    print("\n" + "=" * 78)
    print("B. IN-BAND CONCENTRATION -- is the cheap band's edge a band or an event?")
    print("=" * 78)
    alllegs = load("STANDARD") + load("BANKROLL_200")
    print(f"{'band':9} {'legs':>5} {'mkts':>5} {'wallets':>7} {'ROI%':>8} "
          f"{'ex-5%':>8} {'ex-10%':>8} {'topW%share':>10}")
    for name in BAND_NAMES:
        g = [l for l in alllegs if l["band"] == name]
        if not g:
            continue
        s = sorted(g, key=lambda l: -l["pnl"])
        tot = pnl(g)
        byw = {}
        for l in g:
            byw[l["wallet"]] = byw.get(l["wallet"], 0.0) + l["pnl"]
        topw = max(byw.values()) if byw else 0.0
        share = 100.0 * topw / tot if abs(tot) >= 200 else float("nan")
        share_s = f"{share:>9.1f}%" if share == share else "        n/a"
        print(f"{name:9} {len(g):>5} {len({l['market'] for l in g}):>5} "
              f"{len(byw):>7} {roi(g):>+8.1f} {roi(s[5:]):>+8.1f} {roi(s[10:]):>+8.1f} "
              f"{share_s}")

    # breadth test that does not depend on PnL ordering: split each band in half by time.
    print("\n   half-split calibration (does the band's edge hold in BOTH halves by time?)")
    alllegs = [l for l in alllegs if l.get("ms")]
    ts = sorted(l["ms"] for l in alllegs)
    mid = ts[len(ts) // 2]
    print(f"   split at {time.strftime('%Y-%m-%d', time.gmtime(mid/1000))}")
    print(f"   {'band':9} {'H1 n':>5} {'H1 edge':>8} {'H2 n':>5} {'H2 edge':>8} "
          f"{'mkts':>5} {'wallets':>7}")
    for name in BAND_NAMES:
        g = [l for l in alllegs if l["band"] == name]
        if not g:
            continue
        cells = []
        for half in (0, 1):
            h = [l for l in g if (0 if l["ms"] < mid else 1) == half]
            if len(h) < 10:
                cells.append((len(h), None))
                continue
            px = sum(l["px"] * l["notional"] for l in h) / sum(l["notional"] for l in h)
            hit = 100.0 * sum(l["won"] for l in h) / len(h)
            cells.append((len(h), hit - 100 * px))
        f = lambda v: "    n/a" if v is None else f"{v:>+7.1f}"
        print(f"   {name:9} {cells[0][0]:>5} {f(cells[0][1])} {cells[1][0]:>5} "
              f"{f(cells[1][1])} {len({l['market'] for l in g}):>5} "
              f"{len({l['wallet'] for l in g}):>7}")

    print("\n   per band, the single biggest market by PnL and its share of band PnL:")
    for name in BAND_NAMES:
        g = [l for l in alllegs if l["band"] == name]
        if not g:
            continue
        bym = {}
        for l in g:
            bym.setdefault(l["market"], []).append(l)
        mk, ml = max(bym.items(), key=lambda kv: pnl(kv[1]))
        tot = pnl(g)
        print(f"   {name:9} {pnl(ml):>+9.2f} / {tot:>+9.2f} "
              f"({100*pnl(ml)/tot if tot else 0:>5.1f}%)  {len(ml)} legs  {mk[:56]}")


# ---------------------------------------------------------------- C. era cut
def era_cut():
    print("\n" + "=" * 78)
    print("C. ERA CUT -- has the dead-zone loss reproduced on the v58+ era yet?")
    print("   decision threshold from 2026-10-20: n>=300 legs on ruleSetVersion>=58")
    print("=" * 78)
    for min_rule in (58, 59, 60, 62):
        for bot in BOTS:
            legs = load(bot, days=90, min_rule=min_rule)
            if not legs:
                continue
            dz = [l for l in legs if l["band"] == "0.4-0.6"]
            if not dz:
                continue
            loci, hici = cluster_ci(dz)
            share = 100.0 * sum(l["notional"] for l in dz) / sum(l["notional"] for l in legs)
            print(f"   v{min_rule}+ {bot:14} deadzone n={len(dz):>4} "
                  f"ROI {roi(dz):>+7.2f}% [{loci:>+7.2f},{hici:>+7.2f}]  "
                  f"= {share:.1f}% of lane ntl   lane total n={len(legs)}")


# ---------------------------------------------------------------- D. wallet null
def wallet_null(reps=2000, seed=23):
    """Multiple-testing correction, done as an out-of-sample persistence test.

    FIRST ATTEMPT FAILED AND IS KEPT HERE AS A WARNING: I built a permutation null on
    per-wallet ROI (shuffle PnL across legs, recompute max-wallet ROI). It returned
    p95 == p99 == the observed max on every rep. Cause: ROI is a ratio whose denominator is
    the wallet's notional, so the max is always taken by the wallet with the smallest book
    and any positive PnL assigned to it. The statistic is degenerate and I refuse to quote it.

    The question axis 4 actually asks is: does the ranking *at selection time* predict the
    future? So: split the 90d book at the midpoint, rank wallets by first-half ROI, and
    measure those same wallets' second-half ROI. A real wallet edge persists; a screened-out
    sample of 226 does not. No ratio-null required -- this is the selection test itself.
    """
    print("\n" + "=" * 78)
    print("D. WALLET PERSISTENCE -- does first-half wallet rank predict second half?")
    print("=" * 78)
    alllegs = [l for l in (load("STANDARD") + load("BANKROLL_200")) if l.get("ms")]
    if not alllegs:
        print("   no timestamped legs"); return
    ts = sorted(l["ms"] for l in alllegs)
    mid = ts[len(ts) // 2]
    for l in alllegs:
        l["half"] = 0 if l["ms"] < mid else 1
    h0 = [l for l in alllegs if l["half"] == 0]
    h1 = [l for l in alllegs if l["half"] == 1]
    print(f"   split at {time.strftime('%Y-%m-%d', time.gmtime(mid/1000))}: "
          f"H1 {len(h0)} legs, H2 {len(h1)} legs")

    def by_wallet(legs, min_legs):
        d = {}
        for l in legs:
            d.setdefault(l["wallet"], []).append(l)
        return {w: ls for w, ls in d.items()
                if len(ls) >= min_legs and sum(x["notional"] for x in ls) > 0}

    w0 = by_wallet(h0, 4)
    w1 = by_wallet(h1, 3)
    both = sorted(set(w0) & set(w1))
    print(f"   wallets with >=4 H1 legs and >=3 H2 legs: {len(both)}")
    if len(both) < 8:
        print("   too few overlapping wallets for a persistence read"); return

    ranked = sorted(both, key=lambda w: -roi(w0[w]))
    n = len(ranked)
    q = max(1, n // 3)
    top, bot = ranked[:q], ranked[-q:]
    print(f"\n   H1 top third (n={q}): H1 ROI {roi([l for w in top for l in w0[w]]):+.1f}%  "
          f"-> H2 ROI {roi([l for w in top for l in w1[w]]):+.1f}%")
    print(f"   H1 bottom third (n={q}): H1 ROI {roi([l for w in bot for l in w0[w]]):+.1f}%  "
          f"-> H2 ROI {roi([l for w in bot for l in w1[w]]):+.1f}%")
    print(f"   all overlap (n={n}):    H1 ROI {roi([l for w in both for l in w0[w]]):+.1f}%  "
          f"-> H2 ROI {roi([l for w in both for l in w1[w]]):+.1f}%")
    # rank correlation
    r0 = [roi(w0[w]) for w in both]
    r1 = [roi(w1[w]) for w in both]
    rho = float(np.corrcoef(np.argsort(np.argsort(r0)), np.argsort(np.argsort(r1)))[0, 1])
    print(f"   Spearman rank correlation H1 vs H2 wallet ROI: {rho:+.3f} (n={n})")

    # permutation null on the H1-top -> H2 spread
    rng = np.random.default_rng(seed)
    obs = roi([l for w in top for l in w1[w]]) - roi([l for w in bot for l in w1[w]])
    null = np.empty(reps)
    arr = ranked[:]
    for i in range(reps):
        rng.shuffle(arr)
        t, b = arr[:q], arr[-q:]
        null[i] = roi([l for w in t for l in w1[w]]) - roi([l for w in b for l in w1[w]])
    p = float((null >= obs).mean())
    print(f"\n   H2 spread (H1-top minus H1-bottom): {obs:+.1f}pp  "
          f"null p95 {np.percentile(null,95):+.1f}pp  -> p = {p:.3f}")


def recency_and_basis():
    """E. Is the dead-zone loss still happening, and is 'edge' resolution or early exit?"""
    print("\n" + "=" * 78)
    print("E. RECENCY + PnL BASIS -- does the dead zone still lose, and where does PnL come from?")
    print("=" * 78)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    print(f"{'window':8} {'band':9} {'legs':>5} {'notional':>10} {'ROI%':>8}")
    for days in (90, 30, 14, 7):
        for name in BAND_NAMES:
            legs = [l for l in load("STANDARD", days=days) if l["band"] == name]
            if len(legs) < 5:
                continue
            print(f"{str(days)+'d':8} {name:9} {len(legs):>5} "
                  f"{sum(l['notional'] for l in legs):>10,.0f} {roi(legs):>+8.1f}")
        print()

    print("   PnL basis: how much comes from early exits ('closed') vs settlement ('resolved')")
    since = int((time.time() - 90 * 86400) * 1000)
    rows = con.execute(
        """SELECT botId, status, COUNT(*) n, SUM(simulatedPositionSize) ntl,
                  SUM(realizedPnl) p
           FROM PaperTrade
           WHERE isDemo=0 AND status IN ('closed','resolved') AND realizedPnl IS NOT NULL
             AND openedAt >= ?
           GROUP BY 1,2 ORDER BY 1,2""", (since,)).fetchall()
    seen = set()
    agg = {}
    # dedupe consistently with load(): first leg per bot|wallet|market|outcome
    for r in con.execute(
        """SELECT botId, status, walletAddress, marketId, outcome, entryPrice,
                  simulatedPositionSize, realizedPnl
           FROM PaperTrade
           WHERE isDemo=0 AND status IN ('closed','resolved') AND realizedPnl IS NOT NULL
             AND openedAt >= ? ORDER BY openedAt ASC""", (since,)):
        k = (r["botId"], r["walletAddress"], r["marketId"], r["outcome"])
        if k in seen or not r["entryPrice"] or r["entryPrice"] <= 0:
            continue
        seen.add(k)
        a = agg.setdefault((r["botId"], r["status"]), [0, 0.0, 0.0])
        a[0] += 1; a[1] += r["simulatedPositionSize"] or 0; a[2] += r["realizedPnl"]
    for (bot, st), (n_, ntl, p) in sorted(agg.items()):
        print(f"   {bot:14} {st:9} n={n_:>5} ${ntl:>9,.0f} PnL ${p:>+9,.2f} "
              f"ROI {100*p/ntl if ntl else 0:>+7.2f}%")

    # Reconciliation: does the hit-rate read and the notional-weighted ROI agree?
    # EXACT identity: per leg ROI = (won - p)/p on the dollars-at-risk basis (verified against
    # raw rows: a resolved win has realizedPnl == size*(1-p)/p to the cent). Averaging that is
    # the equal-weight ROI. The tempting shortcut (hitRate - meanPx)/meanPx is NOT exact --
    # it replaces E[1/p] with 1/E[p], and by Jensen those differ whenever p varies. I used the
    # shortcut in the first run and it printed -0.64% against a true +7.47%. It is removed.
    print("\n   reconciliation, resolved legs only (exact equal-weight ROI = mean((won-p)/p)):")
    for bot in BOTS:
        con2 = sqlite3.connect(DB)
        con2.row_factory = sqlite3.Row
        since = int((time.time() - 90 * 86400) * 1000)
        seen2 = set()
        legs = []
        for r in con2.execute(
            """SELECT walletAddress, marketId, outcome, entryPrice, simulatedPositionSize,
                      realizedPnl FROM PaperTrade
               WHERE botId=? AND isDemo=0 AND status='resolved' AND realizedPnl IS NOT NULL
                 AND openedAt >= ? ORDER BY openedAt ASC""", (bot, since)):
            k = (r["walletAddress"], r["marketId"], r["outcome"])
            if k in seen2 or not r["entryPrice"] or r["entryPrice"] <= 0:
                continue
            seen2.add(k)
            legs.append((r["entryPrice"], r["simulatedPositionSize"] or 0, r["realizedPnl"]))
        if not legs:
            continue
        n_ = len(legs)
        pxs = [x[0] for x in legs]
        hits = [1 if x[2] > 0 else 0 for x in legs]
        eq_roi = 100 * sum((1 - x[0]) / x[0] if x[2] > 0 else -1 for x in legs) / n_
        nw_roi = 100 * sum(x[2] for x in legs) / sum(x[1] for x in legs)
        print(f"   {bot:14} n={n_:>5} hit {100*sum(hits)/n_:.1f}% avgPx {sum(pxs)/n_:.3f} "
              f"| equal-weight ROI {eq_roi:+.2f}%   notional-weighted {nw_roi:+.2f}%")


def calibration_by_window():
    """F. Does the dead zone's CALIBRATION loss persist, even where its ROI has gone flat?

    This resolves the contradiction in E: 90d 0.4-0.6 ROI is -6.9% but the 30d cut is -0.7%.
    ROI on a few dozen legs is noise-dominated; the hit-rate edge (hit% - avgPx) is a tighter
    statistic. If the calibration loss is still negative at 30d, the band is still broken and
    the flat 30d ROI is small-sample luck. If it is not, the band genuinely healed.
    """
    print("\n" + "=" * 78)
    print("F. CALIBRATION BY WINDOW -- is the dead zone still miscalibrated, or has it healed?")
    print("=" * 78)
    for bot in BOTS:
        print(f"\n   {bot}")
        print(f"   {'band':9} " + " ".join(f"{str(d)+'d':>18}" for d in (90, 60, 30)))
        for name in BAND_NAMES:
            cells = []
            for days in (90, 60, 30):
                g = [l for l in load(bot, days=days) if l["band"] == name]
                if len(g) < 10:
                    cells.append(f"{'n/a':>18}")
                    continue
                px = sum(l["px"] * l["notional"] for l in g) / sum(l["notional"] for l in g)
                hit = 100.0 * sum(l["won"] for l in g) / len(g)
                cells.append(f"{hit-100*px:>+7.1f}pp n={len(g):<7}")
            print(f"   {name:9} " + " ".join(cells))


def lane_anatomy():
    """G. Per-lane: what the lane earns WITHOUT its cheap band, and is the cheap edge broad?

    The question that decides capital allocation: each lane's profit is a sum over bands, so
    'remove the band that pays and see what is left' is the honest measure of whether the lane
    has a portfolio edge or one convexity. Also splits closed vs resolved inside the dead zone
    to test whether an exit rule is masking a miscalibrated band.
    """
    print("\n" + "=" * 78)
    print("G. LANE ANATOMY -- profit ex-cheap-band, and whether exits mask a bad band")
    print("=" * 78)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    for bot in BOTS:
        legs = load(bot)
        if not legs:
            continue
        tot_p = pnl(legs)
        tot_n = sum(l["notional"] for l in legs)
        cheap = [l for l in legs if l["band"] == "0.0-0.2"]
        rest = [l for l in legs if l["band"] != "0.0-0.2"]
        cp, cn = pnl(cheap), sum(l["notional"] for l in cheap)
        print(f"\n   {bot}: total ${tot_p:+,.2f} on ${tot_n:,.0f} = {100*tot_p/tot_n:+.2f}%")
        print(f"     cheap <0.20 : ${cp:>+9,.2f} on ${cn:>8,.0f} ({100*cn/tot_n:>4.1f}% of ntl) "
              f"= {100*cp/cn if cn else 0:+.2f}%")
        print(f"     everything else: ${tot_p-cp:>+9,.2f} on ${tot_n-cn:>8,.0f} "
              f"({100*(tot_n-cn)/tot_n:>4.1f}% of ntl) = {roi(rest):+.2f}%")
        print(f"     -> share of lane profit produced by <0.20: "
              f"{100*cp/tot_p if tot_p else float('nan'):.0f}%")

        # cheap-band breadth inside this lane
        s = sorted(cheap, key=lambda l: -l["pnl"])
        byw = {}
        for l in cheap:
            byw[l["wallet"]] = byw.get(l["wallet"], 0.0) + l["pnl"]
        print(f"     cheap band breadth: {len({l['market'] for l in cheap})} markets, "
              f"{len(byw)} wallets, ex-5-leg ROI {roi(s[5:]):+.1f}%, ex-10 {roi(s[10:]):+.1f}%")
        if byw and abs(cp) >= 100:
            tw, twp = max(byw.items(), key=lambda kv: kv[1])
            print(f"       top wallet {tw[:12]}… = {100*twp/cp:+.0f}% of cheap PnL "
                  f"({sum(1 for l in cheap if l['wallet']==tw)} legs)")

    # the exit-masking test
    print("\n   dead-zone 0.4-0.6 PnL split: is an exit rule hiding a miscalibrated band?")
    since = int((time.time() - 90 * 86400) * 1000)
    print(f"   {'lane':14} {'status':9} {'legs':>5} {'notional':>9} {'PnL':>10} {'ROI%':>8}")
    for bot in BOTS:
        for st in ("closed", "resolved"):
            seen = set()
            ls = []
            for r in con.execute(
                """SELECT walletAddress, marketId, outcome, entryPrice,
                          simulatedPositionSize, realizedPnl FROM PaperTrade
                   WHERE botId=? AND isDemo=0 AND status=? AND realizedPnl IS NOT NULL
                     AND entryPrice>=0.4 AND entryPrice<0.6 AND openedAt>=?
                   ORDER BY openedAt ASC""", (bot, st, since)):
                k = (r["walletAddress"], r["marketId"], r["outcome"])
                if k in seen or not r["entryPrice"] or r["entryPrice"] <= 0:
                    continue
                seen.add(k)
                ls.append({"market": r["marketId"], "px": r["entryPrice"],
                           "notional": r["simulatedPositionSize"] or 0,
                           "pnl": r["realizedPnl"], "band": "0.4-0.6",
                           "wallet": r["walletAddress"]})
            if not ls:
                continue
            print(f"   {bot:14} {st:9} {len(ls):>5} "
                  f"{sum(l['notional'] for l in ls):>9,.0f} "
                  f"{pnl(ls):>+10,.2f} {roi(ls):>+8.2f}")


def v54_experiment():
    """H. v54 (2026-09-16) moved C-200 size out of the dead zone into the long-shot band.

    This is the one band doctrine in the system that is ALREADY APPLIED and therefore
    measurable rather than hypothetical: c200BandSizeFactor long-shot 1.25 / dead zone 0.50.
    Did the lever move the band mix, and did the lane's ROI survive it? If yes, the doctrine
    is production-verified and extending the SAME factor set to STANDARD is a copy, not an
    invention -- which is a far stronger proposal than an invented x2.5.
    """
    print("\n" + "=" * 78)
    print("H. v54 VERIFICATION + the STANDARD shadow under the SAME factor set")
    print("   v54 created 2026-09-16; split legs at that date.")
    print("=" * 78)
    cut = int(time.mktime(time.strptime("2026-09-16", "%Y-%m-%d")) * 1000)
    for bot in BOTS:
        print(f"\n   {bot} -- band notional share and ROI, pre vs post v54:")
        print(f"   {'band':9} {'pre n':>6} {'pre %ntl':>9} {'pre ROI':>8} "
              f"{'post n':>7} {'post %ntl':>10} {'post ROI':>9}")
        legs = load(bot, days=None)
        pre = [l for l in legs if l["ms"] < cut]
        post = [l for l in legs if l["ms"] >= cut]
        for name in BAND_NAMES:
            a = [l for l in pre if l["band"] == name]
            b = [l for l in post if l["band"] == name]
            an = sum(l["notional"] for l in pre) or 1
            bn = sum(l["notional"] for l in post) or 1
            print(f"   {name:9} {len(a):>6} {100*sum(l['notional'] for l in a)/an:>8.1f}% "
                  f"{roi(a):>+8.1f} {len(b):>7} {100*sum(l['notional'] for l in b)/bn:>9.1f}% "
                  f"{roi(b):>+9.1f}")
        print(f"   {'TOTAL':9} {len(pre):>6} {'':>9} {roi(pre):>+8.1f} "
              f"{len(post):>7} {'':>10} {roi(post):>+9.1f}   "
              f"(notional ${sum(l['notional'] for l in pre):,.0f} -> "
              f"${sum(l['notional'] for l in post):,.0f})")

    # The shadow: STANDARD's own trailing-90d book under C-200's applied v54 factors,
    # plus the v51 dead-zone rail. Clip scaling only -- a leg's ROI is held constant, which
    # ignores capacity and fill effects. That assumption is the weakest part and is stated.
    print("\n   STANDARD 90d shadow, clip-scaled by the applied C-200 band map")
    print("   (assumption: scaling a clip does not change that leg's ROI; ignores fill)")
    legs = load("STANDARD")
    base_p = pnl(legs)
    base_n = sum(l["notional"] for l in legs)
    print(f"   as traded:                        ${base_p:>+9,.2f} / ${base_n:>9,.0f} "
          f"= {100*base_p/base_n:+.2f}%")
    for label, factors in (
        ("deadzone x0.50 (v51 rail)", {"0.4-0.6": 0.50}),
        ("longshot x1.25 (v54 rail)", {"0.0-0.2": 1.25}),
        ("v54 set on STANDARD",       {"0.0-0.2": 1.25, "0.4-0.6": 0.50}),
        ("v54 + skip deadzone",       {"0.0-0.2": 1.25, "0.4-0.6": 0.00}),
        ("v54 + skip + 0.6-0.8 x0.5", {"0.0-0.2": 1.25, "0.4-0.6": 0.00, "0.6-0.8": 0.50}),
    ):
        nn = pp = 0.0
        for l in legs:
            f = factors.get(l["band"], 1.0)
            nn += l["notional"] * f
            pp += l["pnl"] * f
        print(f"   {label:33} ${pp:>+9,.2f} / ${nn:>9,.0f} = {100*pp/nn:+.2f}%  "
              f"({100*nn/base_n:+.0f}% notional)")


def spread_haircut():
    """I. The paper engine crosses NO spread and pays NO fee (src/lib/copy-cost.ts:34).

    So every ROI in this review is gross. Fees on Polymarket peak near p=0.50; spread as a
    fraction of STAKE peaks at low p. The two costs rank the bands in opposite directions,
    which is exactly why this must be measured rather than asserted. MarketSnapshot carries
    bestBid/bestAsk, so price the cost that actually exists: crossing the quoted spread.

    Shares = notional / px, so buying at the ask costs (spread/2) per share = half the quoted
    spread. Reported net of half-spread (a taker at mid) and of the full spread (worst case).
    """
    print("\n" + "=" * 78)
    print("I. SPREAD COST -- the paper book crosses no spread, so price the one cost it has")
    print("=" * 78)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    alllegs = load("STANDARD") + load("BANKROLL_200")
    priced = 0
    for l in alllegs:
        l["spread"] = None
        r = con.execute(
            """SELECT bestBid, bestAsk, (bestAsk-bestBid) sp FROM MarketSnapshot
               WHERE marketId=? AND collectedAt <= ? AND bestBid IS NOT NULL
                 AND bestAsk IS NOT NULL AND bestAsk > bestBid
               ORDER BY collectedAt DESC LIMIT 1""", (l["market"], l["ms"] + 6 * 3600 * 1000)
        ).fetchone()
        if r and r["sp"] and r["sp"] > 0:
            l["spread"] = float(r["sp"])
            priced += 1
    print(f"   legs with a usable recorded book within 6h of entry: {priced}/{len(alllegs)} "
          f"({100*priced/len(alllegs):.0f}%)")
    print(f"\n   {'band':9} {'legs':>5} {'meanSpr':>7} {'spr%stake':>9} "
          f"{'gross ROI':>10} {'net(half)':>10} {'CI half':>18} {'net(full)':>10}")
    for name in BAND_NAMES:
        g = [l for l in alllegs if l["band"] == name and l["spread"]]
        if not g:
            continue
        n_ = sum(l["notional"] for l in g)
        mean_spr = sum(l["spread"] * l["notional"] for l in g) / n_
        gross = roi(g)
        half_cost = [(l["notional"] / l["px"]) * (l["spread"] / 2) for l in g]
        full_cost = [(l["notional"] / l["px"]) * l["spread"] for l in g]
        half = sum(l["pnl"] - c for l, c in zip(g, half_cost))
        full = sum(l["pnl"] - c for l, c in zip(g, full_cost))
        # notional-weighted spread as % of capital at risk
        spr_pct = 100 * sum(c for c in half_cost) / n_
        net_legs = [dict(l, pnl=l["pnl"] - c) for l, c in zip(g, half_cost)]
        loci, hici = cluster_ci(net_legs)
        print(f"   {name:9} {len(g):>5} {mean_spr:>7.3f} {spr_pct:>8.2f}% "
              f"{gross:>+9.1f}% {100*half/n_:>+9.1f}% [{loci:>+7.1f},{hici:>+7.1f}] "
              f"{100*full/n_:>+9.1f}%")

    # how many legs does the spread make unprofitable at half-spread? (marginal legs)
    print("\n   legs whose ENTIRE profit is smaller than the spread they would have paid:")
    for name in BAND_NAMES:
        g = [l for l in alllegs if l["band"] == name and l["spread"]]
        if not g:
            continue
        cost = [(l["notional"] / l["px"]) * (l["spread"] / 2) for l in g]
        killed = sum(1 for l, c in zip(g, cost) if l["pnl"] > 0 and l["pnl"] < c)
        tot_c = sum(cost)
        print(f"   {name:9} {killed:>5} of {len(g):<5} winners, "
              f"total half-spread cost ${tot_c:>8,.0f}")


def spread_by_window():
    """J. Net-of-spread ROI with clustered CIs by window, per band.

    With the dead zone now hard-skipped on BOTH lanes (v62 C-200, v63 STANDARD), the open
    question moved up the book: 0.6-0.8 and 0.8-1.0 are 30.5% of notional that reads +3.1%
    and -0.0% GROSS, i.e. +1.4% and -1.0% net of half-spread. Those are zeros, not losses --
    so no cut is justified on the 90d cut. But 0.8-1.0's calibration collapses from +0.1pp in
    H1 to -6.8pp in H2, on a 34-day hold. If the recent window is CI-negative net, that is a
    fresh finding; if it is not, this stays a measurement and nothing ships.
    """
    print("\n" + "=" * 78)
    print("J. NET-OF-SPREAD BY WINDOW -- has the upper book turned negative recently?")
    print("=" * 78)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cache: dict = {}

    def spr(market, ms):
        key = (market, ms // 3600000)
        if key in cache:
            return cache[key]
        r = con.execute(
            """SELECT (bestAsk-bestBid) sp FROM MarketSnapshot
               WHERE marketId=? AND collectedAt <= ? AND bestBid IS NOT NULL
                 AND bestAsk IS NOT NULL AND bestAsk > bestBid
               ORDER BY collectedAt DESC LIMIT 1""", (market, ms + 6 * 3600 * 1000)
        ).fetchone()
        v = float(r["sp"]) if r and r["sp"] and r["sp"] > 0 else None
        cache[key] = v
        return v

    for days in (90, 45, 30):
        legs = load("STANDARD", days=days) + load("BANKROLL_200", days=days)
        print(f"\n   trailing {days}d  (net of HALF the quoted spread)")
        print(f"   {'band':9} {'legs':>5} {'notional':>9} {'%ntl':>6} {'gross':>8} "
              f"{'net':>8} {'95% CI net':>18}")
        tot_n = sum(l["notional"] for l in legs) or 1
        for name in BAND_NAMES:
            g = [l for l in legs if l["band"] == name]
            if not g:
                continue
            net_legs = []
            for l in g:
                s = spr(l["market"], l["ms"])
                c = (l["notional"] / l["px"]) * (s / 2) if s else 0.0
                net_legs.append(dict(l, pnl=l["pnl"] - c))
            n_ = sum(l["notional"] for l in g)
            loci, hici = cluster_ci(net_legs)
            print(f"   {name:9} {len(g):>5} {n_:>9,.0f} {100*n_/tot_n:>5.1f}% "
                  f"{roi(g):>+7.1f}% {roi(net_legs):>+7.1f}% "
                  f"[{loci:>+7.1f},{hici:>+7.1f}]")


def lane_duplication():
    """K. STANDARD vs C-200 on the SAME bet -- is STANDARD a redundant, worse-fidelity copy?

    The dedupe key is per-lane (bot|wallet|market|outcome), so both lanes independently copy
    the same wallet signal. If their books overlap heavily, STANDARD is not a second strategy:
    it is a second implementation of the same signal with different rails. The paired
    comparison on identical bets is then the cleanest possible execution measure -- it holds
    the market and the signal fixed and varies only the lane.
    """
    print("\n" + "=" * 78)
    print("K. LANE DUPLICATION -- same bet, two lanes")
    print("=" * 78)
    std = load("STANDARD")
    c200 = load("BANKROLL_200")
    key = lambda l: (l["wallet"], l["market"], l["subject"] if "subject" in l else l["px"])
    # match on wallet+market only; outcome is folded in via market+wallet in practice
    s_by = {}
    for l in std:
        s_by.setdefault((l["wallet"], l["market"]), []).append(l)
    pairs = []
    for c in c200:
        for s in s_by.get((c["wallet"], c["market"]), []):
            pairs.append((c, s))
    print(f"   STANDARD legs {len(std)}, C-200 legs {len(c200)}")
    print(f"   matched (wallet, market) pairs: {len(pairs)}  "
          f"= {100*len(pairs)/max(1,len(c200)):.0f}% of C-200 legs have a STANDARD twin")
    if not pairs:
        print("   no overlap"); return
    c_p = sum(c["pnl"] for c, s in pairs); c_n = sum(c["notional"] for c, s in pairs)
    s_p = sum(s["pnl"] for c, s in pairs); s_n = sum(s["notional"] for c, s in pairs)
    print(f"   on those SAME bets:  C-200 ${c_p:>+9,.2f} on ${c_n:>8,.0f} = "
          f"{100*c_p/c_n:+.1f}%")
    print(f"                        STANDARD ${s_p:>+9,.2f} on ${s_n:>8,.0f} = "
          f"{100*s_p/s_n:+.1f}%")
    print(f"   execution gap: {100*c_p/c_n - 100*s_p/s_n:+.1f}pp per dollar deployed "
          f"(same wallet, same market)")
    # Is the price gap a latency effect (later entry) or a different-trade effect?
    # Both lanes book entry at their OWN detected price (checked: STANDARD -0.22c vs detected,
    # C-200 -1.33c vs detected), so a price gap on a matched market means either (a) STANDARD
    # enters later, or (b) it copies a different ObservedTrade in the same market. Only (a) is
    # a fixable latency cost, so it must be separated rather than asserted.
    dts, dpx = [], []
    for c, s in pairs:
        dts.append((s["ms"] - c["ms"]) / 3_600_000.0)
        dpx.append(s["px"] - c["px"])
    if dts:
        med_t = sorted(dts)[len(dts) // 2]
        med_p = sorted(dpx)[len(dpx) // 2]
        later = sum(1 for d in dts if d > 0.5)
        big = sum(1 for d in dpx if abs(d) > 0.02)
        print(f"\n   STANDARD minus C-200 on matched markets: median time delta "
              f"{med_t:+.1f}h, median price delta {med_p*100:+.1f}c, "
              f"MEAN {100*sum(dpx)/len(dpx):+.1f}c")
        print(f"   pairs with |price delta| > 2c: {big}/{len(dpx)} "
              f"({100*big/len(dpx):.0f}%) -- the mean is carried by this tail, not the bulk")
        print(f"   STANDARD enters LATER by >30min on {later}/{len(dts)} "
              f"({100*later/len(dts):.0f}%) of them")
        if dts and len(dts) > 5:
            rho = float(np.corrcoef(np.argsort(np.argsort(dts)),
                                    np.argsort(np.argsort(dpx)))[0, 1])
            verdict = ("latency story holds" if rho > 0.2 else
                       "NOT a latency story: lanes copy different trades in the same market")
            print(f"   rank corr(time delta, price delta) = {rho:+.3f} -> {verdict}")
    def stat(sel, label):
        if not sel:
            print(f"     {label:22} (none)"); return
        n_ = sum(l["notional"] for l in sel)
        p_ = sum(l["pnl"] for l in sel)
        px_ = sum(l["px"] * l["notional"] for l in sel) / n_
        print(f"     {label:22} n={len(sel):>4} ${n_:>7,.0f} PnL ${p_:>+8,.2f} "
              f"ROI {100*p_/n_:>+7.1f}%  avgPx {px_:.4f}")

    for lane, idx in (("C-200", 0), ("STANDARD", 1)):
        sel = [p[idx] for p in pairs]
        print(f"\n   {lane} on the matched bets:")
        stat(sel, "all")
        stat([l for l in sel if l.get("status") == "closed"], "exited early")
        stat([l for l in sel if l.get("status") == "resolved"], "held to settlement")


def open_book():
    """L. Open-book capital-days -- reproduced here rather than carried from a prior draft.

    A held position costs capital every day whether or not it ever resolves, so the relevant
    comparison is capital-days in the OPEN book vs capital-days the entire FINISHED history
    consumed to earn all of its profit. Carrying this number across reviews without recomputing
    it is how a stale figure becomes a fact, so it is computed from the DB on every run.
    """
    print("\n" + "=" * 78)
    print("L. OPEN BOOK -- stranded capital-days, recomputed")
    print("=" * 78)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    now = time.time() * 1000
    for bot in BOTS + ["ALL"]:
        where = "" if bot == "ALL" else " AND botId=?"
        params = () if bot == "ALL" else (bot,)
        rows = con.execute(
            f"""SELECT walletAddress, marketId, outcome, entryPrice, simulatedPositionSize,
                       unrealizedPnl, openedAt
                FROM PaperTrade WHERE isDemo=0 AND status='open'{where}""", params).fetchall()
        seen = set()
        cd = ntl = mtm = 0.0
        n = 0
        by_band = {}
        for r in rows:
            k = (r["walletAddress"], r["marketId"], r["outcome"])
            if k in seen or not r["entryPrice"] or r["entryPrice"] <= 0:
                continue
            seen.add(k)
            size = r["simulatedPositionSize"] or 0
            if size <= 0:
                continue
            age = max(0.0, (now - r["openedAt"]) / 86_400_000.0)
            n += 1
            ntl += size
            mtm += r["unrealizedPnl"] or 0
            cd += size * age
            b = band_of(r["entryPrice"])
            d = by_band.setdefault(b, [0, 0.0, 0.0, 0.0, 0.0])
            d[0] += 1; d[1] += size; d[2] += r["unrealizedPnl"] or 0; d[3] += size * age
            # a held BUY at p can still return at most (1-p)/p on its stake
            d[4] += size * (1 - r["entryPrice"]) / r["entryPrice"]
        if not n:
            continue
        print(f"\n   {bot}: {n} open bets (deduped), ${ntl:,.0f} notional, "
              f"MTM ${mtm:+,.2f}, weighted age {cd/ntl:.1f}d, capital-days {cd:,.0f}")
        for b in BAND_NAMES:
            if b not in by_band:
                continue
            d = by_band[b]
            print(f"     {b:9} n={d[0]:>4} ${d[1]:>8,.0f} MTM ${d[2]:>+8,.2f} "
                  f"capdays {d[3]:>9,.0f} ({100*d[3]/cd:>4.1f}% of stranded) "
                  f"max upside left ${d[4]:>7,.0f}")

    fin = 0.0
    fn = 0
    seen = set()
    for r in con.execute(
        """SELECT botId, walletAddress, marketId, outcome, simulatedPositionSize, openedAt,
                  closedAt, resolvedAt
           FROM PaperTrade WHERE isDemo=0 AND status IN ('closed','resolved')"""):
        k = (r["botId"], r["walletAddress"], r["marketId"], r["outcome"])
        if k in seen or not r["simulatedPositionSize"]:
            continue
        seen.add(k)
        end = r["resolvedAt"] or r["closedAt"] or r["openedAt"]
        days = max(0.0, (end - r["openedAt"]) / 86_400_000.0)
        fin += r["simulatedPositionSize"] * days
        fn += 1
    print(f"\n   finished history: {fn} bets, capital-days {fin:,.0f} "
          f"(all-time; deduped per lane)")


# =========================================================== 2026-10-22 additions
# The three questions the 10-21 draft left open, each answerable from this DB:
#   M. RICH-TAIL DECOMPOSITION -- is the >=0.80 leak live flow or legacy stock?
#   N. DOES SIZE SEE THE BAND? -- is the clip a function of the band it is buying?
#   O. SIZING SHADOW -- what would a band map have paid on the legs we took?
#   P. 168h STOP REPLAY -- the gate the 10-21 draft set for itself and never ran.

def rich_band(p):
    if p < 0.20:
        return "0.00-0.20"
    if p < 0.40:
        return "0.20-0.40"
    if p < 0.60:
        return "0.40-0.60"
    if p < 0.80:
        return "0.60-0.80"
    if p < 0.95:
        return "0.80-0.95"
    return "0.95-1.00"


RICH_BANDS = ["0.00-0.20", "0.20-0.40", "0.40-0.60", "0.60-0.80", "0.80-0.95", "0.95-1.00"]


def rich_tail():
    """M. The 0.80-1.00 band is not one thing: 0.80-0.95 still has (1-p)/p upside, >=0.95 has none.
    Splitting them decides whether the last draft's 'stranded capital' framing was an exit-rule
    problem or a legacy-stock problem that maxEntryPrice=0.85/0.88 has already stopped."""
    print("\n" + "=" * 78)
    print("M. RICH-TAIL DECOMPOSITION -- 0.80-0.95 vs >=0.95, realised and open")
    print("=" * 78)
    print(f"   {'band':10} {'n':>5} {'stake':>9} {'pnl':>9} {'roi%':>7} "
          f"{'CI95':>18} {'%notl':>6}")
    tot_n = tot_p = 0.0
    for bot in BOTS:
        legs = load(bot, days=None)
        if not legs:
            continue
        print(f"\n   {bot} (all-time, deduped, cost=dollars at risk)")
        by = {}
        for l in legs:
            b = rich_band(l["px"])
            d = by.setdefault(b, [0, 0.0, 0.0])
            d[0] += 1
            d[1] += l["notional"]
            d[2] += l["pnl"]
        grand_n = sum(d[1] for d in by.values())
        for b in RICH_BANDS:
            if b not in by:
                continue
            d = by[b]
            sub = [l for l in legs if rich_band(l["px"]) == b]
            lo, hi = cluster_ci(sub)
            print(f"   {b:10} {d[0]:>5} {d[1]:>9,.0f} {d[2]:>+9,.0f} "
                  f"{100*d[2]/d[1]:>+6.1f}% [{lo:>+6.1f},{hi:>+6.1f}] {100*d[1]/grand_n:>5.1f}%")
        tot_n += grand_n
        tot_p += sum(d[2] for d in by.values())
    print(f"\n   all-lanes realised: ${tot_p:+,.2f} on ${tot_n:,.0f} staked "
          f"({100*tot_p/tot_n:+.1f}%)")

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    now = time.time() * 1000
    print(f"\n   OPEN BOOK by rich band (deduped per lane, MTM = DB unrealisedPnl)")
    for bot in BOTS:
        rows = con.execute(
            """SELECT walletAddress, marketId, outcome, entryPrice, simulatedPositionSize,
                      unrealizedPnl, openedAt, status
               FROM PaperTrade WHERE isDemo=0 AND status='open' AND botId=?""", (bot,)).fetchall()
        seen, by = set(), {}
        for r in rows:
            k = (r["walletAddress"], r["marketId"], r["outcome"])
            if k in seen or not r["entryPrice"] or r["entryPrice"] <= 0:
                continue
            seen.add(k)
            size = r["simulatedPositionSize"] or 0
            if size <= 0:
                continue
            b = rich_band(r["entryPrice"])
            age = max(0.0, (now - r["openedAt"]) / 86_400_000.0)
            upside = size * (1 - r["entryPrice"]) / r["entryPrice"]
            d = by.setdefault(b, [0, 0.0, 0.0, 0.0, 0.0, 0.0])
            d[0] += 1
            d[1] += size
            d[2] += r["unrealizedPnl"] or 0
            d[3] += size * age
            d[4] += upside
            d[5] += age * size
        if not by:
            continue
        tt = sum(d[1] for d in by.values())
        print(f"\n   {bot}: ${tt:,.0f} open notional")
        print(f"   {'band':10} {'n':>4} {'stake':>8} {'MTM':>8} {'capdays':>9} "
              f"{'upside left':>11} {'upside/stake':>12} {'$/capday':>9}")
        for b in RICH_BANDS:
            if b not in by:
                continue
            d = by[b]
            ratio = d[4] / d[1]
            per_cd = (d[2] / (d[3] / 365.0)) if d[3] else 0.0
            print(f"   {b:10} {d[0]:>4} {d[1]:>8,.0f} {d[2]:>+8,.2f} {d[3]:>9,.0f} "
                  f"{d[4]:>11,.0f} {ratio:>11.3f}x {per_cd:>8.1f}%")


def size_sees_band():
    """N. Is the clip a function of the band? Pre-cap size from DecisionJournal, which is what
    the SCORER decided (PaperTrade.simulatedPositionSize can be post-clamp and hide the answer).
    If a lane's pre-cap size is constant while its bands return -8% and +83%, no band
    information is reaching the order and every band claim is about a size the bot never chose."""
    print("\n" + "=" * 78)
    print("N. DOES SIZE SEE THE BAND? -- pre-cap clip by band, per lane")
    print("=" * 78)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    for bot in BOTS:
        rows = con.execute(
            """SELECT p.entryPrice, p.simulatedPositionSize AS post, j.simulatedPositionSize AS pre,
                      j.confidence
               FROM PaperTrade p JOIN DecisionJournal j ON p.decisionJournalId = j.id
               WHERE p.botId=? AND p.isDemo=0
                 AND p.openedAt >= ?""",
            (bot, int((time.time() - 45 * 86400) * 1000))).fetchall()
        if not rows:
            continue
        by = {}
        for r in rows:
            if not r["entryPrice"] or r["entryPrice"] <= 0:
                continue
            b = rich_band(r["entryPrice"])
            pre = r["pre"] if r["pre"] is not None else r["post"]
            d = by.setdefault(b, [0, [], []])
            d[0] += 1
            d[1].append(pre)
            d[2].append(r["confidence"] or 0)
        print(f"\n   {bot} (last 45d)")
        print(f"   {'band':10} {'n':>5} {'pre-cap avg':>12} {'min':>8} {'max':>8} "
              f"{'conf avg':>9} {'conf range':>14}")
        for b in RICH_BANDS:
            if b not in by:
                continue
            d = by[b]
            print(f"   {b:10} {d[0]:>5} {np.mean(d[1]):>12.2f} {min(d[1]):>8.2f} "
                  f"{max(d[1]):>8.2f} {np.mean(d[2]):>9.3f} "
                  f"{min(d[2]):>6.2f}-{max(d[2]):<7.2f}")
        allsizes = [x for d in by.values() for x in d[1]]
        if allsizes and max(allsizes) > 0:
            print(f"   span: max/min pre-cap clip = {max(allsizes)/max(min(allsizes), 0.01):.1f}x")


# C-200 live band map (RuleSet v65): longshot x3.5, dead zone x0.125 (and hard-skipped),
# 0.6-0.8 x0.5, everything else x1.0.
C200_MAP = {"0.00-0.20": 3.5, "0.20-0.40": 1.0, "0.40-0.60": 0.125,
            "0.60-0.80": 0.5, "0.80-0.95": 1.0, "0.95-1.00": 1.0}
# The 10-21 draft's counter-proposal, for comparison: skip the dead zone, leave the rest.
SKIP_ONLY = {"0.00-0.20": 1.0, "0.20-0.40": 1.0, "0.40-0.60": 0.0,
             "0.60-0.80": 1.0, "0.80-0.95": 1.0, "0.95-1.00": 1.0}


def tail_ladder():
    """Q. Is a band's dollar edge an edge, or its top few legs? For each band: ROI as the
    N biggest winners in that band are removed. A band whose ROI survives losing its top 10
    legs can be sized against; a band that collapses to negative is a lottery ticket with a
    positive mean, and up-weighting it multiplies variance, not edge.

    This is the test that decides the sizing question, and it is reported per lane because the
    two lanes size the same band very differently (C-200 ~3.5x on <0.20, STANDARD flat)."""
    print("\n" + "=" * 78)
    print("Q. TAIL LADDER -- band ROI with the top-N legs in that band removed")
    print("=" * 78)
    for bot in BOTS:
        legs = load(bot, days=None)
        if not legs:
            continue
        print(f"\n   {bot}")
        print(f"   {'band':10} {'n':>5} {'roi all':>9} {'-top1':>9} {'-top3':>9} "
              f"{'-top5':>9} {'-top10':>9} {'top10 pnl':>10} {'share':>7}")
        for b in RICH_BANDS:
            sub = [l for l in legs if rich_band(l["px"]) == b]
            if len(sub) < 12:
                continue
            ntl = sum(l["notional"] for l in sub)
            if ntl <= 0:
                continue
            ordered = sorted(sub, key=lambda l: -l["pnl"])
            cells = []
            for k in (1, 3, 5, 10):
                kept = ordered[k:]
                kntl = sum(l["notional"] for l in kept)
                cells.append(100 * sum(l["pnl"] for l in kept) / kntl if kntl else 0.0)
            top10 = sum(l["pnl"] for l in ordered[:10])
            tot = sum(l["pnl"] for l in sub)
            share = 100 * top10 / tot if tot else float("nan")
            print(f"   {b:10} {len(sub):>5} {100*tot/ntl:>+8.1f}% "
                  + " ".join(f"{c:>+8.1f}%" for c in cells)
                  + f" {top10:>+10,.0f} {share:>6.0f}%")


def accumulation_ladder():
    """R. Does COPYING THE SAME MARKET AGAIN pay? The book holds up to 64 separate legs in one
    (wallet, market, outcome) -- each a distinct observed whale fill, so this is genuine
    mirroring, not a re-fire bug. The question is whether the 2nd..64th copies of a position
    earn anything, because C-200 has a per-market ceiling (v55 maxMarketSlugPositions) and
    STANDARD has none.

    Legs inside a group are ordered by openedAt, so index 1 is the first copy. PnL is realised
    only (settled legs), cost basis = dollars at risk, so the ROI of leg k is directly
    comparable across k.
    """
    print("\n" + "=" * 78)
    print("R. ACCUMULATION LADDER -- realised ROI by copy index within (wallet, market, outcome)")
    print("=" * 78)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    for bot in BOTS:
        rows = con.execute(
            """SELECT walletAddress, marketId, outcome, entryPrice, simulatedPositionSize,
                      realizedPnl, openedAt
               FROM PaperTrade WHERE botId=? AND isDemo=0 AND status IN ('closed','resolved')
                 AND realizedPnl IS NOT NULL AND entryPrice > 0
               ORDER BY walletAddress, marketId, outcome, openedAt""", (bot,)).fetchall()
        groups = {}
        for r in rows:
            d = groups.setdefault((r["walletAddress"], r["marketId"], r["outcome"]), [])
            d.append(r)
        buckets = {"1 (first)": [0, 0.0, 0.0], "2-3": [0, 0.0, 0.0], "4-9": [0, 0.0, 0.0],
                   "10+": [0, 0.0, 0.0]}
        for legs in groups.values():
            for i, r in enumerate(legs, start=1):
                key = ("1 (first)" if i == 1 else "2-3" if i <= 3 else "4-9" if i <= 9 else "10+")
                b = buckets[key]
                b[0] += 1
                b[1] += r["simulatedPositionSize"] or 0
                b[2] += r["realizedPnl"] or 0
        tot_stake = sum(b[1] for b in buckets.values())
        print(f"\n   {bot}: {len(groups)} groups, {sum(b[0] for b in buckets.values())} settled legs")
        print(f"   {'copy index':12} {'legs':>6} {'stake':>10} {'pnl':>10} {'roi':>8} "
              f"{'%stake':>7} {'pnl/share':>10}")
        for k in ("1 (first)", "2-3", "4-9", "10+"):
            b = buckets[k]
            if not b[0]:
                continue
            r_ = 100 * b[2] / b[1] if b[1] else 0.0
            print(f"   {k:12} {b[0]:>6} {b[1]:>10,.0f} {b[2]:>+10,.0f} {r_:>7.1f}% "
                  f"{100*b[1]/tot_stake:>6.1f}% {100*b[2]/sum(x[2] for x in buckets.values()) if sum(x[2] for x in buckets.values()) else 0:>9.0f}%")
        # concentration of a single market
        sizes = sorted((sum(r["simulatedPositionSize"] or 0 for r in legs) for legs in groups.values()),
                       reverse=True)
        if sizes:
            print(f"   largest group ${sizes[0]:,.0f}; top-5 groups "
                  f"${sum(sizes[:5]):,.0f} = {100*sum(sizes[:5])/sum(sizes):.1f}% of staked")


def rate_check():
    """S. THE LADDER GAP, measured. Profit = edge x capital x turnover, so the honest scale
    number is realised dollars per calendar day (not ROI, which flatters long holds), and the
    multiple it implies for the ladder's next rung. This is the number that decides whether a
    band or exit change can matter at all."""
    print("\n" + "=" * 78)
    print("S. RATE CHECK -- realised $/day, staked $/day, and the ladder multiple")
    print("=" * 78)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    now = time.time() * 1000
    print(f"   {'window':10} {'legs':>6} {'stake/day':>10} {'pnl/day':>9} {'roi':>8} "
          f"{'days at $5k':>12}")
    for days in (14, 30, 60, 90, 126):
        since = now - days * 86400 * 1000
        rows = con.execute(
            """SELECT p.simulatedPositionSize, p.realizedPnl, p.closedAt, p.resolvedAt
               FROM PaperTrade p WHERE p.isDemo=0 AND p.status IN ('closed','resolved')
                 AND p.realizedPnl IS NOT NULL AND p.openedAt >= ?""", (since,)).fetchall()
        if not rows:
            continue
        stake = sum(r["simulatedPositionSize"] or 0 for r in rows)
        pn = sum(r["realizedPnl"] or 0 for r in rows)
        print(f"   last {days:>3}d  {len(rows):>6} {stake/days:>10,.0f} {pn/days:>+9,.2f} "
              f"{100*pn/stake if stake else 0:>7.1f}% {(5000/(pn/days)) if pn > 0 else float('inf'):>11,.0f}x")
    # open exposure, both bases
    rows = con.execute(
        """SELECT botId, simulatedPositionSize FROM PaperTrade
           WHERE isDemo=0 AND status='open'""").fetchall()
    print(f"\n   open notional (capital basis, all legs): "
          f"${sum(r['simulatedPositionSize'] or 0 for r in rows):,.0f}")
    for bot in BOTS:
        sub = [r for r in rows if r["botId"] == bot]
        print(f"     {bot}: {len(sub)} legs, ${sum(r['simulatedPositionSize'] or 0 for r in sub):,.0f}")


def sizing_shadow():
    """O. Shadow computation on REALISED legs: what would a band map have paid?

    This is a frozen-leg shadow, not a simulation. It holds the leg set fixed and scales each
    leg's stake by the map, which is exactly the question 'was the notional where the edge was'
    and NOT the question 'would re-sizing have changed which trades we took'. PnL scales
    linearly with stake because the paper fill pays a fixed price with no impact.

    Reported three ways because the honest answer differs by basis:
      raw map          -- what the C-200 factors would have done to STANDARD's book
      notional-neutral -- same factors, rescaled so total staked dollars are UNCHANGED
                          (a reallocation, not a size-up; this is the defensible version)
      ex-top-10        -- the same, with the 10 biggest winners removed, because 96% of booked
                          profit is one leg and any up-weight of the cheap band multiplies it
    """
    print("\n" + "=" * 78)
    print("O. SIZING SHADOW -- realised legs re-priced under a band map (frozen legs)")
    print("=" * 78)
    for bot in BOTS:
        legs = load(bot, days=None)
        if not legs:
            continue
        gross = sum(l["notional"] for l in legs)
        base = sum(l["pnl"] for l in legs)
        print(f"\n   {bot}: {len(legs)} deduped settled legs, ${gross:,.0f} staked, "
              f"PnL ${base:+,.2f} ({100*base/gross:+.2f}%)")
        for name, m in (("C-200 map (raw)", C200_MAP),
                        ("C-200 map (notional-neutral)", C200_MAP),
                        ("dead-zone skip only", SKIP_ONLY)):
            scale = 1.0
            if "neutral" in name:
                newgross = sum(l["notional"] * m[rich_band(l["px"])] for l in legs)
                scale = gross / newgross if newgross else 1.0
            tot = sum(l["pnl"] * (1 + (m[rich_band(l["px"])] * scale - 1)) for l in legs)
            # ex-top-10 by pnl
            top = set(sorted(range(len(legs)), key=lambda i: -legs[i]["pnl"])[:10])
            tot_x = sum(l["pnl"] * m[rich_band(l["px"])] * scale
                        for i, l in enumerate(legs) if i not in top)
            base_x = sum(l["pnl"] for i, l in enumerate(legs) if i not in top)
            print(f"     {name:32} PnL ${tot:>+10,.0f} (delta {tot-base:>+9,.0f})  "
                  f"ex-top-10 delta {tot_x-base_x:>+9,.0f}")
        # per-band contribution of the raw map
        print(f"     {'band':10} {'n':>4} {'stake':>8} {'pnl':>9} {'factor':>7} "
              f"{'delta':>9} {'delta ex-top10':>15}")
        top = set(sorted(range(len(legs)), key=lambda i: -legs[i]["pnl"])[:10])
        for b in RICH_BANDS:
            idx = [i for i, l in enumerate(legs) if rich_band(l["px"]) == b]
            if not idx:
                continue
            st = sum(legs[i]["notional"] for i in idx)
            pn = sum(legs[i]["pnl"] for i in idx)
            f = C200_MAP[b]
            dx = sum(legs[i]["pnl"] for i in idx if i not in top) * (f - 1)
            print(f"     {b:10} {len(idx):>4} {st:>8,.0f} {pn:>+9,.0f} {f:>7.3f} "
                  f"{pn*(f-1):>+9,.0f} {dx:>+15,.0f}")


def stop_replay(dedup=True):
    """P. The 168h stop replay -- the gate the 10-21 draft pre-registered and never ran.

    TWO BASES, because they answer different questions and an earlier draft conflated them:
      deduped  -- one row per (wallet|market|outcome): the per-BET view, right for per-trade
                  statistics (duplicate accumulation rows are pseudo-replication).
      all legs -- every fill: the CAPITAL view. Verified that the duplicates are genuine
                  (64 legs in the Barcelona market carry 64 distinct observedTradeIds -- the
                  executor mirrors each whale fill separately, it does not re-fire one signal),
                  so real deployed notional is the full $13.6k, not the deduped $5.3k. A stop
                  rule is a capital rule, so this is the base that sizes the effect.

    Counterfactual: exit at the first recorded mark at or after entry+168h (a bot can only
    exit when a price exists, so the realised exit age is reported rather than assumed to be
    exactly 168h). Hold arm: the market's latest recorded mark, which is the same series, so
    the comparison does not mix a snapshot price against a DB mark. The DB mark is also shown
    as a cross-check.

    Cost basis: dollars at risk, and PnL at a mark m for an entry at p is stake*(m/p - 1) --
    the same convention as open_book()'s '(1-p)/p upside left'.
    """
    print("\n" + "=" * 78)
    print(f"P. 168h STOP REPLAY ({'deduped per bet' if dedup else 'ALL legs (capital basis)'}) "
          f"-- open STANDARD book")
    print("=" * 78)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    now = time.time() * 1000
    STOP = 168 * 3600 * 1000
    rows = con.execute(
        """SELECT walletAddress, marketId, outcome, side, entryPrice, simulatedPositionSize,
                  currentPrice, openedAt
           FROM PaperTrade WHERE isDemo=0 AND status='open' AND botId='STANDARD'""").fetchall()
    seen, trades = set(), []
    for r in rows:
        k = (r["walletAddress"], r["marketId"], r["outcome"])
        if dedup:
            if k in seen:
                continue
            seen.add(k)
        if r["side"] != "BUY" or r["outcome"] not in ("YES", "NO"):
            continue
        if not r["entryPrice"] or r["entryPrice"] <= 0 or not r["simulatedPositionSize"]:
            continue
        trades.append(dict(r))
    by = {}
    for t in trades:
        by.setdefault(t["marketId"], []).append(t)
    priced = []
    for mkt, ts in by.items():
        snaps = con.execute(
            "SELECT collectedAt, yesPrice, noPrice FROM MarketSnapshot WHERE marketId=? "
            "ORDER BY collectedAt", (mkt,)).fetchall()
        if not snaps:
            continue
        times = [s["collectedAt"] for s in snaps]
        for t in ts:
            target = t["openedAt"] + STOP
            i = bisect.bisect_left(times, target)
            if i >= len(snaps):
                i = len(snaps) - 1          # market went quiet: last observed mark
            s, last = snaps[i], snaps[-1]
            px = s["yesPrice"] if t["outcome"] == "YES" else s["noPrice"]
            lpx = last["yesPrice"] if t["outcome"] == "YES" else last["noPrice"]
            if px is None or lpx is None:
                continue
            t = dict(t)
            t["stop_px"] = px
            t["hold_px"] = lpx
            t["stop_age_h"] = (s["collectedAt"] - t["openedAt"]) / 3600000.0
            t["age_h"] = (now - t["openedAt"]) / 3600000.0
            priced.append(t)
    if not priced:
        print("   no priceable open legs")
        return

    def pnl_at(t, px):
        return t["simulatedPositionSize"] * (px / t["entryPrice"] - 1.0)

    def scope(lo, hi):
        return [t for t in priced if lo <= t["entryPrice"] < hi]

    print(f"   priced {len(priced)}/{len(trades)} open STANDARD "
          f"{'bets' if dedup else 'legs'} "
          f"(${sum(t['simulatedPositionSize'] for t in priced):,.0f} notional)")
    print(f"   realised exit age: median {np.median([t['stop_age_h'] for t in priced]):.0f}h, "
          f"p90 {np.percentile([t['stop_age_h'] for t in priced], 90):.0f}h")
    print(f"\n   {'scope':14} {'n':>4} {'notional':>9} {'hold':>9} {'stop':>9} "
          f"{'delta':>8} {'capdays hold':>13} {'capdays stop':>13} {'%kept':>6}")
    for label, lo, hi in (("0.20-1.00 (10-21)", 0.20, 1.01),
                          ("0.40-1.00", 0.40, 1.01),
                          ("0.60-1.00", 0.60, 1.01),
                          ("0.00-0.40 (exempt)", 0.0, 0.40),
                          ("ALL", 0.0, 1.01)):
        sub = scope(lo, hi)
        if not sub:
            continue
        ntl = sum(t["simulatedPositionSize"] for t in sub)
        hold = sum(pnl_at(t, t["hold_px"]) for t in sub)
        stop = sum(pnl_at(t, t["stop_px"]) for t in sub)
        cdh = sum(t["simulatedPositionSize"] * t["age_h"] / 24.0 for t in sub)
        cds = sum(t["simulatedPositionSize"] * min(t["age_h"], t["stop_age_h"]) / 24.0 for t in sub)
        print(f"   {label:14} {len(sub):>4} {ntl:>9,.0f} {hold:>+9,.0f} {stop:>+9,.0f} "
              f"{stop-hold:>+8,.0f} {cdh:>13,.0f} {cds:>13,.0f} {100*cds/cdh:>5.0f}%")

    # THE MARK QUESTION, stated rather than buried: the snapshot series for these markets ends
    # a median 35 days before today, so 'hold at the latest snapshot' is a STALE hold estimate.
    # The DB's currentPrice is fresher. Both are reported; the DB basis is the pessimistic one
    # for the stop and is the one the recommendation has to survive.
    print(f"\n   hold-arm basis comparison (the snapshot series is stale; see docstring)")
    print(f"   {'scope':14} {'stop':>9} {'hold@snap':>10} {'d@snap':>8} "
          f"{'hold@DB':>9} {'d@DB':>8} {'stop@DB%':>9}")
    for label, lo, hi in (("0.40-1.00", 0.40, 1.01), ("0.60-1.00", 0.60, 1.01)):
        sub = scope(lo, hi)
        if not sub:
            continue
        ntl = sum(t["simulatedPositionSize"] for t in sub)
        stop = sum(pnl_at(t, t["stop_px"]) for t in sub)
        hs = sum(pnl_at(t, t["hold_px"]) for t in sub)
        hd = sum(pnl_at(t, t["currentPrice"]) for t in sub)
        print(f"   {label:14} {stop:>+9,.0f} {hs:>+10,.0f} {stop-hs:>+8,.0f} "
              f"{hd:>+9,.0f} {stop-hd:>+8,.0f} {100*(stop-hd)/ntl:>8.1f}%")

    print(f"\n   per-band detail (stop vs hold, same marks)")
    print(f"   {'band':10} {'n':>4} {'notional':>9} {'hold':>9} {'stop':>9} {'delta':>8} "
          f"{'delta%notl':>11}")
    by_band = {}
    for t in priced:
        by_band.setdefault(rich_band(t["entryPrice"]), []).append(t)
    for b in RICH_BANDS:
        if b not in by_band:
            continue
        sub = by_band[b]
        ntl = sum(t["simulatedPositionSize"] for t in sub)
        hold = sum(pnl_at(t, t["hold_px"]) for t in sub)
        stop = sum(pnl_at(t, t["stop_px"]) for t in sub)
        print(f"   {b:10} {len(sub):>4} {ntl:>9,.0f} {hold:>+9,.0f} {stop:>+9,.0f} "
              f"{stop-hold:>+8,.0f} {100*(stop-hold)/ntl:>10.1f}%")

    # EXIT COST: a stop sells at the bid, not the mark. Charge the haircut on the proceeds of
    # every stopped leg and report the breakeven haircut -- the fill assumption, stated.
    def proceeds(t):
        return t["simulatedPositionSize"] * (t["stop_px"] / t["entryPrice"])

    print(f"\n   exit-cost sensitivity (haircut on stopped proceeds)")
    print(f"   {'scope':14} {'delta h=0':>10} {'h=0.5%':>10} {'h=1%':>10} {'h=2%':>10} "
          f"{'breakeven h':>12}")
    for label, lo, hi in (("0.40-1.00", 0.40, 1.01), ("0.60-1.00", 0.60, 1.01)):
        sub = scope(lo, hi)
        if not sub:
            continue
        hold = sum(pnl_at(t, t["hold_px"]) for t in sub)
        stop = sum(pnl_at(t, t["stop_px"]) for t in sub)
        pr = sum(proceeds(t) for t in sub)
        d0 = stop - hold
        cells = [d0 - h * pr for h in (0.0, 0.005, 0.01, 0.02)]
        be = d0 / pr if pr else 0.0
        print(f"   {label:14} " + " ".join(f"{c:>+10,.0f}" for c in cells)
              + f" {100*be:>11.1f}%")

    dball = sum(pnl_at(t, t["currentPrice"]) for t in priced)
    dbsn = sum(pnl_at(t, t["hold_px"]) for t in priced)
    print(f"\n   cross-check: hold arm at DB mark ${dball:+,.2f} vs at latest snapshot "
          f"${dbsn:+,.2f} (same sign, ${abs(dball-dbsn):,.0f} apart)")
    print(f"   DECISION RULE (set 2026-10-21): capital-days cut >=50% for <$150 PnL cost.")
    sub = scope(0.60, 1.01)
    if sub:
        ntl = sum(t["simulatedPositionSize"] for t in sub)
        hold = sum(pnl_at(t, t["hold_px"]) for t in sub)
        stop = sum(pnl_at(t, t["stop_px"]) for t in sub)
        cdh = sum(t["simulatedPositionSize"] * t["age_h"] / 24.0 for t in sub)
        cds = sum(t["simulatedPositionSize"] * min(t["age_h"], t["stop_age_h"]) / 24.0 for t in sub)
        print(f"   >=0.60 scope: capdays {cdh:,.0f} -> {cds:,.0f} "
              f"({100*(1-cds/cdh):.0f}% cut), PnL delta ${stop-hold:+,.2f} "
              f"-> {'PASS' if (cds/cdh <= 0.5 and stop-hold > -150) else 'FAIL'}")
    if dedup:
        stop_replay(dedup=False)


if "--v2" in ARGS or "--all" in ARGS:
    calibration_report()
    inband_concentration()
    era_cut()
    wallet_null()
    recency_and_basis()
    calibration_by_window()
    lane_anatomy()
    v54_experiment()
    spread_haircut()
    spread_by_window()
    lane_duplication()
    open_book()

if "--all" in ARGS or not ARGS:
    default_report()

if "--only-a" in ARGS:
    calibration_report()
if "--only-b" in ARGS:
    inband_concentration()
if "--only-d" in ARGS:
    wallet_null()
if "--only-e" in ARGS:
    recency_and_basis()

if V3:
    rich_tail()
    size_sees_band()
    tail_ladder()
    accumulation_ladder()
    rate_check()
    sizing_shadow()
    stop_replay()
