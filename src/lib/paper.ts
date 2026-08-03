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
    // Scale parent position size (0.25 to 20) down to (0.10 to 10)
    const percent = (size - 0.25) / (20.00 - 0.25);
    size = 0.10 + percent * (10.00 - 0.10);
  }

  size = clampPaperSize(size, botId);

  return prisma.$transaction(async (tx) => {
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
