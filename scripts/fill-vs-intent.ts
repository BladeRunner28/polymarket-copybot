/**
 * fill-vs-intent — READ-ONLY: the measured C-200 fill-vs-intent-price distribution
 * (roadmap card `c200-maker-fill-assumption`, option (b), 2026-09-25).
 *
 * The lane's booked entry IS the Rust sidecar's modelled maker fill
 * (`max(0.01, intent - 0.02)`). This script answers, from our own legs, what the
 * archive could only bound: how far below the price the lane was HANDED did the
 * booked fill actually land?
 *
 *   gap = PaperTrade.entryPrice - PaperTrade.intentPrice
 *     gap ~ -0.02  the sidecar's maker improvement, as modelled
 *     gap ~  0     the leg was booked at the price handed in (no improvement)
 *     gap >  0     booked WORSE than the intent — bug signature, not the model
 *
 * Populations: only legs whose intent was stored (this instrument shipped
 * 2026-09-25) can be measured; everything older is reported as `unmeasured` and
 * contributes no opinion. `FillIntent` rows that never linked to a leg are the
 * copies the sidecar never booked (gated, deduped, or a dropped webhook) and are
 * counted separately.
 *
 * Writes nothing. Prints the same lines src/lib/fill-intent.ts renders, plus the
 * reproduce SQL. Usage: npx tsx scripts/fill-vs-intent.ts [--days N] [--json]
 */
import { prisma } from "../src/lib/db";
import { loadFillVsIntent, renderFillVsIntent, MAKER_IMPROVEMENT } from "../src/lib/fill-intent";

const REPRODUCE_SQL = `
-- measured legs (intent stored), gap distribution
SELECT round((p.entryPrice - p.intentPrice) * 100, 2) AS gap_cents, COUNT(*) AS n
FROM PaperTrade p
WHERE p.isDemo = 0 AND p.botId = 'BANKROLL_200' AND p.intentPrice IS NOT NULL
GROUP BY 1 ORDER BY 1;
-- coverage: intents dispatched vs legs linked
SELECT (SELECT COUNT(*) FROM FillIntent) AS intents,
       (SELECT COUNT(*) FROM FillIntent WHERE paperTradeId IS NULL) AS unlinked,
       (SELECT COUNT(*) FROM PaperTrade WHERE botId='BANKROLL_200' AND intentPrice IS NOT NULL) AS stamped;
`.trim();

async function main() {
  const args = process.argv.slice(2);
  const json = args.includes("--json");
  const daysIdx = args.indexOf("--days");
  const days = daysIdx >= 0 ? Number(args[daysIdx + 1]) : 0;
  const sinceMs = days > 0 ? Date.now() - days * 86_400_000 : undefined;

  const { summary, unlinkedIntents, intents } = await loadFillVsIntent({ sinceMs });
  const windowLabel = days > 0 ? `last ${days}d` : "all legs";
  const lines = renderFillVsIntent(summary, windowLabel);

  if (json) {
    console.log(JSON.stringify({ window: windowLabel, summary, intents, unlinkedIntents }, null, 2));
  } else {
    for (const l of lines) console.log(l);
    console.log(
      `[fill-vs-intent] intents dispatched ${intents}, of which unlinked (no booked leg) ${unlinkedIntents} · ` +
        `assumed improvement $${MAKER_IMPROVEMENT.toFixed(2)}`
    );
    console.log("[fill-vs-intent] reproduce SQL:");
    console.log(REPRODUCE_SQL);
  }
}

main()
  .then(() => prisma.$disconnect())
  .catch(async (e) => {
    console.error(e);
    await prisma.$disconnect();
    process.exit(1);
  });
