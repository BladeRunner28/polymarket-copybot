/**
 * v41 entry-hour policy (2026-08-31 report, user-approved).
 *
 * Calibration analysis of N=1,076 C-200 trades (scripts/analyze-calibration.py,
 * ET hours via ZoneInfo("America/New_York")) found significant hourly
 * effects on C-200 PnL:
 *   20:00 ET  excess -0.27 (z=-3.31), -$91  -> blackout new entries
 *   10:00 ET  -$178 (worst dollar hour, z=-1.74) -> 50% size haircut
 *   21:00 ET  excess +0.25 (z=+2.80)        -> stays open (no blanket ban)
 * v44 (tuning review #13, approved): the 20:00/23:00 blackout applied to BOTH
 * books. v48 (2026-09-04 daily report, approved): 23:00 UN-GATED — venue
 * separation showed 85% of its "drain" was phantom-priced Kalshi rows
 * (-$80.91 on 9 rows); PM-only 23:00 is noise. Re-test after
 * kalshi-reprice-92. 20:00 ET survives venue separation (-$80.43 on 31 PM
 * trades) and stays blacked out. The 10:00 ET haircut stays C-200-only.
 * DST-aware via America/New_York.
 */

const ET_FORMATTER = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  hour: "numeric",
  hourCycle: "h23", // 0-23 (hour12:false alone can yield "24" at midnight)
});

export const C200_BLACKOUT_HOURS_ET: ReadonlySet<number> = new Set([20]); // v48: 23:00 un-gated (phantom-Kalshi artifact)
// C-200-ONLY blackouts (2026-09-13 daily report Change 1, user-approved). The
// shared set above applies to BOTH books; this one must NOT — 08:00 ET is
// C-200-negative but STANDARD-positive (all-time Polymarket-only: C-200 34 rows
// −$71.12; STANDARD 250 rows +$1,048.17), so gating it for STANDARD would remove
// a winning hour. Same reasoning is why the shared 20:00 gate is C-200-only in
// spirit (STANDARD 20:00 = 252 rows +$887.61, blocked since v44 — flagged, not
// changed here).
export const C200_ONLY_BLACKOUT_HOURS_ET: ReadonlySet<number> = new Set([8]);
export const C200_HAIRCUT_HOUR_ET = 10;
export const C200_HAIRCUT_FACTOR = 0.5;

/** Current hour in America/New_York (0-23), DST-aware. */
export function etHourNow(d: Date = new Date()): number {
  return Number(ET_FORMATTER.format(d));
}

export interface C200HourPolicy {
  blackout: boolean;
  /** Blackout that applies to the C-200 book only (not STANDARD). */
  c200OnlyBlackout: boolean;
  sizeFactor: number; // 1 = no change
}

/** Hours blocked for a given book: the shared set + C-200-only extras. */
export function isHourBlackedOut(botId: string, etHour: number): boolean {
  if (C200_BLACKOUT_HOURS_ET.has(etHour)) return true;
  return botId === "BANKROLL_200" && C200_ONLY_BLACKOUT_HOURS_ET.has(etHour);
}

export function c200HourPolicy(etHour: number): C200HourPolicy {
  return {
    blackout: C200_BLACKOUT_HOURS_ET.has(etHour),
    c200OnlyBlackout: C200_ONLY_BLACKOUT_HOURS_ET.has(etHour),
    sizeFactor: etHour === C200_HAIRCUT_HOUR_ET ? C200_HAIRCUT_FACTOR : 1,
  };
}
