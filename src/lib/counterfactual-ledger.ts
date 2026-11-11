/**
 * ONE counterfactual-ledger primitive for DECLINED decisions
 * (roadmap card phil-counterfactual-ledger-primitive, Lane B — measurement only).
 *
 * WHY: every declined-gate shadow was built as its own writer and its own summary
 * math. Four of them exist today — the late-drift gate, the minConfidence bar, the
 * per-wallet ceiling and the long-shot ladder — and the drift between them is not
 * hypothetical: the drift counterfactual got a DUST FLOOR (tuning #29 rec 1,
 * 2026-09-19) and the confidence counterfactual did not, with the same
 * dust-dominated population. Same bug class, one lane fixed, because the fix lived
 * in that lane's own summary instead of in a shared read.
 *
 * WHAT THIS IS
 *   - `appendCounterfactualCandidate` / `appendCounterfactualResolve`: the ONE
 *     append-only write path. It records the decision mechanically (entry price,
 *     stake, fill model, identity, time) and nothing else is derived at write time
 *     from live policy. No thresholds, no lane stakes, no dust floors live here —
 *     they are ARGUMENTS and READ OPTIONS, so a lane cannot quietly own a private
 *     copy of the arithmetic.
 *   - `summarizeLedger`: the ONE declarative read. Row-level totals, the ex-dust
 *     mean, the trailing-7d cohort, the per-signal basis and the per-market basis
 *     are computed once, here, for every lane. A lane's `summarizeX` is a VIEW of
 *     this (field names + which sub-population the lane asks about), not a second
 *     implementation.
 *   - `settledDustRead`: the floor applied to the decisions that actually settled, at
 *     all three levels a gate question is asked at (row / copy signal / market), plus
 *     what it removed, the concentration of what is left, and the banned-tail cut. Added
 *     on 2026-11-11 because the confidence lane had to write that arithmetic a second
 *     time, lane-locally, on 2026-10-31.
 *   - `counterfactualPnl`: the ONE fill/payoff rule — a declined candidate is
 *     priced as a ticket on the named outcome token bought at `entryPrice`, paying
 *     `stake * (settledValue - entry) / entry`. Every lane used this formula; now
 *     there is one copy of it.
 *
 * WHAT THIS IS NOT: a gate. Nothing here is imported by a decision path, nothing
 * here changes a rule, size, booking or threshold, and no lane's headline number
 * moves because of it — the port is verified field-for-field against the
 * pre-port implementations on a frozen window by
 * scripts/reconcile-counterfactual-ledger.ts.
 *
 * Row shape (append-only JSONL, one object per line):
 *   { ts, type: "candidate", schema, lane, marketId, outcome, side, wallet,
 *     entryPrice, stakeUsd, fillKind, ...canonical extras..., ...lane extras }
 * with `{ ts, type: "resolve", marketId, outcome, value }` lines appended by the
 * marker. Readers tolerate legacy rows (pre-port lanes used `currentPrice` or
 * `entryPrice`, and `sizeUsd` instead of `stakeUsd`), which is what makes the
 * table-vs-ledger diff meaningful: both sides read the same file.
 */

import * as fs from "fs";

/** Bumped when the canonical row shape changes. Readers must not infer policy from it. */
export const COUNTERFACTUAL_SCHEMA_VERSION = 1;

export type CounterfactualFillKind =
  /** A constant hypothetical clip — declines booked nothing, so a fixed stake makes candidates comparable. */
  | "fixed_clip"
  /** The would-be size the live path would have booked (Kelly/band sizing already applied). */
  | "would_be_size";

export interface CounterfactualFill {
  kind: CounterfactualFillKind;
  stakeUsd: number;
}

/**
 * Canonical fields written by the primitive. A lane's `extras` may not redefine
 * them — a row with two meanings for `stakeUsd` is exactly the drift this file
 * exists to remove.
 */
