/**
 * standard-fill-stamp — the STANDARD lane's FILL BOOTH: what entry was actually
 * attainable at the decision, in cents, as a distribution.
 *
 * WHY THIS EXISTS (card `t_7560e0d0`, Lane B measurement only)
 * STANDARD books `entryPrice = currentPrice` — a quote read at scoring time
 * (scripts/score-trades.ts:431-447 → src/lib/paper.ts:openPaperTrade) — and it
 * books it with NO fill model at all: p(fill) = 1, price = the quote it read.
 * C-200 was given a fill model on 2026-10-10 and 61% of its booked PnL turned out
 * to sit on legs that never filled. STANDARD has never had that test. The
 * profit-recs 2026-10-29 #1 priced a 1c better entry at +$1,439.33 on the last
 * 90 days' settled notional (5.0% of notional against a 90d realised +8.1%), so
 * the difference between "we can get a cent better" and "we cannot" is 62% of the
 * lane's 90-day profit. This module is the measurement that decides it.
 *
 * WHAT IT IS NOT
 * It changes nothing: no rule, no size, no gate, no booked row. Nothing in the
 * trade path imports it. It is the evidence a Lane A booking change would be
 * decided on, and the card's decision rule is pre-registered:
 *
 *   ship a booking change only once stamped fills exist on >= 300 STANDARD legs;
 *   the claim "a 1c improvement is worth +$1,439.33" is REFUTED if stamped fills
 *   land within ±0.3c of the mid on >= 300 legs.
 *
 * THE ONE READING THAT MUST TRAVEL WITH EVERY NUMBER
 * "Attainable" is REACHABILITY, not a fill: a best ask at or below a price means
 * a seller was willing there, ignoring queue position and ignoring size (a
 * resting bid is swept only up to the printed size). And `min-ask within a lag
 * window` is an OPTIMISTIC bound by construction: it takes the best price of the
 * whole window with hindsight, so a human who waited for it might have waited in
 * vain. The `first-snapshot` row is the one with no waiting and no hindsight.
 *
 * SIGN CONVENTION (the whole card): every delta is (attainable − decision), in
 * CENTS. POSITIVE = the entry we could actually get was WORSE than the price
 * STANDARD booked. NEGATIVE = better than booked. The rec's claim is a large
 * negative mean; the refutation fires when the stamp lands near zero.
 *
 * TWO SOURCES, NEVER POOLED, EACH WITH ITS OWN COVERAGE
 *   book — our own L2 corpus, data/l2/<assetId>.jsonl (top-25 ladder, 5s cadence).
 *          The direct test: the best ASK in the window is a price we could have
 *          lifted, and the snapshot's own bid/ask gives the MID, which is what the
 *          refutation is worded against.
 *   tape — venue prints from data-api (scripts/standard-fill-stamp.ts fetches
 *          them). Weaker by construction: a print is a trade that happened, not a
 *          quote you could have hit, and it carries no mid — so the tape arm can
 *          only speak to price-vs-decision, never to the ±0.3c-of-mid test, and it
 *          is reported exactly that way.
 * Neither source is assumed complete; `coverageOf` reports each one honestly, and a
 * leg with no evidence is excluded from every rate — never counted as "no fill".
 */

import { LEVEL_EPS, type CreditMode, resolveFill, type ResolutionLeg } from "./c200-fill-resolution";

/**
 * STANDARD applies no credit: the level it books IS the decision price, so the
 * shared resolver answers the STANDARD question in mode `none` (level = intent).
 */
export const STANDARD_CREDIT_MODE: CreditMode = "none";

/** The pre-registered gate and tolerance of the card's decision rule. */
export const GATE_LEGS = 300;
export const MID_BAND_C = 0.3;

/**
 * Decision-lag buckets: how long after the decision we allow the entry to work.
 * Upper bounds in ms, half-open (lo, hi]. The first bucket is deliberately tiny —
 * that is a taker submitting now, with no patience and no hindsight.
 */
