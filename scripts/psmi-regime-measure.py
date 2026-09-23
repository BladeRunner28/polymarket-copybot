#!/usr/bin/env python3
"""
psmi-regime-measure — READ-ONLY: does Polycopy's Smart Money Index say anything
about OUR C-200 P&L? (roadmap card `polycopy-psmi-regime-measurement`,
2026-09-23).

WHY: PSMI is the only Polycopy surface with a sanctioned automated feed (keyless,
free with attribution, methodology 2.0.0): GET /api/indexes/smi/public (today's
score) and GET /api/indexes/smi/history?format=csv (daily closes, maxFreeDepth
24 months). Their /api/ is robots-DISALLOWED in general; these two are the
endpoints their own page advertises as free to use, and nothing else on /api/ may
be touched. The card's rule: measure first, gate nothing — a null result closes it.

WHAT IT DOES: joins the stored PSMI history (data/polycopy-psmi-history.csv) to our
own daily realized PnL bucketed by the SAME convention the ladder and the EOD
report use — LOCAL calendar day, `closedAt ?? resolvedAt`, status
closed|resolved, isDemo=0 — and prints:

  * the joined window, n (days), legs, realized/cost
  * level correlations (score + the four components) vs daily PnL, daily edge %
    and per-leg PnL, with a day-resampled bootstrap CI and a permutation p
  * the same with PSMI(t) vs PnL(t+k) for k = -2..+3 (lead/lag)
  * the ACTIVE vs WATCHING zone split, with a POOLED permutation test (shuffling
    inside one group cannot move its mean — that test is always p=1)
  * PSMI quintiles vs daily PnL / edge
  * leg-level metrics (win-leg share, median leg PnL) under a DAY-CLUSTERED
    bootstrap, because 1,872 legs in 45 days are not 1,872 independent draws
  * a throughput check (PSMI vs our legs and cost that day) — mechanically, an
    activity index could move HOW MUCH we trade without moving our edge
  * outlier sensitivity (drop the 2 best and 2 worst days)

Writes nothing. The stored CSV is the immovable record of what their API said;
scripts/fetch-psmi-history.py refreshes it.
"""
import csv
import datetime
import math
import os
import random
import sqlite3
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CSV_PATH = os.path.join(ROOT, "data", "polycopy-psmi-history.csv")
DB_PATH = os.path.join(ROOT, "prisma", "dev.db")
LANE = "BANKROLL_200"          # C-200
CONTROL = "STANDARD"
BOOT = 10000
PERM = 20000

random.seed(20260923)


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


def perm_p_pairs(xs, ys, stat, n=PERM):
    """Pairing permutation — valid for any association statistic."""
    obs = abs(stat(xs, ys))
    if not (obs == obs):
        return float("nan")
    cnt = 0
    y = list(ys)
    for _ in range(n):
        random.shuffle(y)
        if abs(stat(xs, y)) >= obs:
            cnt += 1
    return (cnt + 1) / (n + 1)


def boot_ci_days(days, fn, n=BOOT):
    """Percentile CI resampling whole DAYS (cluster bootstrap)."""
    vals = []
    for _ in range(n):
        sample = [days[random.randrange(len(days))] for _ in range(len(days))]
        v = fn(sample)
        if v == v and v not in (float("inf"), float("-inf")):
            vals.append(v)
    if len(vals) < 100:
        return (float("nan"), float("nan"))
    vals.sort()
    return (vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals))])


def pooled_perm(days, key, stat, n=PERM):
    """Permutation test for a two-group difference: pool, re-split, compare.
    Shuffling within one group leaves its mean untouched (p=1 always) — the
    groups must be re-drawn from the pooled values."""
    a = [d[key] for d in days if d["zone"] == "ACTIVE"]
    b = [d[key] for d in days if d["zone"] == "WATCHING"]
    if len(a) < 3 or len(b) < 3:
        return float("nan")
    obs = abs(stat(a) - stat(b))
    pool = a + b
    cnt = 0
    for _ in range(n):
        random.shuffle(pool)
        if abs(stat(pool[: len(a)]) - stat(pool[len(a):])) >= obs:
            cnt += 1
    return (cnt + 1) / (n + 1)


