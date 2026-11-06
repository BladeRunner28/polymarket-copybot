/**
 * v65 paired read — the pure arithmetic behind the 2026-10-22 REC 1 instrument.
 *
 * Card: `v65-paired-read-instrument`. The rec was named in three consecutive weeklys with no
 * instrument ("close v65 as mechanism-verified + record its PnL read UNVERIFIABLE" — tuning cycle
 * #63), and its own gate is a PRECISION gate, not a significance gate:
 *
 *     2SE <= $10 per leg, at n >= 70 leg pairs, settled clock, isDemo=0, net of both legs' fees.
 *
 * WHY THE PRECISION GATE IS THE WHOLE POINT: the unpaired C-200 book has sd $79.60/leg, so
 * 2SE = 2*sd/sqrt(n) is $19.03 at n=70 and only reaches $10 near n=300. The rec said, in effect,
 * "pair the legs, and only then can this be read". 2SE <= $10 at n=70 requires a PAIRED sd of
 * <= $41.86 per pair — the pairing has to cancel at least half the per-leg dollar variance. This
 * module therefore reports the paired sd, the 2SE it implies, and the n that would be required at
 * the observed sd, so a run can state "no read is possible at this variance" instead of quoting a
 * point estimate whose interval is wider than any plausible effect.
 *
 * TWO PAIRING BASES, never pooled:
 *   exact  same lane + same market + same outcome — the pair shares the RESOLUTION EVENT, so the
 *          outcome-driven variance cancels exactly. This is the only basis that can plausibly meet
 *          the $-10 bar, and it is rare: a market must be copied on both sides of the epoch.
 *   class  same lane + same price band, nearest entry price (1:1, no replacement). Outcomes are
 *          independent draws, so this basis does NOT cancel resolution variance; it is printed
 *          beside `exact` precisely so the difference in paired sd is visible rather than assumed.
 *
 * Pure: no DB, no clock, no I/O. The caller supplies legs with their NET PnL already computed by
 * `feeDecomposition`/`netTargets` (src/lib/training-export.ts), so the fee law is imported from one
 * place and never re-implemented here.
 */

/** Price bands used by the C-200 band map and by every STANDARD band read. Half-open, [lo, hi). */
export const PRICE_BANDS: Array<{ label: string; lo: number; hi: number }> = [
  { label: "<0.20", lo: 0, hi: 0.2 },
  { label: "0.20-0.40", lo: 0.2, hi: 0.4 },
  { label: "0.40-0.60", lo: 0.4, hi: 0.6 },
  { label: "0.60-0.80", lo: 0.6, hi: 0.8 },
  { label: ">=0.80", lo: 0.8, hi: 1.0000001 },
];

export function priceBand(price: number): string {
  for (const b of PRICE_BANDS) if (price >= b.lo && price < b.hi) return b.label;
  return price >= 1 ? ">=0.80" : "<0.20";
}

/** One settled leg. `pnlNet` is already net of BOTH legs' fees for the basis being read. */
export type PairedLeg = {
  id: string;
  lane: string;
  marketId: string;
  outcome: string;
  entryPrice: number;
  sizeUsd: number;
  /** realizedPnl - entry fee - exit fee (0 exit fee on a settlement). */
  pnlNet: number;
  /** realizedPnl as booked (gross of fees). */
  pnlGross: number;
  openedAt: Date;
  settledAt: Date;
  ruleSetVersion: number | null;
};

export type PairBasis = "exact" | "class";

export type LegPair = {
  basis: PairBasis;
  post: PairedLeg;
  pre: PairedLeg;
  /** Pairing distance used by the greedy matcher (price gap for `class`, 0 for `exact`). */
  gap: number;
};

const ms = (d: Date) => d.getTime();

/**
 * 1:1 matching without replacement, greedy on a sort key. Deterministic: ties break on the post
 * leg id, so re-running on the same book cannot shuffle which legs land in which pair.
 */
