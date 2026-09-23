#!/usr/bin/env python3
"""
wallet-depth-floor-test — READ-ONLY: does the SOURCE wallet's record depth
(resolved-position count) predict how our copy of that wallet does, and what
would a minimum-depth floor actually remove?
(roadmap card `polycopy-thin-record-floor-test`, 2026-09-23).

WHY: Polycopy's Sep-8 report flags a record as 'thin' when it holds few resolved
positions (12 of 88 scoreable wallets on their 30-day board, 34 of 65 all-time)
and notes a spectacular number over a handful of bets is often one good week
(their shrink moves the all-time median from 10.52% raw to 2.07%). Our wallet
selection has no explicit depth floor: `globalScore` blends ROI / consistency /
copyability, and the scan profiler works whatever the 25 least-recently-scanned
wallets are. The standing rule is MEASURE FIRST — this script gates nothing.

TWO DEPTH MEASURES, because the stored one is broken in a way that matters:
  (a) AS-OF-PRINT snapshot: WalletProfile.resolvedTradeCount30d. MEASURED
      FINDING: this field is CLAMPED AT 100 (p50 = p75 = p90 = max = 100 over
      3,201 wallets), so it cannot separate a 100-position record from a
      900-position one — exactly the deep end a thin-record rule is meant to
      grade against. It is also a live value, not an as-of-entry one: a wallet's
      depth as read today is not the depth the copy decision saw.
  (b) AS-OF-ENTRY record depth: the number of DISTINCT markets we had already
      observed that wallet trading strictly BEFORE the leg was opened
      (ObservedTrade.timestamp < PaperTrade.openedAt), time-consistent with the
      decision. It measures the depth our own scanner had seen, which is a lower
      bound on the wallet's true history (our observation window starts
      2026-07-13 and predates most of the book).

WHAT IT PRINTS: per lane (split), depth-bucket tables with n / cost / realized /
mean+median leg / win share / edge %, wallet-clustered bootstrap CIs, pooled
permutation for the extreme contrast, a MEDIAN ENTRY PRICE column and the same
contrast WITHIN entry-price quintiles (thin records are often longshot books —
without the price control the depth effect is just a price effect), ranker AUCs
against the scores we already select on, and a FLOOR SIMULATION showing what
each candidate minimum would remove from the lane (legs, cost, realized, edge,
wallets, and how many of the currently-tracked 25 survive).

Writes nothing.
"""
import datetime
import math
import os
import random
import sqlite3
import statistics
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB_PATH = os.path.join(ROOT, "prisma", "dev.db")
LANES = ("BANKROLL_200", "STANDARD")
BOOT = 5000
PERM = 20000
ELEMENT_BUDGET = 40000000     # permutation element-ops per test (~60s in CPython)
BOOT_BUDGET = 20000000        # element-ops per bootstrap CI
random.seed(20260923)
_DRAWS = []
_BOOT_DRAWS = []

SNAP_BUCKETS = [(0, 25, "<25"), (25, 100, "25-99"), (100, 10 ** 9, "100 (clamped)")]


# ---------------------------------------------------------------- statistics
def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return float("nan")
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return num / (dx * dy) if dx and dy else float("nan")


def _ranks(v):
    order = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def spearman(xs, ys):
    return pearson(_ranks(xs), _ranks(ys))


def auc(scores, labels):
    pos = [s for s, l in zip(scores, labels) if l]
    neg = [s for s, l in zip(scores, labels) if not l]
    if not pos or not neg:
        return float("nan")
    ranks = _ranks(scores)
    rsum = sum(r for r, l in zip(ranks, labels) if l)
    n1, n0 = len(pos), len(neg)
    return (rsum - n1 * (n1 + 1) / 2.0) / (n1 * n0)


