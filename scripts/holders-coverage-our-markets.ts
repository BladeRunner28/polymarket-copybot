/**
 * holders-coverage-our-markets — card `polyterm-p5-holders-concentration`, VERIFY gate (a), applied
 * to the universe that actually matters: the markets OUR BOOK holds a leg in, not the top-volume
 * board the hygiene scorer ranks.
 *
 * The gate's exact words: "`/holders` returns a usable top-N share for the markets we actually trade
 * — if the endpoint is empty or capped for our universe, the metric is a null, not a signal, and
 * that null must be recorded".
 *
 * WHAT IT PRINTS, per market: outcome count, holders enumerated, the walk's page count, whether the
 * walk was truncated, the supply of each outcome, and top-1/top-5 shares. Then a coverage summary
 * and the supply identity check (complementary outcomes must carry the same total supply — a gap
 * means the enumeration is wrong, not that the market is odd).
 *
 * READ-ONLY. No writes, no gate input, nothing imported by a live path.
 *
 * Usage: npx tsx scripts/holders-coverage-our-markets.ts [--markets 40] [--min-legs 1]
 */
import { prisma } from "../src/lib/db";
import { holderConcentration } from "../src/lib/market-hygiene";
import { readOutcomeHolders } from "../src/lib/holders-read";
import { VENUE, asNumber, venueGetJson } from "../src/lib/venue-read";

const argOf = (name: string, dflt: number) => {
  const i = process.argv.indexOf(name);
  return i >= 0 ? Number(process.argv[i + 1]) : dflt;
};
const MARKETS = argOf("--markets", 40);
const MIN_LEGS = argOf("--min-legs", 1);

const pct = (n: number | undefined) => (n === undefined || !Number.isFinite(n) ? "n/a" : `${(100 * n).toFixed(1)}%`);

type GammaHit = { conditionId?: string; closed?: boolean; volume24hr?: number };

async function gammaBySlug(slug: string): Promise<GammaHit | null> {
  try {
    const data = await venueGetJson(`${VENUE.gamma}/markets?slug=${encodeURIComponent(slug)}`);
    const rows = Array.isArray(data) ? (data as Record<string, unknown>[]) : [];
    if (!rows.length) return null;
    const m = rows[0];
    return { conditionId: m.conditionId ? String(m.conditionId) : undefined, closed: Boolean(m.closed), volume24hr: asNumber(m.volume24hr) };
  } catch {
    return null;
  }
}

async function main(): Promise<number> {
  // PaperTrade.marketId is the SLUG (not the conditionId), so the slug -> conditionId hop is part of
  // the read; the holders endpoint cannot be asked anything about a slug.
  const markets = await prisma.$queryRawUnsafe<{ marketId: string; legs: bigint }[]>(
    `
    SELECT marketId, COUNT(*) AS legs
    FROM PaperTrade
    WHERE isDemo = 0 AND (status = 'open' OR closedAt > (strftime('%s','now') - 7*86400) * 1000)
    GROUP BY marketId
    HAVING COUNT(*) >= ${MIN_LEGS}
    ORDER BY legs DESC
    LIMIT ${MARKETS}
    `
  );

  console.log(`population: our book — ${markets.length} markets by leg count (open or closed in the last 7d), min legs ${MIN_LEGS}`);
  console.log("");
  const rows: { slug: string; legs: number; hit: GammaHit | null; ok: boolean; read?: Awaited<ReturnType<typeof readOutcomeHolders>> }[] = [];
  for (const m of markets) rows.push({ slug: m.marketId, legs: Number(m.legs), hit: null, ok: false });

  let withCondition = 0;
  let assessed = 0;
  let truncated = 0;
  let empty = 0;
  let errored = 0;
  const supplyGaps: number[] = [];
  const top5s: number[] = [];
  const holderCounts: number[] = [];

  for (const row of rows) {
    row.hit = await gammaBySlug(row.slug);
    if (!row.hit?.conditionId) continue;
    withCondition += 1;
    const read = await readOutcomeHolders(row.hit.conditionId);
    row.read = read;
    if (!read.ok) {
      errored += 1;
      console.log(`  ERR  ${row.slug.slice(0, 50).padEnd(50)} ${read.error.slice(0, 90)}`);
      continue;
    }
    if (read.truncated) truncated += 1;
    const profiles = read.outcomes.map((o) => ({
      outcomeIndex: o.outcomeIndex,
      supply: o.supplyShares,
      n: o.holders.filter((h) => (h.amount ?? 0) > 0).length,
      ...holderConcentration(o.holders, { supplyShares: o.supplyShares, supplyComplete: o.complete }),
    }));
    const live = profiles.filter((p) => p.assessed);
    if (live.length === 0) {
      empty += 1;
      console.log(`  NULL ${row.slug.slice(0, 50).padEnd(50)} list returned but no positive holder amounts`);
      continue;
    }
    assessed += 1;
    const worst = [...live].sort((a, b) => b.top5Share - a.top5Share)[0];
    top5s.push(worst.top5Share);
    holderCounts.push(worst.holderCount);
    if (live.length >= 2) {
      const [a, b] = [...live].sort((x, y) => y.supply - x.supply);
      if (a.supply > 0) supplyGaps.push(Math.abs(a.supply - b.supply) / a.supply);
    }
    console.log(
      `  ok   ${row.slug.slice(0, 50).padEnd(50)} legs=${String(row.legs).padStart(3)} outcomes=${read.outcomes.length} pages=${read.pages}` +
        `${read.truncated ? " TRUNCATED" : ""} n=${String(worst.holderCount).padStart(4)} top1=${pct(worst.top1Share)} top5=${pct(worst.top5Share)}`
    );
  }

  const median = (v: number[]) => (v.length ? [...v].sort((a, b) => a - b)[Math.floor(v.length / 2)] : NaN);
  console.log("");
  console.log("COVERAGE (this is gate (a) for OUR universe):");
  console.log(`  slug -> conditionId resolved : ${withCondition}/${rows.length}`);
  console.log(`  concentration assessed       : ${assessed}/${withCondition}`);
  console.log(`  empty holder lists (NULL)    : ${empty}`);
  console.log(`  endpoint errors              : ${errored}`);
  console.log(`  truncated walks (upper bound): ${truncated}`);
  console.log(`  holders per market: median ${median(holderCounts)} max ${Math.max(...holderCounts, 0)}`);
  console.log(
    `  top5 share (worst outcome): median ${pct(median(top5s))} range ${pct(top5s.length ? Math.min(...top5s) : NaN)}-${pct(top5s.length ? Math.max(...top5s) : NaN)}`
  );
  console.log(
    `  supply identity check (complementary outcomes must match): ${supplyGaps.length} markets, max gap ${pct(Math.max(...supplyGaps, 0))}`
  );
  console.log("");
  console.log(
    assessed === withCondition && empty === 0 && errored === 0
      ? "VERDICT: the endpoint is usable on our universe — no nulls, no errors. Truncated walks are marked, not silently averaged."
      : "VERDICT: NOT usable across the whole universe — see the NULL/ERR rows above; those are nulls to record, not zeros."
  );
  return 0;
}

main()
  .then((c) => process.exit(c))
  .catch((e) => {
    console.error(`fatal: ${e instanceof Error ? e.message : e}`);
    process.exit(1);
  });
