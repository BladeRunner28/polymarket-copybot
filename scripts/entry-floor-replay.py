#!/usr/bin/env python3
"""
PRE-REGISTERED READ — C-200 sub-$0.05 entry floor.

Approved 2026-10-17 (copybot-research-daily REC 1). PRE-REGISTRATION IS THE POINT: the
hypothesis, the measurement basis, the thresholds and the date gate were fixed BEFORE this
script was first run, so the 2026-10-24 reading cannot be re-specified to fit whatever the
data turns out to be.

HYPOTHESIS
  C-200 legs entered below $0.05 are loss-making at any window (lifetime ROI <= -20%) while
  0.05-0.15 legs stay strongly positive. If that holds, the missing sub-0.20 FLOW is a saved
  cost rather than a lost edge, and the operative decision variable is an entry FLOOR, not the
  x3.5 longshot size factor.

DECISION RULE (verbatim from the approved rec, do not edit)
  By 2026-10-24, if BOTH
    (a) the <0.05 cell holds ROI <= -20% at n >= 60 settled C-200 legs, AND
    (b) the trailing-7d sub-0.20 skip counterfactual nets >= +$25 across >= 30 resolved markets,
  then propose `c200MinEntryPrice = 0.05` (which itself needs approval + a 7-day verify:
  0 C-200 legs below 0.05 and no drop in the 7d gate SUM).
  If either fails: record the null and drop the card.

MEASUREMENT BASIS
  * Settled legs  : PaperTrade.botId='BANKROLL_200', status IN ('closed','resolved')
                    (both are settled by the lane's own doctrine: closed = early exit,
                    resolved = natural — PnL ORs them). Window = openedAt (Unix-ms).
  * Cells         : entryPrice < 0.05 | 0.05-0.10 | 0.10-0.15 | 0.15-0.20 (+ >=0.20 reference)
  * Counterfactual: DecisionJournal decision='skip' in the last 7d, JOIN ObservedTrade for the
                    would-be entry price (`detectedPrice` — the scorer's detected price, the
                    same field the drift shadow records). Marked to RESOLUTION value 1/0 from
                    the row-level `resolve` feeds written by the shadow markers
                    (drift-shadow, lowconf-shadow, jev-shadow, longshot-shadow) — the SAME
                    resolution convention the drift shadow counterfactual uses, per the rec.
  * Stake         : $10 fixed hypothetical clip, matching DRIFT_SHADOW_STAKE_USD.
  * Dedupe        : one signal per (marketId|outcome|wallet), earliest decision — the drift
                    shadow's per-signal convention (a market that stays skipped is not counted
                    once per poll).
  * DUST          : entries below $0.10 are reported BOTH ways (dust-inclusive, and ex-dust as
                    `DRIFT_DUST_MIN_ENTRY` does) because at a ~3.6c mean entry one win returns
                    26x on a $10 clip — see the concentration block. This is a declared
                    SENSITIVITY, not a change to the rule.

READ-ONLY. Writes nothing but one appended line in data/entry-floor-read.jsonl.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "prisma" / "dev.db"
OUT = REPO / "data" / "entry-floor-read.jsonl"

# ---- PRE-REGISTERED CONSTANTS (fixed 2026-10-17) -----------------------------
PRE_REGISTERED_AT = "2026-10-17"
GATE_DATE = "2026-10-24"
MIN_N_LT005 = 60
ROI_THRESHOLD = -0.20
CF_MIN_NET = 25.0
CF_MIN_RESOLVED = 30
STAKE_USD = 10.0
DUST_MIN_ENTRY = 0.10           # drift shadow's DRIFT_DUST_MIN_ENTRY
CELLS = [(0.00, 0.05), (0.05, 0.10), (0.10, 0.15), (0.15, 0.20), (0.20, 1.01)]
CF_TOP = 0.20
RESOLVE_FILES = [
    "data/drift-shadow.jsonl",
    "data/lowconf-shadow.jsonl",
    "data/jev-shadow.jsonl",
    "data/longshot-shadow.jsonl",
]


def cell_label(lo: float, hi: float) -> str:
    return f"<{hi:.2f}" if lo == 0 else f"{lo:.2f}-{hi:.2f}" if hi <= 0.20 else f">={lo:.2f}"


def now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def last_read_at() -> tuple[datetime | None, dict | None]:
    """Timestamp (and payload) of the newest line in the series, or (None, None)."""
    if not OUT.exists():
        return None, None
    last = None
    with OUT.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if line:
                last = line
    if not last:
        return None, None
    try:
        rec = json.loads(last)
        ts = str(rec.get("ranAt") or "")
        return datetime.fromisoformat(ts.replace("Z", "+00:00")), rec
    except (json.JSONDecodeError, ValueError):
        return None, None


def staleness_hours() -> float | None:
    """Age of the newest read, in hours (None when the series is empty/unparsable)."""
    ts, _ = last_read_at()
    if ts is None:
        return None
    return (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0


def read_resolutions() -> tuple[dict[str, float], dict[str, int]]:
    """Union of the shadow markers' `resolve` rows: (marketId|outcome) -> 1/0."""
    values: dict[str, float] = {}
    per_file: dict[str, int] = {}
    for rel in RESOLVE_FILES:
        path = REPO / rel
        n = 0
        if not path.exists():
            per_file[rel] = 0
            continue
        with path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("type") != "resolve":
                    continue
                key = f"{row.get('marketId')}|{row.get('outcome')}"
                try:
                    values[key] = float(row.get("value"))
                    n += 1
                except (TypeError, ValueError):
                    continue
        per_file[rel] = n
    return values, per_file


