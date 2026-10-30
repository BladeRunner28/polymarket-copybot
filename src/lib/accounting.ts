/**
 * accounting — THE canonical definition of how a lane's paper book is measured.
 *
 * WHY THIS MODULE EXISTS: the project had at least two accounting paths, and they disagreed.
 * The standing "-3.92% take-all ROI" did not reproduce from the files it named (an independent
 * re-cut read +2.69% on STANDARD and +16.13% all-lane over 90d). A neighbouring review's band
 * table was built by hand in a different script with a different cost basis. When two paths
 * measure the same book, the number that surfaces is whichever script ran last.
 *
 * The ML lane makes this urgent: it exists to be compared AGAINST the copy lanes, and a
 * comparison across two accounting implementations is worthless. So there is one definition,
 * here, and both arms call it.
 *
 * THE FOUR INVARIANTS. Each of these has been violated at least once in this repo's history,
 * which is why each is a test in tests/accounting.test.ts rather than a comment:
 *
 *   1. COST BASIS IS DOLLARS. `PaperTrade.simulatedPositionSize` is USD at risk (schema comment:
 *      "USD, always 5..20"), NOT a share count. Multiplying it by entryPrice understates cost and
 *      inflates ROI — that bug produced a +407% cheap-band read against a true +47.75%, and it is
 *      the single most dangerous error available here because the wrong answer looks like success.
 *
 *   2. BOTH TERMINAL STATUSES COUNT. `closed` = exited early (stale-exit, adverse move);
 *      `resolved` = held to settlement. A lane's PnL is the OR of both. Counting only `resolved`
 *      silently drops every discretionary exit and flatters a lane that bails out of losers.
 *
 *   3. DEDUPE TO THE FIRST LEG PER (bot, wallet, market, outcome). A wallet that trades one
 *      market/outcome repeatedly gets copied repeatedly, and every copy is a separate PaperTrade
 *      row. Summing them double-counts one bet as many; the published tables all dedupe first.
 *
 *   4. CONFIDENCE INTERVALS CLUSTER BY MARKET, NOT BY LEG. Legs inside one market share an
 *      outcome, so their errors are not independent — a leg-clustered CI is too narrow and
 *      manufactures significance. Resampling markets is the only honest interval.
 *
 * Anything computing lane ROI, cost, or a CI for either arm must call this module. The Python
 * reports (scripts/profit-band-report.py) implement the same four invariants and are checked
 * against this module's output; if they diverge, this one is right.
 */

import { prisma } from "./db";
import { positionIdentityKey } from "./outcome-identity";

/** One deduped paper leg, with the two quantities every downstream number is built from. */
export interface LaneLeg {
  walletAddress: string;
  marketId: string;
  outcome: string;
  /** USD at risk — PaperTrade.simulatedPositionSize. NEVER multiplied by entryPrice. */
  cost: number;
  /** Realised PnL in USD (0 when null/absent). */
  pnl: number;
  entryPrice: number;
  openedAt: Date;
  /** resolvedAt ?? closedAt — whichever terminal timestamp exists. */
  doneAt: Date | null;
}

export interface LaneSummary {
  legs: number;
  notional: number;
  pnl: number;
  /** pnl / notional as a percentage. NaN when notional is 0 (never silently 0). */
  roi: number;
  medianHoldDays: number;
}

/** Terminal statuses that represent a finished leg. See invariant 2. */
export const TERMINAL_STATUSES = ["closed", "resolved"] as const;

/**
 * Dedupe to the first leg per (wallet, market, outcome), preserving input order.
 * Pure so it can be tested without a database. Callers must pass rows ordered by openedAt ASC.
 */
export function dedupeFirstLeg<T extends { walletAddress: string; marketId: string; outcome: string }>(
  rows: T[]
): T[] {
  const seen = new Set<string>();
  const out: T[] = [];
  for (const r of rows) {
    const k = positionIdentityKey(r.walletAddress, r.marketId, r.outcome);
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(r);
  }
  return out;
}

