/**
 * READ-ONLY: print the sentiment layer's calibrated edge per research category.
 *
 * Calls the production aggregation exactly as scripts/score-trades.ts does
 * (aggregateSentimentForCategory(cat, yesPrice) with the module defaults:
 * 7-day window, opinionatedThreshold 0.3, then gated by rules.sentimentMinSignals),
 * so a before/after comparison around any RegulatorySignal insert measures the
 * thing that actually reaches copyScore — not a reimplementation of it.
 *
 * BASIS (2026-11-15, card `insidercat-source-audit`): n and rows7d are ROW
 * counts. A row is written every time a poller re-reads a document it has
 * already seen, so a row count is not an evidence count. This script prints the
 * distinct-disclosure count beside every row count, and flags any category whose
 * opinionated set carries a single polarity value — a set that cannot express a
 * direction, whatever its n. The full three-arm reading lives in
 * `npx tsx scripts/research-source-supply-read.ts`.
 *
 * Usage: npx tsx scripts/sentiment-edge-read.ts [price ...]
 */
import { prisma } from "../src/lib/db";
import { aggregateSentimentForCategory } from "../src/lib/forecasting/sentiment";
import { getActiveRules } from "../src/lib/rules";
import { dedupeByEvent, polarityConcentration, type SupplyRow } from "../src/lib/research-source-supply";

const CATEGORIES = [
  "Crypto",
  "Tech/AI",
  "Defense/Geopolitics",
  "Healthcare",
  "Energy/Climate",
  "Finance",
  "Macro/Politics",
];

const WINDOW_MS = 7 * 86_400_000;

async function main() {
  const prices = process.argv.slice(2).map(Number).filter((n) => Number.isFinite(n) && n > 0 && n < 1);
  const pp = prices.length ? prices : [0.5];
  const { rules, version } = await getActiveRules();
  const minSignals = rules.sentimentMinSignals;
  const scale = rules.sentimentScale;
  const since = new Date(Date.now() - WINDOW_MS);
  const opinionatedWhere = {
    processedAt: { gte: since },
    OR: [{ sentimentScore: { gte: 0.3 } }, { sentimentScore: { lte: -0.3 } }],
  };

  const total = await prisma.regulatorySignal.count();
  const totalDistinct = dedupeByEvent(
    (await prisma.regulatorySignal.findMany({
      select: { source: true, sentimentScore: true, confidence: true, processedAt: true, rawPayload: true },
    })) as SupplyRow[]
  ).length;
  const opRows = (await prisma.regulatorySignal.findMany({
    where: opinionatedWhere,
    select: { source: true, sentimentScore: true, confidence: true, processedAt: true, rawPayload: true },
  })) as SupplyRow[];
  const opDistinct = dedupeByEvent(opRows).length;

  console.log(
    `active RuleSet v${version} · sentimentEvidenceEnabled=${rules.sentimentEvidenceEnabled} ` +
      `· sentimentScale=${scale} · sentimentMinSignals=${minSignals}`
  );
  console.log(
    `RegulatorySignal rows=${total} (distinct disclosures ${totalDistinct}) · ` +
      `opinionated in 7d window: rows=${opRows.length}, distinct disclosures=${opDistinct}`
  );
  console.log(`"opinionated" = |sentimentScore| >= 0.3 (module default opinionatedThreshold).`);
  console.log(`A row count is not an evidence count: pollers re-emit documents they have already seen.\n`);

  for (const cat of CATEGORIES) {
    const all = await prisma.regulatorySignal.count({
      where: { marketCategory: cat, processedAt: { gte: since } },
    });
    const catRows = (await prisma.regulatorySignal.findMany({
      where: { marketCategory: cat, ...opinionatedWhere },
      select: { source: true, sentimentScore: true, confidence: true, processedAt: true, rawPayload: true },
    })) as SupplyRow[];
    const conc = polarityConcentration(catRows);
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
    const constancy =
      catRows.length === 0
        ? "no opinionated rows"
        : conc.distinctValues === 1
          ? `SINGLE POLARITY ${conc.modal.toFixed(2)} (${(conc.modalShare * 100).toFixed(1)}% of ${catRows.length} rows, ${dedupeByEvent(catRows).length} distinct disclosures) — cannot express a direction`
          : `${conc.distinctValues} polarity values, modal ${conc.modal.toFixed(2)} at ${(conc.modalShare * 100).toFixed(1)}%`;
    console.log(`[${cat}] rows7d=${all} · ${constancy}`);
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