export interface StampLagBucket {
  maxMs: number;
  label: string;
}

export const STAMP_LAG_BUCKETS: ReadonlyArray<StampLagBucket> = [
  { maxMs: 10_000, label: "0-10s" },
  { maxMs: 30_000, label: "10-30s" },
  { maxMs: 60_000, label: "30-60s" },
  { maxMs: 300_000, label: "1-5m" },
  { maxMs: 1_800_000, label: "5-30m" },
  { maxMs: 3_600_000, label: "30-60m" },
];

/** The widest bucket — the leg's own 1h horizon, used for the gate count. */
export const WIDEST_BUCKET = STAMP_LAG_BUCKETS[STAMP_LAG_BUCKETS.length - 1].label;

/** One observed attainable price inside one lag bucket. */
export interface StampObservation {
  /** Attainable price: min ask (book) or min print (tape). */
  price: number;
  /** Mid at the snapshot that produced `price`. Book only; null on the tape arm. */
  mid: number | null;
}

/** Book evidence for one leg, our own L2 corpus. */
export interface StampBookEvidence {
  /** First snapshot at/after the decision, minus the decision, ms. */
  coverLagMs: number;
  /**
   * True when the market's two outcome tokens were equidistant from the decision
   * price, so "which token is ours" was a coin flip. Those legs are still stamped
   * (the asks of the two tokens are near-complementary) but a reader must know.
   */
  tokenAmbiguous: boolean;
  /** Best ask / best bid at the first snapshot at/after the decision — no waiting. */
  firstAsk: number;
  firstBid: number;
  /** bucket label -> the best (lowest) ask reachable inside it, or null. */
  byBucket: Record<string, StampObservation | null>;
}

/** Tape evidence for one leg, venue prints (data-api). */
export interface StampTapeEvidence {
  /** Prints for OUR token at/after the decision and inside the widest bucket. */
  prints: number;
  /** bucket label -> the lowest print inside it, or null. */
  byBucket: Record<string, StampObservation | null>;
}

/** One STANDARD leg as it enters the booth. */
export interface StampLeg {
  /** PaperTrade.id — the join key back to the booked leg. */
  id: string;
  /** The price STANDARD booked (PaperTrade.entryPrice) = the price it decided at. */
  decisionPrice: number;
  sizeUsd: number;
  book: StampBookEvidence | null;
  tape: StampTapeEvidence | null;
}

export type StampSource = "book" | "tape";

/** (attainable − decision) in CENTS; positive = worse than booked. */
export function deltaCents(attainable: number, decision: number): number {
  return Math.round((attainable - decision) * 100 * 10_000) / 10_000;
}

/** The bucket a coverage lag falls in (label of the first bucket that contains it). */
export function bucketForLag(ms: number): string {
  for (const b of STAMP_LAG_BUCKETS) if (ms <= b.maxMs) return b.label;
  return WIDEST_BUCKET;
}

/** Nearest-rank quantile on an already-sorted array (0 when empty handled by caller). */
function quantileSorted(sorted: number[], p: number): number {
  if (sorted.length === 0) return NaN;
  const idx = Math.min(sorted.length - 1, Math.max(0, Math.ceil(p * sorted.length) - 1));
  return sorted[idx];
}

function mean(xs: number[]): number | null {
  if (xs.length === 0) return null;
  return xs.reduce((a, b) => a + b, 0) / xs.length;
}

