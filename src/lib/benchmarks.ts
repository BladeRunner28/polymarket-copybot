/**
 * Benchmarks: compare (1) bot-filtered paper trades vs (2) blind copy of all
 * tracked-wallet signals vs (3) watchlist vs (4) skipped. Uses OutcomeReview
 * and hypothetical PnL for decisions that were not copied: what would a $10
 * position have done?
 */

import { prisma } from "./db";
import { computePnl } from "./paper";

export interface BenchmarkBucket {
  label: string;
  count: number;
  resolvedCount: number;
  totalPnl: number;
  winRate: number;
  avgPnl: number;
}

export interface BenchmarkReport {
  botFiltered: BenchmarkBucket;
  blindCopy: BenchmarkBucket;
  watchlist: BenchmarkBucket;
  skipped: BenchmarkBucket;
  missedWinners: number; // watchlist/skip decisions that would have won
  avoidedLosers: number; // watchlist/skip decisions that would have lost
  badCopies: number; // paper_copy decisions that lost
  goodSkips: number; // alias of avoidedLosers among skips only
}

const HYPOTHETICAL_SIZE = 10;

function bucket(label: string, rows: { pnl: number | null }[]): BenchmarkBucket {
  const resolved = rows.filter((r) => r.pnl !== null) as { pnl: number }[];
  const total = resolved.reduce((a, r) => a + r.pnl, 0);
  const wins = resolved.filter((r) => r.pnl > 0).length;
  return {
    label,
    count: rows.length,
    resolvedCount: resolved.length,
    totalPnl: Math.round(total * 100) / 100,
    winRate: resolved.length ? Math.round((wins / resolved.length) * 1000) / 1000 : 0,
    avgPnl: resolved.length ? Math.round((total / resolved.length) * 100) / 100 : 0,
  };
}

export async function computeBenchmarks(): Promise<BenchmarkReport> {
  const decisions = await prisma.decisionJournal.findMany({
    include: {
      observedTrade: true,
      paperTrades: true,
      outcomeReviews: true,
    },
  });

  const copyRows: { pnl: number | null }[] = [];
  const watchRows: { pnl: number | null }[] = [];
  const skipRows: { pnl: number | null }[] = [];
  const blindRows: { pnl: number | null }[] = [];

  let missedWinners = 0;
  let avoidedLosers = 0;
  let badCopies = 0;
  let goodSkips = 0;

  for (const d of decisions) {
    // Hypothetical PnL for uncopied decisions comes from OutcomeReview.finalOutcome.
    const review = d.outcomeReviews.find((r) => r.finalOutcome !== null);
    const entry = d.observedTrade.detectedPrice;
    let hypoPnl: number | null = null;
    if (review?.finalOutcome) {
      const won = review.finalOutcome === d.observedTrade.outcome;
      hypoPnl = computePnl(entry, won ? 1 : 0, HYPOTHETICAL_SIZE);
    }

    // Blind copy = every observed signal from a leaderboard wallet, no filtering.
    blindRows.push({ pnl: hypoPnl });

    if (d.decision === "paper_copy") {
      const pt = d.paperTrades[0];
      const pnl = pt?.realizedPnl ?? null;
      copyRows.push({ pnl });
      if (pnl !== null && pnl < 0) badCopies++;
    } else if (d.decision === "watchlist") {
      watchRows.push({ pnl: hypoPnl });
      if (hypoPnl !== null && hypoPnl > 0) missedWinners++;
      if (hypoPnl !== null && hypoPnl < 0) avoidedLosers++;
    } else {
      skipRows.push({ pnl: hypoPnl });
      if (hypoPnl !== null && hypoPnl > 0) missedWinners++;
      if (hypoPnl !== null && hypoPnl < 0) {
        avoidedLosers++;
        goodSkips++;
      }
    }
  }

  return {
    botFiltered: bucket("Bot-filtered paper trades", copyRows),
    blindCopy: bucket("Blind leaderboard copy", blindRows),
    watchlist: bucket("Watchlist (not copied)", watchRows),
    skipped: bucket("Skipped", skipRows),
    missedWinners,
    avoidedLosers,
    badCopies,
    goodSkips,
  };
}