const CANONICAL_KEYS = [
  "ts",
  "type",
  "schema",
  "lane",
  "marketId",
  "outcome",
  "side",
  "wallet",
  "entryPrice",
  "stakeUsd",
  "fillKind",
  "decidedAt",
  "era",
  "reason",
] as const;

export interface CounterfactualCandidateInput {
  /** Feed identity, e.g. "late_drift_gate". Stable: it is the join key for every read. */
  lane: string;
  /** Append target — the lane's own JSONL feed, so existing markers/readers keep working. */
  file: string;
  marketId: string;
  outcome: string;
  /** Copy side as decided (BUY for every copy path today); recorded, never inferred. */
  side: string;
  walletAddress: string;
  /** Executable-ish price the declined copy would have paid. */
  entryPrice: number;
  fill: CounterfactualFill;
  copyScore?: number | null;
  confidence?: number | null;
  ttrHours?: number | null;
  spread?: number | null;
  liquidity?: number | null;
  /** Decision time; defaults to now. Distinct from `ts` only for backfilled rows. */
  decidedAt?: string;
  /** RuleSet era at decision time, when the lane knows it (criterion (d) of the pre-registered read). */
  era?: string | null;
  /** Why the gate fired, verbatim. */
  reason?: string | null;
  /** Lane-specific fields, written flat beside the canonical ones. */
  extras?: Record<string, unknown>;
}

/**
 * Build (but do not write) one canonical candidate row. Pure, so a lane can be
 * tested without touching a file.
 */
export function buildCounterfactualRow(c: CounterfactualCandidateInput): Record<string, unknown> {
  if (!c.lane) throw new Error("counterfactual-ledger: lane is required");
  if (!c.file) throw new Error("counterfactual-ledger: file is required");
  if (typeof c.entryPrice !== "number" || !Number.isFinite(c.entryPrice) || c.entryPrice < 0) {
    throw new Error(`counterfactual-ledger: entryPrice must be a finite, non-negative number (${c.marketId}|${c.outcome})`);
  }
  if (typeof c.fill?.stakeUsd !== "number" || !Number.isFinite(c.fill.stakeUsd) || c.fill.stakeUsd <= 0) {
    throw new Error(`counterfactual-ledger: fill.stakeUsd must be a positive number (${c.marketId}|${c.outcome})`);
  }
  if (c.fill.kind !== "fixed_clip" && c.fill.kind !== "would_be_size") {
    throw new Error(`counterfactual-ledger: unknown fill kind ${String(c.fill.kind)}`);
  }
  const extras = c.extras ?? {};
  for (const key of CANONICAL_KEYS) {
    if (key in extras && key !== "reason") {
      throw new Error(`counterfactual-ledger: extra field "${key}" collides with a canonical field`);
    }
  }
  const decidedAt = c.decidedAt ?? new Date().toISOString();
  return {
    ts: new Date().toISOString(),
    type: "candidate",
    schema: COUNTERFACTUAL_SCHEMA_VERSION,
    lane: c.lane,
    marketId: c.marketId,
    outcome: c.outcome,
    side: c.side,
    wallet: c.walletAddress,
    entryPrice: c.entryPrice,
    stakeUsd: c.fill.stakeUsd,
    fillKind: c.fill.kind,
    decidedAt,
    era: c.era ?? null,
    ...extras,
    reason: c.reason ?? null,
  };
}

/** Append one candidate row to its lane feed. */
export function appendCounterfactualCandidate(c: CounterfactualCandidateInput): Record<string, unknown> {
  const row = buildCounterfactualRow(c);
  fs.appendFileSync(c.file, JSON.stringify(row) + "\n");
  return row;
}

/** Append one settlement mark. The resolve key is (marketId, outcome) — never the stake or wallet. */
export function appendCounterfactualResolve(
  file: string,
  marketId: string,
  outcome: string,
  value: number
): void {
  if (value !== 0 && value !== 1) {
    throw new Error(`counterfactual-ledger: resolve value must be 0 or 1 (got ${value} for ${marketId}|${outcome})`);
  }
  fs.appendFileSync(
    file,
    JSON.stringify({ ts: new Date().toISOString(), type: "resolve", marketId, outcome, value }) + "\n"
  );
}

