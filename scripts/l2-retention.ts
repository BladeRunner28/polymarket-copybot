/**
 * l2-retention — measure the L2 corpus against its retention policy and print the plan.
 * Read-only by default: it writes a JSON read and, with --apply, deletes ONLY files the
 * policy marked `delete` after every guard in src/lib/l2-retention.ts passed.
 *
 *   npx tsx scripts/l2-retention.ts                      # plan + read file
 *   npx tsx scripts/l2-retention.ts --quiet              # cron: prints only when OUTSIDE policy
 *   npx tsx scripts/l2-retention.ts --apply --i-know-this-is-irreversible
 *
 * Evidence for card `l2-retention-cron`. BASIS printed on every run:
 *   population = files in data/l2 (*.jsonl, one per CLOB asset id)
 *   level      = one file; clock = file mtime; size = apparent bytes
 *   guards     = young (<minAgeDays) / unattributed (no market in data/l2-asset-map.jsonl or data/l2-asset-backfill.jsonl)
 *                / protected (market has an open leg, an un-stamped leg, or a live intent)
 */

import { PrismaClient } from "@prisma/client";
import * as fs from "fs";
import { join } from "path";
import {
  DEFAULT_L2_POLICY,
  ceilingVerdict,
  mergeAssetMaps,
  parseAssetMap,
  planL2Retention,
  recentBytesPerDayUpperBound,
  DAY_MS,
  type L2File,
} from "../src/lib/l2-retention";

const REPO = join(__dirname, "..");
const L2_DIR = join(REPO, "data", "l2");
const ASSET_MAP = join(REPO, "data", "l2-asset-map.jsonl");
// Second attribution source (scripts/l2-asset-backfill.py). Separate file on purpose: the
// recorder appends to ASSET_MAP while running, and two writers on one append-only ledger is
// how a torn line gets in the middle of a file instead of at its end.
const ASSET_BACKFILL = join(REPO, "data", "l2-asset-backfill.jsonl");
const OUT = join(REPO, "data", "l2-retention-read.json");
const LEDGER = join(REPO, "data", "l2-retention-ledger.jsonl");

function arg(name: string, def: string): string {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : def;
}
const flag = (name: string) => process.argv.includes(`--${name}`);

const MIN_AGE_DAYS = Number(arg("min-age-days", String(DEFAULT_L2_POLICY.minAgeDays)));
const CEILING_GB = Number(arg("ceiling-gb", String(DEFAULT_L2_POLICY.ceilingBytes / 1024 ** 3)));
const CEILING_BYTES = Math.round(CEILING_GB * 1024 ** 3);
const ALLOW_UNATTRIBUTED = flag("allow-unattributed");
const QUIET = flag("quiet");
const APPLY = flag("apply");
const IRREVERSIBLE = flag("i-know-this-is-irreversible");

const gib = (n: number) => (n / 1024 ** 3).toFixed(2) + " GiB";
const pct = (n: number, d: number) => (d <= 0 ? "n/a" : ((n / d) * 100).toFixed(1) + "%");

/**
 * tokenId -> marketId from BOTH sources: the recorder's map (primary) and the backfill ledger.
 * Prints its own basis: rows read per source, rows skipped, and any disagreement between them.
 */
function readAssetMap(): {
  map: Map<string, string>;
  lines: number;
  backfillLines: number;
  backfillTokens: number;
  skipped: number;
  conflicts: number;
} {
  const read = (path: string): string => (fs.existsSync(path) ? fs.readFileSync(path, "utf8") : "");
  const rec = parseAssetMap(read(ASSET_MAP), "recorder");
  const back = parseAssetMap(read(ASSET_BACKFILL), "backfill");
  const merged = mergeAssetMaps(rec.map, back.map);
  if (merged.conflicts.length > 0) {
    // Not silent, not fatal: print the first few and let the count speak.
    console.error(
      `WARNING: ${merged.conflicts.length} token(s) attributed differently by the recorder and the backfill; recorder wins`,
    );
    for (const c of merged.conflicts.slice(0, 5)) console.error(`  ${c.tokenId}: ${c.primary} (recorder) vs ${c.secondary} (backfill)`);
  }
  return {
    map: merged.map,
    lines: rec.rows,
    backfillLines: back.rows,
    backfillTokens: merged.fromSecondary,
    skipped: rec.skipped + back.skipped,
    conflicts: merged.conflicts.length,
  };
}

