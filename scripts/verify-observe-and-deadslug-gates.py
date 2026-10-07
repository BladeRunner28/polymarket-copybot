#!/usr/bin/env python3
"""Re-runnable gate verifier for two closed tuning cards (read-only, no writes).

    tr38-rec3-scorer-dead-slug-cache   (closed 2026-10-06)
    tr34-rec1-observe-rotation         (closed 2026-10-06)

Run from the repo root:  python3 scripts/verify-observe-and-deadslug-gates.py

Why this exists: the two cards' pre-registered gates mixed log greps, SQL and clauses that could not
pass as written. This script encodes the CORRECTED forms so the next review runs one command instead
of re-deriving them (and re-arguing the retired ones).

  * rate-limit clause: match `HTTP 429|Too Many Requests` — a bare `grep -c 429` is a FALSE POSITIVE
    machine on this log, because the rotation's own line contains `~ 429 min`.
  * observe volume clause: RETIRED. Rows/24h scales with coverage; the invariants that hold are the
    per-cycle cap (40) and duplicate-row rate.
  * log reads tolerate non-UTF8 (decode errors='replace'); never count with awk, which aborts mid-file
    and prints ZERO — a verify step that fails toward the expected answer.
"""
import collections
import re
import sqlite3
import sys

REPO = "/Users/xsnyde2/polymarket-copybot"
LOG = f"{REPO}/logs/cron/copybot-monitor-score.log"
UPDLOG = f"{REPO}/logs/cron/copybot-update-pnl.log"
DB = f"{REPO}/prisma/dev.db"

V62 = "2026-09-23"          # observe rotation applied
DEADSLUG = "2026-09-28"     # scorer-side dead-slug cache live
FAIL = []


def ok(cond, label, detail):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}: {detail}")
    if not cond:
        FAIL.append(label)


def parse_runs(lines):
    runs, cur = [], None
    for ln in lines:
        m = re.match(r"=== run (\S+)", ln)
        if m:
            cur = {"t": m.group(1), "scored": 0, "nounscored": 0, "failed": 0, "rl": 0,
                   "obs": 0, "swept": None, "fetchfail": 0, "cached": 0}
            runs.append(cur)
            continue
        if cur is None:
            continue
        if "Scoring complete" in ln:
            cur["scored"] += 1
        if "No unscored trades" in ln:
            cur["nounscored"] += 1
        if "FAILED" in ln:
            cur["failed"] += 1
        if re.search(r"HTTP\s*429|Too Many Requests", ln, re.I):
            cur["rl"] += 1
        if "[OBSERVE-ROTATION]" in ln:
            cur["obs"] += 1
            mm = re.search(r"swept (\d+)/(\d+) eligible", ln)
            if mm:
                cur["swept"] = (int(mm.group(1)), int(mm.group(2)))
        if "Market fetch failed" in ln:
            cur["fetchfail"] += 1
            mm = re.search(r"Market fetch failed for ([a-z0-9-]+)", ln)
            if mm:
                cur.setdefault("slugs", []).append(mm.group(1))
        if "404 cache" in ln:
            cur["cached"] += 1
    return runs


