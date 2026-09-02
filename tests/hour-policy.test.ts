/**
 * v41 C-200 entry-hour policy tests (2026-08-31 report, approved).
 * Hours are America/New_York (ET), DST-aware — matches the calibration
 * analysis (analyze-calibration.py used ZoneInfo("America/New_York")).
 */

import { describe, it, expect } from "vitest";
import {
  c200HourPolicy,
  etHourNow,
  C200_BLACKOUT_HOURS_ET,
} from "../src/lib/hour-policy";

describe("v41 C-200 hour policy", () => {
  it("blackouts exactly 20:00 and 23:00 ET", () => {
    expect([...C200_BLACKOUT_HOURS_ET].sort()).toEqual([20, 23]);
    for (let h = 0; h < 24; h++) {
      const blacked = h === 20 || h === 23;
      expect(c200HourPolicy(h).blackout).toBe(blacked);
    }
  });

  it("applies the 50% haircut at 10:00 ET only", () => {
    for (let h = 0; h < 24; h++) {
      expect(c200HourPolicy(h).sizeFactor).toBe(h === 10 ? 0.5 : 1);
    }
  });

  it("keeps 21:00 ET open (significant positive edge, z=+2.80)", () => {
    expect(c200HourPolicy(21).blackout).toBe(false);
    expect(c200HourPolicy(21).sizeFactor).toBe(1);
  });

  it("converts instants to ET with DST (Aug = EDT, Jan = EST, Mar switch)", () => {
    // 2026-08-31T00:00Z = 2026-08-30 20:00 EDT
    expect(etHourNow(new Date("2026-08-31T00:00:00Z"))).toBe(20);
    // 2026-01-15T12:00Z = 07:00 EST
    expect(etHourNow(new Date("2026-01-15T12:00:00Z"))).toBe(7);
    // 2026-03-08 06:59Z = 01:59 EST (DST starts 07:00Z)
    expect(etHourNow(new Date("2026-03-08T06:59:00Z"))).toBe(1);
    // 2026-03-08 07:00Z = 03:00 EDT — the switch itself
    expect(etHourNow(new Date("2026-03-08T07:00:00Z"))).toBe(3);
  });
});
