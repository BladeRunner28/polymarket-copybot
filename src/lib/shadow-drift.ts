/**
 * Late-drift gate shadow feed (2026-09-16 C-200 daily report Change 2, approved).
 *
 * The `price drifted X > max 0.004 (too late)` gate is the single largest volume
 * blocker in the book (~2,000 skips/24h, and 905 of a day's skips carried
 * copyScore >= 80) yet its counterfactual has never been measured: nobody knows
 * what those would-have-copied entries were worth. This module is WRITE-ONLY
 * instrumentation — it records the would-have entry price and the market's
 * current state at decision time, and scripts/mark-shadow-longshot.ts marks each
 * candidate to settlement from the same feed machinery, so the gate can be
 * judged on data at the Oct 9 window close.
 *
 * NOTHING here changes behaviour: `maxPriceDrift` must not move before Oct 9 —
 * the Oct 8 Kelly-window read is benchmarked against the pre-Kelly baseline
 * measured at drift 0.004, so moving the gate now would contaminate the
 * comparison (the daily report's own caveat).
 */

import * as fs from "fs";
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
  const row = {
    ts: new Date().toISOString(),
    type: "candidate",
    source: "late_drift_gate",
    marketId: c.marketId,
    outcome: c.outcome,
    side: c.side,
    wallet: c.walletAddress,
    currentPrice: c.currentPrice,
    walletEntryPrice: c.walletEntryPrice,
    detectedPrice: c.detectedPrice,
    drift: Math.round(c.drift * 10000) / 10000,
    maxDrift: c.maxDrift,
    copyScore: c.copyScore,
    confidence: c.confidence,
    ttrHours: c.ttrHours ?? null,
    spread: c.spread ?? null,
    liquidity: c.liquidity ?? null,
    otherBlocks: c.otherBlocks ?? null,
    otherRiskKinds: c.otherRiskKinds ?? null,
    rawConfidence: c.rawConfidence ?? null,
    stakeUsd: DRIFT_SHADOW_STAKE_USD,
    reason: c.reason,
  };
  fs.appendFileSync(DRIFT_SHADOW_FILE, JSON.stringify(row) + "\n");
}

