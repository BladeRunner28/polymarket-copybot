/**
 * Pre-registered shadow-read harness — phil audit Trial A
 * (drafts/phil-audit-2026-09-28.md §"Shadow-trial proposal").
 *
 * WHY: we already mark several shadow feeds to settlement (late-drift gate,
 * minConfidence bar, per-wallet ceilings), but each read is bespoke and reports
 * an average. phil's repo is the clearest available demonstration of what an
 * average hides: their sealed forward test returned -0.0730 with 145% of the
 * P&L in ONE bet, and their own pre-registered criteria (min bets, cw_return > 0,
 * single-bet dominance cap) are what caught it. This module is those criteria,
 * applied to ANY shadow feed, so the Oct 8 window close reads every lane the
 * same way instead of three different ways.
 *
 * WHAT IT IS NOT: a gate. Nothing here decides anything automatically, nothing
 * writes to a ruleset, and no live path imports it for a decision. It turns a
 * set of would-have decisions into a pre-registered verdict, and the verdict's
 * only authority is that its bar was fixed BEFORE the outcomes were read.
 *
 * The four criteria (all must hold — audit Trial A):
 *   (a) cw_return = roi - stake-weighted SE > 0
 *   (b) no single bet carries >= 50% of the total POSITIVE P&L
 *   (c) a market-CLUSTERED bootstrap 95% CI on roi excludes 0
 *   (d) the same sign holds inside each ruleSetVersion era separately
 *
 * Kill rule: fewer than `minBets` bets is "too few decisions to price the gate",
 * never a verdict. Under `minSettledPerArm` the read is `underpowered`: criteria
 * are still reported, but a low-n pass is not promotion evidence and a low-n
 * fail is not a rejection — phil's own forward read was 60 bets and one bet
 * dominated it, which is exactly the sample this rule refuses to judge.
 */

export type ShadowReadRow = {
  /** Identity, for reporting and dedupe (not used for clustering). */
  key: string;
  /** Bootstrap cluster. ALWAYS the market — rows on one market are not independent. */
  cluster: string;
  /** Return per $1 staked for this would-have decision (pnl / stake). */
  ret: number;
  /** Stake the row was priced at. */
  stake: number;
  /** Win/loss sign as settled, for the win-rate line only. */
  won: boolean;
  /** Decision time (ms epoch) — the era is the ruleSet active THEN, not now. */
  decidedAt: number;
  /**
   * Era label (e.g. "v55"). `null` means the feed does not record which ruleset
   * was live, which makes criterion (d) UNVERIFIABLE — and an unverifiable era
   * check is reported as `null`, never quietly treated as passing.
   */
  era: string | null;
};

export type ShadowReadOptions = {
  /** phil `MIN_BETS`: below this the read is too few decisions, not a verdict. */
  minBets?: number;
  /** Our sample bar: below this the read is underpowered (audit Trial A). */
  minSettledPerArm?: number;
  bootstrapIters?: number;
  /** Fixed seed: the CI must be reproducible, not a fresh draw per run. */
  seed?: number;
  alpha?: number;
};

export type EraRead = { era: string; bets: number; roi: number };

export type ShadowReadResult = {
  bets: number;
  clusters: number;
  stakeUsd: number;
  winRate: number;
  roi: number;
  /** Stake-weighted standard error of `roi` (definition below). */
  weightedSe: number;
  cwReturn: number;
  criterionA: boolean;
  largestWinnerShare: number;
  criterionB: boolean;
  ciLow: number;
  ciHigh: number;
  criterionC: boolean;
  eras: EraRead[] | null;
  /** null = unverifiable (no era labels), NOT "passed". */
  criterionD: boolean | null;
  decision: "pass" | "fail" | "too_few_bets" | "underpowered";
  reasons: string[];
};

const DEFAULTS = {
  minBets: 15,
  minSettledPerArm: 150,
  bootstrapIters: 2000,
  seed: 20261008,
  alpha: 0.05,
};

