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
 */

import * as fs from "fs";
import { join } from "path";

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
export const LOWCONF_BAND_EDGES: ReadonlyArray<[number, number]> = [
  [0, 0.2],
  [0.2, 0.4],
  [0.4, 0.6],
  [0.6, 0.8],
  [0.8, 1.01],
];

export function lowConfBandOf(price: number): string {
  for (const [lo, hi] of LOWCONF_BAND_EDGES) if (price >= lo && price < hi) return `${lo}-${hi}`;
  return "other";
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
export const LOWCONF_PRICE_BAND_EDGES: ReadonlyArray<[number, number]> = [
  [0, 0.05],
  [0.05, 0.1],
  [0.1, 0.2],
  [0.2, 0.4],
  [0.4, 0.6],
  [0.6, 0.8],
  [0.8, 1.01],
];

export function lowConfPriceBandOf(price: number): string {
  for (const [lo, hi] of LOWCONF_PRICE_BAND_EDGES) if (price >= lo && price < hi) return `${lo}-${hi}`;
  return "other";
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
  const row = {
    ts: new Date().toISOString(),
    type: "candidate",
    source: "min_confidence_gate",
    marketId: c.marketId,
    outcome: c.outcome,
    side: c.side,
    wallet: c.walletAddress,
    marketQuestion: c.marketQuestion ?? null,
    currentPrice: c.currentPrice,
    band: lowConfBandOf(c.currentPrice),
    rawConfidence: Math.round(c.rawConfidence * 1000) / 1000,
    confidenceBucket: confidenceBucket(c.rawConfidence),
    minConfidence: c.minConfidence,
    copyScore: c.copyScore,
    ttrHours: c.ttrHours ?? null,
    spread: c.spread ?? null,
    liquidity: c.liquidity ?? null,
    otherBlocks: c.otherBlocks,
    confidenceOnly: c.otherBlocks === 0,
    stakeUsd: LOWCONF_SHADOW_STAKE_USD,
    reason: c.reason,
  };
  fs.appendFileSync(LOWCONF_SHADOW_FILE, JSON.stringify(row) + "\n");
}

export function readLowConfRows(): Array<Record<string, unknown>> {
  try {
    return fs
      .readFileSync(LOWCONF_SHADOW_FILE, "utf-8")
      .split("\n")
      .filter((l) => l.trim().length > 0)
      .map((l) => JSON.parse(l) as Record<string, unknown>);
  } catch {
    return [];
  }
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
   * Neither number replaces the other: row-level is the ticket stream, per-signal is the book.
   */
  basis: {
    bets: number;
    signals: number;
    markets: number;
    wouldHavePnlPerSignal: number;
    wouldHavePnlOneBetPerMarket: number;
  };
  /**
   * DUST FLOOR (2026-10-31, card lowconf-shadow-dust-floor). Every figure ABOVE this block
   * is dust-INCLUSIVE and must never be the headline: on the live file entries below
   * `minEntryPrice` own ~96% of `wouldHavePnl` at the bet basis. This block re-cuts the same
   * settled rows with those entries removed, at all three levels (row / signal / market),
   * reports what the floor removed, and prices concentration on the bet basis.
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
  firstCandidateAt: string | null;
  lastCandidateAt: string | null;
}

export function summarizeLowConf(rows: Array<Record<string, unknown>>): LowConfSummary {
  const candidates = rows.filter((r) => r.type === "candidate");
  const resolves = new Map<string, number>();
  for (const r of rows) {
    if (r.type === "resolve") resolves.set(`${r.marketId}|${r.outcome}`, Number(r.value));
  }
  const byBand: LowConfSummary["byBand"] = {};
  const byPriceBand: LowConfSummary["byPriceBand"] = {};
  const byBucket: LowConfSummary["byConfidenceBucket"] = {};
  let marked = 0;
  let wins = 0;
  let pnl = 0;
  let onlyN = 0;
  let onlyMarked = 0;
  let onlyPnl = 0;
  // Earliest ticket per market / per copy signal — the LEVEL basis (see LowConfSummary.basis).
  // Signal key and earliest-wins rule copied from shadow-drift.dedupeSignals so both shadow
  // feeds publish one comparable per-signal basis.
  const firstByMarket = new Map<string, { t: number; pnl: number; entry: number }>();
  const firstBySignal = new Map<string, { t: number; pnl: number; entry: number }>();
  let dustRows = 0;
  let dustRowPnl = 0;
  const markedMarkets = new Set<string>();
  const markedSignals = new Set<string>();
  for (const c of candidates) {
    const stake = Number(c.stakeUsd ?? LOWCONF_SHADOW_STAKE_USD);
    const band = String(c.band ?? lowConfBandOf(Number(c.currentPrice)));
    const bucket = String(c.confidenceBucket ?? confidenceBucket(Number(c.rawConfidence)));
    const b = (byBand[band] ??= { n: 0, marked: 0, wouldHavePnl: 0 });
    const priceBand = lowConfPriceBandOf(Number(c.currentPrice));
    const p = (byPriceBand[priceBand] ??= { n: 0, marked: 0, wouldHavePnl: 0 });
    const k = (byBucket[bucket] ??= { n: 0, marked: 0, wouldHavePnl: 0 });
    b.n++;
    p.n++;
    k.n++;
    const only = c.confidenceOnly === true;
    if (only) onlyN++;
    const v = resolves.get(`${c.marketId}|${c.outcome}`);
    if (v === undefined) continue;
    marked++;
    if (v > 0) wins++;
    const entry = Number(c.currentPrice);
    const rowPnl = entry > 0 ? ((v - entry) / entry) * stake : 0;
    pnl += rowPnl;
    markedMarkets.add(String(c.marketId));
    markedSignals.add(`${c.marketId}|${c.outcome}|${c.wallet ?? ""}`);
    const at = Date.parse(String(c.ts));
    const stamp = Number.isFinite(at) ? at : Number.POSITIVE_INFINITY;
    const mKey = String(c.marketId);
    const sKey = `${c.marketId}|${c.outcome}|${c.wallet ?? ""}`;
    if (!(entry >= LOWCONF_DUST_MIN_ENTRY)) {
      dustRows++;
      dustRowPnl += rowPnl;
    }
    const prevM = firstByMarket.get(mKey);
    if (prevM === undefined || stamp < prevM.t) firstByMarket.set(mKey, { t: stamp, pnl: rowPnl, entry });
    const prevS = firstBySignal.get(sKey);
    if (prevS === undefined || stamp < prevS.t) firstBySignal.set(sKey, { t: stamp, pnl: rowPnl, entry });
    b.marked++;
    b.wouldHavePnl += rowPnl;
    p.marked++;
    p.wouldHavePnl += rowPnl;
    k.marked++;
    k.wouldHavePnl += rowPnl;
    if (only) {
      onlyMarked++;
      onlyPnl += rowPnl;
    }
  }
  const round = (o: Record<string, { n: number; marked: number; wouldHavePnl: number }>) =>
    Object.fromEntries(
      Object.entries(o).map(([key, v]) => [key, { ...v, wouldHavePnl: Math.round(v.wouldHavePnl * 100) / 100 }])
    );
  const ts = candidates.map((r) => String(r.ts)).sort();
  return {
    generatedAt: new Date().toISOString(),
    candidates: candidates.length,
    marked,
    awaitingResolution: candidates.length - marked,
    wins,
    winRate: marked ? wins / marked : null,
    wouldHavePnl: Math.round(pnl * 100) / 100,
    avgPnlPerTrade: marked ? Math.round((pnl / marked) * 100) / 100 : null,
    confidenceOnlyCandidates: onlyN,
    stakeUsd: LOWCONF_SHADOW_STAKE_USD,
    byBand: round(byBand),
    byPriceBand: round(byPriceBand),
    byConfidenceBucket: round(byBucket),
    confidenceOnly: {
      n: onlyN,
      marked: onlyMarked,
      wouldHavePnl: Math.round(onlyPnl * 100) / 100,
      avgPnlPerTrade: onlyMarked ? Math.round((onlyPnl / onlyMarked) * 100) / 100 : null,
    },
    dust: (() => {
      const marketRows = [...firstByMarket.entries()].map(([marketId, r]) => ({ marketId, ...r }));
      const exDustMarkets = marketRows.filter((r) => r.entry >= LOWCONF_DUST_MIN_ENTRY);
      const marketExDust = exDustMarkets.reduce((s, r) => s + r.pnl, 0);
      const sortedMarkets = [...exDustMarkets].sort((a, b) => b.pnl - a.pnl);
      const top10 = sortedMarkets.slice(0, 10).reduce((s, r) => s + r.pnl, 0);
      const top = sortedMarkets[0];
      const bannedTail = marketRows.filter((r) => r.entry > 0 && r.entry < LOWCONF_BANNED_TAIL_MAX);
      const bannedTailPnl = bannedTail.reduce((s, r) => s + r.pnl, 0);
      const sigExDust = [...firstBySignal.values()].filter((r) => r.entry >= LOWCONF_DUST_MIN_ENTRY);
      return {
        minEntryPrice: LOWCONF_DUST_MIN_ENTRY,
        bannedTailMax: LOWCONF_BANNED_TAIL_MAX,
        rowsExcluded: dustRows,
        rowPnlExcluded: Math.round(dustRowPnl * 100) / 100,
        wouldHavePnl: Math.round((pnl - dustRowPnl) * 100) / 100,
        avgPnlPerTrade: marked - dustRows ? Math.round(((pnl - dustRowPnl) / (marked - dustRows)) * 100) / 100 : null,
        signalsExcluded: firstBySignal.size - sigExDust.length,
        wouldHavePnlPerSignal: Math.round(sigExDust.reduce((s, r) => s + r.pnl, 0) * 100) / 100,
        marketsExcluded: marketRows.length - exDustMarkets.length,
        wouldHavePnlOneBetPerMarket: Math.round(marketExDust * 100) / 100,
        wouldHavePnlOneBetPerMarketExTop10: Math.round((marketExDust - top10) * 100) / 100,
        topMarketId: top ? top.marketId : null,
        topMarketPnl: top ? Math.round(top.pnl * 100) / 100 : 0,
        topMarketShare: top && marketExDust !== 0 ? top.pnl / marketExDust : null,
        bannedTailMarkets: bannedTail.length,
        bannedTailOneBetPerMarket: Math.round(bannedTailPnl * 100) / 100,
      };
    })(),
    basis: {
      bets: marked,
      signals: markedSignals.size,
      markets: markedMarkets.size,
      wouldHavePnlPerSignal:
        Math.round([...firstBySignal.values()].reduce((s, r) => s + r.pnl, 0) * 100) / 100,
      wouldHavePnlOneBetPerMarket:
        Math.round([...firstByMarket.values()].reduce((s, r) => s + r.pnl, 0) * 100) / 100,
    },
    firstCandidateAt: ts.length ? ts[0] : null,
    lastCandidateAt: ts.length ? ts[ts.length - 1] : null,
  };
}
