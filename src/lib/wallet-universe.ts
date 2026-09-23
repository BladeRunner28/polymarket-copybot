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
 * v62 (tuning review #34 rec 1, user-approved 2026-09-23) — the OBSERVE set
 * ROTATES. Ordering it by `lastTrackedAt desc` under a 40-wallet cap made the
 * sweep re-take the NEWEST demotions every cycle: measured 09-23, the 40th
 * award went to a wallet demoted ~3.2–4.2 h earlier, 108 of 175 eligible
 * wallets had ZERO observation rows in 24 h, and a deferred wallet's
 * lastTrackedAt was never refreshed, so the deferral was permanent. The sweep
 * now orders by `lastObservedAt` ASC (NULLs first = never observed) and every
 * successful sweep stamps the wallets it swept, so the cap walks the whole
 * eligible pool in ~ceil(pool / MAX_OBSERVE) cycles.
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
export type ObserveWallet = {
  address: string;
  globalScore: number;
  lastTrackedAt: Date | null;
  lastObservedAt: Date | null;
};

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

/** Shared predicate for the OBSERVE universe: wallets demoted out of `track`
 *  that held it inside the trailing window. Live mode only (isDemo=false) — the
 *  demo adapter has no on-chain history, so the demo universe stays empty. */
const observeWhere = () =>
  ({
    status: { not: "track" },
    isDemo: false,
    lastTrackedAt: { gte: new Date(Date.now() - OBSERVE_LOOKBACK_DAYS * 86_400_000) },
  }) as const;

/** Demoted wallets that held `track` inside the trailing window, LEAST recently
 *  observed first (never-observed first), so the MAX_OBSERVE cap rotates over
 *  the whole eligible pool instead of re-taking the newest demotions. Live-mode
 *  only — the demo adapter has no on-chain history. */
export async function observeOnlyWallets(isDemo = false): Promise<ObserveWallet[]> {
  if (isDemo) return [];
  return prisma.walletProfile.findMany({
    where: observeWhere(),
    orderBy: [{ lastObservedAt: { sort: "asc", nulls: "first" } }, { address: "asc" }],
    take: MAX_OBSERVE,
    select: { address: true, globalScore: true, lastTrackedAt: true, lastObservedAt: true },
  });
}

/** How many wallets the observation window currently lists (the pool the
 *  40-wallet cap rotates over) — logged so coverage is measurable per cycle. */
export async function observeEligibleCount(isDemo = false): Promise<number> {
  if (isDemo) return 0;
  return prisma.walletProfile.count({ where: observeWhere() });
}

/** Stamp the wallets a sweep just covered (v62). Called with the wallets whose
 *  activity fetch SUCCEEDED, so a failed fetch is retried next cycle rather than
 *  waiting a full rotation. Returns the number of rows stamped. */
export async function stampObserved(addresses: string[]): Promise<number> {
  if (addresses.length === 0) return 0;
  const { count } = await prisma.walletProfile.updateMany({
    where: { address: { in: addresses } },
    data: { lastObservedAt: new Date() },
  });
  return count;
}

/** Distinct addresses in the copy set, for the scorer's defensive gate. */
export async function copyWalletAddresses(isDemo = false): Promise<Set<string>> {
  const rows = await copyWalletSet(isDemo);
  return new Set(rows.map((r) => r.address));
}