export function readDriftRows(): Array<Record<string, unknown>> {
  try {
    return fs
      .readFileSync(DRIFT_SHADOW_FILE, "utf-8")
      .split("\n")
      .filter((l) => l.trim().length > 0)
      .map((l) => JSON.parse(l) as Record<string, unknown>);
  } catch {
    return [];
  }
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
 */
export function dedupeSignals(
  rows: Array<Record<string, unknown>>
): Map<string, Record<string, unknown>> {
  const out = new Map<string, Record<string, unknown>>();
  for (const c of rows) {
    if (c.type !== "candidate") continue;
    const key = `${c.marketId}|${c.outcome}|${c.wallet}`;
    const prev = out.get(key);
    if (!prev || String(c.ts) < String(prev.ts)) out.set(key, c);
  }
  return out;
}

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

export function summarizeDrift(rows: Array<Record<string, unknown>>): DriftSummary {
  const candidates = rows.filter((r) => r.type === "candidate");
  const resolves = new Map<string, number>();
  for (const r of rows) {
    if (r.type === "resolve") resolves.set(`${r.marketId}|${r.outcome}`, Number(r.value));
  }
  let marked = 0;
  let wins = 0;
  let pnl = 0;
  let pnlExDust = 0;
  let markedExDust = 0;
  // trailing 7-day cohort (decision date, not settle date)
  const cohortCutoff = Date.now() - 7 * 86400000;
  let cohortPnl = 0;
  let cohortMarked = 0;
  for (const c of candidates) {
    const v = resolves.get(`${c.marketId}|${c.outcome}`);
    if (v === undefined) continue;
    marked++;
    if (v > 0) wins++;
    const entry = Number(c.currentPrice);
    const rowPnl = entry > 0 ? ((v - entry) / entry) * Number(c.stakeUsd ?? DRIFT_SHADOW_STAKE_USD) : 0;
    pnl += rowPnl;
    if (entry >= DRIFT_DUST_MIN_ENTRY) {
      pnlExDust += rowPnl;
      markedExDust++;
      const decidedAt = Date.parse(String(c.ts));
      if (Number.isFinite(decidedAt) && decidedAt >= cohortCutoff) {
        cohortPnl += rowPnl;
        cohortMarked++;
      }
    }
  }
  const ts = candidates.map((r) => String(r.ts)).sort();

  // ---- instrument v2: the same statistics, one row per SIGNAL ----------------
  // The loop above counts one trade per POLL: a market that stays drifted is
  // counted once per tick, so its mean answers "what did the average poll of a
  // blocked market return". This pass keeps the earliest poll per
  // (marketId, outcome, wallet) so the number answers "what would the average
  // blocked copy have returned" — the question a gate decision needs.
  let sigPnlEx = 0;
  let sigMarkedEx = 0;
  let sigDust = 0;
  let sigCohortPnl = 0;
  let sigCohortN = 0;
  for (const c of dedupeSignals(rows).values()) {
    const v = resolves.get(`${c.marketId}|${c.outcome}`);
    if (v === undefined) continue;
    const entry = Number(c.currentPrice);
    if (!(entry >= DRIFT_DUST_MIN_ENTRY)) {
      sigDust++;
      continue;
    }
    const rowPnl = entry > 0 ? ((v - entry) / entry) * Number(c.stakeUsd ?? DRIFT_SHADOW_STAKE_USD) : 0;
    sigPnlEx += rowPnl;
    sigMarkedEx++;
    const decidedAt = Date.parse(String(c.ts));
    if (Number.isFinite(decidedAt) && decidedAt >= cohortCutoff) {
      sigCohortPnl += rowPnl;
      sigCohortN++;
    }
  }
  const signals = dedupeSignals(rows);
  const signalsSettled = [...signals.values()].filter(
    (c) => resolves.get(`${c.marketId}|${c.outcome}`) !== undefined
  ).length;

  return {
    generatedAt: new Date().toISOString(),
    candidates: candidates.length,
    marked,
    awaitingResolution: candidates.length - marked,
    wins,
    winRate: marked ? wins / marked : null,
    wouldHavePnl: Math.round(pnl * 100) / 100,
    avgPnlPerTrade: marked ? Math.round((pnl / marked) * 100) / 100 : null,
    avgPnlPerTradeExDust: markedExDust ? Math.round((pnlExDust / markedExDust) * 100) / 100 : null,
    dustExcluded: marked - markedExDust,
    dustMinEntryPrice: DRIFT_DUST_MIN_ENTRY,
    avgPnlPerTradeExDustLast7dCohort: cohortMarked ? Math.round((cohortPnl / cohortMarked) * 100) / 100 : null,
    cohort7dMarked: cohortMarked,
    totalMarked: marked,
    stakeUsd: DRIFT_SHADOW_STAKE_USD,
    firstCandidateAt: ts.length ? ts[0] : null,
    lastCandidateAt: ts.length ? ts[ts.length - 1] : null,
    signals: signals.size,
    signalsSettled,
    avgPnlPerTradeExDustPerSignal: sigMarkedEx ? Math.round((sigPnlEx / sigMarkedEx) * 100) / 100 : null,
    dustExcludedPerSignal: sigDust,
    avgPnlPerTradeExDustLast7dCohortPerSignal: sigCohortN
      ? Math.round((sigCohortPnl / sigCohortN) * 100) / 100
      : null,
    cohort7dMarkedPerSignal: sigCohortN,
    rawConfidenceRows: candidates.filter(
      (c) => c.rawConfidence !== null && c.rawConfidence !== undefined
    ).length,
  };
}