async function main() {
  const prisma = new PrismaClient();
  const nowMs = Date.now();
  try {
    const names = fs.readdirSync(L2_DIR).filter((f) => f.endsWith(".jsonl"));
    const files: L2File[] = [];
    for (const f of names) {
      const st = fs.statSync(join(L2_DIR, f));
      files.push({ tokenId: f.slice(0, -".jsonl".length), bytes: st.size, mtimeMs: st.mtimeMs });
    }

    const assetMap = readAssetMap();
    const tokenToMarket = assetMap.map;

    // Guards. Each is a distinct reason a file cannot be deleted, and each is printed with its own count.
    const openMarkets = await prisma.paperTrade.findMany({
      where: { isDemo: false, status: "open" },
      select: { marketId: true },
      distinct: ["marketId"],
    });
    const unstampedMarkets = await prisma.paperTrade.findMany({
      where: { isDemo: false, fillStatus: null },
      select: { marketId: true },
      distinct: ["marketId"],
    });
    const liveIntents = await prisma.fillIntent.findMany({
      where: { dispatchedAt: { gte: new Date(nowMs - MIN_AGE_DAYS * DAY_MS) } },
      select: { marketId: true },
      distinct: ["marketId"],
    });
    const protectedMarkets = new Set<string>([
      ...openMarkets.map((r) => r.marketId),
      ...unstampedMarkets.map((r) => r.marketId),
      ...liveIntents.map((r) => r.marketId),
    ]);

    const policy = { minAgeDays: MIN_AGE_DAYS, ceilingBytes: CEILING_BYTES, allowUnattributed: ALLOW_UNATTRIBUTED };
    const plan = planL2Retention(files, { nowMs, policy, tokenToMarket, protectedMarkets });
    const growth = recentBytesPerDayUpperBound(files, nowMs, 7);
    const ceiling = ceilingVerdict(plan.totalBytes, CEILING_BYTES, growth);

    const read = {
      generatedAt: new Date(nowMs).toISOString(),
      basis: {
        population: "files in data/l2 (*.jsonl, one per CLOB asset id)",
        level: "one L2 file",
        clock: "file mtime (append-only corpus; mtime = last observation)",
        size: "apparent bytes (st_size)",
        policy,
      },
      corpus: {
        files: plan.totalFiles,
        bytes: plan.totalBytes,
        oldestAgeDays: Number(plan.oldestAgeDays.toFixed(1)),
        growthBytesPerDayUpperBound: Math.round(growth),
        assetMapLines: assetMap.lines,
        assetBackfillLines: assetMap.backfillLines,
        assetBackfillTokens: assetMap.backfillTokens,
        assetMapSkippedRows: assetMap.skipped,
        assetMapConflicts: assetMap.conflicts,
        unmappedFiles: plan.unattributedFiles,
        unmappedBytes: plan.unattributedBytes,
      },
      guards: {
        protectedMarkets: protectedMarkets.size,
        openMarkets: openMarkets.length,
        unstampedMarkets: unstampedMarkets.length,
        liveIntentMarkets: liveIntents.length,
        youngFiles: plan.youngFiles,
        youngBytes: plan.youngBytes,
        protectedFiles: plan.protectedFiles,
        protectedBytes: plan.protectedBytes,
        unattributedFiles: plan.unattributedFiles,
        unattributedBytes: plan.unattributedBytes,
      },
      ceiling: {
        ceilingBytes: CEILING_BYTES,
        status: ceiling.status,
        overBytes: ceiling.overBytes,
        projectedDaysToCeiling: ceiling.projectedDaysToCeiling === null ? null : Number(ceiling.projectedDaysToCeiling.toFixed(1)),
      },
      plan: {
        deleteFiles: plan.deleteFiles,
        deleteBytes: plan.deleteBytes,
        deleteUnattributedBytes: plan.deleteUnattributedBytes,
        unreachableBytes: plan.unreachableBytes,
        oldestDeleteAgeDays: plan.rows.filter((r) => r.verdict === "delete").reduce((m, r) => Math.max(m, r.ageDays), 0),
        applied: false,
      },
    };

    if (!QUIET || ceiling.status === "over") {
      console.log("L2 RETENTION READ");
      console.log(
        `basis: population = data/l2 files, level = one file, clock = mtime, window policy ${MIN_AGE_DAYS}d, ceiling ${CEILING_GB} GiB, as of ${read.generatedAt}`,
      );
      console.log(
        `corpus: ${plan.totalFiles} files / ${gib(plan.totalBytes)}; oldest ${plan.oldestAgeDays.toFixed(1)}d; growth <= ${gib(growth)}/day (upper bound: whole size of every file touched in 7d)`,
      );
      console.log(
        `attribution: recorder ${assetMap.lines} rows + backfill ${assetMap.backfillLines} rows (${assetMap.backfillTokens} tokens) ` +
          `= ${tokenToMarket.size} tokens; skipped ${assetMap.skipped}, conflicts ${assetMap.conflicts}`,
      );
      console.log(
        `guards: young ${plan.youngFiles} / ${gib(plan.youngBytes)} | protected ${plan.protectedFiles} / ${gib(plan.protectedBytes)} across ${protectedMarkets.size} markets (open ${openMarkets.length}, un-stamped ${unstampedMarkets.length}, live intents ${liveIntents.length}) | unattributed ${plan.unattributedFiles} / ${gib(plan.unattributedBytes)} (${pct(plan.unattributedBytes, plan.totalBytes)})`,
      );
      if (ceiling.status === "over") {
        console.log(
          `CEILING BREACH: ${gib(plan.totalBytes)} against ${CEILING_GB} GiB -> over by ${gib(ceiling.overBytes)}; plan would delete ${plan.deleteFiles} files / ${gib(plan.deleteBytes)}, oldest ${read.plan.oldestDeleteAgeDays.toFixed(1)}d`,
        );
        if (plan.unreachableBytes > 0)
          console.log(`  NOT reachable under the guards: ${gib(plan.unreachableBytes)} — every remaining file is young, protected or unattributed`);
        if (plan.deleteUnattributedBytes > 0)
          console.log(`  WARNING: plan destroys ${gib(plan.deleteUnattributedBytes)} of UNATTRIBUTED files (--allow-unattributed)`);
      } else {
        console.log(
          `inside policy: ${gib(CEILING_BYTES - plan.totalBytes)} of headroom; ceiling in ${ceiling.projectedDaysToCeiling ?? "n/a"} days at the upper-bound rate; plan deletes 0`,
        );
      }
    }

    if (APPLY) {
      if (!IRREVERSIBLE) {
        console.error("REFUSED: --apply needs --i-know-this-is-irreversible (the corpus cannot be re-recorded)");
        process.exit(2);
      }
      const victims = plan.rows.filter((r) => r.verdict === "delete");
      if (victims.some((r) => r.marketId === null) && !ALLOW_UNATTRIBUTED) {
        console.error("REFUSED: plan contains unattributed files without --allow-unattributed");
        process.exit(2);
      }
      if (victims.some((r) => r.marketId !== null && protectedMarkets.has(r.marketId))) {
        console.error("REFUSED: plan contains a protected market — the guard is broken, do not delete");
        process.exit(2);
      }
      let freed = 0;
      for (const r of victims) {
        fs.unlinkSync(join(L2_DIR, `${r.tokenId}.jsonl`));
        freed += r.bytes;
        fs.appendFileSync(
          LEDGER,
          JSON.stringify({
            atMs: nowMs,
            tokenId: r.tokenId,
            marketId: r.marketId,
            bytes: r.bytes,
            mtimeMs: Math.round(r.mtimeMs),
            ageDays: Number(r.ageDays.toFixed(2)),
            minAgeDays: MIN_AGE_DAYS,
            ceilingBytes: CEILING_BYTES,
          }) + "\n",
        );
      }
      read.plan.applied = true;
      console.log(`APPLIED: deleted ${victims.length} files / ${gib(freed)}; ledger ${LEDGER}`);
    }

    fs.writeFileSync(OUT, JSON.stringify(read, null, 2) + "\n");
    if (!QUIET) console.log(`read -> ${OUT}`);
    // Cron contract: rc 0 with NO output is the only healthy case. A breach exits 1 so the
    // caller can tell "outside policy" from "check failed" (rc 2+ / unparseable).
    if (QUIET && ceiling.status === "over") process.exitCode = 1;
  } finally {
    await prisma.$disconnect();
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
