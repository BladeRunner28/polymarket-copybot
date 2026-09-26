#!/usr/bin/env python3
"""
c200-intent-watch — watcher for the C-200 fill-intent instrument AND the L2 coverage fix.

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
  5. dispatch_unrecorded  scorer runs logging 'Dispatching Execution Intent' after the newest intent row
                     wrote nothing.
  6. shadow_off      FILL_INTENT_SHADOW=0 visible in the running dashboard's environment.
  7. l2_coverage     (v62 gate) for every fill intent dispatched AFTER the A2/B' fix, the market's L2
                     book file must start within 90s of the dispatch and its quote-event file must
                     exist — i.e. the recorder really did pick the market up at dispatch time, which is
                     the whole reason the 5-minute print-through horizon can be measured. Before the
                     fix the lag was 2.7-8.6 min, so this check would have failed on every leg.

Each alert fires once per distinct object (state file, default data/c200-intent-watch-state.json);
repeat ticks stay silent. Exit code is always 0 unless the watcher itself cannot read its inputs.

D (tape ingest) runs from here too: when the measured-leg count changes, the artifact is refreshed from
the public trade tape (`c200-printthrough.py --json`), so each leg's prints are recorded while the
endpoint still has them.

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
PRINTTHROUGH = os.path.join(ROOT, "scripts", "c200-printthrough.py")

# The instrument went live with the 23:33:14 CDT rebuild on 2026-09-25; legs booked before that
# legitimately carry no intent price (no backfill by design).
FLOOR_MS = 1790397194000
# v62 (A2 + B'): the recorder pins a dispatched market, so coverage must start within seconds of the
# dispatch from here on. This is the moment the v62 build actually started running
# ("[l2] recorder starting 2026-09-26T08:29:46Z" = 03:29:46 CDT), not the moment it was intended to
# start: the first-value here read 1790413140000 (03:59 CDT, 30 min in the FUTURE) behind a comment
# claiming 03:19, which would have exempted every dispatch for the next half hour from the gate.
# Intents before this floor are exempt (and provably lagged 2.7-8.6 min — see the
# l2-subscribe-at-dispatch brief). No intent was dispatched while the recorder was down, so nothing
# measured is being exempted by this floor.
L2_FIX_MS = 1790411386000        # 2026-09-26 03:29:46 CDT, the real v62 go-live
L2_LAG_BUDGET_MS = 90_000
RECORDER_STALE_S = 180           # heartbeat is every 15s; 3 missed beats = stalled sockets/hung process
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
        s.setdefault("verifiedIntents", {})
        s.setdefault("flags", {})
        return s
    except Exception:
        return {"alertedLegs": [], "alertedIntents": [], "verifiedIntents": {}, "flags": {}}


def save_state(path: str, s: dict) -> None:
    s["alertedLegs"] = s["alertedLegs"][-500:]
    s["alertedIntents"] = s["alertedIntents"][-500:]
    # A verified intent is never re-scanned (the book files are large and append-only), so this is the
    # only thing keeping the per-tick cost bounded; drop the oldest beyond the cap.
    if len(s.get("verifiedIntents", {})) > 500:
        keep = list(s["verifiedIntents"].items())[-500:]
        s["verifiedIntents"] = dict(keep)
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


def _hhmmss(ms: int) -> str:
    return time.strftime("%H:%M:%S", time.localtime(ms / 1000))


def _tail_max_ts(path: str, chunk: int = 64 * 1024) -> int | None:
    """Newest ts in the last `chunk` bytes (a few hundred lines: hours on a quiet market)."""
    last = None
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > chunk:
                fh.seek(size - chunk)
            for raw in fh.read().decode("utf-8", "ignore").splitlines():
                try:
                    ts = json.loads(raw).get("ts")
                except Exception:
                    continue
                if ts:
                    last = ts
    except Exception:
        return None
    return last


def book_window(path: str, lo: int, hi: int, cap_bytes: int = 512 * 1024 * 1024) -> dict:
    """Find recorder output inside [lo, hi] in an append-only book file.

    ts is monotonic in these files, so the scan stops at the first line past `hi`. Two shapes keep this
    cheap on a 9.6 GB corpus (4650 files):
      * a market whose coverage ENDED before `lo` (the common stale case) is answered from the tail
        alone — no full read;
      * a live market is read from the start, which measured 0.09 s for a 12.8 MB file (140 MB/s), and
        the verdict is cached per intent so each one is paid for once.
    Returns hit/before (last ts < lo)/after (first ts > hi)/truncated. `before` and `after` together
    mean a real GAP covering the window.
    """
    r: dict = {"hit": None, "before": None, "after": None, "first": None, "read": 0, "truncated": False}
    tail = _tail_max_ts(path)
    if tail is not None and tail < lo:
        r["before"] = tail                       # coverage ends before the window: no full scan needed
        return r
    try:
        with open(path, "rb") as fh:
            for raw in fh:
                r["read"] += len(raw)
                if r["read"] > cap_bytes:
                    r["truncated"] = True
                    break
                try:
                    ts = json.loads(raw).get("ts")
                except Exception:
                    continue
                if ts is None:
                    continue
                if r["first"] is None:
                    r["first"] = ts
                if ts < lo:
                    r["before"] = ts
                elif ts <= hi:
                    r["hit"] = ts
                    break
                else:
                    r["after"] = ts
                    break
    except Exception as e:
        r["error"] = str(e)
    return r


def l2_coverage_gate(intents: list[dict], st: dict) -> list[dict]:
    """For each post-v62 intent: was the recorder writing this market's book at dispatch time?

    The verdict is "a data/l2/<asset>.jsonl line inside [dispatch - 30s, dispatch + 90s]", because the
    recorder snapshots every subscribed asset every 5s — so a pin shows up as snapshots within seconds.
    Deliberately NOT "the file's first line": these files are append-only and long-lived, so a market
    last covered days ago starts long before today's dispatch, and a first-line test would pass for a
    market the recorder dropped hours ago (that was the first version of this check). The pinned-only
    quote-event tape (data/l2-events) is reported as context but is never the verdict — a quiet market
    can legitimately produce no price_change event for minutes after a pin that worked.
    """
    asset_map: dict[str, list[str]] = {}
    p = os.path.join(ROOT, "data", "l2-asset-map.jsonl")
    if os.path.exists(p):
        for line in open(p):
            try:
                o = json.loads(line)
                asset_map[o["marketId"]] = o["assetIds"]
            except Exception:
                pass
    out = []
    verified = st.setdefault("verifiedIntents", {})
    for it in intents:
        t0 = it["dispatchedAt"]
        if t0 < L2_FIX_MS or verified.get(it["id"]) == "ok" or it["id"] in st["alertedIntents"]:
            continue      # pre-fix lag is known; verified = scanned once; alerted = already reported
        lo, hi = t0 - 30_000, t0 + L2_LAG_BUDGET_MS
        assets = asset_map.get(it["marketId"], [])
        if not assets:
            out.append({**it, "asset": None,
                        "why": "the market has no asset-map entry — its CLOB token ids were never "
                               "resolved (gamma 429/timeout), so no pin was possible"})
            continue
        res = {a: book_window(os.path.join(ROOT, "data", "l2", f"{a}.jsonl"), lo, hi) for a in assets}
        hit = next((a for a, r in res.items() if r["hit"] is not None), None)
        if hit:
            verified[it["id"]] = "ok"
            continue
        # no coverage: pick the asset that came closest, for a truthful diagnostic
        def rank(kv):
            r = kv[1]
            return (0, r["after"] - t0) if r.get("after") is not None else (1, -(r.get("before") or 0))
        a, r = sorted(res.items(), key=rank)[0]
        events = 0
        ev = os.path.join(ROOT, "data", "l2-events", f"{a}.jsonl")
        if os.path.exists(ev):
            try:
                events = sum(1 for _ in open(ev))
            except Exception:
                pass
        if r.get("error"):
            why = f"cannot read the book file {a}.jsonl: {r['error']}"
        elif r.get("after") is not None and r.get("before") is not None:
            why = (f"book gap {_hhmmss(r['before'])}→{_hhmmss(r['after'])} spans the {_hhmmss(t0)} dispatch: "
                   f"the recorder had this market unsubscribed exactly when the copy was dispatched")
        elif r.get("after") is not None:
            why = (f"first recorder data for this market is {_hhmmss(r['after'])}, "
                   f"{(r['after'] - t0) / 1000:.0f}s AFTER the {_hhmmss(t0)} dispatch")
        elif r.get("before") is not None:
            why = (f"this market's book ends {_hhmmss(r['before'])}, {(t0 - r['before']) / 60000:.1f} min "
                   f"before the dispatch — the recorder was offline or the market was unsubscribed then")
        elif r.get("truncated"):
            why = "UNDETERMINED: the book file is larger than the scan cap"
        else:
            why = "the book file exists but holds no parsable line"
        out.append({**it, "asset": a, "why": why, "events": events})
    return out


def recorder_alive() -> tuple[bool, str]:
    """Is the L2 recorder running, and is its heartbeat current?

    Both halves matter. The process existing says nothing about whether its sockets are still
    delivering, and the heartbeat (every 15s) is only written by a live process. This check exists
    because the failure that actually happened was silent: the recorder was started by hand from a
    shell on 2026-09-24, died at ~03:19 on 2026-09-26, and the only thing that noticed was a human
    reading the log — L2 coverage simply stopped with no alarm anywhere.
    """
    try:
        pids = subprocess.run(["pgrep", "-f", "scripts/record-l2.ts"],
                              capture_output=True, text=True, timeout=15).stdout.split()
    except Exception as e:
        return True, f"cannot check ({e})"
    if not pids:
        return False, "no `tsx scripts/record-l2.ts` process is running"
    log = os.path.join(ROOT, "logs", "record-l2.log")
    try:
        age = time.time() - os.path.getmtime(log)
        if age > RECORDER_STALE_S:
            return False, (f"the process is alive but its heartbeat log has not been written for "
                           f"{int(age)}s ({RECORDER_STALE_S}s = 3 missed beats) — sockets stalled or hung")
    except Exception:
        pass
    return True, ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB)
    ap.add_argument("--state", default=STATE)
    ap.add_argument("--scorer-log", default=os.path.join(ROOT, "logs", "cron", "copybot-monitor-score.log"))
    ap.add_argument("--no-process-check", action="store_true")
    ap.add_argument("--no-ingest", action="store_true", help="skip the D tape ingest")
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

    # 7. v62 coverage gate: did the recorder actually cover the dispatch window?
    post_fix = [dict(r) for r in db(a.db).execute(
        "SELECT id, marketId, outcome, intentPrice, dispatchedAt FROM FillIntent WHERE dispatchedAt >= ? "
        "ORDER BY dispatchedAt", (L2_FIX_MS,))]
    offenders = l2_coverage_gate(post_fix, st)
    if offenders:
        worst = "; ".join(f"{o['marketId']} {o['outcome']} — {o['why']}" for o in offenders[:3])
        alerts.append(
            f"🚨 **L2 coverage gate FAILED for {len(offenders)} post-v62 dispatch(es)** — {worst}. The dispatch-time "
            f"pin did not deliver a book around t0, so those legs' 5-minute windows are unmeasurable again (a copy's "
            f"5-min window is the whole point of the fix: `l2-subscribe-at-dispatch`). Check the recorder log for "
            f"`pinned <market>` lines and `heartbeat … pinned=N pins=N lastPoll=Ns ago` — lastPoll near 0 means the "
            f"poll loop is alive, so the fault is gamma token resolution or the socket.")

    # 8. recorder alive + heartbeat fresh (the failure that actually happened, silently)
    if not a.no_process_check and not a.now_ms:
        up, why = recorder_alive()
        if up:
            st["flags"].pop("recorderDown", None)
        elif not st["flags"].get("recorderDown"):
            alerts.append(
                f"🚨 **L2 recorder is DOWN or stalled** — {why}. Book snapshots and the pinned-market quote tape "
                f"are NOT being written, so every C-200 window from now on is unmeasurable. Restart it "
                f"(`cd ~/polymarket-copybot && DATABASE_URL=file:./dev.db node node_modules/tsx/dist/cli.mjs "
                f"scripts/record-l2.ts >> logs/record-l2.log 2>&1 &`) or, better, load the LaunchAgent written "
                f"for exactly this: `launchctl bootstrap gui/$(id -u) "
                f"~/Library/LaunchAgents/com.xsnyde2.copybot-l2-recorder.plist` (KeepAlive — it was started by "
                f"hand until now, which is why it could die unnoticed).")
            st["flags"]["recorderDown"] = True

    # D: fold the public trade tape into the artifact for freshly closed windows (recorded while the
    # endpoint still has the prints). NOTE the flag: this used to call `--ingest-closed`, which does not
    # exist in c200-printthrough.py — the call exited 2 with that usage error and the failure was
    # swallowed (captured output, no return-code check), so D had never ingested anything. The real
    # entry point is `--json` (append the artifact, quiet stdout), and a non-zero exit now raises.
    if not a.no_ingest and not a.now_ms and st.get("lastMeasured") != measured:
        try:
            p = subprocess.run(["python3", PRINTTHROUGH, "--json"],
                               capture_output=True, text=True, timeout=150, cwd=ROOT)
            if p.returncode != 0:
                alerts.append(f"⚠️ tape ingest (D) FAILED (exit {p.returncode}) — "
                              f"{(p.stderr or p.stdout or '').strip()[-300:]}")
            else:
                st["lastMeasured"] = measured
        except Exception as e:
            alerts.append(f"⚠️ tape ingest (D) failed: {e}")

    if alerts:
        alerts.append(f"_watcher state: measured {measured} legs / {GATE_LEGS} to gate · "
                      f"unpaired {len(unpaired)} · unlinked {len(unlinked)}_")
        print("\n\n".join(alerts))
    for r in new_unpaired + new_bad:
        st["alertedLegs"].append(r["id"])
    for r in new_unlinked:
        st["alertedIntents"].append(r["id"])
    # Coverage offenders are appended too — the dedupe filter in the gate reads this list, and without
    # this line a failed coverage window would re-alert on every tick (verified-OK intents are kept
    # separately in verifiedIntents, so they are never re-scanned).
    for o in offenders:
        st["alertedIntents"].append(o["id"])

    # The state file is written even on a silent tick (cheap, keeps flags/monotonicity honest).
    save_state(a.state, st)
    return 0


if __name__ == "__main__":
    sys.exit(main())
