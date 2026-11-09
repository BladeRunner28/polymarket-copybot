/**
 * market-hygiene rank read — the PRE-REGISTERED measurement, as pure functions.
 *
 * WHY (card `polyterm-p3-hygiene-preregistered-read`, audit §P3, drafts/polyterm-audit-2026-09-28.md:179):
 * `src/lib/market-hygiene.ts` scores markets (`heuristic`, `advisory_only`, read by no live path).
 * The audit fixed the only acceptable promotion test in advance: rank correlation between the
 * hygiene score and the SUBSEQUENT realized copy outcome, on the same rows, with the sign checked
 * inside each ruleSetVersion era separately, and a kill rule ("fewer than ~150 settled rows per
 * arm is too few decisions to price the gate, not a verdict"). "The scores look sensible" is not
 * that measurement. This module is the arithmetic; scripts/market-hygiene-rank-read.ts is the read.
 *
 * PRE-REGISTERED DECISION RULE (written before the first run, 2026-11-09):
 *   PASS  = Spearman(riskScore, per-$1 return) < 0 in ALL THREE eras
 *           AND the pooled market-clustered bootstrap 95% CI upper bound < 0.
 *           (riskScore is higher = riskier, so a real hygiene signal must rank LOWER returns.)
 *   NO RANK INFORMATION otherwise (sign flip, CI spanning zero, or an era below the n floor).
 *   A PASS is still NOT a promotion: promotion would be a Lane A change and needs approval.
 *   REFUTATION: if anything below contradicts the sign across eras, the card closes with that.
 *
 * Basis discipline: every consumer states population, level and clock. Nothing here reads time
 * except the caller passing an as-of instant.
 */

export type HygieneRankLeg = {
  legId: string;
  /** Clustering key for the bootstrap: legs inside one market are not independent. */
  marketId: string;
  /** Era label from eraOf(ruleSetVersion) — see src/lib/training-export.ts. */
  era: string;
  /** DecisionJournal.ruleSetVersion the leg was scored under; null = unversioned row. */
  ruleSetVersion: number | null;
  /** As-of snapshot instant the score was computed at (ms). Always <= the decision instant. */
  snapAtMs: number;
  riskScore: number;
  riskGrade: string;
  washScore: number;
  washAssessed: boolean;
  entryPrice: number;
  /** realizedPnl / simulatedPositionSize: per $1 staked. Positive = the copy made money. */
  returned: number;
  /** True when the leg settled at the venue's outcome rather than being exited early. */
  settlement: boolean;
};

export type ReturnSummary = {
  n: number;
  mean: number;
  median: number;
  /** 10% trimmed mean (both tails), the standard guard against one fat leg. */
  trimmedMean: number;
  winRate: number;
  sum: number;
  /** Mean per $1 with the 10 best legs removed — the concentration check. */
  exTop10: number;
};

export function returnSummary(values: readonly number[]): ReturnSummary {
  const n = values.length;
  if (n === 0) {
    return { n: 0, mean: 0, median: 0, trimmedMean: 0, winRate: 0, sum: 0, exTop10: 0 };
  }
  const sorted = [...values].sort((a, b) => a - b);
  const mean = (xs: readonly number[]) => xs.reduce((a, b) => a + b, 0) / xs.length;
  const median = n % 2 === 1 ? sorted[(n - 1) / 2] : (sorted[n / 2 - 1] + sorted[n / 2]) / 2;
  const cut = Math.floor(n * 0.1);
  const trimmed = cut > 0 ? sorted.slice(cut, n - cut) : sorted;
  const exTop = n > 10 ? sorted.slice(0, n - 10) : [];
  return {
    n,
    mean: mean(sorted),
    median,
    trimmedMean: mean(trimmed),
    winRate: values.filter((v) => v > 0).length / n,
    sum: sorted.reduce((a, b) => a + b, 0),
    exTop10: exTop.length ? mean(exTop) : 0,
  };
}

/** Tie-averaged 1-based ranks. */
export function averageRanks(values: readonly number[]): number[] {
  const idx = values.map((v, i) => ({ v, i })).sort((a, b) => a.v - b.v);
  const ranks = new Array<number>(values.length).fill(0);
  let start = 0;
  while (start < idx.length) {
    let end = start;
    while (end + 1 < idx.length && idx[end + 1].v === idx[start].v) end++;
    const avg = (start + end) / 2 + 1;
    for (let k = start; k <= end; k++) ranks[idx[k].i] = avg;
    start = end + 1;
  }
  return ranks;
}

