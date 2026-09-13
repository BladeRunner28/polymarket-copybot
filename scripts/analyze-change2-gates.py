#!/usr/bin/env python3
"""Change 2 gate read (C-200): pre-registered evidence for the Oct 8 decision.

Change 2 of the 2026-09-13 daily report ("gate the two significant drain
entry-hours and the premium band") was APPROVED IN PRINCIPLE but NOT applied:
it is queued to the Oct 8 close of the pre-registered Kelly window, with shadow
measurement in the meantime. This script is that measurement — it reads the
live paper book and reports exactly the three gate candidates, in-window
(since the v50 Kelly-window start) next to all-time, so the Oct 8 decision is
mechanical rather than re-argued from scratch.

Gate candidates (from analyze-calibration.py, N=1,453 Polymarket-only):
  08:00 ET entries           excess -0.2106  z=-2.69  PnL -$76.60  (N=34)
  20:00 ET entries           excess -0.2365  z=-2.82  PnL -$80.43  (N=31)
  entry price 0.60-0.80      excess -0.0963  z=-3.34  PnL -$67.52  (N=290)
                             (with Kalshi: -$73.75 on $1,618 staked)

IMPORTANT — 20:00 ET is ALREADY blacked out in code (src/lib/hour-policy.ts,
v41/v48: C200_BLACKOUT_HOURS_ET = {20}), so its all-time N is history, not live
flow; the only *ungated* hour in the candidate list is 08:00 ET. This script
prints the live policy state so the read cannot be misread as "20:00 is still
costing money".

Pre-registered decision rule (set 2026-09-13, before the data arrives):
  APPLY the gate at Oct 8 iff, in the in-window sample only,
      |z| >= 2.0  AND  realized PnL < 0  AND  N >= 20
  Otherwise keep measuring. All-time stats are context, never the trigger — the
  report's own caveat is that the live regime (Kelly sizing + v53 adverse-only
  exit, both active) is what the gate would be applied to.

Usage (project root):
    python3 scripts/analyze-change2-gates.py
    python3 scripts/analyze-change2-gates.py --since 2026-09-06
Writes data/change2-gates[-since-<date>].json (the canonical all-time file is
owned by this script alone; --since writes a suffixed file).
"""

from __future__ import annotations  # keep annotations importable on py3.9

import argparse
import importlib.util
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "prisma", "dev.db")

# Reuse the stats + DB-read conventions of the calibration analysis instead of
# forking them (single source of truth for excess-return math).
_cal_path = os.path.join(ROOT, "scripts", "analyze-calibration.py")
_spec = importlib.util.spec_from_file_location("analyze_calibration", _cal_path)
assert _spec is not None and _spec.loader is not None, f"cannot load {_cal_path}"
cal = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cal)  # type: ignore[union-attr]

ET = ZoneInfo("America/New_York")

GATE_HOURS = [8]  # 20:00 ET is already blacked out in hour-policy.ts
CONTEXT_HOURS = [0, 1, 20]
BAND = (0.6, 0.8)

DECISION_RULE = {
    "min_abs_z": 2.0,
    "require_negative_pnl": True,
    "min_n": 20,
    "sample": "in-window only (all-time is context, never the trigger)",
    "set_at": "2026-09-13",
}


def since_ms(since: str | None) -> int | None:
    if not since:
        return None
    return int(
        datetime.fromisoformat(since + "T00:00:00").replace(tzinfo=ET).timestamp() * 1000
    )


def load_rows(bot: str, since: str | None):
    con = sqlite3.connect(DB)
    sql = """SELECT entryPrice, realizedPnl, openedAt, simulatedPositionSize, id, marketId, outcome
             FROM PaperTrade
             WHERE botId=? AND status IN ('resolved','closed')
               AND realizedPnl IS NOT NULL AND isDemo=0
               AND venue != 'Kalshi'"""
    params: list = [bot]
    ms = since_ms(since)
    if ms is not None:
        sql += " AND openedAt >= ?"
        params.append(ms)
    rows = con.execute(sql, params).fetchall()
    con.close()
    return rows