function greedyMatch(
  post: PairedLeg[],
  pre: PairedLeg[],
  groupKey: (l: PairedLeg) => string,
  gap: (p: PairedLeg, q: PairedLeg) => number,
  admissible: (p: PairedLeg, q: PairedLeg) => boolean,
  basis: PairBasis
): LegPair[] {
  const byGroup = new Map<string, PairedLeg[]>();
  for (const q of pre) {
    const k = groupKey(q);
    const arr = byGroup.get(k);
    if (arr) arr.push(q);
    else byGroup.set(k, [q]);
  }
  const candidates: Array<{ p: PairedLeg; q: PairedLeg; gap: number }> = [];
  for (const p of post) {
    for (const q of byGroup.get(groupKey(p)) ?? []) {
      if (!admissible(p, q)) continue;
      candidates.push({ p, q, gap: gap(p, q) });
    }
  }
  candidates.sort((a, b) =>
    a.gap !== b.gap ? a.gap - b.gap : a.p.id !== b.p.id ? (a.p.id < b.p.id ? -1 : 1) : a.q.id < b.q.id ? -1 : 1
  );
  const usedPost = new Set<string>();
  const usedPre = new Set<string>();
  const out: LegPair[] = [];
  for (const c of candidates) {
    if (usedPost.has(c.p.id) || usedPre.has(c.q.id)) continue;
    usedPost.add(c.p.id);
    usedPre.add(c.q.id);
    out.push({ basis, post: c.p, pre: c.q, gap: c.gap });
  }
  return out;
}

/**
 * Same lane + same market + same outcome. The pair shares its resolution event: whatever the market
 * did, it did to both legs, so the difference is the position's own economics, not the draw.
 */
export function exactMates(post: PairedLeg[], pre: PairedLeg[]): LegPair[] {
  return greedyMatch(
    post,
    pre,
    (l) => `${l.lane}|${l.marketId}|${l.outcome}`,
    (p, q) => Math.abs(ms(p.openedAt) - ms(q.openedAt)),
    () => true,
    "exact"
  );
}

/**
 * Same lane + same price band, nearest entry price, within `maxPriceGap` (default 0.10 = one
 * half-band). Different markets are allowed and expected; this basis does NOT cancel the
 * resolution draw, and its paired sd is the reason to say so out loud.
 */
export function classPairs(post: PairedLeg[], pre: PairedLeg[], maxPriceGap = 0.1): LegPair[] {
  return greedyMatch(
    post,
    pre,
    (l) => `${l.lane}|${priceBand(l.entryPrice)}`,
    (p, q) => Math.abs(p.entryPrice - q.entryPrice),
    (p, q) => Math.abs(p.entryPrice - q.entryPrice) <= maxPriceGap,
    "class"
  );
}

export type PairedStats = {
  n: number;
  /** mean of (post - pre), dollars per pair. */
  meanDiff: number;
  sd: number;
  se: number;
  twoSe: number;
  sumDiff: number;
  preMean: number;
  postMean: number;
  preSd: number;
  postSd: number;
  clusters: number;
  /** Market-clustered 95% CI on `meanDiff` (CR0, cluster = the unordered market pair). */
  clusterCi: { lo: number; hi: number };
};

const mean = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0);

function sdOf(xs: number[]): number {
  if (xs.length < 2) return 0;
  const m = mean(xs);
  return Math.sqrt(xs.reduce((a, x) => a + (x - m) ** 2, 0) / (xs.length - 1));
}

/**
 * Paired statistics on (post - pre). Clusters are the unordered PAIR OF MARKETS, so two pairs that
 * share a market are treated as one observation for the interval — the same correction the slug-cap
 * and per-market reads use, applied here because a market can be copied repeatedly on both sides.
 */
export function pairedStats(pairs: LegPair[]): PairedStats {
  const diffs = pairs.map((p) => p.post.pnlNet - p.pre.pnlNet);
  const n = diffs.length;
  const m = mean(diffs);
  const sd = sdOf(diffs);
  const se = n > 0 ? sd / Math.sqrt(n) : 0;
  const groups = new Map<string, number[]>();
  for (let i = 0; i < pairs.length; i++) {
    const k = [pairs[i].post.marketId, pairs[i].pre.marketId].sort().join("|");
    const arr = groups.get(k);
    if (arr) arr.push(diffs[i]);
    else groups.set(k, [diffs[i]]);
  }
  const G = groups.size;
  let clusterVar = 0;
  if (n > 0 && G > 1) {
    for (const g of groups.values()) {
      const u = g.reduce((a, x) => a + x, 0) - g.length * m;
      clusterVar += u * u;
    }
    clusterVar = (clusterVar * (G / (G - 1))) / (n * n);
  }
  const halfWidth = G > 1 ? 1.96 * Math.sqrt(clusterVar) : NaN;
  return {
    n,
    meanDiff: m,
    sd,
    se,
    twoSe: 2 * se,
    sumDiff: diffs.reduce((a, x) => a + x, 0),
    preMean: mean(pairs.map((p) => p.pre.pnlNet)),
    postMean: mean(pairs.map((p) => p.post.pnlNet)),
    preSd: sdOf(pairs.map((p) => p.pre.pnlNet)),
    postSd: sdOf(pairs.map((p) => p.post.pnlNet)),
    clusters: G,
    clusterCi: { lo: m - halfWidth, hi: m + halfWidth },
  };
}

