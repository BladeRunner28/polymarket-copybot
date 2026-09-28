/** Shared domain types for adapters and engines. */

import type { DataProvenance } from "./provenance";
import type { PrintFilterReport } from "./print-types";

export interface LeaderboardEntry {
  address: string;
  label?: string;
  rank: number;
  pnl?: number;
  volume?: number;
  /**
   * Where this row came from and whether it lags the live tape. Additive label
   * (src/lib/provenance.ts) — no consumer is required to read it, and nothing
   * may present a lagged row as live.
   */
  provenance?: DataProvenance;
  raw?: unknown;
}

export interface WalletActivityTrade {
  marketId: string;
  conditionId?: string;
  marketQuestion: string;
  /**
   * RAW event-slug token (first dash-segment). Deliberately kept as-is: the v45
   * per-bot blacklist and the per-slug position cap are defined on this
   * granularity. Do NOT read it as a category — see marketCategoryClass.
   */
  marketCategory?: string;
  /** Real market category (coarse bucket) — src/lib/market-category.ts. */
  marketCategoryClass?: string;
  /** Real market category at league/market-type grain. */
  marketCategoryFine?: string;
  outcome: string; // "YES" | "NO" | token label
  side: "BUY" | "SELL";
  price: number; // 0..1
  size: number; // USD
  timestamp: Date;
  resolved?: boolean;
  won?: boolean; // only meaningful when resolved
  pnl?: number; // realized PnL if resolved
  liquidity?: number;
  spread?: number;
  /** Source + lag label (src/lib/provenance.ts). Additive; never claims a duration. */
  provenance?: DataProvenance;
  raw?: unknown;
}

export interface MarketState {
  marketId: string;
  conditionId?: string;
  question: string;
  category?: string;
  yesPrice?: number;
  noPrice?: number;
  bestBid?: number;
  bestAsk?: number;
  spread?: number;
  liquidity?: number;
  volume?: number;
  /**
   * Trailing 24h volume in USD, when the venue reports it. Distinct from
   * `volume` (lifetime). The market-hygiene shadow scores read this one.
   */
  volume24hr?: number;
  /** hours until expected resolution; null/undefined if unknown */
  timeToResolutionHours?: number;
  resolved?: boolean;
  /**
   * Winning token's label as the venue reports it ("Yes", "Under", "Vitality").
   * Prefer this over `winningOutcome` + a label comparison: guessing YES/NO is
   * what booked 70 phantom losses (see src/lib/resolution.ts).
   */
  winningLabel?: string;
  /** Legacy alias — same value as winningLabel (kept for existing call sites). */
  winningOutcome?: string;
  /** The market's token labels in price order, when the venue provides them. */
  outcomeLabels?: string[];
  /** Token prices in the same order as outcomeLabels. */
  outcomePrices?: number[];
  /** Source + lag label (src/lib/provenance.ts). */
  provenance?: DataProvenance;
  /**
   * Which Gamma slug endpoint produced this market object. Recorded because the
   * legacy offset endpoint is past its announced sunset (2026-05-01) and we fall
   * back to it only when the current `/markets/slug/{slug}` contract fails —
   * a silent fallback would hide a live-compat regression.
   */
  gammaEndpoint?: "slug" | "legacy";
  raw?: unknown;
}

/**
 * wallet-depth-field-clamp (2026-09-23): the true size of a wallet's position
 * record, measured past the scanner's sampling ceilings. `censored` means the
 * walk hit its own budget, so the counts are lower bounds — stored as such.
 */
export interface WalletDepth {
  closedCount: number;
  openCount: number;
  totalCount: number;
  closedCensored: boolean;
  openCensored: boolean;
  censored: boolean;
  capNote: string;
  requests: number;
}

export interface DataAdapter {
  readonly source: string;
  readonly isDemo: boolean;
  fetchLeaderboard(limit: number): Promise<LeaderboardEntry[]>;
  /**
   * `onPrintFilter` is an optional observer for the client-side print-type guard
   * (audit §P6): it fires only when a non-fill row was dropped, so callers that
   * pass it can report the event, and callers that don't are unaffected by it.
   */
  fetchWalletActivity(
    address: string,
    days: number,
    onPrintFilter?: (report: PrintFilterReport) => void
  ): Promise<WalletActivityTrade[]>;
  /**
   * Depth of the wallet's position record, INDEPENDENT of the scoring sample.
   * `sample` carries what fetchWalletActivity returned so a wallet below the
   * sampling ceilings costs no extra requests.
   */
  fetchWalletDepth(
    address: string,
    sample: { closed: number; open: number }
  ): Promise<WalletDepth>;
  fetchMarket(marketId: string): Promise<MarketState>;
}

/** Error thrown when a live API fails. Never swallowed, never faked. */
export class AdapterError extends Error {
  constructor(
    public readonly endpoint: string,
    public readonly status: number | null,
    message: string
  ) {
    super(`[${endpoint}] ${message}${status !== null ? ` (HTTP ${status})` : ""}`);
    this.name = "AdapterError";
  }
}