def dedupe_by_position(rows):
    """Collapse duplicate accumulation rows into one logical position.

    The book carries legacy multi-entry duplicates (same market+outcome opened
    several times by the pre-guard scorer; journal fix landed, history not yet
    cleaned). They inflate N and can flip a bucket's z on their own — the
    2026-09-13 00:00 ET read (z=-5.07) was 4 rows on one market. An entry-hour
    gate is a decision-level rule, so the decision sample is the deduped one:
    keep the FIRST entry per (marketId, outcome) and report the collapse.
    """
    seen = {}
    collapsed = 0
    for r in rows:
        key = f"{r[5]}|{r[6]}"
        prev = seen.get(key)
        if prev is None:
            seen[key] = r
        else:
            collapsed += 1
            if cal.finish_time_ms(r[2]) < cal.finish_time_ms(prev[2]):
                seen[key] = r
    return list(seen.values()), collapsed


def open_book(bot: str):
    con = sqlite3.connect(DB)
    r = con.execute(
        """SELECT COUNT(*), COALESCE(SUM(simulatedPositionSize),0) FROM PaperTrade
           WHERE botId=? AND status='open'""",
        (bot,),
    ).fetchone()
    con.close()
    return int(r[0]), round(float(r[1]), 2)


def policy_state():
    """Read the live hour policy from source (no import: keeps this stdlib-only)."""
    path = os.path.join(ROOT, "src", "lib", "hour-policy.ts")
    out = {"source": os.path.relpath(path, ROOT), "blackout_hours_et": None, "haircut_hour_et": None}
    try:
        with open(path) as f:
            txt = f.read()
        m = re.search(r"C200_BLACKOUT_HOURS_ET[^=]*=\s*new Set\(\[([^\]]*)\]", txt)
        if m:
            out["blackout_hours_et"] = [int(x) for x in m.group(1).split(",") if x.strip()]
        m = re.search(r"export const C200_HAIRCUT_HOUR_ET\s*=\s*(\d+)", txt)
        if m:
            out["haircut_hour_et"] = int(m.group(1))
    except OSError:
        pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bot", default="BANKROLL_200")
    ap.add_argument("--since", default="2026-09-06",
                    help="in-window start (ET midnight). Default 2026-09-06 = v50/Kelly-window start.")
    ap.add_argument("--all-time", action="store_true",
                    help="run the all-time window instead of the in-window one")
    args = ap.parse_args()

    windows = {"in_window": None if args.all_time else args.since, "all_time": None}
    if args.all_time:
        windows = {"all_time": None}

    by_hour = {w: defaultdict(list) for w in windows}
    by_band = {w: [] for w in windows}
    by_hour_dd = {w: defaultdict(list) for w in windows}
    by_band_dd = {w: [] for w in windows}
    totals = {}
    collapse = {}
    for w, since in windows.items():
        rows = load_rows(args.bot, since)
        dd_rows, collapsed = dedupe_by_position(rows)
        collapse[w] = {"raw": len(rows), "deduped": len(dd_rows), "collapsed": collapsed}
        for group, source in ((None, rows), ("dd", dd_rows)):
            bh = by_hour_dd[w] if group == "dd" else by_hour[w]
            bb = by_band_dd[w] if group == "dd" else by_band[w]
            for r in source:
                p, pnl, opened = r[0], r[1], r[2]
                won = pnl > 0
                ms = cal.finish_time_ms(opened)
                if not ms:
                    continue
                h = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(ET).hour
                bh[h].append((p, won, pnl))
                if BAND[0] <= p < BAND[1]:
                    bb.append((p, won, pnl))
        totals[w] = cal.band_stats([(r[0], r[1] > 0, r[1]) for r in rows])

    pol = policy_state()
    open_n, open_stake = open_book(args.bot)

    print(f"Change 2 gate read ({args.bot}) — ** = |z|>=2 (Polymarket-only, isDemo=0, Kalshi excluded)")
    print(f"Live hour policy: blackout ET hours {pol['blackout_hours_et']}, "
          f"haircut ET hour {pol['haircut_hour_et']} ({pol['source']})")
    print(f"Open book: {open_n} rows, ${open_stake:.2f} staked")
    print("Gate stats use the DEDUPED sample (one row per market+outcome: legacy duplicate")
    print("accumulation rows otherwise inflate N and can flip a bucket's z on their own)\n")

    out = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "bot": args.bot,
        "windows": {w: (windows[w] or "all-time") for w in windows},
        "live_policy": pol,
        "open_book": {"rows": open_n, "stakedUsd": open_stake},
        "decision_rule": DECISION_RULE,
        "sample_collapse": collapse,
        "gates": {},
    }

    for w in windows:
        label = f"since {windows[w]}" if windows[w] else "all-time"
        c = collapse[w]
        print(f"[{label}]  raw N={c['raw']}  deduped N={c['deduped']}  "
              f"({c['collapsed']} duplicate rows collapsed)  PnL(realized, raw)=${totals[w]['realizedPnl']:+.2f}")
        gates = {}
        for h in GATE_HOURS + CONTEXT_HOURS:
            raw_s = cal.band_stats(by_hour[w].get(h, []))
            s = cal.band_stats(by_hour_dd[w].get(h, []))
            if s["n"] == 0:
                print(f"   {h:02d}:00 ET  N=0  (no entries in this window)")
                gates[f"hour_{h:02d}_et"] = {"n": 0}
                continue
            gated = h in (pol["blackout_hours_et"] or [])
            status = "ALREADY BLACKED OUT" if gated else "ungated"
            print(f"   {h:02d}:00 ET  N={s['n']:>4} (raw {raw_s['n']:>4})  win%={s['winRate']*100:5.1f}  "
                  f"excess={s['excessReturn']:+.4f} (z={s['z']:+.2f})  PnL=${s['realizedPnl']:+.2f}"
                  f"{' **' if s['significant'] else ''}  [{status}]")
            gates[f"hour_{h:02d}_et"] = {**s, "n_raw": raw_s["n"],
                                          "excess_raw": raw_s["excessReturn"], "z_raw": raw_s["z"],
                                          "already_gated": gated,
                                          "would_trigger": bool(
                                              abs(s["z"]) >= DECISION_RULE["min_abs_z"]
                                              and s["realizedPnl"] < 0
                                              and s["n"] >= DECISION_RULE["min_n"]
                                              and not gated)}
        raw_s = cal.band_stats(by_band[w])
        s = cal.band_stats(by_band_dd[w])
        print(f"   entry {BAND[0]:.2f}-{BAND[1]:.2f}  N={s['n']:>4} (raw {raw_s['n']:>4})  win%={s['winRate']*100:5.1f}  "
              f"excess={s['excessReturn']:+.4f} (z={s['z']:+.2f})  PnL=${s['realizedPnl']:+.2f}"
              f"{' **' if s['significant'] else ''}")
        gates["band_0.60-0.80"] = {**s, "n_raw": raw_s["n"],
                                   "excess_raw": raw_s["excessReturn"], "z_raw": raw_s["z"],
                                   "would_trigger": bool(abs(s["z"]) >= DECISION_RULE["min_abs_z"]
                                                         and s["realizedPnl"] < 0
                                                         and s["n"] >= DECISION_RULE["min_n"])}
        out["gates"][w] = {"label": label, "total": totals[w], "collapse": c, "gates": gates}
        print()

    print("Pre-registered trigger (in-window only): |z| >= 2.0 AND PnL < 0 AND N >= 20")
    for k, v in out["gates"][list(windows)[0]]["gates"].items():
        if v.get("n", 0) == 0:
            continue
        print(f"   {k:18} {'TRIGGERS' if v.get('would_trigger') else 'no'}"
              f"{' (already gated)' if v.get('already_gated') else ''}")

    suffix = "" if args.all_time else f"-since-{args.since}"
    path = os.path.join(ROOT, "data", f"change2-gates{suffix}.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nWrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
