#!/usr/bin/env python3
"""standard-fill-aware-basis-split — READ-ONLY: is the fill booth's delta measured against
the entry that was ACTUALLY BOOKED, or against a price that has since been REWRITTEN?

WHY (card `standard-fill-aware-booking`, Lane A proposal, 2026-11-12)
The fill booth (scripts/standard-fill-stamp.ts) ran ONCE, 2026-10-29T17:14Z, and stamped each
leg with `firstAsk` — the first best-ask after the decision. Its delta is
    deltaC = (firstAsk - PaperTrade.entryPrice) * 100
where `entryPrice` was read at stamp time. Between that snapshot and today, TWO price-side
changes landed that REWRITE `PaperTrade.entryPrice` on finished rows:

  fbf9073  2026-11-09  price-side: price the token the leg holds, by the venue's own label
  d974287  2026-11-11  ledger-price-side repair APPLIED: 233 finished rows re-priced
                       (data/repair-manifests/ledger-price-side-applied-*.jsonl + preimage)

So a naive re-run of scripts/standard-fill-aware-rerebook.py today subtracts an ask measured
against the OLD basis from an entry that now carries the NEW basis. On the 2026-10-29 artifact
that flips the mean delta from +1.04c (the 10-29 reading) to -1.10c — a sign inversion produced
by the repair, not by the market.

WHAT THIS SCRIPT DOES
Rebuilds the 10-29 basis from the repair PREIMAGE (full rows, pre-write) and prints the same
two clauses three ways, so the difference is visible instead of assumed:

  as-of-today   current PaperTrade row (what a re-run reads)
  as-booked     preimage row where the leg was repaired, current row otherwise
  clean-only    the subset the repair never touched (a basis-free control)

Nothing is written: DB opened `file:...?mode=ro` + PRAGMA query_only=1, no artifact touched.

Usage: python3 scripts/standard-fill-aware-basis-split.py [--json] [--db P] [--artifact P]
                            [--preimage P] [--ledger P]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sqlite3
import sys
import time
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REREBOOK = os.path.join(ROOT, "scripts", "standard-fill-aware-rerebook.py")
DEFAULT_ARTIFACT = os.path.join(ROOT, "data", "standard-fill-stamp.jsonl")
DEFAULT_PREIMAGE = os.path.join(
    ROOT, "data", "repair-manifests", "ledger-price-side-preimage-20261111T123934.json"
)
DEFAULT_LEDGER = os.path.join(
    ROOT, "data", "repair-manifests", "ledger-price-side-applied-20261111T123934.jsonl"
)
TAKER60_LAG_MS = 60_000


def load_module(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"[basis-split] cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_preimage(path: str) -> dict[str, dict[str, Any]]:
    if not os.path.exists(path):
        raise SystemExit(f"[basis-split] preimage missing: {path}")
    d = json.load(open(path))
    rows = d.get("paperTrade") or []
    return {r["id"]: r for r in rows if r.get("id")}


def load_ledger_ids(path: str) -> set[str]:
    ids: set[str] = set()
    if not os.path.exists(path):
        return ids
    for line in open(path, encoding="utf8"):
        t = line.strip()
        if not t:
            continue
        try:
            o = json.loads(t)
        except json.JSONDecodeError:
            continue
        if o.get("type") == "header":
            continue
        pid = o.get("paperTradeId")
        if pid:
            ids.add(pid)
    return ids


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None)
    ap.add_argument("--artifact", default=DEFAULT_ARTIFACT)
    ap.add_argument("--preimage", default=DEFAULT_PREIMAGE)
    ap.add_argument("--ledger", default=DEFAULT_LEDGER)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rb = load_module(REREBOOK, "standard_fill_aware_rerebook")
    db = rb.resolve_db(args.db)
    snap = rb.read_snapshot(args.artifact)
    legs = snap["legs"]
    cur = rb.load_legs(db, [l["id"] for l in legs if l.get("id")])
    pre = load_preimage(args.preimage)
    repaired = load_ledger_ids(args.ledger)

    rows: list[dict[str, Any]] = []
    for l in legs:
        book = l.get("book")
        lid = l.get("id")
        if not book or not lid or lid not in cur:
            continue
        first_ask = book.get("firstAsk")
        if first_ask is None:
            continue
        c = cur[lid]
        if c["status"] not in ("resolved", "closed") or c["pnl"] is None:
            continue
        p = pre.get(lid)
        rows.append(
            {
                "id": lid,
                "size": float(c["size"] or 0),
                "pnlNow": float(c["pnl"]),
                "entryNow": float(c["entryPrice"] or 0),
                "pnlPre": float(p["realizedPnl"]) if p and p.get("realizedPnl") is not None else float(c["pnl"]),
                "entryPre": float(p["entryPrice"]) if p and p.get("entryPrice") is not None else float(c["entryPrice"] or 0),
                "firstAsk": float(first_ask),
                "coverLagMs": book.get("coverLagMs"),
                "hourAsk": (
                    float(book["byBucket"]["30-60m"]["price"])
                    if (book.get("byBucket") or {}).get("30-60m", {}).get("price") is not None
                    else None
                ),
                "reach": None,
                "openedAt": c["openedAt"],
                "doneAt": c["doneAt"],
                "repaired": lid in repaired,
                "botId": c.get("botId"),
            }
        )

    def measure(basis: str, subset: list[dict[str, Any]]) -> dict[str, Any]:
        e_key, p_key = ("entryPre", "pnlPre") if basis == "as-booked" else ("entryNow", "pnlNow")
        ds: list[float] = []
        ntl = booked = rebooked = better = 0.0
        # the VOLUME half (C-200's policy): reachable iff the widest-window best ask <= entry;
        # an unresolved leg (no 30-60m cell) passes through exactly as before, never as "unfilled"
        fa = fa_ntl = 0.0
        tried = reach = 0
        comb = 0.0  # both halves: unfilled -> not a position; filled -> re-booked at the ask
        for r in subset:
            entry, pnl, size = r[e_key], r[p_key], r["size"]
            if not (0 < entry < 1) or size <= 0:
                continue
            dc = round((r["firstAsk"] - entry) * 100, 4)
            ds.append(dc)
            ntl += size
            booked += pnl
            rebooked += rb.reprice(entry, size, pnl, dc / 100.0)[1]
            better += rb.reprice(entry, size, pnl, -0.01)[1]
            hit = r["hourAsk"] if r["hourAsk"] is None else (r["hourAsk"] <= entry + 1e-9)
            if hit is None:
                fa += pnl
                fa_ntl += size
                comb += pnl
            else:
                tried += 1
                if hit:
                    reach += 1
                    fa += pnl
                    fa_ntl += size
                    comb += rb.reprice(entry, size, pnl, dc / 100.0)[1]
        st = rb.stats(ds)
        return {
            "basis": basis,
            "n": len(ds),
            "notionalUsd": round(ntl, 2),
            "bookedPnlUsd": round(booked, 2),
            "bookedRoiPct": round(100 * booked / ntl, 3) if ntl else None,
            "rebookedPnlUsd": round(rebooked, 2),
            "rebookedRoiPct": round(100 * rebooked / ntl, 3) if ntl else None,
            "roiDeltaPp": round(100 * (rebooked - booked) / ntl, 3) if ntl else None,
            "rec1cBetterPnlUsd": round(better, 2),
            "delta": st,
            "pfill": {
                "fillAwarePnlUsd": round(fa, 2),
                "fillAwareRoiPct": round(100 * fa / ntl, 3) if ntl else None,
                "roiDeltaPp": round(100 * (fa - booked) / ntl, 3) if ntl else None,
                "resolvedLegs": tried,
                "reachableLegs": reach,
                "reachRate": round(reach / tried, 4) if tried else None,
            },
            "combined": {
                "pnlUsd": round(comb, 2),
                "roiPct": round(100 * comb / ntl, 3) if ntl else None,
                "roiDeltaPp": round(100 * (comb - booked) / ntl, 3) if ntl else None,
            },
        }

    clean = [r for r in rows if not r["repaired"]]
    dirty = [r for r in rows if r["repaired"]]
    # RESIDUAL EXPOSURE. The repair manifest classified what was FINISHED on 2026-11-11.
    # A leg opened before the price-side fix (fbf9073, 2026-11-09 09:15 CST) and finished
    # AFTER the repair can still carry the sibling-token entry with no repair to undo it —
    # its booked price is unknowable here, so it is neither "clean" nor in the ledger.
    PRICE_FIX_MS = 1_794_237_316_000
    REPAIR_MS = 1_794_422_374_862
    residual = [
        r
        for r in clean
        if (r["openedAt"] or 0) < PRICE_FIX_MS and (r["doneAt"] or 0) > REPAIR_MS
    ]
    strict = [r for r in clean if r not in residual]
    # FORWARD population: opened at/after 2026-10-29 (the day the card was written) and not
    # basis-contaminated — the population the card's ">=300 forward legs" clause actually names.
    FORWARD_MS = 1_793_287_841_000
    fwd = [r for r in strict if (r["openedAt"] or 0) >= FORWARD_MS]
    t60 = [r for r in rows if r["coverLagMs"] is not None and r["coverLagMs"] <= TAKER60_LAG_MS]
    t60clean = [r for r in t60 if not r["repaired"]]
    t60strict = [r for r in t60clean if r not in residual]

    report = {
        "db": db,
        "snapshotAt": snap.get("ranAt"),
        "artifactLegs": len(legs),
        "settledStamped": len(rows),
        "repairedInPopulation": len(dirty),
        "residualExposure": len(residual),
        "strictlyClean": len(strict),
        "forwardClean": len(fwd),
        "repairLedgerRows": len(repaired),
        "preimageRows": len(pre),
        "cells": {
            "all/as-of-today": measure("as-of-today", rows),
            "all/as-booked": measure("as-booked", rows),
            "clean/as-of-today": measure("as-of-today", clean),
            "clean/as-booked": measure("as-booked", clean),
            "repaired/as-of-today": measure("as-of-today", dirty),
            "repaired/as-booked": measure("as-booked", dirty),
            "taker60/as-of-today": measure("as-of-today", t60),
            "taker60/as-booked": measure("as-booked", t60),
            "taker60-clean/as-booked": measure("as-booked", t60clean),
            "strict/as-of-today": measure("as-of-today", strict),
            "strict/as-booked": measure("as-booked", strict),
            "taker60-strict/as-booked": measure("as-booked", t60strict),
            "residual/as-booked": measure("as-booked", residual),
            "forward-clean/as-booked": measure("as-booked", fwd),
        },
    }

    if args.json:
        print(json.dumps(report, indent=2))
        return

    print(f"db            {db}")
    print(f"artifact      {snap.get('ranAt')}  legs={len(legs)}")
    print(f"preimage      {len(pre)} rows · repair ledger {len(repaired)} ids")
    print(f"population    {len(rows)} settled stamped legs · {len(dirty)} repaired by d974287 ({100*len(dirty)/max(1,len(rows)):.1f}%) · "
          f"{len(residual)} residual-exposure · {len(strict)} strictly clean")
    print()
    hdr = f"{'cell':26} {'n':>4} {'notional':>9} {'booked':>9} {'rebooked':>9} {'Δpp':>7} {'pfillΔ':>7} {'bothΔ':>7} {'mean c':>7} {'med c':>6} {'±0.3c':>6}"
    print(hdr)
    print("-" * len(hdr))
    def f(x, width, prec):
        return "—".rjust(width) if x is None else f"{x:>{width}.{prec}f}"

    for k, v in report["cells"].items():
        d = v["delta"]
        band = "—".rjust(5) if d.get("shareWithinBand") is None else format(d["shareWithinBand"] * 100, "5.1f")
        print(
            f"{k:26} {v['n']:>4} {v['notionalUsd']:>9.2f} {v['bookedPnlUsd']:>9.2f} "
            f"{v['rebookedPnlUsd']:>9.2f} {f(v['roiDeltaPp'], 7, 2)} {f(v['pfill']['roiDeltaPp'], 7, 2)} "
            f"{f(v['combined']['roiDeltaPp'], 7, 2)} {f(d['meanC'], 7, 3)} {f(d['medianC'], 6, 2)} {band}%"
        )
    print()
    print("as-of-today = current PaperTrade row (a naive re-run)")
    print("as-booked   = preimage row for repaired legs (the basis the booth measured against)")
    print("clean-*     = legs the repair never touched (control)")


if __name__ == "__main__":
    main()
