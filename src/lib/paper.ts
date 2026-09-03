/**
 * Paper trading engine. Creates simulated positions ($.25–$20), updates their
 * PnL, and resolves them. All functions call assertPaperOnly() as a tripwire.
 * PnL model for a BUY of outcome O at price p with $S: shares = S/p,
 * value = shares * currentPrice, pnl = value - S. On resolution the price is
 * 1 (won) or 0 (lost). SELL is modeled as buying the opposite outcome.
 */

import { prisma } from "./db";
import { assertPaperOnly, clampPaperSize, checkCircuitBreaker } from "./safety";

export function computePnl(entryPrice: number, currentPrice: number, sizeUsd: number): number {
  if (entryPrice <= 0) return 0;
  const shares = sizeUsd / entryPrice;
  return Math.round((shares * currentPrice - sizeUsd) * 100) / 100;
}

/**
 * v41 (2026-08-31 report, user-approved): C-200 (BANKROLL_200) size mapping.
 * Maps the STANDARD-scale parent size (0.25-20) into the C-200 band
 * ($0.20-$20 - overall cap raised from $10) and applies calibration-band
 * multipliers from the N=1,076 C-200 calibration analysis:
 *   entry < 0.20  x1.5  - the only significant positive edge (excess +0.31, z=+4.47)
 *   0.20-0.40     x1.0  - positive excess (z=+2.72) but dollar-negative; watch
 *   0.40-0.60     x0.5  - dead zone: 48% of volume, -$271.70 = 99.9% of total
 *                         drag (v42, 2026-09-01 report: deepened from x0.75)
 *   entry >= 0.60 x0.5  - significant premium drag on favorites (z=-2.49/-2.42)
 * Band sizing lives HERE (single source of truth); the v37 rules-layer
 * factors (deadZoneSizeFactor / longshotSizeFactor) are neutralized at 1.0
 * (RuleSet v39) so the bands apply exactly once. Caller clamps the result.
 */
export function mapBankroll200Size(standardScaleSize: number, entryPrice: number): number {
  const percent = (standardScaleSize - 0.25) / (20.0 - 0.25);
  let size = 0.2 + percent * (20.0 - 0.2);
  // Only apply band multipliers to sane prices (0..1 markets); non-finite or
  // <=0 entries (bad data) fall through at x1.0.
  if (Number.isFinite(entryPrice) && entryPrice > 0) {
    if (entryPrice < 0.2) size *= 1.5;
    else if (entryPrice >= 0.6) size *= 0.5;
    else if (entryPrice >= 0.4) size *= 0.5; // v42: was x0.75
  }
  return size;
}

export async function openPaperTrade(params: {
  decisionJournalId: string;
  walletAddress: string;
  marketId: string;
  outcome: string;
  side: string;
  entryPrice: number;
  simulatedPositionSize: number;
  isDemo?: boolean;
  botId?: string; // <--- NEW
  venue?: string; // Phase 3: Multi-Venue expansion
}) {
  assertPaperOnly("openPaperTrade");
  const botId = params.botId ?? "STANDARD";
  const venue = params.venue ?? "Polymarket";
  let size = params.simulatedPositionSize;

  // Enforce Phase 1 Safety: Circuit Breaker
  await checkCircuitBreaker(prisma, botId);

  if (botId === "BANKROLL_200") {
    // v41: calibration-band mapping + overall cap raise ($10 -> $20).
    size = mapBankroll200Size(size, params.entryPrice);
  }

  // Ensure absolute bounds enforcement
  size = clampPaperSize(size, botId);

  // Feature: Phase 4 (Shadow Production)
  // Route the C-200 bot through the Rust FAK Execution API instead of direct DB write.
  if (botId === "BANKROLL_200") {
    console.log(`[Node.js] Dispatching Execution Intent to Rust Core for ${botId}...`);
    try {
      await fetch("http://127.0.0.1:3014/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          bot_id: botId,
          venue,
          market_id: params.marketId,
          outcome: params.outcome,
          side: params.side,
          price: params.entryPrice,
          size_usd: size,
          decision_journal_id: params.decisionJournalId,
          wallet_address: params.walletAddress
        })
      });
      // Rust webhook will handle the DB write upon successful simulation
      return { id: "rust-pending" };
    } catch (e) {
      throw new Error(`Rust Execution Engine offline or failed: ${e}`);
    }
  }

  return await prisma.$transaction(async (tx) => {
    if (botId !== "STANDARD") {
      const bankroll = await tx.botBankroll.findUniqueOrThrow({ where: { botId } });
      if (bankroll.cashBalance < size) {
        throw new Error(`Insufficient capital for ${botId}: Available $${bankroll.cashBalance.toFixed(2)}, Required $${size.toFixed(2)}`);
      }
      await tx.botBankroll.update({
        where: { botId },
        data: { cashBalance: { decrement: size } }
      });
    }

    return await tx.paperTrade.create({
      data: {
        botId,
        venue,
        decisionJournalId: params.decisionJournalId,
        walletAddress: params.walletAddress,
        marketId: params.marketId,
        outcome: params.outcome,
        side: params.side,
        entryPrice: params.entryPrice,
        currentPrice: params.entryPrice,
        simulatedPositionSize: size,
        unrealizedPnl: 0,
        status: "open",
        isDemo: params.isDemo ?? false,
      },
    });
  });
}

