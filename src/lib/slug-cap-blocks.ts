/**
 * slug-cap-blocks — the v45 per-slug cap, read back out of the journal, and the
 * price of the legs it refused.
 *
 * WHY THIS EXISTS (2026-10-30, slug-cap-token-granularity):
 * The 2026-09-23 measurement of this rail used `scripts/replay-slug-cap-basis.ts`,
 * a time-ordered replay over C-200 legs AS BOOKED. That instrument cannot see the
 * legs the cap itself blocked — a blocked leg never becomes a PaperTrade — so its
 * incumbent (token) arm can only ever report a LOWER bound, and it reports ~0 on a
 * window where the journal recorded 105 blocks. Its 2026-09-23 headline (83 legs
 * blocked, 71 on the mega-bucket token 'highest', "blocks net WINNERS = starving")
 * is worse than a lower bound: the replay is not cap-activation aware, so the
 * pre-v45 stock (v45 activated 2026-09-03T06:43:59Z; token 'highest' ran to 80
 * concurrent open legs before it) is re-counted as cap-blocked.
 *
 * The leg the cap actually refused is in the journal: DecisionJournal.risksJson
 * carries `BANKROLL_200: v45 market-slug cap (<token> would be 16/15)`. That is
 * the population this module reads. Pricing those legs is the only measurement of
 * the rail that is not a counterfactual about legs the rail already admitted.
 */

/** One blocked leg's cause, parsed from a journal `risksJson` blob. */
export type SlugCapBlock = {
  /** raw event-slug token the cap counted ('highest', 'dota2', …) */
  token: string;
  /** what the open count would have become had the leg opened */
  wouldBe: number;
  /** the cap in force at decision time (rules.maxMarketSlugPositions) */
  cap: number;
};

// Anchored on the exact string scripts/score-trades.ts writes (line ~781). A
// looser pattern would also match prose about the cap in a card note.
const BLOCK_RE = /v45 market-slug cap \(([^ ]+) would be (\d+)\/(\d+)\)/g;

/** Every slug-cap block recorded on one decision row (usually 0 or 1). */
export function parseSlugCapBlocks(risksJson: string | null | undefined): SlugCapBlock[] {
  if (!risksJson) return [];
  const out: SlugCapBlock[] = [];
  BLOCK_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = BLOCK_RE.exec(risksJson)) !== null) {
    const wouldBe = Number(m[2]);
    const cap = Number(m[3]);
    if (!Number.isFinite(wouldBe) || !Number.isFinite(cap)) continue;
    out.push({ token: m[1], wouldBe, cap });
  }
  return out;
}

export function isSlugCapBlock(risksJson: string | null | undefined): boolean {
  return parseSlugCapBlocks(risksJson).length > 0;
}

/**
 * PnL of the refused leg per $1 staked, had it been copied at `entryPrice` and
 * held to settlement: a winning token pays $1/share, so $1 buys 1/p shares and
 * returns (1-p)/p; a loser returns -$1. No fee and no slippage — both are stated
 * as zero in the caller's basis line rather than silently priced.
 *
 * @returns null when the entry price cannot describe a stake (p<=0 or p>1).
 */
export function perDollarReturn(entryPrice: number | null | undefined, won: boolean): number | null {
  if (typeof entryPrice !== "number" || !Number.isFinite(entryPrice)) return null;
  if (entryPrice <= 0 || entryPrice > 1) return null;
  return won ? (1 - entryPrice) / entryPrice : -1;
}

export type ReturnSummary = {
  n: number;
  /** sum of per-$1 returns (i.e. PnL per $1 staked on every leg) */
  sum: number;
  mean: number;
  median: number;
  /** mean after dropping floor(n*trim) from each tail — concentration check */
  trimmedMean: number;
  winRate: number;
  /** the single worst leg's per-$1 return (magnitude), for concentration */
  worstLeg: number;
  /** `sum` with the 10 LARGEST positive legs removed — the ex-top-10 concentration check */
  exTop10Sum: number;
};

function median(sorted: number[]): number {
  if (sorted.length === 0) return 0;
  const mid = sorted.length >> 1;
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

/** Summary of per-$1 returns, with the trim and the ex-top-10 that keep one leg
 *  from speaking for the population. `trim` is a fraction of each tail. */
export function summarizeReturns(returns: number[], trim = 0.05): ReturnSummary {
  const xs = returns.filter((v) => Number.isFinite(v)).sort((a, b) => a - b);
  const n = xs.length;
  if (n === 0) {
    return { n: 0, sum: 0, mean: 0, median: 0, trimmedMean: 0, winRate: 0, worstLeg: 0, exTop10Sum: 0 };
  }
  const sum = xs.reduce((a, v) => a + v, 0);
  const k = Math.floor(n * trim);
  const core = k > 0 && n - 2 * k > 0 ? xs.slice(k, n - k) : xs;
  return {
    n,
    sum,
    mean: sum / n,
    median: median(xs),
    trimmedMean: core.reduce((a, v) => a + v, 0) / core.length,
    winRate: xs.filter((v) => v > 0).length / n,
    worstLeg: xs[0] < 0 ? -xs[0] : 0,
    exTop10Sum: xs.slice(0, Math.max(0, n - 10)).reduce((a, v) => a + v, 0),
  };
}
