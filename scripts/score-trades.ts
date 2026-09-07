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
import { openPaperTrade, mapBankroll200Size, applyKellyBandRails } from "../src/lib/paper";
import { assertPaperOnly, clampPaperSize } from "../src/lib/safety";
import { c200HourPolicy, etHourNow } from "../src/lib/hour-policy";
import { effectiveExposureCap } from "../src/lib/exposure-cap";
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
import { kellySizeForCopy } from "../src/lib/kelly";

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
  if (rules.kellyEnabled === 1 && !premiumCalibration) {
    // Fail-loud once per run: Kelly is enabled but the λ̂ table is unreadable —
    // the edge definition doesn't exist. Run continues on legacy sizing (the
    // per-copy Kelly gate below also requires the table).
    logError(
      "[KELLY] kellyEnabled=1 but premium-calibration.json missing/corrupt — Kelly OFF this run, legacy sizing (kellyEnabled stays 1 in rules)"
    );
  }

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
      where: {
        botId: "BANKROLL_200",
        status: { in: ["closed", "resolved"] },
        // TR-15 (2026-09-03): early-exit trades book realized PnL at closedAt
        // (resolvedAt stays NULL) — a resolvedAt-only filter made the daily
        // loss gate blind to exit-bleed days (e.g. 2026-08-31: −$239 early
        // exits read as +$53). A row matching both arms is counted once.
        OR: [{ resolvedAt: { gte: dayStart } }, { closedAt: { gte: dayStart } }],
      },
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
  // v49 Phase B: Kelly's available bankroll is the bot's FREE CASH. Fills
  // decrement cashBalance at booking (recordExecutionResult), so open
  // exposure is ALREADY excluded — subtracting c200OpenNotional again would
  // double-count and starve Kelly below its design cap (the $1,146 test book
  // in tests/kelly.test.ts is cashBalance scale, reconciled 2026-09-05).
  const c200AvailableBankroll = bankrollRow?.cashBalance ?? 0;
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

  // v46 (2026-09-03, approved): equity-linked gross-exposure cap —
  // $base + 50% × max(0, net worth − principal). Symmetric: shrinks when
  // equity falls back. Stays at the base while the book is below principal.
  const c200Principal = bankrollRow?.principal ?? 0;
  const c200ExposureCap = effectiveExposureCap(rules.maxGrossExposureUsd, c200NetWorth, c200Principal);

  const c200OpenRows = await prisma.paperTrade.findMany({
    where: { botId: "BANKROLL_200", status: "open" },
    select: {
      decision: { select: { observedTrade: { select: { marketQuestion: true, marketCategory: true } } } },
    },
  });
  const c200CategoryCounts = new Map<string, number>();
  const c200SlugCounts = new Map<string, number>(); // v45: raw marketCategory slug counts
  for (const row of c200OpenRows) {
    const ot = row.decision?.observedTrade;
    const cat = researchCategoryFor(ot?.marketQuestion, ot?.marketCategory);
    if (cat) c200CategoryCounts.set(cat, (c200CategoryCounts.get(cat) ?? 0) + 1);
    if (ot?.marketCategory) c200SlugCounts.set(ot.marketCategory, (c200SlugCounts.get(ot.marketCategory) ?? 0) + 1);
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
  // TR-14 (2026-09-03): running gross-exposure total for the C-200 book.
  // Seeded from the cycle-start snapshot and incremented per booked copy so
  // candidates later in THIS run see earlier acceptances (fixes per-cycle
  // overshoot past maxGrossExposureUsd).
  let c200RunningExposure = c200OpenNotional;

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
      if (c200RunningExposure + (result.simulatedPositionSize ?? 0) > c200ExposureCap)
        riskGates.push(
          `gross exposure cap (${(c200RunningExposure + (result.simulatedPositionSize ?? 0)).toFixed(2)} > ${c200ExposureCap.toFixed(0)} = $${rules.maxGrossExposureUsd} base + 50% above principal)`
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
        // v44 (tuning review #13, approved): hour blackout now covers BOTH
        // books — 20:00/23:00 ET drains (z=−2.99/−2.42) cost STANDARD too
        // (window-opened −$622 worst on record); C-200-only gating left
        // STANDARD exposed. The 10:00 ET haircut stays C-200-only.
        if (hourPolicy.blackout) {
          log(`[${botId}] hour blackout ${etHour}:00 ET (significant drain) — skipping copy ${t.marketId}`);
          continue;
        }
        // Short-TTR lane is scoped to the compounding bot (C-200) — STANDARD
        // keeps its long-dated book while the lane feeds the daily-PnL channel.
        if (result.lane === "short_ttr" && botId === "STANDARD") continue;
        // v29 capital recycling: cap the C-200 open book so capital cycles
        // through fresh 70–79 / short-TTR signals instead of being stranded
        // in stale long-dated positions.
        if (botId === "BANKROLL_200") {
          const openCount = await prisma.paperTrade.count({
            where: { botId: "BANKROLL_200", status: "open" },
          });
          if (openCount >= rules.maxOpenPositions) {
            log(`[BANKROLL_200] open-position cap (${rules.maxOpenPositions}) reached — skipping copy ${t.marketId}`);
            continue;
          }
        }

        // v45 (execution-leak Step 2, approved): per-bot market-category
        // blacklist — the structural −EV slug set (lol/cs2/nfl/… lose for
        // BOTH bots regardless of venue; verified 2026-09-03). Per-bot because
        // dota2/elon are C-200-positive while STANDARD-negative. Question-
        // fragment slugs (what/of/the/where/which) are NOT blacklisted — they
        // wrap hundreds of real markets each. Per-bot gate: log + continue
        // (journal untouched — the sibling bot in this loop may still copy).
        const botBlacklist =
          botId === "BANKROLL_200" ? (rules.c200Blacklist ?? []) : (rules.standardBlacklist ?? []);
        if (t.marketCategory && botBlacklist.includes(t.marketCategory)) {
          log(`[${botId}] v45 blacklist category "${t.marketCategory}" — skipping copy ${t.marketId}`);
          continue;
        }

        // v45: per-market-slug open-position cap for C-200 — closes the hole
        // where the v41 research-category gate maps esports to uncapped
        // "Other". Counts open C-200 positions per raw marketCategory slug
        // (lol/cs2/…); 0 = disabled.
        if (botId === "BANKROLL_200" && rules.maxMarketSlugPositions > 0 && t.marketCategory) {
          const slugOpen = (c200SlugCounts.get(t.marketCategory) ?? 0) + 1;
          if (slugOpen > rules.maxMarketSlugPositions) {
            log(
              `[BANKROLL_200] v45 market-slug cap (${t.marketCategory} would be ${slugOpen}/${rules.maxMarketSlugPositions}) — skipping copy ${t.marketId}`
            );
            continue;
          }
          c200SlugCounts.set(t.marketCategory, slugOpen);
        }

        try {
          // Phase 5: Directional Cross-Market Arb Simulation
          // Instead of assuming Polymarket is the cheapest venue, the Signal Brain evaluates 
          // whether to route the execution to Kalshi or PredictIt based on probability arbitrage rules.
          let executionVenue = "Polymarket";
          let positionSize = result.simulatedPositionSize;
          let premiumRisk: string | undefined;
          let kellySized = false; // v49 Phase B: Kelly computed this copy's size

          // v37: Kalshi gate — route to Kalshi only when the copy clears the
          // venue score/confidence bars AND the venue's realized PnL is above
          // the circuit-breaker floor (currently tripped: realized < −$50 →
          // effectively Polymarket-only until the leg recovers). Single venue
          // decision (legacy two-arm routing collapsed: conf>0.90 and
          // 0.8<conf≤0.90 both routed Kalshi when eligible — identical here).
          const kalshiEligible =
            result.copyScore >= rules.kalshiMinCopyScore &&
            result.confidence >= rules.kalshiMinConfidence &&
            kalshiRealized >= rules.kalshiCircuitBreakerPnl;
          if (botId === "BANKROLL_200" && result.confidence > 0.8 && kalshiEligible) {
            // High-confidence C-200 trades prefer the Kalshi venue for better
            // execution when the venue breaker permits.
            executionVenue = "Kalshi";
          }
          executionVenues.add(executionVenue);

          // v49 Phase B (drafts/phase-b-kelly-design.md): Kelly sizing for
          // C-200 main-lane copies — the calibrated edge (band λ̂, + Kalshi
          // venue offset) decides size AND skip. Replaces the ×3 confidence
          // boost + v38 premium-overlay resize; the paper.ts band remap is
          // bypassed at open for Kelly-sized copies (no double sizing).
          // Short-TTR lane keeps its fixed size (channel design); STANDARD
          // keeps legacy sizing; kellyEnabled=0 → legacy path untouched.
          const isKellyCandidate =
            botId === "BANKROLL_200" && result.lane !== "short_ttr" && rules.kellyEnabled === 1;
          if (isKellyCandidate && premiumCalibration) {
            const lam =
              getBandLambda(currentPrice, premiumCalibration.bands) +
              (executionVenue === "Kalshi" ? premiumCalibration.venueOffsetKalshi : 0);
            const kelly = kellySizeForCopy({
              price: currentPrice,
              outcome: t.outcome as "YES" | "NO",
              lambda: lam,
              side: t.side as "BUY" | "SELL",
              availableBankroll: c200AvailableBankroll,
              fraction: rules.kellyFraction,
              maxBankrollPct: rules.kellyMaxBankrollPct,
              maxSizeUsd: rules.kellyMaxSizeUsd,
              minBetUsd: rules.kellyMinBetUsd,
              minEdgePct: rules.kellyMinEdgePct,
            });
            const bandLabel = (() => {
              for (const b of premiumCalibration.bands) {
                if (currentPrice >= b.lo && currentPrice < b.hi) return `[${b.lo},${b.hi})`;
              }
              const last = premiumCalibration.bands[premiumCalibration.bands.length - 1];
              return last ? `[${last.lo},${last.hi})` : "?";
            })();
            if (kelly.skip) {
              log(
                `[KELLY] ${t.marketId} band=${bandLabel} λ̂=${lam.toFixed(3)} q=— p=${currentPrice.toFixed(3)} f*=0 avail=$${c200AvailableBankroll.toFixed(0)} size=$0 SKIP ${kelly.reason}`
              );
              continue; // C-200 main-lane only — the STANDARD leg is unaffected
            }
            // v51 (2026-09-07 report changes 1+2, user-approved — explicit
            // Kelly-window freeze override): band rails on Kelly admits so the
            // Kelly path cannot contradict the band map (paper.ts) on the two
            // regime-robust findings while λ̂ tables sit between refits. Dead
            // zone [0.40,0.60): cap at the legacy-equivalent (×0.25 map) size;
            // long-shot <0.20: floor at the legacy-equivalent (×2.0 map) size.
            // Inert while λ̂ keeps the dead zone at f*≤0 and <0.20 at −0.91.
            const legacyEquiv = clampPaperSize(mapBankroll200Size(result.simulatedPositionSize, currentPrice));
            const railedSize = applyKellyBandRails(kelly.sizeUsd, legacyEquiv, currentPrice);
            if (railedSize !== kelly.sizeUsd) {
              log(
                `[KELLY-RAIL] ${t.marketId} band=${bandLabel} p=${currentPrice.toFixed(3)} ` +
                  `${currentPrice >= 0.4 && currentPrice < 0.6 ? "dead-zone cap" : "long-shot floor"}: ` +
                  `kelly $${kelly.sizeUsd.toFixed(2)} vs legacy-equiv $${legacyEquiv.toFixed(2)} → $${railedSize.toFixed(2)}`
              );
            }
            positionSize = railedSize;
            kellySized = true;
            // Journal tag retained on Kelly-sized copies (design §6) — the
            // premium λ̂ is the same quantity that drove the sizing.
            premiumRisk = premiumRiskTag(lam, executionVenue);
            log(
              `[KELLY] ${t.marketId} band=${bandLabel} λ̂=${lam.toFixed(3)} q=${kelly.q.toFixed(3)} p=${currentPrice.toFixed(3)} f*=${kelly.fStarApplied.toFixed(4)} avail=$${c200AvailableBankroll.toFixed(0)} size=$${kelly.sizeUsd.toFixed(2)}`
            );
          }

          // v29: the ×3 high-confidence boost only applies BELOW the capped
          // band. Scores ≥ highScoreCapMin are the worst bucket in the Aug
          // data (score≥80: −$0.77/trade) — they keep the flat capped size
          // instead of being re-inflated here. Bypassed on Kelly-sized copies:
          // Kelly already scales by edge (doubling would re-inflate the
          // long-shot band Kelly just sized).
          if (
            !kellySized &&
            botId === "BANKROLL_200" &&
            result.confidence > 0.90 &&
            result.copyScore < rules.highScoreCapMin
          ) {
            // Apply recommended max allocation increase strictly for high-confidence trades
            // Expanding limits to 15% of bankroll for the best setups.
            if (positionSize) {
              positionSize = Math.min(positionSize * 3, 45.00);
            }
          }

          // Phase A (v38): Wang-calibrated premium overlay — measurement-first.
          // C-200 copies only; short-TTR lane copies are tagged but NOT
          // resized (the fixed lane size is the channel's design). Skipped on
          // Kelly-sized copies (v49): Kelly already sized from the same λ̂ —
          // applying the overlay again would double-apply the premium signal.
          // premiumRisk was set by the Kelly block when kellySized.
          if (botId === "BANKROLL_200" && rules.premiumOverlayEnabled === 1 && premiumCalibration && positionSize && !kellySized) {
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

          // v44 (tuning review #13, approved): STANDARD high-side entry cap —
          // 0.80–1.01 is the worst band (z=−2.50, p=0.013). Enforced per-leg
          // here, NOT via the shared maxEntryPrice rule (that gate is
          // symmetric [1−max, max]; lowering it would kill the <0.15 long-shot
          // edge). C-200 de-risks ≥0.60 via band sizing instead.
          if (botId === "STANDARD" && rules.standardMaxEntryPrice > 0 && currentPrice > rules.standardMaxEntryPrice) {
            log(`[STANDARD] high-entry cap (${currentPrice.toFixed(3)} > ${rules.standardMaxEntryPrice.toFixed(2)}) — skipping copy ${t.marketId}`);
            continue;
          }

          // v47 (2026-09-03 daily report, approved): C-200 high-side entry
          // cap — hard-cap new copy entries at ≤0.80 (the z=−2.48 premium
          // drag band, −8.5pp excess on 0.80–1.01). Same per-leg pattern:
          // the symmetric maxEntryPrice must stay at 0.95 to preserve the
          // <0.20 long-shot edge (z=+4.05). Applies to main + short-TTR lane.
          if (botId === "BANKROLL_200" && rules.c200MaxEntryPrice > 0 && currentPrice > rules.c200MaxEntryPrice) {
            log(`[BANKROLL_200] high-entry cap (${currentPrice.toFixed(3)} > ${rules.c200MaxEntryPrice.toFixed(2)}) — skipping copy ${t.marketId}`);
            continue;
          }

          await openPaperTrade({
            botId,
            venue: executionVenue,
            decisionJournalId: decision.id,
            walletAddress: t.walletAddress,
            marketId: t.marketId,
            marketQuestion: t.marketQuestion, // TR-16: Kalshi ticker resolution
            outcome: t.outcome,
            side: t.side,
            entryPrice: currentPrice,
            simulatedPositionSize: positionSize || 0.25,
            isDemo: t.isDemo,
            // v49 Phase B: Kelly-sized copies bypass the v41 band remap and
            // clamp at kellyMaxSizeUsd (executor cap override) — legacy path
            // (kellyEnabled=0) passes undefined and stays byte-identical.
            kelly: kellySized ? { maxSizeUsd: rules.kellyMaxSizeUsd } : undefined,
          });

          // TR-14 (2026-09-03): count the booked C-200 size against the running
          // exposure total (only on success; the catch below leaves it untouched).
          if (botId === "BANKROLL_200") c200RunningExposure += positionSize || 0.25;

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
