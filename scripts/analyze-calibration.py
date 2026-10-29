#!/usr/bin/env python3
"""Significance-tested calibration + hourly-returns analysis on the copybot's
own finished paper trades (port of the jon-becker/prediction-market-analysis
excess-return pattern, MIT).

For each entry-price band and each hour-of-day (ET), computes:
  win_rate, excess_return (win_rate - mean entry price), z-stat (two-sided),
  p-value, N, and realized PnL -- computed TWICE, on two named bases:
    EXIT basis    (realizedPnl > 0): the book. Depends on the exit policy under test.
    OUTCOME basis (did the token win): OutcomeReview.finalOutcome vs the trade outcome.
  The excess-return framing below is a CALIBRATION quantity, so the OUTCOME arm is the
  one it describes; the EXIT arm is the book and is not a probability read.
  p-value, N, and realized PnL.

Excess-return framing: a binary contract bought at price p pays $1 on win, so
per-contract edge = E[won] - p = win_rate - p. se = sqrt(wr(1-wr)/N) under the
null (fair pricing). |z| >= 2 marks a bucket whose edge is unlikely to be noise
-- the significance layer the daily PnL buckets don't have.

Output: console table + data/calibration-analysis.json (for the dashboard /
daily report). No new dependencies -- stdlib sqlite3 + math only.

Usage (project root):  python3 scripts/analyze-calibration.py [--bot BANKROLL_200]
                          [--since YYYY-MM-DD]   # regime filter (ET midnight):
                                                  # only trades opened >= date.
                                                  # Writes data/calibration-analysis-since-<date>.json
                                                  # instead of the canonical file (which the daily
                                                  # report owns). v52 additive observability tooling.
"""
import argparse
import json
import math
import os
import re
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


