/**
 * Low-confidence reject shadow feed (2026-09-20 C-200 daily report change 2,
 * user-approved).
 *
 * `minConfidence` (0.7) is the funnel's largest single blocker by mention count
 * (5,358 mentions over 24h) and nobody knows whether those entries would have paid —
 * the skip rows stored `confidence = 0`, so the gate could not be priced from the
 * table at all. Change 2 fixes the storage; this file is the priced side of it:
 * every decision the CONFIDENCE gate rejected is recorded with the price, band and
 * the confidence it was rejected at, and scripts/mark-shadow-longshot.ts marks each
 * candidate to settlement from the same feed machinery as the long-shot ladder, the
 * drift counterfactual and the per-wallet ceiling vetoes.
 *
 * WRITE-ONLY instrumentation: no gate, threshold, sizing or routing reads this file,
 * and `minConfidence` must not move on the strength of it until the Oct 8 window
 * close (the read is attributed by ruleSetVersion).
 *
 * 2026-11-11 (card phil-counterfactual-ledger-primitive): rows go through the shared
 * append-only primitive and `summarizeLowConf` is a VIEW of the shared read
 * (src/lib/counterfactual-ledger.ts). This lane is the one the card was written about:
 * the drift counterfactual got a dust floor on 2026-09-19 and this one did not, on the
 * same dust-dominated population, because each lane owned its own arithmetic — and
 * when the floor was finally added here on 2026-10-31 it had to be written a second
 * time, lane-locally. The arithmetic (fill rule, dedupe key, dust floor, level basis,
 * concentration) now lives once; this file passes a floor and picks field names.
 */

import { join } from "path";
import {
  appendCounterfactualCandidate,
  groupStats,
  ledgerEntryPrice,
  priceBandOf,
  readLedger,
  settledDustRead,
  summarizeLedger,
  COARSE_BAND_EDGES,
  FINE_PRICE_BAND_EDGES,
} from "./counterfactual-ledger";

export const LOWCONF_SHADOW_FILE = join(__dirname, "..", "..", "data", "lowconf-shadow.jsonl");
export const LOWCONF_SHADOW_SUMMARY_FILE = join(__dirname, "..", "..", "data", "lowconf-shadow-summary.json");

/**
 * Fixed hypothetical clip, matching the drift counterfactual's convention: skipped
 * decisions booked nothing, so a constant stake makes candidates comparable to each
 * other and to the drift feed. The band and the real price are stored alongside, so
 * a band-scoped question can still be answered.
 */
export const LOWCONF_SHADOW_STAKE_USD = Number(process.env.LOWCONF_SHADOW_STAKE_USD ?? 10);

/** Same band edges as the calibration table, so the read joins to it directly. */
export const LOWCONF_BAND_EDGES: ReadonlyArray<[number, number]> = COARSE_BAND_EDGES;

export function lowConfBandOf(price: number): string {
  return priceBandOf(price, LOWCONF_BAND_EDGES);
}

/**
 * Finer PRICE split inside the coarse bands (2026-10-25 C-200 daily report).
 *
 * WHY: the headline `wouldHavePnl` is 97% one population — tickets priced below
 * 0.05, where a $10 stake wins ~$200-1000. Those entries were BANNED at admission
 * by RuleSet v67 (`c200LongshotBandFloor` 0.05, 2026-10-24), so they are no longer
 * tradable, yet the coarse "0-0.2" row lumps them in with 0.05-0.20 and reads as
 * "long-shots pay, lower the floor". Measured 2026-10-25: sub-0.05 priced 617 rows
 * = +$540,380 of the $554,735 headline; 0.05-0.20 priced 861 rows = +$14,355.
 * Additive only — every pre-existing field is computed exactly as before.
 */
export const LOWCONF_PRICE_BAND_EDGES: ReadonlyArray<[number, number]> = FINE_PRICE_BAND_EDGES;

