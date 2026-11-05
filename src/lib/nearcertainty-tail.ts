/**
 * nearcertainty-tail — price the sub-0.05 candidates the near-certainty clause
 * refuses.
 *
 * WHY THIS EXISTS (roadmap card `nearcertainty-tail-shadow`, Backlog, Lane B):
 * `src/lib/scoring/trade.ts` hard-skips any entry whose price is
 * `> maxEntryPrice` OR `< 1 - maxEntryPrice` (v71: 0.95, so the live band is
 * 0.05–0.95) with the reason "price X near certainty — limited upside". The
 * 2026-10-12 longshot-flow-funnel census reported that this clause refused 100%
 * of the deepest slice of the band that carries the book (all 129 sub-0.05
 * candidates in its week). The clause has never been priced: nobody has asked
 * what those refused legs would have returned had they been copied.
 *
 * THE THREE THINGS THIS MODULE REFUSES TO LET A HEADLINE DO
 *   1. POLLS ARE NOT BETS. `shadow-lowconf.ts` taught this the hard way: one
 *      refused market is re-journalled on every scan, so row counts run ~10x the
 *      number of distinct positions (`dedupeToSignal`). Every rate below is
 *      reported on SIGNAL level, with the row count printed beside it.
 *   2. DUST IS NOT A TAIL. A mark at the 0.001 tick floor is not a 1-in-1000
 *      longshot you could buy — it is a dead market (or a mis-read token) and its
 *      per-$1 return would be +999. `NEARCERT_DUST_FLOOR` excludes it, and the
 *      caller prints the population at several floors so the reader can see how
 *      much of the read is floor dust rather than asking us to pick one.
 *   3. THE ARITHMETIC MEAN IS NOT A RETURN. A sub-0.05 book is 95% "-1" and 5%
 *      "+30"; its arithmetic mean can be positive while every compounding path
 *      is negative (the same geometry `ml-near-certainty-does-not-survive`
 *      documented). `geometricMeanPerLeg` and `breakevenWinRate` travel with
 *      every mean.
 *
 * NOTHING HERE TOUCHES A DECISION. No gate, threshold, rule, sizing input or
 * booking path imports this module; it is read-only arithmetic over rows the
 * pipeline already wrote. Relaxing the clause is Lane A and is not in here.
 */

import { summarizeReturns, perDollarReturn, type ReturnSummary } from "./slug-cap-blocks";

/** The live clause: `1 - rules.maxEntryPrice` (v71 maxEntryPrice = 0.95). */
export const NEARCERT_CHEAP_SIDE = 0.05;

/**
 * Below half a cent a "stake" is 200x leverage on a mark sitting on the venue's
 * 0.001 tick floor. Those rows are counted as dust, never priced.
 */
export const NEARCERT_DUST_FLOOR = 0.005;