def dnorm(value) -> str:
    """Comparison key for a token label: alphanumerics only, uppercased.

    Same contract as normalizeOutcomeLabel in src/lib/resolution.ts: the venue writes
    "Yes"/"No", dev.db stores "YES"/"NO", and team markets carry real names.
    """
    return re.sub(r"[^A-Za-z0-9]", "", value or "").upper()




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
    ap.add_argument("--since", default=None, help="regime filter: only trades opened >= YYYY-MM-DD (ET midnight)")
    ap.add_argument("--dedupe", action="store_true",
                    help="decision-level sample: collapse duplicate accumulation rows (same marketId+outcome, "
                         "keep first entry). Duplicates are pseudo-replication — they inflate N and every z-stat "
                         "(all-time C-200: 1,473 rows vs 785 decisions). Default OFF so mid-window comparisons "
                         "stay on the raw sample; writes a -deduped file suffix.")
    ap.add_argument("--out", default=None, help="write the artifact here instead of the canonical path (a probe run must not overwrite a published file)")
    args = ap.parse_args()

    since_ms = None
    if args.since:
        since_ms = int(
            datetime.fromisoformat(args.since + "T00:00:00")
            .replace(tzinfo=ZoneInfo("America/New_York"))
            .timestamp()
            * 1000
        )

    con = sqlite3.connect(DB)
    # v48 (2026-09-04 daily report, approved): exclude the phantom-priced
    # legacy Kalshi leg until kalshi-reprice-92 lands — its 0.52-stub rows
    # distorted the 23:00 ET hour stats (85% of that "drain" was Kalshi).
    sql = """SELECT id, entryPrice, realizedPnl, openedAt, marketId, outcome FROM PaperTrade
          WHERE botId=? AND status IN ('resolved','closed')
            AND realizedPnl IS NOT NULL AND isDemo=0
            AND venue != 'Kalshi'"""
    params: list = [args.bot]
    if since_ms is not None:
        sql += " AND openedAt >= ?"
        params.append(since_ms)
    rows = con.execute(sql, params).fetchall()



    # SETTLEMENT BASIS (2026-10-29, label-integrity-probability-arms).
    # This script declares a PROBABILITY quantity (excess_return = win_rate - mean
    # entry price, the calibration edge of a binary contract) and then computed
    # `won` from OUR EXIT SIGN (`pnl > 0`), i.e. from the exit policy under test.
    # Both arms are now computed on the same population and printed side by side:
    #   EXIT    = realizedPnl > 0            (the book; every leg)
    #   OUTCOME = did this token actually win (OutcomeReview.finalOutcome vs the
    #             trade outcome, normalised) -- only on settlement-knowable legs.
    # The OUTCOME arm is the one the declared metric is about; its cost is
    # coverage, which is printed with it and never extrapolated.
    settlement: dict = {}
    if rows:
        ids = [r[0] for r in rows]
        for i in range(0, len(ids), 400):
            chunk = ids[i : i + 400]
            q = (
                "SELECT paperTradeId, finalOutcome FROM OutcomeReview "
                "WHERE paperTradeId IN (%s) ORDER BY createdAt" % ",".join("?" * len(chunk))
            )
            for ptid, final in con.execute(q, chunk):
                if ptid and final:
                    settlement[ptid] = final  # last review wins (ORDER BY createdAt ASC)
    con.close()

    deduped_from = None
    if args.dedupe:
        # Duplicate accumulation rows (same market+outcome, pre-guard multi-entry)
        # are one DECISION repeated: keeping them counts the same bet N times and
        # inflates the z-stat. Keep the first entry per position.
        seen: dict = {}
        # indices are (id, entryPrice, realizedPnl, openedAt, marketId, outcome)
        for r in sorted(rows, key=lambda x: finish_time_ms(x[3])):
            seen.setdefault(f"{r[4]}|{r[5]}", r)
        deduped_from = len(rows)
        rows = list(seen.values())

    et = ZoneInfo("America/New_York")
    by_band = defaultdict(list)
    by_hour = defaultdict(list)
    by_band_out = defaultdict(list)
    by_hour_out = defaultdict(list)
    outcome_unknown = 0
    for tid, p, pnl, opened, _mid, outcome in rows:
        won = pnl > 0  # EXIT basis
        by_band[None].append((p, won, pnl))
        for lo, hi in BANDS:
            if lo <= p < hi:
                by_band[(lo, hi)].append((p, won, pnl))
        ms = finish_time_ms(opened)
        hour = None
        if ms:
            hour = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(et).hour
            by_hour[hour].append((p, won, pnl))
        # OUTCOME basis: the winning token label the review recorded, compared to the
        # token we bought. Anything else (no review, empty label) is UNKNOWN and stays
        # out of the probability arm instead of being counted as a loss.
        final = settlement.get(tid)
        won_out = None
        if final:
            won_out = dnorm(final) == dnorm(outcome)
        if won_out is None:
            outcome_unknown += 1
        else:
            by_band_out[None].append((p, won_out, pnl))
            for lo, hi in BANDS:
                if lo <= p < hi:
                    by_band_out[(lo, hi)].append((p, won_out, pnl))
            if hour is not None:
                by_hour_out[hour].append((p, won_out, pnl))

    bands_out = []
    lines = []
    all_rows = by_band.pop(None)
    all_rows_out = by_band_out.pop(None)
    total = band_stats(all_rows)  # EXIT basis
    total_out = band_stats(all_rows_out)  # OUTCOME basis
    t_n = total_out["n"]
    t_wr = total_out["winRate"]
    t_ex = total_out["excessReturn"]
    t_z = total_out["z"]
    t_pnl = total_out["realizedPnl"]
    out_lines = [
        f"  ALL:  N={t_n:>5}  win%={t_wr*100:5.1f}  excess={t_ex:+.4f}  (z={t_z:+.2f})  PnL=${t_pnl:+.2f}"
    ]
    lines.append(
        f"  ALL:  N={total['n']:>5}  win%={total['winRate']*100:5.1f}  "
        f"excess={total['excessReturn']:+.4f}  (z={total['z']:+.2f})  PnL=${total['realizedPnl']:+.2f}"
    )
    for lo, hi in BANDS:
        b = by_band.get((lo, hi), [])
        s = band_stats(b)
        s["band"] = f"{lo:.2f}-{hi:.2f}"
        s["basis"] = "exit"
        s_out = band_stats(by_band_out.get((lo, hi), []))
        s_out["band"] = s["band"]
        s_out["basis"] = "outcome"
        s["outcome"] = s_out
        o_n = s_out["n"]
        o_wr = s_out["winRate"]
        o_ex = s_out["excessReturn"]
        o_z = s_out["z"]
        o_p = s_out["p"]
        o_pnl = s_out["realizedPnl"]
        out_lines.append(
            f"  entry {lo:.2f}-{hi:.2f}: N={o_n:>5}  win%={o_wr*100:5.1f}  excess={o_ex:+.4f}  "
            f"(z={o_z:+.2f}, p={o_p:.4f})  PnL=${o_pnl:+.2f}" + (" **" if s_out["significant"] else "")
        )
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
        s["basis"] = "exit"
        s_out = band_stats(by_hour_out.get(h, []))
        s_out["hour"] = h
        s_out["basis"] = "outcome"
        s["outcome"] = s_out
        hours_out.append(s)
        flag = " **" if s["significant"] else ""
        hlines.append(
            f"  {h:02d}:00 ET  N={s['n']:>4}  win%={s['winRate']*100:5.1f}  "
            f"excess={s['excessReturn']:+.4f}  (z={s['z']:+.2f})  PnL=${s['realizedPnl']:+.2f}{flag}"
        )

    out = {
        "analyzedAt": datetime.now(timezone.utc).isoformat(),
        "bot": args.bot,
        "since": args.since,
        "deduped": bool(args.dedupe),
        "dedupedFromRows": deduped_from,
        "method": "excess return = win_rate - mean entry price; se=sqrt(wr(1-wr)/N); |z|>=2 significant (port of jon-becker/prediction-market-analysis, MIT)",
        "total": total,
        "totalOutcome": total_out,
        "outcomeCoverage": round(total_out["n"] / max(len(rows), 1), 4),
        "outcomeUnknownLegs": outcome_unknown,
        "labelBasis": {
            "arm_total_bands_hours": "EXIT = realizedPnl > 0 (the book, every finished leg)",
            "arm_totalOutcome_band_outcome": "OUTCOME = OutcomeReview.finalOutcome vs the trade outcome (settlement-knowable legs only)",
            "why": "the declared quantity (excess_return = win_rate - mean entry price) is a calibration read, so it belongs on the OUTCOME arm; until 2026-10-29 it was computed on the exit sign -- the exit policy under test",
            "rule": "an unknown outcome is excluded, never counted as a loss",
        },
        "bands": bands_out,
        "hours": hours_out,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    write_path = OUT
    if args.since or args.bot != "BANKROLL_200" or args.dedupe:
        # v53 (TR-21 rec 3): include bot + window in the filename — a STANDARD
        # run must not clobber the C-200 artifact (bot in name only for
        # non-default bots to keep the canonical C-200 all-time path stable).
        # --dedupe is a DIFFERENT sample, so it never overwrites the raw file.
        parts = ["calibration-analysis"]
        if args.bot != "BANKROLL_200":
            parts.append(args.bot)
        if args.since:
            parts.append(f"since-{args.since}")
        if args.dedupe:
            parts.append("deduped")
        write_path = os.path.join(ROOT, "data", "-".join(parts) + ".json")
    if args.out:
        write_path = args.out  # explicit probe path wins; canonical file untouched
    with open(write_path, "w") as f:
        json.dump(out, f, indent=2)

    label = f"since {args.since}" if args.since else "all-time"
    if args.dedupe:
        label += f", decision-level (deduped from {deduped_from} rows)"
    print(f"Calibration analysis ({args.bot}, {label}, N={total['n']}) — ** = |z|>=2 significant")
    print("Price bands:")
    print("\n".join(lines))
    print("Returns by hour (ET):")
    print("\n".join(hlines))
    cov = out["outcomeCoverage"]
    print(f"  coverage {t_n}/{len(rows)} legs = {cov*100:.1f}% settlement-knowable; {outcome_unknown} excluded (unknown is never a loss)")
    print("OUTCOME basis (did the token win; settlement-knowable legs only):")
    print("\n".join(out_lines))
    print(f"\nWrote {write_path}")


if __name__ == "__main__":
    main()