function pearson(xs: readonly number[], ys: readonly number[]): number | null {
  const n = xs.length;
  if (n < 3) return null;
  const mx = xs.reduce((a, b) => a + b, 0) / n;
  const my = ys.reduce((a, b) => a + b, 0) / n;
  let sxy = 0;
  let sxx = 0;
  let syy = 0;
  for (let i = 0; i < n; i++) {
    const dx = xs[i] - mx;
    const dy = ys[i] - my;
    sxy += dx * dy;
    sxx += dx * dx;
    syy += dy * dy;
  }
  if (sxx === 0 || syy === 0) return null;
  return sxy / Math.sqrt(sxx * syy);
}

/**
 * Spearman rank correlation. Null when n < 3 or either side is constant — "cannot answer" must
 * never be printed as 0.0, which would read as "no relationship" rather than "no variance".
 */
export function spearman(xs: readonly number[], ys: readonly number[]): number | null {
  if (xs.length !== ys.length) throw new Error("spearman: length mismatch");
  return pearson(averageRanks(xs), averageRanks(ys));
}

/** Deterministic RNG so a published CI can be reproduced. */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export type ClusterBootstrap = { lo: number; hi: number; iters: number; usable: number };

/**
 * Percentile bootstrap over CLUSTERS (markets), not legs: legs in one market share a market-level
 * score and a shared outcome shock, so a leg-level CI would be far too narrow.
 */
export function clusterBootstrapSpearman(
  points: readonly { cluster: string; x: number; y: number }[],
  stat: (xs: number[], ys: number[]) => number | null = spearman,
  iters = 4000,
  seed = 20261109,
): ClusterBootstrap | null {
  if (points.length < 3) return null;
  const byCluster = new Map<string, { x: number; y: number }[]>();
  for (const p of points) {
    const arr = byCluster.get(p.cluster) ?? [];
    arr.push({ x: p.x, y: p.y });
    byCluster.set(p.cluster, arr);
  }
  const clusters = [...byCluster.values()];
  if (clusters.length < 3) return null;
  const rand = mulberry32(seed);
  const draws: number[] = [];
  for (let it = 0; it < iters; it++) {
    const xs: number[] = [];
    const ys: number[] = [];
    for (let k = 0; k < clusters.length; k++) {
      const pick = clusters[Math.floor(rand() * clusters.length)];
      for (const row of pick) {
        xs.push(row.x);
        ys.push(row.y);
      }
    }
    const s = stat(xs, ys);
    if (s !== null && Number.isFinite(s)) draws.push(s);
  }
  if (draws.length < 100) return { lo: NaN, hi: NaN, iters, usable: draws.length };
  draws.sort((a, b) => a - b);
  const at = (q: number) => draws[Math.min(draws.length - 1, Math.max(0, Math.floor(q * (draws.length - 1))))];
  return { lo: at(0.025), hi: at(0.975), iters, usable: draws.length };
}

/** The audit's spread-of-inputs guard: an arm missing its inputs is not "clean". */
export const WASH_INPUT_COVERAGE_MIN = 0.5;

export type EraRead = {
  era: string;
  nLegs: number;
  nMarkets: number;
  nSettlementLegs: number;
  returns: ReturnSummary;
  riskSpearman: number | null;
  riskCi: ClusterBootstrap | null;
  washSpearman: number | null;
  washAssessedShare: number;
  byGrade: { grade: string; n: number; returns: ReturnSummary }[];
  /** Within-band read: the price confounder, controlled crudely. */
  byPriceBand: { band: string; n: number; riskSpearman: number | null }[];
};

const PRICE_BANDS: { band: string; lo: number; hi: number }[] = [
  { band: "0.00-0.20", lo: 0, hi: 0.2 },
  { band: "0.20-0.40", lo: 0.2, hi: 0.4 },
  { band: "0.40-0.60", lo: 0.4, hi: 0.6 },
  { band: "0.60-0.80", lo: 0.6, hi: 0.8 },
  { band: "0.80-1.00", lo: 0.8, hi: 1.0000001 },
];

export function priceBandOf(price: number): string {
  const hit = PRICE_BANDS.find((b) => price >= b.lo && price < b.hi);
  return hit?.band ?? "out-of-range";
}

export const ERA_ORDER = ["pre-kelly-v1-48", "kelly-window-v49-57", "exposure-v58plus"] as const;

/** Audit kill rule: below this many settled rows an arm is "too few decisions to price the gate". */
export const MIN_ARM_ROWS = 150;

