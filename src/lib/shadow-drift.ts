/**
 * Late-drift gate shadow feed (2026-09-16 C-200 daily report Change 2, approved).
 *
 * The `price drifted X > max 0.004 (too late)` gate is the single largest volume
 * blocker in the book (~2,000 skips/24h, and 905 of a day's skips carried
 * copyScore >= 80) yet its counterfactual was never measured: nobody knew what
 * those would-have-copied entries were worth. This module records the would-have
 * entry and the market's state at decision time; scripts/mark-shadow-longshot.ts
 * marks each candidate to settlement so the gate can be judged on data.
 *
 * WRITE-ONLY instrumentation: no gate, threshold, sizing or routing reads this
 * file, and `maxPriceDrift` must not move on the strength of it.
 *
 * 2026-10-29 (card phil-counterfactual-ledger-primitive): the writer and the
 * summary math are no longer local. Rows go through the shared append-only
 * primitive (src/lib/counterfactual-ledger.ts) and `summarizeDrift` is a VIEW of
 * the shared read — same fill rule, same dust floor, same per-signal dedupe as
 * every other declined-gate lane. The published field names and their values are
 * unchanged (verified field-for-field against the pre-port implementation by
 * scripts/reconcile-counterfactual-ledger.ts on a frozen window).
 */

import {
  appendCounterfactualCandidate,
  dedupeSignals as dedupeSignalsShared,
  ledgerEntryPrice,
  priceBandOf,
  readLedger,
  summarizeLedger,
  COARSE_BAND_EDGES,
} from "./counterfactual-ledger";
import { join } from "path";

export const DRIFT_SHADOW_FILE = join(__dirname, "..", "..", "data", "drift-shadow.jsonl");
export const DRIFT_SHADOW_SUMMARY_FILE = join(__dirname, "..", "..", "data", "drift-shadow-summary.json");

/** Fixed hypothetical clip for comparability across candidates (they booked nothing). */
export const DRIFT_SHADOW_STAKE_USD = 10;

/**
 * #29 rec 1 (2026-09-19, approved): DUST FLOOR for the counterfactual average.
 *
 * A $0.0005 entry that settles at 1.0 returns 2000x — two such marks turned the
 * gate's headline into $23.03/trade, of which 96% was those two rows, while the
 * rest of the sample averaged $1.29 (≈ the bot's own +$0.94). Entries below this
 * floor are not executable at any sane size on Polymarket, so they are excluded
 * from the per-trade average and reported separately. The headline figure is kept
 * for continuity and labelled as dust-inclusive.
 *
 * The floor is passed to the shared read as an OPTION (the primitive itself has
 * no floor and no other threshold), and the same option is what the minConfidence
 * lane now passes — one policy, one place.
 */
export const DRIFT_DUST_MIN_ENTRY = Number(process.env.DRIFT_DUST_MIN_ENTRY ?? 0.10);

export interface DriftShadowCandidate {
  marketId: string;
  outcome: string;
  side: string;
  walletAddress: string;
  /** Executable-ish price the scorer would have copied at. */
  currentPrice: number;
  /** Price the wallet entered at — the drift reference. */
  walletEntryPrice: number;
  /** Scorer's detected price at signal time. */
  detectedPrice: number;
  drift: number;
  maxDrift: number;
  copyScore: number;
  confidence: number;
  ttrHours?: number;
  spread?: number;
  liquidity?: number;
  /**
   * Residual risks OTHER than the drift gate at decision time (same field the
   * lowconf feed has always carried). Instrument v2, 2026-10-11: without it a
   * reader cannot tell "the drift gate was the only blocker" from "this row was
   * blocked by four things".
   */
  otherBlocks?: number;
  /**
   * Instrument v3 (2026-10-20, Lane B): WHICH other risks fired, not just how many.
   *
   * `otherBlocks` counts co-blockers but cannot name them, and the count alone made the
   * drift gate unpriceable in the direction that matters: measured on 2026-10-20, **0 of
   * 6,838** rows carrying the field had `otherBlocks === 0`, so a sign fix to the drift
   * comparison would admit ZERO copies on its own — but the file cannot say whether the
   * co-blockers are hard gates or soft/informational risks, because only the count was
   * stored. The identities make that attribution possible on future rows.
   */
  otherRiskKinds?: string[];
  /**
   * The v37 confidence as COMPUTED, before the skip paths zero it. `confidence`
   * below is 0 by construction on every skip/watchlist/lane return
   * (src/lib/scoring/trade.ts:46), so the recorded `confidence` field of this
   * feed is structurally zero; a gate-correct screen has to read THIS one.
   * Instrument v2, 2026-10-11. Rows written before that date carry null and the
   * value must be reconstructed from copyScore:
   * `(copyScore - watchlistScore) / (100 - watchlistScore)`.
   */
  rawConfidence?: number;
  /** Why the gate fired, verbatim from the skip risks. */
  reason: string;
}