export function lowConfPriceBandOf(price: number): string {
  return priceBandOf(price, LOWCONF_PRICE_BAND_EDGES);
}

/**
 * DUST FLOOR for the counterfactual (2026-10-31, card lowconf-shadow-dust-floor).
 *
 * A $10 ticket at 0.0005 that settles at 1.0 returns 20,000x, so a handful of sub-cent
 * rows can own the entire headline — the exact defect tuning #29 rec 1 fixed for the
 * drift feed (DRIFT_DUST_MIN_ENTRY, 0.10) and never for this lane. Below the floor an
 * entry is not executable at any sane size on this venue, so those rows answer "would
 * the gate have made money on a lottery ticket nobody could buy", not "would the refused
 * copy have paid".
 *
 * Default 0.10 matches the drift feed's floor so the two shadows stay comparable; it is
 * env-overridable and is a MEASUREMENT floor only — no gate, threshold or sizing reads it.
 * Since 2026-11-11 the floor is applied by the SHARED read (settledDustRead), not by a
 * lane-local copy of the arithmetic.
 */
export const LOWCONF_DUST_MIN_ENTRY = Number(process.env.LOWCONF_DUST_MIN_ENTRY ?? 0.10);

/**
 * The slice the v67 admission floor (c200LongshotBandFloor 0.05) already bans. Reported
 * separately because the 2026-10-26 magnitude correction was stated on this cut
 * (sub-0.05 = $266,309 of $277,533 per-market), so the two must stay reconcilable.
 */
export const LOWCONF_BANNED_TAIL_MAX = 0.05;

/** Confidence bucket, so the read can ask "what if the bar were 0.6 instead of 0.7?" */
export function confidenceBucket(rawConfidence: number): string {
  if (rawConfidence >= 0.7) return ">=0.70";
  if (rawConfidence >= 0.6) return "0.60-0.70";
  if (rawConfidence >= 0.5) return "0.50-0.60";
  if (rawConfidence >= 0.4) return "0.40-0.50";
  return "<0.40";
}

export interface LowConfShadowCandidate {
  marketId: string;
  outcome: string;
  side: string;
  walletAddress: string;
  marketQuestion?: string;
  currentPrice: number;
  /** The confidence the gate rejected at (raw, pre-zeroing). */
  rawConfidence: number;
  /** The bar in force at rejection. */
  minConfidence: number;
  copyScore: number;
  ttrHours?: number;
  spread?: number;
  liquidity?: number;
  /** Hard skips on the same decision; 0 = confidence was the ONLY thing blocking. */
  otherBlocks: number;
  reason: string;
}

export function appendLowConfShadow(c: LowConfShadowCandidate): void {
  appendCounterfactualCandidate({
    lane: "min_confidence_gate",
    file: LOWCONF_SHADOW_FILE,
    marketId: c.marketId,
    outcome: c.outcome,
    side: c.side,
    walletAddress: c.walletAddress,
    entryPrice: c.currentPrice,
    fill: { kind: "fixed_clip", stakeUsd: LOWCONF_SHADOW_STAKE_USD },
    copyScore: c.copyScore,
    ttrHours: c.ttrHours ?? null,
    spread: c.spread ?? null,
    liquidity: c.liquidity ?? null,
    reason: c.reason,
    extras: {
      // Legacy field names kept verbatim (readers, dashboards, the frozen golden diff).
      source: "min_confidence_gate",
      marketQuestion: c.marketQuestion ?? null,
      currentPrice: c.currentPrice,
      band: lowConfBandOf(c.currentPrice),
      rawConfidence: Math.round(c.rawConfidence * 1000) / 1000,
      confidenceBucket: confidenceBucket(c.rawConfidence),
      minConfidence: c.minConfidence,
      otherBlocks: c.otherBlocks,
      confidenceOnly: c.otherBlocks === 0,
    },
  });
}

export function readLowConfRows(): Array<Record<string, unknown>> {
  return readLedger(LOWCONF_SHADOW_FILE);
}

