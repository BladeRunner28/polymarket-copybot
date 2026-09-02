#!/usr/bin/env python3
"""
Astro Shadow comparison (Phase Astro-1) — does astrological sentiment show ANY
relationship with resolved paper PnL?

Reads ~/polymarket-copybot/data/astro-shadow.jsonl (daily D-tier astro scores
from src/astro_shadow.py) and joins against PaperTrade.resolvedAt / realizedPnl
in prisma/dev.db (read-only). Reports:

  * daily score vs daily realized PnL: Pearson correlation + sign agreement
  * retrograde-day vs non-retrograde-day mean/median daily PnL (Welch t)
  * new/full-moon window vs other days
  * eclipse-window vs other days

Output: console digest + data/astro-shadow-summary.json.
Usage:  python3 scripts/compare-astro.py
"""
import json
import math
import os
import sqlite3
import statistics
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASTRO_PATH = os.path.join(ROOT, "data", "astro-shadow.jsonl")
OUT = os.path.join(ROOT, "data", "astro-shadow-summary.json")
DB = os.path.join(ROOT, "prisma", "dev.db")

MIN_DAYS = 10  # need at least this many overlapping days before reporting


def load_astro():
    rows = []
    if os.path.exists(ASTRO_PATH):
        with open(ASTRO_PATH) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        pass
    return {r["day"]: r for r in rows}


def load_daily_pnl():
    """Daily realized PnL from paper trades (read-only connection).

    Attribution: closed (early-exit) trades use closedAt; market-resolved
    trades use resolvedAt. This covers the full realized-PnL history.
    """
    uri = "file:{}?mode=ro".format(DB)
    con = sqlite3.connect(uri, uri=True)
    con.execute("PRAGMA busy_timeout=8000")
    q = """
    SELECT d, botId, COUNT(*) AS n, SUM(pnl) AS pnl FROM (
      SELECT
        CASE WHEN closedAt > 1e12 THEN date(closedAt/1000,'unixepoch')
             ELSE date(closedAt) END AS d,
        botId, realizedPnl AS pnl
      FROM PaperTrade
      WHERE status='closed' AND realizedPnl IS NOT NULL AND closedAt IS NOT NULL
      UNION ALL
      SELECT
        CASE WHEN resolvedAt > 1e12 THEN date(resolvedAt/1000,'unixepoch')
             ELSE date(resolvedAt) END AS d,
        botId, realizedPnl
      FROM PaperTrade
      WHERE status='resolved' AND realizedPnl IS NOT NULL AND resolvedAt IS NOT NULL
    ) GROUP BY d, botId
    """
    cur = con.execute(q)
    by_day = {}
    for d, bot, n, pnl in cur.fetchall():
        if not d:
            continue
        e = by_day.setdefault(d, {"STANDARD": 0.0, "OTHER": 0.0, "n": 0})
        e["n"] += n
        key = bot if bot == "STANDARD" else "OTHER"
        e[key] += pnl or 0.0
    con.close()
    return by_day


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = statistics.mean(xs), statistics.mean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx == 0 or vy == 0:
        return None
    return cov / math.sqrt(vx * vy)


def welch(xs, ys):
    """Welch's t-statistic (positive => xs mean > ys mean)."""
    if len(xs) < 2 or len(ys) < 2:
        return None
    mx, my = statistics.mean(xs), statistics.mean(ys)
    vx, vy = statistics.variance(xs), statistics.variance(ys)
    nx, ny = len(xs), len(ys)
    se = math.sqrt(vx / nx + vy / ny)
    if se == 0:
        return None
    return (mx - my) / se


def summarize(rows, label):
    """rows: list of (astro_row, daily_pnl, n_trades)."""
    if len(rows) < MIN_DAYS:
        return {"label": label, "n": len(rows), "insufficient": True}
    scores = [r[0]["score"] for r in rows]
    pnls = [r[1] for r in rows]
    corr = pearson(scores, pnls)
    directional = [(s, p) for s, p in zip(scores, pnls) if abs(s) > 0.01]
    agree = sum(1 for s, p in directional if (s > 0) == (p > 0))
    return {
        "label": label,
        "n": len(rows),
        "meanPnl": round(statistics.mean(pnls), 2),
        "medianPnl": round(statistics.median(pnls), 2),
        "correlation": round(corr, 3) if corr is not None else None,
        "signAgreement": round(agree / len(directional), 3) if directional else None,
        "positiveDays": sum(1 for p in pnls if p > 0),
        "negativeDays": sum(1 for p in pnls if p < 0),
    }