/**
 * THE fill rule: what a declined ticket would have returned. A copy is a ticket on
 * the row's own outcome token, so a resolved 1 pays `stake * (1 - entry) / entry`
 * and a resolved 0 loses the stake's notional (`-stake`). A non-executable entry
 * (<= 0) returns 0 rather than a manufactured windfall — the same guard every
 * legacy lane used, now in one place.
 */
export function counterfactualPnl(entryPrice: number, settledValue: number, stakeUsd: number): number {
  if (!(entryPrice > 0)) return 0;
  return ((settledValue - entryPrice) / entryPrice) * stakeUsd;
}

/** A settled row is a win when the row's outcome token won. */
export function counterfactualWon(settledValue: number): boolean {
  return settledValue > 0;
}

/** Coarse band edges used by the calibration table (kept as lane data, not policy). */
export const COARSE_BAND_EDGES: ReadonlyArray<[number, number]> = [
  [0, 0.2],
  [0.2, 0.4],
  [0.4, 0.6],
  [0.6, 0.8],
  [0.8, 1.01],
];

/** Finer price split, so a band read can separate a banned sub-0.05 tail. */
export const FINE_PRICE_BAND_EDGES: ReadonlyArray<[number, number]> = [
  [0, 0.05],
  [0.05, 0.1],
  [0.1, 0.2],
  [0.2, 0.4],
  [0.4, 0.6],
  [0.6, 0.8],
  [0.8, 1.01],
];

/** Bucket a price onto a declared edge table. Pure; edges are the caller's policy. */
export function priceBandOf(price: number, edges: ReadonlyArray<[number, number]> = COARSE_BAND_EDGES): string {
  for (const [lo, hi] of edges) if (price >= lo && price < hi) return `${lo}-${hi}`;
  return "other";
}

export function readLedger(file: string): Array<Record<string, unknown>> {
  try {
    return fs
      .readFileSync(file, "utf-8")
      .split("\n")
      .filter((l) => l.trim().length > 0)
      .map((l) => JSON.parse(l) as Record<string, unknown>);
  } catch {
    return [];
  }
}

/** Pre-port rows carry the price under `currentPrice` (three lanes) or `entryPrice` (long-shot ladder). */
export const DEFAULT_ENTRY_PRICE_FIELDS: ReadonlyArray<string> = ["currentPrice", "entryPrice"];

export function ledgerEntryPrice(
  row: Record<string, unknown>,
  fields: ReadonlyArray<string> = DEFAULT_ENTRY_PRICE_FIELDS
): number {
  for (const f of fields) {
    const v = row[f];
    if (typeof v === "number" && Number.isFinite(v)) return v;
  }
  return Number.NaN;
}

export function ledgerStake(
  row: Record<string, unknown>,
  opts: { stakeField?: string; defaultStakeUsd?: number } = {}
): number {
  const v = row[opts.stakeField ?? "stakeUsd"];
  if (typeof v === "number" && Number.isFinite(v)) return v;
  return opts.defaultStakeUsd ?? 0;
}

/**
 * One row per distinct copy signal: (marketId, outcome, wallet), keeping the
 * EARLIEST poll — the decision the gate actually made and the price a relaxed
 * tolerance would have paid. Copied here from shadow-drift (2026-10-11 instrument
 * v2) so every lane's per-opportunity basis uses one key and one tie-break.
 */
export function dedupeSignals(
  rows: Array<Record<string, unknown>>
): Map<string, Record<string, unknown>> {
  return dedupeBy(rows, (c) => `${c.marketId}|${c.outcome}|${c.wallet}`);
}

/** Earliest candidate per arbitrary key (market-only basis uses this with marketId). */
export function dedupeBy(
  rows: Array<Record<string, unknown>>,
  keyOf: (r: Record<string, unknown>) => string
): Map<string, Record<string, unknown>> {
  const out = new Map<string, Record<string, unknown>>();
  for (const c of rows) {
    if (c.type !== "candidate") continue;
    const key = keyOf(c);
    const prev = out.get(key);
    if (!prev || String(c.ts) < String(prev.ts)) out.set(key, c);
  }
  return out;
}

