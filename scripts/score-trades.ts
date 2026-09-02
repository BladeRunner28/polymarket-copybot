/**
 * score:trades — score all unscored ObservedTrades against active rules and
 * create DecisionJournal entries; open PaperTrades for paper_copy decisions.
 */

import { prisma } from "../src/lib/db";
import { getAdapter } from "../src/lib/adapters";
import { getActiveRules } from "../src/lib/rules";
import { scoreTrade } from "../src/lib/scoring/trade";
import { researchCategoryFor } from "../src/lib/research-categories";
import { aggregateSentimentForCategory } from "../src/lib/forecasting/sentiment";
import { openPaperTrade } from "../src/lib/paper";
import { c200HourPolicy, etHourNow } from "../src/lib/hour-policy";
import { assertPaperOnly } from "../src/lib/safety";
import { log, logError } from "../src/lib/redact";
import { sendDiscord } from "../src/lib/discord";
import { join } from "path";
import * as fs from "fs";
import {
  getBandLambda,
  computePremiumFactor,
  premiumRiskTag,
  loadPremiumCalibration,
} from "../src/lib/premium";

async function main() {
  assertPaperOnly("score:trades");
  const adapter = getAdapter();
  const { rules, version } = await getActiveRules();

  // Phase A (v38): Wang-Transform premium calibration table, refit monthly by
  // scripts/calibrate-premium.py into data/premium-calibration.json. Missing
  // or corrupt file → null → overlay safely off.
  const premiumCalibration = loadPremiumCalibration(
    join(__dirname, "..", "data", "premium-calibration.json")
  );

  // v37: Kalshi venue circuit breaker (2026-08-30 report) — the recent Kalshi
  // leg is the biggest loss center (closed −$223.80 over Aug 29–31). Computed
  // once per run; when the venue's realized PnL is below the breaker floor,
  // Kalshi routing is paused (stays Polymarket).
  const kalshiRealized =
    (await prisma.paperTrade.aggregate({
      where: { botId: "BANKROLL_200", venue: "Kalshi", status: { in: ["closed", "resolved"] } },
      _sum: { realizedPnl: true },
    }))._sum.realizedPnl ?? 0;

  // v40 risk gates (Homerun audit, 2026-08-31) — precomputed once per run:
  // daily loss limit (today's C-200 realized PnL) and gross exposure cap.
  const dayStart = new Date();
  dayStart.setHours(0, 0, 0, 0);
  const todayC200Pnl =
    (await prisma.paperTrade.aggregate({
      where: { botId: "BANKROLL_200", status: { in: ["closed", "resolved"] }, resolvedAt: { gte: dayStart } },
      _sum: { realizedPnl: true },
    }))._sum.realizedPnl ?? 0;
  const c200OpenNotional =
    (await prisma.paperTrade.aggregate({
      where: { botId: "BANKROLL_200", status: "open" },
      _sum: { simulatedPositionSize: true },
    }))._sum.simulatedPositionSize ?? 0;

  // v41 hour policy (2026-08-31 report, approved) - computed once per run:
  // 20:00 & 23:00 ET blackout, 10:00 ET 50% haircut (C-200 only; the STANDARD
  // long-dated book is unaffected). 21:00 ET stays open (z=+2.80 edge).
  const etHour = etHourNow();
  const hourPolicy = c200HourPolicy(etHour);

  // v41 portfolio risk gates (tuning review #12, 2026-09-01, approved) —
  // octagon-audit §4 additions on top of the per-market v40 gates:
  //   1) Drawdown gate: C-200 net worth = principal + realizedPnl + Σ open
  //      unrealized. Peak persisted in data/c200-drawdown.json (seeded from
  //      principal); trips when (peak − netWorth)/peak > maxDrawdownPct.
  //   2) Per-category concentration: max open C-200 positions per research
  //      category (researchCategoryFor). Unmapped markets are heterogeneous
  //      and uncapped. 0 = disabled.
  const DRAW_DOWN_FILE = join(__dirname, "..", "data", "c200-drawdown.json");
  const bankrollRow = await prisma.botBankroll.findUnique({ where: { botId: "BANKROLL_200" } });
  const openUnrealAgg = await prisma.paperTrade.aggregate({
    where: { botId: "BANKROLL_200", status: "open" },
    _sum: { unrealizedPnl: true },
  });
  const c200NetWorth =
    (bankrollRow?.principal ?? 0) +
    (bankrollRow?.realizedPnl ?? 0) +
    (openUnrealAgg._sum.unrealizedPnl ?? 0);
  let peakBankroll: number;
  try {
    peakBankroll = JSON.parse(fs.readFileSync(DRAW_DOWN_FILE, "utf-8")).peak ?? 0;
  } catch {
    peakBankroll = 0;
  }
  if (peakBankroll < (bankrollRow?.principal ?? 0)) peakBankroll = bankrollRow?.principal ?? 0;
  if (c200NetWorth > peakBankroll) {
    peakBankroll = c200NetWorth;
    fs.writeFileSync(
      DRAW_DOWN_FILE,
      JSON.stringify({ peak: peakBankroll, updatedAt: new Date().toISOString() })
    );
  }
  const c200DrawdownPct = peakBankroll > 0 ? Math.max(0, (peakBankroll - c200NetWorth) / peakBankroll) : 0;

  const c200OpenRows = await prisma.paperTrade.findMany({
    where: { botId: "BANKROLL_200", status: "open" },
    select: {
      decision: { select: { observedTrade: { select: { marketQuestion: true, marketCategory: true } } } },
    },
  });
  const c200CategoryCounts = new Map<string, number>();
  for (const row of c200OpenRows) {
    const ot = row.decision?.observedTrade;
    const cat = researchCategoryFor(ot?.marketQuestion, ot?.marketCategory);
    if (cat) c200CategoryCounts.set(cat, (c200CategoryCounts.get(cat) ?? 0) + 1);
  }

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
  let laneCopies = 0; // short-TTR lane copies (scoped to BANKROLL_200)

  for (const t of unscored) {
    const wallet = await prisma.walletProfile.findUnique({ where: { address: t.walletAddress } });
    if (!wallet) continue;
    
    // Phase 7: Swarm / Cluster Detection
    const oneHourAgo = new Date(Date.now() - 60 * 60 * 1000);
    const swarmCount = await prisma.observedTrade.count({
      where: {
        marketId: t.marketId,
        outcome: t.outcome,
        side: t.side,
        timestamp: { gte: oneHourAgo }
      }
    });

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

    // Phase 8: Regulatory/Political Sentiment (C-200 research bot).
    // v39 (Phase A2): when the evidence aggregation is enabled, the sentiment
    // layer is a calibrated Bayesian edge — delta = posterior − market in
    // probability points — over the category's 7d opinionated signals, instead
    // of the legacy single-signal fixed boost. Aggregation runs in YES-frame;
    // the edge is then signed by the trade's direction (NO/SELL flip it).
    // Neutral FR notices contribute nothing by construction.
    let regulatoryAgreement: number | undefined;
    let sentimentDelta: number | undefined;
    try {
      const researchCat = researchCategoryFor(t.marketQuestion, t.marketCategory);
      if (researchCat) {
        const sideSign = t.side === "SELL" ? -1 : 1;
        const outcomeSign = t.outcome === "NO" ? -1 : 1;
        if (rules.sentimentEvidenceEnabled === 1) {
          const yesPrice = t.outcome === "NO" ? 1 - currentPrice : currentPrice;
          const agg = await aggregateSentimentForCategory(researchCat, yesPrice);
          if (agg && agg.n >= rules.sentimentMinSignals) {
            sentimentDelta = sideSign * outcomeSign * agg.delta;
            // Measurement-first: log the full posterior path per decision so
            // outcomes can be compared against the legacy boost regime.
            log(
              `[SENTIMENT] ${t.marketId} cat=${researchCat} prior=${agg.prior.toFixed(3)} ` +
                `posterior=${agg.pAware.toFixed(3)} deltaYes=${agg.delta.toFixed(4)} ` +
                `n=${agg.n} clusters=${agg.clusterCount}`
            );
          }
        } else {
          // Legacy path: most recent *opinionated* signal: neutral (0.0) FR
          // notices shouldn't mask the last directional regulatory event.
          const recent = await prisma.regulatorySignal.findFirst({
            where: {
              marketCategory: researchCat,
              processedAt: { gte: new Date(Date.now() - 7 * 86_400_000) },
              OR: [{ sentimentScore: { gte: 0.3 } }, { sentimentScore: { lte: -0.3 } }],
            },
            orderBy: { processedAt: "desc" },
          });
          if (recent) {
            regulatoryAgreement = sideSign * outcomeSign * recent.sentimentScore;
          }
        }
      }
    } catch {
      // Sentiment lookup failure is non-fatal; score without the adjustment.
    }

    const result = scoreTrade(
      {
        walletGlobalScore: wallet.globalScore,
        walletCategoryWinRate: catWinRate,
        walletEntryPrice: t.walletEntryPrice,
        currentPrice,
        spread,
        liquidity,
        timeToResolutionHours: ttr,
        swarmCount,
        tradeSize: t.size,
        regulatoryAgreement,
        sentimentDelta,
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
      if (result.lane === "short_ttr") {
        // Lane copies have their own per-cycle budget, separate from the main funnel.
        if (laneCopies >= rules.shortTtrMaxCopiesPerCycle)
          capRisk = `short-TTR lane copy cap (${rules.shortTtrMaxCopiesPerCycle}) reached`;
      } else if (copies >= rules.maxCopiesPerCycle) {
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

      // v40 risk gates (Homerun audit, 2026-08-31): daily loss limit, gross
      // exposure cap, and per-token flash-crash circuit breaker. Journaled as
      // watchlist (reviewable) — same pattern as the volume guards.
      const riskGates: string[] = [];
      if (todayC200Pnl < rules.dailyLossLimitUsd)
        riskGates.push(`daily loss limit (today ${todayC200Pnl.toFixed(2)} < ${rules.dailyLossLimitUsd.toFixed(0)})`);
      if (c200OpenNotional + (result.simulatedPositionSize ?? 0) > rules.maxGrossExposureUsd)
        riskGates.push(
          `gross exposure cap (${(c200OpenNotional + (result.simulatedPositionSize ?? 0)).toFixed(2)} > ${rules.maxGrossExposureUsd})`
        );
      if (rules.tokenCircuitBreakerPct > 0) {
        const windowStart = new Date(Date.now() - rules.tokenCircuitBreakerWindowMin * 60_000);
        const cooldownStart = new Date(Date.now() - rules.tokenCircuitBreakerCooldownMin * 60_000);
        const trip = await prisma.tokenCircuitTrip.findFirst({
          where: { marketId: t.marketId, trippedAt: { gte: cooldownStart } },
        });
        if (trip) {
          riskGates.push(`token circuit breaker (tripped ${trip.reason})`);
        } else {
          const recent = await prisma.observedTrade.findMany({
            where: { marketId: t.marketId, timestamp: { gte: windowStart } },
            select: { detectedPrice: true },
          });
          const prices = recent.map((r) => r.detectedPrice).filter((p) => p > 0);
          if (prices.length >= 2) {
            const min = Math.min(...prices);
            const max = Math.max(...prices);
            const flash = (max - min) / Math.max(min, 0.001);
            if (flash > rules.tokenCircuitBreakerPct) {
              await prisma.tokenCircuitTrip.create({
                data: {
                  marketId: t.marketId,
                  reason: `flash move ${min.toFixed(3)} -> ${max.toFixed(3)} in ${rules.tokenCircuitBreakerWindowMin}m`,
                },
              });
              riskGates.push(
                `token circuit breaker (flash move ${(flash * 100).toFixed(0)}% in ${rules.tokenCircuitBreakerWindowMin}m)`
              );
            }
          }
        }
      }
      // v41: portfolio drawdown gate — halt new copies when the C-200 book is
      // more than maxDrawdownPct off its peak (octagon-audit §4).
      if (rules.maxDrawdownPct > 0 && c200DrawdownPct > rules.maxDrawdownPct) {
        riskGates.push(
          `drawdown gate (net worth $${c200NetWorth.toFixed(0)} vs peak $${peakBankroll.toFixed(0)} = ${(c200DrawdownPct * 100).toFixed(1)}% > ${(rules.maxDrawdownPct * 100).toFixed(0)}%)`
        );
      }
      // v41: per-category concentration gate — max open positions per
      // research category (unmapped "Other" is heterogeneous, uncapped).
      const tradeCat = researchCategoryFor(t.marketQuestion, t.marketCategory);
      if (rules.maxCategoryPositions > 0 && tradeCat) {
        const projected = (c200CategoryCounts.get(tradeCat) ?? 0) + 1;
        if (projected > rules.maxCategoryPositions) {
          riskGates.push(`category concentration (${tradeCat} would be ${projected}/${rules.maxCategoryPositions})`);
        } else {
          c200CategoryCounts.set(tradeCat, projected);
        }
      }
      if (riskGates.length > 0) {
        await prisma.decisionJournal.update({
          where: { id: decision.id },
          data: {
            decision: "watchlist",
            risksJson: JSON.stringify([...result.risks, ...riskGates]),
            simulatedPositionSize: null,
          },
        });
        log(`[RISK-GATE] ${t.marketId} ${riskGates.join(" | ")}`);
        watches++;
        continue;
      }

      const executionVenues: Set<string> = new Set();
      for (const botId of ["STANDARD", "BANKROLL_200"]) {
        // Short-TTR lane is scoped to the compounding bot (C-200) — STANDARD
        // keeps its long-dated book while the lane feeds the daily-PnL channel.
        if (result.lane === "short_ttr" && botId === "STANDARD") continue;
        // v29 capital recycling: cap the C-200 open book so capital cycles
        // through fresh 70–79 / short-TTR signals instead of being stranded
        // in stale long-dated positions.
        if (botId === "BANKROLL_200") {
          // v41: 20:00 ET (z=-3.31, -$91) and 23:00 ET (z=-2.90, -$98) are
          // significant drains - no new C-200 entries in those hours.
          if (hourPolicy.blackout) {
            log(`[BANKROLL_200] hour blackout ${etHour}:00 ET (significant drain) — skipping copy ${t.marketId}`);
            continue;
          }
          const openCount = await prisma.paperTrade.count({
            where: { botId: "BANKROLL_200", status: "open" },
          });
          if (openCount >= rules.maxOpenPositions) {
            log(`[BANKROLL_200] open-position cap (${rules.maxOpenPositions}) reached — skipping copy ${t.marketId}`);
            continue;
          }
        }

        try {
          // Phase 5: Directional Cross-Market Arb Simulation
          // Instead of assuming Polymarket is the cheapest venue, the Signal Brain evaluates 
          // whether to route the execution to Kalshi or PredictIt based on probability arbitrage rules.
          let executionVenue = "Polymarket";
          
          let positionSize = result.simulatedPositionSize;
          
          // v29: the ×3 high-confidence boost only applies BELOW the capped
          // band. Scores ≥ highScoreCapMin are the worst bucket in the Aug
          // data (score≥80: −$0.77/trade) — they keep the flat capped size
          // instead of being re-inflated here.
          // v37: Kalshi gate — route to Kalshi only when the copy clears the
          // venue score/confidence bars AND the venue's realized PnL is above
          // the circuit-breaker floor (currently tripped: realized < −$50 →
          // effectively Polymarket-only until the leg recovers).
          const kalshiEligible =
            result.copyScore >= rules.kalshiMinCopyScore &&
            result.confidence >= rules.kalshiMinConfidence &&
            kalshiRealized >= rules.kalshiCircuitBreakerPnl;
          if (botId === "BANKROLL_200" && result.confidence > 0.90 && result.copyScore < rules.highScoreCapMin) {
            // Apply recommended max allocation increase strictly for high-confidence trades
            // Expanding limits to 15% of bankroll for the best setups.
            if (positionSize) {
              positionSize = Math.min(positionSize * 3, 45.00); 
            }
            // Also prioritize Maker limit orders conceptually via cross-venue routing logic.
            if (kalshiEligible) executionVenue = "Kalshi";
          } else if (botId === "BANKROLL_200" && result.confidence > 0.8) {
             // Simulate that high-confidence trades are routed to Kalshi for better execution
             if (kalshiEligible) executionVenue = "Kalshi";
          }
          executionVenues.add(executionVenue);

          // Phase A (v38): Wang-calibrated premium overlay — measurement-first.
          // C-200 copies only; short-TTR lane copies are tagged but NOT
          // resized (the fixed lane size is the channel's design).
          let premiumRisk: string | undefined;
          if (botId === "BANKROLL_200" && rules.premiumOverlayEnabled === 1 && premiumCalibration && positionSize) {
            const lam =
              getBandLambda(currentPrice, premiumCalibration.bands) +
              (executionVenue === "Kalshi" ? premiumCalibration.venueOffsetKalshi : 0);
            premiumRisk = premiumRiskTag(lam, executionVenue);
            if (result.lane !== "short_ttr") {
              const orig = positionSize;
              positionSize = Math.min(
                positionSize *
                  computePremiumFactor(
                    lam,
                    rules.premiumOverlayK,
                    rules.premiumOverlayMinFactor,
                    rules.premiumOverlayMaxFactor
                  ),
                45.0
              );
              log(
                `[PREMIUM] ${t.marketId} venue=${executionVenue} entry=${currentPrice.toFixed(3)} λ̂=${lam.toFixed(3)} factor=${(positionSize / orig).toFixed(2)} size ${orig.toFixed(2)}→${positionSize.toFixed(2)}`
              );
            }
          }

          // v41: 10:00 ET is the single largest dollar drain (-$178, z=-1.74)
          // - 50% size haircut on C-200 copies.
          if (botId === "BANKROLL_200" && hourPolicy.sizeFactor !== 1 && positionSize) {
            log(
              `[BANKROLL_200] ${etHour}:00 ET size haircut ×${hourPolicy.sizeFactor} — ` +
                `${positionSize.toFixed(2)} → ${(positionSize * hourPolicy.sizeFactor).toFixed(2)}`
            );
            positionSize *= hourPolicy.sizeFactor;
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
            simulatedPositionSize: positionSize || 0.25,
            isDemo: t.isDemo,
          });

          // Phase A: surface the premium risk on the journal (reportable).
          if (premiumRisk) {
            await prisma.decisionJournal.update({
              where: { id: decision.id },
              data: { risksJson: JSON.stringify([...result.risks, premiumRisk]) },
            });
          }
        } catch (e) {
          logError(`[${botId}] Skipped execution: ${e instanceof Error ? e.message : e}`);
        }
      }
      copies++;
      if (result.lane === "short_ttr") {
        laneCopies++;
        log(
          `[SHORT-TTR lane] BANKROLL_200 copy: ${t.marketId} ` +
            `(ttr ${ttr !== undefined ? ttr.toFixed(1) + "h" : "?"}, score ${result.copyScore})`
        );
      }

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

  log(`Scoring complete: ${copies} paper copies (${laneCopies} short-TTR lane), ${watches} watchlist, ${skips} skips.`);
}

main()
  .catch((e) => {
    logError("score:trades FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
