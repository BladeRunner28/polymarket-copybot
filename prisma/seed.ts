/**
 * Seed script — DEMO DATA ONLY. Everything created here is flagged
 * isDemo=true and labeled "[DEMO]" so it can never be confused with live
 * research data. Gives the dashboard something to render on first run.
 */

import { PrismaClient } from "@prisma/client";
import { DemoAdapter } from "../src/lib/adapters/demo";
import { DEFAULT_RULES } from "../src/lib/rules";
import { scoreWallet, walletStatus } from "../src/lib/scoring/wallet";
import { scoreTrade } from "../src/lib/scoring/trade";
import { computePnl } from "../src/lib/paper";

const prisma = new PrismaClient();

async function main() {
  console.log("Seeding DEMO data (all rows flagged isDemo / labeled [DEMO])…");

  // Rules v1
  const existingRules = await prisma.ruleSet.findFirst({ where: { active: true } });
  if (!existingRules) {
    await prisma.ruleSet.create({
      data: { version: 1, active: true, rulesJson: JSON.stringify(DEFAULT_RULES) },
    });
  }
  const rules = DEFAULT_RULES;

  const demo = new DemoAdapter();
  const leaderboard = await demo.fetchLeaderboard(50);

  await prisma.leaderboardScan.create({
    data: {
      source: "demo",
      walletCount: leaderboard.length,
      lookbackDays: 30,
      rawSummaryJson: JSON.stringify({ note: "DEMO seed data", top10: leaderboard.slice(0, 10) }),
    },
  });

  let paperCount = 0;
  for (const entry of leaderboard) {
    const trades = await demo.fetchWalletActivity(entry.address, 30);
    const score = scoreWallet(trades, rules);
    const { status, reason } = walletStatus(score, rules);

    const wallet = await prisma.walletProfile.upsert({
      where: { address: entry.address },
      create: {
        address: entry.address,
        label: entry.label,
        sourceRank: entry.rank,
        status,
        isDemo: true,
        roi30d: score.roi30d,
        consistencyScore: score.consistencyScore,
        copyabilityScore: score.copyabilityScore,
        oneHitWonderPenalty: score.oneHitWonderPenalty,
        globalScore: score.globalScore,
        bestCategory: score.bestCategory,
        categoryStrengthsJson: JSON.stringify(score.categoryStrengths),
        averageTradeSize: score.averageTradeSize,
        tradeCount30d: score.tradeCount30d,
        resolvedTradeCount30d: score.resolvedTradeCount30d,
        winRate30d: score.winRate30d,
        averageLiquidity: score.averageLiquidity,
        averageSpread: score.averageSpread,
        copyabilityNotes: `${reason}. ${score.copyabilityNotes}`,
        riskNotes: score.riskNotes,
        lastScannedAt: new Date(),
      },
      update: {},
    });

    // Seed observed trades + decisions + paper trades for tracked wallets
    if (status !== "track") continue;
    for (const t of trades.slice(0, 4)) {
      const market = await demo.fetchMarket(t.marketId);
      const currentPrice = (t.outcome === "NO" ? market.noPrice : market.yesPrice) ?? t.price;

      const observed = await prisma.observedTrade.create({
        data: {
          walletAddress: wallet.address,
          marketId: t.marketId,
          marketQuestion: t.marketQuestion,
          marketCategory: t.marketCategory,
          outcome: t.outcome,
          side: t.side,
          walletEntryPrice: t.price,
          detectedPrice: currentPrice,
          size: t.size,
          timestamp: t.timestamp,
          isDemo: true,
        },
      }).catch(() => null);
      if (!observed) continue;

      await prisma.marketSnapshot.create({
        data: {
          marketId: market.marketId,
          question: market.question,
          category: market.category,
          yesPrice: market.yesPrice,
          noPrice: market.noPrice,
          bestBid: market.bestBid,
          bestAsk: market.bestAsk,
          spread: market.spread,
          liquidity: market.liquidity,
          volume: market.volume,
          timeToResolution: market.timeToResolutionHours,
          isDemo: true,
        },
      });

      const result = scoreTrade(
        {
          walletGlobalScore: score.globalScore,
          walletEntryPrice: t.price,
          currentPrice,
          spread: market.spread,
          liquidity: market.liquidity,
          timeToResolutionHours: market.timeToResolutionHours,
        },
        rules
      );

      const decision = await prisma.decisionJournal.create({
        data: {
          observedTradeId: observed.id,
          walletAddress: wallet.address,
          marketId: t.marketId,
          decision: result.decision,
          copyScore: result.copyScore,
          confidence: result.confidence,
          reasonsJson: JSON.stringify(result.reasons),
          risksJson: JSON.stringify(result.risks),
          walletQualityScore: result.breakdown.walletQualityScore,
          categoryFitScore: result.breakdown.categoryFitScore,
          entryTimingScore: result.breakdown.entryTimingScore,
          spreadScore: result.breakdown.spreadScore,
          liquidityScore: result.breakdown.liquidityScore,
          thesisScore: result.breakdown.thesisScore,
          simulatedPositionSize: result.simulatedPositionSize,
          ruleSetVersion: 1,
          isDemo: true,
        },
      });

      if (result.decision === "paper_copy" && result.simulatedPositionSize) {
        const resolved = market.resolved ?? false;
        const won = resolved ? market.winningOutcome === t.outcome : undefined;
        const finalPrice = resolved ? (won ? 1 : 0) : currentPrice;
        const pnl = computePnl(currentPrice, finalPrice, result.simulatedPositionSize);
        const pt = await prisma.paperTrade.create({
          data: {
            decisionJournalId: decision.id,
            walletAddress: wallet.address,
            marketId: t.marketId,
            outcome: t.outcome,
            side: t.side,
            entryPrice: currentPrice,
            currentPrice: finalPrice,
            simulatedPositionSize: result.simulatedPositionSize,
            unrealizedPnl: resolved ? 0 : pnl,
            realizedPnl: resolved ? pnl : null,
            status: resolved ? "resolved" : "open",
            resolvedAt: resolved ? new Date() : null,
            isDemo: true,
            openedAt: t.timestamp,
          },
        });
        // A few hourly snapshots
        for (let h = 4; h >= 1; h--) {
          const drift = currentPrice + (finalPrice - currentPrice) * ((4 - h) / 4);
          await prisma.pnlSnapshot.create({
            data: {
              paperTradeId: pt.id,
              price: drift,
              pnl: computePnl(currentPrice, drift, result.simulatedPositionSize),
              collectedAt: new Date(Date.now() - h * 3600_000),
            },
          });
        }
        if (resolved) {
          await prisma.outcomeReview.create({
            data: {
              decisionJournalId: decision.id,
              paperTradeId: pt.id,
              finalOutcome: market.winningOutcome,
              simulatedPnl: pnl,
              wasDecisionGood: pnl > 0,
              lessonsJson: JSON.stringify([
                pnl > 0 ? "[DEMO] Copy won — filters aligned" : "[DEMO] Copy lost — review entry drift",
              ]),
            },
          });
        }
        paperCount++;
      }
    }
  }

  const wallets = await prisma.walletProfile.count();
  const decisions = await prisma.decisionJournal.count();
  console.log(
    `Demo seed complete: ${wallets} wallets, ${decisions} decisions, ${paperCount} paper trades.`
  );
}

main()
  .catch((e) => {
    console.error("Seed failed:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
