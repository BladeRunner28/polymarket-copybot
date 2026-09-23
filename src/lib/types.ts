/** Shared domain types for adapters and engines. */

export interface LeaderboardEntry {
  address: string;
  label?: string;
  rank: number;
  pnl?: number;
  volume?: number;
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
  fetchWalletActivity(address: string, days: number): Promise<WalletActivityTrade[]>;
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
