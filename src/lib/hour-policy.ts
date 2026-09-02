/**
 * v41 entry-hour policy (2026-08-31 report, user-approved).
 *
 * Calibration analysis of N=1,076 C-200 trades (scripts/analyze-calibration.py,
 * ET hours via ZoneInfo("America/New_York")) found significant hourly
 * effects on C-200 PnL:
 *   20:00 ET  excess -0.27 (z=-3.31), -$91  -> blackout new C-200 entries
 *   23:00 ET  excess -0.25 (z=-2.90), -$98  -> blackout new C-200 entries
 *   10:00 ET  -$178 (worst dollar hour, z=-1.74) -> 50% size haircut
 *   21:00 ET  excess +0.25 (z=+2.80)        -> stays open (no blanket ban)
 * Scoped to BANKROLL_200 (the compounding C-200 book); the STANDARD
 * long-dated book is unaffected. DST-aware via America/New_York.
 */

const ET_FORMATTER = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  hour: "numeric",
  hourCycle: "h23", // 0-23 (hour12:false alone can yield "24" at midnight)
});

export const C200_BLACKOUT_HOURS_ET: ReadonlySet<number> = new Set([20, 23]);
export const C200_HAIRCUT_HOUR_ET = 10;
export const C200_HAIRCUT_FACTOR = 0.5;

/** Current hour in America/New_York (0-23), DST-aware. */
export function etHourNow(d: Date = new Date()): number {
  return Number(ET_FORMATTER.format(d));
}

export interface C200HourPolicy {
  blackout: boolean;
  sizeFactor: number; // 1 = no change
}

export function c200HourPolicy(etHour: number): C200HourPolicy {
  return {
    blackout: C200_BLACKOUT_HOURS_ET.has(etHour),
    sizeFactor: etHour === C200_HAIRCUT_HOUR_ET ? C200_HAIRCUT_FACTOR : 1,
  };
}
