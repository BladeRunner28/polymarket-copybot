/**
 * c200-fill-resolution — the shared, READ-ONLY resolver for one question:
 * **did this C-200 leg ever own a position at the level it was booked at?**
 *
 * WHY THIS EXISTS (roadmap card `c200-maker-fill-assumption`, item 1 of
 * `approved-work-queue-20261026`)
 * The lane books one PaperTrade per dispatched intent. Both halves of that
 * booking were modelled: the PRICE (`entry = intent − credit`) and the VOLUME
 * (`p(fill) = 1`). The price half was corrected on 2026-10-10 (the sidecar's
 * `maker_credit()` books 2¢ × the measured per-band reach share). The volume
 * half was never restated anywhere: every published C-200 figure — edge,
 * per-trade PnL, capital-velocity — still assumes every intended copy turned
 * into a position.
 *
 * MEASURED, AND WHAT IT SAYS: on the pre-registered print-through instrument
 * (`data/c200-printthrough.jsonl`, 354 dispatched legs, read 2026-10-10 and
 * again 2026-10-26) the flat-2¢ level was reachable on 18/339 legs within 5 min
 * and 65/339 within 1 h. At the shallower credit the sidecar books TODAY the
 * rate is higher but nowhere near 1 — so "booked PnL" is a sum over legs, some
 * of which would never have been positions at all.
 *
 * WHAT THIS MODULE IS NOT: it is not a booking change. Nothing in the trade,
 * sizing, gate or Kelly path imports it; the report keeps publishing booked
 * figures. Turning fill-aware booking ON is a Lane A decision and lives on the
 * card with a before/after and a rollback.
 *
 * THE ONE READING THAT MUST TRAVEL WITH EVERY NUMBER
 * A best ask at or below our level means a SELLER was willing at our price — it
 * is evidence the level was reachable, not a fill: it ignores queue position and
 * ignores size (a resting bid is swept only up to the printed size). So the
 * honest output is "reachable", never "filled", and every rate below is a rate
 * of REACHABILITY.
 *
 * TWO CREDIT MODES
 *   "flat"  entry = intent − 0.02                (the model until 2026-10-10)
 *   "live"  entry = intent − 0.02 × measuredFillShare(intent)  (the model that runs now)
 * The sidecar clamps the entry at 0.01; `levelFor` mirrors that clamp exactly.
 *
 * A THIRD MODE, FOR A LANE THAT APPLIES NO CREDIT AT ALL
 *   "none"  entry = intent                        (STANDARD: no fill model whatsoever)
 * Added for the STANDARD fill booth (scripts/standard-fill-stamp.ts, card `t_7560e0d0`)
 * so that lane is resolved by THIS resolver rather than a fork of it: with zero credit
 * the level IS the price the lane booked, so `resolveFill` answers exactly the
 * STANDARD question — "was the booked price reachable in the evidence we hold". It is
 * additive: every existing mode returns byte-identical values.
 */

import { MAKER_IMPROVEMENT_USD, measuredFillShare } from "./copy-cost";

/** Which credit the sidecar applied when it booked the leg ("none" = STANDARD). */
export type CreditMode = "live" | "flat" | "none";

/** The flat model's improvement, mirrored from rust-sidecar/src/main.rs. */
export const FLAT_CREDIT_USD = MAKER_IMPROVEMENT_USD;

/** Float tolerance on a cents-scale quote (prices are exact to 3 decimals). */
export const LEVEL_EPS = 1e-9;

/** Sidecar's floor on a booked entry price (`max(0.01, price − improvement)`). */
export const MIN_BOOKED_ENTRY = 0.01;

/** The credit the sidecar books for an intent at `intentPrice` under `mode`. */
export function creditUsdFor(intentPrice: number, mode: CreditMode): number {
  if (mode === "none") return 0;
  if (mode === "flat") return FLAT_CREDIT_USD;
  if (!Number.isFinite(intentPrice) || intentPrice <= 0) return 0;
  return FLAT_CREDIT_USD * measuredFillShare(intentPrice);
}

/** The level a resting bid at `intentPrice` would have to sit at to be booked. */
export function levelFor(intentPrice: number, mode: CreditMode): number {
  return Math.max(MIN_BOOKED_ENTRY, intentPrice - creditUsdFor(intentPrice, mode));
}

