/**
 * Pure helpers for the ML training-data export (card `ml1-target-net-pnl-and-price-baseline`).
 *
 * The export used to emit the binary label `wasDecisionGood = 1[PnL > 0]` as its target. The copy
 * lane is negatively skewed (avg winner +$6.02 vs avg loser -$5.84 today), so a win-count target
 * rewards exactly the wrong thing: measured on the decision dataset, win rate is 57.8% while mean
 * net-entry PnL is +$0.08. The target is now magnitude-bearing:
 *
 *   pnl_net_entry = realizedPnl - entry-leg taker fee      (the cost a gate can know ex ante)
 *   y_net_entry   = 1[pnl_net_entry > 0]                   (classification form of the same label)
 *
 * Fee model is IMPORTED, never re-implemented: `takerFeePerShare` / `categoryFeeRate` from
 * `src/lib/scoring/price-edge.ts`, which mirrors the keyword map in
 * `scripts/build-decision-dataset.py` so the offline fit and this export agree. Shares = size/entry,
 * so the entry fee is `size * rate * (1 - entry)`.
 *
 * This module is pure (no DB, no I/O, no logging) so the target math can be unit-tested and cannot
 * drift from the Python model it has to reconcile with.
 */

import { categoryFeeRate, takerFeePerShare } from "./scoring/price-edge";
import { didOutcomeWin } from "./resolution";

/**
 * Coarse era label from the RuleSet version a decision was scored under. Boundaries are deliberate
 * milestones, not tuned: v49 = the Kelly window opens (Phase B, 2026-09-06), v58 = the per-wallet
 * exposure rail lands (2026-09-19). Unversioned rows stay 'unknown' rather than joining a neighbour.
 */
export function eraOf(ruleSetVersion: number | null | undefined): string {
  if (ruleSetVersion === null || ruleSetVersion === undefined) return "unknown";
  if (ruleSetVersion < 49) return "pre-kelly-v1-48";
  if (ruleSetVersion < 58) return "kelly-window-v49-57";
  return "exposure-v58plus";
}

export interface FeeInput {
  entryPrice: number;
  sizeUsd: number;
  /** Question text + market id; the fee category is keyword-inferred (there is no fee column). */
  feeText: string | null | undefined;
  status: string;
  /** PaperTrade.currentPrice — the exit mark, only meaningful for an early exit. */
  currentPrice: number | null | undefined;
}

export interface FeeDecomposition {
  feeRate: number;
  shares: number;
  exitPrice: number | null;
  feeEntryUsd: number;
  feeExitUsd: number;
}

/**
 * Fee decomposition for one leg. A `resolved` leg pays 0/1 at settlement and trades no exit, so only
 * an early exit (`closed` with a usable mark) carries an exit fee.
 */
export function feeDecomposition(input: FeeInput): FeeDecomposition {
  const rate = categoryFeeRate(input.feeText);
  const shares = input.sizeUsd / input.entryPrice;
  const exitPrice =
    input.status === "closed" &&
    typeof input.currentPrice === "number" &&
    input.currentPrice > 0 &&
    input.currentPrice < 1
      ? input.currentPrice
      : null;
  return {
    feeRate: rate,
    shares,
    exitPrice,
    feeEntryUsd: shares * takerFeePerShare(input.entryPrice, rate),
    feeExitUsd: exitPrice === null ? 0 : shares * takerFeePerShare(exitPrice, rate),
  };
}

export interface TargetInput {
  realizedPnl: number;
  fees: FeeDecomposition;
}

export interface NetTargets {
  pnlNetEntry: number;
  pnlNetFull: number;
  yNetEntry: 0 | 1;
}

export function netTargets(input: TargetInput): NetTargets {
  const pnlNetEntry = input.realizedPnl - input.fees.feeEntryUsd;
  return {
    pnlNetEntry,
    pnlNetFull: input.realizedPnl - input.fees.feeEntryUsd - input.fees.feeExitUsd,
    // Strictly greater: a leg that nets exactly zero is not a win.
    yNetEntry: pnlNetEntry > 0 ? 1 : 0,
  };
}

/**
 * The repo's own "did the token we bought actually win" label, where determinable.
 * Returns null (blank in the CSV) when the venue's winning label is absent or describes a different
 * market — `didOutcomeWin` treats those as undeterminable rather than guessing. Measured on the
 * exported acted book 2026-10-11: determinable on 3,408/4,841 rows (70.4%), so 29.6% ship blank
 * (the older decision dataset covered 78% — a different row set, not a drift).
 */
export function outcomeLabel(
  tradeOutcome: string | null | undefined,
  finalOutcome: string | null | undefined,
): 0 | 1 | null {
  const won = didOutcomeWin(tradeOutcome, { winningLabel: finalOutcome ?? null });
  return won === null ? null : won ? 1 : 0;
}

/**
 * Collapse duplicate-accumulation rows: the same position opened repeatedly is one bet, not N.
 * Key and order match `scripts/build-decision-dataset.py --dedupe` exactly (first entry per
 * bot|wallet|market|outcome in `openedAt ASC` order) so the two artifacts reconcile.
 */
export function dedupeFirstPerPosition<
  T extends { botId: string; walletAddress: string; marketId: string; outcome: string },
>(rows: T[]): T[] {
  const seen = new Set<string>();
  const out: T[] = [];
  for (const r of rows) {
    const key = [r.botId, r.walletAddress, r.marketId, r.outcome].join("\u0001");
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(r);
  }
  return out;
}

/** Round to the 4 decimals the Python dataset writes, so sums reconcile digit for digit. */
export function round4(v: number): number {
  return Math.round(v * 1e4) / 1e4;
}