/**
 * Record an execution result coming back from the Rust execution engine
 * (execution-result webhook). The ONLY place — besides resolve/close — that
 * mutates BotBankroll, so the cash ledger stays consistent with paper.ts.
 */
export async function recordExecutionResult(body: {
  botId: string;
  venue: string;
  decisionJournalId: string;
  walletAddress: string;
  marketId: string;
  outcome: string;
  side: string;
  entryPrice: number;
  simulatedPositionSize: number;
}): Promise<void> {
  assertPaperOnly("recordExecutionResult");
  await prisma.$transaction(async (tx) => {
    // 1. If compounding bot, deduct cash
    if (body.botId !== "STANDARD") {
      const bankroll = await tx.botBankroll.findUniqueOrThrow({ where: { botId: body.botId } });
      if (bankroll.cashBalance < body.simulatedPositionSize) {
        throw new Error(`Insufficient capital`);
      }
      await tx.botBankroll.update({
        where: { botId: body.botId },
        data: { cashBalance: { decrement: body.simulatedPositionSize } },
      });
    }
    // 2. Write the trade based on Rust's FAK fill confirmation
    await tx.paperTrade.create({
      data: {
        botId: body.botId,
        venue: body.venue,
        decisionJournalId: body.decisionJournalId,
        walletAddress: body.walletAddress,
        marketId: body.marketId,
        outcome: body.outcome,
        side: body.side,
        entryPrice: body.entryPrice,
        currentPrice: body.entryPrice,
        simulatedPositionSize: body.simulatedPositionSize,
      },
    });
  });
}

/** Update an open paper trade with the latest price; snapshot PnL. */
export async function updatePaperTradePrice(tradeId: string, currentOutcomePrice: number) {
  assertPaperOnly("updatePaperTradePrice");
  const trade = await prisma.paperTrade.findUniqueOrThrow({ where: { id: tradeId } });
  if (trade.status !== "open") return trade;
  const pnl = computePnl(trade.entryPrice, currentOutcomePrice, trade.simulatedPositionSize);
  const [updated] = await prisma.$transaction([
    prisma.paperTrade.update({
      where: { id: tradeId },
      data: { currentPrice: currentOutcomePrice, unrealizedPnl: pnl },
    }),
    prisma.pnlSnapshot.create({
      data: { paperTradeId: tradeId, price: currentOutcomePrice, pnl },
    }),
  ]);
  return updated;
}

/** Resolve a paper trade when the underlying market resolves. */
export async function resolvePaperTrade(tradeId: string, won: boolean) {
  assertPaperOnly("resolvePaperTrade");
  const trade = await prisma.paperTrade.findUniqueOrThrow({ where: { id: tradeId } });
  if (trade.status === "resolved") return trade;
  const finalPrice = won ? 1 : 0;
  const pnl = computePnl(trade.entryPrice, finalPrice, trade.simulatedPositionSize);
  const payout = trade.simulatedPositionSize + pnl;

  return prisma.$transaction(async (tx) => {
    if (trade.botId !== "STANDARD") {
      await tx.botBankroll.update({
        where: { botId: trade.botId },
        data: {
          cashBalance: { increment: payout },
          realizedPnl: { increment: pnl }
        }
      });
    }
    return tx.paperTrade.update({
      where: { id: tradeId },
      data: {
        status: "resolved",
        currentPrice: finalPrice,
        unrealizedPnl: 0,
        realizedPnl: pnl,
        resolvedAt: new Date(),
      },
    });
  });
}

/** Close a paper trade early at the current market price (rule-driven exit). */
export async function closePaperTrade(tradeId: string, exitPrice: number, _reason: string) {
  assertPaperOnly("closePaperTrade");
  const trade = await prisma.paperTrade.findUniqueOrThrow({ where: { id: tradeId } });
  if (trade.status !== "open") return trade;
  const pnl = computePnl(trade.entryPrice, exitPrice, trade.simulatedPositionSize);
  const payout = trade.simulatedPositionSize + pnl;

  return prisma.$transaction(async (tx) => {
    if (trade.botId !== "STANDARD") {
      await tx.botBankroll.update({
        where: { botId: trade.botId },
        data: {
          cashBalance: { increment: payout },
          realizedPnl: { increment: pnl }
        }
      });
    }
    return tx.paperTrade.update({
      where: { id: tradeId },
      data: {
        status: "closed",
        currentPrice: exitPrice,
        unrealizedPnl: 0,
        realizedPnl: pnl,
        closedAt: new Date(),
      },
    });
  });
}