export interface LedgerReadOptions {
  /** Fields to try for the entry price, in order (legacy row shapes). */
  entryPriceFields?: ReadonlyArray<string>;
  /** Field carrying the stake (default `stakeUsd`; the wallet-cap lane used `sizeUsd`). */
  stakeField?: string;
  /** Stake to assume when a row carries none. */
  defaultStakeUsd?: number;
  /**
   * Dust floor for the ex-dust mean (null/undefined = no floor). A $0.0005 entry
   * that settles at 1 returns 2000x; excluded rows are reported, never silently
   * dropped. The floor is a READ OPTION so every lane gets the same one.
   */
  dustMinEntry?: number | null;
  /** Trailing cohort window in days (default 7). */
  cohortDays?: number;
  /** Clock override, for tests and for reading a frozen window. */
  now?: number;
  /** Restrict the priced sub-population (the long-shot ladder prices only its admits). */
  betFilter?: (row: Record<string, unknown>) => boolean;
}

export interface GroupStats {
  /** Candidates in the group (resolved or not). */
  n: number;
  marked: number;
  wouldHavePnl: number;
}

export interface LedgerStats {
  /** Candidate rows matching the lane's bet filter. */
  bets: number;
  /** Candidate rows of ANY status (the lane's raw feed size). */
  candidates: number;
  marked: number;
  awaitingResolution: number;
  wins: number;
  winRate: number | null;
  wouldHavePnl: number;
  avgPnlPerTrade: number | null;
  /** Total stake on marked rows. */
  stakedUsd: number;
  /** Ex-dust read. `minEntryPrice` is null when no floor was requested. */
  exDust: {
    minEntryPrice: number | null;
    marked: number;
    wouldHavePnl: number;
    avgPnlPerTrade: number | null;
    excluded: number;
  };
  /** Trailing cohort (decision time), priced ex-dust when a floor is set. */
  cohort: { days: number; marked: number; wouldHavePnl: number; avgPnlPerTrade: number | null };
  /** Every distinct copy signal (marketId|outcome|wallet), settled or not. */
  signals: number;
  signalsSettled: number;
  /** Per-signal basis, ex-dust (instrument v2); `dustExcluded` counts settled signals under the floor. */
  perSignal: {
    settled: number;
    exDustMarked: number;
    exDustWouldHavePnl: number;
    exDustAvg: number | null;
    dustExcluded: number;
    cohortMarked: number;
    cohortAvg: number | null;
  };
  /** One-ticket-per-signal / one-ticket-per-market totals (raw, no dust filter). */
  perOpportunity: {
    signals: number;
    markets: number;
    wouldHavePnlPerSignal: number;
    wouldHavePnlOneBetPerMarket: number;
  };
  firstCandidateAt: string | null;
  lastCandidateAt: string | null;
}

const round2 = (v: number) => Math.round(v * 100) / 100;
const mean = (sum: number, n: number) => (n > 0 ? round2(sum / n) : null);

/**
 * THE declarative read. Every lane summary is a view of this: same resolve join,
 * same fill rule, same dust floor, same dedupe, same cohort window.
 */