def boot_ci_clusters(groups, fn, n=None):
    """Cluster bootstrap: resample the SHARED UNIT (wallets), not legs. Draws are
    budgeted by total element count so an 9k-leg lane cannot take minutes."""
    total = sum(len(g) for g in groups)
    draws = n or max(1000, min(BOOT, int(BOOT_BUDGET / max(1, total))))
    _BOOT_DRAWS.append(draws)
    vals = []
    for _ in range(draws):
        sample = [groups[random.randrange(len(groups))] for _ in range(len(groups))]
        v = fn(sample)
        if v == v and abs(v) != float("inf"):
            vals.append(v)
    if len(vals) < 100:
        return (float("nan"), float("nan"))
    vals.sort()
    return (vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals))])


def auc_half(n_pos, n_neg):
    """Hanley–McNeil closed-form 95% half-width of an AUC at A=0.5 — the sample's
    minimum detectable discrimination. No randomness."""
    a = 0.5
    q1 = a / (2 - a)
    q2 = 2 * a * a / (1 + a)
    se = math.sqrt((a * (1 - a) + (n_pos - 1) * (q1 - a * a) + (n_neg - 1) * (q2 - a * a)) / (n_pos * n_neg))
    return 1.96 * se


def fast_mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def pooled_perm_clusters(groups_a, groups_b, stat, n=None):
    """Two-group difference where the GROUP LABEL is permuted at the shared unit
    (WALLET) level: the pooled wallets are re-split each draw, so the legs of one
    wallet never move independently of each other. A leg-level shuffle treats
    hundreds of legs as hundreds of draws and reports p=0.000 for trivial gaps."""
    wa = [g for g in groups_a if g]
    wb = [g for g in groups_b if g]
    fa = [x for g in wa for x in g]
    fb = [x for g in wb for x in g]
    if len(fa) < 5 or len(fb) < 5 or len(wa) < 4 or len(wb) < 4:
        return float("nan")
    obs = abs(stat(fa) - stat(fb))
    pool = wa + wb
    na = len(wa)
    draws = n or max(2000, min(PERM, int(ELEMENT_BUDGET / max(1, len(fa) + len(fb)))))
    _DRAWS.append(draws)
    cnt = 0
    for _ in range(draws):
        random.shuffle(pool)
        a = [x for g in pool[:na] for x in g]
        b = [x for g in pool[na:] for x in g]
        if abs(stat(a) - stat(b)) >= obs:
            cnt += 1
    return (cnt + 1) / (draws + 1)


def draws_note():
    if not _DRAWS:
        return ""
    return "permutation draws %d-%d (adaptive to pool size)" % (min(_DRAWS), max(_DRAWS))


def ci_line(L, buckets, label):
    """Wallet-clustered 95% CI on the mean leg, one line for a set of buckets."""
    parts = []
    for name, grp in buckets:
        if len(grp) < 10:
            parts.append("%s n/a" % name)
            continue
        gh = [[l["pnl"] for l in grp if l["wallet"] == w] for w in {l["wallet"] for l in grp}]
        lo, hi = boot_ci_clusters(gh, lambda s: fast_mean([x for g in s for x in g]))
        parts.append("%s [%s, %s]" % (name, money(lo), money(hi)))
    print("    wallet-clustered 95%% CI on mean leg (%s): %s" % (label, " | ".join(parts)))


def money(v):
    return "%s$%.2f" % ("-" if v < 0 else "", abs(v))


def pct(v):
    return "n/a" if v is None or v != v else "%+.3f" % v


# --------------------------------------------------------------------- data
def load():
    con = sqlite3.connect("file:%s?mode=ro" % DB_PATH, uri=True)
    obs = con.execute(
        "SELECT walletAddress, marketId, timestamp, observationOnly FROM ObservedTrade WHERE isDemo = 0"
    ).fetchall()
    legs = con.execute(
        """SELECT p.botId, p.walletAddress, p.realizedPnl, p.simulatedPositionSize,
                  p.entryPrice, p.openedAt
           FROM PaperTrade p
           WHERE p.isDemo = 0 AND p.status IN ('closed','resolved') AND p.realizedPnl IS NOT NULL"""
    ).fetchall()
    scans = con.execute(
        """SELECT address, coalesce(resolvedTradeCount30d,0), coalesce(tradeCount30d,0),
                  coalesce(winRate30d,0), coalesce(roi30d,0), coalesce(globalScore,0),
                  coalesce(status,''), coalesce(lastScannedAt,0), coalesce(updatedAt,0)
           FROM WalletProfile WHERE isDemo = 0"""
    ).fetchall()
    con.close()
    return obs, legs, scans


