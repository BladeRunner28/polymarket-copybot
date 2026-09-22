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
import { c200HourPolicy, etHourNow, isHourBlackedOut } from "../src/lib/hour-policy";
import { effectiveExposureCap, marketCapDecision, walletCapDecision, isPortfolioGate } from "../src/lib/exposure-cap";
import { readWalletCapBaseline, baselineFor } from "../src/lib/wallet-cap-basis";
import { applyBandSizeFactor } from "../src/lib/band-size";
import { appendWalletCapShadow } from "../src/lib/shadow-wallet-cap";
import { appendLowConfShadow } from "../src/lib/shadow-lowconf";
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
import { appendShadowRow, SHADOW_MAX_PRICE } from "../src/lib/shadow-longshot";
import { appendDriftShadow } from "../src/lib/shadow-drift";
import { copyWalletAddresses, MAX_TRACKED } from "../src/lib/wallet-universe";

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
  // v53 (tuning review #21 rec 2, user-approved 2026-09-11): shadow BOTH
  // drawdown definitions for the Sep 15 octagon §4 decision — MTM (the current
  // gate basis: peak ratchets on unrealized marks, the Sep 7/8 freeze
  // mechanism) vs realized-only (principal + ledger realized). Log-only; the
  // gate stays on MTM until the refit. State file keeps both peaks + any note.
  // 2026-09-15 tuning review #26 rec 2 (user-approved): the basis is DECLARED in
  // data/c200-drawdown.json (`basis` + `peakRule`) instead of implied, and every
  // consumer — the drawdown gate, the equity-linked exposure cap, and both log
  // lines — derives from that one value. Before this, the gate and the cap both
  // silently used MTM while the state file said nothing, so the same book read
  // 88.0% of cap on MTM vs 130.0% on realized-only with no way to tell which one
  // was in force. Legacy files with no `basis` keep the historical MTM behavior.
  type DdBasis = "mtm" | "realized" | "min";
  let drawdownState: {
    peak?: number;
    realizedPeak?: number;
    note?: string;
    updatedAt?: string;
    basis?: DdBasis;
    peakRule?: string;
    basisDeclaredAt?: string;
  } = {};
  try {
    drawdownState = JSON.parse(fs.readFileSync(DRAW_DOWN_FILE, "utf-8"));
  } catch {
    drawdownState = {};
  }
  const principal = bankrollRow?.principal ?? 0;
  // Declared basis: the RULESET is the source of truth (v56, #29 rec 3) and the
  // state file is the fallback for rulesets that predate the field, then "mtm"
  // (legacy). Written back to the file below so the two never disagree.
  const ddBasis: DdBasis = ((rules.ddBasis || undefined) as DdBasis) ?? drawdownState.basis ?? "mtm";
  let peakBankroll = drawdownState.peak ?? 0;
  if (peakBankroll < principal) peakBankroll = principal;
  const realizedOnlyNW = principal + (bankrollRow?.realizedPnl ?? 0);
  let realizedPeak = drawdownState.realizedPeak ?? principal;
  if (realizedPeak < principal) realizedPeak = principal;
  if (realizedOnlyNW > realizedPeak) realizedPeak = realizedOnlyNW;
  let ddStateDirty = false;
  if (c200NetWorth > peakBankroll) {
    peakBankroll = c200NetWorth;
    ddStateDirty = true;
  }
  if (drawdownState.realizedPeak !== realizedPeak) ddStateDirty = true;
  if (ddStateDirty || !drawdownState.basis) {
    fs.writeFileSync(
      DRAW_DOWN_FILE,
      JSON.stringify({
        ...drawdownState,
        peak: peakBankroll,
        realizedPeak,
        basis: ddBasis,
        peakRule:
          drawdownState.peakRule ??
          "peak ratchets on the declared basis only; a reset is a deliberate act — record note + basisDeclaredAt with it",
        basisDeclaredAt: drawdownState.basisDeclaredAt ?? new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      })
    );
  }
  const c200DrawdownPct = peakBankroll > 0 ? Math.max(0, (peakBankroll - c200NetWorth) / peakBankroll) : 0;
  const realizedOnlyDdPct =
    realizedPeak > 0 ? Math.max(0, (realizedPeak - realizedOnlyNW) / realizedPeak) : 0;

  const basisNetWorth =
    ddBasis === "mtm" ? c200NetWorth : ddBasis === "realized" ? realizedOnlyNW : Math.min(c200NetWorth, realizedOnlyNW);
  const basisPeak =
    ddBasis === "mtm" ? peakBankroll : ddBasis === "realized" ? realizedPeak : Math.min(peakBankroll, realizedPeak);
  const basisDrawdownPct = basisPeak > 0 ? Math.max(0, (basisPeak - basisNetWorth) / basisPeak) : 0;
  log(
    `[DRAWDOWN-SHADOW] basis=${ddBasis} ${(basisDrawdownPct * 100).toFixed(1)}% (peak $${basisPeak.toFixed(0)}, NW $${basisNetWorth.toFixed(0)}) | ` +
      `MTM ${(c200DrawdownPct * 100).toFixed(1)}% (peak $${peakBankroll.toFixed(0)}, NW $${c200NetWorth.toFixed(0)}) ` +
      `vs realized-only ${(realizedOnlyDdPct * 100).toFixed(1)}% (realized peak $${realizedPeak.toFixed(0)}, realized NW $${realizedOnlyNW.toFixed(0)})`
  );

  // v46 (2026-09-03, approved): equity-linked gross-exposure cap —
  // $base + 50% × max(0, net worth − principal). Symmetric: shrinks when
  // equity falls back. Stays at the base while the book is below principal.
  const c200Principal = bankrollRow?.principal ?? 0;
  const c200ExposureCap = effectiveExposureCap(rules.maxGrossExposureUsd, basisNetWorth, c200Principal);
  // 2026-09-16 tuning review #27 rec 1 (user-approved): shadow the cap under the
  // OTHER basis. The cap is MTM-linked, so the +$1.2k of unrealized marks on the
  // book inflate it; if those marks revert, the same book sits far above the
  // realized-only cap and the gate freezes entries with no warning. Log both
  // every run so the gap is visible before it binds.
  const realizedOnlyExposureCap = effectiveExposureCap(rules.maxGrossExposureUsd, realizedOnlyNW, c200Principal);
  // Cap shadow (rec 1) — unconditional, logged next to the drawdown shadow.
  log(
    `[CAP-SHADOW] declared(${ddBasis}) cap $${c200ExposureCap.toFixed(0)} vs realized-only cap $${realizedOnlyExposureCap.toFixed(0)} ` +
      `(base $${rules.maxGrossExposureUsd} + 50% above principal $${c200Principal.toFixed(0)}) | ` +
      `NW ${ddBasis} $${basisNetWorth.toFixed(0)} / realized-only $${realizedOnlyNW.toFixed(0)} | ` +
      `gap $${(c200ExposureCap - realizedOnlyExposureCap).toFixed(0)}`
  );

  const c200OpenRows = await prisma.paperTrade.findMany({
    where: { botId: "BANKROLL_200", status: "open" },
    select: {
      marketId: true,
      walletAddress: true, // v58: per-wallet ceiling input
      simulatedPositionSize: true,
      decision: { select: { observedTrade: { select: { marketQuestion: true, marketCategory: true } } } },
    },
  });
  // v55 per-market ceiling: current legs + notional per marketId.
  const c200MarketLegs = new Map<string, number>();
  const c200MarketNotional = new Map<string, number>();
  for (const row of c200OpenRows) {
    c200MarketLegs.set(row.marketId, (c200MarketLegs.get(row.marketId) ?? 0) + 1);
    c200MarketNotional.set(
      row.marketId,
      (c200MarketNotional.get(row.marketId) ?? 0) + (row.simulatedPositionSize ?? 0)
    );
  }
  const c200MarketNotionalCap =
    rules.maxMarketNotionalPctOfCap > 0 ? rules.maxMarketNotionalPctOfCap * c200ExposureCap : 0;
  // v58 (tuning review #30 rec 1, user-approved): per-WALLET notional on the
  // C-200 book, and the ceiling it is measured against. Same fraction-of-cap
  // form as v55 so the rail scales with the equity-linked cap instead of
  // becoming non-binding the moment the book grows (the way v55's fixed
  // $125.12 ceiling did).
  const c200WalletNotional = new Map<string, number>();
  for (const row of c200OpenRows) {
    c200WalletNotional.set(
      row.walletAddress,
      (c200WalletNotional.get(row.walletAddress) ?? 0) + (row.simulatedPositionSize ?? 0)
    );
  }
  const c200WalletNotionalCap =
    rules.maxWalletNotionalPctOfCap > 0 ? rules.maxWalletNotionalPctOfCap * c200ExposureCap : 0;
  // v59 (2026-09-19 daily report rec 2, user-approved): grandfather the
  // pre-activation stock. Under "stock" the ceiling is the wallet's whole open
  // notional, so a wallet already above it is frozen outright (the top wallet
  // held $993.66 against a $431 ceiling = 2.3x, 109 vetoes in 15h) instead of
  // being gated gradually. Under "delta" the ceiling becomes
  // baseline(wallet) + pct x cap: the wallet keeps its existing book and may add
  // at most one ceiling of NEW notional, which is the rail's purpose (no wallet
  // exceeds its activation notional by more than the ceiling) without the
  // standstill it was never meant to impose. Baseline is a frozen snapshot
  // (data/wallet-cap-baseline.json); a wallet first seen after activation reads 0
  // and gets the plain ceiling.
  const walletCapBasis = rules.walletCapBasis === "delta" ? "delta" : "stock";
  const walletCapBaseline = walletCapBasis === "delta" ? readWalletCapBaseline() : null;
  const c200CategoryCounts = new Map<string, number>();
  const c200SlugCounts = new Map<string, number>(); // v45: raw marketCategory slug counts
  for (const row of c200OpenRows) {
    const ot = row.decision?.observedTrade;
    const cat = researchCategoryFor(ot?.marketQuestion, ot?.marketCategory);
    if (cat) c200CategoryCounts.set(cat, (c200CategoryCounts.get(cat) ?? 0) + 1);
    if (ot?.marketCategory) c200SlugCounts.set(ot.marketCategory, (c200SlugCounts.get(ot.marketCategory) ?? 0) + 1);
  }

  // v61 (tuning review #33 rec 1, user-approved 2026-09-22): observation-only
  // rows are measurement, not candidates — they are never scored, never
  // journaled and never copied. Excluding them here keeps the skip histogram and
  // the copy funnel exactly as they were before the observation sweep was added.
  const unscored = await prisma.observedTrade.findMany({
    where: { decisions: { none: {} }, observationOnly: false },
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
  let shadowLogged = 0; // v53: sub-0.20 shadow-ladder candidates logged
  let driftShadowLogged = 0; // 2026-09-16 Change 2: late-drift gate counterfactuals logged
  // change 2 (2026-09-20 daily report, approved): would-have entries the CONFIDENCE
  // gate rejected. minConfidence is the funnel's biggest blocker by mention count and
  // was unpriceable — skip rows stored confidence=0, so no outcome could be joined to
  // the bar. Write-only; a threshold change still needs the Oct 8 window close.
  let lowConfShadowLogged = 0;
  // #29 rec 2 (2026-09-19, approved): count candidates blocked by a PORTFOLIO gate
  // (drawdown / gross exposure). These fire BEFORE the per-bot leg loop, so when
  // they block everything the run produces no copies, no leg blocks and no signal
  // that anything is wrong — the Sep 16-18 freeze ran 39.7h before a human noticed.
  let portfolioGateBlocks = 0;
  // TR-14 (2026-09-03): running gross-exposure total for the C-200 book.
  // Seeded from the cycle-start snapshot and incremented per booked copy so
  // candidates later in THIS run see earlier acceptances (fixes per-cycle
  // overshoot past maxGrossExposureUsd).
  let c200RunningExposure = c200OpenNotional;

  // v52 (tuning review #19 rec 1, user-approved 2026-09-08): sweep-fill
  // duplicate coalescing — one wallet sweeping one market+outcome is ONE
  // economic intent (exchange-level order splits), not N full-size copies
  // (bkfibaw 4 fills/1s → 4×$91.49@0.04 → −$361.40).
  // TR-20 rec 1 option A (user-approved 2026-09-09): coalesce into the OPEN
  // copy — the anchor is an OPEN position for (wallet, market, outcome) at ANY
  // age, not a 15m recency window. The 24-min-cadence sweep (0x85f0 on
  // ucl-liv-atm-2026-09-09-liv NO: 70 STANDARD opens = $1,260 of one economic
  // intent) beat the recency window; the open-copy condition catches ANY
  // cadence. A same-key fill while the position is open is the same sweep
  // continuing → skipped. The key frees when the copy closes/resolves (a later
  // same-key fill is then a fresh intent). Seeded per run, extended in-loop
  // after each successful open, so a multi-fill sweep collapses to one copy.
  const openCopyRows = await prisma.paperTrade.findMany({
    where: { status: "open" },
    select: { walletAddress: true, marketId: true, outcome: true },
  });
  const openCopyKeys = new Set(
    openCopyRows.map((p) => `${p.walletAddress}|${p.marketId}|${p.outcome}`)
  );
  let deduped = 0;

  // v61 the COPY side of the split: only the current top-N tracked wallets may
  // book a NEW copy. Same predicate the monitor uses to decide which rows are
  // copy-eligible, re-read here because a wallet can be demoted by the hourly
  // scan between the monitor's fetch and this run. Anything else that still
  // reaches the loop is journaled as a skip rather than scored.
  const copyEligible = await copyWalletAddresses(adapter.isDemo);
  for (const t of unscored) {
    // v52 sweep-dedup guard (option A): collapse fills of a (wallet, market,
    // outcome) that already has an OPEN copy — cadence-agnostic by design.
    const dupKey = `${t.walletAddress}|${t.marketId}|${t.outcome}`;
    if (openCopyKeys.has(dupKey)) {
      deduped++;
      log(
        `[DEDUPE] ${t.walletAddress.slice(0, 6)}… ${t.marketId} ${t.outcome} — sweep fill coalesced into the open copy (one position per wallet/market/outcome); no duplicate copy`
      );
      // v54 (tuning review #22 rec 1, approved): JOURNAL the coalesced fill so
      // it leaves the unscored queue permanently. Unjournaled skips were
      // re-processed every run and could re-book once per run — the failure
      // signature behind the 5 post-guard duplicate pairs (#22).
      try {
        await prisma.decisionJournal.create({
          data: {
            observedTradeId: t.id,
            walletAddress: t.walletAddress,
            marketId: t.marketId,
            decision: "skip",
            copyScore: 0,
            confidence: 0,
            reasonsJson: "[]",
            risksJson: JSON.stringify([
              "coalesced into open copy — same wallet/market/outcome already open (v52 option-A dedupe; v54 journaling)",
            ]),
            isDemo: t.isDemo,
          },
        });
      } catch (e) {
        logError(`[DEDUPE] journal write failed for ${t.id}: ${e instanceof Error ? e.message : e}`);
      }
      continue;
    }
    const wallet = await prisma.walletProfile.findUnique({ where: { address: t.walletAddress } });
    if (!wallet) continue;

    // v61 defensive copy gate (rec 1: "keep new copy bookings on the current
    // top-25 only"). The monitor already stamps non-top-25 wallets
    // observationOnly, so this branch fires only on a demotion that landed
    // between the monitor's sweep and this scoring run.
    if (!copyEligible.has(t.walletAddress)) {
      skips++;
      log(
        `[OBSERVE-ONLY] ${t.walletAddress.slice(0, 6)}… ${t.marketId} — wallet outside the current top-${MAX_TRACKED} copy set; observed, not copied`
      );
      try {
        await prisma.decisionJournal.create({
          data: {
            observedTradeId: t.id,
            walletAddress: t.walletAddress,
            marketId: t.marketId,
            decision: "skip",
            copyScore: 0,
            confidence: 0,
            reasonsJson: "[]",
            risksJson: JSON.stringify([
              `observation-only: wallet outside the current top-${MAX_TRACKED} copy set (v61 observation/copy split)`,
            ]),
            isDemo: t.isDemo,
          },
        });
      } catch (e) {
        logError(`[OBSERVE-ONLY] journal write failed for ${t.id}: ${e instanceof Error ? e.message : e}`);
      }
      continue;
    }
    
    // Phase 7: Swarm / Cluster Detection
    const oneHourAgo = new Date(Date.now() - 60 * 60 * 1000);
    // v61: swarm is a COPY signal — observation-only rows must not inflate it,
    // or widening the monitored universe would silently move copy scores.
    const swarmCount = await prisma.observedTrade.count({
      where: {
        marketId: t.marketId,
        outcome: t.outcome,
        side: t.side,
        timestamp: { gte: oneHourAgo },
        observationOnly: false,
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

    // v53 (2026-09-11 C-200 daily report Change 1, approved): long-shot shadow
    // ladder — log EVERY sub-0.20 candidate with its full feature vector; the
    // would-admit book (drift ≤ 0.01 / spread ≤ 0.08 / conf ≥ 0.50) is marked
    // to resolution next to the live book by scripts/mark-shadow-longshot.ts.
    // Live thresholds stay frozen (Oct 8); this only measures. Never fatal.
    if (currentPrice < SHADOW_MAX_PRICE) {
      try {
        appendShadowRow({
          marketId: t.marketId,
          outcome: t.outcome,
          side: t.side,
          walletAddress: t.walletAddress,
          entryPrice: currentPrice,
          walletEntryPrice: t.walletEntryPrice,
          detectedPrice: t.detectedPrice,
          spread,
          liquidity,
          ttrHours: ttr,
          confidence: result.confidence,
          copyScore: result.copyScore,
          liveDecision: result.decision,
          longshotFloorScore: rules.longshotMinCopyScore,
          longshotFloorConf: rules.longshotMinConfidence,
        });
        shadowLogged++;
      } catch (e) {
        logError(`[SHADOW] append failed for ${t.marketId}: ${e instanceof Error ? e.message : e}`);
      }
    }

    const decision = await prisma.decisionJournal.create({
      data: {
        observedTradeId: t.id,
        walletAddress: t.walletAddress,
        marketId: t.marketId,
        decision: result.decision,
        copyScore: result.copyScore,
        confidence: result.confidence,
        // change 2 (approved): the values the gates actually used, so skip rows
        // stop being unanswerable (confidence is 0 by construction on 3 paths).
        rawConfidence: result.rawConfidence,
        adjustedCopyScore: result.adjustedCopyScore,
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
            // v61: the flash-move breaker is a risk gate on real copy candidates;
            // observation rows (wallet fill price, no market read) would add a
            // second price convention to the window.
            where: { marketId: t.marketId, timestamp: { gte: windowStart }, observationOnly: false },
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
      if (rules.maxDrawdownPct > 0 && basisDrawdownPct > rules.maxDrawdownPct) {
        riskGates.push(
          `drawdown gate [${ddBasis}] (net worth $${basisNetWorth.toFixed(0)} vs peak $${basisPeak.toFixed(0)} = ${(basisDrawdownPct * 100).toFixed(1)}% > ${(rules.maxDrawdownPct * 100).toFixed(0)}%)`
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
      if (riskGates.some(isPortfolioGate)) portfolioGateBlocks++;
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

      // 2026-09-15 tuning review #26 recs 1+4 (user-approved): collect the gates
      // that blocked each leg. The journal row above was written with
      // decision=result.decision BEFORE any gate ran, so a fully-blocked copy
      // stayed decision='paper_copy' (539 stored copy rows, 466 with no
      // PaperTrade, and the EOD line printed 422 against 79 real opens) — and
      // gates that only `continue` (v45 slug cap: 338 blocks/24h) wrote nothing
      // at all, hiding them from the skip histogram and the refit sample.
      const legBlocks: string[] = [];
      let legsOpened = 0;
      const executionVenues: Set<string> = new Set();
      for (const botId of ["STANDARD", "BANKROLL_200"]) {
        // v44 (tuning review #13, approved): hour blackout now covers BOTH
        // books — 20:00/23:00 ET drains (z=−2.99/−2.42) cost STANDARD too
        // (window-opened −$622 worst on record); C-200-only gating left
        // STANDARD exposed. The 10:00 ET haircut stays C-200-only.
        // 2026-09-13 Change 1: plus C-200-ONLY blackout hours (08:00 ET —
        // C-200-negative, STANDARD-positive; isHourBlackedOut scopes it).
        if (isHourBlackedOut(botId, etHour)) {
          log(`[${botId}] hour blackout ${etHour}:00 ET (significant drain) — skipping copy ${t.marketId}`);
          legBlocks.push(`${botId}: hour blackout ${etHour}:00 ET`);
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
            legBlocks.push(`BANKROLL_200: open-position cap (${openCount}/${rules.maxOpenPositions})`);
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
          legBlocks.push(`${botId}: v45 blacklist category "${t.marketCategory}"`);
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
            legBlocks.push(
              `BANKROLL_200: v45 market-slug cap (${t.marketCategory} would be ${slugOpen}/${rules.maxMarketSlugPositions})`
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
              legBlocks.push(`BANKROLL_200: kelly no-edge (${kelly.reason})`);
              continue; // C-200 main-lane only — the STANDARD leg is unaffected
            }
            // v51 (2026-09-07 report changes 1+2, user-approved — explicit
            // Kelly-window freeze override): band rails on Kelly admits so the
            // Kelly path cannot contradict the band map (paper.ts) on the two
            // regime-robust findings while λ̂ tables sit between refits. Dead
            // zone [0.40,0.60): cap at the legacy-equivalent (×0.25 map) size;
            // long-shot <0.20: floor at the legacy-equivalent (×2.0 map) size.
            // Inert while λ̂ keeps the dead zone at f*≤0 and <0.20 at −0.91.
            // v54: the Kelly rails compare against the SAME band factors the
            // legacy path books with, so a reallocation moves both paths together.
            const legacyEquiv = clampPaperSize(
              mapBankroll200Size(result.simulatedPositionSize, currentPrice, {
                longshot: rules.c200LongshotBandFactor,
                deadZone: rules.c200DeadZoneBandFactor,
              })
            );
            const railedSize = applyKellyBandRails(kelly.sizeUsd, legacyEquiv, currentPrice);
            if (railedSize !== kelly.sizeUsd) {
              log(
                `[KELLY-RAIL] ${t.marketId} band=${bandLabel} p=${currentPrice.toFixed(3)} ` +
                  // v57 change B widened the cap to [0.20, 0.60) — the old two-way
                  // label printed "long-shot floor" for a 0.20–0.40 CAP, which
                  // misreads the rail's own production evidence (observability only).
                  `${currentPrice >= 0.4 ? "dead-zone cap" : currentPrice >= 0.2 ? "mid-band cap (v57-B)" : "long-shot floor"}: ` +
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

          // v60 (2026-09-20 daily report change 1, user-approved): band-scoped size
          // factor, applied to the FINAL size and to WHATEVER lane booked it. This is
          // the mechanism the approved change needed: the v38 premium overlay skips
          // short-TTR lane copies (`lane !== "short_ttr"`) and every 0.60-0.80 copy in
          // the book is a lane copy (84 of the last 87 opens at exactly $4.99 = lane
          // size x 0.5 band map), so flipping that flag could not bind here. Sits after
          // Kelly/lane sizing and before the concentration gates, so v55/v58 measure
          // the size that actually books.
          if (botId === "BANKROLL_200" && positionSize && rules.c200BandSizeFactor !== 1) {
            const sized = applyBandSizeFactor(
              positionSize,
              currentPrice,
              rules.c200BandSizeFactor,
              rules.c200BandSizeFactorRange
            );
            if (sized !== positionSize) {
              log(
                `[BAND-SIZE] ${t.marketId} entry=${currentPrice.toFixed(3)} band=${rules.c200BandSizeFactorRange} ` +
                  `factor=${rules.c200BandSizeFactor} size ${positionSize.toFixed(2)}→${sized.toFixed(2)} (lane=${result.lane ?? "main"})`
              );
              positionSize = sized;
            }
          }

          // v44 (tuning review #13, approved): STANDARD high-side entry cap —
          // 0.80–1.01 is the worst band (z=−2.50, p=0.013). Enforced per-leg
          // here, NOT via the shared maxEntryPrice rule (that gate is
          // symmetric [1−max, max]; lowering it would kill the <0.15 long-shot
          // edge). C-200 de-risks ≥0.60 via band sizing instead.
          if (botId === "STANDARD" && rules.standardMaxEntryPrice > 0 && currentPrice > rules.standardMaxEntryPrice) {
            log(`[STANDARD] high-entry cap (${currentPrice.toFixed(3)} > ${rules.standardMaxEntryPrice.toFixed(2)}) — skipping copy ${t.marketId}`);
            legBlocks.push(`STANDARD: high-entry cap (${currentPrice.toFixed(3)} > ${rules.standardMaxEntryPrice.toFixed(2)})`);
            continue;
          }

          // v47 (2026-09-03 daily report, approved): C-200 high-side entry
          // cap — hard-cap new copy entries at ≤0.80 (the z=−2.48 premium
          // drag band, −8.5pp excess on 0.80–1.01). Same per-leg pattern:
          // the symmetric maxEntryPrice must stay at 0.95 to preserve the
          // <0.20 long-shot edge (z=+4.05). Applies to main + short-TTR lane.
          if (botId === "BANKROLL_200" && rules.c200MaxEntryPrice > 0 && currentPrice > rules.c200MaxEntryPrice) {
            log(`[BANKROLL_200] high-entry cap (${currentPrice.toFixed(3)} > ${rules.c200MaxEntryPrice.toFixed(2)}) — skipping copy ${t.marketId}`);
            legBlocks.push(`BANKROLL_200: high-entry cap (${currentPrice.toFixed(3)} > ${rules.c200MaxEntryPrice.toFixed(2)})`);
            continue;
          }

          // v55 (daily report Change 1, user-approved): per-market concentration
          // ceiling, checked on the FINAL size (Kelly/band sizing all applied
          // above) so it cannot be gamed by a late resize. Whichever binds first.
          if (botId === "BANKROLL_200" && (c200MarketNotionalCap > 0 || rules.maxMarketLegsPerMarketId > 0)) {
            const legsHere = c200MarketLegs.get(t.marketId) ?? 0;
            const notionalHere = c200MarketNotional.get(t.marketId) ?? 0;
            const sizeHere = positionSize || 0.25;
            const verdict = marketCapDecision({
              legsAlready: legsHere,
              notionalAlready: notionalHere,
              sizeUsd: sizeHere,
              maxLegs: rules.maxMarketLegsPerMarketId,
              notionalCapUsd: c200MarketNotionalCap,
            });
            if (verdict.blocked) {
              log(`[BANKROLL_200] v55 per-market cap (${verdict.why}) — skipping copy ${t.marketId}`);
              legBlocks.push(`BANKROLL_200: v55 per-market cap (${verdict.why})`);
              continue;
            }
            c200MarketLegs.set(t.marketId, legsHere + 1);
            c200MarketNotional.set(t.marketId, notionalHere + sizeHere);
          }

          // v58 (tuning review #30 rec 1, user-approved): per-WALLET
          // concentration ceiling — the mirror of the v55 rail above, on the
          // final size, so a late resize cannot game it. The wallet map is
          // read only here, so the increment lives inside the pass branch and
          // later candidates in THIS run already see earlier acceptances
          // (the same per-cycle fix TR-14 applied to gross exposure).
          if (botId === "BANKROLL_200" && c200WalletNotionalCap > 0) {
            const walletHere = c200WalletNotional.get(t.walletAddress) ?? 0;
            const walletSize = positionSize || 0.25;
            // v59: the grandfathered stock is added to the ceiling, not to the
            // measurement — current + size > baseline + ceiling is exactly
            // "the wallet may add at most one ceiling of new notional".
            const baseline = baselineFor(walletCapBaseline, t.walletAddress);
            const effectiveCeiling = c200WalletNotionalCap + baseline;
            const walletVerdict = walletCapDecision({
              notionalAlready: walletHere,
              sizeUsd: walletSize,
              notionalCapUsd: effectiveCeiling,
            });
            if (walletVerdict.blocked) {
              const basisNote =
                walletCapBasis === "delta"
                  ? ` | basis delta: $${baseline.toFixed(2)} grandfathered + $${c200WalletNotionalCap.toFixed(2)} allowance`
                  : "";
              log(
                `[BANKROLL_200] v58 per-wallet cap (${walletVerdict.why}${basisNote}) — skipping copy ${t.marketId}`
              );
              legBlocks.push(`BANKROLL_200: v58 per-wallet cap (${walletVerdict.why})`);
              // rec 1a (approved): price the veto instead of assuming it. Write-only.
              try {
                appendWalletCapShadow({
                  marketId: t.marketId,
                  outcome: t.outcome,
                  side: t.side,
                  walletAddress: t.walletAddress,
                  marketQuestion: t.marketQuestion,
                  currentPrice,
                  sizeUsd: walletSize,
                  copyScore: result.copyScore,
                  confidence: result.confidence,
                  ttrHours: ttr,
                  spread,
                  liquidity,
                  walletNotionalUsd: walletHere,
                  ceilingUsd: effectiveCeiling,
                  reason: walletVerdict.why ?? "",
                });
              } catch (e) {
                logError(
                  `[WALLET-CAP-SHADOW] append failed for ${t.marketId}: ${e instanceof Error ? e.message : e}`
                );
              }
              continue;
            }
            c200WalletNotional.set(t.walletAddress, walletHere + walletSize);
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
            // v54: band multipliers come from the active ruleset (the C-200
            // legacy path applies them inside openPaperTrade; the Kelly path
            // already used them for its rails below this call).
            bandFactors: {
              longshot: rules.c200LongshotBandFactor,
              deadZone: rules.c200DeadZoneBandFactor,
            },
          });

          // v52 sweep-dedup (option A): this open copy is now the coalescing
          // anchor — any later fill of the same (wallet, market, outcome)
          // while it stays open collapses into it.
          openCopyKeys.add(`${t.walletAddress}|${t.marketId}|${t.outcome}`);
          legsOpened++;

          // Counters and the copy alert belong to a SUCCESSFUL open, so they live
          // inside this per-leg loop. They used to sit after it, once per scored
          // DECISION, which counted and logged a "paper copy" even when every leg
          // was blocked by a gate: lifetime 5,120 "paper copies" logged against
          // 1,879 actual execution intents. The same counters gate `capRisk`
          // (lane 10/cycle, main 50/cycle), so blocked candidates were also eating
          // the per-cycle budget — those caps now behave as designed.
          //
          // Semantics per bot: STANDARD gets a row written here, so this counts
          // positions; BANKROLL_200 only DISPATCHES to the Rust sidecar (the row is
          // written by its webhook callback), so this counts dispatches that passed
          // every gate — the closest thing to "copies made" this loop can observe.
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

      // Rec 1: label a copy by OUTCOME. If no leg opened for this decision, it
      // was never a copy — relabel it `skip` and keep the blocking gates on the
      // row (Rec 4: slug-cap and friends are now visible to the histogram and
      // the refit sample). If at least one leg opened, the copy label stands and
      // the blocks are recorded as context only.
      if (legBlocks.length > 0) {
        const relabel = result.decision === "paper_copy" && legsOpened === 0;
        await prisma.decisionJournal.update({
          where: { id: decision.id },
          data: {
            risksJson: JSON.stringify([...result.risks, ...legBlocks]),
            ...(relabel ? { decision: "skip", simulatedPositionSize: null } : {}),
          },
        });
        if (relabel) skips++;
      }
    } else if (result.decision === "watchlist") watches++;
    else {
      skips++;
      // 2026-09-16 C-200 daily report Change 2 (user-approved): WRITE-ONLY
      // counterfactual for the late-drift gate — the largest volume blocker in
      // the book (~2,000 skips/24h, 905 of them at copyScore >= 80) with no
      // measured outcome. Records the would-have entry so the gate can be judged
      // on data at the Oct 9 close; `maxPriceDrift` itself must NOT move before
      // then (the Oct 8 read is benchmarked at drift 0.004).
      // change 2: price the confidence gate. Recorded for every skip it blocked
      // (confidenceOnly flags the ones where nothing else was wrong — the population
      // a lower bar would actually admit).
      const confRisk = (result.risks ?? []).find((r) => /confidence .* < min/.test(r));
      if (confRisk) {
        try {
          appendLowConfShadow({
            marketId: t.marketId,
            outcome: t.outcome,
            side: t.side,
            walletAddress: t.walletAddress,
            marketQuestion: t.marketQuestion,
            currentPrice,
            rawConfidence: result.rawConfidence ?? result.confidence,
            minConfidence:
              currentPrice < rules.longshotMaxPrice ? rules.longshotMinConfidence : rules.minConfidence,
            copyScore: result.copyScore,
            ttrHours: ttr,
            spread,
            liquidity,
            otherBlocks: Math.max(0, (result.risks ?? []).length - 1),
            reason: confRisk,
          });
          lowConfShadowLogged++;
        } catch (e) {
          logError(`[LOWCONF-SHADOW] append failed for ${t.marketId}: ${e instanceof Error ? e.message : e}`);
        }
      }

      const driftRisk = (result.risks ?? []).find((r) => /price drifted/i.test(r));
      if (driftRisk) {
        try {
          appendDriftShadow({
            marketId: t.marketId,
            outcome: t.outcome,
            side: t.side,
            walletAddress: t.walletAddress,
            currentPrice,
            walletEntryPrice: t.walletEntryPrice,
            detectedPrice: t.detectedPrice,
            drift: Math.abs(currentPrice - t.walletEntryPrice),
            maxDrift: rules.maxPriceDrift,
            copyScore: result.copyScore,
            confidence: result.confidence,
            ttrHours: ttr,
            spread,
            liquidity,
            reason: driftRisk,
          });
          driftShadowLogged++;
        } catch (e) {
          logError(`[DRIFT-SHADOW] append failed for ${t.marketId}: ${e instanceof Error ? e.message : e}`);
        }
      }
    }
  }

  // Pre-loop halt report (#29 rec 2). Logged on EVERY halted cycle so a freeze is
  // visible in the log (and greppable) within one 10-minute tick; the Discord
  // alert is rate-limited to once per 6h so a multi-day freeze cannot spam.
  if (copies === 0 && portfolioGateBlocks > 0) {
    log(
      `[PRE-LOOP HALT] 0 copies this cycle — ${portfolioGateBlocks} candidate(s) vetoed by a PORTFOLIO gate ` +
        `(drawdown/exposure) before any leg loop ran. Entries are HALTED, not quiet. ` +
        `declared basis=${ddBasis}, DD ${(basisDrawdownPct * 100).toFixed(1)}%, gross $${c200RunningExposure.toFixed(2)} vs cap $${c200ExposureCap.toFixed(2)}`
    );
    try {
      const HALT_FILE = join(__dirname, "..", "data", "pre-loop-halt.json");
      let lastMs = 0;
      try {
        lastMs = (JSON.parse(fs.readFileSync(HALT_FILE, "utf-8")) as { lastAlertAtMs?: number }).lastAlertAtMs ?? 0;
      } catch {
        lastMs = 0;
      }
      const ALERT_EVERY_MS = 6 * 3_600_000;
      if (Date.now() - lastMs > ALERT_EVERY_MS) {
        await sendDiscord(
          [
            "🚨 **C-200 entries are HALTED (portfolio gate)** _(paper only)_",
            `**Blocked this cycle:** ${portfolioGateBlocks} candidates, 0 copies`,
            `**Basis:** ${ddBasis} — drawdown ${(basisDrawdownPct * 100).toFixed(1)}% (peak $${basisPeak.toFixed(0)}, NW $${basisNetWorth.toFixed(0)})`,
            `**Exposure:** $${c200RunningExposure.toFixed(2)} vs cap $${c200ExposureCap.toFixed(2)}`,
            `_No entries can open while this holds. Check the MTM/realized basis if the drawdown reads high._`,
          ].join("\n")
        );
        fs.writeFileSync(HALT_FILE, JSON.stringify({ lastAlertAtMs: Date.now(), portfolioGateBlocks, ddBasis }, null, 2));
      }
    } catch (e) {
      logError(`[PRE-LOOP HALT] alert failed: ${e instanceof Error ? e.message : e}`);
    }
  }

  log(
    `Scoring complete: ${copies} paper copies (${laneCopies} short-TTR lane), ${watches} watchlist, ${skips} skips, ` +
      `${deduped} sweep-duplicates coalesced, ${shadowLogged} shadow long-shot candidates logged, ` +
      `${driftShadowLogged} drift-gate counterfactuals logged.`
  );
}

main()
  .catch((e) => {
    logError("score:trades FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
