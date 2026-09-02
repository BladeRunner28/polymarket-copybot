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
const CLOB_API = "https://clob.polymarket.com";

/**
 * Resolve archived markets via the CLOB API. Gamma 404s dead/renamed slugs
 * (the root cause of the empty OutcomeReview table), but CLOB keeps every
 * market by conditionId with a per-token `winner` flag — keyless, read-only.
 */
async function fetchResolvedViaClob(conditionId: string | null) {
  if (!conditionId) return null;
  const res = await fetch(
    `${CLOB_API}/markets/${encodeURIComponent(conditionId)}`,
    {
      headers: { accept: "application/json", "user-agent": "copybot-research/0.1 (paper-trading-only)" },
      signal: AbortSignal.timeout(15000),
    }
  );
  if (!res.ok) throw new Error(`clob ${res.status}`);
  const m = (await res.json()) as {
    closed?: boolean;
    tokens?: Array<{ outcome: string; winner: boolean }>;
  };
  if (!m.closed) return null;
  const winner = (m.tokens ?? []).find((t) => t.winner === true);
  return winner ? { resolved: true as const, winningOutcome: winner.outcome } : null;
}

async function main() {
  const adapter = getAdapter();
  const pending = await prisma.decisionJournal.findMany({
    where: {
      outcomeReviews: { none: { finalOutcome: { not: null } } },
      ...(adapter.isDemo ? {} : { isDemo: false }),
    },
    include: { observedTrade: true, paperTrades: true },
    // paper_copy < skip < watchlist alphabetically — real-PnL labels first,
    // so the ML training set fills with actual outcomes before hypotheticals.
    orderBy: { decision: "asc" },
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
      let m: { resolved?: boolean; winningOutcome?: string } | null = null;
      try {
        m = await adapter.fetchMarket(d.marketId);
      } catch {
        // Gamma 404s archived slugs — CLOB still serves them by conditionId.
        m = await fetchResolvedViaClob(d.observedTrade.conditionId);
      }
      if (!m || !m.resolved || !m.winningOutcome) continue; // not resolved yet

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