export function appendDriftShadow(c: DriftShadowCandidate): void {
  appendCounterfactualCandidate({
    lane: "late_drift_gate",
    file: DRIFT_SHADOW_FILE,
    marketId: c.marketId,
    outcome: c.outcome,
    side: c.side,
    walletAddress: c.walletAddress,
    entryPrice: c.currentPrice,
    fill: { kind: "fixed_clip", stakeUsd: DRIFT_SHADOW_STAKE_USD },
    copyScore: c.copyScore,
    confidence: c.confidence,
    ttrHours: c.ttrHours ?? null,
    spread: c.spread ?? null,
    liquidity: c.liquidity ?? null,
    reason: c.reason,
    extras: {
      // Legacy field names kept verbatim: existing readers, dashboards and the
      // frozen golden diff all read these keys.
      source: "late_drift_gate",
      currentPrice: c.currentPrice,
      walletEntryPrice: c.walletEntryPrice,
      detectedPrice: c.detectedPrice,
      drift: Math.round(c.drift * 10000) / 10000,
      maxDrift: c.maxDrift,
      otherBlocks: c.otherBlocks ?? null,
      otherRiskKinds: c.otherRiskKinds ?? null,
      rawConfidence: c.rawConfidence ?? null,
    },
  });
}

export function readDriftRows(): Array<Record<string, unknown>> {
  return readLedger(DRIFT_SHADOW_FILE);
}

/**
 * Instrument v2 (2026-10-11, card drift-shadow-instrument-defects): the SECOND
 * day series, cut to one row per copy signal. The original series samples the
 * CUMULATIVE per-poll mean once a day; this one samples the cumulative
 * per-signal mean, so a market that stays drifted is not counted once per
 * 10-minute poll. The pre-registered 2026-09-20 bar keeps reading the original
 * series (that is the quantity it was pre-registered against); this series is
 * published ALONGSIDE it and is what a per-opportunity read must use.
 */
export const DRIFT_DECAY_SERIES_PER_SIGNAL_FILE = join(
  __dirname,
  "..",
  "..",
  "data",
  "drift-decay-series-per-signal.jsonl"
);

/**
 * One row per distinct copy signal: (marketId, outcome, wallet), keeping the
 * EARLIEST poll — the decision at which the signal first appeared, which is also
 * the price a relaxed tolerance would have paid.
 *
 * The rule now lives in the shared primitive so every lane's per-opportunity
 * basis uses one key and one tie-break; this re-export keeps the drift feed's
 * public surface (tests and the marker import it from here).
 */
export function dedupeSignals(
  rows: Array<Record<string, unknown>>
): Map<string, Record<string, unknown>> {
  return dedupeSignalsShared(rows);
}

/** Coarse band edges, re-exported for readers that band drift rows by price. */
export { COARSE_BAND_EDGES as DRIFT_BAND_EDGES };
export { priceBandOf as driftBandOf };

/**
 * Consecutive days at or below the bar, read from the END of a day series (a
 * day's last reading is the day's value). Pure, so both bases share one rule and
 * the rule is testable without a runner.
 */
export function consecutiveDaysAtOrBelow(
  series: Array<{ day: string; avgPnlPerTradeExDust: number | null }>,
  barUsd: number
): number {
  let consecutive = 0;
  for (let i = series.length - 1; i >= 0; i--) {
    const v = series[i].avgPnlPerTradeExDust;
    if (v !== null && v <= barUsd) consecutive++;
    else break;
  }
  return consecutive;
}