export function summarizeLedger(
  rows: Array<Record<string, unknown>>,
  opts: LedgerReadOptions = {}
): LedgerStats {
  const entryFields = opts.entryPriceFields ?? DEFAULT_ENTRY_PRICE_FIELDS;
  const stakeOf = (r: Record<string, unknown>) =>
    ledgerStake(r, { stakeField: opts.stakeField, defaultStakeUsd: opts.defaultStakeUsd });
  const pick = (r: Record<string, unknown>) => ledgerEntryPrice(r, entryFields);

  const candidates = rows.filter((r) => r.type === "candidate");
  const bets = opts.betFilter ? candidates.filter(opts.betFilter) : candidates;
  const resolves = new Map<string, number>();
  for (const r of rows) {
    if (r.type === "resolve") resolves.set(`${r.marketId}|${r.outcome}`, Number(r.value));
  }
  const settle = (r: Record<string, unknown>) => resolves.get(`${r.marketId}|${r.outcome}`);

  const dustMin = opts.dustMinEntry ?? null;
  const cohortDays = opts.cohortDays ?? 7;
  const now = opts.now ?? Date.now();
  const cohortCutoff = now - cohortDays * 86400000;
  const inCohort = (r: Record<string, unknown>) => {
    const at = Date.parse(String(r.ts));
    return Number.isFinite(at) && at >= cohortCutoff;
  };

  let marked = 0;
  let wins = 0;
  let pnl = 0;
  let staked = 0;
  let exMarked = 0;
  let exPnl = 0;
  let cohortMarked = 0;
  let cohortPnl = 0;
  for (const bet of bets) {
    const v = settle(bet);
    if (v === undefined) continue;
    const entry = pick(bet);
    const stake = stakeOf(bet);
    const rowPnl = counterfactualPnl(entry, v, stake);
    marked++;
    if (counterfactualWon(v)) wins++;
    pnl += rowPnl;
    staked += stake;
    const overFloor = dustMin === null || entry >= dustMin;
    if (overFloor) {
      exMarked++;
      exPnl += rowPnl;
      if (inCohort(bet)) {
        cohortMarked++;
        cohortPnl += rowPnl;
      }
    }
  }

  // --- per-signal basis (one row per marketId|outcome|wallet, earliest poll) ----
  const signals = dedupeSignals(bets);
  let signalsSettled = 0;
  let sigMarked = 0;
  let sigPnl = 0;
  let sigDust = 0;
  let sigCohortMarked = 0;
  let sigCohortPnl = 0;
  for (const sig of signals.values()) {
    const v = settle(sig);
    if (v === undefined) continue;
    signalsSettled++;
    const entry = pick(sig);
    if (dustMin !== null && !(entry >= dustMin)) {
      sigDust++;
      continue;
    }
    const rowPnl = counterfactualPnl(entry, v, stakeOf(sig));
    sigMarked++;
    sigPnl += rowPnl;
    if (inCohort(sig)) {
      sigCohortMarked++;
      sigCohortPnl += rowPnl;
    }
  }

  // --- one-ticket-per-opportunity totals (the LEVEL basis a gate question needs) --
  const perSignal = dedupeBy(bets, (c) => `${c.marketId}|${c.outcome}|${c.wallet}`);
  const perMarket = dedupeBy(bets, (c) => String(c.marketId));
  let perSignalPnl = 0;
  let perMarketPnl = 0;
  for (const sig of perSignal.values()) {
    const v = settle(sig);
    if (v === undefined) continue;
    perSignalPnl += counterfactualPnl(pick(sig), v, stakeOf(sig));
  }
  for (const m of perMarket.values()) {
    const v = settle(m);
    if (v === undefined) continue;
    perMarketPnl += counterfactualPnl(pick(m), v, stakeOf(m));
  }

  const ts = candidates.map((r) => String(r.ts)).sort();
  return {
    bets: bets.length,
    candidates: candidates.length,
    marked,
    awaitingResolution: bets.length - marked,
    wins,
    winRate: marked ? wins / marked : null,
    wouldHavePnl: round2(pnl),
    avgPnlPerTrade: mean(pnl, marked),
    stakedUsd: round2(staked),
    exDust: {
      minEntryPrice: dustMin,
      marked: exMarked,
      wouldHavePnl: round2(exPnl),
      avgPnlPerTrade: mean(exPnl, exMarked),
      excluded: marked - exMarked,
    },
    cohort: {
      days: cohortDays,
      marked: cohortMarked,
      wouldHavePnl: round2(cohortPnl),
      avgPnlPerTrade: mean(cohortPnl, cohortMarked),
    },
    signals: signals.size,
    signalsSettled,
    perSignal: {
      settled: signalsSettled,
      exDustMarked: sigMarked,
      exDustWouldHavePnl: round2(sigPnl),
      exDustAvg: mean(sigPnl, sigMarked),
      dustExcluded: sigDust,
      cohortMarked: sigCohortMarked,
      cohortAvg: mean(sigCohortPnl, sigCohortMarked),
    },
    perOpportunity: {
      signals: signalsSettled,
      markets: new Set(
        bets.filter((b) => settle(b) !== undefined).map((b) => String(b.marketId))
      ).size,
      wouldHavePnlPerSignal: round2(perSignalPnl),
      wouldHavePnlOneBetPerMarket: round2(perMarketPnl),
    },
    firstCandidateAt: ts.length ? ts[0] : null,
    lastCandidateAt: ts.length ? ts[ts.length - 1] : null,
  };
}

