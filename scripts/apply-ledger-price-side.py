#!/usr/bin/env python3
"""apply-ledger-price-side.py -- the WRITE half of the ledger price-side repair.

Card: ledger-price-side-repair (Lane A, approved 2026-11-11T18:35:34Z).
Proposal + manifest: drafts/ledger-price-side-repair-20261110.md

WHAT IT DOES (and nothing else)
  1. reads the pre/post manifest produced by scripts/profit-ledger-repair-preflight.py
     (233 finished PaperTrade rows whose booked entryPrice is the SIBLING token's price);
  2. dumps a full-row pre-image of every row it is about to touch + the BotBankroll rows;
  3. in ONE sqlite transaction:
       - UPDATE PaperTrade entryPrice / currentPrice / realizedPnl, each guarded on the
         pre-image (a row that moved since the manifest aborts the whole write);
       - posts the price-side DELTA to BotBankroll (BANKROLL_200 only -- STANDARD never
         posts to the bankroll by design, matching resolvePaperTrade/closePaperTrade);
       - appends one corrected PnlSnapshot row per repaired leg whose realizedPnl moved,
         backdated to the leg's own end time so the hourly series stays period-accurate
         (the dashboard's last-snapshot-per-trade read and the hourly rollup both pick it up;
         run `npm run rollup:pnl` afterwards so the pre-aggregate self-heals).
  4. writes a ledger (the rollback source) with the ids, pre/post values, snapshot ids and
     the bankroll before/after.

SAFETY
  * dry run by default; nothing is written without --apply.
  * every UPDATE is guarded: `WHERE id=? AND entryPrice=? AND realizedPnl IS ?`. A second
    run finds the repaired rows classify as *consistent*, so the class is empty and the run
    refuses (`nothing to repair`) instead of double-posting.
  * exit code 2 on a stale manifest (rows changed since generation) -- re-run the preflight.
  * the pre-image file it writes is a full `SELECT *` per row, so rollback never recomputes
    anything: scripts/rollback-ledger-price-side.py --ledger <file>.

USAGE
  COPYBOT_DB=$PWD/prisma/dev.db python3 scripts/apply-ledger-price-side.py \
      --manifest data/repair-manifests/ledger-price-side-20261111.jsonl           # dry run
  ... --apply
"""
import argparse
import json
import os
import secrets
import sqlite3
import sys
import time

DB = os.environ.get("COPYBOT_DB", "prisma/dev.db")
BANKROLL_BOTS = {"BANKROLL_200"}      # STANDARD skips BotBankroll by design
SNAP_EPS = 0.005                       # a leg whose pnl moved less than this needs no snapshot


def con(rw):
    c = sqlite3.connect(f"file:{DB}?mode={'rw' if rw else 'ro'}", uri=True, timeout=60)
    c.row_factory = sqlite3.Row
    return c


def load_manifest(path):
    recs = [json.loads(l) for l in open(path) if l.strip()]
    ids = [r["paperTradeId"] for r in recs]
    if len(ids) != len(set(ids)):
        raise SystemExit("manifest carries duplicate paperTradeId rows -- refusing")
    for r in recs:
        if r["status"] == "open":
            raise SystemExit(f"manifest carries an OPEN leg ({r['paperTradeId']}) -- refusing")
        if r["post"]["realizedPnl"] is None or r["post"]["exitPrice"] is None:
            raise SystemExit(f"manifest row {r['paperTradeId']} has no post image -- refusing")
    return recs


def end_ms(row):
    v = row["closedAt"] if row["closedAt"] is not None else row["resolvedAt"]
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    # DATETIME string fallback (should not happen on this DB: ms ints)
    return int(time.mktime(time.strptime(str(v)[:19], "%Y-%m-%d %H:%M:%S")) * 1000)


def crawl(c, recs):
    cur = {r["id"]: r for r in c.execute(
        f"SELECT * FROM PaperTrade WHERE id IN ({','.join('?' * len(recs))})",
        [r["paperTradeId"] for r in recs])}
    stale, plan = [], []
    for r in recs:
        d = cur.get(r["paperTradeId"])
        pre = r["pre"]
        if d is None:
            stale.append((r["paperTradeId"], "missing"))
            continue
        if (abs(d["entryPrice"] - pre["entryPrice"]) > 1e-9
                or abs(d["currentPrice"] - pre["currentPrice"]) > 1e-9
                or abs((d["realizedPnl"] or 0) - (pre["realizedPnl"] or 0)) > 1e-9):
            stale.append((r["paperTradeId"], "values moved since the manifest"))
            continue
        plan.append({"id": r["paperTradeId"], "row": r, "db": dict(d)})
    return cur, stale, plan


