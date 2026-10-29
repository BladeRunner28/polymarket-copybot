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