/**
 * Breakdown by an arbitrary key (band, wallet, confidence bucket) using the same
 * resolve join and fill rule. `n` counts every candidate in the group; `marked`
 * and `wouldHavePnl` count the settled ones only — the convention all four lane
 * breakdowns already used.
 */
export function groupStats(
  rows: Array<Record<string, unknown>>,
  keyOf: (row: Record<string, unknown>) => string,
  opts: LedgerReadOptions = {}
): Record<string, GroupStats> {
  const entryFields = opts.entryPriceFields ?? DEFAULT_ENTRY_PRICE_FIELDS;
  const stakeOf = (r: Record<string, unknown>) =>
    ledgerStake(r, { stakeField: opts.stakeField, defaultStakeUsd: opts.defaultStakeUsd });
  const resolves = new Map<string, number>();
  for (const r of rows) {
    if (r.type === "resolve") resolves.set(`${r.marketId}|${r.outcome}`, Number(r.value));
  }
  const candidates = rows.filter((r) => r.type === "candidate" && (opts.betFilter ? opts.betFilter(r) : true));
  const out: Record<string, GroupStats> = {};
  for (const c of candidates) {
    const key = keyOf(c);
    const g = (out[key] ??= { n: 0, marked: 0, wouldHavePnl: 0 });
    g.n++;
    const v = resolves.get(`${c.marketId}|${c.outcome}`);
    if (v === undefined) continue;
    g.marked++;
    g.wouldHavePnl += counterfactualPnl(ledgerEntryPrice(c, entryFields), v, stakeOf(c));
  }
  for (const g of Object.values(out)) g.wouldHavePnl = round2(g.wouldHavePnl);
  return out;
}

/**
 * SETTLED-LEVEL DUST READ — the floor applied to the decisions that actually
 * settled, at all three levels a gate question is asked at (row / copy signal /
 * market), plus what the floor removed and how concentrated the remainder is.
 *
 * WHY a separate function instead of more options on `summarizeLedger`: a lane's
 * LEVEL basis keys on the EARLIEST SETTLED poll of a key (the lowconf lane's
 * `marketLedger` and its `basis` have worked that way since 2026-10-26), while the
 * row-level totals key on every poll. Folding the two into one pass would change
 * the published drift basis; keeping one implementation of the settled-level rule
 * here is what stops a lane from growing its own again — which is exactly what
 * happened on 2026-10-31, when a private copy of this arithmetic had to be added
 * to the confidence lane because the shared read could not express it.
 *
 * All money fields are returned UNROUNDED; the lane rounds what it publishes, so
 * this file owns the arithmetic and not the presentation.
 */
export interface DustReadOptions {
  entryPriceFields?: ReadonlyArray<string>;
  stakeField?: string;
  defaultStakeUsd?: number;
  /** The floor. Required: a dust read with no floor is just the inclusive read. */
  dustMinEntry: number;
  /**
   * A second, LOWER cut reported at market level — the admission tail a rule
   * already bans (lowconf's v67 sub-0.05 band floor), kept separately reconcilable.
   */
  bannedTailMax?: number;
  /** Concentration cut for the market-level total (default 10). */
  topN?: number;
  betFilter?: (row: Record<string, unknown>) => boolean;
}

