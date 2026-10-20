/**
 * backfill-market-category — fill ObservedTrade.marketCategoryClass / marketCategoryFine for the
 * ~335k rows written before the taxonomy existed (~2026-W38 and earlier).
 *
 * WHY: the two columns were added around 2026-W39 and never backfilled. Any query that joins on
 * them silently drops ~90% of history — which is exactly the bug that made a category analysis
 * report 96.4% "uncategorised" when true coverage was 99.4%. Backfilling makes the NEW taxonomy
 * authoritative for all history, so ML feature exports and cohort reports agree.
 *
 * SAFETY, in order:
 *   1. PARITY GATE (this must pass before anything is written). 2.9M rows already carry a stored
 *      class. We run the classifier over a sample of them and refuse to write if agreement is
 *      below --min-parity. The classifier is a parity-checked port, but a port that has drifted is
 *      worse than no backfill, so this is measured, not assumed.
 *   2. UNDO RECORD. Every backfilled marketId is written to a file BEFORE the update, so the
 *      change is reversible on a 10GB DB where a full backup is not free. Reversal is
 *      `--revert <file>`.
 *   3. CLASSIFY ONCE PER MARKET. The classifier keys on marketId + question, both per-market, so
 *      we classify distinct markets rather than 335k rows.
 *
 * Run:
 *   DATABASE_URL="file:./dev.db" npx tsx scripts/backfill-market-category.ts            # parity check only
 *   DATABASE_URL="file:./dev.db" npx tsx scripts/backfill-market-category.ts --apply
 *   DATABASE_URL="file:./dev.db" npx tsx scripts/backfill-market-category.ts --revert <undo.json>
 */
import { prisma } from "../src/lib/db";
import { classifyMarketCategory } from "../src/lib/market-category";
import { log } from "../src/lib/redact";
import { writeFileSync } from "node:fs";

const has = (f: string) => process.argv.includes(`--${f}`);
const val = (f: string, d?: string) => {
  const i = process.argv.indexOf(`--${f}`);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : d;
};

const SAMPLE = Number(val("sample", "40000"));
const MIN_PARITY = Number(val("min-parity", "0.98"));

type Cls = { coarse: string; fine: string };

async function parityCheck(): Promise<{ agree: number; total: number; worst: Array<[string, string, number]> }> {
  // sample rows that ALREADY have a stored class — that is our ground truth
  const rows = await prisma.$queryRawUnsafe<Array<{ marketId: string; marketQuestion: string | null; c: string; f: string }>>(
    `SELECT marketId, marketQuestion, marketCategoryClass AS c, marketCategoryFine AS f
       FROM ObservedTrade
      WHERE marketCategoryClass IS NOT NULL AND marketCategoryClass <> ''
      ORDER BY RANDOM() LIMIT ${SAMPLE}`
  );
  let agree = 0;
  const disagree = new Map<string, number>();
  for (const r of rows) {
    const got = classifyMarketCategory(r.marketId, r.marketQuestion ?? null);
    if (got.coarse === r.c && got.fine === r.f) agree++;
    else {
      const k = `${r.c}/${r.f} -> ${got.coarse}/${got.fine}`;
      disagree.set(k, (disagree.get(k) ?? 0) + 1);
    }
  }
  const worst = [...disagree.entries()]
    .map(([k, n]) => [k.split(" -> ")[0], k.split(" -> ")[1], n] as [string, string, number])
    .sort((a, b) => b[2] - a[2])
    .slice(0, 10);
  return { agree, total: rows.length, worst };
}

