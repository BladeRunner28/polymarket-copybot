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
  /** Same, but priced at the market's last observed mark for candidates still open. */
  totalMarked: number;
  stakeUsd: number;
  firstCandidateAt: string | null;
  lastCandidateAt: string | null;
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
    }
  }
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
    avgPnlPerTradeExDust: markedExDust ? Math.round((pnlExDust / markedExDust) * 100) / 100 : null,
    dustExcluded: marked - markedExDust,
    dustMinEntryPrice: DRIFT_DUST_MIN_ENTRY,
    totalMarked: marked,
    stakeUsd: DRIFT_SHADOW_STAKE_USD,
    firstCandidateAt: ts.length ? ts[0] : null,
    lastCandidateAt: ts.length ? ts[ts.length - 1] : null,
  };
}
