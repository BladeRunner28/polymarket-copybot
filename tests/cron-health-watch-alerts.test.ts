/**
 * 2026-11-01 (self-audit) — three defects in this watcher's own alerting, all measured on
 * fixtures against the pre-fix script:
 *
 * 1. REMINDER CLOCK. "reminds every 6h while a job stays down" (module docstring AND the
 *    footer of every alert) was unreachable for any job that ticks more often than 6h.
 *    `alerted_at` was rewritten to now() on every pass, including passes that emitted
 *    nothing, so a 10-minute job with a live outage re-read its own alert age as ~10
 *    minutes forever. Measured: a job 5h50m past its alert took a silent tick, its
 *    alerted_at jumped 350 minutes forward, and the next tick (20 minutes of wall time
 *    later) still said nothing. Over two ticks: 0 reminders -> 1.
 *    The only re-alert left was ALERT_EVERY (10) more failures: 100 minutes for the 10m
 *    monitor, but 10 hours for the hourly PnL job and 10 DAYS for the daily EOD report.
 *
 * 2. PAST DUE. There was no sensor at all for "the scheduler never dispatched this job".
 *    Such a job writes no error, keeps last_status=ok, failure_streak=0, and the interval
 *    quiet test needs last_run_at — so a job that NEVER ran could not even be quiet.
 *    Measured: enabled job, next_run_at 3h in the past -> "all quiet — 1/1 jobs ok";
 *    last_run_at=null with next_run_at 5h in the past -> the same line.
 *
 * 3. The alert's re-run hint hardcoded `bash`, so for the one job whose script is a .py
 *    (this watcher) it printed a command that exits 2 with a shell syntax error.
 */

import { describe, it, expect } from "vitest";
import { execFileSync } from "child_process";
import fs from "fs";
import os from "os";
import path from "path";

const SCRIPT = path.join(__dirname, "..", "scripts", "cron-scripts", "cron-health-watch.py");
const now = Date.now();
const iso = (msAgo: number) => new Date(now - msAgo).toISOString();
const MIN = 60_000;

type Job = Record<string, unknown>;

function failingJob(over: Job = {}): Job {
  return {
    id: "job-a",
    name: "copybot-monitor-score",
    script: "copybot-monitor-score.sh",
    schedule: { kind: "interval", minutes: 10, display: "every 10m" },
    enabled: true,
    state: "scheduled",
    failure_streak: 5,
    last_status: "error",
    last_error: "boom",
    last_run_at: iso(5 * MIN),
    next_run_at: iso(-5 * MIN),
    deliver: "local",
    failure_deliver: "discord",
    ...over,
  };
}

/** Run the watcher on a fixture; returns stdout and the state file it left behind. */
function run(jobs: Job[], state: Record<string, unknown>): { out: string; state: Record<string, any> } {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "chw-"));
  const jf = path.join(dir, "jobs.json");
  const sf = path.join(dir, "state.json");
  fs.writeFileSync(jf, JSON.stringify({ jobs }));
  fs.writeFileSync(sf, JSON.stringify(state));
  const out = execFileSync("python3", [SCRIPT, "--verbose"], {
    encoding: "utf8",
    env: { ...process.env, CRON_HEALTH_JOBS: jf, CRON_HEALTH_STATE: sf },
  });
  return { out, state: JSON.parse(fs.readFileSync(sf, "utf8")) };
}

describe("cron-health-watch: the 6h 'still down' reminder must survive silent ticks", () => {
  it("does not move alerted_at forward on a tick that sends nothing", () => {
    const alertedAt = iso(350 * MIN); // 5h50m ago, inside the reminder window
    const { out, state } = run([failingJob()], {
      "job-a": { alerted_at: alertedAt, alerted_streak: 5, down_since: iso(7 * 60 * MIN) },
    });
    expect(out).not.toContain("consecutive failures");
    expect(state["job-a"].alerted_at).toBe(alertedAt);
  });

  it("fires the reminder on the tick where the alert age passes 6h", () => {
    // State carried forward from a silent tick at 5h50m, 20 minutes of wall time later.
    const { out } = run([failingJob()], {
      "job-a": { alerted_at: iso(370 * MIN), alerted_streak: 5, down_since: iso(7 * 60 * MIN) },
    });
    expect(out).toContain("consecutive failures");
    expect(out).toContain("copybot-monitor-score");
  });
});

describe("cron-health-watch: a job nobody dispatches must not read as healthy", () => {
  const cronJob = {
    id: "job-b",
    name: "copybot-eod",
    script: "copybot-eod.sh",
    schedule: { kind: "cron", expr: "0 22 * * *", display: "0 22 * * *" },
    enabled: true,
    state: "scheduled",
    failure_streak: 0,
    last_status: "ok",
    last_error: null,
    last_run_at: iso(27 * 60 * MIN),
    next_run_at: iso(180 * MIN),
    deliver: "discord",
    failure_deliver: null,
  };

  it("alerts when next_run_at is hours in the past with no failure recorded", () => {
    const { out } = run([cronJob as Job], {});
    expect(out).toContain("PAST DUE");
    expect(out).toContain("copybot-eod");
    expect(out).toContain("+180m");
  });

  it("alerts for a job that has NEVER run (last_run_at null, next_run_at past)", () => {
    const { out } = run([{ ...cronJob, last_run_at: null, next_run_at: iso(300 * MIN) } as Job], {});
    expect(out).toContain("PAST DUE");
    expect(out).toContain("+300m");
  });

  it("stays silent for ordinary scheduler jitter (live ledger shows 0.8m late)", () => {
    const { out } = run([{ ...cronJob, next_run_at: iso(0.8 * MIN) } as Job], {});
    expect(out).not.toContain("PAST DUE");
  });
});

describe("cron-health-watch: the operator instructions must be runnable", () => {
  it("prints python3, not bash, for a .py script", () => {
    const { out } = run([failingJob({ script: "cron-health-watch.py" })], {});
    expect(out).toContain("python3 ~/.hermes/scripts/cron-health-watch.py");
    expect(out).not.toContain("bash ~/.hermes/scripts/cron-health-watch.py");
  });

  it("still prints bash for a .sh script", () => {
    const { out } = run([failingJob()], {});
    expect(out).toContain("bash ~/.hermes/scripts/copybot-monitor-score.sh");
  });
});

describe("cron-health-watch: the verbose line must not assert an absence it has not checked", () => {
  it("names a job that is already at the alert threshold", () => {
    const { out } = run([failingJob()], {
      "job-a": { alerted_at: iso(2 * MIN), alerted_streak: 5, down_since: iso(60 * MIN) },
    });
    // 2026-11-12: the script's wording moved when the bar became PER JOB (ddefd62 —
    // a once-a-week job trips at ONE failure, so "3 failures" was itself the fixed-string
    // lie this arm exists to catch). The test kept asserting the retired string and had
    // been red at HEAD since; it now keys on the current sentence AND still requires the
    // job NAME, which is the part that actually prevents a suppressed job from vanishing.
    expect(out).not.toContain("no job at or over its failure bar");
    expect(out).toContain("1 job(s) at/over its failure bar inside the");
    expect(out).toContain("copybot-monitor-score");
  });
});
