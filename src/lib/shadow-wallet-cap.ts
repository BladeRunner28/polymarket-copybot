/**
 * Per-wallet ceiling shadow feed (2026-09-19 C-200 daily report rec 1a, approved).
 *
 * The v58 per-wallet ceiling (`maxWalletNotionalPctOfCap`) went live 2026-09-19
 * 13:25 CDT and binds HARD on the wallet that was already above it: the top
 * wallet holds ~$994 of a ~$431 ceiling, so every would-be copy from that wallet
 * is vetoed (109 in the first 15 h, 1-4 per cycle). Nobody knows what those
 * entries were worth, and the raw count overstates the cost (some would have
 * died on the 0.80 price cap or the drift gate anyway).
 *
 * This module is WRITE-ONLY instrumentation: it records the would-be copy (its
 * size, its entry price and band, the wallet's notional at that moment) and
 * scripts/mark-shadow-longshot.ts marks every candidate to settlement from the
 * same feed machinery, publishing data/wallet-cap-shadow-summary.json.
 *
 * NOTHING here changes behaviour: the ceiling value and its basis are a rule
 * decision (RuleSet), not a side effect of the instrument.
 */

import * as fs from "fs";
import { join } from "path";

export const WALLET_CAP_SHADOW_FILE = join(__dirname, "..", "..", "data", "wallet-cap-shadow.jsonl");
export const WALLET_CAP_SHADOW_SUMMARY_FILE = join(__dirname, "..", "..", "data", "wallet-cap-shadow-summary.json");

/** Same band edges the calibration table uses, so the read joins to it directly. */
export const BAND_EDGES: ReadonlyArray<[number, number]> = [
  [0, 0.2],
  [0.2, 0.4],
  [0.4, 0.6],
  [0.6, 0.8],
  [0.8, 1.01],
];

export function bandOf(price: number): string {
  for (const [lo, hi] of BAND_EDGES) if (price >= lo && price < hi) return `${lo}-${hi}`;
  return "other";
}

export interface WalletCapShadowCandidate {
  marketId: string;
  outcome: string;
  side: string;
  walletAddress: string;
  marketQuestion?: string;
  /** Executable-ish price the scorer would have copied at. */
  currentPrice: number;
  /** The size the copy WOULD have booked (Kelly/band sizing already applied). */
  sizeUsd: number;
  copyScore: number;
  confidence: number;
  ttrHours?: number;
  spread?: number;
  liquidity?: number;
  /** Wallet notional at decision time and the ceiling it was measured against. */
  walletNotionalUsd: number;
  ceilingUsd: number;
  /** Why the gate fired, verbatim from the leg block. */
  reason: string;
}

export function appendWalletCapShadow(c: WalletCapShadowCandidate): void {
  const row = {
    ts: new Date().toISOString(),
    type: "candidate",
    source: "per_wallet_cap",
    marketId: c.marketId,
    outcome: c.outcome,
    side: c.side,
    wallet: c.walletAddress,
    marketQuestion: c.marketQuestion ?? null,
    currentPrice: c.currentPrice,
    band: bandOf(c.currentPrice),
    sizeUsd: Math.round(c.sizeUsd * 100) / 100,
    copyScore: c.copyScore,
    confidence: c.confidence,
    ttrHours: c.ttrHours ?? null,
    spread: c.spread ?? null,
    liquidity: c.liquidity ?? null,
    walletNotionalUsd: Math.round(c.walletNotionalUsd * 100) / 100,
    ceilingUsd: Math.round(c.ceilingUsd * 100) / 100,
    reason: c.reason,
  };
  fs.appendFileSync(WALLET_CAP_SHADOW_FILE, JSON.stringify(row) + "\n");
}

export function readWalletCapRows(): Array<Record<string, unknown>> {
  try {
    return fs
      .readFileSync(WALLET_CAP_SHADOW_FILE, "utf-8")
      .split("\n")
      .filter((l) => l.trim().length > 0)
      .map((l) => JSON.parse(l) as Record<string, unknown>);
  } catch {
    return [];
  }
}

export interface WalletCapSummary {
  generatedAt: string;
  candidates: number;
  marked: number;
  awaitingResolution: number;
  wins: number;
  winRate: number | null;
  /** Sum of (settled value − entry)/entry × that row's own would-be size. */
  wouldHavePnl: number;
  avgPnlPerTrade: number | null;
  stakedUsd: number;
  byBand: Record<string, { n: number; marked: number; wouldHavePnl: number }>;
  byWallet: Record<string, { n: number; marked: number; wouldHavePnl: number }>;
  firstCandidateAt: string | null;
  lastCandidateAt: string | null;
}

export function summarizeWalletCap(rows: Array<Record<string, unknown>>): WalletCapSummary {
  const candidates = rows.filter((r) => r.type === "candidate");
  const resolves = new Map<string, number>();
  for (const r of rows) {
    if (r.type === "resolve") resolves.set(`${r.marketId}|${r.outcome}`, Number(r.value));
  }
  const byBand: WalletCapSummary["byBand"] = {};
  const byWallet: WalletCapSummary["byWallet"] = {};
  let marked = 0;
  let wins = 0;
  let pnl = 0;
  let staked = 0;
  for (const c of candidates) {
    const band = String(c.band ?? bandOf(Number(c.currentPrice)));
    const wallet = String(c.wallet ?? "?");
    const size = Number(c.sizeUsd ?? 0);
    const b = (byBand[band] ??= { n: 0, marked: 0, wouldHavePnl: 0 });
    const w = (byWallet[wallet] ??= { n: 0, marked: 0, wouldHavePnl: 0 });
    b.n++;
    w.n++;
    const v = resolves.get(`${c.marketId}|${c.outcome}`);
    if (v === undefined) continue;
    marked++;
    if (v > 0) wins++;
    const entry = Number(c.currentPrice);
    const rowPnl = entry > 0 ? ((v - entry) / entry) * size : 0;
    pnl += rowPnl;
    staked += size;
    b.marked++;
    b.wouldHavePnl += rowPnl;
    w.marked++;
    w.wouldHavePnl += rowPnl;
  }
  const round = (o: Record<string, { n: number; marked: number; wouldHavePnl: number }>) =>
    Object.fromEntries(
      Object.entries(o).map(([k, v]) => [k, { ...v, wouldHavePnl: Math.round(v.wouldHavePnl * 100) / 100 }])
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
    stakedUsd: Math.round(staked * 100) / 100,
    byBand: round(byBand),
    byWallet: round(byWallet),
    firstCandidateAt: ts.length ? ts[0] : null,
    lastCandidateAt: ts.length ? ts[ts.length - 1] : null,
  };
}
