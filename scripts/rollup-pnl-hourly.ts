/**
 * rollup:pnl — maintain the `PnlHourlyRollup` pre-aggregate.
 *
 * WHY: three dashboard pages (/, /performance, /analytics) each ran
 *   SELECT strftime('%Y-%m-%d %H:00:00', collectedAt/1000, 'unixepoch'), botId, SUM(pnl)
 *   FROM PnlSnapshot JOIN PaperTrade GROUP BY 1, 2
 * inline on every request. That is a full scan of PnlSnapshot (1.99M rows,
 * 159 MB table + 147 MB of indexes) plus a temp B-tree — ~10s per page load
 * through the dashboard. This script materializes the same aggregate once per
 * hour so the pages read ~2.5k rows instead.
 *
 * SEMANTICS (must stay identical to the old inline query):
 *   - hour is UTC, formatted exactly like strftime('...%H:00:00', unixepoch)
 *   - grouped by (hour, botId), botId from the joined PaperTrade
 *   - no demo filter, no status filter (the old query had none)
 *
 * MODES
 *   (default)            incremental: recompute from the last stored hour
 *                        (minus LOOKBACK_HOURS) to now, replace those hours
 *   --rebuild            recompute every hour from scratch
 *   --verify             recompute a window from live data and diff it against
 *                        the stored rollup; writes nothing
 *   --verify-hours=N     window size for --verify (default 48)
 *
 * Every run (except --verify) also reconciles SUM(rollup) against
 * SUM(PnlSnapshot.pnl) and self-heals with a full rebuild on mismatch, so a
 * stale/gappy rollup can never silently misreport PnL.
 */

import { prisma } from "../src/lib/db";
import { log, logError } from "../src/lib/redact";

const LOOKBACK_HOURS = 2;
const RECONCILE_TOLERANCE = 0.01; // SUM(REAL) associativity — a cent is noise

type AggRow = { hour: string; botId: string; total: number; n: number | bigint };

const hourExpr = `strftime('%Y-%m-%d %H:00:00', s.collectedAt / 1000, 'unixepoch')`;

const args = process.argv.slice(2);
const REBUILD = args.includes("--rebuild");
const VERIFY = args.includes("--verify");
const verifyHours = (() => {
  const a = args.find((x) => x.startsWith("--verify-hours="));
  return a ? Number(a.split("=")[1]) : 48;
})();

/** Aggregate PnlSnapshot rows at-or-after `sinceMs` (null = all rows). */
async function aggregate(sinceMs: number | null): Promise<AggRow[]> {
  if (sinceMs === null) {
    return prisma.$queryRawUnsafe<AggRow[]>(`
      SELECT ${hourExpr} AS hour, t.botId AS botId, SUM(s.pnl) AS total, COUNT(*) AS n
      FROM PnlSnapshot s JOIN PaperTrade t ON s.paperTradeId = t.id
      GROUP BY hour, t.botId`);
  }
  return prisma.$queryRaw<AggRow[]>`
    SELECT strftime('%Y-%m-%d %H:00:00', s.collectedAt / 1000, 'unixepoch') AS hour,
           t.botId AS botId, SUM(s.pnl) AS total, COUNT(*) AS n
    FROM PnlSnapshot s JOIN PaperTrade t ON s.paperTradeId = t.id
    WHERE s.collectedAt >= ${sinceMs}
    GROUP BY hour, t.botId`;
}

const msOfHour = (hour: string) => Date.parse(`${hour.replace(" ", "T")}Z`);
const hourOf = (ms: number) =>
  new Date(Math.floor(ms / 3_600_000) * 3_600_000).toISOString().slice(0, 19).replace("T", " ");

async function watermark(): Promise<{ hour: string; botId: string } | null> {
  return prisma.pnlHourlyRollup.findFirst({ orderBy: { hour: "desc" }, select: { hour: true, botId: true } });
}

async function writeRows(rows: AggRow[]): Promise<number> {
  if (rows.length === 0) return 0;
  const now = new Date();
  await prisma.pnlHourlyRollup.createMany({
    data: rows.map((r) => ({
      hour: r.hour,
      botId: r.botId,
      totalPnl: Number(r.total ?? 0),
      snapshotCount: Number(r.n ?? 0),
      updatedAt: now,
    })),
  });
  return rows.length;
}

/**
 * SUM over the rollup vs SUM over the raw table.
 *
 * The CURRENT UTC hour is excluded: PnlSnapshot is append-only and the hourly
 * cron keeps adding rows to it, so that hour is a moving target — comparing it
 * would flag a "mismatch" on every run and trigger pointless rebuilds. Every
 * settled hour is compared, which is where a stale or gappy rollup would show.
 */
async function reconcile(): Promise<{
  live: number;
  rolled: number;
  delta: number;
  snapshots: number;
  currentHourLive: number;
  currentHourRolled: number;
}> {
  const curHour = hourOf(Date.now());
  const [live] = await prisma.$queryRaw<Array<{ live: number | null; n: number | bigint }>>`
    SELECT SUM(pnl) AS live, COUNT(*) AS n FROM PnlSnapshot`;
  const [settled] = await prisma.$queryRaw<Array<{ raw: number | null }>>`
    SELECT SUM(s.pnl) AS raw FROM PnlSnapshot s
    WHERE strftime('%Y-%m-%d %H:00:00', s.collectedAt / 1000, 'unixepoch') < ${curHour}`;
  const [rolled] = await prisma.$queryRaw<Array<{ rolled: number | null; current: number | null }>>`
    SELECT SUM(CASE WHEN hour < ${curHour} THEN totalPnl ELSE 0 END) AS rolled,
           SUM(CASE WHEN hour = ${curHour} THEN totalPnl ELSE 0 END) AS current
    FROM PnlHourlyRollup`;
  const r = Number(rolled?.rolled ?? 0);
  const raw = Number(settled?.raw ?? 0);
  return {
    live: raw,
    rolled: r,
    delta: r - raw,
    snapshots: Number(live?.n ?? 0),
    currentHourLive: Number(live?.live ?? 0) - raw,
    currentHourRolled: Number(rolled?.current ?? 0),
  };
}

