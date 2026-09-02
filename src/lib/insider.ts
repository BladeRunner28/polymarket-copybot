/**
 * Insider/anomaly wallet scoring — reimplementation of homerun's
 * insider_detector.py components (AGPL-3.0, read-only reference; concepts
 * only, no code copied) on the copybot's own tables.
 *
 * 11 weighted components, each normalized to 0..1:
 *   win_rate 0.10 · timing_alpha 0.16 · roi 0.08 · brier 0.12 ·
 *   entry_resolution_edge 0.10 · concentration 0.07 · pre_news_timing 0.12 ·
 *   market_selection_edge 0.08 · drawdown 0.05 · cluster_correlation 0.08 ·
 *   funding_overlap 0.04 (no data → neutral 0.5)
 *
 * Score 0..1. Flags: watch ≥ 0.60 (needs ≥15 resolved trades), flagged ≥ 0.72
 * (needs ≥25). The pre-news-timing component is the copybot-specific gem: a
 * wallet that consistently trades BEFORE RegulatorySignals in the same
 * category is exactly the signal source worth copying.
 */

import { prisma } from "./db";
import { researchCategoryFor } from "./research-categories";

export const INSIDER_WEIGHTS = {
  winRate: 0.1,
  timingAlpha: 0.16,
  roi: 0.08,
  brier: 0.12,
  entryResolutionEdge: 0.1,
  concentration: 0.07,
  preNewsTiming: 0.12,
  marketSelectionEdge: 0.08,
  drawdown: 0.05,
  clusterCorrelation: 0.08,
  fundingOverlap: 0.04,
};

export const WATCH_THRESHOLD = 0.6;
export const FLAGGED_THRESHOLD = 0.72;
export const WATCH_MIN_TRADES = 15;
export const FLAGGED_MIN_TRADES = 25;

const clamp01 = (v: number) => Math.min(1, Math.max(0, v));

export interface InsiderComponents {
  winRate: number;
  timingAlpha: number;
  roi: number;
  brier: number;
  entryResolutionEdge: number;
  concentration: number;
  preNewsTiming: number;
  marketSelectionEdge: number;
  drawdown: number;
  clusterCorrelation: number;
  fundingOverlap: number;
}

export interface InsiderScoreResult {
  walletAddress: string;
  score: number;
  flagged: boolean;
  watch: boolean;
  nResolved: number;
  components: InsiderComponents;
}

