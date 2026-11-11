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
 *
 * 2026-10-29 (card phil-counterfactual-ledger-primitive): the writer and the
 * summary math are the shared ones now. This lane's fill model is
 * `would_be_size` — the stake is the size the live path would have booked, which
 * is a DECLARED fill model rather than a lane-private stake constant.
 */

import {
  appendCounterfactualCandidate,
  groupStats,
  ledgerEntryPrice,
  priceBandOf,
  readLedger,
  summarizeLedger,
  COARSE_BAND_EDGES,
} from "./counterfactual-ledger";
import { join } from "path";

export const WALLET_CAP_SHADOW_FILE = join(__dirname, "..", "..", "data", "wallet-cap-shadow.jsonl");
export const WALLET_CAP_SHADOW_SUMMARY_FILE = join(__dirname, "..", "..", "data", "wallet-cap-shadow-summary.json");

/** Same band edges the calibration table uses, so the read joins to it directly. */
export const BAND_EDGES: ReadonlyArray<[number, number]> = COARSE_BAND_EDGES;

export function bandOf(price: number): string {
  return priceBandOf(price, BAND_EDGES);
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
  // The size the leg would have booked, rounded to cents BEFORE it is written, so
  // the canonical stake and the legacy `sizeUsd` field are the same number (the
  // pre-port summary priced the stored, rounded value).
  const sizeUsd = Math.round(c.sizeUsd * 100) / 100;
  appendCounterfactualCandidate({
    lane: "per_wallet_cap",
    file: WALLET_CAP_SHADOW_FILE,
    marketId: c.marketId,
    outcome: c.outcome,
    side: c.side,
    walletAddress: c.walletAddress,
    entryPrice: c.currentPrice,
    // The declined leg's own would-be size, not a fixed clip: the counterfactual
    // keeps asking what the veto cost, in the size the rail actually blocked.
    fill: { kind: "would_be_size", stakeUsd: sizeUsd },
    copyScore: c.copyScore,
    confidence: c.confidence,
    ttrHours: c.ttrHours ?? null,
    spread: c.spread ?? null,
    liquidity: c.liquidity ?? null,
    reason: c.reason,
    extras: {
      // Legacy field names kept verbatim.
      source: "per_wallet_cap",
      marketQuestion: c.marketQuestion ?? null,
      currentPrice: c.currentPrice,
      band: bandOf(c.currentPrice),
      sizeUsd: Math.round(c.sizeUsd * 100) / 100,
      walletNotionalUsd: Math.round(c.walletNotionalUsd * 100) / 100,
      ceilingUsd: Math.round(c.ceilingUsd * 100) / 100,
    },
  });
}

export function readWalletCapRows(): Array<Record<string, unknown>> {
  return readLedger(WALLET_CAP_SHADOW_FILE);
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
  /** ADDITIVE (2026-10-29): per-signal read of the same rows, from the shared basis. */
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

/**
 * VIEW of the shared counterfactual read. The stake is the row's own `sizeUsd`
 * (fill model `would_be_size`), so the aggregate PnL answers "what did the rail
 * cost in the sizes it blocked".
 */
export function summarizeWalletCap(rows: Array<Record<string, unknown>>): WalletCapSummary {
  const s = summarizeLedger(rows, { stakeField: "sizeUsd", defaultStakeUsd: 0 });
  return {
    generatedAt: new Date().toISOString(),
    candidates: s.candidates,
    marked: s.marked,
    awaitingResolution: s.awaitingResolution,
    wins: s.wins,
    winRate: s.winRate,
    wouldHavePnl: s.wouldHavePnl,
    avgPnlPerTrade: s.avgPnlPerTrade,
    stakedUsd: s.stakedUsd,
    byBand: groupStats(rows, (c) => String(c.band ?? bandOf(ledgerEntryPrice(c))), {
      stakeField: "sizeUsd",
      defaultStakeUsd: 0,
    }),
    byWallet: groupStats(rows, (c) => String(c.wallet ?? "?"), {
      stakeField: "sizeUsd",
      defaultStakeUsd: 0,
    }),
    basis: {
      bets: s.marked,
      signals: s.perOpportunity.signals,
      markets: s.perOpportunity.markets,
      wouldHavePnlPerSignal: s.perOpportunity.wouldHavePnlPerSignal,
      wouldHavePnlOneBetPerMarket: s.perOpportunity.wouldHavePnlOneBetPerMarket,
    },
    firstCandidateAt: s.firstCandidateAt,
    lastCandidateAt: s.lastCandidateAt,
  };
}
