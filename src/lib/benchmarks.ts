/**
 * Benchmarks: compare (1) bot-filtered paper trades vs (2) blind copy of all
 * tracked-wallet signals vs (3) watchlist vs (4) skipped. Uses OutcomeReview
 * and hypothetical PnL for decisions that were not copied: what would a $10
 * position have done?
 */

import { computePnl } from "./paper";
import { copyDecisions, decisionCounts, reviewedDecisions } from "./decision-aggregates";

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

function bucket(label: string, rows: { pnl: number | null }[], totalCount: number): BenchmarkBucket {
  const resolved = rows.filter((r) => r.pnl !== null) as { pnl: number }[];
  const total = resolved.reduce((a, r) => a + r.pnl, 0);
  const wins = resolved.filter((r) => r.pnl > 0).length;
  return {
    label,
    count: totalCount,
    resolvedCount: resolved.length,
    totalPnl: Math.round(total * 100) / 100,
    winRate: resolved.length ? Math.round((wins / resolved.length) * 1000) / 1000 : 0,
    avgPnl: resolved.length ? Math.round((total / resolved.length) * 100) / 100 : 0,
  };
}

export async function computeBenchmarks(): Promise<BenchmarkReport> {
  // Narrow reads (see src/lib/decision-aggregates.ts): counts come from a SQL
  // GROUP BY, hypothetical PnL only exists for the ~688 decisions with a
  // resolved review, and the bot's own bucket only needs paper_copy rows.
  // Previously this pulled all 253k rows with three nested includes (~10s).
  const [counts, reviewed, copies] = await Promise.all([decisionCounts(), reviewedDecisions(), copyDecisions()]);

  // Hypothetical PnL per reviewed decision (same computePnl call as before).
  const hypoRows = reviewed.map((d) => ({
    decision: d.decision,
    pnl: computePnl(d.detectedPrice, d.finalOutcome === d.outcome ? 1 : 0, HYPOTHETICAL_SIZE),
  }));

  const isCopy = (d: { decision: string }) => d.decision === "paper_copy";
  const isWatch = (d: { decision: string }) => d.decision === "watchlist";

  const copyRows: { pnl: number | null }[] = copies.map((c) => ({ pnl: c.realizedPnl }));
  // Blind copy = every observed signal, no filtering: the reviewed rows carry
  // the only non-null values, everything else is a null row for the count.
  const blindRows: { pnl: number | null }[] = hypoRows.map((h) => ({ pnl: h.pnl }));
  const watchRows: { pnl: number | null }[] = hypoRows.filter(isWatch).map((h) => ({ pnl: h.pnl }));
  const skipRows: { pnl: number | null }[] = hypoRows
    .filter((h) => !isCopy(h) && !isWatch(h))
    .map((h) => ({ pnl: h.pnl }));

  let missedWinners = 0;
  let avoidedLosers = 0;
  let badCopies = 0;
  let goodSkips = 0;

  for (const c of copies) {
    if (c.realizedPnl !== null && c.realizedPnl < 0) badCopies++;
  }
  for (const h of hypoRows) {
    if (isCopy(h)) continue;
    if (h.pnl > 0) missedWinners++;
    if (h.pnl < 0) {
      avoidedLosers++;
      if (!isWatch(h)) goodSkips++;
    }
  }

  return {
    botFiltered: bucket("Bot-filtered paper trades", copyRows, counts.paperCopy),
    blindCopy: bucket("Blind leaderboard copy", blindRows, counts.total),
    watchlist: bucket("Watchlist (not copied)", watchRows, counts.watchlist),
    skipped: bucket("Skipped", skipRows, counts.skipped),
    missedWinners,
    avoidedLosers,
    badCopies,
    goodSkips,
  };
}
