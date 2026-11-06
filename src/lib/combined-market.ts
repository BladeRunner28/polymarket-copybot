/**
 * combined-market — the identity of a market that cannot be copied: one with NO SLUG.
 *
 * WHY THIS EXISTS (roadmap card `parlay-rows-in-decision-path`, Lane B, 2026-11-05):
 * Polymarket "AND" parlays (combined markets) arrive on the wallet tape with an EMPTY
 * marketId. Before tuning #64 they were journalled and scored like single markets: the
 * market fetch had no slug to resolve, `currentPrice` fell back to `detectedPrice`, and
 * the gate stack returned verdicts ("price drifted 0.217 since entry") about a price
 * nobody could trade. This module names that class ONCE so no instrument has to
 * re-derive it ad hoc, and so the next run cannot mistake a text match for the identity.
 *
 * THE TEXT RULE IS NOT THE CLASSIFIER — MEASURED, NOT ASSUMED.
 * A `" AND "` substring test looks obvious and is wrong. ObservedTrade, isDemo=0,
 * 30d window ending 2026-11-05T20:08Z: 164,670 rows carry " AND " in the question AND
 * a real slug. They are ordinary English ("between $1.75T and $2.00T", "between 37m
 * and 40m") and equally genuine compound markets that DO settle on their own slug
 * ("Will Ann Kao win Hsinchu City and Cheng Chao-fang win Hsinchu County?"). Only an
 * EMPTY slug identifies a leg the pipeline cannot price or resolve. See
 * `textAndLookalike` below, which the census prints as a control so the false-positive
 * class stays visible rather than being rediscovered.
 *
 * NOTHING HERE DECIDES ANYTHING. No gate, threshold, sizing input or booking path
 * imports this module: the intake exclusion it describes was already approved (tuning
 * #64 Rec 1) and is implemented in scripts/monitor-trades.ts. This is the naming and
 * the arithmetic behind the census in scripts/combined-market-census.ts.
 */

export type MarketIdentity = { marketId?: string | null };

/**
 * The intake exclusion epoch. Commit 35e42c0 (tuning #64 Rec 1), authored
 * 2026-10-23T21:55:48-05:00 = 2026-10-24T02:55:48Z, is the moment blank-marketId rows
 * stopped being stored as copyable. A decision journalled on an unsluggable row AFTER
 * this instant is a regression, not history — `isLeak` is what makes that falsifiable.
 */
export const INTAKE_EXCLUSION_EPOCH = "2026-10-24T02:55:48Z";

/** A slug is the only handle a market can be fetched, priced and settled by. */
export function isUnsluggableMarket(m: MarketIdentity): boolean {
  const id = m.marketId;
  return id === undefined || id === null || id.trim() === "";
}

export type IngestClassification = {
  /** the leg can never be priced or resolved: no slug */
  untradeable: boolean;
  /** stored observation-only, so no reader may copy it */
  excludedAtIntake: boolean;
  /** untradeable AND still copyable — the defect `tuning #64` closed */
  leakedAsCopyable: boolean;
};

export function classifyIngestRow(row: MarketIdentity & { observationOnly?: boolean | null }): IngestClassification {
  const untradeable = isUnsluggableMarket(row);
  const excludedAtIntake = row.observationOnly === true;
  return { untradeable, excludedAtIntake, leakedAsCopyable: untradeable && !excludedAtIntake };
}

export function decisionEra(createdAt: Date | string | number, epoch: string = INTAKE_EXCLUSION_EPOCH): "pre-fix" | "post-fix" {
  const t = createdAt instanceof Date ? createdAt.getTime() : typeof createdAt === "number" ? createdAt : Date.parse(createdAt);
  return t < Date.parse(epoch) ? "pre-fix" : "post-fix";
}


/**
 * Control, not a classifier: does the question text contain a top-level " AND "?
 * Kept so the census can print how many rows this naive rule would wrongly sweep in.
 * NEVER use this to exclude a leg — it catches "between 37m and 40m".
 */
export function textAndLookalike(question: string | null | undefined): boolean {
  return typeof question === "string" && / AND /.test(question);
}

export type UnsluggableLeg = {
  botId: string;
  size: number;
  realizedPnl: number | null;
  entryPrice: number;
  outcome: string;
};

export type LegSummary = {
  legs: number;
  staked: number;
  bookedPnl: number;
  /** share of staked that was booked as a total loss */
  lossShare: number;
  /** legs whose outcome label is empty — no venue label, so no settlement basis */
  blankOutcome: number;
  byBot: Record<string, { legs: number; staked: number; pnl: number }>;
};

/**
 * One row per booked leg, never one row per decision: 38 paper_copy decisions produced 40
 * legs here because two lanes book the same signal, and reading decisions as legs is how
 * this class gets counted twice.
 */
export function summarizeUnsluggableLegs(legs: UnsluggableLeg[]): LegSummary {
  const byBot: Record<string, { legs: number; staked: number; pnl: number }> = {};
  let staked = 0;
  let bookedPnl = 0;
  let blankOutcome = 0;
  for (const l of legs) {
    const pnl = l.realizedPnl ?? 0;
    staked += l.size;
    bookedPnl += pnl;
    if (!l.outcome || l.outcome.trim() === "") blankOutcome++;
    const b = (byBot[l.botId] ??= { legs: 0, staked: 0, pnl: 0 });
    b.legs++;
    b.staked += l.size;
    b.pnl += pnl;
  }
  return {
    legs: legs.length,
    staked: round2(staked),
    bookedPnl: round2(bookedPnl),
    // `+ 0` collapses the -0 that a zero booked PnL produces (Object.is(-0, 0) is false,
    // and a test asserting "0.0% loss share" must not fail on the sign of nothing).
    lossShare: staked > 0 ? round4(-bookedPnl / staked) + 0 : 0,
    blankOutcome,
    byBot: Object.fromEntries(Object.entries(byBot).map(([k, v]) => [k, { legs: v.legs, staked: round2(v.staked), pnl: round2(v.pnl) }])),
  };
}

function round2(x: number): number { return Math.round(x * 100) / 100; }
function round4(x: number): number { return Math.round(x * 10000) / 10000; }