/**
 * Stake-weighted ROI and its standard error.
 *
 * `roi` is the stake-weighted mean of per-bet returns, i.e. total PnL per dollar
 * actually staked — not the mean of per-bet percentages, which would let a $0.02
 * stake outvote a $50 one.
 *
 * `SE` is the weighted standard error: sqrt( Σ wᵢ²(rᵢ - roi)² ) × sqrt(n/(n-1)),
 * with wᵢ = stakeᵢ / Σstake. The n/(n-1) factor is the usual finite-sample
 * correction; at n < 2 it is undefined and the SE is reported as the full spread
 * (a single bet cannot carry a standard error, and pretending otherwise is how
 * a one-bet sample becomes a "win").
 */
export function stakeWeightedRead(rows: readonly ShadowReadRow[]): { roi: number; se: number; stakeUsd: number } {
  const stakeUsd = rows.reduce((a, r) => a + r.stake, 0);
  if (rows.length === 0 || stakeUsd <= 0) return { roi: 0, se: 0, stakeUsd: 0 };
  const roi = rows.reduce((a, r) => a + (r.stake / stakeUsd) * r.ret, 0);
  if (rows.length < 2) return { roi, se: Math.abs(roi), stakeUsd };
  const variance =
    rows.reduce((a, r) => a + (r.stake / stakeUsd) ** 2 * (r.ret - roi) ** 2, 0) * (rows.length / (rows.length - 1));
  return { roi, se: Math.sqrt(Math.max(variance, 0)), stakeUsd };
}

/** Deterministic PRNG (mulberry32) so a re-run reproduces the same CI. */
function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Market-clustered bootstrap CI on the stake-weighted ROI. Resamples MARKET
 * groups, never rows: several would-have bets on one market share a single
 * resolution, so row-level resampling would understate the interval — the
 * mistake a plausible-looking bootstrap makes.
 */
export function clusteredBootstrapCi(
  rows: readonly ShadowReadRow[],
  opts: { iters?: number; seed?: number; alpha?: number } = {}
): { low: number; high: number } {
  const iters = opts.iters ?? DEFAULTS.bootstrapIters;
  const alpha = opts.alpha ?? DEFAULTS.alpha;
  const byCluster = new Map<string, ShadowReadRow[]>();
  for (const r of rows) {
    const list = byCluster.get(r.cluster) ?? [];
    list.push(r);
    byCluster.set(r.cluster, list);
  }
  const groups = [...byCluster.values()];
  if (groups.length === 0) return { low: 0, high: 0 };
  if (groups.length === 1) {
    // One market cannot yield an interval: report a degenerate one and let the
    // caller see it excludes nothing.
    const { roi } = stakeWeightedRead(rows);
    return { low: roi, high: roi };
  }
  const rand = rng(opts.seed ?? DEFAULTS.seed);
  const draws: number[] = [];
  for (let i = 0; i < iters; i++) {
    const sample: ShadowReadRow[] = [];
    for (let g = 0; g < groups.length; g++) {
      sample.push(...groups[Math.floor(rand() * groups.length)]);
    }
    draws.push(stakeWeightedRead(sample).roi);
  }
  draws.sort((a, b) => a - b);
  const loIdx = Math.floor((alpha / 2) * draws.length);
  const hiIdx = Math.min(draws.length - 1, Math.ceil((1 - alpha / 2) * draws.length) - 1);
  return { low: draws[loIdx], high: draws[hiIdx] };
}

/**
 * Apply the pre-registered criteria. Pure and deterministic: same rows + same
 * options produce the same verdict, which is what "pre-registered" has to mean
 * to be worth anything.
 */