export interface LowConfSummary {
  generatedAt: string;
  candidates: number;
  marked: number;
  awaitingResolution: number;
  wins: number;
  winRate: number | null;
  wouldHavePnl: number;
  avgPnlPerTrade: number | null;
  confidenceOnlyCandidates: number;
  stakeUsd: number;
  byBand: Record<string, { n: number; marked: number; wouldHavePnl: number }>;
  /** Price sub-split inside the coarse bands — separates the v67-banned sub-0.05 tail. */
  byPriceBand: Record<string, { n: number; marked: number; wouldHavePnl: number }>;
  byConfidenceBucket: Record<string, { n: number; marked: number; wouldHavePnl: number }>;
  /** The counterfactual the gate question actually needs: confidence-only rejects. */
  confidenceOnly: { n: number; marked: number; wouldHavePnl: number; avgPnlPerTrade: number | null };
  /**
   * DUST FLOOR (2026-10-31, card lowconf-shadow-dust-floor). Every figure ABOVE this block
   * is dust-INCLUSIVE and must never be the headline: on the live file entries below
   * `minEntryPrice` own ~96% of `wouldHavePnl` at the bet basis. This block re-cuts the same
   * settled rows with those entries removed, at all three levels (row / signal / market),
   * reports what the floor removed, and prices concentration on the bet basis.
   *
   * Since 2026-11-11 the block is computed by the SHARED read (settledDustRead): the floor,
   * the dedupe key and the arithmetic exist once, so this lane cannot grow a private
   * variant again.
   */
  dust: {
    minEntryPrice: number;
    bannedTailMax: number;
    /** Row level — one ticket per POLL (the ticket stream, not the book). */
    rowsExcluded: number;
    rowPnlExcluded: number;
    wouldHavePnl: number;
    avgPnlPerTrade: number | null;
    /** Signal level — earliest poll per marketId|outcome|wallet. */
    signalsExcluded: number;
    wouldHavePnlPerSignal: number;
    /** Market level — earliest poll per market (the bet basis). */
    marketsExcluded: number;
    wouldHavePnlOneBetPerMarket: number;
    /** Same market-level total with its ten largest contributors removed. */
    wouldHavePnlOneBetPerMarketExTop10: number;
    topMarketId: string | null;
    topMarketPnl: number;
    /** topMarketPnl as a share of the ex-dust market-level total (null when that is 0). */
    topMarketShare: number | null;
    /** Entries below LOWCONF_BANNED_TAIL_MAX, market level — reconciles the v67-banned tail. */
    bannedTailMarkets: number;
    bannedTailOneBetPerMarket: number;
  };
  /**
   * LEVEL basis (2026-10-26, self-audit). `marked` counts candidate ROWS, and a row is one
   * $10 ticket offered on one poll — the same market|outcome|wallet is re-decided every time
   * the scan runs while the price stays put. Measured on the live file: 23,001 marked rows
   * collapse to 4,943 distinct copy signals (marketId|outcome|wallet) on 4,240 markets, one
   * triple logged 363 times — so `wouldHavePnl` answers "what did the average POLL of a
   * refused market return", not "what would the refused COPY have returned".
   *
   * Same defect `summarizeDrift` carried until 2026-10-11 (card
   * drift-shadow-instrument-defects: 26,928 rows -> 9,075 signals); this publishes both bases
   * with the SAME key and the SAME earliest-wins rule so the two shadows stay comparable.
   *
   * Both now come from the SHARED read (2026-11-11), not a lane-local copy of the rule.
   */
  basis: {
    bets: number;
    signals: number;
    markets: number;
    wouldHavePnlPerSignal: number;
    wouldHavePnlOneBetPerMarket: number;
  };
  firstCandidateAt: string | null;
  lastCandidateAt: string | null;
}

const round2 = (v: number) => Math.round(v * 100) / 100;

