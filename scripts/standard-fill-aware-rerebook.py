#!/usr/bin/env python3
"""standard-fill-aware-rerebook — READ-ONLY: what the STANDARD book's realised PnL becomes
when each leg is re-booked at the entry the fill booth measured as ATTAINABLE, instead of
at the quote STANDARD booked.

WHY (roadmap card `standard-fill-aware-booking`, Lane A proposal, 2026-10-29)
The card's decision rule has two clauses and the fill booth (scripts/standard-fill-stamp.ts,
data/standard-fill-stamp.jsonl) only supplies the first one:

  clause 1  the stamped entry is worse than the booked price by a median >= 0.5c
  clause 2  the RE-BOOKED 90d ROI falls >= 1.0pp

This script measures clause 2 and re-measures clause 1 on the same population, so the
proposal's two numbers come from one pass over one join.

HOW A LEG IS RE-PRICED (no model, just the arithmetic the book already implies)
STANDARD books pnl = size * (exit/entry - 1), so the exit price a settled leg implies is
  exit = entry * (1 + pnl/size)
and re-booking the same leg at entry' (the attainable ask) gives
  pnl' = size * (exit/entry' - 1)
For a resolved loss (pnl = -size) exit = 0 and pnl' = -size: a worse entry cannot deepen a
total loss, which is exactly right.

THREE DELTAS, NEVER POOLED
  taker    firstAsk - booked  (the first book snapshot at/after the decision: no patience,
           no hindsight) — the delta a booking rule would actually use.
  taker60  same, restricted to legs whose first snapshot arrived within 60s of the decision,
           so "the ask at the decision" is not a five-minute-old quote. Disciplined read.
  hourmin  lowest ask inside the 30-60m window - booked — OPTIMISTIC by construction (it
           takes the window's best price with hindsight). Reported, never the basis.

WHAT THIS IS NOT
It writes no DB row, no RuleSet, no booked figure, and nothing in the trade path imports it.
The booking change is a Lane A decision; this is the evidence for it.

Every number carries its own n and coverage. A leg with no book evidence is EXCLUDED from
every rate — never counted as "no fill", never imputed.

Usage: python3 scripts/standard-fill-aware-rerebook.py [--json] [--db P] [--artifact P]
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ARTIFACT = os.path.join(ROOT, "data", "standard-fill-stamp.jsonl")
DAY_MS = 86_400_000
HORIZON_90D_MS = 90 * DAY_MS
GATE_LEGS = 300
MID_BAND_C = 0.3
MEDIAN_CLAUSE_C = 0.5
ROI_CLAUSE_PP = 1.0
TAKER60_LAG_MS = 60_000


def db_candidates() -> list[str]:
    """prisma/dev.db is 12 GB and lives in the PRIMARY tree; a worktree gets a 0-byte stub."""
    seen: list[str] = []
    for base in (ROOT, ROOT, ROOT):
        cand = os.path.join(base, "prisma", "dev.db")
        if cand not in seen:
            seen.append(cand)
    # walk up out of a .worktrees/<id> checkout
    d = ROOT
    for _ in range(4):
        cand = os.path.join(d, "prisma", "dev.db")
        if cand not in seen:
            seen.append(cand)
        d = os.path.dirname(d)
    return seen


def resolve_db(explicit: str | None) -> str:
    if explicit:
        if not os.path.exists(explicit):
            raise SystemExit(f"[rerebook] --db {explicit} does not exist")
        return explicit
    for cand in db_candidates():
        if os.path.exists(cand) and os.path.getsize(cand) > 1_000_000:
            return cand
    raise SystemExit("[rerebook] no populated prisma/dev.db found — pass --db")


def read_snapshot(file: str) -> dict[str, Any]:
    last = None
    with open(file, "r", encoding="utf8") as fh:
        for line in fh:
            t = line.strip()
            if not t:
                continue
            try:
                o = json.loads(t)
            except json.JSONDecodeError:
                continue  # a torn line is not a snapshot
            if isinstance(o.get("legs"), list):
                last = o
    if last is None:
        raise SystemExit(f"[rerebook] no snapshot in {file} — run scripts/standard-fill-stamp.ts first")
    return last


def quantile(sorted_xs: list[float], p: float) -> float:
    if not sorted_xs:
        return float("nan")
    idx = min(len(sorted_xs) - 1, max(0, int(-(-p * len(sorted_xs) // 1)) - 1))  # nearest-rank
    return sorted_xs[idx]


def epoch_ymd(ms: int) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ms / 1000)) if ms else "n/a"


def stats(xs: list[float]) -> dict[str, Any]:
    if not xs:
        return {"n": 0, "meanC": None, "medianC": None, "p10C": None, "p90C": None}
    s = sorted(xs)
    mid = len(s) // 2
    med = s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2
    return {
        "n": len(s),
        "meanC": round(sum(s) / len(s), 4),
        "medianC": round(med, 4),
        "p10C": round(quantile(s, 0.10), 4),
        "p90C": round(quantile(s, 0.90), 4),
        "minC": round(s[0], 4),
        "maxC": round(s[-1], 4),
        # Shares the proposal quotes. Compare AFTER rounding to 4dp on purpose: (0.11 - 0.10) * 100
        # evaluates to 0.9999999999999996 in binary float, so an exact 1.00c delta would be excluded
        # from ">= +1c worse" — 8 of 235 legs flipped on that noise alone. Rounded, a tick-exact
        # 1.0c counts as a cent.
        "shareAtOrBetter": round(sum(1 for x in s if x <= 0) / len(s), 4),
        "shareWorseBy1C": round(sum(1 for x in s if x >= 1.0) / len(s), 4),
        "shareWithinBand": round(sum(1 for x in s if abs(x) <= MID_BAND_C) / len(s), 4),
    }


def load_legs(db: str, ids: list[str]) -> dict[str, dict[str, Any]]:
    """One read-only pass over the 12 GB live DB, restricted to the artifact's leg ids."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=60)
    con.row_factory = sqlite3.Row
    out: dict[str, dict[str, Any]] = {}
    cur = con.cursor()
    cur.execute("PRAGMA query_only=1")
    chunk = 400
    for i in range(0, len(ids), chunk):
        part = ids[i : i + chunk]
        q = ",".join("?" * len(part))
        rows = cur.execute(
            f"""SELECT id, marketId, outcome, botId, entryPrice, simulatedPositionSize AS size,
                       realizedPnl AS pnl, status, openedAt, COALESCE(resolvedAt, closedAt) AS doneAt
                FROM PaperTrade
                WHERE botId='STANDARD' AND isDemo=0 AND id IN ({q})""",
            part,
        ).fetchall()
        for r in rows:
            out[r["id"]] = dict(r)
    con.close()
    return out


