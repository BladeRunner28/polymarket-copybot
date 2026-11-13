#!/usr/bin/env python3
"""
sizing-rails-read.py — the sizing read behind drafts/sizing-rails-proposal-20261112.md

Answers three questions, in the order they have to be answered:

  1. WHICH RAIL BINDS?  Three "max size" numbers exist and they disagree.
       BotBankroll.minPositionSize / maxPositionSize   (the advertisable table row)
       BOT_LIMITS                                      (src/lib/safety.ts, legacy path)
       rules.kellyMaxSizeUsd                           (RuleSet, Kelly path, C-200 only)
     The ceilings are PARSED from their real sources (safety.ts, the ACTIVE RuleSet,
     BotBankroll) — never retyped here. A second hand-written copy of this arithmetic is
     the defect this repo has paid for three times (the $30 rail, the duplicated rule
     values, the ML_LANE $100 rail).

  2. IS SIZE ALLOCATED TO EDGE?  Per lane. Both lanes on one shared denominator, because
     the portfolio aggregate is dominated by whichever lane holds the notional and the two
     lanes have disagreed in sign.

  3. WHAT DRIVES SIZE NOW?  STANDARD's clip is a deterministic function of the score bucket
     and, since v68, of the time-to-resolution (maturity) bucket. If the clip carries no
     edge information, the allocation question is about the MECHANISM, not about weights.

METHOD / label basis (these are not interchangeable and are printed with every figure)
  cost basis          PaperTrade.simulatedPositionSize = DOLLARS AT RISK. NOT multiplied by
                      entryPrice: that error once inflated a band ROI ~8x in this repo.
  realised population status IN ('closed','resolved') — TR-15 OR, never resolvedAt alone
                      (73.9% of finished legs exit early; a resolved-only population is
                      winner-skewed: base win 48.4% -> 62.7% on resolved only).
  label               realizedPnl (a leg's OWN realised result). NOT the market outcome.
                      A leg that exited early carries the exit policy in its label, so every
                      ROI below answers "was this leg profitable", not "did the signal
                      predict the market". Any arm whose population is resolved-only says so
                      on the line.
  dedupe              first leg per (wallet, market, outcome), ordered by openedAt.
  CI                  market-clustered bootstrap (legs inside one market share an outcome).
  regime              DecisionJournal.ruleSetVersion, never openedAt.

Run: .venv-ml/bin/python scripts/sizing-rails-read.py [--db prisma/dev.db]
Writes nothing. Opens the DB immutable=1 so a live writer cannot be blocked by it.
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict

import numpy as np

SAFETY_TS = "src/lib/safety.ts"
MATURITY_SHORT_H = 24.0
MATURITY_LONG_H = 72.0
MATURITY_HUGE_H = 168.0


# ---------------------------------------------------------------- source-of-truth readers

def parse_bot_limits(path=SAFETY_TS):
    """BOT_LIMITS straight out of safety.ts — the file that enforces it."""
    src = open(path, encoding="utf-8").read()
    block = re.search(r"BOT_LIMITS[^{]*\{(.*?)\n\}", src, re.S)
    if not block:
        raise SystemExit("BOT_LIMITS block not found in %s" % path)
    limits = {}
    for bot, mn, mx in re.findall(
        r"(\w+)\s*:\s*\{\s*min:\s*([\d.]+)\s*,\s*max:\s*([\d.]+)\s*\}", block.group(1)
    ):
        limits[bot] = {"min": float(mn), "max": float(mx)}
    if not limits:
        raise SystemExit("BOT_LIMITS parsed empty — refusing to report a fake rail")
    return limits


def active_rules(con):
    row = con.execute(
        "SELECT version, rulesJson FROM RuleSet WHERE active=1 ORDER BY version DESC LIMIT 1"
    ).fetchone()
    if not row:
        raise SystemExit("no active RuleSet")
    return row[0], json.loads(row[1])


def effective_rails(bot, limits, rules):
    """Mirror of clampPaperSize: hi = maxUsd !== undefined ? max(limits.min, maxUsd) : limits.max
    and of isKellyCandidate: botId === 'BANKROLL_200' (Kelly is C-200 ONLY)."""
    has = bot in limits
    lim = limits.get(bot) or limits["STANDARD"]
    kelly_max = None
    if bot == "BANKROLL_200" and rules.get("kellyEnabled") == 1:
        kelly_max = max(lim["min"], float(rules.get("kellyMaxSizeUsd", 0)))
    hi = lim["max"] if kelly_max is None else max(lim["max"], kelly_max)
    return {"min": lim["min"], "max": hi, "legacy_max": lim["max"],
            "kelly_max": kelly_max, "has_bot_limits": has}


# ---------------------------------------------------------------- stats

def cluster_ci(pairs, iters=1200, seed=7):
    """Market-clustered bootstrap over per-leg ratios."""
    by = defaultdict(list)
    for m, v in pairs:
        by[m].append(v)
    groups = [np.array(v, dtype=float) for v in by.values() if v]
    if len(groups) < 2:
        return (float("nan"), None, None, len(groups))
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(iters):
        idx = rng.integers(0, len(groups), len(groups))
        means.append(np.concatenate([groups[i] for i in idx]).mean())
    means.sort()
    allv = np.concatenate(groups)
    return (float(allv.mean()), float(means[int(0.025 * len(means))]),
            float(means[int(0.975 * len(means))]), len(groups))


def rankdata(x):
    """Average ranks with tie correction (no scipy dependency)."""
    x = np.asarray(x, dtype=float)
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(len(x), dtype=float)
    i = 0
    while i < len(x):
        j = i
        while j + 1 < len(x) and x[order[j + 1]] == x[order[i]]:
            j += 1
        ranks[order[i:j + 1]] = 0.5 * (i + j) + 1.0
        i = j + 1
    return ranks


def spearman(a, b):
    if len(a) < 3:
        return float("nan")
    ra, rb = rankdata(a), rankdata(b)
    if ra.std() == 0 or rb.std() == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


# ---------------------------------------------------------------- data

def load_legs(con, bot):
    q = """
    SELECT p.walletAddress, p.marketId, p.outcome, p.simulatedPositionSize,
           COALESCE(p.realizedPnl, 0), p.openedAt, p.resolvedAt, p.status,
           d.ruleSetVersion
    FROM PaperTrade p
    LEFT JOIN DecisionJournal d ON d.id = p.decisionJournalId
    WHERE p.botId = ? AND p.isDemo = 0 AND p.status IN ('closed','resolved')
      AND p.simulatedPositionSize > 0
    ORDER BY p.openedAt ASC
    """
    seen, rows = set(), []
    for w, m, o, size, pnl, opened, resolved, status, ver in con.execute(q, (bot,)):
        key = (w, m, o)
        if key in seen:
            continue
        seen.add(key)
        size = float(size)
        rows.append({
            "market": m, "size": size, "pnl": float(pnl), "roi": float(pnl) / size,
            "opened": opened, "resolved": resolved, "status": status,
            "ver": ver, "ttr_h": ((resolved - opened) / 3600000.0
                                  if (status == "resolved" and resolved and opened) else None),
        })
    return rows


# ---------------------------------------------------------------- reporting

def fmt_ci(lo, hi):
    return "[%+.1f, %+.1f]" % (lo * 100, hi * 100) if lo is not None else "n/a"


def line(label, rows, indent="  "):
    if not rows:
        print("%s%-28s n=0" % (indent, label))
        return None
    cost = sum(r["size"] for r in rows)
    pnl = sum(r["pnl"] for r in rows)
    m, lo, hi, k = cluster_ci([(r["market"], r["roi"]) for r in rows])
    med = int(np.median([r["opened"] for r in rows]))
    print("%s%-28s n=%5d  cost $%9.0f  PnL $%9.2f  dwROI %+7.2f%%  unweighted %+7.2f%%  CI %s  mkt=%3d  medOpen %s"
          % (indent, label, len(rows), cost, pnl, pnl / cost * 100, m * 100, fmt_ci(lo, hi), k,
             __import__("datetime").datetime.utcfromtimestamp(med / 1000).strftime("%Y-%m-%d")))
    return {"n": len(rows), "cost": cost, "pnl": pnl, "dw": pnl / cost, "uw": m,
            "lo": lo, "hi": hi, "median_open": med}


def buckets_by_size(rows, name):
    """Quartile buckets on UNIQUE clip values, so a point mass cannot create an empty bucket."""
    sizes = np.array([r["size"] for r in rows])
    uniq = np.unique(sizes)
    if len(uniq) <= 4:
        edges = list(uniq)
        print("\n  -- ROI by clip value (only %d distinct clips exist — percentile quintiles would "
              "collapse to empty buckets) --" % len(uniq))
    else:
        qs = np.percentile(sizes, [20, 40, 60, 80])
        edges = sorted(set([float(np.min(uniq))] + [float(q) for q in qs] + [float(np.max(uniq))]))
        print("\n  -- ROI by clip size (quartile edges on unique values: %s) --"
              % ", ".join("$%.2f" % e for e in edges))
    out = []
    for i, lo in enumerate(edges[:-1] if len(edges) > 1 else edges):
        hi = edges[i + 1] if len(edges) > 1 else None
        if hi is None or hi == lo:
            sel = [r for r in rows if r["size"] == lo]
        elif i == len(edges) - 2:
            # TOP bucket is INCLUSIVE of the maximum, or the clamp boundary ($20 STANDARD,
            # $100 C-200) — the single most decision-relevant cohort — silently drops out.
            sel = [r for r in rows if lo <= r["size"] <= hi]
        else:
            sel = [r for r in rows if lo <= r["size"] < hi]
        s = line("%s$%.2f%s" % ("" if len(edges) > 1 else "", lo, "-$%.2f" % hi if hi is not None else ""), sel)
        if s:
            out.append((lo, s))
    if len(out) >= 3:
        corr = spearman([r["size"] for r in rows], [r["roi"] for r in rows])
        bcorr = spearman([o[0] for o in out], [o[1]["uw"] for o in out])
        print("\n  size-vs-edge rank correlation (Spearman, leg level): %+.3f   "
              "(bucket level: %+.3f)" % (corr, bcorr))
        print("    +1 = capital concentrated where the edge is; -1 = allocated inversely to edge.")
    return out


def clip_histogram(rows, indent="  "):
    c = Counter(round(r["size"], 2) for r in rows)
    tot = sum(c.values())
    top = c.most_common(8)
    print("%sdistinct clip values: %d of %d legs" % (indent, len(c), tot))
    for val, n in top:
        print("%s  $%8.2f  %5d legs  %5.1f%%" % (indent, val, n, n / tot * 100))


def ttr_arm(rows, indent="  "):
    """resolved-only: hours-to-resolution proxy = resolvedAt - openedAt (the market's own life)."""
    live = [r for r in rows if r["ttr_h"] is not None]
    print("\n  -- ROI by time-to-resolution at entry (RESOLVED-ONLY arm: n=%d of %d legs; "
          "winner-skewed, see header) --" % (len(live), len(rows)))
    bands = [("0-24h  (v68 x0.5)", lambda h: h < MATURITY_SHORT_H),
             ("24-72h (v68 x1.0)", lambda h: MATURITY_SHORT_H <= h < MATURITY_LONG_H),
             ("72-168h(v68 x1.5)", lambda h: MATURITY_LONG_H <= h < MATURITY_HUGE_H),
             (">168h  (v68 x1.0)", lambda h: h >= MATURITY_HUGE_H)]
    out = []
    for label, pred in bands:
        sel = [r for r in live if pred(r["ttr_h"])]
        s = line(label, sel, indent)
        if s:
            out.append((label, s))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="prisma/dev.db")
    args = ap.parse_args()
    if not os.path.exists(args.db):
        raise SystemExit("no db at %s" % args.db)

    limits = parse_bot_limits()
    con = sqlite3.connect("file:%s?immutable=1" % args.db, uri=True)
    version, rules = active_rules(con)

    print("=" * 132)
    print("SIZING RAILS READ — which ceiling binds, and is size allocated to edge?")
    print("=" * 132)
    print("db %s (%d bytes, mtime %s) · active RuleSet v%d · read immutable=1, writes nothing"
          % (args.db, os.path.getsize(args.db),
             __import__("datetime").datetime.utcfromtimestamp(int(os.path.getmtime(args.db))).strftime("%Y-%m-%d %H:%M"),
             version))

    print("\n1. THE THREE RAILS, EACH READ FROM ITS OWN SOURCE")
    print("   %-14s %10s %10s %10s %10s   %s" % ("bot", "table min", "table max", "BOT_LIMITS", "kellyMax", "effective"))
    table = {r[0]: (r[1], r[2]) for r in con.execute(
        "SELECT botId, minPositionSize, maxPositionSize FROM BotBankroll")}
    for bot in sorted(set(list(limits.keys()) + list(table.keys()))):
        t = table.get(bot)
        e = effective_rails(bot, limits, rules)
        print("   %-14s %10s %10s %10s %10s   min $%.2f  max $%.2f%s"
              % (bot,
                 "$%.2f" % t[0] if t else "-", "$%.2f" % t[1] if t else "-",
                 "$%.2f/$%.2f" % (e["legacy_max"], e["min"]) if e["has_bot_limits"] else "NO ENTRY",
                 "$%.2f" % e["kelly_max"] if e["kelly_max"] is not None else "-",
                 e["min"], e["max"],
                 "" if e["has_bot_limits"] else "   <- falls back to STANDARD"))
    print("   kellyEnabled=%s kellyMaxSizeUsd=%s (v%d)"
          % (rules.get("kellyEnabled"), rules.get("kellyMaxSizeUsd"), version))

    print("\n2. SIZE vs EDGE, PER LANE")
    print("   LABEL BASIS: realizedPnl on closed|resolved, deduped first leg per (wallet,market,outcome).")
    print("   dwROI = dollar-weighted (where the dollars went). unweighted = typical leg. Not the same question.")

    summary = {}
    for bot in ("BANKROLL_200", "STANDARD"):
        rows = load_legs(con, bot)
        e = effective_rails(bot, limits, rules)
        if not rows:
            continue
        print("\n" + "-" * 132)
        print("%s — %d realised legs" % (bot, len(rows)))
        alls = line("all", rows)
        summary[bot] = {"all": alls, "effective": e}

        # --- advertised-rail falsification
        over_advert = [r for r in rows if table.get(bot) and r["size"] > table[bot][1]]
        over_code = [r for r in rows if r["size"] > e["legacy_max"]]
        at_kelly = [r for r in rows if e["kelly_max"] is not None and r["size"] >= e["kelly_max"] - 1e-9]
        print("   clips above the TABLE max ($%.2f): %d legs / $%.2f notional / max $%.2f"
              % (table[bot][1] if table.get(bot) else 0, len(over_advert),
                 sum(r["size"] for r in over_advert),
                 max([r["size"] for r in over_advert] or [0])))
        print("   clips above BOT_LIMITS legacy max ($%.2f): %d legs / $%.2f notional"
              % (e["legacy_max"], len(over_code), sum(r["size"] for r in over_code)))
        if e["kelly_max"] is not None:
            print("   clips AT the Kelly ceiling ($%.2f): %d legs / $%.2f notional  (max clip $%.2f)"
                  % (e["kelly_max"], len(at_kelly), sum(r["size"] for r in at_kelly),
                     max(r["size"] for r in rows)))

        print("\n   clip distribution")
        clip_histogram(rows, "   ")
        buckets_by_size(rows, bot)
        ttr_arm(rows, "   ")

        # --- era split (regime = journal ruleSetVersion)
        for lo, hi, name in ((0, 67, "pre-v68"), (68, 10 ** 6, "v68+")):
            sel = [r for r in rows if r["ver"] is not None and lo <= r["ver"] <= hi]
            if not sel:
                print("\n   ERA %s: no legs with a journal ruleSetVersion in range" % name)
                continue
            print("\n   ERA %s (journal ruleSetVersion %s-%s)" % (name, lo, hi))
            line("  era total", sel, "   ")
            clip_histogram(sel, "     ")
            buckets_by_size(sel, bot)
        unknown = [r for r in rows if r["ver"] is None]
        if unknown:
            print("\n   %d legs carry no ruleSetVersion (pre-journal) — excluded from the era split only"
                  % len(unknown))

    print("\n3. CONCENTRATION CHECK on the biggest clip bucket (is the edge one leg?)")
    for bot in ("BANKROLL_200", "STANDARD"):
        rows = load_legs(con, bot)
        if not rows:
            continue
        top = sorted(rows, key=lambda r: -r["size"])[:max(1, len(rows) // 4)]
        for drop in (0, 5):
            sel = sorted(top, key=lambda r: -r["pnl"])[drop:]
            line("%s top-quartile clip, ex-top-%d pnl" % (bot, drop), sel, "   ")

    print("\n4. ARE THE CLIPS THAT EXCEED THE LEGACY CEILING PAYING? (the Kelly override's value test)")
    print("   C-200 is the only lane that can exceed BOT_LIMITS ($20) — the Kelly path passes maxUsd.")
    band_plan = {
        "BANKROLL_200": [(0, 5, "$0-5"), (5, 10, "$5-10"), (10, 20, "$10-20"),
                         (20, 50, "$20-50  (Kelly override)"), (50, 100, "$50-99"),
                         (100, 1e9, "$100 = kellyMaxSizeUsd")],
        "STANDARD": [(0, 8, "$0-8"), (8, 12.2, "$8-12.20"), (12.2, 18, "$12.20-18"),
                     (18, 1e9, "$18-20 (top own bucket)")],
    }
    for bot in ("BANKROLL_200", "STANDARD"):
        rows = load_legs(con, bot)
        if not rows:
            continue
        print("\n   %s" % bot)
        for lo, hi, name in band_plan[bot]:
            sel = [r for r in rows if lo <= r["size"] < hi or (hi > 1e8 and r["size"] >= lo)]
            s = line(name, sel, "     ")
            if s and len(sel) >= 20:
                ex = sorted(sel, key=lambda r: -r["pnl"])[5:]
                line("  ex-top-5 pnl", ex, "     ")
        # what if the Kelly ceiling were lowered to the legacy $20?
        if bot == "BANKROLL_200":
            over = [r for r in rows if r["size"] > 20.0]
            if over:
                cost = sum(r["size"] for r in over)
                pnl = sum(r["pnl"] for r in over)
                capped = sum(min(r["size"], 20.0) for r in over)
                scaled = sum(r["pnl"] * min(r["size"], 20.0) / r["size"] for r in over)
                print("\n     COUNTERFACTUAL: cap every clip at the legacy $20 ceiling")
                print("       clipped population n=%d  cost $%.2f -> $%.2f  PnL $%.2f -> $%.2f "
                      "(PnL rescaled linearly in size; paper PnL is linear)"
                      % (len(over), cost, capped, pnl, scaled))
                print("       delta on the lane's realised PnL: $%+.2f" % (scaled - pnl))

    print("\n5. STANDARD CAP COUNTERFACTUALS (paper PnL is linear in size, so rescale each leg by min(cap,size)/size)")
    print("   UPPER BOUND ONLY: no re-selection, no clamp re-entry, no gate interaction. The legs above a cap are not")
    print("   a random sample — they are the high-score era's biggest clips, so this prices a ceiling, not a rule.")
    rows = load_legs(con, "STANDARD")
    v68 = [r for r in rows if r["ver"] is not None and r["ver"] >= 68]
    for cap in (12.0, 14.0, 16.0, 18.0, 20.0):
        for label, pop in (("all", rows), ("v68+", v68)):
            if not pop:
                continue
            base = sum(r["pnl"] for r in pop)
            scaled = sum(r["pnl"] * min(cap, r["size"]) / r["size"] for r in pop)
            cost0 = sum(r["size"] for r in pop)
            cost1 = sum(min(cap, r["size"]) for r in pop)
            top10 = set(id(r) for r in sorted(pop, key=lambda r: -r["pnl"])[:10])
            b10 = sum(r["pnl"] for r in pop if id(r) not in top10)
            s10 = sum(r["pnl"] * min(cap, r["size"]) / r["size"] for r in pop
                      if id(r) not in top10)
            ncut = sum(1 for r in pop if r["size"] > cap)
            print("   cap $%5.2f  %-4s  n=%4d (cut %3d)  cost $%8.0f -> $%8.0f  PnL $%8.2f -> $%8.2f  "
                  "delta $%+8.2f   ex-top-10 delta $%+8.2f   dwROI %+.2f%% -> %+.2f%%"
                  % (cap, label, len(pop), ncut, cost0, cost1, base, scaled, scaled - base,
                     s10 - b10, base / cost0 * 100, scaled / cost1 * 100))

    print("\n   POWER of the cap question (market-clustered delta, how many markets before a CI could exclude zero):")
    by = defaultdict(list)
    for r in rows:
        by[r["market"]].append(r)
    for cap in (12.0, 14.0, 16.0):
        d = []
        for m, legs in by.items():
            d.append(sum(r["pnl"] * (min(cap, r["size"]) / r["size"] - 1.0) for r in legs))
        d = np.array(d)
        mean, sd = d.mean(), d.std(ddof=1)
        need = (1.959964 * sd / abs(mean)) ** 2 if mean != 0 else float("inf")
        mde = 1.959964 * sd / np.sqrt(len(d))
        print("     cap $%.2f: per-market delta mean $%+.3f  SD $%.2f  (n=%d mkts)  "
              "-> MDE now $%.2f/market = $%.0f all-time; a CI would exclude zero at ~%d markets"
              % (cap, mean, sd, len(d), mde, mde * len(d),
                 int(np.ceil(need)) if need == need else -1))

    print("\n" + "=" * 132)
    print("READ: a ceiling nobody reaches is not a rail. Coverage/era caveats are in the header, not optional.")
    print("=" * 132)
    return 0


if __name__ == "__main__":
    sys.exit(main())
