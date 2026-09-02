#!/usr/bin/env python3
"""Significance-tested calibration + hourly-returns analysis on the copybot's
own finished paper trades (port of the jon-becker/prediction-market-analysis
excess-return pattern, MIT).

For each entry-price band and each hour-of-day (ET), computes:
  win_rate, excess_return (win_rate - mean entry price), z-stat (two-sided),
  p-value, N, and realized PnL.

Excess-return framing: a binary contract bought at price p pays $1 on win, so
per-contract edge = E[won] - p = win_rate - p. se = sqrt(wr(1-wr)/N) under the
null (fair pricing). |z| >= 2 marks a bucket whose edge is unlikely to be noise
-- the significance layer the daily PnL buckets don't have.

Output: console table + data/calibration-analysis.json (for the dashboard /
daily report). No new dependencies -- stdlib sqlite3 + math only.

Usage (project root):  python3 scripts/analyze-calibration.py [--bot BANKROLL_200]
"""
import argparse
import json
import math
import os
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "prisma", "dev.db")
OUT = os.path.join(ROOT, "data", "calibration-analysis.json")
MIN_BAND_N = 20

# Same bands as calibrate-premium.py / the daily report.
BANDS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]


def two_sided_p(z: float) -> float:
    """p = 2*(1 - Phi(|z|)) via math.erf (no scipy needed)."""
    return 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(z) / math.sqrt(2.0))))


def finish_time_ms(row) -> int:
    """openedAt/resolvedAt are Unix-ms ints in dev.db (or ISO strings)."""
    v = row
    if isinstance(v, str):
        try:
            return int(datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp() * 1000)
        except ValueError:
            return 0
    return int(v or 0)


def band_stats(rows):
    """rows: [(entryPrice, won, realizedPnl)]. Returns band stats dict."""
    n = len(rows)
    wr = sum(1 for _, w, _ in rows if w) / n if n else 0.0
    avg_p = sum(p for p, _, _ in rows) / n if n else 0.0
    excess = wr - avg_p
    se = math.sqrt(wr * (1 - wr) / n) if n else 0.0
    z = excess / se if se > 0 else 0.0
    pnl = sum(pnl for _, _, pnl in rows)
    return {
        "n": n,
        "winRate": round(wr, 4),
        "avgEntry": round(avg_p, 4),
        "excessReturn": round(excess, 4),
        "z": round(z, 3),
        "p": round(two_sided_p(z), 6),
        "significant": abs(z) >= 2.0,
        "realizedPnl": round(pnl, 2),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bot", default="BANKROLL_200")
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    rows = con.execute(
        """SELECT entryPrice, realizedPnl, openedAt FROM PaperTrade
           WHERE botId=? AND status IN ('resolved','closed')
             AND realizedPnl IS NOT NULL AND isDemo=0""",
        (args.bot,),
    ).fetchall()
    con.close()

    et = ZoneInfo("America/New_York")
    by_band = defaultdict(list)
    by_hour = defaultdict(list)
    for p, pnl, opened in rows:
        won = pnl > 0
        by_band[None].append((p, won, pnl))
        for lo, hi in BANDS:
            if lo <= p < hi:
                by_band[(lo, hi)].append((p, won, pnl))
        ms = finish_time_ms(opened)
        if ms:
            h = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(et).hour
            by_hour[h].append((p, won, pnl))

    bands_out = []
    lines = []
    all_rows = by_band.pop(None)
    total = band_stats(all_rows)
    lines.append(
        f"  ALL:  N={total['n']:>5}  win%={total['winRate']*100:5.1f}  "
        f"excess={total['excessReturn']:+.4f}  (z={total['z']:+.2f})  PnL=${total['realizedPnl']:+.2f}"
    )
    for lo, hi in BANDS:
        b = by_band.get((lo, hi), [])
        s = band_stats(b)
        s["band"] = f"{lo:.2f}-{hi:.2f}"
        bands_out.append(s)
        flag = " **" if s["significant"] else ""
        lines.append(
            f"  entry {lo:.2f}–{hi:.2f}: N={s['n']:>5}  win%={s['winRate']*100:5.1f}  "
            f"excess={s['excessReturn']:+.4f}  (z={s['z']:+.2f}, p={s['p']:.4f})  "
            f"PnL=${s['realizedPnl']:+.2f}{flag}"
        )

    hours_out = []
    hlines = []
    for h in range(24):
        s = band_stats(by_hour.get(h, []))
        if s["n"] == 0:
            continue
        s["hour"] = h
        hours_out.append(s)
        flag = " **" if s["significant"] else ""
        hlines.append(
            f"  {h:02d}:00 ET  N={s['n']:>4}  win%={s['winRate']*100:5.1f}  "
            f"excess={s['excessReturn']:+.4f}  (z={s['z']:+.2f})  PnL=${s['realizedPnl']:+.2f}{flag}"
        )

    out = {
        "analyzedAt": datetime.now(timezone.utc).isoformat(),
        "bot": args.bot,
        "method": "excess return = win_rate - mean entry price; se=sqrt(wr(1-wr)/N); |z|>=2 significant (port of jon-becker/prediction-market-analysis, MIT)",
        "total": total,
        "bands": bands_out,
        "hours": hours_out,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f, indent=2)

    print(f"Calibration analysis ({args.bot}, N={total['n']}) — ** = |z|>=2 significant")
    print("Price bands:")
    print("\n".join(lines))
    print("Returns by hour (ET):")
    print("\n".join(hlines))
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
