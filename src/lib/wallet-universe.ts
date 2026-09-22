/**
 * v61 (tuning review #33 rec 1, user-approved 2026-09-22) — OBSERVATION vs COPY.
 *
 * The hourly wallet cap re-derives the tracked set on every scan (top
 * MAX_TRACKED by globalScore), so a wallet rotates out of `track` minutes after
 * it was copied and its trades stop being seen at all. Measured 2026-09-22: the
 * detected-trade funnel fell 6,515 → 1,211/24h, and 58% of the prior window came
 * from four wallets the cap had rotated out — all still trading on-chain.
 *
 * This module is the single source of truth for the two universes:
 *   - COPY set     : current status='track', top MAX_TRACKED by score. The ONLY
 *                    wallets allowed to book a new copy.
 *   - OBSERVE set  : wallets whose lastTrackedAt (see WalletProfile) is inside
 *                    the trailing window — i.e. they held `track` recently, were
 *                    demoted, and are still worth watching. Their trades are
 *                    stored as ObservedTrade rows with observationOnly=true.
 *
 * Containment rule: an observation row must never reach a copy decision or a
 * published number. Its readers filter `observationOnly: false` (score-trades
 * unscored queue / swarm count / flash window, insider.ts, record-l2.ts), and
 * measurement scripts are structurally safe because they JOIN ObservedTrade via
 * DecisionJournal, which observation rows never get.
 */
import { prisma } from "./db";

export const MAX_TRACKED = Number(process.env.MAX_TRACKED_WALLETS ?? 25);
export const OBSERVE_LOOKBACK_DAYS = Number(process.env.WALLET_OBSERVE_LOOKBACK_DAYS ?? 7);
/** Upper bound on the observation sweep — a 7d window of hourly churn can list
 *  hundreds of wallets; the recently-demoted (still active) ones are taken first
 *  and the remainder is reported as deferred rather than silently dropped. */
export const MAX_OBSERVE = Number(process.env.MAX_OBSERVE_WALLETS ?? 40);

export type CopyWallet = { address: string; globalScore: number };
export type ObserveWallet = { address: string; globalScore: number; lastTrackedAt: Date | null };

/**
 * The wallets allowed to book NEW copies. Identical predicate to the monitor's
 * read-time cap (status='track', top-N by score), so the scorer's gate cannot
 * disagree with the universe the monitor fetched.
 */
export async function copyWalletSet(isDemo = false): Promise<CopyWallet[]> {
  return prisma.walletProfile.findMany({
    where: isDemo ? { status: "track" } : { status: "track", isDemo: false },
    orderBy: [{ globalScore: "desc" }, { address: "asc" }],
    take: MAX_TRACKED,
    select: { address: true, globalScore: true },
  });
}

/** Demoted wallets that held `track` inside the trailing window, most recently
 *  tracked first. Live-mode only — the demo adapter has no on-chain history. */
export async function observeOnlyWallets(isDemo = false): Promise<ObserveWallet[]> {
  if (isDemo) return [];
  const cutoff = new Date(Date.now() - OBSERVE_LOOKBACK_DAYS * 86_400_000);
  return prisma.walletProfile.findMany({
    where: { status: { not: "track" }, isDemo: false, lastTrackedAt: { gte: cutoff } },
    orderBy: [{ lastTrackedAt: "desc" }, { address: "asc" }],
    take: MAX_OBSERVE,
    select: { address: true, globalScore: true, lastTrackedAt: true },
  });
}

/** Distinct addresses in the copy set, for the scorer's defensive gate. */
export async function copyWalletAddresses(isDemo = false): Promise<Set<string>> {
  const rows = await copyWalletSet(isDemo);
  return new Set(rows.map((r) => r.address));
}
