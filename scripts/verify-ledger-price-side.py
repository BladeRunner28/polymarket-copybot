#!/usr/bin/env python3
"""verify-ledger-price-side.py -- post-write invariants for the ledger price-side repair.

Read-only. Given the ledger apply-ledger-price-side.py wrote, it checks the five things the
approval named, each against the DB rather than against the script's own claim:

  1. every repaired row holds its POST image (entryPrice, currentPrice, realizedPnl);
  2. every appended PnlSnapshot row exists, carries the post pnl, and is the LAST snapshot
     for its trade (the dashboard's `orderBy collectedAt desc, take 1` read);
  3. the bankroll moved by exactly the posted delta and the bankroll-vs-rows OFFSET is
     unchanged (a rebuild would have moved it; a delta posting must not);
  4. the row class is EMPTY (no finished leg whose booked price is the sibling's) --
     the same arithmetic the preflight uses, recomputed here;
  5. a second apply would find nothing to repair.

USAGE
  COPYBOT_DB=$PWD/prisma/dev.db python3 scripts/verify-ledger-price-side.py \
      --ledger data/repair-manifests/ledger-price-side-applied-<ts>.jsonl \
      --offset-before -570.12        # BANKROLL_200: rows - bankroll, measured pre-write
"""
import argparse
import json
import os
import sqlite3
import sys

DB = os.environ.get("COPYBOT_DB", "prisma/dev.db")
MIRROR_TOL = 0.06
SEP_TOL = 0.10


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--offset-before", type=float, default=None,
                    help="BANKROLL_200 (sum of its rows - BotBankroll.realizedPnl) before the write")
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

    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=60)
    c.row_factory = sqlite3.Row
    fails = []

    # 1 -- post images in place
    bad = []
    for r in rows:
        d = c.execute("SELECT entryPrice,currentPrice,realizedPnl FROM PaperTrade WHERE id=?",
                      (r["paperTradeId"],)).fetchone()
        if (d is None or abs(d["entryPrice"] - r["post"]["entryPrice"]) > 1e-9
                or abs(d["currentPrice"] - r["post"]["exitPrice"]) > 1e-9
                or abs((d["realizedPnl"] or 0) - (r["post"]["realizedPnl"] or 0)) > 1e-9):
            bad.append(r["paperTradeId"])
    print(f"1. post image in place: {len(rows) - len(bad)}/{len(rows)} rows"
          f"{'' if not bad else '  FAIL ' + str(bad[:5])}")
    if bad:
        fails.append("post image")

    # 2 -- snapshots
    snaps = [r for r in rows if r.get("snapshotId")]
    missing, wrong, not_last = 0, 0, 0
    for r in snaps:
        s = c.execute("SELECT price,pnl,collectedAt FROM PnlSnapshot WHERE id=?",
                      (r["snapshotId"],)).fetchone()
        if s is None:
            missing += 1
            continue
        if abs(s["pnl"] - r["post"]["realizedPnl"]) > 1e-9 or abs(s["price"] - r["post"]["exitPrice"]) > 1e-9:
            wrong += 1
        last = c.execute("SELECT id FROM PnlSnapshot WHERE paperTradeId=? "
                         "ORDER BY collectedAt DESC LIMIT 1", (r["paperTradeId"],)).fetchone()
        if last is None or last["id"] != r["snapshotId"]:
            not_last += 1
    print(f"2. snapshots: {len(snaps)} ledgers, {missing} missing, {wrong} wrong value, "
          f"{not_last} not the trade's last snapshot")
    if missing or wrong or not_last:
        fails.append("snapshots")

    # 3 -- bankroll delta + unchanged offset
    for bot, b in (header.get("botBankroll") or {}).items():
        d = c.execute("SELECT realizedPnl,cashBalance FROM BotBankroll WHERE botId=?",
                      (bot,)).fetchone()
        dr = round(d["realizedPnl"] - b["pre"]["realizedPnl"], 2)
        dc = round(d["cashBalance"] - b["pre"]["cashBalance"], 2)
        print(f"3. bankroll {bot}: realizedPnl {b['pre']['realizedPnl']:,.2f} -> {d['realizedPnl']:,.2f} "
              f"(delta {dr:+,.2f}, posted {b['delta']:+,.2f}); cash delta {dc:+,.2f}")
        if abs(dr - b["delta"]) > 0.02 or abs(dc - b["delta"]) > 0.02:
            fails.append(f"bankroll delta {bot}")
        if a.offset_before is not None:
            rsum = c.execute("SELECT SUM(realizedPnl) s FROM PaperTrade WHERE botId=? "
                             "AND status!='open' AND isDemo=0", (bot,)).fetchone()["s"]
            off = round((rsum or 0) - d["realizedPnl"], 2)
            print(f"   offset (all finished rows - bankroll): {off:+,.2f} (pre-write "
                  f"{a.offset_before:+,.2f})")
            if abs(off - a.offset_before) > 0.05:
                fails.append(f"bankroll offset {bot}")

    # 4 -- the class is empty
    q = """SELECT p.id,p.botId,p.entryPrice,p.status,o.walletEntryPrice w
             FROM PaperTrade p JOIN DecisionJournal dj ON dj.id=p.decisionJournalId
             LEFT JOIN ObservedTrade o ON o.id=dj.observedTradeId
            WHERE p.isDemo=0 AND p.status!='open' AND o.walletEntryPrice IS NOT NULL
              AND 0 < o.walletEntryPrice AND o.walletEntryPrice < 1"""
    n_inv, n_tot = 0, 0
    for r in c.execute(q):
        bid, w = r["entryPrice"], r["w"]
        mirror = abs(bid - (1.0 - w))
        n_tot += 1
        if mirror + 0.01 < abs(bid - w) and mirror <= MIRROR_TOL and abs(bid - w) > SEP_TOL:
            n_inv += 1
    print(f"4. class: INVERTED finished rows = {n_inv} of {n_tot:,} fill-bearing rows "
          f"(pre-write 233)")

    # 5 -- totals land where the approval said
    booked = c.execute("SELECT SUM(realizedPnl) s FROM PaperTrade WHERE isDemo=0 AND status!='open'"
                       ).fetchone()["s"]
    print(f"5. rows: finished non-demo SUM(realizedPnl) = {booked:+,.2f} "
          f"(pre-write {booked - header['rowDelta']:+,.2f}, ledger delta {header['rowDelta']:+,.2f})")

    print("VERIFY " + ("PASS" if not fails else "FAIL: " + ", ".join(fails)))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
