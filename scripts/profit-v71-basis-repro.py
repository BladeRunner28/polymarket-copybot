#!/usr/bin/env python3
"""WHICH BASIS REPRODUCES THE 2026-11-03 v71 NUMBERS? (read-only diagnostic)

v71 (shortTtrDeadZoneBandFactor 0.25->0.5, shortTtrPremiumBandFactor 0.5->2.0) was justified by:
  regime v49+, 1,168 bets / $13,111 / 57.4d / +$55.24 a day
  short-TTR 0.60-0.80 = +24.4% CI [+14.5,+32.6]   (z=4.00, ex-top-5 keeps 86%)
  short-TTR 0.40-0.60 = +22.6% CI [+10.2,+34.9]   (z=2.52, 290 markets)

Run on the closed+resolved basis those same cells read +3.9% and +5.1% -- a 20pp gap that looks
like a defect and is not. This script walks the plausible variants so the difference is
ATTRIBUTED rather than argued about. The answer (2026-11-04): the prior draft was on
status='resolved' only, i.e. the conditional edge given that our own 24h adverse stop did not
intervene. Both bases are legitimate; the defect was leaving it unstated.

Lane attribution here is the journal label ('Short-TTR lane' in DecisionJournal.reasonsJson),
which is authoritative. A snapshot-TTR proxy is printed for comparison because it disagrees on
68% of main-lane legs and using it silently moves every cell.

USAGE  python3 scripts/profit-v71-basis-repro.py
"""
import sqlite3
import numpy as np

con = sqlite3.connect("file:prisma/dev.db?mode=ro", uri=True)
con.row_factory = sqlite3.Row
BANDS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0001)]


def band_of(p):
    for lo, hi in BANDS:
        if lo <= p < hi:
            return f"{lo:.1f}-{hi:.1f}" if hi <= 1 else "0.8-1.0"


def cluster_ci(legs, reps=1500, seed=7):
    by = {}
    for l in legs:
        by.setdefault(l["m"], []).append(l)
    keys = list(by)
    if len(keys) < 3:
        return (0.0, 0.0)
    rng = np.random.default_rng(seed)
    out = np.empty(reps)
    for i in range(reps):
        pick = rng.integers(0, len(keys), len(keys))
        sp = sn = 0.0
        for j in pick:
            for l in by[keys[j]]:
                sp += l["p"]
                sn += l["n"]
        out[i] = 100 * sp / sn if sn else 0.0
    return float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))


def pull(status_clause, min_rule=49):
    sql = f"""
      SELECT p.botId, p.walletAddress, p.marketId, p.outcome, p.entryPrice, p.simulatedPositionSize n,
             p.realizedPnl p, p.openedAt, p.closedAt, p.resolvedAt, j.reasonsJson rj
      FROM PaperTrade p JOIN DecisionJournal j ON p.decisionJournalId=j.id
      WHERE p.isDemo=0 AND p.realizedPnl IS NOT NULL AND p.entryPrice>0
        AND p.simulatedPositionSize>0 AND j.ruleSetVersion>=? AND {status_clause}
      ORDER BY p.openedAt ASC"""
    tc, out = {}, []
    for r in con.execute(sql, (min_rule,)).fetchall():
        end = r["resolvedAt"] or r["closedAt"]
        if not end:
            continue
        ck = (r["marketId"], r["openedAt"] // 3_600_000)
        if ck not in tc:
            s = con.execute("""SELECT timeToResolution FROM MarketSnapshot
                 WHERE marketId=? AND collectedAt<=? AND timeToResolution IS NOT NULL
                 ORDER BY collectedAt DESC LIMIT 1""",
                            (r["marketId"], r["openedAt"] + 900_000)).fetchone()
            tc[ck] = s[0] if s else None
        ttr = tc[ck]
        if r["botId"] != "BANKROLL_200":
            lane = "standard"
        elif r["rj"] and "Short-TTR lane" in r["rj"]:
            lane = "shttr"
        else:
            lane = "c200main"
        proxy = "shttr" if (ttr is not None and 2 <= ttr <= 72) else "c200main"
        out.append({"bot": r["botId"], "lane": lane, "proxy": proxy, "m": r["marketId"],
                    "w": r["walletAddress"], "o": r["outcome"], "b": band_of(r["entryPrice"]),
                    "n": r["n"], "p": r["p"], "px": r["entryPrice"], "ttr": ttr,
                    "hold": max((end - r["openedAt"]) / 86_400_000, 1 / 24)})
    return out


def dedupe(legs):
    seen, out = set(), []
    for l in legs:
        k = (l["bot"], l["w"], l["m"], l["o"])
        if k in seen:
            continue
        seen.add(k)
        out.append(l)
    return out


def report(tag, legs):
    n = sum(l["n"] for l in legs)
    span = (max(l["px"] for l in legs) * 0 + 1)  # placeholder to keep signature stable
    print(f"\n{tag:52} bets={len(legs):>5} notional=${n:>8,.0f} "
          f"PnL=${sum(l['p'] for l in legs):>+8,.0f} "
          f"roi={100*sum(l['p'] for l in legs)/n if n else 0:>+6.1f}%")
    for lane in ("standard", "c200main", "shttr"):
        for b in ("0.4-0.6", "0.6-0.8"):
            g = [l for l in legs if l["lane"] == lane and l["b"] == b]
            if len(g) < 5:
                continue
            nn = sum(l["n"] for l in g)
            lo, hi = cluster_ci(g)
            print(f"    {lane:10} {b} n={len(g):>4} ntl=${nn:>7,.0f} "
                  f"roi={100*sum(l['p'] for l in g)/nn:>+6.1f}% CI[{lo:+.1f},{hi:+.1f}]")


print("=" * 100)
print("VARIANTS -- which population/filter reproduces the 2026-11-03 numbers?")
print("=" * 100)
report("A closed+resolved, journal join, no dedupe", pull("p.status IN ('closed','resolved')"))
report("B same + dedupe (the standard bet-level basis)", dedupe(pull("p.status IN ('closed','resolved')")))
report("C RESOLVED ONLY + dedupe  <-- reproduces the v71 draft", dedupe(pull("p.status='resolved'")))
report("D resolved only, no dedupe", pull("p.status='resolved'"))

legs = dedupe(pull("p.status IN ('closed','resolved')"))
print("\nLANE ATTRIBUTION check (journal label vs snapshot-TTR proxy)")
for lane in ("c200main", "shttr"):
    g = [l for l in legs if l["lane"] == lane]
    agree = sum(1 for l in g if l["proxy"] == lane)
    print(f"   journal {lane:9} n={len(g):>4} proxy agrees on {100*agree/max(len(g),1):>5.1f}% of legs")
