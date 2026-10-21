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
import sqlite3
import sys
import time
import numpy as np

DB = "prisma/dev.db"
BOTS = ["STANDARD", "BANKROLL_200"]
BANDS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0001)]
ARGS = sys.argv[1:]
V2 = "--v2" in ARGS or "--all" in ARGS


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
