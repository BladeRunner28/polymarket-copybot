/**
 * market-hygiene-rank-read — the PRE-REGISTERED read for card
 * `polyterm-p3-hygiene-preregistered-read` (audit §P3, drafts/polyterm-audit-2026-09-28.md:179).
 *
 * QUESTION. `src/lib/market-hygiene.ts` grades markets (wash indicators + 6-factor risk grade),
 * advisory-only, read by no live path. The audit fixed the promotion test in advance: does the
 * hygiene score RANK the subsequent realized copy outcome, with the same sign inside each
 * ruleSetVersion era, on the same rows? Kill rule: fewer than ~150 settled rows per arm is
 * "too few decisions to price the gate", not a verdict. This script is that read. Read-only.
 *
 * BASIS (stated, never implied):
 *   population = settled non-demo PaperTrade legs (status closed|resolved, realizedPnl not null)
 *                joined to DecisionJournal for the ruleSetVersion era (eraOf, src/lib/training-export.ts);
 *   level      = the leg (the bootstrap clusters on MARKET, because legs in one market are not independent);
 *   clock      = the as-of MarketSnapshot at or before the leg's openedAt (<= 12h stale) — NEVER a
 *                value fetched today, so volume/liquidity/spread are what the bot could have seen;
 *   outcome    = realizedPnl / simulatedPositionSize, i.e. per $1 staked, on that leg.
 *
 * TWO INPUT-BASIS LIMITS, printed on every run rather than papered over:
 *   1. `volume24hr` has no history in this repo (rawMarketJson is '{}'); it is RECONSTRUCTED as our
 *      own cumulative-volume delta over the widest snapshot window inside [open-36h, open], scaled
 *      to 24h. Windows shorter than 6h are rejected as too noisy.
 *   2. a MISSING input is not an observed zero. The ported volume factor used to print "no recent
 *      volume" (40) for an unmeasured market; that defect was repaired in src/lib/market-hygiene.ts
 *      in this same run (8,067 of 12,685 legs had no reconstructable volume24hr). The read still
 *      drops any factor whose input is absent and renormalises the weights, and prints the ported
 *      score beside it so the two can never silently diverge.
 *
 * PRE-REGISTERED VERDICT RULE: see src/lib/hygiene-rank.ts header (fixed before the first run).
 * This script decides nothing and wires into nothing: a PASS is still not a promotion.
 *
 * Run: npx tsx scripts/market-hygiene-rank-read.ts
 */
import { writeFileSync } from "fs";
import { join, resolve } from "path";
import { prisma } from "../src/lib/db";
import { marketRiskGrade, washTradeProfile, type HygieneMarketInput } from "../src/lib/market-hygiene";
import { eraOf } from "../src/lib/training-export";
import {
  ERA_ORDER,
  MIN_ARM_ROWS,
  preRegisteredVerdict,
  priceBandOf,
  readEra,
  spearman,
  returnSummary,
  type HygieneRankLeg,
} from "../src/lib/hygiene-rank";

// The 2026-11-09 first run is the pre-registered artefact; a re-run must not overwrite it in
// place, or the record of what was read before the rule had seen any data disappears.
const OUT = process.env.HYGIENE_RANK_OUT
  ? resolve(process.env.HYGIENE_RANK_OUT)
  : join(__dirname, "..", "data", "market-hygiene-rank.json");
const ASOF_WINDOW_MS = 12 * 3600 * 1000;
const VOL_LOOKBACK_MS = 36 * 3600 * 1000;
const VOL_MIN_WINDOW_MS = 6 * 3600 * 1000;

const pct = (n: number) => `${(100 * n).toFixed(1)}%`;
const f3 = (n: number | null) => (n === null || !Number.isFinite(n) ? "n/a" : n.toFixed(3));
const usd = (n: number) => `${n >= 0 ? "+" : "-"}$${Math.abs(n).toFixed(2)}`;

type LegRow = {
  legId: string;
  marketId: string;
  openedAt: number;
  entryPrice: number;
  size: number;
  realizedPnl: number;
  status: string;
  ruleSetVersion: number | null;
  snapAt: number;
  liquidity: number | null;
  volume: number | null;
  spread: number | null;
  ttr: number | null;
  question: string | null;
  category: string | null;
};

type VolRow = { legId: string; priorVolume: number; priorAt: number };

/**
 * Factor weights whose input is actually present. The ported grade maps a missing input to a
 * concrete sub-score (volume -> "no recent volume" 40; end date -> 50), which would let an
 * unmeasured market wear a measured label. Here a missing input drops the factor instead.
 */
