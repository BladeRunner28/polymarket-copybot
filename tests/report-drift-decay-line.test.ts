/**
 * Drift/decay line rendering (2026-11-17 self-audit).
 *
 * The defect: `consecutiveDaysAtOrBelow ?? 0` and `tripped ? … : "not tripped"`
 * rendered a MISSING measurement as a PASSING one — an arm that was never computed
 * printed "bar 0/7d … not tripped", byte-identical to an arm that was computed and
 * found the bar holding. On live data the two arms disagree for a legitimate reason
 * (per-poll 43 days / TRIPPED vs per-signal 0 days / not tripped — different
 * populations), so "not tripped" must never also mean "unknown".
 */

import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { describe, it, expect } from "vitest";
import { driftDecayLine, driftDecayText, type DriftSummary } from "../src/lib/report";

const complete: DriftSummary = {
  avgPnlPerTradeExDust: 0.03,
  marked: 43824,
  avgPnlPerTradeExDustPerSignal: 0.56,
  signalsSettled: 11419,
  decayBar: { thresholdUsd: 0.5, daysRequired: 7, consecutiveDaysAtOrBelow: 43, cohort7d: -1.28, tripped: true },
  decayBarPerSignal: { thresholdUsd: 0.5, daysRequired: 7, consecutiveDaysAtOrBelow: 0, cohort7d: -0.28, tripped: false },
};

describe("drift decay line", () => {
  it("renders a complete artifact exactly as the report did before the fix", () => {
    expect(driftDecayText(complete)).toBe(
      "• Drift gate counterfactual: +$0.03/trade ex-dust per poll (43824 marked)" +
        " · per-signal +$0.56/trade ex-dust (11419 settled signals, bar 0/7d, cohort7d(per-signal) −$0.28 — not tripped)" +
        " · decay bar (per-poll): 43 consecutive days at ≤$0.50 (needs 7) · cohort7d(per-poll) −$1.28 — TRIPPED"
    );
  });

  it("an arm with no streak says UNMEASURED instead of 0/7d", () => {
    const t = driftDecayText({
      ...complete,
      decayBarPerSignal: { thresholdUsd: 0.5, daysRequired: 7, cohort7d: -0.28 },
    })!;
    const psArm = t.split("settled signals")[1].split("decay bar (per-poll)")[0];
    expect(psArm).toContain("bar UNMEASURED");
    expect(psArm).not.toContain("bar 0/7d");
    // and no verdict is invented for it
    expect(psArm).toContain("verdict UNMEASURED");
    // the per-poll arm still reports its own, real verdict
    expect(t).toContain("— TRIPPED");
  });

  it("a null streak is missing data, not a zero streak", () => {
    const t = driftDecayText({
      ...complete,
      decayBar: { thresholdUsd: 0.5, daysRequired: 7, consecutiveDaysAtOrBelow: null, cohort7d: null, tripped: null },
    })!;
    const poll = t.split("decay bar (per-poll):")[1];
    expect(poll).toContain("streak UNMEASURED");
    expect(poll).not.toContain("0 consecutive days");
    expect(poll).not.toContain("not tripped");
  });

  it("a missing verdict is NOT 'not tripped'", () => {
    const t = driftDecayText({
      ...complete,
      decayBar: { thresholdUsd: 0.5, daysRequired: 7, consecutiveDaysAtOrBelow: 43, cohort7d: -1.28 },
    })!;
    const poll = t.split("decay bar (per-poll):")[1];
    expect(poll).toContain("verdict UNMEASURED");
    expect(poll).not.toContain("not tripped");
  });

  it("no base figure means no line at all (an absent line is honest)", () => {
    expect(driftDecayText({ marked: 10 })).toBeUndefined();
  });
});

/**
 * 2026-11-18 self-audit: `driftDecayText`'s undefined is correct as a PURE function, but
 * the report used it as "drop the line", so an unreadable summary removed the drift
 * counterfactual from the EOD with no trace. `driftDecayLine` now always returns text.
 */
describe("drift decay line as emitted (never absent)", () => {
  const dir = mkdtempSync(path.join(tmpdir(), "driftline-"));
  const write = (name: string, body: unknown) => {
    const f = path.join(dir, name);
    writeFileSync(f, typeof body === "string" ? body : JSON.stringify(body));
    return f;
  };
  const now = new Date("2026-11-18T12:50:00Z");

  it("a fresh, complete summary renders byte-identically to the pre-fix line", () => {
    const f = write("fresh.json", { ...complete, generatedAt: "2026-11-18T12:26:11.134Z" });
    expect(driftDecayLine(f, now)).toBe(driftDecayText(complete));
  });

  it("an unreadable summary says UNAVAILABLE instead of vanishing", () => {
    const f = write("broken.json", "{not json");
    const line = driftDecayLine(f, now);
    expect(line).toContain("UNAVAILABLE");
    expect(line).toContain("NOT a clean counterfactual");
  });

  it("a missing summary says UNAVAILABLE instead of vanishing", () => {
    const line = driftDecayLine(path.join(dir, "absent.json"), now);
    expect(line).toContain("UNAVAILABLE");
    expect(line).not.toContain("Drift gate counterfactual: −$");
  });

  it("a summary with no base figure says UNMEASURED, not nothing", () => {
    const f = write("nobase.json", { generatedAt: "2026-11-18T12:26:11.134Z", marked: 45056 });
    const line = driftDecayLine(f, now);
    expect(line).toContain("UNMEASURED");
    expect(line).toContain("45056 marked");
  });

  it("a 7-day-old summary is flagged STALE in place — a dead shadow:mark is visible", () => {
    const f = write("old.json", { ...complete, generatedAt: "2026-11-11T12:26:11.134Z" });
    const line = driftDecayLine(f, now);
    expect(line).toContain("summary STALE");
    expect(line).toContain("7.0d old");
    // the figures are still shown — the flag is additive, not a replacement
    expect(line).toContain("+$0.03/trade ex-dust per poll");
  });

  it("an undated summary cannot establish freshness and says so", () => {
    const f = write("undated.json", complete);
    expect(driftDecayLine(f, now)).toContain("summary UNDATED");
  });
});