export interface DriftSummary {
  generatedAt: string;
  candidates: number;
  marked: number;
  awaitingResolution: number;
  wins: number;
  winRate: number | null;
  /** Sum of (settled value − entry)/entry × stakeUsd over marked candidates. */
  wouldHavePnl: number;
  avgPnlPerTrade: number | null;
  /** Mean PnL/trade EXCLUDING entries below DRIFT_DUST_MIN_ENTRY (the honest read). */
  avgPnlPerTradeExDust: number | null;
  /** How many settled candidates the dust floor removed. */
  dustExcluded: number;
  dustMinEntryPrice: number;
  /**
   * Trailing-window read (2026-09-20, tuning #31 rec 2 support): the same
   * ex-dust mean restricted to candidates DECIDED in the last 7 days. The
   * cumulative figure above drifts mechanically as settled rows accumulate,
   * so the pre-registered decay bar reads both.
   */
  avgPnlPerTradeExDustLast7dCohort: number | null;
  cohort7dMarked: number;
  /** Same, but priced at the market's last observed mark for candidates still open. */
  totalMarked: number;
  stakeUsd: number;
  firstCandidateAt: string | null;
  lastCandidateAt: string | null;
  /**
   * --- instrument v2, one row per SIGNAL (2026-10-11) ------------------------
   * `candidates`/`marked`/`avgPnlPerTradeExDust` above count one "trade" per
   * poll row, so a market that stays drifted is counted once per 10-minute tick
   * (26,928 rows = 9,075 distinct signals; one market contributed 428 rows). The
   * fields below re-cut the same statistics to one row per
   * (marketId, outcome, wallet), keeping the EARLIEST poll. They answer "what
   * would the average blocked COPY have returned", which is the actionable
   * question; the poll-row numbers stay for continuity and for the
   * pre-registered bar.
   */
  signals: number;
  signalsSettled: number;
  avgPnlPerTradeExDustPerSignal: number | null;
  dustExcludedPerSignal: number;
  avgPnlPerTradeExDustLast7dCohortPerSignal: number | null;
  cohort7dMarkedPerSignal: number;
  /** Candidate rows carrying rawConfidence (rows written from 2026-10-11 on). */
  rawConfidenceRows: number;
}

/**
 * VIEW of the shared counterfactual read (src/lib/counterfactual-ledger.ts).
 * Field names and values are the pre-port ones; nothing lane-specific is computed
 * here beyond the rawConfidence row count the feed itself owns.
 *
 * `now` overrides the clock the trailing-7d cohort is measured against. Production
 * callers omit it (wall clock). It exists so the port's reconcile gate can price the
 * cohort at the SAME instant the pre-port golden was captured at — otherwise a diff
 * run a few minutes later "mismatches" purely because the 7-day boundary moved.
 */
export function summarizeDrift(
  rows: Array<Record<string, unknown>>,
  opts: { now?: number } = {}
): DriftSummary {
  const s = summarizeLedger(rows, {
    dustMinEntry: DRIFT_DUST_MIN_ENTRY,
    stakeField: "stakeUsd",
    defaultStakeUsd: DRIFT_SHADOW_STAKE_USD,
    now: opts.now,
  });
  return {
    generatedAt: new Date().toISOString(),
    candidates: s.candidates,
    marked: s.marked,
    awaitingResolution: s.awaitingResolution,
    wins: s.wins,
    winRate: s.winRate,
    wouldHavePnl: s.wouldHavePnl,
    avgPnlPerTrade: s.avgPnlPerTrade,
    avgPnlPerTradeExDust: s.exDust.avgPnlPerTrade,
    dustExcluded: s.exDust.excluded,
    dustMinEntryPrice: DRIFT_DUST_MIN_ENTRY,
    avgPnlPerTradeExDustLast7dCohort: s.cohort.avgPnlPerTrade,
    cohort7dMarked: s.cohort.marked,
    totalMarked: s.marked,
    stakeUsd: DRIFT_SHADOW_STAKE_USD,
    firstCandidateAt: s.firstCandidateAt,
    lastCandidateAt: s.lastCandidateAt,
    signals: s.signals,
    signalsSettled: s.signalsSettled,
    avgPnlPerTradeExDustPerSignal: s.perSignal.exDustAvg,
    dustExcludedPerSignal: s.perSignal.dustExcluded,
    avgPnlPerTradeExDustLast7dCohortPerSignal: s.perSignal.cohortAvg,
    cohort7dMarkedPerSignal: s.perSignal.cohortMarked,
    rawConfidenceRows: rows.filter((r) => {
      if (r.type !== "candidate") return false;
      return r.rawConfidence !== null && r.rawConfidence !== undefined;
    }).length,
  };
}

/** Entry price of a legacy or canonical drift row (exposed for reconciliation reads). */
export function driftEntryPrice(row: Record<string, unknown>): number {
  return ledgerEntryPrice(row);
}