function renormalisedRisk(input: HygieneMarketInput, now: Date) {
  const grade = marketRiskGrade(input, now);
  const present: Record<string, boolean> = {
    resolution_clarity: true,
    liquidity: input.liquidity !== undefined && input.liquidity !== null,
    time_risk: !!input.endDate && !isNaN(input.endDate.getTime()),
    volume_quality: input.volume24hr !== undefined && input.liquidity !== undefined,
    spread: input.spread !== undefined && input.spread !== null,
    category_risk: true,
  };
  const used = grade.factors.filter((f) => present[f.key]);
  const w = used.reduce((a, f) => a + f.weight, 0);
  const score = w > 0 ? Math.round(used.reduce((a, f) => a + f.score * f.weight, 0) / w) : grade.score;
  const omitted = [
    ...new Set([
      ...grade.omitted,
      ...grade.factors.filter((f) => !present[f.key]).map((f) => f.key),
    ]),
  ];
  return { asIs: grade.score, grade: grade.grade, score, omitted };
}

async function main() {
  const legs = await prisma.$queryRawUnsafe<LegRow[]>(
    `
    SELECT pt.id AS legId, pt.marketId AS marketId, pt.openedAt AS openedAt, pt.entryPrice AS entryPrice,
           pt.simulatedPositionSize AS size, pt.realizedPnl AS realizedPnl, pt.status AS status,
           dj.ruleSetVersion AS ruleSetVersion,
           s.collectedAt AS snapAt, s.liquidity AS liquidity, s.volume AS volume,
           s.spread AS spread, s.timeToResolution AS ttr, s.question AS question, s.category AS category
    FROM PaperTrade pt
    JOIN DecisionJournal dj ON dj.id = pt.decisionJournalId
    JOIN MarketSnapshot s ON s.id = (
      SELECT s0.id FROM MarketSnapshot s0
      WHERE s0.marketId = pt.marketId
        AND s0.collectedAt <= pt.openedAt AND s0.collectedAt >= pt.openedAt - ${ASOF_WINDOW_MS}
        AND s0.liquidity IS NOT NULL
      ORDER BY s0.collectedAt DESC LIMIT 1)
    WHERE pt.isDemo = 0 AND pt.status IN ('closed','resolved') AND pt.realizedPnl IS NOT NULL
    `,
  );

  const volRows = await prisma.$queryRawUnsafe<VolRow[]>(
    `
    SELECT pt.id AS legId, s.volume AS priorVolume, s.collectedAt AS priorAt
    FROM PaperTrade pt
    JOIN MarketSnapshot s ON s.id = (
      SELECT s0.id FROM MarketSnapshot s0
      WHERE s0.marketId = pt.marketId
        AND s0.collectedAt >= pt.openedAt - ${VOL_LOOKBACK_MS} AND s0.collectedAt <= pt.openedAt
        AND s0.volume IS NOT NULL
      ORDER BY s0.collectedAt ASC LIMIT 1)
    WHERE pt.isDemo = 0 AND pt.status IN ('closed','resolved') AND pt.realizedPnl IS NOT NULL
    `,
  );
  const volByLeg = new Map(volRows.map((r) => [r.legId, r]));

  const scored: HygieneRankLeg[] = [];
  const asIsScores: number[] = [];
  const asIsReturns: number[] = [];
  let volEstimated = 0;
  let volMissing = 0;
  let omittedVolume = 0;

  for (const row of legs) {
    const snapAt = new Date(Number(row.snapAt));
    const openedAt = Number(row.openedAt);
    const endDate = row.ttr !== null && row.ttr !== undefined ? new Date(Number(snapAt) + Number(row.ttr) * 3600e3) : null;

    let volume24hr: number | undefined;
    const prior = volByLeg.get(row.legId);
    if (prior && row.volume !== null && Number(row.volume) >= Number(prior.priorVolume)) {
      const hours = (Number(row.snapAt) - Number(prior.priorAt)) / 3600e3;
      if (hours * 3600e3 >= VOL_MIN_WINDOW_MS) {
        volume24hr = ((Number(row.volume) - Number(prior.priorVolume)) / hours) * 24;
        volEstimated += 1;
      }
    }
    if (volume24hr === undefined) volMissing += 1;

    const input: HygieneMarketInput = {
      slug: row.marketId,
      question: row.question ?? undefined,
      categoryForRisk: row.category ?? undefined,
      endDate,
      volume24hr,
      liquidity: row.liquidity !== null ? Number(row.liquidity) : undefined,
      spread: row.spread !== null ? Number(row.spread) : undefined,
      closed: false,
    };
    const risk = renormalisedRisk(input, snapAt);
    const wash = washTradeProfile(input);
    if (risk.omitted.includes("volume_quality")) omittedVolume += 1;
    asIsScores.push(risk.asIs);
    asIsReturns.push(Number(row.realizedPnl) / Number(row.size));
    scored.push({
      legId: row.legId,
      marketId: row.marketId,
      era: eraOf(row.ruleSetVersion),
      ruleSetVersion: row.ruleSetVersion === null ? null : Number(row.ruleSetVersion),
      snapAtMs: Number(row.snapAt),
      riskScore: risk.score,
      riskGrade: risk.grade,
      washScore: wash.score,
      washAssessed: wash.assessed,
      entryPrice: Number(row.entryPrice),
      returned: Number(row.realizedPnl) / Number(row.size),
      settlement: row.status === "resolved",
    });
  }

  const order = [...ERA_ORDER];
  const unknownEra = scored.filter((l) => !ERA_ORDER.includes(l.era as (typeof ERA_ORDER)[number]));
  const eras = [...order, ...(unknownEra.length ? ["unknown"] : [])].map((e) => readEra(e, scored));
  const verdict = preRegisteredVerdict(eras, scored);

  // Sensitivity: the PORTED score, which maps a missing volume input to "no recent volume" (40).
  // Printed so the renormalisation can never hide a result that only exists because of it.
  const asIsRho = spearman(asIsScores, asIsReturns);

  console.log("market-hygiene PRE-REGISTERED rank read (read-only)");
  console.log(`clock: legs opened through ${new Date(Math.max(...scored.map((l) => l.snapAtMs))).toISOString()}; as-of snapshot <= open, <= ${ASOF_WINDOW_MS / 3600e3}h stale`);
  console.log(`population: ${scored.length} settled non-demo legs over ${new Set(scored.map((l) => l.marketId)).size} markets`);
  console.log("");
  console.log(`input basis: volume24hr reconstructed on ${volEstimated}/${scored.length} legs (${pct(volEstimated / scored.length)}), missing on ${volMissing}; volume_quality factor omitted (weights renormalised) on ${omittedVolume}`);
  console.log("");
  console.log("ERA            legs   mkts  settle  mean/$1   median   win    riskSpearman  95% CI(market-clustered)  washSpearman");
  for (const e of eras) {
    const ci = e.riskCi;
    console.log(
      `${e.era.padEnd(16)} ${String(e.nLegs).padStart(5)}  ${String(e.nMarkets).padStart(5)}  ${String(e.nSettlementLegs).padStart(6)}  ` +
        `${usd(e.returns.mean).padStart(8)}  ${usd(e.returns.median).padStart(8)}  ${pct(e.returns.winRate).padStart(5)}  ` +
        `${f3(e.riskSpearman).padStart(12)}  ${(ci ? `[${f3(ci.lo)}, ${f3(ci.hi)}]` : "n/a").padStart(24)}  ${f3(e.washSpearman)}`,
    );
  }
  console.log("");
  console.log(`pooled riskSpearman ${f3(verdict.pooledRiskSpearman)} CI ${verdict.pooledCi ? `[${f3(verdict.pooledCi.lo)}, ${f3(verdict.pooledCi.hi)}]` : "n/a"} (cluster=market, ${verdict.pooledCi?.iters ?? 0} iters)`);
  console.log(`sensitivity: ported as-is risk score rho ${f3(asIsRho)} (differs from the primary only where liquidity/spread/end-date are absent)`);
  console.log(`VERDICT: ${verdict.verdict}`);
  for (const r of verdict.reasons) console.log(`  - ${r}`);
  console.log("");
  console.log("risk-grade bands (renormalised score; higher = riskier):");
  for (const e of eras) {
    if (e.nLegs === 0) continue;
    const line = e.byGrade.filter((g) => g.n > 0).map((g) => `${g.grade}: n=${g.n} mean ${usd(g.returns.mean)} median ${usd(g.returns.median)} exTop10 ${usd(g.returns.exTop10)}`).join(" | ");
    console.log(`  ${e.era}: ${line}`);
  }
  console.log("");
  console.log("price-band control (does the rank survive inside the entry-price band?):");
  for (const e of eras) {
    if (e.nLegs === 0) continue;
    console.log(`  ${e.era}: ${e.byPriceBand.map((b) => `${b.band} n=${b.n} rho=${f3(b.riskSpearman)}`).join(" | ")}`);
  }
  console.log("");
  console.log("concentration (audit discipline: a big number is a reason to verify):");
  for (const e of eras) {
    if (e.nLegs === 0) continue;
    console.log(`  ${e.era}: mean ${usd(e.returns.mean)} trimmed(10%) ${usd(e.returns.trimmedMean)} exTop10 ${usd(e.returns.exTop10)} sum ${usd(e.returns.sum)}`);
  }

  console.log("");
  console.log("settlement-only sensitivity (early exits are OUR policy; a market-quality rank should show on natural resolutions too):");
  const settlementSensitivity: { era: string; n: number; rho: number | null; mean: number }[] = [];
  for (const e of eras) {
    const rows = scored.filter((l) => l.era === e.era && l.settlement);
    const rho = spearman(rows.map((l) => l.riskScore), rows.map((l) => l.returned));
    const mean = returnSummary(rows.map((l) => l.returned)).mean;
    settlementSensitivity.push({ era: e.era, n: rows.length, rho, mean });
    console.log(`  ${e.era}: n=${rows.length} rho=${f3(rho)} mean ${usd(mean)}`);
  }
  console.log("");
  const scores = scored.map((l) => l.riskScore);
  console.log(`risk-score spread: ${new Set(scores).size} distinct values, min ${Math.min(...scores)}, max ${Math.max(...scores)}`);
  const vc = new Map<number, number>();
  for (const row of legs) {
    const v = row.ruleSetVersion ?? -1;
    vc.set(v, (vc.get(v) ?? 0) + 1);
  }
  const versions = [...vc.entries()].sort((a, b) => a[0] - b[0]);
  const big = versions.filter(([, n]) => n >= MIN_ARM_ROWS);
  const versionCensus = {
    versions: versions.length,
    reachingFloor: big.length,
    medianLegsPerVersion: returnSummary(versions.map(([, n]) => n)).median,
    atFloor: big.map(([v, n]) => `${v}:${n}`),
  };
  console.log(
    `per-ruleSetVersion census: ${versions.length} versions, ${big.length} reach the ${MIN_ARM_ROWS}-row floor (median n=${versionCensus.medianLegsPerVersion}); the era grouping is eraOf() from src/lib/training-export.ts, not a per-version read${big.length ? `; at floor: ${versionCensus.atFloor.join(", ")}` : ""}`,
  );
  // The card's wording is "inside each ruleSetVersion era separately". The coarse eraOf() grouping
  // above is a convenience; this is the faithful per-version read on the versions that clear the
  // audit's 150-row floor. A per-version read across all 67 versions (median n=67) would be 67 coin
  // flips, not 67 measurements, so the floor is applied exactly as the audit wrote it.
  const perVersion = versions
    .filter(([, n]) => n >= MIN_ARM_ROWS)
    .map(([version, n]) => {
      const rows = scored.filter((l) => l.ruleSetVersion === version);
      return { version, n, rho: spearman(rows.map((l) => l.riskScore), rows.map((l) => l.returned)) };
    })
    .filter((r) => r.rho !== null);
  const negVersions = perVersion.filter((r) => (r.rho as number) < 0).length;
  console.log(
    `per-version read at floor: ${negVersions}/${perVersion.length} negative (${pct(negVersions / Math.max(1, perVersion.length))}); ${perVersion.map((r) => `v${r.version}:${f3(r.rho)}`).join(" ")}`,
  );
  const payload = {
    generatedAt: new Date().toISOString(),
    basis: {
      population: "settled non-demo PaperTrade legs joined to DecisionJournal for ruleSetVersion era",
      level: "leg; bootstrap clusters on market",
      clock: "as-of MarketSnapshot at or before openedAt (<=12h stale); outcome realizedPnl/size",
      outcome: "realizedPnl / simulatedPositionSize",
      volume24hr: `reconstructed from our own cumulative-volume delta, window >=6h inside [open-36h, open], scaled to 24h; ${volEstimated}/${scored.length} legs`,
      riskScore: "ported 6-factor grade, weights renormalised over factors whose input is present",
      minArmRows: MIN_ARM_ROWS,
    },
    verdict,
    eras,
    sensitivity: { portedAsIsSpearman: asIsRho, n: asIsScores.length, note: "ported formula reads a missing volume input as no recent volume (40)" },
    settlementSensitivity,
    versionCensus,
    perVersion,
    counts: { legs: scored.length, markets: new Set(scored.map((l) => l.marketId)).size, volEstimated, volMissing, omittedVolume },
  };
  writeFileSync(OUT, JSON.stringify(payload, null, 2) + "\n");
  console.log(`\nwrote ${OUT}`);
}

main()
  .catch((err) => {
    console.error(err);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
