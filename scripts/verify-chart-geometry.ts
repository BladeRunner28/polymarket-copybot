/**
 * Rendered-geometry parity: render the charts' SVG path data from the rollup
 * and from the raw inline GROUP BY at the SAME moment, and compare the strings.
 *
 * The before/after HTML diff can't isolate a refactor from data drift (new
 * snapshots arrive hourly and shift the chart's shared y-scale), so this
 * compares geometry computed from both data sources in one run.
 *
 *   npx tsx scripts/verify-chart-geometry.ts
 */

import { prisma } from "../src/lib/db";
import { dailyPnlSeries, hourlyPnlSeries } from "../src/lib/pnl-rollup";

// Mirror of src/components/chart.tsx geometry.
function linePath(points: { x: string; y: number }[], allSeries: Array<{ x: string; y: number }[]>, h = 160) {
  const w = 720, pad = 36;
  const ys = allSeries.flatMap((s) => s.map((p) => p.y));
  const minY = Math.min(...ys, 0);
  const maxY = Math.max(...ys, 0);
  const range = maxY - minY || 1;
  const sx = (i: number, len: number) => pad + (i / (len - 1)) * (w - pad * 2);
  const sy = (y: number) => h - pad - ((y - minY) / range) * (h - pad * 2);
  return points.map((p, i) => `${i === 0 ? "M" : "L"}${sx(i, points.length).toFixed(1)},${sy(p.y).toFixed(1)}`).join(" ");
}

const round2 = (v: number) => Math.round(v * 100) / 100;

async function main() {
  // ---- hourly (root page + performance page) ----
  const rawHourly = await prisma.$queryRaw<Array<{ hour: string; botId: string; total_pnl: number }>>`
    SELECT strftime('%Y-%m-%d %H:00:00', s.collectedAt / 1000, 'unixepoch') as hour, t.botId, SUM(s.pnl) as total_pnl
    FROM PnlSnapshot s JOIN PaperTrade t ON s.paperTradeId = t.id GROUP BY hour, t.botId ORDER BY hour ASC`;
  const rollHourly = await hourlyPnlSeries();

  const mkSeries = (rows: Array<{ hour: string; botId: string; total_pnl: number }>) => {
    const std = rows.filter((r) => r.botId === "STANDARD").map((s) => ({ x: s.hour ? s.hour.slice(5, 13) : "", y: round2(s.total_pnl ?? 0) })).filter((p) => p.x !== "");
    const c200 = rows.filter((r) => r.botId === "BANKROLL_200").map((s) => ({ x: s.hour ? s.hour.slice(5, 13) : "", y: round2(s.total_pnl ?? 0) })).filter((p) => p.x !== "");
    return [std, c200];
  };
  const [rawStd, rawC200] = mkSeries(rawHourly);
  const [rollStd, rollC200] = mkSeries(rollHourly);
  const rawPaths = [linePath(rawStd, [rawStd, rawC200]), linePath(rawC200, [rawStd, rawC200])];
  const rollPaths = [linePath(rollStd, [rollStd, rollC200]), linePath(rollC200, [rollStd, rollC200])];

  console.log(`hourly series points: raw STANDARD=${rawStd.length} BANKROLL_200=${rawC200.length} | rollup STANDARD=${rollStd.length} BANKROLL_200=${rollC200.length}`);
  console.log(`  STANDARD path identical: ${rawPaths[0] === rollPaths[0]}`);
  console.log(`  BANKROLL_200 path identical: ${rawPaths[1] === rollPaths[1]}`);

  // ---- daily (analytics page) ----
  const rawDaily = await prisma.$queryRaw<Array<{ day: string; botId: string; total_pnl: number }>>`
    SELECT strftime('%Y-%m-%d', s.collectedAt / 1000, 'unixepoch') as day, t.botId, SUM(s.pnl) as total_pnl
    FROM PnlSnapshot s JOIN PaperTrade t ON s.paperTradeId = t.id GROUP BY day, t.botId ORDER BY day ASC`;
  const rollDaily = await dailyPnlSeries();

  const dailySeries = (rows: Array<{ day: string; botId: string; total_pnl: number }>) => {
    const byBot = new Map<string, { day: string; cum: number }[]>();
    for (const s of rows) {
      const arr = byBot.get(s.botId) ?? [];
      const cum = arr.length ? arr[arr.length - 1].cum + s.total_pnl : s.total_pnl;
      arr.push({ day: s.day, cum: round2(cum) });
      byBot.set(s.botId, arr);
    }
    return byBot;
  };
  const rawMap = dailySeries(rawDaily), rollMap = dailySeries(rollDaily);
  let dayChecks = 0, dayDiffs = 0;
  for (const bot of ["BANKROLL_200", "STANDARD"]) {
    const a = (rawMap.get(bot) ?? []).map((p) => `${p.day}=${p.cum}`).join(",");
    const b = (rollMap.get(bot) ?? []).map((p) => `${p.day}=${p.cum}`).join(",");
    dayChecks++;
    if (a !== b) {
      dayDiffs++;
      const av = a.split(","), bv = b.split(",");
      const n = av.findIndex((v, i) => v !== bv[i]);
      console.log(`  DIFF daily ${bot} at index ${n}: raw=${av[n]} rollup=${bv[n]} (len ${av.length} vs ${bv.length})`);
    }
  }
  console.log(`daily cumulative series: bots checked=${dayChecks} differing=${dayDiffs}`);
  console.log(`\n${rawPaths[0] === rollPaths[0] && rawPaths[1] === rollPaths[1] && dayDiffs === 0 ? "CHART GEOMETRY IDENTICAL" : "CHART GEOMETRY DIFFERS"}`);
  await prisma.$disconnect();
}
main();
