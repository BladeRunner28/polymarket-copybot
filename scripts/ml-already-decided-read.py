#!/usr/bin/env python3
"""ml-already-decided-read — what would excluding "the market was already decided at entry"
actually remove from the ML training population, and what does it cost the export's books?

READ-ONLY. Card `training-exclude-already-decided-rows` (Lane A proposal, 2026-11-16).

WHY THIS EXISTS
---------------
`DecisionJournal.alreadyDecidedAtEntry` (priceAtDecision >= 0.995) shipped 2026-11-14 and is
written at the scoring site, but `scripts/export-training-data.ts` has no filter for it, so an
entry at 0.998 is still a training row with a nearly predetermined label and an edge of ~0.
The proposal's job is to say HOW BIG that class is and WHAT removing it moves. A number quoted
in prose cannot be re-run, so it lives here instead.

THE FOUR ARMS (a filter can key on any of them; they are NOT the same population)
--------------------------------------------------------------------------------
  flag         DecisionJournal.alreadyDecidedAtEntry = 1        -- the column; live only from its epoch
  price        DecisionJournal.priceAtDecision >= 0.995         -- same rule, raw value, wider stamp
  detected     ObservedTrade.detectedPrice >= 0.995             -- the LEGACY proxy: the copied
                                                                  wallet's own print, which is the
                                                                  only basis a pre-epoch row has
  entry        PaperTrade.entryPrice >= 0.995                    -- our OWN booked price (mid minus
                                                                  the maker credit), so it can sit
                                                                  below 0.995 on a leg the market
                                                                  had already decided

WHY THE ARMS DISAGREE IS THE PROPOSAL'S SUBSTANCE: the column's history starts at its epoch, so a
column-only filter removes 0 rows today; the class the card names is carried by the detection
price on rows written before that epoch.

TWO SECONDARY EFFECTS THE FILTER HAS, MEASURED HERE RATHER THAN ASSUMED
----------------------------------------------------------------------
  * DUPLICATE PROMOTION. `dedupeFirstPerPosition` keeps the FIRST leg per
    (bot, wallet, market, outcome) in `openedAt` order, and the export filters in SQL, i.e.
    BEFORE the dedupe. Dropping a first leg therefore promotes a later duplicate leg into the
    population — a SQL filter can ADD rows while removing rows.
  * RECONCILIATION SCOPE. The export reconciles itself against the frozen
    `data/decision-dataset.manifest.json` on rows settled at or before that manifest's
    `generated_at`. Those rows include already-decided legs, so a naive filter makes the check
    fail BY CONSTRUCTION (the same defect class the fee-truth scope fix repaired). Counted here
    so the patch does not ship a check that can never pass.

Usage:  python3 scripts/ml-already-decided-read.py [--csv training_data.csv] [--json]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "prisma", "dev.db")
MANIFEST = os.path.join(ROOT, "data", "decision-dataset.manifest.json")
ALREADY_DECIDED_PRICE = 0.995  # mirrors src/lib/decision-provenance.ts


def fnum(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def pct(n, d):
    return "n/a" if not d else "%.1f%%" % (100.0 * n / d)


def load_population(path):
    with open(path) as fh:
        rows = list(csv.DictReader(fh))
    return rows


def journal_fields(con, decision_ids):
    """flag + priceAtDecision per decision id, in chunks (SQLite's variable limit)."""
    flag, price = {}, {}
    ids = sorted(decision_ids)
    for i in range(0, len(ids), 800):
        chunk = ids[i:i + 800]
        q = ("SELECT id, alreadyDecidedAtEntry, priceAtDecision FROM DecisionJournal "
             "WHERE id IN (%s)" % ",".join("?" * len(chunk)))
        for did, f, p in con.execute(q, chunk):
            flag[did] = int(f or 0)
            price[did] = p
    return flag, price


def arm_stats(rows, pred):
    sel = [r for r in rows if pred(r)]
    if not sel:
        return {"n": 0}
    y = [float(r["y_net_entry"]) for r in sel]
    pnl = [float(r["pnl_net_entry"]) for r in sel]
    ent = [float(r["entry_price"]) for r in sel]
    return {
        "n": len(sel),
        "share_of_population": 100.0 * len(sel) / len(rows),
        "y_rate": 100.0 * sum(y) / len(sel),
        "mean_net_entry": statistics.mean(pnl),
        "sum_net_entry": sum(pnl),
        "mean_entry": statistics.mean(ent),
    }


def duplicate_promotion(con, rows, pred):
    """For each excluded row, is there a later closed/resolved leg on the same position key?"""
    excluded = [r for r in rows if pred(r)]
    if not excluded:
        return {"excluded": 0, "promoted": 0, "promoted_rows": []}
    out = []
    for r in excluded:
        # The excluded row's own openedAt is the ORDER key the dedupe uses, so the leg that
        # would be promoted is the earliest qualifying row with a LATER openedAt on the key.
        own = con.execute("SELECT openedAt FROM PaperTrade WHERE id=?", (r["paper_trade_id"],)).fetchone()
        if own is None:
            continue
        cur = con.execute(
            "SELECT id, entryPrice, realizedPnl, openedAt FROM PaperTrade "
            "WHERE botId=? AND walletAddress=? AND marketId=? AND outcome=? AND id<>? "
            "  AND status IN ('closed','resolved') AND isDemo=0 AND realizedPnl IS NOT NULL "
            "  AND entryPrice > 0 AND entryPrice < 1 AND openedAt > ? "
            "ORDER BY openedAt ASC LIMIT 1",
            (r["bot_id"], r["wallet"], r["market_id"], r["outcome"], r["paper_trade_id"], own[0]),
        ).fetchall()
        if cur:
            out.append({"excluded_trade": r["paper_trade_id"], "promoted_trade": cur[0][0],
                        "promoted_entry": cur[0][1], "promoted_pnl": cur[0][2]})
    return {"excluded": len(excluded), "promoted": len(out), "promoted_rows": out}


def promoted_class(con, promoted_rows):
    """Of the legs a WHERE-level filter would re-admit, how many are THEMSELVES already decided?

    A promoted leg that is also decided is not a leak of the class, it is a second application of
    the same rule — so this number, not the raw count, is what a WHERE-level filter would still
    remove. It separates "swaps legs" (harmless) from "re-admits decided entries" (the defect).
    """
    if not promoted_rows:
        return {"promoted": 0, "promoted_also_decided": 0, "promoted_entry_mean": None}
    ids = [p["promoted_trade"] for p in promoted_rows]
    decided = 0
    for pid in ids:
        row = con.execute(
            "SELECT t.detectedPrice FROM PaperTrade pt JOIN DecisionJournal d ON d.id=pt.decisionJournalId "
            "JOIN ObservedTrade t ON t.id=d.observedTradeId WHERE pt.id=?", (pid,)).fetchone()
        if row and row[0] is not None and row[0] >= ALREADY_DECIDED_PRICE:
            decided += 1
    entries = [p["promoted_entry"] for p in promoted_rows if p["promoted_entry"] is not None]
    return {
        "promoted": len(promoted_rows),
        "promoted_also_decided": decided,
        "promoted_entry_mean": (sum(entries) / len(entries)) if entries else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=os.path.join(ROOT, "training_data.csv"))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(args.csv):
        print("training_data.csv not found at %s -- run the export first" % args.csv)
        return 1
    rows = load_population(args.csv)
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)

    dec_ids = {r["decision_id"] for r in rows}
    flag, price = journal_fields(con, dec_ids)

    def is_flag(r):
        return flag.get(r["decision_id"], 0) == 1

    def is_price(r):
        p = price.get(r["decision_id"])
        return p is not None and p >= ALREADY_DECIDED_PRICE

    def is_detected(r):
        p = fnum(r["detected_price"])
        return p is not None and p >= ALREADY_DECIDED_PRICE

    def is_entry(r):
        p = fnum(r["entry_price"])
        return p is not None and p >= ALREADY_DECIDED_PRICE

    arms = {
        "population": arm_stats(rows, lambda r: True),
        "flag": arm_stats(rows, is_flag),
        "price_at_decision": arm_stats(rows, is_price),
        "detected_price_proxy": arm_stats(rows, is_detected),
        "entry_price": arm_stats(rows, is_entry),
    }

    # ---- the SHAPE of the class: a time-and-era concentration, not a diffuse live phenomenon ----
    decided_rows = [r for r in rows if is_detected(r)]
    shape = {}
    if decided_rows:
        shape["decision_at_min"] = min(r["decision_at"] for r in decided_rows)
        shape["decision_at_max"] = max(r["decision_at"] for r in decided_rows)
        shape["before_boundary"] = len([r for r in decided_rows if r["decision_at"] < "2026-08-21"])
        era = {}
        for r in decided_rows:
            era[r["era"]] = era.get(r["era"], 0) + 1
        shape["by_era"] = era
        rsv = {}
        for r in decided_rows:
            k = r["rule_set_version"] or "null"
            rsv[k] = rsv.get(k, 0) + 1
        shape["by_rule_set_version"] = rsv

    # ---- threshold sensitivity: the 0.995 line is a POLICY choice, so show its neighbours ----
    sweep = []
    for t in (0.99, 0.995, 0.999):
        n = len([r for r in rows if (fnum(r["detected_price"]) or 0) >= t])
        sweep.append({"threshold": t, "n": n, "share": (100.0 * n / len(rows)) if rows else 0.0})

    # ---- the column's own clock, so "0 rows" can be read as epoch, not as a dead writer ----
    col = {}
    col["journal_rows_all"] = con.execute(
        "SELECT COUNT(*) FROM DecisionJournal WHERE isDemo=0").fetchone()[0]
    col["journal_rows_flagged"] = con.execute(
        "SELECT COUNT(*) FROM DecisionJournal WHERE isDemo=0 AND alreadyDecidedAtEntry=1").fetchone()[0]
    col["journal_rows_priced"] = con.execute(
        "SELECT COUNT(*) FROM DecisionJournal WHERE isDemo=0 AND priceAtDecision IS NOT NULL").fetchone()[0]
    col["epoch"] = con.execute(
        "SELECT datetime(MIN(createdAt)/1000,'unixepoch') FROM DecisionJournal "
        "WHERE alreadyDecidedAtEntry=1").fetchone()[0]
    # acted legs journaled since the epoch: the ONLY rows a column filter can ever see
    col["acted_rows_since_epoch"] = con.execute(
        "SELECT COUNT(*) FROM PaperTrade pt JOIN DecisionJournal d ON d.id=pt.decisionJournalId "
        "WHERE d.createdAt >= (SELECT MIN(createdAt) FROM DecisionJournal WHERE alreadyDecidedAtEntry=1)").fetchone()[0]

    # ---- dedupe promotion: a SQL filter runs before dedupeFirstPerPosition ----
    promo = duplicate_promotion(con, rows, is_detected)
    promo_class = promoted_class(con, promo["promoted_rows"])

    # ---- reconciliation scope: excluded rows the frozen manifest can still adjudicate ----
    recon = {}
    try:
        m = json.load(open(MANIFEST))
        as_of = m["generated_at"].replace("Z", "+00:00")
        import datetime as _dt
        as_of_ms = int(_dt.datetime.fromisoformat(as_of).timestamp() * 1000)
        in_scope = [r for r in rows if is_detected(r) and r["terminal_at"]
                    and int(_dt.datetime.fromisoformat(r["terminal_at"].replace("Z", "+00:00")).timestamp() * 1000) <= as_of_ms]
        recon = {
            "manifest_generated_at": m["generated_at"],
            "manifest_rows_emitted": m["rows_emitted"],
            "excluded_rows_in_manifest_scope": len(in_scope),
            "frozen_manifest_pnl_gross": m["pnl_gross"],
            "frozen_manifest_pnl_net_entry": m["pnl_net_entry"],
            "frozen_manifest_pnl_net_full": m["pnl_net_full"],
        }
    except Exception as exc:  # noqa: BLE001 - a missing manifest is data, not a crash
        recon = {"error": str(exc)}

    report = {"csv": args.csv, "rows": len(rows), "arms": arms, "column": col,
              "threshold_sweep": sweep, "class_shape": shape,
              "duplicate_promotion": {k: v for k, v in promo.items() if k != "promoted_rows"},
              "promoted_class": promo_class,
              "reconciliation": recon}

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0

    print("ML training population: %s" % args.csv)
    print("  rows %d | decision ids %d (joined %d) | decision_at %s .. %s" % (
        len(rows), len(dec_ids), len(flag), min(r["decision_at"] for r in rows),
        max(r["decision_at"] for r in rows)))
    print()
    print("  %-22s %7s %8s %8s %14s %14s %7s" % (
        "arm", "n", "share", "y=1", "mean_net_entry", "sum_net_entry", "mean@"))
    for name, a in arms.items():
        if not a["n"]:
            print("  %-22s %7d %8s %8s %14s %14s %7s" % (name, 0, "0.0%", "-", "-", "-", "-"))
            continue
        print("  %-22s %7d %8s %8s %14s %14s %7.3f" % (
            name, a["n"], pct(a["n"], len(rows)), pct(a["y_rate"], 100),
            "%+.3f" % a["mean_net_entry"], "%+.2f" % a["sum_net_entry"], a["mean_entry"]))
    print()
    print("Shape of the class (detection-print arm):")
    if shape:
        print("  decision_at %s .. %s | inside the frozen train window (<2026-08-21): %d of %d" % (
            shape["decision_at_min"], shape["decision_at_max"], shape["before_boundary"], len(decided_rows)))
        print("  by era: %s" % shape["by_era"])
        print("  by ruleSetVersion: %s" % shape["by_rule_set_version"])
    print()
    print("Threshold sensitivity on the detection print (the 0.995 line is a policy choice):")
    for s in sweep:
        print("  detected_price >= %.3f : %5d rows (%s of the population)" % (
            s["threshold"], s["n"], pct(s["n"], len(rows))))
    print()
    print("The column's own clock (why the flag arm is empty today):")
    print("  journal rows (isDemo=0): %d | flagged: %d | priceAtDecision stamped: %d" % (
        col["journal_rows_all"], col["journal_rows_flagged"], col["journal_rows_priced"]))
    print("  flag epoch (first flagged row): %s" % col["epoch"])
    print("  acted legs journaled since that epoch: %d" % col["acted_rows_since_epoch"])
    print()
    print("Duplicate promotion (the SQL filter runs BEFORE dedupeFirstPerPosition):")
    print("  excluded rows: %d | would re-admit a later leg on the same position key: %d" % (
        promo["excluded"], promo["promoted"]))
    if promo_class["promoted"]:
        not_decided = promo_class["promoted"] - promo_class["promoted_also_decided"]
        print("  of those promoted legs, already decided themselves: %d (mean booked entry %.3f), not decided: %d" % (
            promo_class["promoted_also_decided"], promo_class["promoted_entry_mean"] or 0.0, not_decided))
        print("  => a WHERE-level filter cannot see the dedupe's representative: it would swap %d of the "
              "%d keys for another already-decided leg and re-admit %d under a different row. Filter AFTER "
              "the dedupe so the POSITION is what gets dropped." % (
                  promo_class["promoted_also_decided"],
                  promo_class["promoted_also_decided"] + not_decided, not_decided))
    print()
    print("Reconciliation scope (frozen data/decision-dataset.manifest.json):")
    for k, v in recon.items():
        print("  %-36s %s" % (k, v))
    return 0


if __name__ == "__main__":
    sys.exit(main())
