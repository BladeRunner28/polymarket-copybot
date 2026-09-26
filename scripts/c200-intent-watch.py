#!/usr/bin/env python3
"""
c200-intent-watch — watcher for the C-200 fill-intent instrument.

WHAT IT WATCHES (silent when healthy; the cron delivers stdout verbatim, so empty = no message)
  1. gate_cleared    measured C-200 legs (intentPrice stamped) >= 50 -> the c200-maker-fill-assumption
                     gate is runnable. Fires ONCE, with the distribution.
  2. unpaired_leg    a BANKROLL_200 leg booked on/after the instrument went live (2026-09-25 23:33 CDT)
                     with intentPrice still NULL -> the webhook half of the shadow is not stamping.
                     That is the documented failure signature ("FillIntent/write silently failing").
  3. gap_anomaly     a stamped leg whose (entry - intent) is neither the modelled -$0.02 nor the
                     sidecar's 0.01 clamp (intent - 0.02 < 0.01 -> entry 0.01, gap = 0.01 - intent).
                     Anything else means a leg was booked by a path that skipped the filler.
  4. unlinked_intent a FillIntent dispatched >20 min ago with no booked leg (paperTradeId NULL) —
                     dispatched but never booked.
  5. shadow_off      FILL_INTENT_SHADOW=0 visible in the running dashboard's environment.

Each alert fires once per distinct object (state file, default data/c200-intent-watch-state.json);
repeat ticks stay silent. Exit code is always 0 unless the watcher itself cannot read its inputs
(a failure to read is reported, not swallowed).

USAGE
  python3 scripts/c200-intent-watch.py                 # normal tick (silent when healthy)
  python3 scripts/c200-intent-watch.py --db <path> --state <path>   # fixture testing
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "prisma", "dev.db")
STATE = os.path.join(ROOT, "data", "c200-intent-watch-state.json")

# The instrument went live with the 23:33:14 CDT rebuild on 2026-09-25; legs booked before that
# legitimately carry no intent price (no backfill by design).
FLOOR_MS = 1790397194000
GATE_LEGS = 50
DELTA = 0.02
TOL = 1e-9
STALE_INTENT_MS = 20 * 60 * 1000
PORT = 3013


def db(path: str) -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)   # live edge: immutable=1 would hide WAL rows
    c.row_factory = sqlite3.Row
    return c


def load_state(path: str) -> dict:
    try:
        with open(path) as fh:
            s = json.load(fh)
        s.setdefault("alertedLegs", [])
        s.setdefault("alertedIntents", [])
        s.setdefault("flags", {})
        return s
    except Exception:
        return {"alertedLegs": [], "alertedIntents": [], "flags": {}}


def save_state(path: str, s: dict) -> None:
    s["alertedLegs"] = s["alertedLegs"][-500:]
    s["alertedIntents"] = s["alertedIntents"][-500:]
    s["updatedAt"] = int(time.time() * 1000)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(s, fh, indent=1)


def dashboard_env_shadow_off() -> bool:
    """FILL_INTENT_SHADOW=0 in the running dashboard process (revert switch left accidentally on)."""
    try:
        pids = subprocess.run(["lsof", "-nP", f"-iTCP:{PORT}", "-sTCP:LISTEN", "-t"],
                              capture_output=True, text=True, timeout=20).stdout.split()
        for pid in pids:
            env = subprocess.run(["ps", "eww", "-p", pid],
                                 capture_output=True, text=True, timeout=20).stdout
            if re.search(r"FILL_INTENT_SHADOW=0(\s|$)", env):
                return True
    except Exception:
        return False
    return False


def unrecorded_dispatches(log_path: str, newest_intent_ms: int | None, max_lines: int = 40000) -> int:
    """Scorer runs that logged 'Dispatching Execution Intent' AFTER the newest FillIntent row.

    The failure signature both shadow writers hide (they are never-throw by design): the copy either
    books without a stamp or the dispatch is logged and nothing is written. Run headers in the log are
    local ISO, so string comparison against the newest intent's local time is the comparison.
    """
    if not os.path.exists(log_path):
        return 0
    cutoff = ""
    if newest_intent_ms:
        cutoff = time.strftime("%Y-%m-%dT%H:%M:%S",
                               time.localtime((newest_intent_ms + 120000) / 1000))
    run_time, hits = None, 0
    try:
        with open(log_path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            back = min(size, 4_000_000)
            fh.seek(size - back)
            tail = fh.read().decode("utf-8", "ignore").splitlines()
    except Exception:
        return 0
    for line in tail[-max_lines:]:
        if line.startswith("=== run "):
            run_time = line.split()[2]
        elif "Dispatching Execution Intent" in line and run_time and (not cutoff or run_time > cutoff):
            hits += 1
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB)
    ap.add_argument("--state", default=STATE)
    ap.add_argument("--scorer-log", default=os.path.join(ROOT, "logs", "cron", "copybot-monitor-score.log"))
    ap.add_argument("--no-process-check", action="store_true")
    ap.add_argument("--now-ms", type=int, default=None, help="fixture testing: freeze the clock")
    a = ap.parse_args()
    now_ms = a.now_ms or int(time.time() * 1000)

    st = load_state(a.state)
    alerts: list[str] = []

    try:
        c = db(a.db)
        measured = c.execute(
            "SELECT COUNT(*) FROM PaperTrade WHERE botId='BANKROLL_200' AND isDemo=0 "
            "AND intentPrice IS NOT NULL").fetchone()[0]
        unpaired = [dict(r) for r in c.execute(
            "SELECT id, marketId, outcome, entryPrice, openedAt FROM PaperTrade "
            "WHERE botId='BANKROLL_200' AND isDemo=0 AND openedAt >= ? AND intentPrice IS NULL "
            "ORDER BY openedAt", (FLOOR_MS,))]
        stamped = [dict(r) for r in c.execute(
            "SELECT id, marketId, outcome, entryPrice, intentPrice, ROUND(entryPrice-intentPrice,6) AS gap "
            "FROM PaperTrade WHERE botId='BANKROLL_200' AND isDemo=0 AND intentPrice IS NOT NULL")]
        unlinked = [dict(r) for r in c.execute(
            "SELECT id, marketId, outcome, intentPrice, dispatchedAt FROM FillIntent "
            "WHERE paperTradeId IS NULL AND ? - dispatchedAt > ?", (now_ms, STALE_INTENT_MS))]
    except Exception as e:                                    # cannot read -> say so, do not swallow
        print(f"⚠️ **C-200 intent watch FAILED to read its inputs** — {e}. "
              f"The instrument's state is UNKNOWN this tick (not healthy).")
        return 0

    # 1. gate cleared
    if measured >= GATE_LEGS and not st["flags"].get("gateCleared"):
        dist = {}
        for r in stamped:
            key = f"{r['gap']:.4f}"
            dist[key] = dist.get(key, 0) + 1
        top = ", ".join(f"{k}: {v}" for k, v in sorted(dist.items(), key=lambda kv: -kv[1])[:4])
        alerts.append(
            f"✅ **C-200 fill-intent gate is RUNNABLE** — {measured} measured legs (bar {GATE_LEGS}). "
            f"Gap (entry - intent) distribution: {top}. Run `npx tsx scripts/fill-vs-intent.ts` for the full "
            f"read-out; the c200-maker-fill-assumption decision (keep / cut to measured / remove the 2¢) is now "
            f"answerable — still recommendation-only until you approve a PnL/sizing change.")
        st["flags"]["gateCleared"] = True

    # 2. unpaired legs (post-deploy legs with no stamp)
    new_unpaired = [r for r in unpaired if r["id"] not in st["alertedLegs"]]
    if new_unpaired:
        worst = ", ".join(f"{r['marketId']} {r['outcome']} @{r['entryPrice']}" for r in new_unpaired[:3])
        alerts.append(
            f"🚨 **C-200 intent stamp MISSING** — {len(new_unpaired)} leg(s) booked after the instrument went "
            f"live carry no intent price ({worst}). The dispatch→webhook half of the shadow is not landing: "
            f"check the dashboard bundle/start time vs the source mtime and whether the sidecar posted "
            f"`execution-result`. The copies themselves are unaffected.")

    # 3. gap anomaly
    bad = []
    for r in stamped:
        gap = r["gap"]
        clamped = abs(r["entryPrice"] - 0.01) < 1e-9 and r["intentPrice"] < 0.03   # sidecar's 0.01 floor
        if abs(gap + DELTA) > TOL and not clamped:
            bad.append(r)
    new_bad = [r for r in bad if r["id"] not in st["alertedLegs"]]
    if new_bad:
        worst = ", ".join(f"{r['marketId']} entry {r['entryPrice']} vs intent {r['intentPrice']} (gap {r['gap']})"
                          for r in new_bad[:3])
        alerts.append(
            f"🚨 **C-200 fill gap anomaly** — {len(new_bad)} leg(s) where (entry - intent) is not -$0.02: {worst}. "
            f"A leg was booked outside the sidecar's filler (or the clamp rule changed); the sweep's 2¢ "
            f"assumption does not describe these legs.")

    # 4. dispatched but never booked
    new_unlinked = [r for r in unlinked if r["id"] not in st["alertedIntents"]]
    if new_unlinked:
        worst = ", ".join(f"{r['marketId']} {r['outcome']} @{r['intentPrice']}"
                          f" ({int((now_ms - r['dispatchedAt']) / 60000)}m ago)" for r in new_unlinked[:3])
        alerts.append(
            f"⚠️ **C-200 intent dispatched but NOT booked** — {len(new_unlinked)} intent(s) older than 20 min "
            f"have no leg: {worst}. The sidecar accepted the dispatch but no execution-result webhook booked it "
            f"(the '4xx from a live sidecar is a silent no-op' question).")

    # 5. dispatches logged with no intent row (the silent-shadow-write signature)
    newest_intent_ms = None
    try:
        row = db(a.db).execute("SELECT MAX(dispatchedAt) FROM FillIntent").fetchone()
        newest_intent_ms = row[0] if row else None
    except Exception:
        pass
    miss = unrecorded_dispatches(a.scorer_log, newest_intent_ms)
    if miss and not st["flags"].get("dispatchUnrecorded"):
        alerts.append(
            f"🚨 **C-200 dispatch logged with NO intent row** — {miss} dispatch(es) in scorer runs after the "
            f"newest FillIntent ({time.strftime('%Y-%m-%d %H:%M', time.localtime((newest_intent_ms or 0) / 1000))}) "
            f"wrote nothing. Both shadow writers are never-throw, so this is a swallowed error (a copy may still "
            f"book, only the measurement is missing): check `grep -i 'fill-intent' logs/cron/*.log` for the skip "
            f"warning and whether FILL_INTENT_SHADOW=0 is set in the scorer/dashboard env.")
        st["flags"]["dispatchUnrecorded"] = True

    # 6. revert switch left on
    if not a.no_process_check and not st["flags"].get("shadowOff") and dashboard_env_shadow_off():
        alerts.append(
            "⚠️ **C-200 fill-intent shadow is OFF** — `FILL_INTENT_SHADOW=0` is set in the running dashboard's "
            "environment, so no intent prices are being recorded. Unset it (and restart) to resume measurement.")
        st["flags"]["shadowOff"] = True

    if alerts:
        alerts.append(f"_watcher state: measured {measured} legs / {GATE_LEGS} to gate · "
                      f"unpaired {len(unpaired)} · unlinked {len(unlinked)}_")
        print("\n\n".join(alerts))
    for r in new_unpaired + new_bad:
        st["alertedLegs"].append(r["id"])
    for r in new_unlinked:
        st["alertedIntents"].append(r["id"])

    # The state file is written even on a silent tick (cheap, keeps flags/monotonicity honest).
    save_state(a.state, st)
    return 0


if __name__ == "__main__":
    sys.exit(main())
