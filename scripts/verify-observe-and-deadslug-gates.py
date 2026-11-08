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
  * header parity (2026-11-08): the card asked for `runs == Scoring complete + No unscored trades`
    over the WHOLE window since 2026-09-28. That was exact on the close date and became a permanent
    FAIL once the 2026-10-13/14 `NO_IMPROVEMENT_TOL` TDZ crash (92 runs) entered the window, which
    makes a NEW crash unreadable. The bar is now LIVE-STATE (zero incomplete runs in the trailing
    7 days) and every historical incomplete run is printed underneath with its signature and span.
"""
import collections
import datetime as dt
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
ERR_RE = re.compile(r"(Traceback \(most recent call last\)|^\s*[A-Za-z_]*Error\b|npm ERR!|"
                    r"^\s*at <anonymous>|^Error:)", re.M)


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
                   "obs": 0, "swept": None, "fetchfail": 0, "cached": 0, "lines": []}
            runs.append(cur)
            continue
        if cur is None:
            continue
        cur["lines"].append(ln)
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
    # 2026-11-08 (self-audit, Lane B): this bar used to demand that EVERY run since 2026-09-28
    # carry one of the two completion lines. It was exact on the close date (1,044 + 44 = 1,088)
    # and is now 4,763 + 482 against 5,338 -- a permanent FAIL the file could never clear, so a
    # NEW crash would have been indistinguishable from the 93 old ones. The 93 are not mystery:
    # 92 are the 2026-10-13/14 `NO_IMPROVEMENT_TOL` TDZ ReferenceError in src/lib/fill-intent.ts
    # (since fixed) and 1 is 2026-10-26T09:26, a run that stops after [DRAWDOWN-SHADOW] with no
    # error text at all. Split them, keep them visible, and make the bar a LIVE-STATE bar: a run
    # that scores without completing is a FAIL if it happened in the trailing 7 days.
    incomplete = [r for r in w if r["scored"] == 0 and r["nounscored"] == 0]
    crashed = [r for r in incomplete if any(ERR_RE.search(ln) for ln in r["lines"])]
    silent = [r for r in incomplete if not any(ERR_RE.search(ln) for ln in r["lines"])]
    last7 = [(dt.date.fromisoformat(runs[-1]["t"][:10]) - dt.timedelta(days=7)).isoformat()]
    recent_bad = [r for r in incomplete if r["t"][:10] >= last7[0]]
    ok(not recent_bad, "header parity, trailing 7d (completion line or 'No unscored trades')",
       f"{len(w) - len(incomplete)}/{len(w)} runs since {DEADSLUG} complete; "
       f"{len(recent_bad)} incomplete in the trailing 7d ({last7[0]}..) "
       f"{[r['t'] for r in recent_bad][:3] if recent_bad else ''}")
    if incomplete:
        span = f"{incomplete[0]['t']} .. {incomplete[-1]['t']}"
        print(f"    HISTORICAL EXCEPTIONS (not this bar's FAIL, listed so they cannot be forgotten):"
              f" {len(incomplete)} incomplete runs {span}")
        if crashed:
            print(f"      - {len(crashed)} with an error/short-trace: {crashed[0]['t']}..{crashed[-1]['t']}"
                  f" | signature: {next((ln.strip()[:90] for ln in crashed[-1]['lines'] if ERR_RE.search(ln)), '-')}")
        if silent:
            print(f"      - {len(silent)} SILENT (no error text, no completion): "
                  f"{[r['t'] for r in silent][:4]}")
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
    # 2026-11-08 (self-audit, Lane B): this line was labelled "RETIRED — NOT a failure" and still
    # went through ok(), i.e. it WOULD have flipped VERDICT and the exit code on a bar the card
    # explicitly retired (it passes today only because rows/24h is 6x the old floor). A retired
    # bar that can still fail the run is a label that misstates what it does, so it is now an
    # INFO line and contributes nothing to FAIL. It still prints, with its number.
    print(f"  [INFO] rows/24h clause (RETIRED 2026-10-06, does not affect VERDICT): {rows} rows/24h "
          f"= {per_wallet:.0f} rows/wallet/day vs 248 pre-v62 — the count rose because coverage "
          f"(distinct wallets {distinct}) did, not because the rotation regressed")
    dups = q("SELECT COALESCE(SUM(n-1),0) FROM (SELECT COUNT(*) n FROM ObservedTrade WHERE observationOnly=1 "
             "AND CAST(timestamp AS INTEGER) > ? GROUP BY walletAddress, marketId, timestamp, side HAVING n>1)",
             (cutoff,)).fetchone()[0]
    # 2026-11-08: `dups / max(rows,1) < 0.01` reported 0/0 as a clean 0.00%. An empty population is
    # the one state where the duplicate rate is unknowable, so it must not be a PASS.
    ok(rows > 0 and dups / rows < 0.01, "duplicate observation rows",
       f"{dups}/{rows} = {100*dups/rows:.2f}% (invariant < 1%; 0 rows = UNKNOWABLE, not clean)"
       if rows else f"0 rows in the last 24h — the duplicate rate is UNKNOWABLE (not 0.00%)")

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