export function evaluateShadowRead(
  rows: readonly ShadowReadRow[],
  opts: ShadowReadOptions = {}
): ShadowReadResult {
  const minBets = opts.minBets ?? DEFAULTS.minBets;
  const minSettled = opts.minSettledPerArm ?? DEFAULTS.minSettledPerArm;
  const reasons: string[] = [];

  const { roi, se, stakeUsd } = stakeWeightedRead(rows);
  const cwReturn = roi - se;
  const criterionA = rows.length > 0 && cwReturn > 0;
  if (!criterionA) reasons.push(`(a) cw_return ${cwReturn.toFixed(4)} <= 0 (roi ${roi.toFixed(4)}, se ${se.toFixed(4)})`);

  // (b) single-bet dominance over POSITIVE P&L only: a big loser must not be
  // able to "dilute" a single outsized winner into looking diversified.
  const positive = rows.map((r) => r.stake * r.ret).filter((p) => p > 0);
  const totalPositive = positive.reduce((a, p) => a + p, 0);
  const largest = positive.length > 0 ? Math.max(...positive) : 0;
  const largestWinnerShare = totalPositive > 0 ? largest / totalPositive : 1;
  const criterionB = totalPositive > 0 && largestWinnerShare < 0.5;
  if (!criterionB) {
    reasons.push(
      totalPositive > 0
        ? `(b) largest bet is ${(largestWinnerShare * 100).toFixed(1)}% of positive P&L (cap 50%)`
        : "(b) no positive P&L at all"
    );
  }

  const ci = clusteredBootstrapCi(rows, { iters: opts.bootstrapIters, seed: opts.seed, alpha: opts.alpha });
  const clusters = new Set(rows.map((r) => r.cluster)).size;
  // A single market cannot yield an interval, so it cannot pass (c) — the
  // degenerate [roi, roi] would otherwise read as an interval that excludes 0.
  const criterionC = rows.length > 0 && clusters >= 2 && (ci.low > 0 || ci.high < 0);
  if (!criterionC) {
    reasons.push(
      clusters < 2
        ? `(c) only ${clusters} market cluster(s) — no interval to read`
        : `(c) clustered 95% CI [${ci.low.toFixed(4)}, ${ci.high.toFixed(4)}] includes 0`
    );
  }

  const eraRows = rows.filter((r) => r.era !== null);
  let eras: EraRead[] | null = null;
  let criterionD: boolean | null = null;
  if (eraRows.length === rows.length && rows.length > 0) {
    const byEra = new Map<string, ShadowReadRow[]>();
    for (const r of eraRows) {
      const list = byEra.get(r.era as string) ?? [];
      list.push(r);
      byEra.set(r.era as string, list);
    }
    eras = [...byEra.entries()]
      .map(([era, list]) => ({ era, bets: list.length, roi: stakeWeightedRead(list).roi }))
      .sort((a, b) => a.era.localeCompare(b.era));
    criterionD = eras.length > 0 && eras.every((e) => e.roi > 0);
    if (!criterionD) {
      reasons.push(`(d) sign not consistent across eras: ${eras.map((e) => `${e.era}=${e.roi.toFixed(3)}`).join(", ")}`);
    }
  } else {
    reasons.push("(d) UNVERIFIABLE — rows carry no ruleSetVersion era, so the era split cannot be read");
  }

  const decided = (): ShadowReadResult["decision"] => {
    if (rows.length < minBets) return "too_few_bets";
    if (rows.length < minSettled) return "underpowered";
    return criterionA && criterionB && criterionC && criterionD === true ? "pass" : "fail";
  };
  const decision = decided();
  if (decision === "too_few_bets") {
    reasons.unshift(`KILL RULE: ${rows.length} bets < ${minBets} — too few decisions to price the gate, NOT a verdict`);
  } else if (decision === "underpowered") {
    reasons.unshift(
      `UNDERPOWERED: ${rows.length} bets < ${minSettled} pre-registered bar — criteria reported, no promotion ` +
        `and no rejection (a low-n pass is how a one-bet sample becomes a "win")`
    );
  }

  const wins = rows.filter((r) => r.won).length;
  return {
    bets: rows.length,
    clusters,
    stakeUsd: Math.round(stakeUsd * 100) / 100,
    winRate: rows.length > 0 ? wins / rows.length : 0,
    roi,
    weightedSe: se,
    cwReturn,
    criterionA,
    largestWinnerShare,
    criterionB,
    ciLow: ci.low,
    ciHigh: ci.high,
    criterionC,
    eras,
    criterionD,
    decision,
    reasons,
  };
}