# ------------------------------------------------------------------ the data
def load_pnL_by_day():
    con = sqlite3.connect("file:%s?mode=ro" % DB_PATH, uri=True)
    rows = con.execute(
        """SELECT p.botId, p.realizedPnl, p.simulatedPositionSize, p.walletAddress,
                  p.marketId, p.outcome, COALESCE(p.closedAt, p.resolvedAt) AS fin
           FROM PaperTrade p
           WHERE p.isDemo = 0 AND p.status IN ('closed','resolved')
             AND COALESCE(p.closedAt, p.resolvedAt) IS NOT NULL"""
    ).fetchall()
    con.close()
    byday = {}
    for bot, pnl, size, wallet, market, outcome, fin in rows:
        day = datetime.datetime.fromtimestamp(fin / 1000.0).strftime("%Y-%m-%d")
        a = byday.setdefault((day, bot), {"n": 0, "pnl": 0.0, "cost": 0.0, "wins": 0, "legs": []})
        a["n"] += 1
        a["pnl"] += pnl or 0.0
        a["cost"] += size or 0.0
        a["wins"] += 1 if (pnl or 0.0) > 0 else 0
        a["legs"].append(pnl or 0.0)
    return byday


def build_series():
    byday = load_pnL_by_day()
    with open(CSV_PATH) as fh:
        ps = list(csv.DictReader(l for l in fh if not l.startswith("#")))
    out = []
    for i, r in enumerate(ps):
        day = r["date"]
        lane = byday.get((day, LANE), {"n": 0, "pnl": 0.0, "cost": 0.0, "wins": 0, "legs": []})
        ctl = byday.get((day, CONTROL), {"n": 0, "pnl": 0.0, "cost": 0.0, "wins": 0, "legs": []})
        prev = int(ps[i - 1]["score"]) if i > 0 else None
        out.append(
            dict(
                date=day, score=int(r["score"]), zone=r["zone"],
                momentum=int(r["momentum"]), breadth=int(r["breadth"]),
                participation=int(r["participation"]), conviction=int(r["conviction"]),
                delta=(int(r["score"]) - prev) if prev is not None else None,
                n=lane["n"], pnl=lane["pnl"], cost=lane["cost"],
                legs=lane["legs"],
                win_share=(lane["wins"] / lane["n"]) if lane["n"] else None,
                median_leg=statistics.median(lane["legs"]) if lane["legs"] else None,
                ctl_n=ctl["n"], ctl_pnl=ctl["pnl"], ctl_cost=ctl["cost"],
            )
        )
    return out


def money(v):
    return "%s$%.2f" % ("-" if v < 0 else "", abs(v))


def pct(v):
    return "n/a" if v != v or v is None else "%+.3f" % v