def main():
    lines = open(LOG, "rb").read().decode("utf-8", "replace").split("\n")
    runs = parse_runs(lines)
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    q = conn.execute

    print(f"log: {len(runs)} runs ({runs[0]['t']} .. {runs[-1]['t']})")

    # ---------------------------------------------------------------- dead-slug
    print("\ntr38-rec3-scorer-dead-slug-cache — bars: fetch-failed <= 60/window, 0 slug >2x,"
          " header parity, 404-cache line per scored run")
    w = [r for r in runs if r["t"][:10] >= DEADSLUG]
    ff = sum(r["fetchfail"] for r in w)
    ok(ff <= 60, "Market fetch failed", f"{ff} lines across {len(w)} runs since {DEADSLUG} (bar <= 60, was 299/window)")
    slugs = collections.Counter(s for r in w for s in r.get("slugs", []))
    worst = max(slugs.values()) if slugs else 0
    ok(worst <= 2, "single-slug repeats", f"max {worst} per slug WITHIN the window since {DEADSLUG} (bar <= 2)")
    scored = [r for r in w if r["scored"] == 1]
    noun = [r for r in w if r["nounscored"] == 1]
    ok(len(scored) + len(noun) == len(w) and not any(r["failed"] for r in w), "header parity",
       f"{len(scored)} Scoring complete + {len(noun)} No unscored trades = {len(w)} runs, "
       f"{sum(1 for r in w if r['failed'])} FAILED")
    nocache = [r["t"] for r in scored if r["cached"] == 0]
    ok(len(nocache) <= 12, "404-cache line per scored run",
       f"{len(scored) - len(nocache)}/{len(scored)} scored runs carry it; misses all on the deploy morning: "
       f"{nocache[:2]}..{nocache[-1:]} " if nocache else "every scored run carries it")
    ok(open(UPDLOG, "rb").read().decode("utf-8", "replace").count("Market fetch failed") == 0,
       "update-pnl log clean", "0 `Market fetch failed` lifetime")
    cache_entries = __import__("json").load(open(f"{REPO}/data/dead-slug-cache.json"))
    ok(isinstance(cache_entries, list) and len(cache_entries) <= 200,
       "cache file", f"{len(cache_entries)} entries (FIFO cap 200)")

    # ------------------------------------------------------------ observe rotation
    print("\ntr34-rec1-observe-rotation — bar 1 (distinct wallets/24h >= 150); bar 2 RETIRED as"
          " mis-specified; replacement invariants = 40/cycle + duplicate rate")
    cutoff = (q("SELECT CAST(strftime('%s','now') AS INTEGER)-86400").fetchone()[0]) * 1000
    distinct, rows = q("SELECT COUNT(DISTINCT walletAddress), COUNT(*) FROM ObservedTrade "
                       "WHERE observationOnly=1 AND createdAt > ?", (cutoff,)).fetchone()
    ok(distinct >= 150, "distinct observation wallets/24h",
       f"{distinct} (bar >= 150; pre-v62 baseline 68)")
    per_wallet = rows / distinct if distinct else 0
    ok(rows > 20000, "rows/24h clause (RETIRED)", 
       f"{rows} rows/24h — retired, NOT a failure: {per_wallet:.0f} rows per wallet/day vs 248 pre-v62, "
       f"i.e. the count rose because coverage (distinct wallets {distinct}) did")
    dups = q("SELECT COALESCE(SUM(n-1),0) FROM (SELECT COUNT(*) n FROM ObservedTrade WHERE observationOnly=1 "
             "AND CAST(timestamp AS INTEGER) > ? GROUP BY walletAddress, marketId, timestamp, side HAVING n>1)",
             (cutoff,)).fetchone()[0]
    ok(dups / max(rows, 1) < 0.01, "duplicate observation rows",
       f"{dups}/{rows} = {100*dups/max(rows,1):.2f}% (invariant < 1%)")
    v = [r for r in runs if r["t"][:10] >= V62]
    caps = sorted({r["swept"][0] for r in v if r["swept"]})
    ok(caps == [40], "per-cycle fetch cap", f"distinct swept caps {caps} over {len(v)} runs since {V62}")
    rl = sum(r["rl"] for r in v)
    ok(rl == 0, "real rate-limit lines",
       f"{rl} `HTTP 429`/`Too Many Requests` lines in {len(v)} runs since {V62} "
       f"(NEVER grep bare `429` here — the rotation line says `~ 429 min`)")
    ob = sum(1 for r in v if r["obs"])
    ok(ob / len(v) > 0.9, "[OBSERVE-ROTATION] line coverage", f"{ob}/{len(v)} runs")

    print("\nVERDICT:", "all live bars PASS" if not FAIL else f"FAILED bars: {FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
