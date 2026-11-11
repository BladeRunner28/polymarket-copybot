#!/usr/bin/env python3
"""rollback-ledger-price-side.py -- exact reversal of apply-ledger-price-side.py.

Reads the ledger the apply wrote (data/repair-manifests/ledger-price-side-applied-<ts>.jsonl)
and, in one transaction:
  * restores entryPrice / currentPrice / realizedPnl on every touched PaperTrade row,
    guarded on the POST image (a row that moved since the write aborts the rollback);
  * deletes the PnlSnapshot rows the apply appended, by id;
  * restores BotBankroll.realizedPnl / cashBalance to the pre-write values.

Nothing is recomputed: every value is the literal from the ledger.

USAGE
  COPYBOT_DB=$PWD/prisma/dev.db python3 scripts/rollback-ledger-price-side.py \
      --ledger data/repair-manifests/ledger-price-side-applied-20261111T182000.jsonl        # dry run
  ... --apply
"""
import argparse
import json
import os
import sqlite3
import sys
import time

DB = os.environ.get("COPYBOT_DB", "prisma/dev.db")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    header, rows = None, []
    for line in open(a.ledger):
        r = json.loads(line)
        if r.get("type") == "header":
            header = r
        elif r.get("type") == "row":
            rows.append(r)
    if header is None:
        raise SystemExit("ledger has no header -- refusing")

    c = sqlite3.connect(f"file:{DB}?mode={'rw' if a.apply else 'ro'}", uri=True, timeout=60)
    c.row_factory = sqlite3.Row

    # guards first, so a dry run reports exactly what a write would do
    ok, bad = 0, []
    for r in rows:
        d = c.execute("SELECT entryPrice, currentPrice, realizedPnl FROM PaperTrade WHERE id=?",
                      (r["paperTradeId"],)).fetchone()
        if d is None:
            bad.append((r["paperTradeId"], "missing"))
            continue
        if (abs(d["entryPrice"] - r["post"]["entryPrice"]) > 1e-9
                or abs(d["currentPrice"] - r["post"]["exitPrice"]) > 1e-9
                or abs((d["realizedPnl"] or 0) - (r["post"]["realizedPnl"] or 0)) > 1e-9):
            bad.append((r["paperTradeId"], "row moved since the repair"))
            continue
        ok += 1
    print(f"rows in ledger: {len(rows)}  restorable: {ok}  blocked: {len(bad)}")
    for pid, why in bad[:10]:
        print(f"  BLOCKED {pid}: {why}")
    snaps = [r for r in rows if r.get("snapshotId")]
    live_snaps = c.execute(
        f"SELECT COUNT(*) n FROM PnlSnapshot WHERE id IN ({','.join('?' * len(snaps))})",
        [r["snapshotId"] for r in snaps]).fetchone()["n"] if snaps else 0
    print(f"snapshots in ledger: {len(snaps)}  still present: {live_snaps}")

    if not a.apply:
        print("DRY RUN -- nothing written.")
        return 0
    if bad:
        raise SystemExit("refusing to roll back with blocked rows -- inspect first")

    c.execute("BEGIN IMMEDIATE")
    try:
        for r in rows:
            n = c.execute(
                "UPDATE PaperTrade SET entryPrice=?, currentPrice=?, realizedPnl=? "
                "WHERE id=? AND entryPrice=? AND realizedPnl IS ?",
                (r["pre"]["entryPrice"], r["pre"]["currentPrice"], r["pre"]["realizedPnl"],
                 r["paperTradeId"], r["post"]["entryPrice"], r["post"]["realizedPnl"])).rowcount
            if n != 1:
                raise RuntimeError(f"rollback guard failed on {r['paperTradeId']}")
        for r in snaps:
            c.execute("DELETE FROM PnlSnapshot WHERE id=? AND paperTradeId=?",
                      (r["snapshotId"], r["paperTradeId"]))
        for bot, b in (header.get("botBankroll") or {}).items():
            n = c.execute(
                "UPDATE BotBankroll SET realizedPnl=?, cashBalance=?, updatedAt=? "
                "WHERE botId=? AND realizedPnl=? AND cashBalance=?",
                (b["pre"]["realizedPnl"], b["pre"]["cashBalance"], int(time.time() * 1000),
                 bot, b["post"]["realizedPnl"], b["post"]["cashBalance"])).rowcount
            if n != 1:
                raise RuntimeError(f"bankroll rollback guard failed on {bot}")
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK")
        raise
    print(f"rolled back {len(rows)} rows, {len(snaps)} snapshots, {len(header.get('botBankroll') or {})} bankrolls")
    return 0


if __name__ == "__main__":
    sys.exit(main())