/** The evidence a single leg carries into the resolver. */
export interface ResolutionLeg {
  /** Price the lane was handed (PaperTrade.intentPrice / FillIntent.intentPrice). */
  intentPrice: number;
  /**
   * Lowest best-ask seen in OUR L2 window for this token after the dispatch
   * (`book.minAsk` in the print-through artifact). Null = no book coverage.
   */
  bookMinAsk: number | null;
  /**
   * Tape evidence at the FLAT level only: the artifact is computed with a 2¢
   * delta, so a `true` says "the flat level printed" and a `false` says "the
   * flat level did not print". Monotonicity makes these asymmetric — see
   * `resolveFill`.
   */
  tapeReached5: boolean | null;
  tapeReached60: boolean | null;
}

export type FillBasis = "book-window" | "tape-lower-bound" | "tape-flat" | "unresolved";

export interface FillVerdict {
  /** True = the level was reachable by the evidence we hold. */
  reachable: boolean;
  basis: FillBasis;
  /** The level tested, i.e. intent − credit(mode), clamped at 0.01. */
  level: number;
  credit: number;
}

/**
 * Resolve one leg.
 *
 * PRECEDENCE, and why it is not symmetric:
 *  - Our own book window is the direct test: minAsk ≤ level ⇒ reachable.
 *  - The tape only speaks at the FLAT level (2¢ below intent). Reachability is
 *    monotone in the level: a fill at a DEEPER level does not imply a fill at a
 *    SHALLOWER one, but the absence of a fill at the deeper level proves the
 *    absence of one at the shallower level. So `tapeReached60 === false` is a
 *    valid NEGATIVE at any credit, and `tapeReached60 === true` is only a valid
 *    POSITIVE under the flat model — it is NOT used as a positive for the live,
 *    shallower credit (that would manufacture fills).
 *  - Everything else is UNRESOLVED and must be excluded from rates, never
 *    silently counted as "did not fill".
 */
export function resolveFill(leg: ResolutionLeg, mode: CreditMode): FillVerdict {
  const credit = creditUsdFor(leg.intentPrice, mode);
  const level = levelFor(leg.intentPrice, mode);
  if (leg.bookMinAsk !== null && Number.isFinite(leg.bookMinAsk)) {
    return { reachable: leg.bookMinAsk <= level + LEVEL_EPS, basis: "book-window", level, credit };
  }
  if (leg.tapeReached60 === false) {
    return { reachable: false, basis: "tape-lower-bound", level, credit };
  }
  if (leg.tapeReached60 === true) {
    if (mode === "flat") return { reachable: true, basis: "tape-flat", level, credit };
    // Shallower than the level the tape actually cleared: no opinion.
    return { reachable: false, basis: "unresolved", level, credit };
  }
  return { reachable: false, basis: "unresolved", level, credit };
}

/** One settled (or open) leg, ready to be priced both ways. */
export interface FillAwareLeg {
  leg: ResolutionLeg;
  /** Booked realized PnL; null = not settled, contributes to no PnL column. */
  realizedPnl: number | null;
  /** Dollars at risk on the booked leg (`simulatedPositionSize`). */
  sizeUsd: number;
  /** Band label source; defaults to `intentPrice` when omitted. */
  bandPrice?: number;
  /**
   * Market id — the bootstrap CLUSTER key for `marketClusteredDelta`. Optional;
   * a leg without one becomes its own cluster, so it can never be pooled with a
   * market it does not belong to.
   */
  marketId?: string;
}

export const FILL_BANDS: ReadonlyArray<{ lo: number; hi: number; label: string }> = [
  { lo: 0.0, hi: 0.1, label: "0.00-0.10" },
  { lo: 0.1, hi: 0.2, label: "0.10-0.20" },
  { lo: 0.2, hi: 0.4, label: "0.20-0.40" },
  { lo: 0.4, hi: 0.6, label: "0.40-0.60" },
  { lo: 0.6, hi: 0.8, label: "0.60-0.80" },
  { lo: 0.8, hi: 1.0000001, label: "0.80-1.00" },
];

export function bandOf(price: number): string {
  const b = FILL_BANDS.find((x) => price >= x.lo && price < x.hi);
  return b ? b.label : FILL_BANDS[FILL_BANDS.length - 1].label;
}

