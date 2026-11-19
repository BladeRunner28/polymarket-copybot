import { describe, expect, it } from "vitest";
import { instrumentHeartbeatText, STAGE_POLICY, type StageHeartbeat } from "../src/lib/report";

/**
 * 2026-11-15 self-audit.
 *
 * The EOD report proved exactly one job's liveness (the wallet scan). The four stages that
 * produce the numbers it prints had no freshness line, so the 2026-11-13→14 stall — the
 * PnL stage wrote ZERO PnlSnapshot rows from 11-13 09:34 to 11-14 06:45 (21 h), with nine
 * consecutive `breaking stale lock … and continuing` hourly runs each hung to the harness
 * ceiling — rendered in the report exactly like a healthy day.
 *
 * These cases pin the states apart: fresh, stale (with the multiple of its own cadence),
 * never-written, unreadable, and a mix where the stale stage must not hide the others.
 * The thresholds themselves are tested because they are LIFTED FROM THE FLEET, not guessed:
 * monitor-score runs every 10 min (not 30, not the 2 h in HERMES.md) and `review:outcomes`
 * has no standalone job at all — it writes once a day inside the 22:00 EOD chain.
 */
const NOW = new Date("2026-11-14T06:00:00-06:00");

const stage = (key: string, lastWriteAt: Date | null, extra?: Partial<StageHeartbeat>): StageHeartbeat => ({
  key,
  label: key,
  ...STAGE_POLICY[key],
  lastWriteAt,
  ...extra,
});

const min = (n: number) => new Date(NOW.getTime() - n * 60_000);
const hr = (n: number) => new Date(NOW.getTime() - n * 3_600_000);

describe("instrument heartbeat tells a dead stage from a quiet one", () => {
  it("all stages fresh renders ages and names its population", () => {
    const line = instrumentHeartbeatText(
      [stage("monitor", min(6)), stage("score", min(6)), stage("pnl", min(48)), stage("review", hr(8.9))],
      NOW
    );
    expect(line).toBe(
      "• Instrument heartbeat (last write per stage, isDemo=0 · monitor copy-set only): monitor 6m ago · score 6m ago · pnl 48m ago · review 8.9h ago"
    );
    expect(line).not.toContain("⚠️");
  });

  it("the 2026-11-14 stall is visible: a 20 h hole on the hourly stage", () => {
    const line = instrumentHeartbeatText(
      [
        stage("monitor", min(1)),
        stage("score", min(29)),
        stage("pnl", new Date("2026-11-13T09:34:55-06:00")),
        stage("review", new Date("2026-11-12T22:01:04-06:00")),
      ],
      NOW
    );
    expect(line).toContain("⚠️ Instrument heartbeat: pnl has written nothing for 20.4h (20× its 1h cadence)");
    // review was ALSO 32 h stale here, but its stage is a daily one: under the measured
    // 48 h floor it is reported as an age, not a warning. The 20 h pnl hole is the finding.
    expect(line).not.toContain("review has written nothing");
    expect(line).toContain("other stages: monitor 1m ago · score 29m ago · review 32.0h ago");
  });

  it("a normal afternoon does NOT flag review — it is silent by design between 22:00 runs", () => {
    // The 6 h cadence HERMES.md documents would have cried wolf every day around 16:00.
    const line = instrumentHeartbeatText([stage("review", hr(18))], NOW);
    expect(line).not.toContain("⚠️");
    expect(line).toContain("review 18.0h ago");
    // One whole missed daily run still has to be caught.
    expect(instrumentHeartbeatText([stage("review", hr(49))], NOW)).toContain("⚠️");
  });

  it("thresholds are edges, not vibes: one tick over the wrapper's own 45-min lock ceiling trips", () => {
    expect(instrumentHeartbeatText([stage("monitor", min(44))], NOW)).not.toContain("⚠️");
    expect(instrumentHeartbeatText([stage("monitor", min(46))], NOW)).toContain("⚠️");
    expect(instrumentHeartbeatText([stage("pnl", min(129))], NOW)).not.toContain("⚠️");
    expect(instrumentHeartbeatText([stage("pnl", min(131))], NOW)).toContain("⚠️");
  });

  it("a duration-bound monitor run (~17 min effective) is not stale at 45 min", () => {
    // Runs are longer than the 10-min schedule; the lock makes the wrapper skip, not write.
    expect(instrumentHeartbeatText([stage("score", min(40))], NOW)).not.toContain("⚠️");
  });

  it("an unreadable table is UNREADABLE, never a fresh-looking age", () => {
    const line = instrumentHeartbeatText([stage("score", null, { unreadable: true }), stage("pnl", min(10))], NOW);
    expect(line).toContain("score UNREADABLE");
    expect(line).not.toContain("score 0m ago");
    expect(line).not.toContain("⚠️"); // unknown, not proven stale — but never silently clean either
  });

  it("a table with no rows ever says NEVER instead of inventing an age", () => {
    const line = instrumentHeartbeatText([stage("review", null)], NOW);
    expect(line).toContain("review NEVER");
    expect(line).not.toContain("0m ago");
  });

  it("no stages means no line at all", () => {
    expect(instrumentHeartbeatText([], NOW)).toBeUndefined();
  });
});