async function main() {
  const t0 = Date.now();

  // ---------- verify: recompute a live window and diff against the rollup ----
  if (VERIFY) {
    const sinceMs = Date.now() - verifyHours * 3_600_000;
    const curHour = hourOf(Date.now());
    const live = await aggregate(sinceMs);
    const stored = await prisma.pnlHourlyRollup.findMany({ where: { hour: { gte: hourOf(sinceMs) } } });
    const key = (r: { hour: string; botId: string }) => `${r.hour}|${r.botId}`;
    const storedMap = new Map(stored.map((r) => [key(r), r]));
    let mismatches = 0;
    const moving: string[] = [];
    for (const r of live) {
      // The in-progress hour is append-only and still filling: report it, don't
      // count it as drift.
      if (r.hour === curHour) {
        moving.push(`${r.hour} ${r.botId}: live=${Number(r.total ?? 0).toFixed(2)} n=${r.n} vs rollup=${storedMap.get(key(r))?.totalPnl?.toFixed(2) ?? "absent"}`);
        continue;
      }
      const s = storedMap.get(key(r));
      const expected = Number(r.total ?? 0);
      if (!s || Math.abs(s.totalPnl - expected) > 1e-6 || s.snapshotCount !== Number(r.n)) {
        mismatches++;
        if (mismatches <= 5) {
          logError(`  MISMATCH ${r.hour} ${r.botId}: live=${expected} n=${r.n} rollup=${s?.totalPnl} n=${s?.snapshotCount}`);
        }
      }
    }
    const extra = stored.filter((r) => r.hour !== curHour && !live.some((l) => key(l) === key(r))).length;
    log(`verify (last ${verifyHours}h): live_hours=${live.length} stored_hours=${stored.length} mismatches=${mismatches} stale_extra=${extra}`);
    for (const m of moving) log(`  in-progress hour (not drift): ${m}`);
    const rec = await reconcile();
    log(`reconcile: rollup=${rec.rolled.toFixed(2)} raw=${rec.live.toFixed(2)} delta=${rec.delta.toFixed(4)} snapshots=${rec.snapshots}`);
    await prisma.$disconnect();
    process.exit(mismatches === 0 && extra === 0 ? 0 : 1);
  }

  // ---------- incremental or full rebuild ----------
  const wm = REBUILD ? null : await watermark();
  let mode = REBUILD || !wm ? "rebuild" : "incremental";

  let sinceMs: number | null = null;
  let fromHour: string | null = null;
  if (mode === "incremental" && wm) {
    sinceMs = msOfHour(wm.hour) - LOOKBACK_HOURS * 3_600_000;
    fromHour = hourOf(sinceMs);
  }

  let rows = await aggregate(sinceMs);
  let written = 0;
  if (mode === "rebuild") {
    await prisma.$transaction([
      prisma.pnlHourlyRollup.deleteMany({}),
      prisma.pnlHourlyRollup.createMany({
        data: rows.map((r) => ({
          hour: r.hour,
          botId: r.botId,
          totalPnl: Number(r.total ?? 0),
          snapshotCount: Number(r.n ?? 0),
          updatedAt: new Date(),
        })),
      }),
    ]);
    written = rows.length;
  } else {
    await prisma.pnlHourlyRollup.deleteMany({ where: { hour: { gte: fromHour! } } });
    written = await writeRows(rows);
  }

  // ---------- reconcile, self-heal on mismatch ----------
  let rec = await reconcile();
  if (Math.abs(rec.delta) > RECONCILE_TOLERANCE) {
    logError(`reconcile FAILED: delta=${rec.delta.toFixed(4)} — full rebuild`);
    rows = await aggregate(null);
    await prisma.$transaction([
      prisma.pnlHourlyRollup.deleteMany({}),
      prisma.pnlHourlyRollup.createMany({
        data: rows.map((r) => ({
          hour: r.hour,
          botId: r.botId,
          totalPnl: Number(r.total ?? 0),
          snapshotCount: Number(r.n ?? 0),
          updatedAt: new Date(),
        })),
      }),
    ]);
    written = rows.length;
    mode = "rebuild";
    rec = await reconcile();
  }

  const total = await prisma.pnlHourlyRollup.count();
  log(
    `rollup-pnl ${mode}: wrote ${written} hour-rows in ${Date.now() - t0}ms (table=${total}) | ` +
      `settled-hours rollup=${rec.rolled.toFixed(2)} raw=${rec.live.toFixed(2)} delta=${rec.delta.toFixed(4)} | ` +
      `current-hour rollup=${rec.currentHourRolled.toFixed(2)} live=${rec.currentHourLive.toFixed(2)}`
  );

  if (Math.abs(rec.delta) > RECONCILE_TOLERANCE) {
    logError(`rollup still inconsistent after rebuild (delta=${rec.delta.toFixed(4)})`);
    await prisma.$disconnect();
    process.exit(1);
  }
  await prisma.$disconnect();
}

main().catch(async (e) => {
  logError(`rollup-pnl failed: ${e instanceof Error ? e.message : String(e)}`);
  await prisma.$disconnect().catch(() => {});
  process.exit(1);
});