/** Anchored on the exact string `src/lib/scoring/trade.ts` writes. */
const OPERAND_RE = /price ([\d.]+) near certainty \(band /;

/** Every risk string on one journal row (risksJson is a JSON array of strings). */
export function riskEntries(risksJson: string | null | undefined): string[] {
  if (!risksJson) return [];
  try {
    const v = JSON.parse(risksJson);
    return Array.isArray(v) ? v.map((x) => String(x)) : [];
  } catch {
    return [];
  }
}

/** The price the clause actually compared (its operand), or null if this row
 *  does not carry a near-certainty refusal. */
export function parseNearCertaintyOperand(risksJson: string | null | undefined): number | null {
  if (!risksJson) return null;
  const m = OPERAND_RE.exec(risksJson);
  if (!m) return null;
  const p = Number(m[1]);
  return Number.isFinite(p) ? p : null;
}

/**
 * Was the near-certainty clause the ONLY thing standing between this candidate
 * and a copy? If another gate also refused it, relaxing the clause admits
 * nothing and the leg must not be counted as forgone value.
 */
export function isSoleBlocker(entries: string[]): boolean {
  return entries.length === 1 && parseNearCertaintyOperand(JSON.stringify(entries)) !== null;
}

export type PriceBucket = "floor" | "0.005-0.02" | "0.02-0.05" | "0.05+";

/** Buckets that separate a buyable longshot from a dead-market tick-floor read. */
export function priceBucket(p: number): PriceBucket {
  if (p < NEARCERT_DUST_FLOOR) return "floor";
  if (p < 0.02) return "0.005-0.02";
  if (p < NEARCERT_CHEAP_SIDE) return "0.02-0.05";
  return "0.05+";
}

export type Liveness = "live" | "post-close" | "unknown";

/**
 * Was the decision stamped BEFORE the market closed?
 *
 * @returns "live" (the mark was tradeable), "post-close" (a poll of an already
 *          settled market — 0.000 marks and settled losers live here), or
 *          "unknown" when the market is closed but carries no readable clock.
 *          "unknown" is never coerced to live: a silent `true` is how a probe
 *          starts measuring settled dust as if it were tradeable.
 *
 * A market the venue still reports as OPEN cannot have been closed at decision
 * time — that is the only case where absence of a close time means "live"
 * (86 markets in the 2026-11-05 read are long-dated futures that settle in 2027).
 */
export function decisionLiveness(
  decidedAtMs: number,
  closed: boolean | null | undefined,
  closedTimeIso: string | null | undefined
): Liveness {
  if (closed !== true) return "live";
  const t = parseVenueClock(closedTimeIso);
  if (t === null) return "unknown";
  return decidedAtMs < t ? "live" : "post-close";
}

/**
 * The venue writes `2026-10-15 21:00:00+00` — a space separator and a 2-digit
 * offset. `Date.parse` returns NaN for BOTH, and a swallowed NaN here silently
 * turned every row into "clock unknown" (caught by `--self-test` on 2026-11-05).
 * A clock that cannot be read must be an explicit null, never a quiet true.
 */
export function parseVenueClock(iso: string | null | undefined): number | null {
  if (!iso) return null;
  let s = String(iso).trim().replace(" ", "T");
  if (/[+-]\d{2}$/.test(s)) s += ":00";
  // A clock with NO offset parses as the host's local time, silently shifting
  // every comparison by the machine's offset. The venue always sends one; if it
  // ever stops, UTC is the only defensible reading.
  else if (!/([zZ]|[+-]\d{2}:\d{2})$/.test(s)) s += "Z";
  const t = Date.parse(s);
  return Number.isFinite(t) ? t : null;
}

/** One refused candidate, at the level the funnel actually saw it. */
export interface NearCertCandidate {
  marketId: string;
  outcome: string;
  /** first live decision in the window for this market+outcome */
  decidedAtMs: number;
  /** the price the clause compared */
  operand: number;
  /** the observed trade's own price (may disagree with `operand`) */
  detectedPrice: number | null;
  soleBlocker: boolean;
}

/**
 * One leg per market+outcome: the EARLIEST live refusal is the moment a copy
 * would have been opened; every later row for the same token is the same
 * position polled again, not a second opportunity.
 */
export function dedupeToSignal<T extends { marketId: string; outcome: string; decidedAtMs: number }>(
  rows: T[]
): { legs: T[]; rows: number; inflation: number } {
  const first = new Map<string, T>();
  for (const r of rows) {
    const k = `${r.marketId}\u0000${r.outcome}`;
    const prev = first.get(k);
    if (!prev || r.decidedAtMs < prev.decidedAtMs) first.set(k, r);
  }
  const legs = [...first.values()].sort((a, b) => a.decidedAtMs - b.decidedAtMs);
  return { legs, rows: rows.length, inflation: legs.length ? rows.length / legs.length : 0 };
}

/** Per-$1 return at a stated entry, held to settlement. Delegates to the shared
 *  definition so this lane and the slug-cap lane can never drift apart. */
export function legReturn(entry: number | null | undefined, won: boolean): number | null {
  return perDollarReturn(entry, won);
}

/**
 * Win rate a cohort needs to break even at its own prices (per-$1 stake, held to
 * settlement, no fee): a leg bought at p returns (1-p)/p when it wins and -1 when
 * it loses, so E=0 at winRate = p.
 */
export function breakevenWinRate(entryPrices: number[]): number {
  const xs = entryPrices.filter((p) => Number.isFinite(p) && p > 0 && p <= 1);
  return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0;
}

/** Compounded per-leg growth: mean of log(1+r), exponentiated. A single -1 leg
 *  makes the product zero, which is the point (one wipe-out ends the series). */
export function geometricMeanPerLeg(returns: number[]): number | null {
  const xs = returns.filter((r) => Number.isFinite(r));
  if (xs.length === 0) return null;
  // A single -1 leg makes the compounded product zero — that IS the answer, and
  // dropping it (the obvious filter) would report a compounding path that does
  // not exist. Log growth is -infinity there, so the per-leg return is -1.
  if (xs.some((r) => r <= -1)) return -1;
  const s = xs.reduce((a, r) => a + Math.log(1 + r), 0) / xs.length;
  return Math.exp(s) - 1;
}

/** Expected per-$1 return of ONE INTENT once fills are priced: a maker order that
 *  never trades returns 0, so the intent's EV is reach x conditional return. */
export function evPerIntent(reach: number, conditionalReturn: number): number {
  return reach * conditionalReturn;
}

/** Share of the cohort's total positive return carried by its largest `k` legs. */
export function topKShare(returns: number[], k: number): number {
  const pos = returns.filter((r) => r > 0).sort((a, b) => b - a);
  const total = returns.filter((r) => r > 0).reduce((a, b) => a + b, 0);
  if (total <= 0) return 0;
  return pos.slice(0, k).reduce((a, b) => a + b, 0) / total;
}

export interface CohortRead extends ReturnSummary {
  /** mean entry price = the win rate this cohort must beat */
  breakevenWinRate: number;
  geometricMean: number | null;
  top5ShareOfWins: number;
}

/** Summarise one cohort of priced legs with the concentration companions welded on. */
export function summarizeCohort(legs: Array<{ entry: number; ret: number }>): CohortRead {
  const s = summarizeReturns(legs.map((l) => l.ret));
  return {
    ...s,
    breakevenWinRate: breakevenWinRate(legs.map((l) => l.entry)),
    geometricMean: geometricMeanPerLeg(legs.map((l) => l.ret)),
    top5ShareOfWins: topKShare(legs.map((l) => l.ret), 5),
  };
}