export interface SettledDustRead {
  row: {
    marked: number;
    /** Dust-INCLUSIVE row-level total — the ticket stream. */
    wouldHavePnl: number;
    dustExcluded: number;
    dustWouldHavePnl: number;
    exDustMarked: number;
    exDustWouldHavePnl: number;
    exDustAvgPnlPerTrade: number | null;
  };
  signal: {
    /** Distinct settled copy signals (marketId|outcome|wallet, earliest settled poll). */
    settled: number;
    dustExcluded: number;
    /** Dust-inclusive total over those signals. */
    wouldHavePnl: number;
    exDustMarked: number;
    exDustWouldHavePnl: number;
  };
  market: {
    /** Distinct settled markets (earliest settled poll each) — the BET basis. */
    settled: number;
    dustExcluded: number;
    /** Dust-inclusive total over those markets. */
    wouldHavePnl: number;
    exDustMarkets: number;
    exDustWouldHavePnl: number;
    topN: number;
    exTopNWouldHavePnl: number;
    topMarketId: string | null;
    topMarketPnl: number;
    topMarketShare: number | null;
    bannedTailMax: number | null;
    bannedTailMarkets: number;
    bannedTailWouldHavePnl: number;
  };
}

export function settledDustRead(
  rows: Array<Record<string, unknown>>,
  opts: DustReadOptions
): SettledDustRead {
  const entryFields = opts.entryPriceFields ?? DEFAULT_ENTRY_PRICE_FIELDS;
  const stakeOf = (r: Record<string, unknown>) =>
    ledgerStake(r, { stakeField: opts.stakeField, defaultStakeUsd: opts.defaultStakeUsd });
  const resolves = new Map<string, number>();
  for (const r of rows) {
    if (r.type === "resolve") resolves.set(`${r.marketId}|${r.outcome}`, Number(r.value));
  }

  interface Level {
    key: string;
    t: number;
    pnl: number;
    entry: number;
  }
  const bySignal = new Map<string, Level>();
  const byMarket = new Map<string, Level>();
  const keepEarliest = (map: Map<string, Level>, key: string, row: Level) => {
    const prev = map.get(key);
    if (prev === undefined || row.t < prev.t) map.set(key, row);
  };

  let marked = 0;
  let pnl = 0;
  let dustExcluded = 0;
  let dustPnl = 0;
  for (const c of rows) {
    if (c.type !== "candidate") continue;
    if (opts.betFilter && !opts.betFilter(c)) continue;
    const v = resolves.get(`${c.marketId}|${c.outcome}`);
    if (v === undefined) continue;
    const entry = ledgerEntryPrice(c, entryFields);
    const rowPnl = counterfactualPnl(entry, v, stakeOf(c));
    marked++;
    pnl += rowPnl;
    if (!(entry >= opts.dustMinEntry)) {
      dustExcluded++;
      dustPnl += rowPnl;
    }
    const at = Date.parse(String(c.ts));
    const t = Number.isFinite(at) ? at : Number.POSITIVE_INFINITY;
    const marketKey = String(c.marketId);
    const signalKey = `${c.marketId}|${c.outcome}|${c.wallet ?? ""}`;
    keepEarliest(bySignal, signalKey, { key: signalKey, t, pnl: rowPnl, entry });
    keepEarliest(byMarket, marketKey, { key: marketKey, t, pnl: rowPnl, entry });
  }

  const overFloor = (r: Level) => r.entry >= opts.dustMinEntry;
  const sum = (rs: Level[]) => rs.reduce((s, r) => s + r.pnl, 0);

  const signalRows = [...bySignal.values()];
  const exDustSignals = signalRows.filter(overFloor);

  const marketRows = [...byMarket.values()];
  const exDustMarkets = marketRows.filter(overFloor);
  const marketExDust = sum(exDustMarkets);
  const ranked = [...exDustMarkets].sort((a, b) => b.pnl - a.pnl);
  const topN = opts.topN ?? 10;
  const topNpnl = ranked.slice(0, topN).reduce((s, r) => s + r.pnl, 0);
  const top = ranked[0];
  const bannedTailMax = opts.bannedTailMax ?? null;
  const bannedTail =
    bannedTailMax === null
      ? []
      : marketRows.filter((r) => r.entry > 0 && r.entry < bannedTailMax);

  return {
    row: {
      marked,
      wouldHavePnl: pnl,
      dustExcluded,
      dustWouldHavePnl: dustPnl,
      exDustMarked: marked - dustExcluded,
      exDustWouldHavePnl: pnl - dustPnl,
      exDustAvgPnlPerTrade: marked - dustExcluded ? (pnl - dustPnl) / (marked - dustExcluded) : null,
    },
    signal: {
      settled: signalRows.length,
      dustExcluded: signalRows.length - exDustSignals.length,
      wouldHavePnl: sum(signalRows),
      exDustMarked: exDustSignals.length,
      exDustWouldHavePnl: sum(exDustSignals),
    },
    market: {
      settled: marketRows.length,
      dustExcluded: marketRows.length - exDustMarkets.length,
      wouldHavePnl: sum(marketRows),
      exDustMarkets: exDustMarkets.length,
      exDustWouldHavePnl: marketExDust,
      topN,
      exTopNWouldHavePnl: marketExDust - topNpnl,
      topMarketId: top ? top.key : null,
      topMarketPnl: top ? top.pnl : 0,
      topMarketShare: top && marketExDust !== 0 ? top.pnl / marketExDust : null,
      bannedTailMax,
      bannedTailMarkets: bannedTail.length,
      bannedTailWouldHavePnl: sum(bannedTail),
    },
  };
}

