/**
 * READ-ONLY: print the sentiment layer's calibrated edge per research category.
 *
 * Calls the production aggregation exactly as scripts/score-trades.ts does
 * (aggregateSentimentForCategory(cat, yesPrice) with the module defaults:
 * 7-day window, opinionatedThreshold 0.3, then gated by rules.sentimentMinSignals),
 * so a before/after comparison around any RegulatorySignal insert measures the
 * thing that actually reaches copyScore — not a reimplementation of it.
 *
 * Usage: npx tsx scripts/sentiment-edge-read.ts [price ...]
 */
import { prisma } from "../src/lib/db";
import { aggregateSentimentForCategory } from "../src/lib/forecasting/sentiment";
import { getActiveRules } from "../src/lib/rules";

const CATEGORIES = [
  "Crypto",
  "Tech/AI",
  "Defense/Geopolitics",
  "Healthcare",
  "Energy/Climate",
  "Finance",
  "Macro/Politics",
];

async function main() {
  const prices = process.argv.slice(2).map(Number).filter((n) => Number.isFinite(n) && n > 0 && n < 1);
  const pp = prices.length ? prices : [0.5];
  const { rules, version } = await getActiveRules();
  const minSignals = rules.sentimentMinSignals;
  const scale = rules.sentimentScale;

  const total = await prisma.regulatorySignal.count();
  const op = await prisma.regulatorySignal.count({
    where: {
      processedAt: { gte: new Date(Date.now() - 7 * 86_400_000) },
      OR: [{ sentimentScore: { gte: 0.3 } }, { sentimentScore: { lte: -0.3 } }],
    },
  });
  console.log(
    `active RuleSet v${version} · sentimentEvidenceEnabled=${rules.sentimentEvidenceEnabled} ` +
      `· sentimentScale=${scale} · sentimentMinSignals=${minSignals}`
  );
  console.log(`RegulatorySignal rows=${total} · opinionated in 7d window=${op}\n`);
  console.log(`"opinionated" = |sentimentScore| >= 0.3 (module default opinionatedThreshold)\n`);

  for (const cat of CATEGORIES) {
    const all = await prisma.regulatorySignal.count({
      where: { marketCategory: cat, processedAt: { gte: new Date(Date.now() - 7 * 86_400_000) } },
    });
    const cells: string[] = [];
    for (const p of pp) {
      const agg = await aggregateSentimentForCategory(cat, p);
      if (!agg) {
        cells.push(`p=${p.toFixed(2)} agg=null(<${minSignals} opinionated)`);
        continue;
      }
      const gated = agg.n >= minSignals;
      cells.push(
        `p=${p.toFixed(2)} n=${agg.n} prior=${agg.prior.toFixed(4)} post=${agg.pAware.toFixed(4)} ` +
          `delta=${agg.delta.toFixed(5)} pts=${(agg.delta * scale).toFixed(3)} ${gated ? "" : "(BELOW minSignals)"}`
      );
    }
    console.log(`[${cat}] rows7d=${all}`);
    for (const c of cells) console.log(`   ${c}`);
  }
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