export interface FillAwareCell {
  label: string;
  /** Legs carrying any evidence (book or tape) — the rate's denominator base. */
  attempted: number;
  /** Legs with no evidence at all; excluded from every rate. */
  unresolved: number;
  /** Legs whose level was reachable. */
  reachable: number;
  /** reachable / (attempted − unresolved). Null when nothing is resolved. */
  reachRate: number | null;
  notionalUsd: number;
  reachableNotionalUsd: number;
  /** Booked realized PnL over the settled legs in the cell. */
  bookedPnlUsd: number;
  /** Same, with every unreachable leg booked as $0 (never entered). */
  fillAwarePnlUsd: number;
  /** Settled legs in the cell (PnL columns' own population). */
  settled: number;
  /** bookedPnl / notional (%. booked assumes p(fill)=1). */
  bookedRoiPct: number | null;
  /** fillAwarePnl / notional-of-reachable legs (%) — conditional on filling. */
  roiGivenFillPct: number | null;
  /** fillAwarePnl / notional of ALL attempted settled legs (%) — per intended copy. */
  perIntendedCopyPct: number | null;
  medianBookedPnlUsd: number | null;
  medianFillAwarePnlUsd: number | null;
  /** Booked PnL with the ten best legs removed — is the cell one leg wide? */
  exTop10BookedUsd: number | null;
  exTop10FillAwareUsd: number | null;
}

export interface FillAwareSummary {
  mode: CreditMode;
  total: FillAwareCell;
  byBand: FillAwareCell[];
}

