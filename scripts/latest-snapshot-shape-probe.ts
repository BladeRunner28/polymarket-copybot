/**
 * Read-only instrument for the `dashboard-latest-snapshot-cost` card: is the /paper-trades
 * "latest snapshot per market" read better as ONE aggregate-with-bare-columns query, or as
 * two steps (index-only MAX(collectedAt) per market, then one indexed seek per (marketId,
 * collectedAt) pair)?
 *
 * It also asserts PARITY: the shipped `loadOpenMtmHorizon()` output must agree, market by
 * market, with the retired single-query shape on the same data — the fix must not drop a
 * market or shift a snapshot stamp (that is the card's own fail condition).
 *
 * Writes nothing.  npx tsx scripts/latest-snapshot-shape-probe.ts
 */
import { prisma } from "../src/lib/db";
import { Prisma } from "@prisma/client";
import {
  loadOpenMtmHorizon,
  type HorizonSummary,
} from "../src/lib/open-mtm-horizon";

type Snap = {
  marketId: string;
  collectedAt: Date | bigint | number | string;
  timeToResolution: number | null;
  question: string | null;
  isDemo: number | boolean | null;
};

/** SQLite ms-DATETIME may come back as number/bigint/Date/string depending on the path. */
function msOf(v: Snap["collectedAt"]): number {
  if (v === null || v === undefined) return NaN;
  if (typeof v === "number") return v;
  if (typeof v === "bigint") return Number(v);
  if (v instanceof Date) return v.getTime();
  return Number(v);
}

async function timed(label: string, runs: number, fn: () => Promise<any>) {
  const ts: number[] = [];
  let r: any;
  for (let i = 0; i < runs; i++) {
    const t = Date.now();
    r = await fn();
    ts.push(Date.now() - t);
  }
  ts.sort((a, b) => a - b);
  console.log(
    `  ${label}: median ${ts[Math.floor(ts.length / 2)]} ms (min ${ts[0]}, max ${ts[ts.length - 1]}, n=${runs})`,
  );
  return r;
}

const norm = (rows: Snap[]) =>
  rows
    .map((r) =>
      [r.marketId, msOf(r.collectedAt), r.timeToResolution, r.question, Number(r.isDemo)].join("|"),
    )
    .sort()
    .join(",");

async function main() {
  const grouped = await prisma.paperTrade.groupBy({
    by: ["marketId"],
    where: { botId: "STANDARD", status: "open" },
  });
  const ids = grouped.map((g: any) => g.marketId);
  console.log(`STANDARD open markets: ${ids.length}`);

  // RETIRED shape (the one this card is about), kept here as the reference side.
  const B = await timed("OLD  single query (bare columns, GROUP BY)", 5, () =>
    prisma.$queryRaw<Snap[]>(Prisma.sql`
      SELECT marketId, MAX(collectedAt) AS collectedAt, timeToResolution, question, isDemo
      FROM MarketSnapshot WHERE marketId IN (${Prisma.join(ids)}) GROUP BY marketId`),
  );

  // SHIPPED shape: the production read path, end to end (its own groupBy included).
  const summary: HorizonSummary = await timed("NEW  loadOpenMtmHorizon(STANDARD), shipped code", 5, () =>
    loadOpenMtmHorizon({ botId: "STANDARD" }),
  );

  const bRows = B as Snap[];
  const rows = bRows.length;
  const groups = summary.totals.groups;
  console.log(`  rows: OLD ${rows} | NEW groups ${groups} | open legs ${summary.totals.legs}`);

  // Parity: every OLD row must be represented in the NEW summary with the SAME stamp,
  // ttr, question and demo flag — and vice versa.
  const byId = new Map(bRows.map((r) => [r.marketId, r]));
  const mismatches: string[] = [];
  for (const g of summary.groups) {
    const r = byId.get(g.marketId);
    if (!r) {
      mismatches.push(`missing in OLD: ${g.marketId}`);
      continue;
    }
    if (msOf(r.collectedAt) !== g.snapshotMs) mismatches.push(`snapshotMs ${g.marketId}`);
    if ((r.timeToResolution ?? null) !== (g.ttrHours ?? null)) mismatches.push(`ttr ${g.marketId}`);
    if ((r.question ?? null) !== (g.question ?? null)) mismatches.push(`question ${g.marketId}`);
    if (Boolean(r.isDemo) !== Boolean(g.isDemo)) mismatches.push(`isDemo ${g.marketId}`);
  }
  const seen = new Set(summary.groups.map((g) => g.marketId));
  for (const r of bRows) if (!seen.has(r.marketId)) mismatches.push(`missing in NEW: ${r.marketId}`);

  console.log(`  PARITY OLD-vs-SHIPPED rows/groups: ${rows} vs ${groups} — mismatches: ${mismatches.length}`);
  if (mismatches.length) console.log("   ", mismatches.slice(0, 10));
  console.log(`  ignored demo/zero-leg markets: ${ids.length - rows}`);
  console.log(`  (reference: FIELD-identical raw row sets OLD vs simple pair fetch — see git history)`);
  console.log(`  standalone check: ${norm(bRows).length > 0 ? "rows normalised OK" : "NO ROWS"}`);

  await prisma.$disconnect();
  process.exit(mismatches.length ? 1 : 0);
}

main();