function median(xs: number[]): number | null {
  if (xs.length === 0) return null;
  const s = [...xs].sort((a, b) => a - b);
  const mid = s.length >> 1;
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

const r4 = (x: number): number => Math.round(x * 10_000) / 10_000;

/** The distribution of (attainable − decision) on one bucket, with n. */
export interface StampCell {
  bucket: string;
  /** Legs carrying evidence in this bucket — every rate's denominator. */
  n: number;
  meanC: number | null;
  medianC: number | null;
  p10C: number | null;
  p25C: number | null;
  p75C: number | null;
  p90C: number | null;
  minC: number | null;
  maxC: number | null;
  /** |delta| <= MID_BAND_C — the count the refutation's tolerance is read on. */
  withinBand: number;
  shareWithinBand: number | null;
  /** delta <= 0: the entry was attainable at the booked price or better. */
  atOrBetter: number;
  shareAtOrBetter: number | null;
  /** delta >= +1c: we would have paid a cent or more ABOVE the booked price. */
  worseBy1c: number;
  shareWorseBy1c: number | null;
  /** Legs whose snapshot carried a mid (book arm only) — the refutation's n. */
  midN: number;
  /** (attainable − mid) in cents, where the mid is the attaining snapshot's own. */
  meanMidC: number | null;
  medianMidC: number | null;
  shareMidWithinBand: number | null;
  /** Booked notional in the bucket — the weight behind a cents-per-notional claim. */
  notionalUsd: number;
  /** Mean (attainable − contemporaneous mid) — the spread paid at the attaining snapshot. */
  meanAskMinusMidC: number | null;
}

export interface StampCoverage {
  source: StampSource;
  /** Legs offered to this source. */
  offered: number;
  /** Legs with any evidence at all (a bucket reached). */
  covered: number;
  /** covered / offered. */
  rate: number | null;
  /** Legs with evidence inside the widest bucket — the gate's population. */
  coveredWidest: number;
  /** Median coverage lag (ms) over covered legs; null when nothing is covered. */
  medianCoverLagMs: number | null;
  /** Legs where the outcome token could not be told apart (book only). */
  ambiguousToken: number;
}

export interface StampSummary {
  source: StampSource;
  coverage: StampCoverage;
  /** One row per lag bucket, in bucket order (empty buckets keep n = 0). */
  cells: StampCell[];
  /**
   * The FIRST snapshot at/after the decision, whatever its lag — a taker who
   * submits now, with no patience and no hindsight. Book arm only.
   */
  first: StampCell;
  total: StampCell;
}

function emptyCell(bucket: string): StampCell {
  return {
    bucket,
    n: 0,
    meanC: null,
    medianC: null,
    p10C: null,
    p25C: null,
    p75C: null,
    p90C: null,
    minC: null,
    maxC: null,
    withinBand: 0,
    shareWithinBand: null,
    atOrBetter: 0,
    shareAtOrBetter: null,
    worseBy1c: 0,
    shareWorseBy1c: null,
    midN: 0,
    meanMidC: null,
    medianMidC: null,
    shareMidWithinBand: null,
    notionalUsd: 0,
    meanAskMinusMidC: null,
  };
}

function buildCell(bucket: string, xs: Array<{ d: number; midC: number | null; notional: number }>): StampCell {
  if (xs.length === 0) return emptyCell(bucket);
  const ds = xs.map((x) => x.d).sort((a, b) => a - b);
  const mids = xs.map((x) => x.midC).filter((x): x is number => x !== null).sort((a, b) => a - b);
  const within = ds.filter((d) => Math.abs(d) <= MID_BAND_C + LEVEL_EPS).length;
  const better = ds.filter((d) => d <= LEVEL_EPS).length;
  const worse1 = ds.filter((d) => d >= 1 - LEVEL_EPS).length;
  const midWithin = mids.filter((d) => Math.abs(d) <= MID_BAND_C + LEVEL_EPS).length;
  return {
    bucket,
    n: ds.length,
    meanC: r4(mean(ds) as number),
    medianC: r4(median(ds) as number),
    p10C: r4(quantileSorted(ds, 0.1)),
    p25C: r4(quantileSorted(ds, 0.25)),
    p75C: r4(quantileSorted(ds, 0.75)),
    p90C: r4(quantileSorted(ds, 0.9)),
    minC: r4(ds[0]),
    maxC: r4(ds[ds.length - 1]),
    withinBand: within,
    shareWithinBand: within / ds.length,
    atOrBetter: better,
    shareAtOrBetter: better / ds.length,
    worseBy1c: worse1,
    shareWorseBy1c: worse1 / ds.length,
    midN: mids.length,
    meanMidC: mids.length ? r4(mean(mids) as number) : null,
    medianMidC: mids.length ? r4(median(mids) as number) : null,
    shareMidWithinBand: mids.length ? midWithin / mids.length : null,
    notionalUsd: xs.reduce((a, b) => a + b.notional, 0),
    meanAskMinusMidC: mids.length
      ? r4(xs.filter((x) => x.midC !== null).reduce((a, x) => a + (x.d - (x.midC as number)), 0) / mids.length)
      : null,
  };
}

/**
 * Summarise one source. A leg that carries no evidence in a bucket contributes to
 * nothing — it is NOT a zero delta (a zero delta would mean "filled at the booked
 * price", the exact claim under test).
 */
export function summariseStamps(legs: StampLeg[], source: StampSource): StampSummary {
  const buckets = STAMP_LAG_BUCKETS.map((b) => b.label);
  const perBucket = new Map<string, Array<{ d: number; midC: number | null; notional: number }>>(
    buckets.map((b) => [b, []])
  );
  const widest: Array<{ d: number; midC: number | null; notional: number }> = [];
  const firsts: Array<{ d: number; midC: number | null; notional: number }> = [];
  let offered = 0;
  let covered = 0;
  let coveredWidest = 0;
  let ambiguousToken = 0;
  const coverLags: number[] = [];

  for (const leg of legs) {
    offered++;
    if (source === "book" ? leg.book !== null : leg.tape !== null) {
      if (source === "book" && leg.book && leg.book.tokenAmbiguous) ambiguousToken++;
    }
    const byBucket = source === "book" ? leg.book?.byBucket : leg.tape?.byBucket;
    if (!byBucket) continue;
    let any = false;
    for (const b of buckets) {
      const obs = byBucket[b];
      if (!obs) continue;
      any = true;
      const d = deltaCents(obs.price, leg.decisionPrice);
      const midC = obs.mid === null ? null : deltaCents(obs.mid, leg.decisionPrice);
      (perBucket.get(b) as Array<{ d: number; midC: number | null; notional: number }>).push({
        d,
        midC,
        notional: leg.sizeUsd,
      });
    }
    if (any) covered++;
    if (source === "book" && leg.book) {
      coverLags.push(leg.book.coverLagMs);
      const mid = (leg.book.firstAsk + leg.book.firstBid) / 2;
      firsts.push({
        d: deltaCents(leg.book.firstAsk, leg.decisionPrice),
        midC: deltaCents(mid, leg.decisionPrice),
        notional: leg.sizeUsd,
      });
    }
    const w = byBucket[WIDEST_BUCKET];
    if (w) {
      coveredWidest++;
      widest.push({
        d: deltaCents(w.price, leg.decisionPrice),
        midC: w.mid === null ? null : deltaCents(w.mid, leg.decisionPrice),
        notional: leg.sizeUsd,
      });
    }
  }

  return {
    source,
    coverage: {
      source,
      offered,
      covered,
      rate: offered ? covered / offered : null,
      coveredWidest,
      medianCoverLagMs: coverLags.length ? r4(median(coverLags) as number) : null,
      ambiguousToken,
    },
    cells: buckets.map((b) => buildCell(b, perBucket.get(b) as Array<{ d: number; midC: number | null; notional: number }>)),
    first: buildCell("first snapshot", firsts),
    total: buildCell(WIDEST_BUCKET, widest),
  };
}

/**
 * The card's pre-registered decision rule, evaluated rather than asserted.
 *
 * STATISTIC. The claim is denominated in DOLLARS on settled notional
 * (+$1,439.33 / 5.0% of notional), so the money-weighted central tendency is the
 * mean; the median is reported alongside and its verdict is returned separately
 * (`firedOnMedian`) so a skewed distribution cannot be quietly summarised by
 * whichever statistic happens to agree. When the two disagree, the table is the
 * answer — there is no single cents figure to price.
 *
 * `n` is the leg count of the WIDEST bucket, and a leg only counts when the
 * attaining snapshot carried a mid: the test is "within ±0.3c of the MID", and a
 * leg with no mid cannot be in it.
 */
export interface RefutationVerdict {
  source: StampSource;
  n: number;
  gate: number;
  gateMet: boolean;
  bandC: number;
  /** (attainable − mid) mean, cents. Null when nothing carried a mid. */
  meanMidC: number | null;
  medianMidC: number | null;
  /** The pre-registered verdict: gate met AND |mean| <= band. */
  fired: boolean;
  /** Same test on the median, reported so disagreement is visible. */
  firedOnMedian: boolean;
  /** One line a reader cannot mistake. */
  reason: string;
}

export function evaluateRefutation(summary: StampSummary): RefutationVerdict {
  const t = summary.total;
  const n = t.midN;
  const gateMet = n >= GATE_LEGS;
  const meanMidC = t.meanMidC;
  const medianMidC = t.medianMidC;
  const within = (x: number | null) => x !== null && Number.isFinite(x) && Math.abs(x) <= MID_BAND_C + LEVEL_EPS;
  const fired = gateMet && within(meanMidC);
  const firedOnMedian = gateMet && within(medianMidC);
  const stat = meanMidC === null ? "n/a" : `${meanMidC >= 0 ? "+" : ""}${meanMidC.toFixed(2)}c`;
  const med = medianMidC === null ? "n/a" : `${medianMidC >= 0 ? "+" : ""}${medianMidC.toFixed(2)}c`;
  const reason = !gateMet
    ? `NOT EVALUABLE: n=${n} of the required ${GATE_LEGS} legs carry a stamp with a mid (${summary.source} arm), ` +
      `so the ±${MID_BAND_C}c test has no population to fire on. Nothing is refuted and nothing is confirmed.`
    : fired
      ? `REFUTED: on ${n} legs the attainable entry sits ${stat} from the mid (median ${med}), inside ±${MID_BAND_C}c — ` +
        `there is no cent to harvest, and the +$1,439.33 claim fails.`
      : `NOT REFUTED: on ${n} legs the attainable entry sits ${stat} from the mid (median ${med}), outside ±${MID_BAND_C}c — ` +
        `the gap is real, but its SIGN decides whether it is a cost or an opportunity.`;
  return { source: summary.source, n, gate: GATE_LEGS, gateMet, bandC: MID_BAND_C, meanMidC, medianMidC, fired, firedOnMedian, reason };
}

/** The reachability verdict in the shared resolver's own terms (no fork). */
export interface ReachVerdict {
  /** Legs with any book or tape evidence (the rate's denominator). */
  attempted: number;
  unresolved: number;
  reachable: number;
  rate: number | null;
}

/**
 * Run every leg through `resolveFill` in mode `none`: level = the booked price.
 * Book evidence decides when we have it; the tape can only ever add a NEGATIVE at
 * this credit (the tape artifact tests the flat 2c level, which is DEEPER than the
 * decision price, and reachability is monotone in the level) — so a tape-positive
 * leg stays unresolved instead of being counted as a fill.
 */
export function reachability(legs: StampLeg[]): ReachVerdict {
  let attempted = 0;
  let reachable = 0;
  let unresolved = 0;
  for (const leg of legs) {
    const r: ResolutionLeg = {
      intentPrice: leg.decisionPrice,
      bookMinAsk: leg.book?.byBucket[WIDEST_BUCKET]?.price ?? null,
      tapeReached5: null,
      tapeReached60: leg.tape?.byBucket[WIDEST_BUCKET] ? true : null,
    };
    const v = resolveFill(r, STANDARD_CREDIT_MODE);
    if (v.basis === "unresolved") unresolved++;
    else {
      attempted++;
      if (v.reachable) reachable++;
    }
  }
  return { attempted, unresolved, reachable, rate: attempted ? reachable / attempted : null };
}

const c = (x: number | null): string => (x === null || !Number.isFinite(x) ? "n/a" : `${x >= 0 ? "+" : ""}${x.toFixed(2)}c`);
const p = (x: number | null): string => (x === null ? "n/a" : `${(100 * x).toFixed(0)}%`);

/** Render one source's table + coverage. Basis lines are explicit, never implied. */
export function renderStamp(s: StampSummary): string[] {
  const out: string[] = [];
  const cov = s.coverage;
  out.push(
    `[standard-fill-stamp] ${s.source}: evidence on ${cov.covered}/${cov.offered} legs (${p(cov.rate)})` +
      `, ${cov.coveredWidest} inside the ${WIDEST_BUCKET} window` +
      (cov.medianCoverLagMs === null ? "" : `, median cover lag ${(cov.medianCoverLagMs / 1000).toFixed(1)}s`) +
      (cov.ambiguousToken ? `, ${cov.ambiguousToken} legs with an ambiguous outcome token` : "") +
      (s.source === "tape" ? " · prints cannot give a mid, so this arm never feeds the ±0.3c test" : "")
  );
  out.push(
    "[standard-fill-stamp] bucket      n   mean   median      p10      p90   <=booked  >=+1c   |d|<=0.3c   (attainable - decision, cents)"
  );
  const row = (cell: StampCell, label: string): string => {
    if (cell.n === 0) return `[standard-fill-stamp] ${label.padEnd(9)}   0        (no evidence)`;
    return (
      `[standard-fill-stamp] ${label.padEnd(9)} ${String(cell.n).padStart(3)} ` +
      `${c(cell.meanC).padStart(7)} ${c(cell.medianC).padStart(7)} ${c(cell.p10C).padStart(8)} ${c(cell.p90C).padStart(8)} ` +
      `${p(cell.shareAtOrBetter).padStart(8)} ${p(cell.shareWorseBy1c).padStart(6)} ${p(cell.shareWithinBand).padStart(9)}`
    );
  };
  if (s.first.n > 0) out.push(row(s.first, "first*"));
  for (const cell of s.cells) out.push(row(cell, cell.bucket));
  const t = s.total;
  out.push(
    `[standard-fill-stamp] widest ${WIDEST_BUCKET}: n=${t.n} mean ${c(t.meanC)} median ${c(t.medianC)} ` +
      `[${c(t.p10C)}, ${c(t.p90C)}] · at-or-better ${p(t.shareAtOrBetter)} · a cent worse or more ${p(t.shareWorseBy1c)} ` +
      `· $${t.notionalUsd.toFixed(2)} booked notional`
  );
  out.push("[standard-fill-stamp] * first snapshot at/after the decision at whatever lag: no patience, no hindsight");
  if (t.midN > 0 || s.first.midN > 0) {
    out.push(
      "[standard-fill-stamp] vs the CONTEMPORANEOUS MID (the refutation's basis, ±0.3c):"
    );
    const midRow = (cell: StampCell, label: string): string =>
      `[standard-fill-stamp] ${label.padEnd(9)} n=${String(cell.midN).padStart(3)} mean ${c(cell.meanMidC).padStart(7)} ` +
      `median ${c(cell.medianMidC).padStart(7)} · spread paid ${c(cell.meanAskMinusMidC).padStart(6)} ` +
      `· within ±${MID_BAND_C}c ${p(cell.shareMidWithinBand).padStart(4)}`;
    if (s.first.midN > 0) out.push(midRow(s.first, "first*"));
    for (const cell of s.cells) if (cell.midN > 0) out.push(midRow(cell, cell.bucket));
    out.push(midRow(t, "widest"));
  }
  return out;
}