async function main() {
  const revertFile = val("revert");
  if (revertFile) {
    const ids: string[] = JSON.parse(require("node:fs").readFileSync(revertFile, "utf8"));
    log(`REVERT: nulling ${ids.length.toLocaleString()} marketIds recorded in ${revertFile}`);
    let done = 0;
    for (let i = 0; i < ids.length; i += 500) {
      const chunk = ids.slice(i, i + 500);
      const ph = chunk.map(() => "?").join(",");
      const r = await prisma.$executeRawUnsafe(
        `UPDATE ObservedTrade SET marketCategoryClass = NULL, marketCategoryFine = NULL WHERE marketId IN (${ph})`,
        ...chunk
      );
      done += r;
    }
    log(`REVERT complete — ${done.toLocaleString()} rows restored to NULL.`);
    return;
  }

  log("=== 1. PARITY GATE ===");
  const p = await parityCheck();
  const rate = p.agree / p.total;
  log(`sampled ${p.total.toLocaleString()} rows that already carry a stored class`);
  log(`classifier agreement: ${p.agree.toLocaleString()}/${p.total.toLocaleString()} = ${(rate * 100).toFixed(3)}%`);
  if (p.worst.length) {
    log("top disagreements (stored -> classifier):");
    for (const [a, b, n] of p.worst) log(`   ${a.padEnd(22)} -> ${b.padEnd(22)} ${n}`);
  }
  if (rate < MIN_PARITY) {
    log(`REFUSING TO WRITE: agreement ${(rate * 100).toFixed(3)}% is below --min-parity ${(MIN_PARITY * 100).toFixed(1)}%`);
    process.exitCode = 2;
    return;
  }
  log(`PASS (>= ${(MIN_PARITY * 100).toFixed(1)}%)`);

  const pending = await prisma.$queryRawUnsafe<Array<{ n: number }>>(
    `SELECT COUNT(DISTINCT marketId) AS n FROM ObservedTrade WHERE marketCategoryClass IS NULL OR marketCategoryClass = ''`
  );
  const rowCount = await prisma.$queryRawUnsafe<Array<{ n: number }>>(
    `SELECT COUNT(*) AS n FROM ObservedTrade WHERE marketCategoryClass IS NULL OR marketCategoryClass = ''`
  );
  log("");
  log(`=== 2. SCOPE ===`);
  log(`rows to backfill      : ${Number(rowCount[0].n).toLocaleString()}`);
  log(`distinct markets      : ${Number(pending[0].n).toLocaleString()}`);

  if (!has("apply")) {
    log("");
    log("DRY RUN — nothing written. Re-run with --apply to backfill.");
    return;
  }

  log("");
  log("=== 3. APPLY ===");
  const markets = await prisma.$queryRawUnsafe<Array<{ marketId: string; marketQuestion: string | null }>>(
    `SELECT marketId, MAX(marketQuestion) AS marketQuestion
       FROM ObservedTrade
      WHERE marketCategoryClass IS NULL OR marketCategoryClass = ''
      GROUP BY marketId`
  );
  log(`classifying ${markets.length.toLocaleString()} distinct markets...`);

  const classified: Array<{ marketId: string; coarse: string; fine: string }> = [];
  for (const m of markets) {
    const c: Cls = classifyMarketCategory(m.marketId, m.marketQuestion ?? null);
    classified.push({ marketId: m.marketId, coarse: c.coarse, fine: c.fine });
  }

  // undo record FIRST — reversibility before mutation
  const undoPath = `data/category-backfill-undo-${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
  writeFileSync(undoPath, JSON.stringify(classified.map((c) => c.marketId)));
  log(`undo record written: ${undoPath} (${classified.length.toLocaleString()} marketIds)`);

  const BATCH = 400;
  let written = 0;
  for (let i = 0; i < classified.length; i += BATCH) {
    const chunk = classified.slice(i, i + BATCH);
    const cases = chunk.map(() => "(?,?,?)").join(",");
    const params = chunk.flatMap((c) => [c.marketId, c.coarse, c.fine]);
    written += await prisma.$executeRawUnsafe(
      `WITH v(marketId, coarse, fine) AS (VALUES ${cases})
       UPDATE ObservedTrade
          SET marketCategoryClass = (SELECT coarse FROM v WHERE v.marketId = ObservedTrade.marketId),
              marketCategoryFine  = (SELECT fine   FROM v WHERE v.marketId = ObservedTrade.marketId)
        WHERE (marketCategoryClass IS NULL OR marketCategoryClass = '')
          AND marketId IN (SELECT marketId FROM v)`,
      ...params
    );
    if (i % (BATCH * 20) === 0) log(`  ...${i.toLocaleString()}/${classified.length.toLocaleString()} markets, ${written.toLocaleString()} rows`);
  }
  log(`rows updated: ${written.toLocaleString()}`);

  const after = await prisma.$queryRawUnsafe<Array<{ n: number }>>(
    `SELECT COUNT(*) AS n FROM ObservedTrade WHERE marketCategoryClass IS NULL OR marketCategoryClass = ''`
  );
  log(`remaining NULL after backfill: ${Number(after[0].n).toLocaleString()}`);
  log("");
  log(`Revert with: npx tsx scripts/backfill-market-category.ts --revert ${undoPath}`);
}

main()
  .catch((e) => {
    log("backfill-market-category FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
