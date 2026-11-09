/**
 * /workers printed "NaNd NaNh" for a running worker's elapsed time on 2026-11-09, then "1h 22m" for
 * a process 49 seconds old. Three separate defects, all pinned here:
 *
 *  1. `tasks.started_at` (written by the current kanban code) is a 12-digit TEXT epoch-CENTISECOND
 *     value ("179424557890"); older rows carried 10-digit epoch seconds there, and the newest code
 *     leaves worker_started_at NULL. The panel used the raw value in arithmetic -> NaN.
 *  2. `Date.parse("179424557890")` is NaN, so a normaliser that only understood numbers and ISO
 *     strings returned null for exactly the value that was broken.
 *  3. A two-tier "milliseconds if > 1e11" rule sends a 12-digit centisecond value through /1000 and
 *     lands 100x early — a duration that looks plausible and is wrong by a factor of a hundred.
 *     The first version of this test asserted that wrong answer (179423581), so it is corrected here.
 *
 * `task_runs.started_at` is INTEGER epoch seconds and is the only trustworthy "this run began" value,
 * which is why the panel prefers it.
 */
import { describe, expect, it } from "vitest";
import { toEpoch } from "../src/lib/epoch";

describe("toEpoch — the magnitudes this fleet actually stores", () => {
  it("reads epoch CENTISECONDS (12 digits) — the current writer's format", () => {
    // Live value from tasks.started_at for a running card, 2026-11-09.
    expect(toEpoch("179424557890")).toBe(1794245578);
    expect(toEpoch(179424557890)).toBe(1794245578);
  });

  it("reads epoch MILLISECONDS (13 digits)", () => {
    expect(toEpoch("1794245578900")).toBe(1794245578);
    expect(toEpoch(1794245578900)).toBe(1794245578);
  });

  it("reads epoch SECONDS (10 digits) unchanged — the older rows and task_runs", () => {
    expect(toEpoch(1794245578)).toBe(1794245578);
    expect(toEpoch("1794245578")).toBe(1794245578);
  });

  it("reads the cron ISO 8601 form", () => {
    const iso = "2026-10-29T12:25:35.80-05:00";
    expect(toEpoch(iso)).toBe(Math.floor(Date.parse(iso) / 1000));
  });

  it("returns null for junk rather than a number that looks plausible", () => {
    expect(toEpoch(null)).toBeNull();
    expect(toEpoch(undefined)).toBeNull();
    expect(toEpoch("")).toBeNull();
    expect(toEpoch("   ")).toBeNull();
    expect(toEpoch("not a date")).toBeNull();
    // typeof NaN === "number": returning it is exactly what printed "NaNd NaNh".
    expect(toEpoch(NaN)).toBeNull();
  });

  it("a null must not be computed with — the distinction the panel needs", () => {
    const started = toEpoch(null);
    expect(started).toBeNull();
    const elapsed = started !== null ? 1794245627 - started : null;
    expect(elapsed).toBeNull();
  });

  it("49 seconds of real age must render as 49s, not 1h 22m", () => {
    // The regression: preferring the TASK's started_at (first attempt) made a fresh run look 1h22m.
    const now = 1794245627;
    const currentRunStart = toEpoch(1794245578); // task_runs.started_at
    const firstAttempt = toEpoch("1794240681"); // tasks.started_at, older row shape
    expect(now - (currentRunStart as number)).toBe(49);
    expect(now - (firstAttempt as number)).toBe(4946);
  });
});
