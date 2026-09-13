import { prisma } from "../src/lib/db";
import { Prisma } from "@prisma/client";
import { computeBenchmarks } from "../src/lib/benchmarks";
import { hourlyPnlSeries, dailyPnlSeries } from "../src/lib/pnl-rollup";

async function t<T>(label: string, fn: () => Promise<T>): Promise<T> {
  const s = Date.now();
  const r = await fn();
  const ms = Date.now() - s;
  const size = Array.isArray(r) ? ` rows=${r.length}` : "";
  console.log(`${ms.toString().padStart(8)}ms  ${label}${size}`);
  return r;
}

async function main() {
  console.log("=== NEW: pnl series (rollup-backed) ===");
  await t("hourlyPnlSeries()", () => hourlyPnlSeries());
  await t("dailyPnlSeries()", () => dailyPnlSeries());

  console.log("\n=== NEW: computeBenchmarks (narrow select) ===");
  await t("computeBenchmarks()", () => computeBenchmarks());

  console.log("\n=== NEW: analytics decisionJournal (narrow select) ===");
  await t("decisionJournal narrow select, all rows", () =>
    prisma.decisionJournal.findMany({
      select: {
        decision: true,
        createdAt: true,
        observedTrade: { select: { outcome: true, detectedPrice: true } },
        paperTrades: { select: { realizedPnl: true } },
        outcomeReviews: { select: { finalOutcome: true } },
      },
      orderBy: { createdAt: "asc" },
    })
  );

  console.log("\n=== NEW: signals latest-snapshot-per-market SQL ===");
  const decisions = await prisma.decisionJournal.findMany({ orderBy: { createdAt: "desc" }, take: 100, include: { observedTrade: true } });
  const marketIds = [...new Set(decisions.map((d) => d.marketId))];
  const snaps = await t(`latest snapshot per market (${marketIds.length} markets)`, () =>
    prisma.$queryRaw<Array<{ marketId: string }>>(Prisma.sql`
      SELECT marketId, MAX(collectedAt) AS collectedAt, spread, liquidity, timeToResolution
      FROM MarketSnapshot
      WHERE marketId IN (${Prisma.join(marketIds)})
      GROUP BY marketId
    `)
  );

  console.log("\n=== parity: SQL latest-snapshot vs old JS full-fetch logic ===");
  const oldRows = await prisma.marketSnapshot.findMany({ where: { marketId: { in: marketIds } }, orderBy: { collectedAt: "desc" } });
  const oldLatest = new Map<string, (typeof oldRows)[number]>();
  for (const s of oldRows) if (!oldLatest.has(s.marketId)) oldLatest.set(s.marketId, s);
  let diffs = 0;
  for (const s of snaps as unknown as Array<{ marketId: string; spread: number | null; liquidity: number | null; timeToResolution: number | null }>) {
    const o = oldLatest.get(s.marketId);
    if (!o) {
      diffs++;
      console.log(`  MISSING in new: ${s.marketId}`);
      continue;
    }
    if (o.spread !== s.spread || o.liquidity !== s.liquidity || o.timeToResolution !== s.timeToResolution) {
      diffs++;
      console.log(`  DIFF ${s.marketId}: old(spread=${o.spread},liq=${o.liquidity},ttr=${o.timeToResolution}) new(spread=${s.spread},liq=${s.liquidity},ttr=${s.timeToResolution})`);
    }
  }
  console.log(`  markets=${marketIds.length} new=${snaps.length} old=${oldLatest.size} field_diffs=${diffs} (old fetched ${oldRows.length} rows)`);

  await prisma.$disconnect();
}
main();