export function readEra(era: string, legs: readonly HygieneRankLeg[]): EraRead {
  const rows = legs.filter((l) => l.era === era);
  const markets = new Set(rows.map((l) => l.marketId));
  const riskSpearman = spearman(rows.map((l) => l.riskScore), rows.map((l) => l.returned));
  const riskCi = clusterBootstrapSpearman(rows.map((l) => ({ cluster: l.marketId, x: l.riskScore, y: l.returned })));
  const washRows = rows.filter((l) => l.washAssessed);
  const byGradeMap = new Map<string, number[]>();
  for (const l of rows) {
    const arr = byGradeMap.get(l.riskGrade) ?? [];
    arr.push(l.returned);
    byGradeMap.set(l.riskGrade, arr);
  }
  const byPriceBand = PRICE_BANDS.map((b) => {
    const bandRows = rows.filter((l) => priceBandOf(l.entryPrice) === b.band);
    return {
      band: b.band,
      n: bandRows.length,
      riskSpearman: spearman(bandRows.map((l) => l.riskScore), bandRows.map((l) => l.returned)),
    };
  });
  return {
    era,
    nLegs: rows.length,
    nMarkets: markets.size,
    nSettlementLegs: rows.filter((l) => l.settlement).length,
    returns: returnSummary(rows.map((l) => l.returned)),
    riskSpearman,
    riskCi,
    washSpearman: washRows.length >= 3 ? spearman(washRows.map((l) => l.washScore), washRows.map((l) => l.returned)) : null,
    washAssessedShare: rows.length ? washRows.length / rows.length : 0,
    byGrade: ["A", "B", "C", "D", "F"].map((grade) => {
      const vals = byGradeMap.get(grade) ?? [];
      return { grade, n: vals.length, returns: returnSummary(vals) };
    }),
    byPriceBand,
  };
}

export type Verdict = {
  verdict: "PASS" | "NO RANK INFORMATION" | "TOO FEW DECISIONS";
  reasons: string[];
  pooledRiskSpearman: number | null;
  pooledCi: ClusterBootstrap | null;
};

/**
 * Apply the PRE-REGISTERED rule verbatim. No post-hoc additions: the rule was fixed in the audit
 * (2026-09-28) and restated in this file's header before the first run.
 */
export function preRegisteredVerdict(
  perEra: readonly EraRead[],
  legs: readonly HygieneRankLeg[],
): Verdict {
  const reasons: string[] = [];
  const arms = perEra.filter((e) => e.nLegs > 0);
  const thin = arms.filter((e) => e.nLegs < MIN_ARM_ROWS);
  const pooledRiskSpearman = spearman(legs.map((l) => l.riskScore), legs.map((l) => l.returned));
  const pooledCi = clusterBootstrapSpearman(legs.map((l) => ({ cluster: l.marketId, x: l.riskScore, y: l.returned })));
  if (thin.length > 0) {
    for (const t of thin) reasons.push(`${t.era}: ${t.nLegs} settled legs < ${MIN_ARM_ROWS} floor -> too few decisions to price the gate`);
    return { verdict: "TOO FEW DECISIONS", reasons, pooledRiskSpearman, pooledCi };
  }
  const missing = arms.filter((e) => e.riskSpearman === null);
  if (missing.length > 0) {
    for (const m of missing) reasons.push(`${m.era}: rank correlation undefined (no variance in score or return)`);
    return { verdict: "NO RANK INFORMATION", reasons, pooledRiskSpearman, pooledCi };
  }
  const allNegative = arms.every((e) => (e.riskSpearman as number) < 0);
  const ciExcludesZero = pooledCi !== null && Number.isFinite(pooledCi.hi) && pooledCi.hi < 0;
  if (allNegative && ciExcludesZero) {
    reasons.push(`risk score ranks lower returns in all ${arms.length} eras and the pooled clustered CI upper bound ${pooledCi!.hi.toFixed(3)} < 0`);
    return { verdict: "PASS", reasons, pooledRiskSpearman, pooledCi };
  }
  if (!allNegative) {
    const flips = arms.filter((e) => (e.riskSpearman as number) >= 0).map((e) => `${e.era} ${(e.riskSpearman as number).toFixed(3)}`);
    reasons.push(`sign is not negative in every era: ${flips.join(", ")}`);
  }
  if (pooledCi === null || !Number.isFinite(pooledCi.hi) || pooledCi.hi >= 0) {
    reasons.push(`pooled clustered CI does not exclude zero (hi=${pooledCi && Number.isFinite(pooledCi.hi) ? pooledCi.hi.toFixed(3) : "n/a"})`);
  }
  return { verdict: "NO RANK INFORMATION", reasons, pooledRiskSpearman, pooledCi };
}
