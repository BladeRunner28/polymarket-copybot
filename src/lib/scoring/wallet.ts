/**
 * Wallet scoring: ROI, consistency, copyability, one-hit-wonder penalty,
 * category strengths. Pure functions — easy to test.
 */

import { WalletActivityTrade } from "../types";
import { Rules } from "../rules";

export interface WalletScore {
  roi30d: number;
  consistencyScore: number; // 0..100
  copyabilityScore: number; // 0..100
  oneHitWonderPenalty: number; // 0..100 (higher = worse)
  globalScore: number; // 0..100
  bestCategory: string | null;
  /** Keyed on `categoryBasis` — read it through the stored payload's own `basis`, never assumed. */
  categoryStrengths: Record<string, { trades: number; winRate: number; pnl: number }>;
  /** Diagnostic only (never feeds categoryFitScore): the same map at the FINE class grain. */
  categoryStrengthsFine: Record<string, { trades: number; winRate: number; pnl: number }>;
  /** Which dimension `categoryStrengths` / `bestCategory` are keyed on. */
  categoryBasis: WalletCategoryBasis;
  averageTradeSize: number;
  tradeCount30d: number;
  resolvedTradeCount30d: number;
  winRate30d: number;
  averageLiquidity: number;
  averageSpread: number;
  averageEntryTiming: number;
  copyabilityNotes: string;
  riskNotes: string;
}

/**
 * Which dimension the wallet's category strengths are bucketed on (v72, operator-approved
 * 2026-11-11). "token" is the RAW event-slug token — defective as a category (the token
 * `highest` spans 14,879 marketIds and `bestCategory` reads `will`/`what`/`world`), but it is
 * what every score published before v72 was built on, so it stays the default. "class" is
 * `marketCategoryClass` (src/lib/market-category.ts): 3 buckets/wallet vs 14, 33 trades/bucket
 * vs 2.5, 87-91% coverage vs 69-84%. Measured 2026-09-23: the class basis ranks leg outcomes at
 * chance in both lanes (C-200 coarse 0.487, fine 0.502; STANDARD coarse 0.493, fine 0.522), the
 * same null as the token basis — so this is a LABEL/consistency change, not an edge claim.
 */
export type WalletCategoryBasis = Rules["walletCategoryBasis"];

/** Bucket key for one trade under a basis; a missing/empty value lands in "uncategorized". */
export function categoryBucketKey(t: WalletActivityTrade, basis: WalletCategoryBasis): string {
  const raw = basis === "class" ? t.marketCategoryClass : t.marketCategory;
  return raw && raw.length > 0 ? raw : "uncategorized";
}

type StrengthMap = WalletScore["categoryStrengths"];

function strengthMap(trades: WalletActivityTrade[], keyOf: (t: WalletActivityTrade) => string): StrengthMap {
  const cats: Record<string, { trades: number; wins: number; pnl: number }> = {};
  for (const t of trades) {
    const c = keyOf(t);
    cats[c] ??= { trades: 0, wins: 0, pnl: 0 };
    cats[c].trades++;
    // SETTLEMENT basis (label-integrity-wallet-win-filter, operator-approved 2026-11-11):
    // a bucket win is the venue's settlement flag, not our exit sign. `won === undefined`
    // (a closed position whose mark is not terminal) is not a win, and it is not *defaulted*
    // to one either — see settledWinRate() for the same rule on the wallet denominator.
    if (t.resolved && t.won === true) cats[c].wins++;
    cats[c].pnl += t.pnl ?? 0;
  }
  const out: StrengthMap = {};
  for (const [c, v] of Object.entries(cats)) {
    out[c] = {
      trades: v.trades,
      winRate: v.trades ? v.wins / v.trades : 0,
      pnl: Math.round(v.pnl * 100) / 100,
    };
  }
  return out;
}

/**
 * The stored form of a wallet's category map. `basis` travels WITH the map because the two
 * generations coexist in WalletProfile (a swap only re-keys a wallet when the hourly scan
 * reaches it), and a reader that assumed a key space would silently look up a token in a
 * class map and find nothing.
 */