/** The rec's pre-registered bar, as constants rather than prose. */
export const V65_GATE = { maxTwoSe: 10, minPairs: 70 } as const;

export type GateVerdict = {
  n: number;
  twoSe: number;
  nPass: boolean;
  precisionPass: boolean;
  /** RESOLVABLE | UNRESOLVABLE-BY-PRECISION | VANISHED-BY-N (the card's own FAIL wording). */
  verdict: "RESOLVABLE" | "UNRESOLVABLE-BY-PRECISION" | "VANISHED-BY-N";
  /** At the observed paired sd, the pair count 2SE <= $10 would need. */
  requiredPairs: number;
  /** At n = minPairs, the largest paired sd that could still meet 2SE <= $10. */
  requiredSd: number;
};

/**
 * Precision needs a STATISTIC to be precise about: with an empty pairing, `sd` is 0 and 2SE is 0,
 * which would read as PASS on the precision clause and FAIL only on n. That is the right disposition
 * (VANISHED-BY-N), but the precision clause must not be quoted as met on zero pairs — so it is
 * reported false whenever n < 2.
 */
export function gateVerdict(stats: PairedStats, gate = V65_GATE): GateVerdict {
  const nPass = stats.n >= gate.minPairs;
  const precisionPass = stats.n >= 2 && stats.twoSe <= gate.maxTwoSe;
  const requiredPairs = stats.sd > 0 ? Math.ceil((2 * stats.sd / gate.maxTwoSe) ** 2) : gate.minPairs;
  const requiredSd = (gate.maxTwoSe * Math.sqrt(gate.minPairs)) / 2;
  const verdict: GateVerdict["verdict"] = !nPass
    ? "VANISHED-BY-N"
    : precisionPass
      ? "RESOLVABLE"
      : "UNRESOLVABLE-BY-PRECISION";
  return { n: stats.n, twoSe: stats.twoSe, nPass, precisionPass, verdict, requiredPairs, requiredSd };
}

/** Dollar formatting shared by the script and its tests, so a printed number has ONE form. */
export const usd = (n: number) => `${n >= 0 ? "+" : "-"}$${Math.abs(n).toFixed(2)}`;

/**
 * Concentration, on the paired differences. A mean that lives in its top few pairs is a draw, not an
 * effect — the repo has already published one of those (the <0.20 band's realised ROI, 120% of it in
 * ten legs). Every read therefore prints median, ex-top-3 and ex-top-10 beside the mean.
 */
export type Concentration = {
  sum: number;
  median: number;
  trimmedMean: number;
  exTop: Array<{ k: number; sum: number; mean: number }>;
  topShare: number;
};

export function diffConcentration(pairs: LegPair[], ks = [3, 10]): Concentration {
  const d = pairs.map((p) => p.post.pnlNet - p.pre.pnlNet).sort((a, b) => b - a);
  const n = d.length;
  const sum = d.reduce((a, x) => a + x, 0);
  const med = n ? (n % 2 ? d[(n - 1) / 2] : (d[n / 2 - 1] + d[n / 2]) / 2) : 0;
  // 10% trimmed mean, symmetric trim — stated so nobody has to guess the trim level.
  const trim = Math.floor(n * 0.1);
  const core = n > 2 * trim ? d.slice(trim, n - trim) : d;
  return {
    sum,
    median: med,
    trimmedMean: core.length ? core.reduce((a, x) => a + x, 0) / core.length : 0,
    exTop: ks.map((k) => {
      const rest = d.slice(k);
      return { k, sum: rest.reduce((a, x) => a + x, 0), mean: rest.length ? rest.reduce((a, x) => a + x, 0) / rest.length : 0 };
    }),
    topShare: sum !== 0 ? d.slice(0, 10).reduce((a, x) => a + x, 0) / sum : 0,
  };
}
