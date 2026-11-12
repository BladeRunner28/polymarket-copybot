/**
 * SAFETY MODULE — the single source of truth for execution policy.
 *
 * Version 1 is PAPER TRADING ONLY.
 *   - No private keys are accepted, stored, or requested.
 *   - No transactions are signed.
 *   - No orders are sent to any exchange.
 *   - REAL_EXECUTION_ENABLED is a hard-coded constant, not an env var, so it
 *     cannot be flipped by configuration mistake. Enabling real execution
 *     would require a deliberate code change, review, and a new version.
 */

export const REAL_EXECUTION_ENABLED = false as const;

export const PAPER_MIN_SIZE_USD = 0.25;
export const PAPER_MAX_SIZE_USD = 20;

export const BOT_LIMITS: Record<string, { min: number; max: number }> = {
  STANDARD: { min: 0.25, max: 20.00 },
  // v41 (2026-08-31, approved): C-200 overall cap raised $10 -> $20.
  BANKROLL_200: { min: 0.10, max: 20.00 }
};

/** Throws if anything ever tries to execute a real trade. */
export function assertPaperOnly(context: string): void {
  // REAL_EXECUTION_ENABLED is typed `false as const`; this guard exists so
  // that any future edit flipping the constant still hits a runtime tripwire
  // in every code path that creates trades.
  if ((REAL_EXECUTION_ENABLED as boolean) !== false) {
    throw new Error(
      `SAFETY VIOLATION in ${context}: real execution is not permitted in version 1.`
    );
  }
}

/**
 * Clamp a simulated position size into the allowed paper range.
 *
 * @param maxUsd optional per-call upper bound override. v49 Phase B: the
 *   Kelly sizer's kellyMaxSizeUsd (default $60) exceeds the legacy
 *   BANKROLL_200 cap ($20) by design — the executor must honor the rule-set
 *   cap for Kelly-sized copies while legacy sizing keeps BOT_LIMITS exactly.
 *   Never below the bot's floor (avoids an inverted range).
 */
export function clampPaperSize(usd: number, botId: string = "STANDARD", maxUsd?: number): number {
  const limits = BOT_LIMITS[botId] || BOT_LIMITS.STANDARD;
  if (!Number.isFinite(usd)) return limits.min;
  const hi = maxUsd !== undefined ? Math.max(limits.min, maxUsd) : limits.max;
  return Math.min(hi, Math.max(limits.min, usd));
}

/**
 * The bot ids whose sizing can take the KELLY path — i.e. the lanes for which
 * `clampPaperSize(usd, botId, rules.kellyMaxSizeUsd)` can raise the ceiling above BOT_LIMITS.
 *
 * Mirrors `isKellyCandidate` in scripts/score-trades.ts
 * (`botId === "BANKROLL_200" && lane !== "short_ttr" && rules.kellyEnabled === 1`).
 * Kept here so the ceiling arithmetic has ONE definition instead of one per script.
 */
export const KELLY_BOTS: readonly string[] = ["BANKROLL_200"];

/**
 * The size range a lane can ACTUALLY be given, per sizing path.
 *
 *   legacy path   clampPaperSize(usd, botId)          -> BOT_LIMITS[botId] ?? BOT_LIMITS.STANDARD
 *   Kelly path    clampPaperSize(usd, botId, maxUsd)  -> hi = max(limits.min, maxUsd),
 *                   reachable only for KELLY_BOTS; every other lane keeps limits.max
 *
 * `BotBankroll.minPositionSize` / `maxPositionSize` are DISPLAY-ONLY copies of this and nothing
 * reads them. Every writer or checker of those columns MUST call this function rather than
 * re-derive the arithmetic: the ML_LANE row advertised $0.10 / $100 for 22 days because
 * scripts/apply-ml-lane.ts mirrored `max(BOT_LIMITS.max, kellyMaxSizeUsd)` onto a lane that has
 * no BOT_LIMITS entry (so it falls back to STANDARD's {0.25, 20}) and cannot take the Kelly path.
 */
export function effectiveSizeLimits(
  botId: string,
  kellyMaxSizeUsd: number
): { min: number; max: number } {
  const limits = BOT_LIMITS[botId] || BOT_LIMITS.STANDARD;
  const max = KELLY_BOTS.includes(botId)
    ? Math.max(limits.max, Math.max(limits.min, kellyMaxSizeUsd))
    : limits.max;
  return { min: limits.min, max };
}

/**
 * Feature: Phase 1 - Circuit Breaker
 * PBI: Auto-halts execution if a bot fires off an abnormal burst of trades.
 * Prevents blowing up the portfolio during network/bot tilt anomalies.
 */
export async function checkCircuitBreaker(prisma: any, botId: string): Promise<void> {
  const FIVE_MINUTES_AGO = new Date(Date.now() - 5 * 60 * 1000);
  const MAX_TRADES_PER_5M = 15; // Strict threshold for copy anomalies

  const recentTrades = await prisma.paperTrade.count({
    where: {
      botId,
      openedAt: { gte: FIVE_MINUTES_AGO }
    }
  });

  if (recentTrades >= MAX_TRADES_PER_5M) {
    throw new Error(`CIRCUIT BREAKER TRIPPED for ${botId}: ${recentTrades} trades in the last 5 minutes exceeds threshold of ${MAX_TRADES_PER_5M}. Halting execution.`);
  }
}