export interface CategoryStrengthsPayload {
  basis: WalletCategoryBasis;
  strengths: StrengthMap;
  fine?: StrengthMap;
}

export function encodeCategoryStrengths(score: WalletScore): string {
  const payload: CategoryStrengthsPayload = {
    basis: score.categoryBasis,
    strengths: score.categoryStrengths,
  };
  if (Object.keys(score.categoryStrengthsFine).length > 0) payload.fine = score.categoryStrengthsFine;
  return JSON.stringify(payload);
}

/**
 * Read a stored category map. Legacy rows are a BARE flat map written before v72 — they are
 * token-keyed by construction (that is what scoreWallet produced), so they decode to basis
 * "token" rather than being guessed at.
 */
export function decodeCategoryStrengths(json: string | null | undefined): CategoryStrengthsPayload {
  const empty: CategoryStrengthsPayload = { basis: "token", strengths: {} };
  if (!json) return empty;
  let parsed: unknown;
  try {
    parsed = JSON.parse(json);
  } catch {
    return empty;
  }
  if (!parsed || typeof parsed !== "object") return empty;
  const obj = parsed as Record<string, unknown>;
  if (obj.basis === "token" || obj.basis === "class") {
    const wrap = (v: unknown): StrengthMap =>
      v && typeof v === "object" ? (v as StrengthMap) : {};
    return {
      basis: obj.basis,
      strengths: wrap(obj.strengths),
      ...(obj.fine ? { fine: wrap(obj.fine) } : {}),
    };
  }
  return { basis: "token", strengths: parsed as StrengthMap };
}

/**
 * The category win rate that feeds `categoryFitScore` for ONE observation, read on the basis the
 * stored map was BUILT on (v72). Returns undefined — "no category information", which scoreTrade
 * maps to its neutral 50 — when the observation carries no value for that basis: a pre-2026-09-23
 * row has no class, and a wallet the hourly scan has not re-scored yet still holds a token map.
 */
export function categoryWinRateFor(
  payload: CategoryStrengthsPayload,
  obs: { marketCategory?: string | null; marketCategoryClass?: string | null }
): number | undefined {
  const key = payload.basis === "class" ? obs.marketCategoryClass : obs.marketCategory;
  if (!key) return undefined;
  return payload.strengths[key]?.winRate;
}

function clamp(v: number, lo = 0, hi = 100): number {
  return Math.min(hi, Math.max(lo, v));
}

/**
 * One-hit-wonder penalty: share of total positive PnL contributed by the
 * single best trade. If one trade made most of the money, the "edge" is
 * probably luck. 0 = evenly earned, 100 = all profit from one trade.
 */
export function oneHitWonderPenalty(trades: WalletActivityTrade[]): number {
  const wins = trades.filter((t) => t.resolved && (t.pnl ?? 0) > 0);
  if (wins.length === 0) return 100; // no proven wins at all
  if (wins.length === 1) return 90; // exactly one win — unproven
  const totalPos = wins.reduce((a, t) => a + (t.pnl ?? 0), 0);
  const best = Math.max(...wins.map((t) => t.pnl ?? 0));
  const share = totalPos > 0 ? best / totalPos : 1;
  // share 0.2 (even) -> ~0 penalty; share 0.9 -> heavy penalty
  return clamp(((share - 0.25) / 0.65) * 100);
}

/**
 * SETTLEMENT BASIS for every win-rate arm (label-integrity-wallet-win-filter, Lane A,
 * operator-approved 2026-11-11).
 *
 * The win-rate terms used to read `(pnl ?? 0) > 0` — OUR exit sign, which is one of the things
 * the bot is trying to predict. A leg we sold at a profit on a token that later settled to zero
 * counted as a win, and the row's own `won` flag (the venue's settlement read, set by
 * src/lib/adapters/polymarket.ts from a TERMINAL mark) was never consulted by the scorer at all.
 *
 * Denominator = resolved legs on which the venue can state an outcome at all (`won !== undefined`).
 * A closed position marked inside the terminal band is NOT evidence either way and is excluded —
 * never defaulted to a loss. Returns null when no leg carries a settlement read, so a caller can
 * tell "no evidence" from "lost everything".
 *
 * Unchanged on purpose (same approval): ROI, copyability, the one-hit-wonder penalty and the
 * `resolved` population that gates them. Those price what the wallet EARNED; only the win-rate
 * arms claim to price what it PREDICTED.
 */
