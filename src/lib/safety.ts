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
  BANKROLL_200: { min: 0.10, max: 10.00 }
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

/** Clamp a simulated position size into the allowed paper range. */
export function clampPaperSize(usd: number, botId: string = "STANDARD"): number {
  const limits = BOT_LIMITS[botId] || BOT_LIMITS.STANDARD;
  if (!Number.isFinite(usd)) return limits.min;
  return Math.min(limits.max, Math.max(limits.min, usd));
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