def snap_id(taken):
    while True:
        s = "crep" + secrets.token_hex(10)
        if s not in taken:
            taken.add(s)
            return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--apply", action="store_true", help="write; default is a dry run")
    ap.add_argument("--ledger", default=None,
                    help="where to write the rollback ledger (default data/repair-manifests/"
                         "ledger-price-side-applied-<ts>.jsonl)")
    a = ap.parse_args()

    recs = load_manifest(a.manifest)
    c = con(a.apply)
    cur, stale, plan = crawl(c, recs)
    print(f"manifest rows: {len(recs)}   present: {len(cur)}   repairable: {len(plan)}   "
          f"stale: {len(stale)}")
    if stale:
        for pid, why in stale[:10]:
            print(f"  STALE {pid}: {why}")
        print("stale manifest -- re-run scripts/profit-ledger-repair-preflight.py "
              "and re-generate on the day of the write")
        raise SystemExit(2)

    # ---- the plan, priced
    dpnl = {}
    n_snap = 0
    for p in plan:
        pre, post = p["row"]["pre"], p["row"]["post"]
        d = round((post["realizedPnl"] or 0) - (pre["realizedPnl"] or 0), 2)
        g = dpnl.setdefault(p["row"]["botId"], [0, 0.0, 0.0])
        g[0] += 1
        g[1] += d
        g[2] += pre["simulatedPositionSize"] or 0
        p["delta"] = d
        p["snap"] = abs(d) > SNAP_EPS
        n_snap += int(p["snap"])
    tot = sum(g[1] for g in dpnl.values())
    print(f"\nrow class delta: {tot:+,.2f}")
    for bot, (n, d, ntl) in sorted(dpnl.items()):
        print(f"  {bot:<13} rows {n:>4}  notional ${ntl:>10,.2f}  pnl delta {d:>+10,.2f}")
    print(f"snapshots to append (legs whose pnl moved): {n_snap}")

    bk = {}
    for bot in BANKROLL_BOTS:
        row = c.execute("SELECT * FROM BotBankroll WHERE botId=?", (bot,)).fetchone()
        if row is None:
            raise SystemExit(f"no BotBankroll row for {bot}")
        d = round(dpnl.get(bot, [0, 0.0, 0.0])[1], 2)
        bk[bot] = {"pre": dict(row), "delta": d,
                   "post": {"realizedPnl": round(row["realizedPnl"] + d, 6),
                            "cashBalance": round(row["cashBalance"] + d, 6)}}
        print(f"  bankroll {bot}: realizedPnl {row['realizedPnl']:,.2f} -> "
              f"{row['realizedPnl'] + d:,.2f}   cash {row['cashBalance']:,.2f} -> "
              f"{row['cashBalance'] + d:,.2f}")

    if not a.apply:
        print("\nDRY RUN -- nothing written. Re-run with --apply to execute.")
        return 0

    stamp = time.strftime("%Y%m%dT%H%M%S")
    predir = os.path.join("data", "repair-manifests")
    os.makedirs(predir, exist_ok=True)
    preimage = os.path.join(predir, f"ledger-price-side-preimage-{stamp}.json")
    ledger = a.ledger or os.path.join(predir, f"ledger-price-side-applied-{stamp}.jsonl")

    json.dump({"generatedAt": int(time.time() * 1000), "manifest": a.manifest,
               "paperTrade": [p["db"] for p in plan], "botBankroll": bk},
              open(preimage, "w"), indent=1, sort_keys=True)
    print(f"\npre-image (full rows): {preimage}")

    taken = set()
    applied = []
    t0 = time.time()
    c.execute("BEGIN IMMEDIATE")
    try:
        for p in plan:
            r, pre, post = p["row"], p["row"]["pre"], p["row"]["post"]
            n = c.execute(
                "UPDATE PaperTrade SET entryPrice=?, currentPrice=?, realizedPnl=? "
                "WHERE id=? AND entryPrice=? AND realizedPnl IS ?",
                (post["entryPrice"], post["exitPrice"], post["realizedPnl"],
                 p["id"], pre["entryPrice"], pre["realizedPnl"])).rowcount
            if n != 1:
                raise RuntimeError(f"guard failed on {p['id']}: {n} rows changed (expected 1)")
            end = end_ms(p["db"])
            snap = None
            if p["snap"]:
                if end is None:
                    raise RuntimeError(f"{p['id']} has no end timestamp -- cannot place a snapshot")
                sid = snap_id(taken)
                c.execute("INSERT INTO PnlSnapshot (id, paperTradeId, price, pnl, collectedAt) "
                          "VALUES (?,?,?,?,?)",
                          (sid, p["id"], post["exitPrice"], post["realizedPnl"], end + 1000))
                snap = sid
            snap_ts = (end + 1000) if (snap and end is not None) else None
            applied.append({"paperTradeId": p["id"], "botId": r["botId"],
                            "pre": pre, "post": post, "delta": p["delta"],
                            "snapshotId": snap, "snapshotCollectedAt": snap_ts})
        for bot, b in bk.items():
            n = c.execute(
                "UPDATE BotBankroll SET realizedPnl=?, cashBalance=?, updatedAt=? "
                "WHERE botId=? AND realizedPnl=? AND cashBalance=?",
                (b["post"]["realizedPnl"], b["post"]["cashBalance"],
                 int(time.time() * 1000), bot, b["pre"]["realizedPnl"],
                 b["pre"]["cashBalance"])).rowcount
            if n != 1:
                raise RuntimeError(f"bankroll guard failed on {bot}: {n} rows changed")
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK")
        raise

    with open(ledger, "w") as f:
        f.write(json.dumps({"type": "header", "appliedAt": int(time.time() * 1000),
                            "manifest": a.manifest, "preImage": preimage,
                            "rows": len(applied), "rowDelta": tot,
                            "botBankroll": bk}, sort_keys=True) + "\n")
        for row in applied:
            rec = {"type": "row", **row}
            f.write(json.dumps(rec, sort_keys=True) + "\n")
    print(f"applied {len(applied)} rows in {time.time() - t0:.1f}s")
    print(f"snapshots appended: {sum(1 for r in applied if r['snapshotId'])}")
    print(f"ledger (rollback source): {ledger}")
    print("next: npm run rollup:pnl   # let the hourly pre-aggregate self-heal")
    return 0


if __name__ == "__main__":
    sys.exit(main())