export function settledWinRate(trades: WalletActivityTrade[]): number | null {
  const known = trades.filter((t) => t.resolved && t.won !== undefined);
  if (known.length === 0) return null;
  return known.filter((t) => t.won === true).length / known.length;
}

/** Consistency: steadiness of win rate and PnL distribution across resolved trades. */
export function consistencyScore(trades: WalletActivityTrade[]): number {
  const resolved = trades.filter((t) => t.resolved && t.pnl !== undefined);
  if (resolved.length < 3) return 10;
  // Win term on the SETTLEMENT basis; a sample with no knowable outcome contributes no wins
  // (0), which is the honest reading of "unproven" — the PnL-distribution terms are unchanged.
  const winRate = settledWinRate(trades) ?? 0;
  const pnls = resolved.map((t) => t.pnl ?? 0);
  const mean = pnls.reduce((a, b) => a + b, 0) / pnls.length;
  const std = Math.sqrt(pnls.reduce((a, b) => a + (b - mean) ** 2, 0) / pnls.length);
  // Coefficient-of-variation style: lower relative volatility = more consistent.
  const cov = mean > 0 ? std / mean : 5;
  const covScore = clamp(100 - cov * 20);
  const wrScore = clamp(winRate * 130 - 20); // 50% wr -> 45, 70% -> 71
  const volumeBonus = clamp(resolved.length * 3, 0, 20);
  return clamp(covScore * 0.4 + wrScore * 0.5 + volumeBonus * 0.5);
}

/**
 * Copyability: can WE realistically follow this wallet? Penalizes illiquid
 * markets, wide spreads, and very late entries (entering near resolution
 * means we'd get worse prices).
 */
export function copyabilityScore(trades: WalletActivityTrade[], rules: Rules): number {
  if (trades.length === 0) return 0;
  const withLiq = trades.filter((t) => t.liquidity !== undefined);
  const withSpread = trades.filter((t) => t.spread !== undefined);
  const avgLiq = withLiq.length
    ? withLiq.reduce((a, t) => a + (t.liquidity ?? 0), 0) / withLiq.length
    : 0;
  const avgSpread = withSpread.length
    ? withSpread.reduce((a, t) => a + (t.spread ?? 0), 0) / withSpread.length
    : 0.1;
  const liqScore = clamp((avgLiq / (rules.minLiquidity * 4)) * 100);
  const spreadScore = clamp(100 - (avgSpread / rules.maxSpread) * 50);
  // Extreme prices (<0.05 or >0.95) are hard to copy profitably.
  const extremeShare =
    trades.filter((t) => t.price < 0.05 || t.price > 0.95).length / trades.length;
  const priceScore = clamp(100 - extremeShare * 120);
  return clamp(liqScore * 0.4 + spreadScore * 0.35 + priceScore * 0.25);
}