def reprice(entry: float, size: float, pnl: float, delta_usd: float) -> tuple[float, float, float]:
    """(entry', pnl', exit) for one settled leg re-booked at entry + delta."""
    shares = size / entry
    exit_px = entry + pnl / shares
    new_entry = max(0.01, entry + delta_usd)
    new_pnl = size * (exit_px / new_entry - 1.0)
    # a stake cannot lose more than itself, and the floor clamp must not manufacture value
    new_pnl = max(-size, min(new_pnl, size * (1.0 / new_entry - 1.0)))
    return round(new_entry, 6), round(new_pnl, 2), round(exit_px, 6)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None)
    ap.add_argument("--artifact", default=DEFAULT_ARTIFACT)
    ap.add_argument("--since", default=None, help="YYYY-MM-DD — only legs opened at/after this date (era cut)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    since_cut = None
    if args.since:
        since_cut = int(time.mktime(time.strptime(args.since, "%Y-%m-%d")) * 1000)

    db = resolve_db(args.db)
    snap = read_snapshot(args.artifact)
    now_ms = int(time.time() * 1000)
    since_90d = now_ms - HORIZON_90D_MS

    legs = snap["legs"]
    by_id = load_legs(db, [l["id"] for l in legs if l.get("id")])

    # ---- collect the three deltas per leg (book arm only; the tape carries no ask/mid)
    deltas: list[dict[str, Any]] = []
    for l in legs:
        book = l.get("book")
        if not book:
            continue
        row = by_id.get(l["id"])
        if not row:
            continue
        if since_cut is not None and isinstance(row["openedAt"], int) and row["openedAt"] < since_cut:
            continue
        entry = float(row["entryPrice"] or 0)
        if not (0 < entry < 1):
            continue
        first_ask = book.get("firstAsk")
        hour = (book.get("byBucket") or {}).get("30-60m") or {}
        hour_ask = hour.get("price")
        deltas.append(
            {
                "id": l["id"],
                "entry": entry,
                "size": float(row["size"] or 0),
                "pnl": None if row["pnl"] is None else float(row["pnl"]),
                "status": row["status"],
                "openedAt": row["openedAt"],
                "coverLagMs": book.get("coverLagMs"),
                "takerC": None if first_ask is None else round((first_ask - entry) * 100, 4),
                "hourminC": None if hour_ask is None else round((hour_ask - entry) * 100, 4),
                # the mid bases are NOT re-derived per leg here: the booth owns that arithmetic
                # (snapshot bid/ask), and a mid rebuilt from a bucket boundary is a different
                # quantity. See report["decisionRule"]["refutation_ofMid"].
            }
        )

    settled = [d for d in deltas if d["status"] in ("resolved", "closed") and d["pnl"] is not None]
    variants = {
        "taker": [d for d in settled if d["takerC"] is not None],
        "taker60": [
            d
            for d in settled
            if d["takerC"] is not None and d["coverLagMs"] is not None and d["coverLagMs"] <= TAKER60_LAG_MS
        ],
        "hourmin": [d for d in settled if d["hourminC"] is not None],
    }
    key_of = {"taker": "takerC", "taker60": "takerC", "hourmin": "hourminC"}

    def window(xs: list[dict[str, Any]], since: int) -> list[dict[str, Any]]:
        return [d for d in xs if isinstance(d["openedAt"], int) and d["openedAt"] >= since]

    report: dict[str, Any] = {
        "db": db,
        "artifact": args.artifact,
        "snapshotAt": snap.get("ranAt"),
        "artifactLegs": len(legs),
        "joinedLegs": len(deltas),
        "settledWithEvidence": len(settled),
        "variants": {},
    }

    for name, xs in variants.items():
        for scope, since in (("all-time", 0), ("90d", since_90d)):
            sel = window(xs, since)
            if not sel:
                report["variants"][f"{name}/{scope}"] = {"n": 0}
                continue
            k = key_of[name]
            ds = [d[k] for d in sel if d[k] is not None]
            notional = sum(d["size"] for d in sel)
            booked = sum(d["pnl"] for d in sel)
            rows = [reprice(d["entry"], d["size"], d["pnl"], d[k] / 100.0) for d in sel]
            rebooked = sum(r[1] for r in rows)
            # same population, rec-style counterfactual: 1c BETTER on every leg
            better = sum(reprice(d["entry"], d["size"], d["pnl"], -0.01)[1] for d in sel)
            report["variants"][f"{name}/{scope}"] = {
                "n": len(sel),
                "notionalUsd": round(notional, 2),
                "bookedPnlUsd": round(booked, 2),
                "bookedRoiPct": round(100 * booked / notional, 3) if notional else None,
                "rebookedPnlUsd": round(rebooked, 2),
                "rebookedRoiPct": round(100 * rebooked / notional, 3) if notional else None,
                "roiDeltaPp": round(100 * (rebooked - booked) / notional, 3) if notional else None,
                "pnlDeltaUsd": round(rebooked - booked, 2),
                "rec1cBetterPnlUsd": round(better, 2),
                "rec1cBetterRoiPct": round(100 * better / notional, 3) if notional else None,
                "delta": stats(ds),
                "winLegs": sum(1 for d in sel if d["pnl"] > 0),
                "lossLegs": sum(1 for d in sel if d["pnl"] <= 0),
            }

    # ---- lane baseline, so a projection onto the whole book is anchored in a measured denominator
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=60)
    cur = con.cursor()
    cur.execute("PRAGMA query_only=1")

    def lane(since_ms: int) -> dict[str, Any]:
        r = cur.execute(
            """SELECT COUNT(*) n, COALESCE(SUM(simulatedPositionSize),0) ntl,
                      COALESCE(SUM(realizedPnl),0) pnl
               FROM PaperTrade
               WHERE botId='STANDARD' AND isDemo=0 AND status IN ('resolved','closed')
                 AND openedAt >= ? AND realizedPnl IS NOT NULL""",
            (since_ms,),
        ).fetchone()
        n, ntl, pnl = int(r[0]), float(r[1]), float(r[2])
        return {
            "n": n,
            "notionalUsd": round(ntl, 2),
            "pnlUsd": round(pnl, 2),
            "roiPct": round(100 * pnl / ntl, 3) if ntl else None,
        }

    epoch_ms = int(snap.get("coverage", {}).get("l2CorpusEpochMs") or 0)
    report["laneBaseline"] = {
        "standard90d": lane(since_90d),
        "standardSinceL2Epoch": lane(epoch_ms),
        "l2EpochMs": epoch_ms,
        "note": "the fill booth can only speak to legs opened at/after the L2 corpus epoch; "
        "that is the population every measured delta below is drawn from",
    }

    # ---- the volume half: p(fill) = the shared resolver's verdict, mode `none`
    # (reachable iff the widest-window best ask <= the booked price). Mirrors
    # reachability() in src/lib/standard-fill-stamp.ts and bookedPnl() in src/lib/paper.ts:
    # an unresolved leg (no book window) books EXACTLY as before, never as "did not fill".
    def reachable_of(book: dict[str, Any] | None, entry: float) -> bool | None:
        if not book:
            return None
        cell = (book.get("byBucket") or {}).get("30-60m")
        if not cell or cell.get("price") is None:
            return None
        return float(cell["price"]) <= entry + 1e-9

    for scope, since in (("all-time", 0), ("90d", since_90d)):
        sel = window([d for d in settled], since)
        if not sel:
            continue
        notional = sum(d["size"] for d in sel)
        booked_pnl = sum(d["pnl"] for d in sel)
        fa_pnl = 0.0
        tried = reach = 0
        fa_notional = 0.0
        for d in sel:
            b = next((l.get("book") for l in legs if l["id"] == d["id"]), None)
            v = reachable_of(b, d["entry"])
            if v is None:
                fa_pnl += d["pnl"]  # unresolved: pass through (the C-200 policy)
                fa_notional += d["size"]
                continue
            tried += 1
            if v:
                reach += 1
                fa_pnl += d["pnl"]
                fa_notional += d["size"]
        report["variants"][f"pfill/{scope}"] = {
            "n": len(sel),
            "notionalUsd": round(notional, 2),
            "bookedPnlUsd": round(booked_pnl, 2),
            "bookedRoiPct": round(100 * booked_pnl / notional, 3) if notional else None,
            "fillAwarePnlUsd": round(fa_pnl, 2),
            "fillAwareRoiPct": round(100 * fa_pnl / notional, 3) if notional else None,
            "roiDeltaPp": round(100 * (fa_pnl - booked_pnl) / notional, 3) if notional else None,
            "resolvedLegs": tried,
            "reachableLegs": reach,
            "reachRate": round(reach / tried, 4) if tried else None,
            "fillAwareNotionalUsd": round(fa_notional, 2),
        }

    # ---- reproduce the card's headline from the same read-only connection, so the proposal's
    # counterfactual and the rec's counterfactual are computed by the same arithmetic.
    # SS.8 in scripts/profit-sellside.py aggregates ALL lanes (no botId filter) on `resolved`
    # legs opened in the last 90d and prices "1c better on the winning half" as
    # n*(1/(p-0.01) - 1/p). Same formula here, same window.
    r90 = cur.execute(
        """SELECT COUNT(*) n, COALESCE(SUM(simulatedPositionSize),0) ntl,
                  COALESCE(SUM(realizedPnl),0) pnl
           FROM PaperTrade WHERE isDemo=0 AND status='resolved' AND openedAt >= ?""",
        (since_90d,),
    ).fetchone()
    gain = 0.0
    for px, n, pnl in cur.execute(
        """SELECT entryPrice, simulatedPositionSize, COALESCE(realizedPnl,0)
           FROM PaperTrade WHERE isDemo=0 AND status='resolved' AND openedAt >= ?""",
        (since_90d,),
    ):
        px = float(px or 0)
        n = float(n or 0)
        if not (0.02 < px < 1) or n <= 0 or float(pnl) <= 0:
            continue
        gain += n * (1.0 / (px - 0.01) - 1.0 / px)
    report["ssS8Reproduction"] = {
        "n": int(r90[0]),
        "notionalUsd": round(float(r90[1]), 2),
        "pnlUsd": round(float(r90[2]), 2),
        "roiPct": round(100 * float(r90[2]) / float(r90[1]), 3) if float(r90[1]) else None,
        "oneCentUsd": round(gain, 2),
    }
    con.close()

    # ---- projections: the measured Δpp carried onto the lane's own 90d settled notional.
    # LABELLED AS PROJECTIONS — the evidence covers 29% of in-scope legs, so this is what the
    # measured rate implies for the whole book, not a figure measured on the whole book.
    base = report["laneBaseline"]["standardSinceL2Epoch"]
    proj = {}
    for name in ("taker", "taker60", "pfill"):
        r = report["variants"].get(f"{name}/90d", {})
        if r.get("roiDeltaPp") is None or not base.get("notionalUsd"):
            continue
        proj[name] = {
            "measuredRoiDeltaPp": r["roiDeltaPp"],
            "laneNotionalUsd": base["notionalUsd"],
            "lanePnlUsd": base["pnlUsd"],
            "projectedPnlFallUsd": round(r["roiDeltaPp"] / 100 * base["notionalUsd"], 2),
            "projectedLanePnlUsd": round(base["pnlUsd"] + r["roiDeltaPp"] / 100 * base["notionalUsd"], 2),
        }
    report["projections"] = proj

    # ---- clause 1 + refutation, on the same pass
    first_ds = [d["takerC"] for d in settled if d["takerC"] is not None]
    taker60_ds = [d["takerC"] for d in variants["taker60"]]
    st_first = stats(first_ds)
    st_60 = stats(taker60_ds)
    # The refutation is worded "within ±0.3c of the mid". The booth owns the mid arithmetic
    # because it has the snapshot's own bid/ask: take its published cells rather than
    # re-deriving a mid from a bucket boundary. `book.first` = first snapshot at/after the
    # decision; `book.cells[30-60m]` = the widest window.
    bk = snap.get("book") or {}
    first_cell = bk.get("first") or {}
    widest_cell = next((c for c in (bk.get("cells") or []) if c.get("bucket") == "30-60m"), {}) or {}
    n_mid = int(first_cell.get("midN") or 0)
    mid_basis = {
        "n": n_mid,
        "bandC": MID_BAND_C,
        "firstSnapshot": {
            "meanMidC": first_cell.get("meanMidC"),
            "medianMidC": first_cell.get("medianMidC"),
            "shareWithinBand": first_cell.get("shareMidWithinBand"),
            "meanAskMinusMidC": first_cell.get("meanAskMinusMidC"),
        },
        "widestWindow": {
            "meanMidC": widest_cell.get("meanMidC"),
            "medianMidC": widest_cell.get("medianMidC"),
            "shareWithinBand": widest_cell.get("shareMidWithinBand"),
        },
    }
    mean_mid = mid_basis["firstSnapshot"]["meanMidC"]
    fires_on_first_mid = mean_mid is not None and abs(mean_mid) <= MID_BAND_C

    gate_met = len(first_ds) >= GATE_LEGS
    clause1 = st_first["medianC"] is not None and st_first["medianC"] >= MEDIAN_CLAUSE_C
    nine = report["variants"].get("taker/90d", {})
    clause2 = nine.get("roiDeltaPp") is not None and nine["roiDeltaPp"] <= -ROI_CLAUSE_PP

    report["decisionRule"] = {
        "gate": {"required": GATE_LEGS, "n": len(first_ds), "met": gate_met},
        "clause1_medianC": {
            "threshold": MEDIAN_CLAUSE_C,
            "taker": st_first,
            "taker60": st_60,
            "met_taker": clause1,
            "met_taker60": st_60["medianC"] is not None and st_60["medianC"] >= MEDIAN_CLAUSE_C,
        },
        "clause2_roiFallPp": {
            "threshold": -ROI_CLAUSE_PP,
            "taker_90d": nine.get("roiDeltaPp"),
            "met": clause2,
        },
        "refutation_ofMid": {
            **mid_basis,
            "fires_on_first_mid": fires_on_first_mid,
            "note": "the contemporaneous mid travels with the ask, so this basis flatters a taker; "
            "the decision-relevant basis is vs the BOOKED price, which is the decision mid",
        },
    }

    if args.json:
        print(json.dumps(report, indent=2))
        return

    v = report["variants"]
    print(f"[rerebook] db {db} ({os.path.getsize(db)/1e9:.2f} GB, read-only) · artifact snapshot {snap.get('ranAt')}")
    print(
        f"[rerebook] era cut: opened >= {args.since}" if args.since else "[rerebook] era cut: none (all stamped legs)"
    )
    print(
        f"[rerebook] artifact {report['artifactLegs']} legs · {report['joinedLegs']} joined to a STANDARD leg · "
        f"{report['settledWithEvidence']} settled with book evidence "
        f"(book arm = 29% of in-scope legs; the rest carry no ask and are EXCLUDED, never imputed)"
    )
    print("")
    hdr = f"[rerebook] {'variant/scope':<16}{'n':>5}{'notional':>11}{'booked':>10}{'ROI':>8}{'re-booked':>11}{'ROI':>8}{'Δpp':>8}{'1c-better':>11}{'ROI':>8}"
    print(hdr)
    for name in ("taker", "taker60", "hourmin"):
        for scope in ("all-time", "90d"):
            r = v.get(f"{name}/{scope}", {})
            if not r or not r.get("n"):
                print(f"[rerebook] {name + '/' + scope:<16}     0   (no settled leg)")
                continue
            print(
                f"[rerebook] {name + '/' + scope:<16}{r['n']:>5}{r['notionalUsd']:>11,.0f}"
                f"{r['bookedPnlUsd']:>10,.0f}{r['bookedRoiPct']:>7.1f}%{r['rebookedPnlUsd']:>11,.0f}"
                f"{r['rebookedRoiPct']:>7.1f}%{r['roiDeltaPp']:>8.2f}{r['rec1cBetterPnlUsd']:>11,.0f}"
                f"{r['rec1cBetterRoiPct']:>7.1f}%"
            )
    print("")
    for name in ("taker", "taker60", "hourmin"):
        d = v.get(f"{name}/90d", {}).get("delta") or {}
        if d.get("n"):
            print(
                f"[rerebook] delta cents (attainable - booked), 90d, {name:<8} n={d['n']:<4} "
                f"mean {d['meanC']:+.2f}c  median {d['medianC']:+.2f}c  p10 {d['p10C']:+.2f}c  p90 {d['p90C']:+.2f}c  "
                f"range [{d['minC']:+.2f}, {d['maxC']:+.2f}]  at-or-better {100 * d['shareAtOrBetter']:.0f}%  "
                f">=+1c worse {100 * d['shareWorseBy1C']:.0f}%  |d|<=0.3c {100 * d['shareWithinBand']:.0f}%"
            )
    pf = v.get("pfill/90d", {})
    if pf:
        print("")
        print(
            f"[rerebook] VOLUME HALF (p(fill) = resolver verdict, mode none): n={pf['n']} settled stamped legs, "
            f"{pf['reachableLegs']}/{pf['resolvedLegs']} reachable ({100 * (pf['reachRate'] or 0):.0f}%) · "
            f"booked {pf['bookedPnlUsd']:,.2f} ({pf['bookedRoiPct']:.1f}%) vs fill-aware "
            f"{pf['fillAwarePnlUsd']:,.2f} ({pf['fillAwareRoiPct']:.1f}%) on {pf['notionalUsd']:,.0f} notional "
            f"= {pf['roiDeltaPp']:+.2f}pp"
        )
    lb = report["laneBaseline"]
    print("")
    print(
        f"[rerebook] LANE STANDARD settled, since L2 epoch ({epoch_ymd(lb['l2EpochMs'])}): "
        f"{lb['standardSinceL2Epoch']['n']} legs / ${lb['standardSinceL2Epoch']['notionalUsd']:,.0f} -> "
        f"${lb['standardSinceL2Epoch']['pnlUsd']:,.0f} ({lb['standardSinceL2Epoch']['roiPct']:+.1f}%)"
    )
    print(
        f"[rerebook] LANE STANDARD settled, last 90d: {lb['standard90d']['n']} legs / "
        f"${lb['standard90d']['notionalUsd']:,.0f} -> ${lb['standard90d']['pnlUsd']:,.0f} "
        f"({lb['standard90d']['roiPct']:+.1f}%)"
    )
    if report.get("ssS8Reproduction"):
        r = report["ssS8Reproduction"]
        print(
            f"[rerebook] SS.8 reproduction (ALL lanes, read-only): 90d settled {r['n']:,} legs / "
            f"${r['notionalUsd']:,.0f} -> ${r['pnlUsd']:,.0f} ({r['roiPct']:+.1f}%) · 1c better on the winning "
            f"half = ${r['oneCentUsd']:,.2f} ({100 * r['oneCentUsd'] / r['notionalUsd'] if r['notionalUsd'] else 0:.1f}% of notional)"
        )
    if report["projections"]:
        print("")
        for name, x in report["projections"].items():
            print(
                f"[rerebook] PROJECTION {name:<8} measured {x['measuredRoiDeltaPp']:+.2f}pp carried onto the lane's "
                f"${x['laneNotionalUsd']:,.0f} since-epoch notional -> ${x['projectedPnlFallUsd']:,.0f} of PnL "
                f"(lane {x['lanePnlUsd']:,.0f} -> {x['projectedLanePnlUsd']:,.0f}) — projection, not a measurement"
            )
    print("")
    dr = report["decisionRule"]
    print(
        f"[rerebook] GATE   n={dr['gate']['n']} of {dr['gate']['required']} required -> "
        f"{'MET' if dr['gate']['met'] else 'NOT MET'}"
    )
    print(
        f"[rerebook] CLAUSE1 median delta >= +{MEDIAN_CLAUSE_C}c  taker {dr['clause1_medianC']['taker']['medianC']:+.2f}c "
        f"({'met' if dr['clause1_medianC']['met_taker'] else 'not met'}) · taker60 "
        f"{dr['clause1_medianC']['taker60']['medianC']:+.2f}c "
        f"({'met' if dr['clause1_medianC']['met_taker60'] else 'not met'})"
    )
    print(
        f"[rerebook] CLAUSE2 90d ROI falls >= {ROI_CLAUSE_PP}pp  measured {dr['clause2_roiFallPp']['taker_90d']:+.2f}pp "
        f"({'met' if dr['clause2_roiFallPp']['met'] else 'not met'})"
    )
    om = dr["refutation_ofMid"]
    fs, ww = om["firstSnapshot"], om["widestWindow"]
    print(
        f"[rerebook] REFUTATION basis (booth's own mid cells) n={om['n']} · first snapshot: "
        f"attainable-mid mean {fs['meanMidC']:+.2f}c median {fs['medianMidC']:+.2f}c, "
        f"{100 * (fs['shareWithinBand'] or 0):.0f}% within ±{MID_BAND_C}c, spread paid {fs['meanAskMinusMidC']:+.2f}c "
        f"> {'FIRES' if om['fires_on_first_mid'] else 'does not fire'} · 30-60m window: mean {ww['meanMidC']:+.2f}c"
    )
    print(
        "[rerebook] BASIS WARNING: 'the mid' is ambiguous and decides the clause — against the mid AT the "
        "attaining snapshot the ±0.3c band can fire; against the BOOKED price (the decision mid, the number the "
        "P&L was computed from) it cannot. Pre-register the booked-price basis."
    )
    print(
        "[rerebook] NOTHING APPLIED: no DB row, RuleSet, rule, gate or booked figure was written. "
        "The booking change is a Lane A decision."
    )


if __name__ == "__main__":
    main()
