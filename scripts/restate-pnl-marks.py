#!/usr/bin/env python3
"""restate-pnl-marks.py -- the WRITE half of the PnlSnapshot mark restatement.

Card: pnlsnapshot-mark-restatement (Lane A -- WAITS FOR APPROVAL).
Proposal + measurement: drafts/pnlsnapshot-mark-restatement-20261111.md
Measurement script:    scripts/pnlsnapshot-mark-restatement-measure.py

WHAT IT DOES (and nothing else)
  For every PnlSnapshot mark row attached to one of the 233 legs repaired by
  apply-ledger-price-side.py (applied 2026-11-11T18:39:34Z), rewrite `price` and
  `pnl` into the leg's OWN frame:

    pre-fix mark, leg holds token index 1  ->  price' = 1 - price   (it carried
                                               the positional read of the FIRST
                                               token, i.e. the sibling's price)
    pre-fix mark, leg holds token index 0  ->  price' = price       (the positional
                                               read already WAS its own token)
    post-fix mark (written after the 2026-11-09 write fix) -> price' = price
    pnl' = computePnl(repaired entryPrice, price', simulatedPositionSize)  [always]

  It also handles the two classes it must NOT guess at:
    * the 196 marks the repair itself APPENDED (identified by snapshotId inside the
      applied ledger) are final and are left alone;
    * marks on legs whose fillStatus is 'unfilled' were never positions -- left
      alone by default (`--zero-unfilled` restates them to 0 as an alternative).

  Then it prints the exact command to rebuild the pre-aggregate:
      npm run rollup:pnl -- --rebuild
  (the incremental path only recomputes from the last stored hour minus 2h, so a
  historical rewrite is invisible to it).

SAFETY
  * dry run by default; nothing is written without --apply.
  * every UPDATE is guarded on the full pre-image
    (`WHERE id=? AND price=? AND pnl=?`) -- a row that moved aborts the whole run.
  * it refuses to touch a leg that is still OPEN (a live mark must never move on a
    historical rewrite), and refuses a mark whose timestamp is after the leg ended.
  * it dumps a full-row pre-image of every row it touches, in the same shape as
    data/repair-manifests/ledger-price-side-applied-*.jsonl, before writing;
    `--rollback <file>` restores from it and writes nothing else.
  * README of the numbers it will move is printed in the dry run: per bot, per
    rollup cell, and the new SUM(PnlSnapshot.pnl).

USAGE
  COPYBOT_DB=$PWD/prisma/dev.db python3 scripts/restate-pnl-marks.py            # dry run
  ... --apply
  COPYBOT_DB=$PWD/prisma/dev.db python3 scripts/restate-pnl-marks.py --rollback <ledger.jsonl> --apply
"""
import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.request
from collections import defaultdict

DB = os.environ.get("COPYBOT_DB", "prisma/dev.db")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPLIED = os.path.join(ROOT, "data/repair-manifests/ledger-price-side-applied-20261111T123934.jsonl")
MANIFEST = os.path.join(ROOT, "data/repair-manifests/ledger-price-side-20261111.jsonl")
TOKENS = "/tmp/mark-restatement-tokens.json"   # venue token-list cache (keyless, refetchable)
CODE_FIX_MS = 1794237316000     # 2026-11-09T15:15:16Z -- commit fbf9073


def con(rw):
    c = sqlite3.connect(f"file:{DB}?mode={'rw' if rw else 'ro'}", uri=True, timeout=60)
    c.row_factory = sqlite3.Row
    return c


def compute_pnl(entry, price, size):
    """src/lib/paper.ts computePnl -- keep this byte-identical to the source."""
    if not entry or entry <= 0:
        return 0.0
    return round((size / entry) * price - size, 2)


def norm(s):
    return "".join(ch for ch in (s or "").upper() if ch.isalnum())


