/**
 * verify:dashboard-parity — proves the dashboard refactor (rollup + narrow
 * decision reads) returns the same numbers as the implementations it replaced.
 *
 * Run after any change to: src/lib/pnl-rollup.ts, src/lib/decision-aggregates.ts,
 * src/lib/benchmarks.ts, or the Analytics page's funnel/benchmark sections.
 * It recomputes everything the OLD way (full scans, inline JS) and the NEW way,
 * then diffs. Exit 1 on any mismatch.
 *
 *   npx tsx scripts/verify-dashboard-parity.ts
 */

import { prisma } from "../src/lib/db";
import { computeBenchmarks, type BenchmarkReport } from "../src/lib/benchmarks";
import { copyDecisions, decisionCounts, reviewedDecisions } from "../src/lib/decision-aggregates";
import { dailyPnlSeries, hourlyPnlSeries } from "../src/lib/pnl-rollup";
import { computePnl } from "../src/lib/paper";

const HYP = 10;
const dayKey = (d: Date) => d.toISOString().slice(0, 10);
let failures = 0;

function check(label: string, ok: boolean, detail = "") {
  if (!ok) failures++;
  console.log(`${ok ? "  ok  " : "  FAIL"} ${label}${detail ? ` — ${detail}` : ""}`);
}

// ───────────────────────── OLD implementations ─────────────────────────

async function oldBenchmarks(): Promise<BenchmarkReport> {
  const decisions = await prisma.decisionJournal.findMany({
    include: { observedTrade: true, paperTrades: true, outcomeReviews: true },
  });
  const copyRows: { pnl: number | null }[] = [];
  const watchRows: { pnl: number | null }[] = [];
  const skipRows: { pnl: number | null }[] = [];
  const blindRows: { pnl: number | null }[] = [];
  let missedWinners = 0, avoidedLosers = 0, badCopies = 0, goodSkips = 0;
  for (const d of decisions) {
    const review = d.outcomeReviews.find((r) => r.finalOutcome !== null);
    const entry = d.observedTrade.detectedPrice;
    let hypoPnl: number | null = null;
    if (review?.finalOutcome) {
      const won = review.finalOutcome === d.observedTrade.outcome;
      hypoPnl = computePnl(entry, won ? 1 : 0, HYP);
    }
    blindRows.push({ pnl: hypoPnl });
    if (d.decision === "paper_copy") {
      const pnl = d.paperTrades[0]?.realizedPnl ?? null;
      copyRows.push({ pnl });
      if (pnl !== null && pnl < 0) badCopies++;
    } else if (d.decision === "watchlist") {
      watchRows.push({ pnl: hypoPnl });
      if (hypoPnl !== null && hypoPnl > 0) missedWinners++;
      if (hypoPnl !== null && hypoPnl < 0) avoidedLosers++;
    } else {
      skipRows.push({ pnl: hypoPnl });
      if (hypoPnl !== null && hypoPnl > 0) missedWinners++;
      if (hypoPnl !== null && hypoPnl < 0) { avoidedLosers++; goodSkips++; }
    }
  }
  const bucket = (label: string, rows: { pnl: number | null }[]) => {
    const resolved = rows.filter((r) => r.pnl !== null) as { pnl: number }[];
    const total = resolved.reduce((a, r) => a + r.pnl, 0);
    const wins = resolved.filter((r) => r.pnl > 0).length;
    return {
      label, count: rows.length, resolvedCount: resolved.length,
      totalPnl: Math.round(total * 100) / 100,
      winRate: resolved.length ? Math.round((wins / resolved.length) * 1000) / 1000 : 0,
      avgPnl: resolved.length ? Math.round((total / resolved.length) * 100) / 100 : 0,
    };
  };
  return {
    botFiltered: bucket("Bot-filtered paper trades", copyRows),
    blindCopy: bucket("Blind leaderboard copy", blindRows),
    watchlist: bucket("Watchlist (not copied)", watchRows),
    skipped: bucket("Skipped", skipRows),
    missedWinners, avoidedLosers, badCopies, goodSkips,
  };
}

