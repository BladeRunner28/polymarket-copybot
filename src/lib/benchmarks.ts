/**
 * Benchmarks: compare (1) bot-filtered paper trades vs (2) blind copy of all
 * tracked-wallet signals vs (3) watchlist vs (4) skipped. Uses OutcomeReview
 * and hypothetical PnL for decisions that were not copied: what would a $10
 * position have done?
 */

import { computePnl } from "./paper";
import { copyDecisions, decisionCounts, reviewedDecisions } from "./decision-aggregates";
import { normalizeOutcomeLabel } from "./resolution";

export interface BenchmarkBucket {
  label: string;
  count: number;
  resolvedCount: number;
  totalPnl: number;
  winRate: number;
  avgPnl: number;
  /**
   * 2026-10-29 (self-audit): Σ stake (USD) on the resolved rows — the denominator that `avgPnl`
   * is silent about. The EOD line used to compare "$/trade" between a bucket sized at whatever
   * each leg was worth and a hypothetical bucket at a flat $10, and printed the verdict as if the
   * two averages shared a unit.
   */
  totalCost: number;
  /** totalPnl / totalCost — the only unit both buckets can be compared in. */
  roi: number;
}

export interface BenchmarkReport {
  botFiltered: BenchmarkBucket;
  /**
   * The SAME question as `blindCopy`, on the same formula and the same flat $10 stake:
   * the decisions we copied, priced hold-to-resolution at the signal price. This is the
   * only pair that can be compared to the blind arm — `botFiltered` above is our EXIT
   * book (early exits included, own stake) and answers a different question.
   *
   * 2026-10-29 (label-integrity-bot-vs-blind-bases): the verdict used to be printed from
   * `botFiltered.roi > blindCopy.roi`, i.e. an EXIT number against an OUTCOME number, on
   * legs where the two labels disagree 7.7% of the time. The verdict now comes from this
   * matched pair; the exit book is still published, labelled, beside it.
   */
  botFilteredOutcome: BenchmarkBucket;
  blindCopy: BenchmarkBucket;
  watchlist: BenchmarkBucket;
  skipped: BenchmarkBucket;
  missedWinners: number; // watchlist/skip decisions that would have won
  avoidedLosers: number; // watchlist/skip decisions that would have lost
  badCopies: number; // paper_copy decisions that lost
  goodSkips: number; // alias of avoidedLosers among skips only
}

const HYPOTHETICAL_SIZE = 10;

type BucketRow = { pnl: number | null; cost?: number | null };

export function benchmarkBucket(label: string, rows: BucketRow[], totalCount: number): BenchmarkBucket {
  const resolved = rows.filter((r) => r.pnl !== null) as { pnl: number; cost?: number | null }[];
  const total = resolved.reduce((a, r) => a + r.pnl, 0);
  const cost = resolved.reduce((a, r) => a + (r.cost ?? 0), 0);
  const wins = resolved.filter((r) => r.pnl > 0).length;
  return {
    label,
    count: totalCount,
    resolvedCount: resolved.length,
    totalPnl: Math.round(total * 100) / 100,
    winRate: resolved.length ? Math.round((wins / resolved.length) * 1000) / 1000 : 0,
    avgPnl: resolved.length ? Math.round((total / resolved.length) * 100) / 100 : 0,
    totalCost: Math.round(cost * 100) / 100,
    roi: cost > 0 ? Math.round((total / cost) * 10000) / 10000 : 0,
  };
}

/**
 * The bot-vs-blind verdict, computed on the only pair that shares a basis.
 *
 * 2026-10-29: kept as a function so a caller cannot pick `botFiltered` (EXIT, own stake)
 * against `blindCopy` (OUTCOME, flat $10) and call the difference merit.
 */
export function beatBlindOnMatchedBasis(r: Pick<BenchmarkReport, "botFilteredOutcome" | "blindCopy">): boolean {
  return r.botFilteredOutcome.roi > r.blindCopy.roi;
}

export async function computeBenchmarks(): Promise<BenchmarkReport> {
  // Narrow reads (see src/lib/decision-aggregates.ts): counts come from a SQL
  // GROUP BY, hypothetical PnL only exists for the ~688 decisions with a
  // resolved review, and the bot's own bucket only needs paper_copy rows.
  // Previously this pulled all 253k rows with three nested includes (~10s).
  const [counts, reviewed, copies] = await Promise.all([decisionCounts(), reviewedDecisions(), copyDecisions()]);

  // Hypothetical PnL per reviewed decision (same computePnl call as before).
  // The label comparison goes through normalizeOutcomeLabel: stored
  // finalOutcome values are API-cased ("No") while stored outcomes are
  // uppercased ("NO"), so a raw === comparison scored every resolved review as a
  // loss — 0/688 exact matches vs 509/688 case-insensitive, which is what made
  // "Blind copy" read −$6,880 at a 0.0% win rate.
  const hypoRows = reviewed.map((d) => ({
    decision: d.decision,
    pnl: computePnl(d.detectedPrice, normalizeOutcomeLabel(d.finalOutcome) === normalizeOutcomeLabel(d.outcome) ? 1 : 0, HYPOTHETICAL_SIZE),
  }));

  const isCopy = (d: { decision: string }) => d.decision === "paper_copy";
  const isWatch = (d: { decision: string }) => d.decision === "watchlist";

  const copyRows: BucketRow[] = copies.map((c) => ({ pnl: c.realizedPnl, cost: c.sizeUsd }));
  // Blind copy = every observed signal, no filtering: the reviewed rows carry
  // the only non-null values, everything else is a null row for the count.
  const blindRows: BucketRow[] = hypoRows.map((h) => ({ pnl: h.pnl, cost: HYPOTHETICAL_SIZE }));
  const watchRows: BucketRow[] = hypoRows.filter(isWatch).map((h) => ({ pnl: h.pnl, cost: HYPOTHETICAL_SIZE }));
  const skipRows: BucketRow[] = hypoRows
    .filter((h) => !isCopy(h) && !isWatch(h))
    .map((h) => ({ pnl: h.pnl, cost: HYPOTHETICAL_SIZE }));

  // MATCHED-BASIS ARM (2026-10-29): the copy decisions that carry a review, priced exactly
  // like the blind arm — hold to resolution at the signal price, flat $10. Coverage is the
  // reviewed share of copies, printed with it; no unreviewed copy is imputed.
  const outRows: BucketRow[] = hypoRows.filter(isCopy).map((h) => ({ pnl: h.pnl, cost: HYPOTHETICAL_SIZE }));

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
    botFiltered: benchmarkBucket("Bot-filtered paper trades", copyRows, counts.paperCopy),
    botFilteredOutcome: benchmarkBucket("Bot copy decisions, hold to resolution", outRows, counts.paperCopy),
    blindCopy: benchmarkBucket("Blind leaderboard copy", blindRows, counts.total),
    watchlist: benchmarkBucket("Watchlist (not copied)", watchRows, counts.watchlist),
    skipped: benchmarkBucket("Skipped", skipRows, counts.skipped),
    missedWinners,
    avoidedLosers,
    badCopies,
    goodSkips,
  };
}