function median(xs: number[]): number | null {
  if (xs.length === 0) return null;
  const s = [...xs].sort((a, b) => a - b);
  const mid = s.length >> 1;
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

/** Sum after dropping the `k` largest values (concentration check). */
function exTop(xs: number[], k: number): number | null {
  if (xs.length <= k) return null;
  const s = [...xs].sort((a, b) => b - a);
  return s.slice(k).reduce((a, b) => a + b, 0);
}

/**
 * Pure summariser. A leg that never reached its level is booked at $0 realized
 * PnL AND $0 notional — it was never a position, so it cannot be a loss either.
 * That is the whole point: `fillAwarePnlUsd` is not the booked PnL minus a
 * haircut, it is the PnL of the subset of copies a resting bid would have owned.
 */
export function summariseFillAware(legs: FillAwareLeg[], mode: CreditMode): FillAwareSummary {
  const cells = new Map<string, FillAwareLeg[]>();
  for (const l of legs) {
    const b = bandOf(l.bandPrice ?? l.leg.intentPrice);
    const arr = cells.get(b) ?? [];
    arr.push(l);
    cells.set(b, arr);
  }
  const build = (label: string, sel: FillAwareLeg[]): FillAwareCell => {
    let attempted = 0;
    let unresolved = 0;
    let reachable = 0;
    let notional = 0;
    let reachableNotional = 0;
    let settled = 0;
    const booked: number[] = [];
    const filled: number[] = [];
    for (const l of sel) {
      const v = resolveFill(l.leg, mode);
      const resolved = v.basis !== "unresolved";
      if (resolved) {
        attempted++;
        if (v.reachable) reachable++;
      } else {
        unresolved++;
      }
      notional += l.sizeUsd;
      if (v.reachable) reachableNotional += l.sizeUsd;
      if (l.realizedPnl !== null && Number.isFinite(l.realizedPnl)) {
        settled++;
        booked.push(l.realizedPnl);
        if (v.reachable) filled.push(l.realizedPnl);
      }
    }
    const bookedPnl = booked.reduce((a, b) => a + b, 0);
    const fillAwarePnl = filled.reduce((a, b) => a + b, 0);
    return {
      label,
      attempted,
      unresolved,
      reachable,
      reachRate: attempted ? reachable / attempted : null,
      notionalUsd: notional,
      reachableNotionalUsd: reachableNotional,
      bookedPnlUsd: bookedPnl,
      fillAwarePnlUsd: fillAwarePnl,
      settled,
      bookedRoiPct: notional > 0 && settled > 0 ? (100 * bookedPnl) / notional : null,
      roiGivenFillPct:
        reachableNotional > 0 && filled.length > 0 ? (100 * fillAwarePnl) / reachableNotional : null,
      perIntendedCopyPct: notional > 0 && settled > 0 ? (100 * fillAwarePnl) / notional : null,
      medianBookedPnlUsd: median(booked),
      medianFillAwarePnlUsd: median(filled),
      exTop10BookedUsd: exTop(booked, 10),
      exTop10FillAwareUsd: exTop(filled, 10),
    };
  };
  const byBand = FILL_BANDS.filter((b) => cells.has(b.label)).map((b) =>
    build(b.label, cells.get(b.label) as FillAwareLeg[])
  );
  return { mode, total: build("all", legs), byBand };
}

/** Signed dollars, the repo's report convention. */
export function usd(x: number | null): string {
  if (x === null || !Number.isFinite(x)) return "n/a";
  return `${x < 0 ? "-" : "+"}$${Math.abs(x).toFixed(2)}`;
}

/** Percent with a sign, or n/a. */
export function pct(x: number | null): string {
  if (x === null || !Number.isFinite(x)) return "n/a";
  return `${x < 0 ? "-" : "+"}${Math.abs(x).toFixed(1)}%`;
}

/** Render one mode's table. Basis is stated per line, never implied. */
export function renderFillAware(s: FillAwareSummary, basisLabel: string): string[] {
  const out: string[] = [];
  const rate = s.total.reachRate === null ? "n/a" : `${(100 * s.total.reachRate).toFixed(1)}%`;
  out.push(
    `[c200-fill-aware] mode=${s.mode} (${basisLabel}): reachable ${s.total.reachable}/${s.total.attempted} ` +
      `= ${rate} (unresolved ${s.total.unresolved}, excluded from the rate)`
  );
  out.push(
    `[c200-fill-aware] booked ${usd(s.total.bookedPnlUsd)} on $${s.total.notionalUsd.toFixed(2)} ` +
      `(${pct(s.total.bookedRoiPct)}) · fill-aware ${usd(s.total.fillAwarePnlUsd)} ` +
      `(${pct(s.total.perIntendedCopyPct)} per intended copy, ${pct(s.total.roiGivenFillPct)} given fill) ` +
      `· delta ${usd(s.total.fillAwarePnlUsd - s.total.bookedPnlUsd)}`
  );
  out.push(
    "[c200-fill-aware] band         n  unres   reach   booked$  bookROI  fillaware$  ROI|fill  per-copy  ex-top10-fill"
  );
  for (const c of s.byBand) {
    const r = c.reachRate === null ? "n/a" : `${(100 * c.reachRate).toFixed(1)}%`;
    out.push(
      `[c200-fill-aware] ${c.label}  ${String(c.attempted).padStart(3)}  ${String(c.unresolved).padStart(5)}  ` +
        `${r.padStart(6)}  ${usd(c.bookedPnlUsd).padStart(9)}  ${pct(c.bookedRoiPct).padStart(8)}  ` +
        `${usd(c.fillAwarePnlUsd).padStart(11)}  ${pct(c.roiGivenFillPct).padStart(8)}  ` +
        `${pct(c.perIntendedCopyPct).padStart(8)}  ${usd(c.exTop10FillAwareUsd).padStart(9)}`
    );
  }
  return out;
}

/* ============================================================================
 * THE UNION READER, AND THE CLUSTERED DELTA — added 2026-11-22 (Lane B repair,
 * card `profit-c200-reachability-stamp`)
 *
 * WHY (measured, not asserted): the C-200 booth APPENDS one snapshot per run and
 * each run re-stamps only the legs it could reach that tick — today's tick holds
 * 4 legs. Every consumer of this artifact (`scripts/c200-fill-aware-pnl.ts`,
 * published as item 1 of `approved-work-queue-20261026`) read the LAST LINE, so
 * re-running it on 2026-11-22 printed `booked +$0.00, 4 legs, 0 settled` while
 * the union underneath held 955 stamped intents (473 dispatched inside 30 days).
 * Same defect class as `standard-fill-union-verdict`: the gate could not be read
 * off the file. This module is the union and its evidence rule, so a reader can
 * no longer be written against a tick.
 *
 * EVIDENCE RULE (copied from the STANDARD booth's merge, `scripts/
 * standard-fill-stamp-merge.py`, so the two booths cannot drift): the newer
 * stamp wins, EXCEPT that a stamp which carries NO evidence never erases one
 * that did — otherwise a single tick that misses the L2 window silently shrinks
 * coverage. `keptOldEvidence` counts exactly those legs, and it is printed.
 * ========================================================================== */

/** The minimum shape a stamped leg must carry to be folded into a union. */
export interface StampCarrier {
  intentId: string;
  book?: { minAsk?: number | null } | null;
  reached60?: boolean | null;
  tapeSilent?: boolean | null;
}

/** Does this stamp carry any evidence at all? (absence is not evidence) */
export function stampHasEvidence(l: StampCarrier): boolean {
  if (l.book && typeof l.book.minAsk === "number" && Number.isFinite(l.book.minAsk)) return true;
  if (l.tapeSilent) return false;
  return typeof l.reached60 === "boolean";
}

export interface StampRow<L extends StampCarrier> {
  ranAt: number;
  legs: L[];
}

export interface StampUnion<L extends StampCarrier> {
  /** One leg per intentId, in first-appearance order. */
  legs: L[];
  /** Snapshots read, and how many of them carried legs. */
  rows: number;
  rowsWithLegs: number;
  /** Newer stamp had no evidence, older did -> the older one is kept (the rule). */
  keptOldEvidence: number;
  /** Older had nothing, newer has evidence. */
  upgraded: number;
  /** Both sides had the same evidence class -> the newer stamp is kept. */
  newerWins: number;
  /** Distinct intentIds seen across every snapshot. */
  distinctLegs: number;
  firstRanAt: number | null;
  lastRanAt: number | null;
}

/**
 * Streaming folder. One instance per artifact; `add()` per line so a 225 MB
 * append-only artifact is never materialised as a whole.
 */
export class StampUnionFolder<L extends StampCarrier> {
  private order: string[] = [];
  private byId = new Map<string, { leg: L; ranAt: number; has: boolean }>();
  private rows = 0;
  private rowsWithLegs = 0;
  private keptOldEvidence = 0;
  private upgraded = 0;
  private newerWins = 0;
  private first: number | null = null;
  private last: number | null = null;

  add(row: StampRow<L>): void {
    this.rows++;
    // A row with no timestamp cannot claim the range; it still folds by evidence.
    if (typeof row.ranAt === "number" && Number.isFinite(row.ranAt) && row.ranAt > 0) {
      if (this.first === null || row.ranAt < this.first) this.first = row.ranAt;
      if (this.last === null || row.ranAt > this.last) this.last = row.ranAt;
    }
    if (!Array.isArray(row.legs) || row.legs.length === 0) return;
    this.rowsWithLegs++;
    for (const leg of row.legs) {
      const id = leg && typeof leg.intentId === "string" ? leg.intentId : "";
      if (!id) continue;
      const has = stampHasEvidence(leg);
      const prev = this.byId.get(id);
      if (!prev) {
        this.order.push(id);
        this.byId.set(id, { leg, ranAt: row.ranAt, has });
        continue;
      }
      // Later rows are appended later; ranAt is carried so an out-of-order
      // artifact still resolves to the NEWER stamp, not the last line read.
      const newer = row.ranAt >= prev.ranAt ? { leg, ranAt: row.ranAt, has } : prev;
      const older = newer === prev ? { leg, ranAt: row.ranAt, has } : prev;
      if (!newer.has && older.has) {
        this.keptOldEvidence++;
        this.byId.set(id, older); // evidence beats absence
      } else {
        if (!older.has && newer.has) this.upgraded++;
        else this.newerWins++;
        this.byId.set(id, newer);
      }
    }
  }

  result(): StampUnion<L> {
    const legs: L[] = [];
    for (const id of this.order) {
      const v = this.byId.get(id);
      if (v) legs.push(v.leg);
    }
    return {
      legs,
      rows: this.rows,
      rowsWithLegs: this.rowsWithLegs,
      keptOldEvidence: this.keptOldEvidence,
      upgraded: this.upgraded,
      newerWins: this.newerWins,
      distinctLegs: this.order.length,
      firstRanAt: this.first,
      lastRanAt: this.last,
    };
  }
}

/** Convenience wrapper for an in-memory row list (tests, small artifacts). */
export function unionStamps<L extends StampCarrier>(rows: Iterable<StampRow<L>>): StampUnion<L> {
  const f = new StampUnionFolder<L>();
  for (const r of rows) f.add(r);
  return f.result();
}

/**
 * Maker-vs-taker delta per dollar of INTENDED copy, with a MARKET-CLUSTERED
 * bootstrap CI. Both arms share the same denominator (every settled leg's
 * notional) so the difference is the booking assumption and nothing else:
 *
 *   bookedRoiPct     = 100 * Σ realizedPnl / Σ notional        (p(fill) = 1)
 *   fillAwareRoiPct  = 100 * Σ (reachable ? realizedPnl : 0) / Σ notional
 *   deltaPct         = fillAwareRoiPct − bookedRoiPct   (percentage points)
 *
 * Clustering is on `marketId`: legs in one market share a resolution event and a
 * price path, so a leg-level bootstrap understates the interval. Resampling
 * markets also reproduces the "is this one market wide" question the printed
 * ex-top-10 column asks. Deterministic (mulberry32) so a reread is identical.
 */
export interface ClusteredDelta {
  mode: CreditMode;
  legs: number;
  /** Distinct market clusters seen (settled or not) — the bootstrap's resampling unit. */
  markets: number;
  reps: number;
  seed: number;
  bookedRoiPct: number | null;
  fillAwareRoiPct: number | null;
  deltaPct: number | null;
  ciLoPct: number | null;
  ciHiPct: number | null;
  /** Markets contributing at least one settled leg. */
  settledMarkets: number;
}

function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function marketClusteredDelta(
  legs: FillAwareLeg[],
  mode: CreditMode,
  opts: { reps?: number; seed?: number } = {}
): ClusteredDelta {
  const reps = Math.max(200, Math.floor(opts.reps ?? 2000));
  const seed = Math.floor(opts.seed ?? 20261122);
  const clusters = new Map<
    string,
    { n: number; notional: number; booked: number; filled: number }
  >();
  let settled = 0;
  for (const l of legs) {
    const pnl = l.realizedPnl;
    const key = l.marketId ?? `leg:${clusters.size}:${settled}`;
    const c = clusters.get(key) ?? { n: 0, notional: 0, booked: 0, filled: 0 };
    if (pnl !== null && Number.isFinite(pnl)) {
      c.booked += pnl;
      c.notional += l.sizeUsd;
      c.n += 1;
      settled++;
      if (resolveFill(l.leg, mode).reachable) c.filled += pnl;
    }
    clusters.set(key, c);
  }
  const settledClusters = [...clusters.entries()].filter(([, c]) => c.n > 0);
  const base: ClusteredDelta = {
    mode,
    legs: legs.length,
    markets: clusters.size,
    reps,
    seed,
    bookedRoiPct: null,
    fillAwareRoiPct: null,
    deltaPct: null,
    ciLoPct: null,
    ciHiPct: null,
    settledMarkets: settledClusters.length,
  };
  if (settledClusters.length < 2) return base;

  // Both arms share ONE denominator per draw: the notional of the settled legs in
  // the resampled markets. Resampling markets therefore moves numerator AND
  // denominator together, which is what makes the interval a market-clustered one
  // rather than a numerator-only interval on a fixed base.
  const sum = settledClusters.reduce(
    (a, [, c]) => ({ booked: a.booked + c.booked, filled: a.filled + c.filled, notional: a.notional + c.notional }),
    { booked: 0, filled: 0, notional: 0 }
  );
  if (!(sum.notional > 0)) return base;
  const bookedRoi = (100 * sum.booked) / sum.notional;
  const filledRoi = (100 * sum.filled) / sum.notional;

  const rnd = mulberry32(seed);
  const draws: number[] = [];
  const k = settledClusters.length;
  for (let r = 0; r < reps; r++) {
    let b = 0;
    let f = 0;
    let nt = 0;
    let n = 0;
    for (let i = 0; i < k; i++) {
      const pick = settledClusters[Math.floor(rnd() * k)];
      b += pick[1].booked;
      f += pick[1].filled;
      nt += pick[1].notional;
      if (pick[1].n > 0) n++;
    }
    if (n < 2 || !(nt > 0)) continue;
    draws.push((100 * f) / nt - (100 * b) / nt);
  }
  if (draws.length === 0) return base;
  draws.sort((a, b) => a - b);
  const at = (q: number) => draws[Math.min(draws.length - 1, Math.max(0, Math.floor(q * draws.length)))];
  return {
    ...base,
    bookedRoiPct: bookedRoi,
    fillAwareRoiPct: filledRoi,
    deltaPct: filledRoi - bookedRoi,
    ciLoPct: at(0.025),
    ciHiPct: at(0.975),
  };
}