def main():
    series = build_series()
    act = [d for d in series if d["n"] > 0]
    if len(act) < 10:
        print("PSMI regime measure: only %d overlapping days — nothing to measure." % len(act))
        return
    legs = sum(d["n"] for d in act)
    pnl = sum(d["pnl"] for d in act)
    cost = sum(d["cost"] for d in act)
    print("PSMI regime measure — READ-ONLY, gates nothing")
    print("  window        : %s → %s (%d PSMI days, %d with >=1 settled C-200 leg)"
          % (series[0]["date"], series[-1]["date"], len(series), len(act)))
    print("  joined sample : %d legs, realized %s on %s cost (%.1f%% of cost)"
          % (legs, money(pnl), money(cost), 100.0 * pnl / cost))
    print("  daily legs    : min %d / median %d / max %d"
          % (min(d["n"] for d in act), statistics.median([d["n"] for d in act]), max(d["n"] for d in act)))

    # ---- level correlations
    print("\nLEVEL: PSMI vs our daily book (day-level, n=%d)" % len(act))
    metrics = [
        ("daily PnL $", lambda d: d["pnl"]),
        ("daily edge %", lambda d: (100.0 * d["pnl"] / d["cost"]) if d["cost"] > 0 else None),
        ("PnL per leg $", lambda d: (d["pnl"] / d["n"]) if d["n"] else None),
    ]
    for label, getter in metrics:
        print("  %s" % label)
        for comp in ("score", "momentum", "breadth", "participation", "conviction", "delta"):
            pairs = [(d[comp], getter(d)) for d in act if d[comp] is not None and getter(d) is not None]
            if len(pairs) < 10:
                continue
            xs = [p[0] for p in pairs]
            ys = [p[1] for p in pairs]
            days = [dict(pair=(a, b)) for a, b in pairs]
            lo, hi = boot_ci_days(days, lambda s: pearson([q["pair"][0] for q in s], [q["pair"][1] for q in s]))
            print("    %-14s pearson %s [%s, %s] perm p=%.3f  spearman %s (perm p=%.3f)"
                  % (comp, pct(pearson(xs, ys)), pct(lo), pct(hi),
                     perm_p_pairs(xs, ys, pearson),
                     pct(spearman(xs, ys)), perm_p_pairs(xs, ys, spearman)))

    # ---- lead / lag
    print("\nLEAD/LAG: PSMI(t) vs C-200 PnL(t+k)")
    for k in (0, 1, 2, 3):
        xs, ys = [], []
        for i in range(len(series) - k):
            if series[i + k]["n"] > 0:
                xs.append(series[i]["score"])
                ys.append(series[i + k]["pnl"])
        print("  +%dd  n=%2d  pearson %s (perm p=%.3f)  spearman %s"
              % (k, len(xs), pct(pearson(xs, ys)), perm_p_pairs(xs, ys, pearson), pct(spearman(xs, ys))))
    for k in (1, 2):
        xs, ys = [], []
        for i in range(k, len(series)):
            if series[i - k]["n"] > 0:
                xs.append(series[i]["score"])
                ys.append(series[i - k]["pnl"])
        print("  -%dd  n=%2d  pearson %s (perm p=%.3f)  spearman %s"
              % (k, len(xs), pct(pearson(xs, ys)), perm_p_pairs(xs, ys, pearson), pct(spearman(xs, ys))))

    # ---- zone split
    print("\nZONE SPLIT (pooled permutation — the only valid form)")
    for zone in ("ACTIVE", "WATCHING"):
        g = [d for d in act if d["zone"] == zone]
        if not g:
            continue
        p = [d["pnl"] for d in g]
        edge = [100.0 * d["pnl"] / d["cost"] for d in g if d["cost"] > 0]
        wins = [d["win_share"] for d in g if d["win_share"] is not None]
        print("  %-8s days=%2d legs=%4d mean %s median %s | win-days %d/%d (%.0f%%) | median edge %s | median win-leg share %.2f"
              % (zone, len(g), sum(d["n"] for d in g), money(statistics.mean(p)), money(statistics.median(p)),
                 sum(1 for v in p if v > 0), len(p), 100.0 * sum(1 for v in p if v > 0) / len(p),
                 ("%.1f%%" % statistics.median(edge)) if edge else "n/a",
                 statistics.median(wins) if wins else float("nan")))
    print("  perm p (mean PnL diff)   = %.3f" % pooled_perm(act, "pnl", statistics.mean))
    print("  perm p (median PnL diff) = %.3f" % pooled_perm(act, "pnl", statistics.median))

    # ---- quintiles
    print("\nPSMI QUINTILES (descending score)")
    g = sorted(act, key=lambda d: -d["score"])
    q = max(1, len(g) // 5)
    for i in range(5):
        sl = g[i * q:(i + 1) * q] if i < 4 else g[i * q:]
        if not sl:
            continue
        p = [d["pnl"] for d in sl]
        edge = [100.0 * d["pnl"] / d["cost"] for d in sl if d["cost"] > 0]
        print("  Q%d score %2d-%2d days=%2d legs=%4d mean %s median %s win-days %d/%d median edge %s"
              % (i + 1, sl[-1]["score"], sl[0]["score"], len(sl), sum(d["n"] for d in sl),
                 money(statistics.mean(p)), money(statistics.median(p)),
                 sum(1 for v in p if v > 0), len(p),
                 ("%.1f%%" % statistics.median(edge)) if edge else "n/a"))

    # ---- leg-level, day-clustered
    print("\nLEG-LEVEL (day-clustered bootstrap; %d legs in %d days — NOT independent draws)" % (legs, len(act)))
    a_legs = [d for d in act if d["zone"] == "ACTIVE"]
    w_legs = [d for d in act if d["zone"] == "WATCHING"]
    for label, grp in (("ACTIVE", a_legs), ("WATCHING", w_legs)):
        all_legs = [x for d in grp for x in d["legs"]]
        lo, hi = boot_ci_days(grp, lambda s: statistics.mean([x for d in s for x in d["legs"]]))
        print("  %-8s legs=%4d mean leg %s [%s, %s]  median leg %s  win-leg %.1f%%"
              % (label, len(all_legs), money(statistics.mean(all_legs)), money(lo), money(hi),
                 money(statistics.median(all_legs)),
                 100.0 * sum(1 for x in all_legs if x > 0) / len(all_legs)))
    hi_v = [d["win_share"] for d in act if d["score"] >= statistics.median([x["score"] for x in act]) and d["win_share"] is not None]
    lo_v = [d["win_share"] for d in act if d["score"] < statistics.median([x["score"] for x in act]) and d["win_share"] is not None]
    if hi_v and lo_v:
        print("  median win-leg share: PSMI >= median %.3f vs below %.3f (n=%d/%d days)"
              % (statistics.median(hi_v), statistics.median(lo_v), len(hi_v), len(lo_v)))

    # ---- throughput (how much we trade, not how well)
    print("\nTHROUGHPUT — does PSMI move how much we trade?")
    xs = [d["score"] for d in act]
    print("  legs/day      pearson %s (perm p=%.3f)  spearman %s"
          % (pct(pearson(xs, [d["n"] for d in act])), perm_p_pairs(xs, [d["n"] for d in act], pearson),
             pct(spearman(xs, [d["n"] for d in act]))))
    g = [d for d in act if d["cost"] > 0]
    print("  cost/day      pearson %s (perm p=%.3f)  spearman %s (n=%d)"
          % (pct(pearson([d["score"] for d in g], [d["cost"] for d in g])),
             perm_p_pairs([d["score"] for d in g], [d["cost"] for d in g], pearson),
             pct(spearman([d["score"] for d in g], [d["cost"] for d in g])), len(g)))

    # ---- control lane
    ctl = [d for d in series if d["ctl_n"] > 0]
    print("\nCONTROL: PSMI vs STANDARD daily PnL (n=%d days)" % len(ctl))
    print("  pearson %s (perm p=%.3f)  spearman %s"
          % (pct(pearson([d["score"] for d in ctl], [d["ctl_pnl"] for d in ctl])),
             perm_p_pairs([d["score"] for d in ctl], [d["ctl_pnl"] for d in ctl], pearson),
             pct(spearman([d["score"] for d in ctl], [d["ctl_pnl"] for d in ctl]))))

    # ---- outlier sensitivity
    print("\nOUTLIER SENSITIVITY (day-level, score vs PnL)")
    srt = sorted(act, key=lambda d: d["pnl"])
    for k in (0, 1, 2, 3):
        trimmed = srt[k:len(srt) - k] if k else srt
        xs = [d["score"] for d in trimmed]
        ys = [d["pnl"] for d in trimmed]
        print("  drop %d best + %d worst: n=%2d pearson %s (perm p=%.3f) spearman %s"
              % (k, k, len(trimmed), pct(pearson(xs, ys)), perm_p_pairs(xs, ys, pearson), pct(spearman(xs, ys))))
    best = srt[-1]
    tot = sum(d["pnl"] for d in act)
    top2 = srt[-1]["pnl"] + srt[-2]["pnl"]
    print("  concentration: best day %s %s (%d legs, PSMI %d); best 2 days = %.0f%% of the sample's realized PnL"
          % (best["date"], money(best["pnl"]), best["n"], best["score"], 100.0 * top2 / tot if tot else float("nan")))

    print("\nReproduce: python3 scripts/psmi-regime-measure.py   (reads %s + %s; writes nothing)"
          % (os.path.relpath(CSV_PATH, ROOT), os.path.relpath(DB_PATH, ROOT)))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