export function summarise(legs: LaneLeg[]): LaneSummary {
  let notional = 0;
  let pnl = 0;
  const holds: number[] = [];
  for (const l of legs) {
    notional += l.cost;
    pnl += l.pnl;
    if (l.doneAt && l.openedAt) holds.push((l.doneAt.getTime() - l.openedAt.getTime()) / 86_400_000);
  }
  holds.sort((a, b) => a - b);
  return {
    legs: legs.length,
    notional,
    pnl,
    roi: notional ? (pnl / notional) * 100 : NaN,
    medianHoldDays: holds.length ? holds[Math.floor(holds.length / 2)] : NaN,
  };
}

/**
 * Market-clustered bootstrap of lane ROI. See invariant 4.
 * Resamples MARKETS with replacement, carrying each market's legs, so within-market correlation
 * is preserved. Deterministic given `seed`, so tests and re-runs agree exactly.
 */
export function clusterBootstrapCI(
  legs: LaneLeg[],
  opts: { iterations?: number; alpha?: number; seed?: number } = {}
): { point: number; lo: number; hi: number; markets: number } {
  const iterations = opts.iterations ?? 2000;
  const alpha = opts.alpha ?? 0.05;

  const byMarket = new Map<string, LaneLeg[]>();
  for (const l of legs) {
    const arr = byMarket.get(l.marketId);
    if (arr) arr.push(l);
    else byMarket.set(l.marketId, [l]);
  }
  const clusters = [...byMarket.values()];
  const point = summarise(legs).roi;
  if (!clusters.length) return { point, lo: NaN, hi: NaN, markets: 0 };

  // mulberry32 — small deterministic PRNG, so this needs no dependency and tests are stable
  let s = (opts.seed ?? 0x9e3779b9) >>> 0;
  const rnd = () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };

  const rois: number[] = [];
  for (let i = 0; i < iterations; i++) {
    let n = 0;
    let p = 0;
    for (let j = 0; j < clusters.length; j++) {
      const c = clusters[Math.floor(rnd() * clusters.length)];
      for (const l of c) {
        n += l.cost;
        p += l.pnl;
      }
    }
    if (n > 0) rois.push((p / n) * 100);
  }
  rois.sort((a, b) => a - b);
  const at = (q: number) => rois[Math.min(rois.length - 1, Math.max(0, Math.floor(q * rois.length)))];
  return { point, lo: at(alpha / 2), hi: at(1 - alpha / 2), markets: clusters.length };
}

/**
 * Load one lane's deduped, finished paper book through the canonical rules.
 * Every caller gets the same population: terminal statuses only, isDemo excluded, first leg per
 * (wallet, market, outcome).
 */
export async function loadLaneLegs(
  botId: string,
  opts: { since?: Date; until?: Date } = {}
): Promise<LaneLeg[]> {
  const rows = await prisma.paperTrade.findMany({
    where: {
      botId,
      isDemo: false,
      status: { in: [...TERMINAL_STATUSES] },
      ...(opts.since || opts.until
        ? {
            openedAt: {
              ...(opts.since ? { gte: opts.since } : {}),
              ...(opts.until ? { lte: opts.until } : {}),
            },
          }
        : {}),
    },
    select: {
      walletAddress: true,
      marketId: true,
      outcome: true,
      simulatedPositionSize: true,
      realizedPnl: true,
      entryPrice: true,
      openedAt: true,
      resolvedAt: true,
      closedAt: true,
    },
    orderBy: { openedAt: "asc" },
  });

  return dedupeFirstLeg(rows).map((r) => ({
    walletAddress: r.walletAddress,
    marketId: r.marketId,
    outcome: r.outcome,
    cost: r.simulatedPositionSize ?? 0,
    pnl: r.realizedPnl ?? 0,
    entryPrice: r.entryPrice ?? 0,
    openedAt: r.openedAt,
    doneAt: r.resolvedAt ?? r.closedAt ?? null,
  }));
}

/** Convenience: the whole measurement in one call. */
export async function laneReport(
  botId: string,
  opts: { since?: Date; until?: Date; iterations?: number } = {}
): Promise<LaneSummary & { ciLo: number; ciHi: number; markets: number }> {
  const legs = await loadLaneLegs(botId, opts);
  const s = summarise(legs);
  const ci = clusterBootstrapCI(legs, { iterations: opts.iterations });
  return { ...s, ciLo: ci.lo, ciHi: ci.hi, markets: ci.markets };
}
