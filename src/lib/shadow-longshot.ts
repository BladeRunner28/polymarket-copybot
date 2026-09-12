/**
 * Long-shot shadow ladder (2026-09-11 C-200 daily report Change 1, approved —
 * freeze-allowed instrumentation, zero capital risk).
 *
 * Thesis (report): the proven <0.20 bucket is STARVED, not scarce — since v49
 * the scorer saw 2,296 distinct sub-0.20 candidates and copied 61 (2.7%,
 * ≈9/day) while ~400 candidates/day arrive in-band; blocker tags: drift 74%,
 * confidence floor 79%, sub-0.05 near-certainty 53%, liquidity 40%, spread 21%.
 * All live thresholds are frozen for the Kelly window (hold through Oct 8), so
 * this module MEASURES instead: every sub-0.20 candidate is logged with its full
 * feature vector, and a shadow book is marked to resolution next to the live
 * book. "Would-admit at the relaxed ladder" is computed both live and
 * retroactively (the raw features are stored, so thresholds can be re-cut).
 *
 * Relaxed ladder (report): drift ≤ 0.01, spread ≤ 0.08, confidence ≥ 0.50,
 * price in [0.05, 0.20). Fixed shadow stake for comparability.
 *
 * Decision point: Sep 22 (7 shadow days) or the Oct 8 Kelly-window close.
 */

import * as fs from "fs";
import { join } from "path";

export const SHADOW_FILE = join(__dirname, "..", "..", "data", "longshot-shadow.jsonl");
export const SHADOW_SUMMARY_FILE = join(__dirname, "..", "..", "data", "longshot-shadow-summary.json");

export const SHADOW_STAKE_USD = 20;
export const SHADOW_MIN_PRICE = 0.05;
export const SHADOW_MAX_PRICE = 0.2;
export const SHADOW_MAX_DRIFT = 0.01;
export const SHADOW_MAX_SPREAD = 0.08;
export const SHADOW_MIN_CONFIDENCE = 0.5;

export interface ShadowCandidate {
  marketId: string;
  outcome: string;
  side: string;
  walletAddress: string;
  /** Executable-ish live price used by the scorer. */
  entryPrice: number;
  walletEntryPrice: number;
  detectedPrice: number;
  spread?: number;
  liquidity?: number;
  ttrHours?: number;
  confidence: number;
  copyScore: number;
  /** Live decision taken (paper_copy | watchlist | skip). */
  liveDecision: string;
  /** v48 long-shot band admission floors (for context). */
  longshotFloorScore?: number;
  longshotFloorConf?: number;
}

export interface ShadowAdmitVerdict {
  wouldAdmit: boolean;
  /** Failed conditions, tagged for funnel analysis. */
  blockers: string[];
}

/** Evaluate the report's relaxed ladder. Pure. */
export function evaluateShadowAdmit(c: ShadowCandidate): ShadowAdmitVerdict {
  const blockers: string[] = [];
  if (c.entryPrice < SHADOW_MIN_PRICE) blockers.push("sub-0.05 near-certainty band");
  if (c.entryPrice >= SHADOW_MAX_PRICE) blockers.push("price >= 0.20");
  const drift = Math.abs(c.entryPrice - c.walletEntryPrice);
  if (drift > SHADOW_MAX_DRIFT) blockers.push(`drift ${drift.toFixed(4)} > ${SHADOW_MAX_DRIFT}`);
  if (c.spread === undefined) blockers.push("no spread data");
  else if (c.spread > SHADOW_MAX_SPREAD) blockers.push(`spread ${c.spread.toFixed(3)} > ${SHADOW_MAX_SPREAD}`);
  if (c.confidence < SHADOW_MIN_CONFIDENCE) blockers.push(`confidence ${c.confidence.toFixed(2)} < ${SHADOW_MIN_CONFIDENCE}`);
  return { wouldAdmit: blockers.length === 0, blockers };
}

/** Append one candidate row (event-sourced JSONL, same style as the other shadow feeds). */
export function appendShadowRow(c: ShadowCandidate): void {
  const verdict = evaluateShadowAdmit(c);
  const row = {
    ts: new Date().toISOString(),
    type: "candidate",
    source: "longshot_shadow_ladder",
    marketId: c.marketId,
    outcome: c.outcome,
    side: c.side,
    wallet: c.walletAddress,
    entryPrice: c.entryPrice,
    walletEntryPrice: c.walletEntryPrice,
    detectedPrice: c.detectedPrice,
    drift: Math.abs(c.entryPrice - c.walletEntryPrice),
    spread: c.spread ?? null,
    liquidity: c.liquidity ?? null,
    ttrHours: c.ttrHours ?? null,
    confidence: c.confidence,
    copyScore: c.copyScore,
    liveDecision: c.liveDecision,
    longshotFloorScore: c.longshotFloorScore ?? null,
    longshotFloorConf: c.longshotFloorConf ?? null,
    stakeUsd: SHADOW_STAKE_USD,
    wouldAdmit: verdict.wouldAdmit,
    blockers: verdict.blockers,
  };
  fs.appendFileSync(SHADOW_FILE, JSON.stringify(row) + "\n");
}

export interface ShadowSummary {
  generatedAt: string;
  candidates: number;
  wouldAdmit: number;
  admitsAwaitingResolution: number;
  resolved: number;
  wins: number;
  winRate: number | null;
  totalPnl: number;
  avgPnlPerTrade: number | null;
  stakeUsd: number;
  firstCandidateAt: string | null;
  lastCandidateAt: string | null;
}

export function readShadowRows(): Array<Record<string, unknown>> {
  try {
    return fs
      .readFileSync(SHADOW_FILE, "utf-8")
      .split("\n")
      .filter((l) => l.trim().length > 0)
      .map((l) => JSON.parse(l) as Record<string, unknown>);
  } catch {
    return [];
  }
}

/** Join candidate + resolve records into the shadow book summary. Pure-ish. */
export function summarizeShadow(rows: Array<Record<string, unknown>>): ShadowSummary {
  const candidates = rows.filter((r) => r.type === "candidate");
  const admits = candidates.filter((r) => r.wouldAdmit === true);
  const resolves = new Map<string, number>();
  for (const r of rows) {
    if (r.type === "resolve") {
      resolves.set(`${r.marketId}|${r.outcome}`, Number(r.value));
    }
  }
  let resolved = 0;
  let wins = 0;
  let totalPnl = 0;
  for (const a of admits) {
    const v = resolves.get(`${a.marketId}|${a.outcome}`);
    if (v === undefined) continue;
    resolved++;
    if (v > 0) wins++;
    const stake = Number(a.stakeUsd ?? SHADOW_STAKE_USD);
    const entry = Number(a.entryPrice);
    totalPnl += entry > 0 ? (v - entry) / entry * stake : 0;
  }
  const ts = candidates.map((r) => String(r.ts)).sort();
  return {
    generatedAt: new Date().toISOString(),
    candidates: candidates.length,
    wouldAdmit: admits.length,
    admitsAwaitingResolution: admits.length - resolved,
    resolved,
    wins,
    winRate: resolved ? wins / resolved : null,
    totalPnl: Math.round(totalPnl * 100) / 100,
    avgPnlPerTrade: resolved ? Math.round((totalPnl / resolved) * 100) / 100 : null,
    stakeUsd: SHADOW_STAKE_USD,
    firstCandidateAt: ts.length ? ts[0] : null,
    lastCandidateAt: ts.length ? ts[ts.length - 1] : null,
  };
}