export async function computeInsiderScore(
  walletAddress: string
): Promise<InsiderScoreResult | null> {
  const wallet = await prisma.walletProfile.findUnique({ where: { address: walletAddress } });
  if (!wallet) return null;

  const resolved = await prisma.paperTrade.findMany({
    where: { walletAddress, status: { in: ["closed", "resolved"] }, isDemo: false },
    select: { entryPrice: true, realizedPnl: true, openedAt: true, resolvedAt: true, marketId: true, outcome: true },
    orderBy: { resolvedAt: "asc" },
  });
  const nResolved = resolved.length;
  if (nResolved === 0) return null;

  // Recent observed trades (60d) for pre-news / concentration / cluster.
  const since = new Date(Date.now() - 60 * 86_400_000);
  const trades = await prisma.observedTrade.findMany({
    where: { walletAddress, timestamp: { gte: since }, isDemo: false },
    select: { marketId: true, outcome: true, marketCategory: true, marketQuestion: true, timestamp: true },
  });
  const totalTrades = trades.length || nResolved;
  // NOTE: ObservedTrade.marketCategory is NOT a research category — the API
  // payload fills it with garbage (outcome indexes, tickers like 'aapl').
  // Always derive the category from the question text with the same mapping
  // the scorer uses, so it lines up with RegulatorySignal categories.
  const categoryOf = (t: { marketQuestion: string }): string | undefined => researchCategoryFor(t.marketQuestion);

  // --- Components ---
  const wins = resolved.filter((t) => (t.realizedPnl ?? 0) > 0).length;
  const winRate = wins / nResolved;

  // Brier: per trade, (won − p)² → 0 perfect, 1 worst; component = 1 − brier.
  const brier = resolved.reduce((a, t) => {
    const p = Math.min(0.99, Math.max(0.01, t.entryPrice));
    const won = (t.realizedPnl ?? 0) > 0 ? 1 : 0;
    return a + (won - p) * (won - p);
  }, 0) / nResolved;
  const brierComponent = 1 - brier;

  // Entry-vs-resolution edge: mean |won − p| (edge captured per contract).
  const entryEdge =
    resolved.reduce((a, t) => {
      const won = (t.realizedPnl ?? 0) > 0 ? 1 : 0;
      return a + Math.abs(won - t.entryPrice);
    }, 0) / nResolved;

  // Timing alpha: wallet's stored averageEntryTiming (0 = very early, 1 = at
  // resolution) inverted — entering early on winners is the insider signature.
  const timingAlpha = clamp01(1 - (wallet.averageEntryTiming ?? 0.5));

  // ROI: roi30d is a fraction (e.g. 0.35 = 35%); 200%+ ROI saturates.
  const roi = clamp01((wallet.roi30d ?? 0) / 2);

  // Pre-news timing: share of observed trades within 24h BEFORE a
  // RegulatorySignal in the same category (trades at/after the news don't count).
  let preNews = 0;
  if (trades.length > 0) {
    const cats = [...new Set(trades.map((t) => categoryOf(t)).filter(Boolean))] as string[];
    if (cats.length > 0) {
      const signals = await prisma.regulatorySignal.findMany({
        where: { marketCategory: { in: cats }, processedAt: { gte: since } },
        select: { marketCategory: true, processedAt: true },
      });
      for (const t of trades) {
        const cat = categoryOf(t);
        if (!cat) continue;
        const before = signals.some(
          (s) =>
            s.marketCategory === cat &&
            s.processedAt.getTime() >= t.timestamp.getTime() &&
            s.processedAt.getTime() <= t.timestamp.getTime() + 24 * 3_600_000
        );
        if (before) preNews++;
      }
    }
  }
  const preNewsComponent = clamp01(preNews / Math.max(totalTrades, 1));

  // Concentration: 1 − HHI over markets (diversified = normal; low weight).
  const marketCounts = new Map<string, number>();
  for (const t of trades) marketCounts.set(t.marketId, (marketCounts.get(t.marketId) ?? 0) + 1);
  const hhi = [...marketCounts.values()].reduce((a, c) => a + (c / totalTrades) ** 2, 0);
  const concentration = clamp01(1 - hhi);

  // Market-selection edge: win rate − mean entry price (positive = beats fair).
  const avgEntry = resolved.reduce((a, t) => a + t.entryPrice, 0) / nResolved;
  const marketSelectionEdge = clamp01(winRate - avgEntry);

  // Drawdown behavior: worst cumulative realized PnL dip, normalized by $100.
  let cum = 0;
  let minCum = 0;
  for (const t of resolved) {
    cum += t.realizedPnl ?? 0;
    if (cum < minCum) minCum = cum;
  }
  const drawdown = clamp01(1 - Math.min(1, -minCum / 100));

  // Cluster correlation: share of the wallet's trades co-occurring (same
  // market+outcome within 1h) with OTHER tracked wallets' trades. Chunked to
  // stay under sqlite's parameter limit; the `not` filter is applied in JS.
  let cluster = 0;
  if (trades.length > 0) {
    const marketIds = [...new Set(trades.map((t) => t.marketId))];
    const others: Array<{ marketId: string; outcome: string; timestamp: Date }> = [];
    for (let i = 0; i < marketIds.length; i += 400) {
      const chunk = marketIds.slice(i, i + 400);
      const rows = await prisma.observedTrade.findMany({
        where: {
          marketId: { in: chunk },
          timestamp: { gte: new Date(Date.now() - 24 * 3_600_000) },
        },
        select: { walletAddress: true, marketId: true, outcome: true, timestamp: true },
      });
      others.push(...rows.filter((r) => r.walletAddress !== walletAddress));
    }
    for (const t of trades) {
      const co =
        others.some(
          (o) =>
            o.marketId === t.marketId &&
            o.outcome === t.outcome &&
            Math.abs(o.timestamp.getTime() - t.timestamp.getTime()) < 3_600_000
        );
      if (co) cluster++;
    }
  }
  const clusterCorrelation = clamp01(cluster / Math.max(totalTrades, 1));

  // Funding-overlap proxy: no wallet-funding data → neutral.
  const fundingOverlap = 0.5;

  const components: InsiderComponents = {
    winRate: clamp01(winRate),
    timingAlpha,
    roi,
    brier: brierComponent,
    entryResolutionEdge: clamp01(entryEdge),
    concentration,
    preNewsTiming: preNewsComponent,
    marketSelectionEdge,
    drawdown,
    clusterCorrelation,
    fundingOverlap,
  };

  const score = Object.entries(INSIDER_WEIGHTS).reduce(
    (a, [k, w]) => a + w * (components[k as keyof InsiderComponents] ?? 0),
    0
  );

  const watch = score >= WATCH_THRESHOLD && nResolved >= WATCH_MIN_TRADES;
  const flagged = score >= FLAGGED_THRESHOLD && nResolved >= FLAGGED_MIN_TRADES;

  return { walletAddress, score, flagged, watch, nResolved, components };
}
