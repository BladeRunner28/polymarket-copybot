/**
 * winrate-companion-read — what the dashboard's Win Rate card says, on both bases, with companions.
 * Read-only. Evidence for card `winrate-payoff-companion-reporting` (queue item 15, 2026-11-03).
 *
 * WHY THIS EXISTS. The dashboard home (src/app/page.tsx) printed "Win Rate: X% | N resolved trades"
 * from `status: 'resolved'` rows with NO isDemo filter, while the EOD report prints a win rate from
 * settled rows (`closed` + `resolved`, isDemo=0). Two different populations, one heading. On top of
 * that, neither line carried average win, average loss or ROI — the 2026-10-27 confusion (a win-rate
 * drop read as a profitability collapse when ROI was the best month on record) is exactly what that
 * gap produces.
 *
 * This script prints BOTH bases side by side, per lane, so the correction is auditable rather than
 * asserted, and so any later drift between the dashboard and the EOD report shows up as a number.
 *
 * BASIS (stated, never implied):
 *   population A "OLD dashboard" = PaperTrade.status = 'resolved' ONLY, no isDemo filter (the exact
 *                query the page ran before 2026-11-03);
 *   population B "settled"       = status IN ('closed','resolved') AND isDemo = 0 (the EOD basis);
 *   level                        = the leg (one PaperTrade row);
 *   clock                        = settlement: COALESCE(closedAt, resolvedAt), displayed as the
 *                earliest such date in the population;
 *   win                          = realizedPnl > 0; ROI = sum(realizedPnl) / sum(simulatedPositionSize).
 *
 * Read-only: no writes, no rule/sizing consumer. Run: npx tsx scripts/winrate-companion-read.ts
 */

import { prisma } from "../src/lib/db";
import { payoffSummary, payoffCompanionText, isoDate } from "../src/lib/payoff";

type Row = {
  botId: string | null;
  realizedPnl: number | null;
  simulatedPositionSize: number;
  closedAt: Date | null;
  resolvedAt: Date | null;
};

const asRows = (rows: Row[]) =>
  rows.map((t) => ({ pnl: t.realizedPnl, stake: t.simulatedPositionSize, at: t.closedAt ?? t.resolvedAt }));

async function main() {
  const select = {
    botId: true,
    realizedPnl: true,
    simulatedPositionSize: true,
    closedAt: true,
    resolvedAt: true,
  } as const;

  const oldBasis = (await prisma.paperTrade.findMany({
    where: { status: "resolved" },
    select,
  })) as Row[];

  const settled = (await prisma.paperTrade.findMany({
    where: { status: { in: ["closed", "resolved"] }, isDemo: false, realizedPnl: { not: null } },
    select,
  })) as Row[];

  const demoInOld = (await prisma.paperTrade.count({ where: { status: "resolved", isDemo: true } })) as number;

  console.log(
    `winrate-companion-read | DB prisma/dev.db | clock=COALESCE(closedAt,resolvedAt) | level=leg | as of ${new Date().toISOString()}`
  );
  console.log(
    `A) OLD dashboard basis: status='resolved' only, NO isDemo scope -> ${oldBasis.length} rows` +
      ` (of which ${demoInOld} are SEEDED DEMO rows, i.e. ${((100 * demoInOld) / Math.max(1, oldBasis.length)).toFixed(1)}% of the population)`
  );
  console.log(`B) settled basis (EOD, now the dashboard): closed+resolved, isDemo=0 -> ${settled.length} rows`);

  const settledPayoff = new Map<string, ReturnType<typeof payoffSummary>>();
  for (const lane of ["STANDARD", "BANKROLL_200"]) {
    const a = payoffSummary(asRows(oldBasis.filter((t) => t.botId === lane)));
    const b = payoffSummary(asRows(settled.filter((t) => t.botId === lane)));
    settledPayoff.set(lane, b);
    const d = b.winRate - a.winRate;
    console.log(`\n${lane}`);
    console.log(`  A old : win ${(100 * a.winRate).toFixed(1)}% | ${payoffCompanionText(a, isoDate)}`);
    console.log(`  B new : win ${(100 * b.winRate).toFixed(1)}% | ${payoffCompanionText(b, isoDate)}`);
    console.log(
      `  delta : win ${(100 * d >= 0 ? "+" : "")}${(100 * d).toFixed(1)}pp on ${b.n - a.n >= 0 ? "+" : ""}${b.n - a.n} legs` +
        ` | avg win ${b.avgWin >= 0 ? "+" : "-"}$${Math.abs(b.avgWin).toFixed(2)} vs ${a.avgWin >= 0 ? "+" : "-"}$${Math.abs(a.avgWin).toFixed(2)}` +
        ` | ROI ${b.roi >= 0 ? "+" : ""}${b.roi.toFixed(1)}% vs ${a.roi >= 0 ? "+" : ""}${a.roi.toFixed(1)}%`
    );
  }

  // Sign test, COMPUTED not asserted: do the two lanes rank the same way by win rate and by ROI?
  // If they do not, a bare rate cannot rank them — which is why the companions are welded to it.
  const std = settledPayoff.get("STANDARD")!;
  const c200 = settledPayoff.get("BANKROLL_200")!;
  const rateRank = std.winRate > c200.winRate ? "STANDARD" : "BANKROLL_200";
  const roiRank = std.roi > c200.roi ? "STANDARD" : "BANKROLL_200";
  console.log(`\nread (computed on the settled basis above, same clock and level):`);
  console.log(
    `      higher win rate -> ${rateRank} (${(100 * Math.max(std.winRate, c200.winRate)).toFixed(1)}% vs ${(100 * Math.min(std.winRate, c200.winRate)).toFixed(1)}%)`
  );
  console.log(
    `      higher ROI      -> ${roiRank} (${Math.max(std.roi, c200.roi).toFixed(1)}% vs ${Math.min(std.roi, c200.roi).toFixed(1)}%)`
  );
  console.log(
    rateRank === roiRank
      ? `      the two agree today; the companions are still the only thing that says so.`
      : `      the two DISAGREE: a bare win rate ranks these lanes the wrong way round, which is this card's defect.`
  );

  await prisma.$disconnect();
}

main().catch(async (e) => {
  console.error("winrate-companion-read FAILED:", e);
  await prisma.$disconnect();
  process.exit(1);
});
