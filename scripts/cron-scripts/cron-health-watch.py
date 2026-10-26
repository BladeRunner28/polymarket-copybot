#!/usr/bin/env python3
"""Hermes cron health watcher — alert when a scheduled job is failing or has gone quiet.

WHY THIS EXISTS: on 2026-10-13 a load-time crash in the copybot repo (TDZ
ReferenceError in src/lib/fill-intent.ts) killed three cron jobs for 16h — 109
failed runs, 0 notifications — because all three are `deliver: local` and nothing
in the system ever read the `failure_streak` that jobs.json records for every job.
The outage was finally caught by the 07:00 tuning review, 12h late. This watcher
reads that counter every 15 minutes instead.

Silent when everything is healthy (empty stdout = nothing is delivered), which is
the Hermes watchdog convention: it only makes noise when something is wrong.

Alerts on:
  * a job reaching MIN_STREAK consecutive failures (new incident)
  * a job already alerted growing by ALERT_EVERY more failures (still down)
  * a 6-hourly reminder while a job stays down (don't let a long outage go quiet)
  * a RECOVERY line once a job returns to ok (closes the thread)

Also flags jobs that are enabled but QUIET: interval-scheduled jobs whose last run
is older than 3x their interval + grace. Scope note: quiet-detection covers
interval schedules only (the copybot core: monitor 10m, update-pnl 60m, watchdogs
5/15m); cron-expression and one-shot schedules are judged on failure_streak alone,
because guessing a cron's expected gap produces false alarms.

READ-ONLY on jobs.json — this script never writes it. Its own state lives beside
it (~/.hermes/cron/cron-health-watch-state.json), outside every repo, so the
daily git backup never sees it and a lost state file costs at most one repeat
alert.

Usage:  python3 cron-health-watch.py [--verbose]
Exit:   0 always (a watchdog that fails when it cannot read its input has no way
        to tell you about it).
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

CRON_DIR = Path.home() / ".hermes" / "cron"
# CRON_HEALTH_JOBS / CRON_HEALTH_STATE let a test point this at a fixture instead
# of the live scheduler state (the only reason they exist — production uses the
# defaults, and an unset override can never change behavior).
JOBS_FILE = Path(os.environ.get("CRON_HEALTH_JOBS") or (CRON_DIR / "jobs.json"))
STATE_FILE = Path(os.environ.get("CRON_HEALTH_STATE") or (CRON_DIR / "cron-health-watch-state.json"))

MIN_STREAK = 3          # failures before a job is an incident
ALERT_EVERY = 10        # re-alert when an already-alerted job grows by this many
REMIND_HOURS = 6        # reminder cadence while a job stays down
QUIET_FACTOR = 3        # interval job is quiet if now - last_run > factor * interval
QUIET_GRACE_MIN = 20    # plus this much slack (dispatch lateness measured ~45-60s)
ERR_SNIPPET = 220       # chars of the last error kept in the alert


def load_json(path: Path, default):
    try:
        with path.open() as fh:
            return json.load(fh)
    except Exception:
        return default


def parse_ts(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / (1000 if value > 1e11 else 1), timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def fmt(ts: datetime | None, tzname: str = "CDT") -> str:
    if ts is None:
        return "never"
    return ts.astimezone().strftime("%Y-%m-%d %H:%M") + f" {tzname}"


STRONG = ("referenceerror", "typeerror", "syntaxerror", "rangeerror", "error:", "cannot access",
          "cannot find", "enoent", "econnrefused", "traceback", "exception", "timed out", "timeout",
          "assertion", "not found")
WEAK = ("failed", "refused", "denied", "elided")
BOILER = ("script exited with code", "stdout:", "stderr:", "=== run")
NOISE = ("node.js v", "at ", "at object.", "^", "code:", "elided")
SKIP_HDR = ("#", "##", "**job id", "**run time", "**mode", "**status", "---")


def error_lines(text: str | None, *, allow_headers: bool = False) -> list[str]:
    out = []
    for ln in str(text or "").splitlines():
        ln = ln.strip()
        if not ln or any(ln.lower().startswith(b) for b in BOILER):
            continue
        if any(ln.lower().startswith(n) for n in NOISE):
            continue
        if not allow_headers and any(ln.lower().startswith(h) for h in SKIP_HDR):
            continue
        out.append(ln)
    return out


def first_error_line(err: str | None, job: dict | None = None) -> str:
    """The most informative single line of a job's failure.

    Hermes stores only a TRUNCATED `last_error` in jobs.json (measured: a Node stack
    trace cut to its frames, the `ReferenceError` line gone), and the on-disk run
    capture in ~/.hermes/cron/output/<job_id>/*.md is tail-truncated the same way —
    a job whose script pipes through `tail -6` can lose the error line from BOTH.
    So: prefer a line that names a concrete error, accept a vaguer failure word next,
    and otherwise say plainly that the text was not captured rather than printing a
    stack frame as if it were the diagnosis.
    """
    sources = [err, newest_output(job) if job else None]
    for wanted in (STRONG, WEAK):
        for source in sources:
            for ln in error_lines(source):
                if any(k in ln.lower() for k in wanted):
                    return ln[:ERR_SNIPPET]
    lines = error_lines(err)
    if lines:
        return lines[0][:ERR_SNIPPET]
    return "(error text not captured — the run capture is tail-truncated; read the job's own log)"


def newest_output(job: dict) -> str | None:
    """Full text of a job's most recent run output, if it is on disk.

    jobs.json truncates last_error; ~/.hermes/cron/output/<job_id>/*.md has the
    whole run. Only ever called for a job that is already failing, so the read cost
    is bounded to the number of unhealthy jobs.
    """
    jid = job.get("id")
    if not jid:
        return None
    outdir = CRON_DIR / "output" / jid
    try:
        files = sorted((p for p in outdir.glob("*.md")), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            return None
        with files[0].open(errors="replace") as fh:
            return fh.read()
    except Exception:
        return None


def expected_interval_minutes(job: dict) -> int | None:
    """Only interval schedules — see the module docstring for why."""
    sched = job.get("schedule") or {}
    if sched.get("kind") == "interval" and sched.get("minutes"):
        try:
            return int(sched["minutes"])
        except Exception:
            return None
    return None


def main() -> int:
    jobs_doc = load_json(JOBS_FILE, {})
    jobs = jobs_doc.get("jobs", []) if isinstance(jobs_doc, dict) else jobs_doc
    if isinstance(jobs, dict):
        jobs = list(jobs.values())
    if not jobs:
        # Unreadable/empty jobs.json is itself worth one line, but do not spam on
        # a transient read failure: report it and exit.
        print(f"⚠️ **cron-health-watch cannot read {JOBS_FILE}** — jobs.json is empty or unreadable at "
              f"{fmt(datetime.now(timezone.utc))}. No job status could be checked.")
        return 0

    now = datetime.now(timezone.utc)
    state = load_json(STATE_FILE, {})
    if not isinstance(state, dict):
        state = {}

    new_lines: list[str] = []
    recovered: list[str] = []
    still_down: list[str] = []
    quiet: list[str] = []

    for job in jobs:
        if not job.get("enabled"):
            state.pop(job.get("id", ""), None)
            continue
        jid = job.get("id") or job.get("name") or "?"
        name = job.get("name") or jid
        streak = int(job.get("failure_streak") or 0)
        status = str(job.get("last_status") or "")
        rec = state.get(jid) or {}

        if streak >= MIN_STREAK or (status == "error" and streak >= MIN_STREAK):
            since = rec.get("down_since") or job.get("last_run_at")
            last_alert = parse_ts(rec.get("alerted_at"))
            alerted_streak = int(rec.get("alerted_streak") or 0)
            due = (
                rec.get("alerted_streak") is None
                or streak >= alerted_streak + ALERT_EVERY
                or (last_alert is not None and now - last_alert >= timedelta(hours=REMIND_HOURS))
            )
            if due:
                head = f"🔴 `{name}` — {streak} consecutive failures"
                detail = f"   ↳ {first_error_line(job.get('last_error'), job)}"
                when = f"   ↳ last run {fmt(parse_ts(job.get('last_run_at')))} · down since {fmt(parse_ts(since))}" if since else ""
                rerun = f"   ↳ re-run: `bash ~/.hermes/scripts/{job['script']}`" if job.get("script") else ""
                new_lines.append(head)
                new_lines.append(detail)
                if rerun:
                    new_lines.append(rerun)
                if when:
                    new_lines.append(when)
            else:
                still_down.append(f"`{name}` ({streak})")
            state[jid] = {
                "alerted_at": now.isoformat(),
                "alerted_streak": streak if due else (alerted_streak or streak),
                "down_since": rec.get("down_since") or since,
            }
            continue

        # healthy path — is this a recovery we already alerted on?
        if rec.get("alerted_at"):
            down_since = parse_ts(rec.get("down_since"))
            dur = ""
            if down_since:
                mins = int((now - down_since).total_seconds() // 60)
                dur = f" after {mins // 60}h {mins % 60}m down" if mins >= 60 else f" after {mins}m down"
            recovered.append(f"✅ `{name}` recovered{dur} — back to ok ({int(rec.get('alerted_streak') or 0)} failures)")
        state.pop(jid, None)

        # quiet check (interval jobs only) — deduped like the failure alerts, or it
        # would repeat the same line every 15 minutes for as long as the job is quiet
        iv = expected_interval_minutes(job)
        last = parse_ts(job.get("last_run_at"))
        qkey = f"quiet:{jid}"
        is_quiet = (
            iv is not None
            and last is not None
            and job.get("state") not in ("paused", "completed")
            and now - last > timedelta(minutes=iv * QUIET_FACTOR + QUIET_GRACE_MIN)
        )
        if is_quiet:
            qrec = state.get(qkey) or {}
            qlast = parse_ts(qrec.get("alerted_at"))
            if qlast is None or (now - qlast) >= timedelta(hours=REMIND_HOURS):
                quiet.append(
                    f"🟡 `{name}` is QUIET — last run {fmt(last)} but it is scheduled every {iv}m "
                    f"(expected within ~{iv * QUIET_FACTOR + QUIET_GRACE_MIN}m). No failure recorded, so nothing crashed: "
                    f"check the scheduler/gateway is alive."
                )
                state[qkey] = {"alerted_at": now.isoformat()}
        else:
            state.pop(qkey, None)

    # persist state before printing, so a delivery failure cannot cause an alert loop
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=1, sort_keys=True))
        tmp.replace(STATE_FILE)
    except Exception as exc:  # never let state IO kill the alert
        print(f"⚠️ cron-health-watch could not persist state ({exc})", file=sys.stderr)

    out: list[str] = []
    if new_lines:
        n = sum(1 for l in new_lines if l.startswith("🔴"))
        out.append(f"🚨 **Cron health — {n} job(s) failing** ({fmt(now)})")
        out.append("")
        out.extend(new_lines)
        out.append("")
        out.append("Fix path: read the job's last output in `~/.hermes/cron/output/<job_id>/`, then re-run its script "
                   "directly (`bash ~/.hermes/scripts/<job>.sh`). This watcher alerts at "
                   f"{MIN_STREAK} consecutive failures and reminds every {REMIND_HOURS}h while a job stays down.")
    if recovered:
        out.extend(recovered)
    if quiet:
        out.extend(quiet)
    if still_down and new_lines:
        out.append("")
        out.append("Still down (no new alert): " + ", ".join(still_down))

    if out:
        print("\n".join(out))
    elif "--verbose" in sys.argv:
        ok = sum(1 for j in jobs if str(j.get("last_status")) == "ok")
        print(f"cron-health-watch: all quiet — {ok}/{len(jobs)} jobs ok, no streak >= {MIN_STREAK}, no quiet jobs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