def load_tokens(conds):
    cache = json.load(open(TOKENS)) if os.path.exists(TOKENS) else {}
    miss = [x for x in conds if x and x not in cache]
    for cond in miss:
        try:
            req = urllib.request.Request(
                f"https://clob.polymarket.com/markets/{cond}",
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
                         "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=25) as r:
                m = json.load(r)
            cache[cond] = [t.get("outcome") for t in (m.get("tokens") or [])]
        except Exception as e:
            print(f"  WARN token list unavailable for {cond}: {e}")
            cache[cond] = []
        time.sleep(0.25)
    if miss:
        os.makedirs(os.path.dirname(TOKENS), exist_ok=True)
        json.dump(cache, open(TOKENS, "w"), indent=1)
    return cache


def leg_index(tokens, cond, outcome):
    labels = tokens.get(cond) or []
    if len(labels) != 2:
        return None
    tgt = norm(outcome)
    hit = [k for k, lab in enumerate(labels) if norm(lab) == tgt]
    if len(hit) == 1:
        return hit[0]
    hit = [k for k, lab in enumerate(labels)
           if norm(lab) and (norm(lab) in tgt or tgt in norm(lab))]
    return hit[0] if len(hit) == 1 else None


def plan_rows(c, only_measured, zero_unfilled):
    app = [json.loads(l) for l in open(APPLIED) if l.strip()]
    man = {r["paperTradeId"]: r for r in (json.loads(l) for l in open(MANIFEST) if l.strip())}
    appended = {r["snapshotId"] for r in app[1:] if r.get("snapshotId")}
    ids = list(man)
    ph = ",".join("?" * len(ids))
    trades = {r["id"]: dict(r) for r in c.execute(f"SELECT * FROM PaperTrade WHERE id IN ({ph})", ids)}

    open_legs = [i for i in ids if trades[i]["status"] == "open"]
    if open_legs:
        raise SystemExit(f"refusing: {len(open_legs)} repaired legs are still OPEN "
                         f"(a live mark must not move on a historical rewrite): {open_legs[:3]}")

    tokens = load_tokens(sorted({man[i].get("conditionId") for i in ids if man[i].get("conditionId")}))
    idx = {i: leg_index(tokens, man[i].get("conditionId"), trades[i]["outcome"]) for i in ids}

    marks = [dict(r) for r in c.execute(
        f"SELECT id, paperTradeId, price, pnl, collectedAt FROM PnlSnapshot "
        f"WHERE paperTradeId IN ({ph}) ORDER BY collectedAt", ids)]

    # venue matches, only for the conservative arm
    near = {}
    if only_measured:
        for r in marks:
            if r["id"] in appended or r["paperTradeId"] not in idx:
                continue
            m = trades[r["paperTradeId"]]
            best = None
            for row in c.execute(
                    "SELECT collectedAt, yesPrice, noPrice FROM MarketSnapshot "
                    "WHERE marketId=? AND collectedAt BETWEEN ? AND ?",
                    (m["marketId"], r["collectedAt"] - 180 * 60 * 1000, r["collectedAt"] + 180 * 60 * 1000)):
                dt = abs(row["collectedAt"] - r["collectedAt"])
                if best is None or dt < best[0]:
                    best = (dt, row["yesPrice"], row["noPrice"])
            if best is not None:
                near[r["id"]] = best

    plan = []
    skipped = defaultdict(int)
    for r in marks:
        pid = r["paperTradeId"]
        t, m = trades[pid], man[pid]
        if r["id"] in appended:
            skipped["repair-appended final"] += 1
            continue
        end = t["closedAt"] if t["closedAt"] is not None else t["resolvedAt"]
        if end is not None and r["collectedAt"] > end:
            skipped["mark stamped after the leg ended"] += 1
            continue
        if t.get("fillStatus") == "unfilled":
            if not zero_unfilled:
                skipped["unfilled leg (never a position)"] += 1
                continue
            new_px, new_pnl = 0.0, 0.0
        else:
            if r["collectedAt"] < CODE_FIX_MS:
                use_mirror = idx.get(pid) != 0        # None = unmapped leg: mirror
            else:
                use_mirror = False
            if only_measured:
                b = near.get(r["id"])
                if b is None or idx.get(pid) is None:
                    skipped["no venue print within 180 min"] += 1
                    continue
                own = b[1] if idx[pid] == 0 else b[2]
                if own is None:
                    skipped["venue print unpriced"] += 1
                    continue
                d_own = abs(r["price"] - own)
                d_mir = abs((1.0 - r["price"]) - own)
                if abs(d_own - d_mir) <= 0.02:
                    skipped["frame ambiguous at the venue"] += 1
                    continue
                use_mirror = d_mir < d_own
            new_px = round(1.0 - r["price"], 6) if use_mirror else r["price"]
            new_pnl = compute_pnl(t["entryPrice"], new_px, t["simulatedPositionSize"])
        if abs(new_px - r["price"]) < 1e-9 and abs(new_pnl - r["pnl"]) < 1e-9:
            skipped["no change"] += 1
            continue
        plan.append({"snapshotId": r["id"], "paperTradeId": pid, "botId": t["botId"],
                     "collectedAt": r["collectedAt"],
                     "pre": {"price": r["price"], "pnl": r["pnl"]},
                     "post": {"price": new_px, "pnl": new_pnl},
                     "delta": new_pnl - r["pnl"]})
    return plan, skipped, len(marks)


def report(plan, skipped, n_marks, c):
    tot = sum(p["delta"] for p in plan)
    per_bot = defaultdict(lambda: [0, 0.0])
    cells = defaultdict(float)
    for p in plan:
        g = per_bot[p["botId"]]
        g[0] += 1
        g[1] += p["delta"]
        cells[(p["collectedAt"] // 3_600_000, p["botId"])] += p["delta"]
    print(f"marks on the repaired legs: {n_marks}")
    for k, v in sorted(skipped.items()):
        print(f"  skipped: {k:<38} {v:>5}")
    print(f"\nrows to restate: {len(plan)}   net pnl delta: {tot:+,.2f}")
    for bot, (n, d) in sorted(per_bot.items()):
        print(f"  {bot:<13} rows {n:>5}  delta {d:>+10,.2f}")
    moved = {k: v for k, v in cells.items() if abs(v) > 0.005}
    print(f"  rollup cells moved: {len(moved)}   largest "
          f"{max((abs(v) for v in moved.values()), default=0):,.2f}")
    cur = c.execute("SELECT COUNT(*) n, SUM(pnl) s FROM PnlSnapshot").fetchone()
    roll = c.execute("SELECT COUNT(*) n, SUM(totalPnl) s FROM PnlHourlyRollup").fetchone()
    print(f"\n  SUM(PnlSnapshot.pnl) {cur['s']:,.2f} -> {cur['s'] + tot:,.2f}")
    print(f"  SUM(PnlHourlyRollup) {roll['s']:,.2f} -> {roll['s'] + tot:,.2f}   "
          f"after `npm run rollup:pnl -- --rebuild`")
    return tot


def apply(plan, c):
    stamp = time.strftime("%Y%m%dT%H%M%S")
    path = os.path.join(ROOT, "data", "repair-manifests", f"mark-restatement-applied-{stamp}.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    c.execute("BEGIN IMMEDIATE")
    try:
        for p in plan:
            n = c.execute("UPDATE PnlSnapshot SET price=?, pnl=? WHERE id=? AND price=? AND pnl=?",
                          (p["post"]["price"], p["post"]["pnl"], p["snapshotId"],
                           p["pre"]["price"], p["pre"]["pnl"])).rowcount
            if n != 1:
                raise RuntimeError(f"guard failed on {p['snapshotId']}: {n} rows changed (expected 1)")
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK")
        raise
    with open(path, "w") as f:
        f.write(json.dumps({"type": "header", "appliedAt": int(time.time() * 1000),
                            "rows": len(plan), "pnlDelta": round(sum(p["delta"] for p in plan), 2),
                            "rule": "pre-fix & idx!=0 -> price'=1-price; pnl'=computePnl(repaired "
                                    "entryPrice, price', size); appended finals and unfilled legs untouched",
                            "source": APPLIED}, sort_keys=True) + "\n")
        for p in plan:
            f.write(json.dumps({"type": "row", **p}, sort_keys=True) + "\n")
    print(f"applied {len(plan)} rows\nledger (rollback source): {path}")
    print("next: npm run rollup:pnl -- --rebuild   # the incremental path cannot see history")


def rollback(path, c, do_apply):
    rows = [json.loads(l) for l in open(path) if l.strip()]
    hdr, rows = (rows[0], rows[1:]) if rows and rows[0].get("type") == "header" else (None, rows)
    print(f"rollback ledger {path}: {len(rows)} rows" + (f", applied {hdr['appliedAt']}" if hdr else ""))
    if do_apply:
        c.execute("BEGIN IMMEDIATE")
        try:
            for r in rows:
                n = c.execute("UPDATE PnlSnapshot SET price=?, pnl=? WHERE id=? AND price=? AND pnl=?",
                              (r["pre"]["price"], r["pre"]["pnl"], r["snapshotId"],
                               r["post"]["price"], r["post"]["pnl"])).rowcount
                if n != 1:
                    raise RuntimeError(f"rollback guard failed on {r['snapshotId']}")
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise
        print(f"restored {len(rows)} rows — run `npm run rollup:pnl -- --rebuild` afterwards")
    else:
        print("DRY RUN -- nothing written. Re-run with --apply.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--only-measured", action="store_true",
                    help="restate only marks the venue can decide (the card's literal gate)")
    ap.add_argument("--zero-unfilled", action="store_true",
                    help="restate marks on unfilled legs to price/pnl 0 as well")
    ap.add_argument("--rollback", default=None, help="restore from a ledger written by --apply")
    a = ap.parse_args()

    c = con(a.apply)
    if a.rollback:
        rollback(a.rollback, c, a.apply)
        return 0
    plan, skipped, n = plan_rows(c, a.only_measured, a.zero_unfilled)
    report(plan, skipped, n, c)
    if not a.apply:
        print("\nDRY RUN -- nothing written. Re-run with --apply.")
        return 0
    if not plan:
        print("nothing to restate")
        return 0
    apply(plan, c)
    return 0


if __name__ == "__main__":
    sys.exit(main())
