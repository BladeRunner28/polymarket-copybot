/**
 * Narrow decision-journal reads for the benchmark/analytics pages.
 *
 * WHY: `computeBenchmarks()` (/performance) and the Analytics page each pulled
 * ALL 253k DecisionJournal rows with `include: { observedTrade, paperTrades,
 * outcomeReviews }` — ~90 MB of JS objects, 4-10s per page load. Almost none of
 * those rows can affect the output:
 *
 *   - hypothetical PnL exists only where an OutcomeReview has a finalOutcome
 *     (688 rows today) — every other decision contributes a `{ pnl: null }`
 *     row, which affects only the *count* of its bucket;
 *   - the bot's own bucket needs only `decision='paper_copy'` rows (14k);
 *   - per-decision counts come from a GROUP BY in SQL.
 *
 * So these helpers fetch ~15k narrow rows instead of 253k wide ones. The JS
 * arithmetic that consumes them is unchanged, which keeps results identical —
 * importantly, `paperTrades[0]` is still resolved by Prisma (1,086 decisions
 * have more than one trade, so its order is NOT reproducible in raw SQL).
 */

import { prisma } from "./db";

export type DecisionCounts = {
  /** exact per-decision-string counts (paper_copy | watchlist | skip | …) */
  byType: Record<string, number>;
  paperCopy: number;
  watchlist: number;
  /** Everything that is neither paper_copy nor watchlist (the "skipped" bucket). */
  skipped: number;
  total: number;
};

/** Per-decision-type counts, from SQL GROUP BY. */
export async function decisionCounts(): Promise<DecisionCounts> {
  const rows = await prisma.decisionJournal.groupBy({ by: ["decision"], _count: { _all: true } });
  const byType: Record<string, number> = {};
  let total = 0;
  for (const r of rows) {
    const n = r._count._all;
    byType[r.decision] = n;
    total += n;
  }
  const paperCopy = byType["paper_copy"] ?? 0;
  const watchlist = byType["watchlist"] ?? 0;
  return { byType, paperCopy, watchlist, skipped: total - paperCopy - watchlist, total };
}

export type ReviewedDecision = {
  /** decision id — only used for de-dup/debug */
  id: string;
  decision: string;
  createdAt: Date;
  /** observed trade fields, required by the hypothetical-PnL formula */
  detectedPrice: number;
  outcome: string;
  /** the first review carrying a non-null finalOutcome (mirrors `.find()`) */
  finalOutcome: string;
};

/**
 * Decisions that have an OutcomeReview with a non-null finalOutcome — the only
 * rows that can produce a hypothetical PnL.
 */
export async function reviewedDecisions(): Promise<ReviewedDecision[]> {
  const rows = await prisma.decisionJournal.findMany({
    where: { outcomeReviews: { some: { finalOutcome: { not: null } } } },
    // createdAt ASC mirrors the original `orderBy: { createdAt: "asc" }` scan —
    // callers rebuild cumulative day series from these rows.
    orderBy: { createdAt: "asc" },
    select: {
      id: true,
      decision: true,
      createdAt: true,
      observedTrade: { select: { detectedPrice: true, outcome: true } },
      outcomeReviews: { select: { finalOutcome: true } },
    },
  });
  const out: ReviewedDecision[] = [];
  for (const d of rows) {
    // Same selection rule as the original JS: first review with a non-null
    // finalOutcome, then a truthiness check.
    const review = d.outcomeReviews.find((r) => r.finalOutcome !== null);
    if (review?.finalOutcome) {
      out.push({
        id: d.id,
        decision: d.decision,
        createdAt: d.createdAt,
        detectedPrice: d.observedTrade.detectedPrice,
        outcome: d.observedTrade.outcome,
        finalOutcome: review.finalOutcome,
      });
    }
  }
  return out;
}

export type CopyDecision = { createdAt: Date; realizedPnl: number | null };

/**
 * paper_copy decisions with the realized PnL of their first paper trade
 * (`paperTrades[0]`), left as Prisma ordered it.
 */
export async function copyDecisions(): Promise<CopyDecision[]> {
  const rows = await prisma.decisionJournal.findMany({
    where: { decision: "paper_copy" },
    orderBy: { createdAt: "asc" },
    select: { createdAt: true, paperTrades: { select: { realizedPnl: true } } },
  });
  return rows.map((d) => ({ createdAt: d.createdAt, realizedPnl: d.paperTrades[0]?.realizedPnl ?? null }));
}
