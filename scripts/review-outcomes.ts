/**
 * review:outcomes — judge past decisions. For each decision without a final
 * review, check whether the market resolved and record whether the decision
 * was good (copied winners / skipped losers) plus lessons learned.
 */

import { prisma } from "../src/lib/db";
import { getAdapter } from "../src/lib/adapters";
import { computePnl } from "../src/lib/paper";
import { log, logError } from "../src/lib/redact";

const HYPOTHETICAL_SIZE = 10;

async function main() {
  const adapter = getAdapter();
  const pending = await prisma.decisionJournal.findMany({
    where: {
      outcomeReviews: { none: { finalOutcome: { not: null } } },
      ...(adapter.isDemo ? {} : { isDemo: false }),
    },
    include: { observedTrade: true, paperTrades: true },
    take: 200,
  });
  if (pending.length === 0) {
    log("No decisions awaiting outcome review.");
    return;
  }

  log(`Reviewing ${pending.length} decisions…`);
  let reviewed = 0;
  const failures: string[] = [];

  for (const d of pending) {
    try {
      const m = await adapter.fetchMarket(d.marketId);
      if (!m.resolved || !m.winningOutcome) continue; // not resolved yet

      const won = m.winningOutcome === d.observedTrade.outcome;
      const pt = d.paperTrades[0];
      const simulatedPnl =
        pt?.realizedPnl ??
        computePnl(d.observedTrade.detectedPrice, won ? 1 : 0, HYPOTHETICAL_SIZE);

      let good: boolean;
      const lessons: string[] = [];
      if (d.decision === "paper_copy") {
        good = simulatedPnl > 0;
        lessons.push(
          good
            ? `Copy won ${simulatedPnl.toFixed(2)} — wallet signal + filters aligned`
            : `Copy lost ${simulatedPnl.toFixed(2)} — check whether entry drift or wallet quality was the miss`
        );
      } else {
        // For watchlist/skip: good if the market went against the wallet.
        good = !won;
        lessons.push(
          won
            ? `Missed winner (+${simulatedPnl.toFixed(2)} hypothetical) — decision was ${d.decision}, review which gate blocked it`
            : `Avoided loser (${simulatedPnl.toFixed(2)} hypothetical) — ${d.decision} was correct`
        );
      }

      await prisma.outcomeReview.create({
        data: {
          decisionJournalId: d.id,
          paperTradeId: pt?.id,
          finalOutcome: m.winningOutcome,
          simulatedPnl,
          wasDecisionGood: good,
          lessonsJson: JSON.stringify(lessons),
        },
      });
      reviewed++;
    } catch (e) {
      failures.push(`${d.marketId}: ${e instanceof Error ? e.message : e}`);
    }
  }

  log(`Outcome review complete: ${reviewed} decisions judged.`);
  if (failures.length) logError(`Failures (${failures.length}):\n` + failures.slice(0, 5).join("\n"));
}

main()
  .catch((e) => {
    logError("review:outcomes FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
