/**
 * score:trades — score all unscored ObservedTrades against active rules and
 * create DecisionJournal entries; open PaperTrades for paper_copy decisions.
 */

import { prisma } from "../src/lib/db";
import { getAdapter } from "../src/lib/adapters";
import { getActiveRules } from "../src/lib/rules";
import { scoreTrade } from "../src/lib/scoring/trade";
import { openPaperTrade } from "../src/lib/paper";
import { assertPaperOnly } from "../src/lib/safety";
import { log, logError } from "../src/lib/redact";
import { sendDiscord } from "../src/lib/discord";

async function main() {
  assertPaperOnly("score:trades");
  const adapter = getAdapter();
  const { rules, version } = await getActiveRules();

  const unscored = await prisma.observedTrade.findMany({
    where: { decisions: { none: {} } },
    orderBy: { timestamp: "desc" },
    take: Number(process.env.SCORE_BATCH_LIMIT ?? 400),
  });
  if (unscored.length === 0) {
    log("No unscored trades.");
    return;
  }

  log(`Scoring ${unscored.length} observed trades with rules v${version}…`);
  let copies = 0,
    watches = 0,
    skips = 0;

  for (const t of unscored) {
    const wallet = await prisma.walletProfile.findUnique({ where: { address: t.walletAddress } });
    if (!wallet) continue;

    let spread: number | undefined;
    let liquidity: number | undefined;
    let ttr: number | undefined;
    let currentPrice = t.detectedPrice;
    try {
      const m = await adapter.fetchMarket(t.marketId);
      spread = m.spread;
      liquidity = m.liquidity;
      ttr = m.timeToResolutionHours;
      const p = t.outcome === "NO" ? m.noPrice : m.yesPrice;
      if (p !== undefined) currentPrice = p;
    } catch (e) {
      logError(`Market fetch failed for ${t.marketId} — scoring with detection-time data. (${e instanceof Error ? e.message : e})`);
    }

    let catWinRate: number | undefined;
    try {
      const cats = JSON.parse(wallet.categoryStrengthsJson) as Record<string, { winRate: number }>;
      if (t.marketCategory && cats[t.marketCategory]) catWinRate = cats[t.marketCategory].winRate;
    } catch { /* ignore */ }

    const result = scoreTrade(
      {
        walletGlobalScore: wallet.globalScore,
        walletCategoryWinRate: catWinRate,
        walletEntryPrice: t.walletEntryPrice,
        currentPrice,
        spread,
        liquidity,
        timeToResolutionHours: ttr,
      },
      rules
    );

    const decision = await prisma.decisionJournal.create({
      data: {
        observedTradeId: t.id,
        walletAddress: t.walletAddress,
        marketId: t.marketId,
        decision: result.decision,
        copyScore: result.copyScore,
        confidence: result.confidence,
        reasonsJson: JSON.stringify(result.reasons),
        risksJson: JSON.stringify(result.risks),
        walletQualityScore: result.breakdown.walletQualityScore,
        roiScore: wallet.roi30d * 100,
        consistencyScore: wallet.consistencyScore,
        copyabilityScore: wallet.copyabilityScore,
        categoryFitScore: result.breakdown.categoryFitScore,
        entryTimingScore: result.breakdown.entryTimingScore,
        spreadScore: result.breakdown.spreadScore,
        liquidityScore: result.breakdown.liquidityScore,
        thesisScore: result.breakdown.thesisScore,
        simulatedPositionSize: result.simulatedPositionSize,
        ruleSetVersion: version,
        isDemo: t.isDemo,
      },
    });

    if (result.decision === "paper_copy" && result.simulatedPositionSize) {
      // Volume guards (rules v3): per-cycle and per-wallet-per-day copy caps.
      // Cap-hit signals are journaled as watchlist so they remain reviewable.
      let capRisk: string | undefined;
      if (copies >= rules.maxCopiesPerCycle) {
        capRisk = `per-cycle copy cap (${rules.maxCopiesPerCycle}) reached`;
      } else {
        const dayAgo = new Date(Date.now() - 86_400_000);
        const walletCopies = await prisma.paperTrade.count({
          where: { botId: "STANDARD", walletAddress: t.walletAddress, isDemo: t.isDemo, openedAt: { gte: dayAgo } },
        });
        if (walletCopies >= rules.maxCopiesPerWalletPerDay)
          capRisk = `wallet daily copy cap (${rules.maxCopiesPerWalletPerDay}) reached`;
      }
      if (capRisk) {
        await prisma.decisionJournal.update({
          where: { id: decision.id },
          data: {
            decision: "watchlist",
            risksJson: JSON.stringify([...result.risks, capRisk]),
            simulatedPositionSize: null,
          },
        });
        watches++;
        continue;
      }

      for (const botId of ["STANDARD", "BANKROLL_200"]) {
        try {
          // Phase 5: Directional Cross-Market Arb Simulation
          // Instead of assuming Polymarket is the cheapest venue, the Signal Brain evaluates 
          // whether to route the execution to Kalshi or PredictIt based on probability arbitrage rules.
          let executionVenue = "Polymarket";
          
          // Naive demonstration of logic routing:
          // In production, we evaluate delta between Kalshi API edge vs Polymarket.
          if (botId === "BANKROLL_200" && result.confidence > 0.8) {
             // Simulate that high-confidence trades are routed to Kalshi for better execution
             executionVenue = "Kalshi";
          }

          await openPaperTrade({
            botId,
            venue: executionVenue,
            decisionJournalId: decision.id,
            walletAddress: t.walletAddress,
            marketId: t.marketId,
            outcome: t.outcome,
            side: t.side,
            entryPrice: currentPrice,
            simulatedPositionSize: result.simulatedPositionSize,
            isDemo: t.isDemo,
          });
        } catch (e) {
          logError(`[${botId}] Skipped execution: ${e instanceof Error ? e.message : e}`);
        }
      }
      copies++;

      // Discord alert on new paper copies (live signals only, never demo data).
      if (!t.isDemo) {
        const isFirstEver =
          (await prisma.paperTrade.count({ where: { isDemo: false } })) === 1;
        await sendDiscord(
          [
            isFirstEver
              ? "🎉 **First real paper copy!** _(paper trading only — no real money)_"
              : "📈 **New paper copy** _(paper only)_",
            `**Market:** ${t.marketQuestion ?? t.marketId}`,
            `**Position:** ${t.side} ${t.outcome} @ ${currentPrice.toFixed(3)} — simulated $${result.simulatedPositionSize.toFixed(2)}`,
            `**Following:** \`${t.walletAddress.slice(0, 10)}…\` (wallet score ${wallet.globalScore.toFixed(0)})`,
            `**Copy score:** ${result.copyScore.toFixed(0)} (rules v${version}) — ${result.reasons[0] ?? ""}`,
          ].join("\n")
        );
      }
    } else if (result.decision === "watchlist") watches++;
    else skips++;
  }

  log(`Scoring complete: ${copies} paper copies, ${watches} watchlist, ${skips} skips.`);
}

main()
  .catch((e) => {
    logError("score:trades FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
