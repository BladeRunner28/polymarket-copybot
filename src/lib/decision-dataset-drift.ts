/**
 * Localisation helpers for the ML export reconciliation (card `export-reconciliation-localisable`).
 *
 * The frozen baseline `data/decision-dataset.manifest.json` stores SUMS ONLY, so the existing check
 * can report "drift" but never WHERE, and the card recorded that as unfixable: "post-hoc localisation
 * is impossible: the pre-change currentPrice is not stored anywhere".
 *
 * That claim is false for the fee legs. The frozen artifact is not only a manifest — it is a
 * 3,516-row CSV (`data/decision-dataset.csv`) that carries `fee_rate`, `fee_entry_usd` and
 * `fee_exit_usd` PER POSITION. The exit fee is `shares * rate * p * (1-p)` with
 * shares = size/entry, so inverting it recovers p(1-p) and hence the exit mark the artifact was
 * priced against (two roots; the pair is reported, never silently picked). A per-position diff
 * therefore names the positions that moved — no baseline regeneration, no change to the manifest's
 * shape, and the frozen file is only ever read.
 *
 * Pure: no I/O. The script supplies parsed rows; everything here is unit-testable.
 */

/** One row of the frozen CSV, in the units the artifact printed. */
export interface FrozenPosition {
  tradeId: string;
  marketId: string;
  entryPrice: number;
  sizeUsd: number;
  feeRate: number;
  feeEntryUsd: number;
  feeExitUsd: number;
  pnlGross: number;
  pnlNetEntry: number;
  pnlNetFull: number;
  /** Blank when the position resolved at settlement rather than being sold out early. */
  closedAt: string | null;
  question: string;
}

/** The same position read from the live DB through the export's own fee model. */
export interface CurrentPosition {
  tradeId: string;
  marketId: string;
  status: string;
  entryPrice: number;
  sizeUsd: number;
  realizedPnl: number;
  feeRate: number;
  feeRateSource: "venue" | "proxy";
  feeEntryUsd: number;
  feeExitUsd: number;
  pnlNetEntry: number;
  pnlNetFull: number;
}

export interface PositionDelta {
  tradeId: string;
  marketId: string;
  question: string;
  /** 'gross' = the realized PnL itself moved; 'fee' = only the fee legs moved. */
  cause: "gross" | "fee" | "both" | "none";
  dGross: number;
  dFeeEntry: number;
  dFeeExit: number;
  dNetEntry: number;
  dNetFull: number;
  /** Exit mark(s) the FROZEN artifact was priced against, recovered from its own fee_exit. */
  frozenExitMarks: number[] | null;
}

/** Tolerance for calling a money cell "moved": a tenth of a cent on a $10 clip. */
export const DELTA_TOLERANCE = 0.005;

/**
 * Parse one frozen CSV line. The file is unquoted and the Python writer replaced commas inside the
 * question with `;`, so a plain split is exact — but a short line is refused rather than padded,
 * because a silently mis-aligned row would report drift that is not there.
 */
export function parseFrozenLine(line: string): FrozenPosition | null {
  const c = line.replace(/\r$/, "").split(",");
  if (c.length < 38) return null;
  const n = (i: number): number => {
    const v = Number(c[i]);
    return Number.isFinite(v) ? v : 0;
  };
  return {
    tradeId: c[0],
    marketId: c[8],
    entryPrice: n(12),
    sizeUsd: n(13),
    question: c[11],
    closedAt: c[6] || null,
    feeRate: n(34),
    feeEntryUsd: n(35),
    feeExitUsd: n(36),
    pnlGross: n(31),
    pnlNetEntry: n(32),
    pnlNetFull: n(33),
  };
}

/**
 * Invert `fee_exit = shares * rate * p * (1 - p)` for p. Returns null when the fee is zero (nothing
 * was priced out) and a single-element list when the quadratic is degenerate (p = 0.5 exactly).
 * Two roots mean the fee alone cannot say which side of 0.5 the mark sat on — that ambiguity is
 * reported, never resolved by assumption.
 */
export function impliedExitMarks(feeExitUsd: number, shares: number, rate: number, dp = 4): number[] | null {
  if (!(feeExitUsd > 0) || !(shares > 0) || !(rate > 0)) return null;
  const x = feeExitUsd / (shares * rate);
  if (x > 0.25) return null; // beyond the parabola's maximum: not this model's fee
  const disc = 1 - 4 * x;
  if (disc < 0) return null;
  const root = Math.sqrt(disc);
  const lo = (1 - root) / 2;
  const hi = (1 + root) / 2;
  const round = (v: number) => Number(v.toFixed(dp));
  return round(lo) === round(hi) ? [round(lo)] : [round(lo), round(hi)];
}