def settled_cells(conn: sqlite3.Connection) -> dict:
    out: dict[str, dict] = {}
    rows = conn.execute(
        """
        SELECT entryPrice, simulatedPositionSize, realizedPnl, status, openedAt
          FROM PaperTrade
         WHERE botId = 'BANKROLL_200'
           AND status IN ('closed', 'resolved')
           AND realizedPnl IS NOT NULL
        """
    ).fetchall()
    cutoff_90 = now_ms() - 90 * 86400 * 1000
    for lo, hi in CELLS:
        label = cell_label(lo, hi)
        sel = [r for r in rows if lo <= (r[0] or 0) < hi]
        both = [r for r in sel]                                    # closed + resolved
        res_only = [r for r in sel if r[3] == "resolved"]           # natural settlement only
        w90 = [r for r in sel if (r[4] or 0) >= cutoff_90]

        def agg(rs):
            n = len(rs)
            if not n:
                return {"n": 0, "staked": 0.0, "pnl": 0.0, "roi": None, "winRate": None,
                        "meanEntry": None, "medianEntry": None}
            staked = sum((r[1] or 0) for r in rs)
            pnl = sum((r[2] or 0) for r in rs)
            wins = sum(1 for r in rs if (r[2] or 0) > 0)
            entries = sorted(r[0] for r in rs)
            mid = entries[len(entries) // 2] if len(entries) % 2 else (
                entries[len(entries) // 2 - 1] + entries[len(entries) // 2]) / 2
            return {
                "n": n,
                "staked": round(staked, 2),
                "pnl": round(pnl, 2),
                "roi": round(pnl / staked, 4) if staked else None,
                "winRate": round(wins / n, 4),
                "meanEntry": round(sum(entries) / n, 4),
                "medianEntry": round(mid, 4),
            }

        out[label] = {
            "lifetime": agg(both),
            "resolvedOnly": agg(res_only),
            "last90d": agg(w90),
        }
    return out


def skip_counterfactual(conn: sqlite3.Connection) -> dict:
    resolves, per_file = read_resolutions()
    cutoff = now_ms() - 7 * 86400 * 1000
    rows = conn.execute(
        """
        SELECT o.marketId, o.outcome, o.detectedPrice, o.walletAddress, j.createdAt
          FROM DecisionJournal j
          JOIN ObservedTrade o ON o.id = j.observedTradeId
         WHERE j.decision = 'skip'
           AND j.createdAt >= ?
           AND o.detectedPrice IS NOT NULL
        """,
        (cutoff,),
    ).fetchall()

    # one signal per (marketId|outcome|wallet), earliest decision (drift-shadow convention)
    signals: dict[str, tuple] = {}
    for market_id, outcome, price, wallet, created in rows:
        if price is None or price <= 0 or price >= CF_TOP:
            continue
        key = f"{market_id}|{outcome}|{wallet}"
        prev = signals.get(key)
        if prev is None or (created or 0) < (prev[4] or 0):
            signals[key] = (market_id, outcome, price, wallet, created)

    bands: dict[str, dict] = {}
    for lo, hi in CELLS[:-1]:
        bands[cell_label(lo, hi)] = {
            "signals": 0, "resolved": 0, "wins": 0, "net": 0.0, "netExDust": 0.0,
            "nExDust": 0, "best": 0.0, "entrySum": 0.0,
        }

    resolved_n = 0
    dust_n = 0
    win_rows: list[tuple[float, float, str]] = []
    for market_id, outcome, price, _wallet, _created in signals.values():
        bucket = None
        for lo, hi in CELLS[:-1]:
            if lo <= price < hi:
                bucket = cell_label(lo, hi)
                break
        if bucket is None:
            continue
        b = bands[bucket]
        b["signals"] += 1
        b["entrySum"] += price
        v = resolves.get(f"{market_id}|{outcome}")
        if v is None:
            continue
        resolved_n += 1
        b["resolved"] += 1
        if v > 0:
            b["wins"] += 1
        row_pnl = ((v - price) / price) * STAKE_USD
        b["net"] += row_pnl
        win_rows.append((row_pnl, price, bucket))
        if price < DUST_MIN_ENTRY:
            dust_n += 1
        else:
            b["netExDust"] += row_pnl
            b["nExDust"] += 1
        b["best"] = max(b["best"], row_pnl)

    win_rows.sort(reverse=True)
    total_net = sum(b["net"] for b in bands.values())
    total_ex_dust = sum(b["netExDust"] for b in bands.values())
    n_ex_dust = sum(b["nExDust"] for b in bands.values())
    top1 = win_rows[0][0] if win_rows else 0.0
    mean_entry = (sum(b["entrySum"] for b in bands.values()) / len(signals)) if signals else None

    return {
        "window": "trailing 7d by DecisionJournal.createdAt",
        "skipSignalsSub020": len(signals),
        "resolved": resolved_n,
        "coverage": round(resolved_n / len(signals), 4) if signals else None,
        "meanEntry": round(mean_entry, 4) if mean_entry else None,
        "netUsd": round(total_net, 2),
        "netExDustUsd": round(total_ex_dust, 2),
        "nExDust": n_ex_dust,
        "dustExcluded": dust_n,
        "top1WinUsd": round(top1, 2),
        "top1ShareOfNet": round(top1 / total_net, 4) if total_net else None,
        "bands": {k: {kk: (round(vv, 2) if isinstance(vv, float) else vv) for kk, vv in v.items()}
                  for k, v in bands.items()},
        "resolutionRowsByFile": per_file,
        "resolutionKeys": len(resolves),
    }


def verdict(cells: dict, cf: dict) -> dict:
    today = datetime.now(timezone.utc).date().isoformat()
    lt005 = cells["<0.05"]["lifetime"]
    gate_a_n = lt005["n"] >= MIN_N_LT005
    gate_a_roi = lt005["roi"] is not None and lt005["roi"] <= ROI_THRESHOLD
    gate_b_n = cf["resolved"] >= CF_MIN_RESOLVED
    gate_b_net = cf["netUsd"] >= CF_MIN_NET
    date_ok = today >= GATE_DATE
    if not date_ok:
        state = "PENDING_DATE"
        note = f"pre-registered; gate date {GATE_DATE} not reached (today {today})"
    elif not gate_a_n:
        state = "INSUFFICIENT_N"
        note = f"<0.05 cell n={lt005['n']} < pre-registered {MIN_N_LT005}"
    elif gate_a_roi and gate_b_n and gate_b_net:
        state = "PROPOSE_FLOOR_0.05"
        note = "both gates fired — propose c200MinEntryPrice=0.05 (needs owner approval + 7-day verify)"
    else:
        state = "NULL_DROP"
        note = "gate did not fire — record the null, drop the card"
    return {
        "state": state,
        "note": note,
        "today": today,
        "gateA_n": {"value": lt005["n"], "pass": gate_a_n, "need": MIN_N_LT005},
        "gateA_roi": {"value": lt005["roi"], "pass": gate_a_roi, "need": f"<= {ROI_THRESHOLD}"},
        "gateB_resolved": {"value": cf["resolved"], "pass": gate_b_n, "need": CF_MIN_RESOLVED},
        "gateB_net": {"value": cf["netUsd"], "pass": gate_b_net, "need": CF_MIN_NET},
    }


def main() -> int:
    if not DB.exists():
        print(f"DB not found: {DB}", file=sys.stderr)
        return 1

    # --if-stale-hours N: skip the append when the series already has a read younger than N.
    # Exists so a daily collector can own this read without the Monday weekly job (same
    # wrapper) double-appending the same day. 0 (default) = always append.
    if_stale = 0.0
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--if-stale-hours" and i + 1 < len(args):
            if_stale = float(args[i + 1])
        elif a.startswith("--if-stale-hours="):
            if_stale = float(a.split("=", 1)[1])
    age = staleness_hours()
    if if_stale > 0 and age is not None and age < if_stale:
        print(f"entry-floor prereg: newest read is {age:.1f}h old (< {if_stale:g}h) — not re-appending")
        return 0

    prior_ts, prior_rec = last_read_at()
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        cells = settled_cells(conn)
        cf = skip_counterfactual(conn)
    finally:
        conn.close()
    v = verdict(cells, cf)
    days_since_gate = (datetime.now(timezone.utc).date()
                       - datetime.fromisoformat(GATE_DATE).date()).days
    read = {
        "read": "entry-floor-prereg",
        "preRegisteredAt": PRE_REGISTERED_AT,
        "gateDate": GATE_DATE,
        "daysSinceGate": days_since_gate,
        "priorReadAt": prior_ts.isoformat(timespec="seconds") if prior_ts else None,
        "ranAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cells": cells,
        "c200Legs": sum(c["lifetime"]["n"] for k, c in cells.items() if k != ">0.20"),
        "skipCounterfactual": cf,
        "verdict": v,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a") as fh:
        fh.write(json.dumps(read, sort_keys=True) + "\n")

    print("=== SETTLED C-200 LEGS BY ENTRY PRICE (lifetime | resolved-only | last 90d) ===")
    for label, c in cells.items():
        lt, ro, w9 = c["lifetime"], c["resolvedOnly"], c["last90d"]
        print(f"  {label:>10}  n={lt['n']:>5} pnl=${lt['pnl']:>10,.2f} roi={lt['roi']:>7} win={lt['winRate']:>6} "
              f"| resolved n={ro['n']:>5} roi={ro['roi']:>7} | 90d n={w9['n']:>4} roi={w9['roi']:>7}")
    print("\n=== SUB-0.20 SKIP COUNTERFACTUAL (7d, $10 clip, resolution-marked) ===")
    print(f"  signals={cf['skipSignalsSub020']} resolved={cf['resolved']} coverage={cf['coverage']} "
          f"meanEntry={cf['meanEntry']}")
    print(f"  net=${cf['netUsd']:,.2f} (dust-inclusive) | ex-dust(${DUST_MIN_ENTRY}) net=${cf['netExDustUsd']:,.2f} "
          f"on n={cf['nExDust']} | dust rows excluded={cf['dustExcluded']}")
    print(f"  top-1 win=${cf['top1WinUsd']:,.2f} = {cf['top1ShareOfNet']} of net  "
          f"<-- concentration check (at ~3.6c means one win is most of the number)")
    for label, b in cf["bands"].items():
        print(f"    {label:>10} signals={b['signals']:>4} resolved={b['resolved']:>4} wins={b['wins']:>3} "
              f"net=${b['net']:>9,.2f} exDust=${b['netExDust']:>9,.2f} best=${b['best']:>8,.2f}")
    print(f"\n=== VERDICT: {v['state']} — {v['note']} ===")
    # Anchored to the pre-registered date, not to "now": a gate that quietly goes unread is
    # the failure mode this line exists to make impossible to miss (2026-10-26 self-audit:
    # the series held ONE read, taken on registration day, and the gate date 2026-10-24
    # passed with nothing scheduled to read it).
    print(f"  gate date {GATE_DATE} = {days_since_gate}d ago · prior read "
          f"{read['priorReadAt'] or 'none'} ({prior_rec.get('verdict', {}).get('state') if prior_rec else '-'})")
    if days_since_gate >= 0 and (prior_ts is None
                                 or prior_ts.date().isoformat() < GATE_DATE):
        print(f"  !! GATE WAS UNREAD: no read of this series exists on/after {GATE_DATE} "
              f"before this one — the 'series answers the gate date' claim was not true")
    print(f"  gateA n {v['gateA_n']['value']}/{v['gateA_n']['need']} pass={v['gateA_n']['pass']} · "
          f"gateA roi {v['gateA_roi']['value']} pass={v['gateA_roi']['pass']} · "
          f"gateB resolved {v['gateB_resolved']['value']}/{v['gateB_resolved']['need']} pass={v['gateB_resolved']['pass']} · "
          f"gateB net ${v['gateB_net']['value']} pass={v['gateB_net']['pass']}")
    try:
        shown = OUT.relative_to(REPO)
    except ValueError:  # OUT outside the repo (tests/fixtures) — print the real path, don't crash after the append
        shown = OUT
    print(f"  appended -> {shown}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