def main():
    obs, leg_rows, scans = load()
    scan = {r[0]: r for r in scans}

    # ---- measure the clamp before using the field
    vals = sorted(r[1] for r in scans)
    n = len(vals)
    clamp_share = sum(1 for v in vals if v >= 100) / float(n)
    print("wallet depth floor test — READ-ONLY, gates nothing")
    print("  WalletProfile.resolvedTradeCount30d distribution over %d wallets: min %d | p10 %d | p25 %d | p50 %d | p75 %d | p90 %d | max %d"
          % (n, vals[0], vals[n // 10], vals[n // 4], vals[n // 2], vals[3 * n // 4], vals[9 * n // 10], vals[-1]))
    print("  >>> the field is CLAMPED at 100: %.1f%% of ALL wallets sit exactly at the cap, so it cannot" % (100.0 * clamp_share))
    print("      distinguish a 100-position record from a 900-position one. Bucket '100 (clamped)' below is the")
    print("      whole deep end, and the as-of-entry measure (b) is the one that can still grade it.")
    tvals = sorted(r[2] for r in scans)
    print("  WalletProfile.tradeCount30d: p50 %d | p90 %d | max %d (%s)"
          % (tvals[n // 2], tvals[9 * n // 10], tvals[-1],
             "also capped" if tvals[-1] >= 200 else "not obviously capped"))
    stamps = [r[7] for r in scans if r[7]]
    print("  as-of stamp: lastScannedAt spans %s -> %s, i.e. every wallet's depth is a snapshot of WHEN it was"
          % (datetime.datetime.fromtimestamp(min(stamps) / 1000.0).strftime("%Y-%m-%d"),
             datetime.datetime.fromtimestamp(max(stamps) / 1000.0).strftime("%Y-%m-%d")))
    print("      scanned (never the depth our copy decision saw).")

    # ---- as-of-entry observed depth: distinct markets seen before the leg opened
    seen = defaultdict(set)          # wallet -> set of (marketId)
    obs_sorted = sorted(obs, key=lambda r: r[2] or 0)
    obs_events = defaultdict(list)   # wallet -> list of (ts, marketId)
    for w, mid, ts, _o in obs_sorted:
        obs_events[w].append((ts or 0, mid))
    depth_cache = {}

    def depth_at(w, opened_ms):
        key = (w, opened_ms // 86400000)     # per-day cache: exact enough, and keeps it fast
        if key in depth_cache:
            return depth_cache[key]
        d = 0
        for ts, mid in obs_events.get(w, ()):
            if ts >= opened_ms:
                break
            seen[w].add(mid)
        d = len(seen[w])
        seen[w].clear()
        depth_cache[key] = d
        return d

    print("\nAS-OF-ENTRY DEPTH (b): distinct markets we had ALREADY observed that wallet trading before the leg")
    print("opened. Healthy: the median as-of-entry depth is what our scanner had seen, not the wallet's true")
    print("history (observation window starts 2026-07-13), so it is a LOWER BOUND on record depth.")

    for lane in LANES:
        L = [r for r in leg_rows if r[0] == lane]
        if len(L) < 50:
            continue
        legs = []
        for bot, w, pnl, size, entry, opened in L:
            s = scan.get(w)
            legs.append(dict(
                wallet=w, pnl=pnl or 0.0, size=size or 0.0, entry=entry or 0.0,
                opened=opened or 0,
                resolved30=s[1] if s else None, trades30=s[2] if s else None,
                winrate30=s[3] if s else None, roi30=s[4] if s else None,
                globalScore=s[5] if s else None, status=s[6] if s else "",
            ))
        print("\n" + "=" * 78)
        print("%s — %d settled legs, %d source wallets, realized %s on %s cost (%.1f%% of cost)"
              % (lane, len(legs), len({l['wallet'] for l in legs}),
                 money(sum(l['pnl'] for l in legs)), money(sum(l['size'] for l in legs)),
                 100.0 * sum(l['pnl'] for l in legs) / max(1e-9, sum(l['size'] for l in legs))))

        # ---------- (a) the stored snapshot
        print("\n  (a) BY STORED snapshot resolvedTradeCount30d — with the price control column")
        print("  %-15s %5s %5s %9s %10s %9s %8s %6s %8s %8s" %
              ("bucket", "wal", "legs", "cost$", "realized$", "mean leg$", "median$", "win%", "edge%", "med entry"))
        bucket_legs = {}
        for lo, hi, label in SNAP_BUCKETS:
            grp = [l for l in legs if l["resolved30"] is not None and lo <= l["resolved30"] < hi]
            bucket_legs[label] = grp
            if not grp:
                continue
            cost = sum(l["size"] for l in grp) or 1e-9
            print("  %-15s %5d %5d %9.0f %10s %9s %8s %5.0f%% %8s %8.3f" % (
                label, len({l['wallet'] for l in grp}), len(grp), sum(l["size"] for l in grp),
                money(sum(l["pnl"] for l in grp)), money(statistics.mean([l["pnl"] for l in grp])),
                money(statistics.median([l["pnl"] for l in grp])),
                100.0 * sum(1 for l in grp if l["pnl"] > 0) / len(grp),
                "%+.1f" % (100.0 * sum(l["pnl"] for l in grp) / cost),
                statistics.median([l["entry"] for l in grp])))
        thin = bucket_legs.get("<25", [])
        deep = bucket_legs.get("100 (clamped)", [])
        ci_line(legs, [("<25", thin), ("25-99", bucket_legs.get("25-99", [])), ("100 clamped", deep)],
                "stored snapshot")
        if thin and deep:
            ga = [[l["pnl"] for l in thin if l["wallet"] == w] for w in {l["wallet"] for l in thin}]
            gb = [[l["pnl"] for l in deep if l["wallet"] == w] for w in {l["wallet"] for l in deep}]
            print("    thin(<25) vs deep(100) — wallet-clustered mean leg: %s vs %s ; clustered perm p(mean)=%.3f p(median)=%.3f [%s]"
                  % (money(fast_mean([l["pnl"] for l in thin])), money(fast_mean([l["pnl"] for l in deep])),
                     pooled_perm_clusters(ga, gb, fast_mean), pooled_perm_clusters(ga, gb, statistics.median), draws_note()))

        # ---------- (b) as-of-entry depth, quartiles of the wallet population
        for l in legs:
            l["depth_at"] = depth_at(l["wallet"], l["opened"])
        dvals = sorted({l["depth_at"] for l in legs})
        if len(dvals) >= 8:
            med = dvals[len(dvals) // 2]
            print("\n  (b) BY AS-OF-ENTRY observed depth — quartiles over our own legs (median depth %d markets)" % med)
            print("  %-15s %5s %5s %9s %10s %9s %8s %6s %8s %8s" %
                  ("depth bucket", "wal", "legs", "cost$", "realized$", "mean leg$", "median$", "win%", "edge%", "med entry"))
            qs = [dvals[int(len(dvals) * k / 4.0)] for k in range(1, 4)]
            cuts = [0] + qs + [10 ** 9]
            qbuckets = {}
            for i in range(4):
                grp = [l for l in legs if cuts[i] <= l["depth_at"] < cuts[i + 1]] if i < 3 else \
                    [l for l in legs if l["depth_at"] >= cuts[i]]
                label = "<%d" % cuts[1] if i == 0 else ("%d-%d" % (cuts[i], cuts[i + 1] - 1) if i < 3 else ">=%d" % cuts[3])
                qbuckets[label] = grp
                if not grp:
                    continue
                cost = sum(l["size"] for l in grp) or 1e-9
                print("  %-15s %5d %5d %9.0f %10s %9s %8s %5.0f%% %8s %8.3f" % (
                    label, len({l['wallet'] for l in grp}), len(grp), sum(l["size"] for l in grp),
                    money(sum(l["pnl"] for l in grp)), money(statistics.mean([l["pnl"] for l in grp])),
                    money(statistics.median([l["pnl"] for l in grp])),
                    100.0 * sum(1 for l in grp if l["pnl"] > 0) / len(grp),
                    "%+.1f" % (100.0 * sum(l["pnl"] for l in grp) / cost),
                    statistics.median([l["entry"] for l in grp])))
            ci_line(legs, sorted(qbuckets.items()), "as-of-entry depth")

        # ---------- price control on (a)
        print("\n  PRICE CONTROL on (a): thin(<25) vs deep(100), WITHIN entry-price quintiles")
        prices = sorted(l["entry"] for l in legs)
        cuts_p = [0.0] + [prices[int(k * len(prices) / 5.0)] for k in range(1, 5)] + [1.01]
        print("  %-13s %5s %5s %10s %10s %10s   %s" % ("entry band", "thin", "deep", "thin mean$", "deep mean$", "diff", "clustered p"))
        for i in range(5):
            a = [l for l in thin if cuts_p[i] <= l["entry"] < cuts_p[i + 1]]
            b = [l for l in deep if cuts_p[i] <= l["entry"] < cuts_p[i + 1]]
            if len(a) < 5 or len(b) < 5:
                print("  %-13s %5d %5d  (too few legs)" % ("%.2f-%.2f" % (cuts_p[i], cuts_p[i + 1]), len(a), len(b)))
                continue
            ga = [[l["pnl"] for l in a if l["wallet"] == w] for w in {l["wallet"] for l in a}]
            gb = [[l["pnl"] for l in b if l["wallet"] == w] for w in {l["wallet"] for l in b}]
            p = pooled_perm_clusters(ga, gb, fast_mean)
            print("  %-13s %5d %5d %10s %10s %10s   %s" % (
                "%.2f-%.2f" % (cuts_p[i], cuts_p[i + 1]), len(a), len(b),
                money(statistics.mean([l["pnl"] for l in a])), money(statistics.mean([l["pnl"] for l in b])),
                money(statistics.mean([l["pnl"] for l in a]) - statistics.mean([l["pnl"] for l in b])),
                "p=%.3f" % p if p == p else "n/a — <%d wallets per side" % 4))
        print("    [%s; p resolution floor 1/(draws+1); legs are clustered inside wallets]"
              % draws_note())

        # ---------- rankers
        print("\n  RANKERS vs 'leg won' (AUC; 0.50 = no information; entry price is the baseline to beat)")
        win = [1 if l["pnl"] > 0 else 0 for l in legs]
        np_, nn_ = sum(win), len(win) - sum(win)
        hw = auc_half(np_, nn_)
        print("  MDE: with %d winning / %d losing legs this sample excludes any true AUC outside 0.50±%.3f"
              % (np_, nn_, hw))
        feats = [
            ("resolvedTradeCount30d (scan)", lambda l: l["resolved30"]),
            ("tradeCount30d (scan)", lambda l: l["trades30"]),
            ("depth as-of-entry (ours)", lambda l: l["depth_at"]),
            ("roi30d", lambda l: l["roi30"]),
            ("globalScore", lambda l: l["globalScore"]),
            ("entryPrice (price baseline)", lambda l: l["entry"]),
            ("1 - entryPrice", lambda l: 1.0 - l["entry"]),
        ]
        for label, get in feats:
            pairs = [(get(l), w) for l, w in zip(legs, win) if get(l) is not None]
            if len(pairs) < 50:
                continue
            print("    %-30s AUC %.3f [%.3f, %.3f] (n=%d)" % (
                label, auc([p[0] for p in pairs], [p[1] for p in pairs]),
                auc([p[0] for p in pairs], [p[1] for p in pairs]) - hw,
                auc([p[0] for p in pairs], [p[1] for p in pairs]) + hw, len(pairs)))
        xs = [l["resolved30"] for l in legs if l["resolved30"] is not None]
        ys = [l["depth_at"] for l in legs if l["resolved30"] is not None]
        print("    spearman(stored snapshot, as-of-entry depth) = %s over %d legs (they are not the same number)"
              % (pct(spearman(xs, ys)), len(xs)))

        # ---------- floor simulation
        print("\n  FLOOR SIMULATION — what a minimum would remove from THIS lane (in-sample; see caveats)")
        base_cost = sum(l["size"] for l in legs) or 1e-9
        base_pnl = sum(l["pnl"] for l in legs)
        all_wallets = {l["wallet"] for l in legs}
        tracked = {w for w in all_wallets if scan.get(w, ("",) * 7)[6] == "track"}
        print("  %-38s %5s %8s %10s %10s %8s %6s %8s" %
              ("floor (removes < N)", "legs", "%cost", "removed$", "kept PnL$", "edge%", "wal", "tracked"))
        rows = []
        rows.append(("none (baseline)", 0))
        rows += [("resolvedTradeCount30d >= %d" % k, k) for k in (10, 25, 50, 100)]
        for label, k in rows:
            kept = [l for l in legs if (l["resolved30"] or 0) >= k]
            rem = [l for l in legs if (l["resolved30"] or 0) < k]
            cost = sum(l["size"] for l in kept) or 1e-9
            kw = {l["wallet"] for l in kept}
            print("  %-38s %5d %7.1f%% %10s %10s %7.1f%% %6d %5d/%d" % (
                label, len(kept), 100.0 * sum(l["size"] for l in kept) / base_cost,
                money(sum(l["pnl"] for l in rem)), money(sum(l["pnl"] for l in kept)),
                100.0 * sum(l["pnl"] for l in kept) / cost, len(kw), len(kw & tracked), len(tracked)))
        print("  %-38s %5s %8s %10s %10s %8s %6s %8s" %
              ("floor on AS-OF-ENTRY depth (ours)", "legs", "%cost", "removed$", "kept PnL$", "edge%", "wal", "tracked"))
        for k in (5, 10, 25, 50, 100, 250):
            kept = [l for l in legs if l["depth_at"] >= k]
            rem = [l for l in legs if l["depth_at"] < k]
            if not kept:
                continue
            cost = sum(l["size"] for l in kept) or 1e-9
            kw = {l["wallet"] for l in kept}
            print("  %-38s %5d %7.1f%% %10s %10s %7.1f%% %6d %5d/%d" % (
                "as-of-entry depth >= %d" % k, len(kept),
                100.0 * sum(l["size"] for l in kept) / base_cost,
                money(sum(l["pnl"] for l in rem)), money(sum(l["pnl"] for l in kept)),
                100.0 * sum(l["pnl"] for l in kept) / cost, len(kw), len(kw & tracked), len(tracked)))
        print("  tracked wallets in this lane: %d of %d source wallets here" % (len(tracked), len(all_wallets)))

    print("\nCAVEATS (printed because these numbers will be quoted):")
    print("  * IN-SAMPLE. Our book exists only where a wallet already cleared every gate, so a floor's")
    print("    'removed PnL' is measured on the legs we actually took — not on what the floor would have")
    print("    traded instead (no counterfactual book).")
    print("  * A floor also removes VOLUME, which is the input to the C-200 phase ladder (the ladder's goal")
    print("    is daily PnL, so a floor that raises edge%% while cutting cost can still slow the ladder).")
    print("  * Our as-of-entry depth is a LOWER BOUND on the wallet's true record: our observation window")
    print("    starts 2026-07-13, so a wallet that traded heavily before that reads thin.")
    print("  * Nothing here is a rule. Any floor is a separate proposal with its own pre-registered gate.")
    print("\nReproduce: python3 scripts/wallet-depth-floor-test.py   (reads %s; writes nothing)" % os.path.relpath(DB_PATH, ROOT))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