export function deltaOf(frozen: FrozenPosition, cur: CurrentPosition): PositionDelta {
  const dGross = cur.realizedPnl - frozen.pnlGross;
  const dFeeEntry = cur.feeEntryUsd - frozen.feeEntryUsd;
  const dFeeExit = cur.feeExitUsd - frozen.feeExitUsd;
  const grossMoved = Math.abs(dGross) > DELTA_TOLERANCE;
  const feeMoved = Math.abs(dFeeEntry) > DELTA_TOLERANCE || Math.abs(dFeeExit) > DELTA_TOLERANCE;
  const cause: PositionDelta["cause"] =
    grossMoved && feeMoved ? "both" : grossMoved ? "gross" : feeMoved ? "fee" : "none";
  const shares = frozen.entryPrice > 0 ? frozen.sizeUsd / frozen.entryPrice : 0;
  return {
    tradeId: frozen.tradeId,
    marketId: frozen.marketId,
    question: frozen.question,
    cause,
    dGross,
    dFeeEntry,
    dFeeExit,
    dNetEntry: cur.pnlNetEntry - frozen.pnlNetEntry,
    dNetFull: cur.pnlNetFull - frozen.pnlNetFull,
    frozenExitMarks: impliedExitMarks(frozen.feeExitUsd, shares, frozen.feeRate),
  };
}

export interface DeltaSummary {
  n: number;
  moved: number;
  byCause: { gross: number; fee: number; both: number };
  sum: { dGross: number; dFeeEntry: number; dFeeExit: number; dNetEntry: number; dNetFull: number };
  /** Signed share of the total |Δ net_full| carried by the single largest position. */
  topSharePct: number;
}

export function summariseDeltas(deltas: PositionDelta[]): DeltaSummary {
  const byCause = { gross: 0, fee: 0, both: 0 };
  const sum = { dGross: 0, dFeeEntry: 0, dFeeExit: 0, dNetEntry: 0, dNetFull: 0 };
  let moved = 0;
  let absTotal = 0;
  let absTop = 0;
  for (const d of deltas) {
    if (d.cause !== "none") {
      moved += 1;
      if (d.cause === "gross" || d.cause === "fee" || d.cause === "both") byCause[d.cause] += 1;
    }
    sum.dGross += d.dGross;
    sum.dFeeEntry += d.dFeeEntry;
    sum.dFeeExit += d.dFeeExit;
    sum.dNetEntry += d.dNetEntry;
    sum.dNetFull += d.dNetFull;
    const a = Math.abs(d.dNetFull);
    absTotal += a;
    if (a > absTop) absTop = a;
  }
  return {
    n: deltas.length,
    moved,
    byCause,
    sum,
    topSharePct: absTotal > 0 ? (100 * absTop) / absTotal : 0,
  };
}

/** Parse the whole frozen CSV (header line included; it is skipped by column count). */
export function parseFrozenCsv(text: string): { positions: FrozenPosition[]; unparsed: number } {
  const lines = text.split("\n").filter((l) => l.trim().length > 0);
  const positions: FrozenPosition[] = [];
  let unparsed = 0;
  for (const line of lines.slice(1)) {
    const r = parseFrozenLine(line);
    if (r === null) unparsed += 1;
    else positions.push(r);
  }
  return { positions, unparsed };
}

export interface Localisation {
  deltas: PositionDelta[];
  missing: string[];
  /** Positions whose CURRENT label is the venue's rate (reported; they are compared, not dropped). */
  truthLabelled: number;
  rateChanged: number;
  unparsed: number;
  summary: DeltaSummary;
  /** Positions sorted by |Δ net_full|, largest first. */
  moved: PositionDelta[];
}

/**
 * Diff every frozen position against its live reading. EVERY position is compared, and both the
 * frozen and the current reading must be priced on the keyword PROXY — that is the only fee model
 * the frozen artifact has (there is no per-row way to know a 2026-09-13 rate otherwise).
 *
 * The earlier version EXCLUDED rows carrying the venue's own rate "because they disagree by
 * construction". That was true while venue truth covered 9 markets. On 2026-11-20 the capture was
 * extended to the whole export (4,387 of 4,397 markets) and the exclusion swallowed 3,498 of the
 * 3,516 frozen positions: the localisation ran on 18 rows and reported "0 positions moved", which
 * is the same defect class as a probe that cannot fail. The label is now COUNTED and printed, never
 * used to drop a row.
 */
export function localiseFrozenPositions(
  frozen: FrozenPosition[],
  current: (tradeId: string) => CurrentPosition | null,
  unparsed = 0,
): Localisation {
  const deltas: PositionDelta[] = [];
  const missing: string[] = [];
  let truthLabelled = 0;
  let rateChanged = 0;
  for (const f of frozen) {
    const cur = current(f.tradeId);
    if (cur === null) {
      missing.push(f.tradeId);
      continue;
    }
    if (cur.feeRateSource === "venue") truthLabelled += 1;
    // Only a genuine proxy-model change counts here: the caller prices `cur` on the proxy, so a
    // venue-rate row does not read as "the rate changed" (see the module note).
    if (Math.abs(cur.feeRate - f.feeRate) > 1e-9) rateChanged += 1;
    deltas.push(deltaOf(f, cur));
  }
  return {
    deltas,
    missing,
    truthLabelled,
    rateChanged,
    unparsed,
    summary: summariseDeltas(deltas),
    moved: deltas
      .filter((d) => d.cause !== "none")
      .sort((a, b) => Math.abs(b.dNetFull) - Math.abs(a.dNetFull)),
  };
}