/** Analytics funnel + benchmark cumulative curves, old full-scan way. */
async function oldAnalytics() {
  const decisions = await prisma.decisionJournal.findMany({
    include: { observedTrade: true, paperTrades: true, outcomeReviews: true },
    orderBy: { createdAt: "asc" },
  });
  const funnel = new Map<string, number>();
  for (const d of decisions) funnel.set(d.decision, (funnel.get(d.decision) ?? 0) + 1);

  const bench = new Map<string, { day: string; pnl: number }[]>();
  const pushB = (label: string, day: string, pnl: number) => {
    const arr = bench.get(label) ?? [];
    arr.push({ day, pnl });
    bench.set(label, arr);
  };
  for (const d of decisions) {
    const day = dayKey(d.createdAt);
    const review = d.outcomeReviews.find((r) => r.finalOutcome !== null);
    let hypo: number | null = null;
    if (review?.finalOutcome && d.observedTrade) {
      const won = review.finalOutcome === d.observedTrade.outcome;
      const entry = d.observedTrade.detectedPrice;
      hypo = HYP * (won ? 1 - entry : -entry);
    }
    if (hypo !== null) pushB("Blind copy", day, hypo);
    if (d.decision === "paper_copy") {
      const pnl = d.paperTrades[0]?.realizedPnl ?? null;
      if (pnl !== null) pushB("Bot (actual)", day, pnl);
    } else if (d.decision === "watchlist" && hypo !== null) pushB("Watchlist (hypo)", day, hypo);
    else if (d.decision === "skip" && hypo !== null) pushB("Skipped (hypo)", day, hypo);
  }
  const finals = new Map<string, number>();
  for (const [label, rows] of bench.entries()) {
    const sorted = rows.sort((a, b) => a.day.localeCompare(b.day));
    let cum = 0;
    for (const r of sorted) cum += r.pnl;
    finals.set(label, Math.round(cum * 100) / 100);
  }
  return { total: decisions.length, funnel, finals };
}

/** Analytics funnel + cumulative curves, new narrow-read way. */
async function newAnalytics() {
  const [counts, reviewed, copies] = await Promise.all([decisionCounts(), reviewedDecisions(), copyDecisions()]);
  const bench = new Map<string, { day: string; pnl: number }[]>();
  const pushB = (label: string, day: string, pnl: number) => {
    const arr = bench.get(label) ?? [];
    arr.push({ day, pnl });
    bench.set(label, arr);
  };
  for (const d of reviewed) {
    const day = dayKey(d.createdAt);
    const won = d.finalOutcome === d.outcome;
    const hypo = HYP * (won ? 1 - d.detectedPrice : -d.detectedPrice);
    pushB("Blind copy", day, hypo);
    if (d.decision === "watchlist") pushB("Watchlist (hypo)", day, hypo);
    else if (d.decision === "skip") pushB("Skipped (hypo)", day, hypo);
  }
  for (const c of copies) {
    if (c.realizedPnl !== null) pushB("Bot (actual)", dayKey(c.createdAt), c.realizedPnl);
  }
  const finals = new Map<string, number>();
  for (const [label, rows] of bench.entries()) {
    const sorted = rows.sort((a, b) => a.day.localeCompare(b.day));
    let cum = 0;
    for (const r of sorted) cum += r.pnl;
    finals.set(label, Math.round(cum * 100) / 100);
  }
  return { total: counts.total, byType: counts.byType, finals };
}

