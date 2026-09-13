import { prisma } from "../src/lib/db";
import { dailyPnlSeries } from "../src/lib/pnl-rollup";
import { copyDecisions, decisionCounts, reviewedDecisions } from "../src/lib/decision-aggregates";

const ET = "America/New_York";
function etPartsUncached(ms: number): { hour: number; weekday: number } {
  const fmt = new Intl.DateTimeFormat("en-US", { timeZone: ET, hour: "numeric", weekday: "short", hour12: false });
  const parts = fmt.formatToParts(new Date(ms));
  let hour = 0, weekday = 0;
  const wdMap: Record<string, number> = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
  for (const p of parts) {
    if (p.type === "hour") hour = parseInt(p.value, 10) % 24;
    if (p.type === "weekday") weekday = wdMap[p.value] ?? 0;
  }
  return { hour, weekday };
}
const FMT = new Intl.DateTimeFormat("en-US", { timeZone: ET, hour: "numeric", weekday: "short", hour12: false });
function etPartsCached(ms: number): { hour: number; weekday: number } {
  const parts = FMT.formatToParts(new Date(ms));
  let hour = 0, weekday = 0;
  const wdMap: Record<string, number> = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
  for (const p of parts) {
    if (p.type === "hour") hour = parseInt(p.value, 10) % 24;
    if (p.type === "weekday") weekday = wdMap[p.value] ?? 0;
  }
  return { hour, weekday };
}

async function t<T>(label: string, fn: () => Promise<T> | T): Promise<T> {
  const s = Date.now();
  const r = await fn();
  console.log(`${(Date.now() - s).toString().padStart(7)}ms  ${label}`);
  return r;
}

async function main() {
  console.log("=== analytics data path (after refactor) ===");
  const [c200Resolved, snapshots, decisionStats, allResolved, trackedWallets, insiderScores] = await Promise.all([
    t("c200Resolved", () => prisma.paperTrade.findMany({ where: { botId: "BANKROLL_200", status: { in: ["closed", "resolved"] }, realizedPnl: { not: null } }, select: { realizedPnl: true, resolvedAt: true, openedAt: true } })),
    t("snapshots (rollup daily)", () => dailyPnlSeries()),
    t("decisionStats (3 narrow reads)", () => Promise.all([decisionCounts(), reviewedDecisions(), copyDecisions()])),
    t("allResolved (nested decision+observedTrade)", () => prisma.paperTrade.findMany({ where: { status: { in: ["closed", "resolved"] }, realizedPnl: { not: null } }, include: { decision: { include: { observedTrade: true } } } })),
    t("trackedWallets", () => prisma.walletProfile.findMany({ where: { status: "track" }, select: { address: true, globalScore: true } })),
    t("insiderScores", () => prisma.walletInsiderScore.findMany({ select: { walletAddress: true, flagged: true, watch: true } })),
  ]);

  console.log(`\nallResolved rows=${allResolved.length}`);
  await t("heat loop, etParts creating an Intl formatter per row (current)", () => {
    const heat = new Map<string, { v: number; n: number }>();
    for (const tr of allResolved as Array<{ resolvedAt: Date | null; openedAt: Date; realizedPnl: number | null }>) {
      const { hour, weekday } = etPartsUncached((tr.resolvedAt ?? tr.openedAt).getTime());
      const k = `${weekday}-${hour}`;
      const cur = heat.get(k) ?? { v: 0, n: 0 };
      cur.v += tr.realizedPnl ?? 0;
      cur.n++;
      heat.set(k, cur);
    }
    return heat.size;
  });
  await t("heat loop, hoisted formatter", () => {
    const heat = new Map<string, { v: number; n: number }>();
    for (const tr of allResolved as Array<{ resolvedAt: Date | null; openedAt: Date; realizedPnl: number | null }>) {
      const { hour, weekday } = etPartsCached((tr.resolvedAt ?? tr.openedAt).getTime());
      const k = `${weekday}-${hour}`;
      const cur = heat.get(k) ?? { v: 0, n: 0 };
      cur.v += tr.realizedPnl ?? 0;
      cur.n++;
      heat.set(k, cur);
    }
    return heat.size;
  });

  // parity of the two implementations
  let diff = 0;
  for (const tr of allResolved as Array<{ resolvedAt: Date | null; openedAt: Date; realizedPnl: number | null }>) {
    const ms = (tr.resolvedAt ?? tr.openedAt).getTime();
    const a = etPartsUncached(ms), b = etPartsCached(ms);
    if (a.hour !== b.hour || a.weekday !== b.weekday) diff++;
  }
  console.log(`\netParts parity: differing rows=${diff} (must be 0)`);

  console.log(`\ncounts: c200Resolved=${c200Resolved.length} snapshots=${snapshots.length} allResolved=${allResolved.length} trackedWallets=${trackedWallets.length} insiderScores=${insiderScores.length}`);
  void decisionStats;
  await prisma.$disconnect();
}
main();