/**
 * VIEW of the shared counterfactual read (src/lib/counterfactual-ledger.ts).
 * The level/band/bucket splits are projections of the same resolve join and the same
 * fill rule, and the dust cut is the shared `settledDustRead`, so this lane cannot
 * drift from the drift lane again.
 */
export function summarizeLowConf(rows: Array<Record<string, unknown>>): LowConfSummary {
  const read = {
    dustMinEntry: LOWCONF_DUST_MIN_ENTRY,
    stakeField: "stakeUsd",
    defaultStakeUsd: LOWCONF_SHADOW_STAKE_USD,
  };
  const s = summarizeLedger(rows, read);
  const d = settledDustRead(rows, { ...read, bannedTailMax: LOWCONF_BANNED_TAIL_MAX, topN: 10 });
  const only = settledDustRead(rows, {
    ...read,
    betFilter: (r) => r.confidenceOnly === true,
  });
  const byBand = groupStats(rows, (c) => String(c.band ?? lowConfBandOf(ledgerEntryPrice(c))));
  const byPriceBand = groupStats(rows, (c) => lowConfPriceBandOf(ledgerEntryPrice(c)));
  const byConfidenceBucket = groupStats(rows, (c) =>
    String(c.confidenceBucket ?? confidenceBucket(Number(c.rawConfidence)))
  );
  const confidenceOnlyCandidates = rows.filter(
    (r) => r.type === "candidate" && r.confidenceOnly === true
  ).length;

  return {
    generatedAt: new Date().toISOString(),
    candidates: s.candidates,
    marked: s.marked,
    awaitingResolution: s.awaitingResolution,
    wins: s.wins,
    winRate: s.winRate,
    wouldHavePnl: s.wouldHavePnl,
    avgPnlPerTrade: s.avgPnlPerTrade,
    confidenceOnlyCandidates,
    stakeUsd: LOWCONF_SHADOW_STAKE_USD,
    byBand,
    byPriceBand,
    byConfidenceBucket,
    confidenceOnly: {
      n: confidenceOnlyCandidates,
      marked: only.row.marked,
      wouldHavePnl: round2(only.row.wouldHavePnl),
      avgPnlPerTrade: only.row.marked ? round2(only.row.wouldHavePnl / only.row.marked) : null,
    },
    dust: {
      minEntryPrice: LOWCONF_DUST_MIN_ENTRY,
      bannedTailMax: LOWCONF_BANNED_TAIL_MAX,
      rowsExcluded: d.row.dustExcluded,
      rowPnlExcluded: round2(d.row.dustWouldHavePnl),
      wouldHavePnl: round2(d.row.exDustWouldHavePnl),
      avgPnlPerTrade:
        d.row.exDustAvgPnlPerTrade === null ? null : round2(d.row.exDustAvgPnlPerTrade),
      signalsExcluded: d.signal.dustExcluded,
      wouldHavePnlPerSignal: round2(d.signal.exDustWouldHavePnl),
      marketsExcluded: d.market.dustExcluded,
      wouldHavePnlOneBetPerMarket: round2(d.market.exDustWouldHavePnl),
      wouldHavePnlOneBetPerMarketExTop10: round2(d.market.exTopNWouldHavePnl),
      topMarketId: d.market.topMarketId,
      topMarketPnl: round2(d.market.topMarketPnl),
      topMarketShare: d.market.topMarketShare,
      bannedTailMarkets: d.market.bannedTailMarkets,
      bannedTailOneBetPerMarket: round2(d.market.bannedTailWouldHavePnl),
    },
    basis: {
      bets: s.marked,
      signals: d.signal.settled,
      markets: d.market.settled,
      wouldHavePnlPerSignal: round2(d.signal.wouldHavePnl),
      wouldHavePnlOneBetPerMarket: round2(d.market.wouldHavePnl),
    },
    firstCandidateAt: s.firstCandidateAt,
    lastCandidateAt: s.lastCandidateAt,
  };
}