export function scoreWallet(trades: WalletActivityTrade[], rules: Rules): WalletScore {
  const resolved = trades.filter((t) => t.resolved && t.pnl !== undefined);
  const invested = trades.reduce((a, t) => a + t.size, 0);
  const realized = resolved.reduce((a, t) => a + (t.pnl ?? 0), 0);
  const roi30d = invested > 0 ? realized / invested : 0;

  const cons = consistencyScore(trades);
  const copy = copyabilityScore(trades, rules);
  const penalty = oneHitWonderPenalty(trades);

  // ROI mapped to 0..100 (0% -> 40, +50% -> ~85, negative -> below 40)
  const roiScore = clamp(40 + roi30d * 90);

  let global =
    roiScore * rules.weightRoi + cons * rules.weightConsistency + copy * rules.weightCopyability;
  // Penalty scales global down by up to 60%.
  global = global * (1 - (penalty / 100) * 0.6);
  if (resolved.length < rules.minResolvedTrades) {
    global = Math.min(global, 40); // unproven wallets capped
  }

  // Category strengths. v72: the bucket DIMENSION is a rule field — token (legacy) or the real
  // coarse class. The fine class is always computed beside it as a diagnostic and never feeds
  // categoryFitScore.
  const basis: WalletCategoryBasis = rules.walletCategoryBasis === "class" ? "class" : "token";
  const categoryStrengths = strengthMap(trades, (t) => categoryBucketKey(t, basis));
  const categoryStrengthsFine = strengthMap(trades, (t) =>
    t.marketCategoryFine && t.marketCategoryFine.length > 0 ? t.marketCategoryFine : "uncategorized"
  );
  let bestCategory: string | null = null;
  let bestPnl = -Infinity;
  for (const [c, v] of Object.entries(categoryStrengths)) {
    // "uncategorized" is the absence of a category, never a strength to advertise.
    if (c === "uncategorized") continue;
    if (v.trades >= 2 && v.pnl > bestPnl) {
      bestPnl = v.pnl;
      bestCategory = c;
    }
  }

  const withLiq = trades.filter((t) => t.liquidity !== undefined);
  const withSpread = trades.filter((t) => t.spread !== undefined);

  const notes: string[] = [];
  const risks: string[] = [];
  if (penalty > 60) risks.push("Most profit came from one lucky trade");
  if (resolved.length < rules.minResolvedTrades) risks.push(`Only ${resolved.length} resolved trades — unproven`);
  if (copy < 40) risks.push("Trades markets that are hard to copy (illiquid or wide spread)");
  if (copy >= 60) notes.push("Trades liquid markets with tight spreads");
  if (cons >= 60) notes.push("Consistent win pattern across trades");
  if (bestCategory) notes.push(`${basis === "class" ? "Strongest class" : "Strongest category"}: ${bestCategory}`);

  return {
    roi30d,
    consistencyScore: Math.round(cons * 10) / 10,
    copyabilityScore: Math.round(copy * 10) / 10,
    oneHitWonderPenalty: Math.round(penalty * 10) / 10,
    globalScore: Math.round(clamp(global) * 10) / 10,
    bestCategory,
    categoryStrengths,
    categoryStrengthsFine,
    categoryBasis: basis,
    averageTradeSize: trades.length ? invested / trades.length : 0,
    tradeCount30d: trades.length,
    resolvedTradeCount30d: resolved.length,
    winRate30d: settledWinRate(trades) ?? 0,
    averageLiquidity: withLiq.length
      ? withLiq.reduce((a, t) => a + (t.liquidity ?? 0), 0) / withLiq.length
      : 0,
    averageSpread: withSpread.length
      ? withSpread.reduce((a, t) => a + (t.spread ?? 0), 0) / withSpread.length
      : 0,
    averageEntryTiming: 0.5, // refined when we have per-market resolution times
    copyabilityNotes: notes.join("; ") || "No notable strengths yet",
    riskNotes: risks.join("; ") || "No major risks flagged",
  };
}

export function walletStatus(score: WalletScore, rules: Rules): { status: string; reason: string } {
  if (score.globalScore >= rules.minWalletGlobalScore + 10 && score.oneHitWonderPenalty < 50) {
    return { status: "track", reason: `Global score ${score.globalScore} with balanced profits — worth following` };
  }
  if (score.globalScore >= rules.minWalletGlobalScore - 15) {
    return { status: "watch", reason: `Global score ${score.globalScore} — promising but not proven enough to track` };
  }
  return {
    status: "ignore",
    reason:
      score.oneHitWonderPenalty > 60
        ? `One-hit-wonder penalty ${score.oneHitWonderPenalty} — profit not repeatable`
        : `Global score ${score.globalScore} below threshold`,
  };
}