/**
 * Adapter to the PRE-REGISTERED read (src/lib/shadow-read.ts, phil audit Trial A).
 *
 * WHY this lives here: criterion (d) of that read is "the same sign holds inside
 * each ruleSetVersion era", and the read can only see an era if the feed recorded
 * one. Every lane now writes `era` through the same primitive, so all lanes are
 * read by one function with one row shape instead of four ad-hoc projections —
 * and a lane that records no era is reported by the read as UNVERIFIABLE, never
 * silently treated as passing.
 *
 * Settlement is the gate: only marked rows carry a return, so only marked rows
 * enter the read. `stake` is the row's declared fill stake.
 */
export function toShadowReadRows(
  rows: Array<Record<string, unknown>>,
  opts: LedgerReadOptions = {}
): Array<import("./shadow-read").ShadowReadRow> {
  const entryFields = opts.entryPriceFields ?? DEFAULT_ENTRY_PRICE_FIELDS;
  const resolves = new Map<string, number>();
  for (const r of rows) {
    if (r.type === "resolve") resolves.set(`${r.marketId}|${r.outcome}`, Number(r.value));
  }
  const out: Array<import("./shadow-read").ShadowReadRow> = [];
  for (const c of rows) {
    if (c.type !== "candidate") continue;
    if (opts.betFilter && !opts.betFilter(c)) continue;
    const v = resolves.get(`${c.marketId}|${c.outcome}`);
    if (v === undefined) continue;
    const stake = ledgerStake(c, { stakeField: opts.stakeField, defaultStakeUsd: opts.defaultStakeUsd });
    if (!(stake > 0)) continue;
    const pnl = counterfactualPnl(ledgerEntryPrice(c, entryFields), v, stake);
    const decidedAt = Date.parse(String(c.decidedAt ?? c.ts));
    out.push({
      key: `${c.marketId}|${c.outcome}|${c.wallet}|${c.ts}`,
      cluster: String(c.marketId),
      ret: pnl / stake,
      stake,
      won: counterfactualWon(v),
      decidedAt: Number.isFinite(decidedAt) ? decidedAt : 0,
      era: typeof c.era === "string" && c.era.length > 0 ? c.era : null,
    });
  }
  return out;
}
