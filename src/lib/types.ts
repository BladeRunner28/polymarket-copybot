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
  marketCategory?: string;
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
  winningOutcome?: string;
  raw?: unknown;
}

export interface DataAdapter {
  readonly source: string;
  readonly isDemo: boolean;
  fetchLeaderboard(limit: number): Promise<LeaderboardEntry[]>;
  fetchWalletActivity(address: string, days: number): Promise<WalletActivityTrade[]>;
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