async function main() {
  console.log("== 1. hourly/daily PnL series: rollup vs inline GROUP BY ==");
  const rawHourly = await prisma.$queryRaw<Array<{ hour: string; botId: string; total_pnl: number }>>`
    SELECT strftime('%Y-%m-%d %H:00:00', s.collectedAt / 1000, 'unixepoch') as hour, t.botId, SUM(s.pnl) as total_pnl
    FROM PnlSnapshot s JOIN PaperTrade t ON s.paperTradeId = t.id GROUP BY hour, t.botId ORDER BY hour ASC`;
  const newHourly = await hourlyPnlSeries();
  const curHour = new Date(Math.floor(Date.now() / 3_600_000) * 3_600_000).toISOString().slice(0, 19).replace("T", " ");
  const keyH = (r: { hour: string; botId: string }) => `${r.hour}|${r.botId}`;
  const mapNew = new Map(newHourly.map((r) => [keyH(r), r.total_pnl]));
  let worst = 0, missing = 0, settledDiff = 0;
  for (const r of rawHourly) {
    const v = mapNew.get(keyH(r));
    if (v === undefined) { missing++; continue; }
    const d = Math.abs(v - r.total_pnl);
    if (d > worst) worst = d;
    if (d > 1e-6 && r.hour !== curHour) settledDiff++;
  }
  check(`hourly rows covered (raw=${rawHourly.length} rollup=${newHourly.length}, missing=${missing})`, missing === 0);
  check(`hourly settled hours identical (max abs diff=${worst.toExponential(2)}, settled mismatches=${settledDiff})`, settledDiff === 0);

  const rawDaily = await prisma.$queryRaw<Array<{ day: string; botId: string; total_pnl: number }>>`
    SELECT strftime('%Y-%m-%d', s.collectedAt / 1000, 'unixepoch') as day, t.botId, SUM(s.pnl) as total_pnl
    FROM PnlSnapshot s JOIN PaperTrade t ON s.paperTradeId = t.id GROUP BY day, t.botId ORDER BY day ASC`;
  const newDaily = await dailyPnlSeries();
  const keyD = (r: { day: string; botId: string }) => `${r.day}|${r.botId}`;
  const mapD = new Map(newDaily.map((r) => [keyD(r), r.total_pnl]));
  let worstD = 0, missingD = 0, settledD = 0;
  const today = new Date().toISOString().slice(0, 10);
  for (const r of rawDaily) {
    const v = mapD.get(keyD(r));
    if (v === undefined) { missingD++; continue; }
    const d = Math.abs(v - r.total_pnl);
    if (d > worstD) worstD = d;
    if (d > 1e-6 && r.day !== today) settledD++;
  }
  check(`daily rows covered (raw=${rawDaily.length} rollup=${newDaily.length}, missing=${missingD})`, missingD === 0);
  check(`daily settled days identical (max abs diff=${worstD.toExponential(2)}, settled mismatches=${settledD})`, settledD === 0);

  console.log("\n== 2. computeBenchmarks: old full-scan vs new narrow reads ==");
  const [oldB, newB] = await Promise.all([oldBenchmarks(), computeBenchmarks()]);
  for (const k of ["botFiltered", "blindCopy", "watchlist", "skipped"] as const) {
    const a = oldB[k], b = newB[k];
    const same = a.count === b.count && a.resolvedCount === b.resolvedCount &&
      Math.abs(a.totalPnl - b.totalPnl) < 1e-9 && a.winRate === b.winRate && a.avgPnl === b.avgPnl;
    check(`${k}: count=${b.count} resolved=${b.resolvedCount} total=${b.totalPnl} winRate=${b.winRate} avg=${b.avgPnl}`, same,
      same ? "" : `old: count=${a.count} resolved=${a.resolvedCount} total=${a.totalPnl} winRate=${a.winRate} avg=${a.avgPnl}`);
  }
  for (const k of ["missedWinners", "avoidedLosers", "badCopies", "goodSkips"] as const) {
    check(`${k}: ${newB[k]}`, oldB[k] === newB[k], oldB[k] === newB[k] ? "" : `old=${oldB[k]}`);
  }

  console.log("\n== 3. Analytics: funnel + benchmark cumulative curves ==");
  const [oldA, newA] = await Promise.all([oldAnalytics(), newAnalytics()]);
  check(`total decisions: ${newA.total}`, oldA.total === newA.total, oldA.total === newA.total ? "" : `old=${oldA.total}`);
  for (const k of ["paper_copy", "watchlist", "skip"]) {
    const o = oldA.funnel.get(k) ?? 0;
    const n = newA.byType[k] ?? 0;
    check(`funnel ${k}: ${n}`, o === n, o === n ? "" : `old=${o}`);
  }
  for (const label of ["Blind copy", "Bot (actual)", "Watchlist (hypo)", "Skipped (hypo)"]) {
    const o = oldA.finals.get(label) ?? 0;
    const n = newA.finals.get(label) ?? 0;
    check(`curve final "${label}": ${n}`, Math.abs(o - n) < 0.005, Math.abs(o - n) < 0.005 ? "" : `old=${o}`);
  }

  console.log(`\n${failures === 0 ? "ALL PARITY CHECKS PASSED" : `${failures} PARITY CHECK(S) FAILED`}`);
  await prisma.$disconnect();
  process.exit(failures === 0 ? 0 : 1);
}

main().catch(async (e) => {
  console.error(e);
  await prisma.$disconnect().catch(() => {});
  process.exit(1);
});
