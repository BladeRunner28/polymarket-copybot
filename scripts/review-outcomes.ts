/**
 * review:outcomes — judge past decisions. For each decision without a final
 * review, check whether the market resolved and record whether the decision
 * was good (copied winners / skipped losers) plus lessons learned.
 */

import { prisma } from "../src/lib/db";
import { getAdapter } from "../src/lib/adapters";
import { computePnl } from "../src/lib/paper";
import { didOutcomeWin } from "../src/lib/resolution";
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
  // 2026-09-15 tuning review #26 rec 3 (user-approved): SELECTION FIX.
  //
  // The old selection (orderBy decision asc, take 200) returned the SAME 200
  // oldest pending copy decisions every night — all created 2026-07-15
  // (long-dated markets such as will-…-ballon-dor…), of which only 34/200 had a
  // resolved leg. The loop then found nothing new to judge, so labels froze
  // (688 for four days, 3 consecutive EOD runs at "0 judged") while 8,475 copy
  // decisions WITH a settled leg sat unreviewed behind that head-of-line block.
  //
  // A decision with a settled leg is provably reviewable, so page those first by
  // recency; fall back to the broad pending set (also by recency) so
  // watchlist/skip rows still accrue hypothetical labels.
  const REVIEW_TAKE = Number(process.env.REVIEW_TAKE ?? 300);
  const settledLegWhere = {
    outcomeReviews: { none: { finalOutcome: { not: null } } },
    ...(adapter.isDemo ? {} : { isDemo: false }),
    paperTrades: { some: { status: { in: ["resolved", "closed"] } } },
  };
  let pending = await prisma.decisionJournal.findMany({
    where: settledLegWhere,
    include: { observedTrade: true, paperTrades: true },
    orderBy: { createdAt: "desc" },
    take: REVIEW_TAKE,
  });
  const settledCandidates = await prisma.decisionJournal.count({ where: settledLegWhere });

  // 2026-09-17 tuning review #28 rec 1 (user-approved): price the GATE's cost.
  // `watchlist` decisions never open a leg (the risk gates fire before booking),
  // so the settled-leg selection above can never see them — the drawdown gate
  // alone blocked 459 of them in #28 and its cost was therefore unmeasurable
  // (0 watchlist labels ever). They are judged on the MARKET outcome instead
  // (the loop already does this for non-copy decisions).
  //
  // Starvation guard: oldest-first, but floored at 30 days. Oldest-first is
  // self-clearing (an older market is likelier to have settled, and the frontier
  // advances as they do); the 30-day floor is what stops the July-era long-dated
  // rows from rebuilding the head-of-line block that #26 rec 3 fixed.
  const WATCH_TAKE = Number(process.env.WATCH_TAKE ?? 100);
  const watchFloor = new Date(Date.now() - 30 * 86_400_000);
  const watchCeil = new Date(Date.now() - 2 * 3_600_000);
  const watchWhere = {
    outcomeReviews: { none: { finalOutcome: { not: null } } },
    ...(adapter.isDemo ? {} : { isDemo: false }),
    decision: "watchlist",
    createdAt: { gte: watchFloor, lte: watchCeil },
  };
  const watchCandidates = await prisma.decisionJournal.count({ where: watchWhere });
  const watchPool = await prisma.decisionJournal.findMany({
    where: watchWhere,
    include: { observedTrade: true, paperTrades: true },
    orderBy: { createdAt: "asc" },
    take: WATCH_TAKE,
  });
  if (pending.length === 0) {
    const fallback = await prisma.decisionJournal.findMany({
      where: {
        outcomeReviews: { none: { finalOutcome: { not: null } } },
        ...(adapter.isDemo ? {} : { isDemo: false }),
      },
      include: { observedTrade: true, paperTrades: true },
      orderBy: { createdAt: "desc" },
      take: REVIEW_TAKE,
    });
    if (fallback.length === 0) {
      log("No decisions awaiting outcome review.");
      return;
    }
    log(`No settled-leg candidates — falling back to the most recent ${fallback.length} pending decisions.`);
    for (const f of fallback) pending.push(f);
  }
  for (const w of watchPool) pending.push(w);
  log(
    `Reviewing ${pending.length} decisions (${settledCandidates} pending rows have a settled leg; ` +
      `${watchCandidates} watchlist rows in the 2h–30d window, taking the ${watchPool.length} oldest).`
  );

  let reviewed = 0;
  const failures: string[] = [];

  for (const d of pending) {
    try {
      let m: { resolved?: boolean; winningOutcome?: string; winningLabel?: string; yesPrice?: number } | null = null;
      try {
        m = await adapter.fetchMarket(d.marketId);
      } catch {
        // Gamma 404s archived slugs — CLOB still serves them by conditionId.
        m = await fetchResolvedViaClob(d.observedTrade.conditionId);
      }
      // The venue's own token label ("Yes", "Under", "Vitality") — comparing it
      // case-insensitively is what makes these reviews correct: the old
      // `winningOutcome === outcome` compared an API-cased label ("No") to the
      // uppercased stored label ("NO"), so `won` was ALWAYS false and every
      // watchlist/skip review was stamped "avoided loser" regardless of reality.
      const winnerLabel = m?.winningLabel ?? m?.winningOutcome;
      if (!m || !m.resolved || !winnerLabel) continue; // not resolved yet

      const won = didOutcomeWin(d.observedTrade.outcome, { winningLabel: winnerLabel, yesPrice: m.yesPrice });
      if (won === null) {
        logError(
          `[REVIEW] unmapped outcome label — decision ${d.id} outcome='${d.observedTrade.outcome}' vs winner='${winnerLabel}': skipping rather than judging`
        );
        continue;
      }
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
          finalOutcome: winnerLabel,
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