def main():
    astro = load_astro()
    pnl = load_daily_pnl()
    days = sorted(set(astro) & set(pnl))
    print(f"astro rows: {len(astro)}  · resolved-PnL days: {len(pnl)}  · overlap: {len(days)}")

    if len(days) < MIN_DAYS:
        print(f"Not enough overlapping days yet (need {MIN_DAYS}); keep accumulating.")
        return

    rows = [(astro[d], pnl[d]["STANDARD"] + pnl[d]["OTHER"], pnl[d]["n"]) for d in days]
    summary = {"analyzedAt": datetime.now(timezone.utc).isoformat(), "overlapDays": len(days)}

    # 1. overall daily correlation
    overall = summarize(rows, "all days")
    summary["allDays"] = overall
    print(f"\n📐 ALL DAYS (n={overall['n']}): corr={overall['correlation']}  "
          f"sign-agree={overall['signAgreement']}  mean={overall['meanPnl']}  median={overall['medianPnl']}")

    # 2. retrograde vs not
    retro = [r for r in rows if r[0].get("retrogrades")]
    plain = [r for r in rows if not r[0].get("retrogrades")]
    s_retro = summarize(retro, "retrograde days")
    s_plain = summarize(plain, "non-retrograde days")
    summary["retrograde"] = {**s_retro, "tWelch": welch([r[1] for r in retro], [r[1] for r in plain])}
    summary["nonRetrograde"] = s_plain
    if "insufficient" in s_retro or "insufficient" in s_plain:
        print(f"\n🌑 RETROGRADE vs NON-RETRO: insufficient days (retro={s_retro.get('n',0)}, plain={s_plain.get('n',0)})")
    else:
        print(f"\n🌑 RETROGRADE (n={s_retro['n']}): mean={s_retro['meanPnl']} median={s_retro['medianPnl']}  vs  "
              f"NON-RETRO (n={s_plain['n']}): mean={s_plain['meanPnl']} median={s_plain['medianPnl']}  "
              f"t={summary['retrograde']['tWelch']}")

    # 3. new/full moon windows vs others
    moon = [r for r in rows if any(e in r[0].get("events", []) for e in ("new moon window", "full moon window"))]
    not_moon = [r for r in rows if r not in moon]
    s_moon = summarize(moon, "new/full moon days")
    s_not_moon = summarize(not_moon, "other days")
    summary["moonWindows"] = {**s_moon, "tWelch": welch([r[1] for r in moon], [r[1] for r in not_moon])}
    summary["nonMoon"] = s_not_moon
    if "insufficient" in s_moon or "insufficient" in s_not_moon:
        print(f"\n🌕 NEW/FULL MOON vs OTHER: insufficient days (moon={s_moon.get('n',0)}, other={s_not_moon.get('n',0)})")
    else:
        print(f"\n🌕 NEW/FULL MOON (n={s_moon['n']}): mean={s_moon['meanPnl']} median={s_moon['medianPnl']}  vs  "
              f"OTHER (n={s_not_moon['n']}): mean={s_not_moon['meanPnl']} median={s_not_moon['medianPnl']}  "
              f"t={summary['moonWindows']['tWelch']}")

    # 4. eclipse windows vs others
    ecl = [r for r in rows if any("eclipse" in e for e in r[0].get("events", []))]
    not_ecl = [r for r in rows if r not in ecl]
    s_ecl = summarize(ecl, "eclipse window days")
    s_not_ecl = summarize(not_ecl, "other days")
    summary["eclipseWindows"] = {**s_ecl, "tWelch": welch([r[1] for r in ecl], [r[1] for r in not_ecl])}
    summary["nonEclipse"] = s_not_ecl
    if "insufficient" in s_ecl or "insufficient" in s_not_ecl:
        print(f"\n🌘 ECLIPSE WINDOWS vs OTHER: insufficient days (ecl={s_ecl.get('n',0)}, other={s_not_ecl.get('n',0)})")
    else:
        print(f"\n🌘 ECLIPSE WINDOWS (n={s_ecl['n']}): mean={s_ecl['meanPnl']} median={s_ecl['medianPnl']}  vs  "
              f"OTHER (n={s_not_ecl['n']}): mean={s_not_ecl['meanPnl']} median={s_not_ecl['medianPnl']}  "
              f"t={summary['eclipseWindows']['tWelch']}")

    # 5. verdict — use the correlation t-statistic (|t|>=2 ≈ p<0.05 at n≈47)
    corr = overall["correlation"]
    n = overall["n"]
    if corr is not None and n > 3:
        t_corr = corr * math.sqrt((n - 2) / (1 - corr * corr))
    else:
        t_corr = None
    summary["corrTStat"] = round(t_corr, 2) if t_corr is not None else None
    t_abs = abs(t_corr) if t_corr is not None else 0.0
    if t_corr is None or t_abs < 2:
        verdict = (
            f"NO SIGNIFICANT SIGNAL — corr={corr}, |t|={t_abs:.1f} (within noise). "
            "Keep accumulating shadow data; do not promote."
        )
    elif abs(corr) < 0.3:
        verdict = "WEAK SIGNAL — worth extending the shadow observation before any promotion decision."
    else:
        verdict = "NOTABLE SIGNAL — flag for careful replication before any promotion (D-tier cap applies)."
    summary["verdict"] = verdict
    print(f"\n⚖️  VERDICT: {verdict}")

    with open(OUT, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
