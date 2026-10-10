/**
 * _perf-analytics.ts — measurement harness for the /analytics page data path.
 *
 * Read-only. Reproduces exactly the reads src/app/analytics/page.tsx issues and
 * times each one, plus each per-row compute pass, so the page's 2.6-3.4s TTFB
 * can be attributed. Run with the main tree's dev.db:
 *   DATABASE_URL="file:/Users/xsnyde2/polymarket-copybot/prisma/dev.db" \
 *     /Users/xsnyde2/polymarket-copybot/node_modules/.bin/tsx _perf-analytics.ts
 */
import { prisma } from "@/lib/db";
import { dailyPnlSeries } from "@/lib/pnl-rollup";
import { copyDecisions, decisionCounts, reviewedDecisions } from "@/lib/decision-aggregates";
import { normalizeOutcomeLabel } from "@/lib/resolution";
import { researchCategoryFor } from "@/lib/research-categories";
import { readFileSync } from "fs";
import { join } from "path";

const ET = "America/New_York";
const ET_FMT = new Intl.DateTimeFormat("en-US", {
  timeZone: ET,
  hour: "numeric",
  weekday: "short",
  hour12: false,
});
const WD_MAP: Record<string, number> = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
function etParts(ms: number): { hour: number; weekday: number } {
  const parts = ET_FMT.formatToParts(new Date(ms));
  let hour = 0;
  let weekday = 0;
  for (const p of parts) {
    if (p.type === "hour") hour = parseInt(p.value, 10) % 24;
    if (p.type === "weekday") weekday = WD_MAP[p.value] ?? 0;
  }
  return { hour, weekday };
}
const dayKey = (d: Date) => d.toISOString().slice(0, 10);

async function timed<T>(label: string, fn: () => Promise<T>): Promise<T> {
  const t0 = performance.now();
  const v = await fn();
  const ms = performance.now() - t0;
  console.log(`QUERY  ${label.padEnd(28)} ${ms.toFixed(0).padStart(6)} ms`);
  return v;
}

function timeSync(label: string, fn: () => void) {
  const t0 = performance.now();
  fn();
  const ms = performance.now() - t0;
  console.log(`COMPUTE ${label.padEnd(27)} ${ms.toFixed(0).padStart(6)} ms`);
}

async function main() {
  const wall0 = performance.now();

  // ---- reads, in the page's order/shape ----
  const c200Resolved = await timed("c200Resolved", () =>
    prisma.paperTrade.findMany({
      where: { botId: "BANKROLL_200", status: { in: ["closed", "resolved"] }, realizedPnl: { not: null } },
      select: { realizedPnl: true, resolvedAt: true, openedAt: true },
    }),
  );
  const snapshots = await timed("dailyPnlSeries", () => dailyPnlSeries());
  const decisionStats = await timed("decisionCounts+reviewed+copies", async () => {
    const [counts, reviewed, copies] = await Promise.all([decisionCounts(), reviewedDecisions(), copyDecisions()]);
    return { counts, reviewed, copies };
  });
  const allResolved = await timed("allResolved(joined)", () =>
    prisma.paperTrade.findMany({
      where: { status: { in: ["closed", "resolved"] }, realizedPnl: { not: null } },
      include: { decision: { include: { observedTrade: true } } },
    }),
  );
  const trackedWallets = await timed("trackedWallets", () =>
    prisma.walletProfile.findMany({ where: { status: "track" }, select: { address: true, globalScore: true } }),
  );
  const insiderScores = await timed("insiderScores", () =>
    prisma.walletInsiderScore.findMany({ select: { walletAddress: true, flagged: true, watch: true } }),
  );
  const cal = await timed("calibration json", async () =>
    JSON.parse(readFileSync(join(process.cwd(), "data", "calibration-analysis.json"), "utf8")),
  );
  const baselineCsv = await timed("baseline csv", async () =>
    readFileSync(join(process.cwd(), "data", "polymarket-calibration-baseline.csv"), "utf8"),
  );
  console.log(`--- rows: allResolved=${allResolved.length} c200=${c200Resolved.length} reviewed=${decisionStats.reviewed.length} copies=${decisionStats.copies.length} rollup=${snapshots.length}`);

  const t0 = performance.now();

  timeSync("dailyMap+bars", () => {
    const dailyMap = new Map<string, number>();
    for (const t of c200Resolved) {
      const d = dayKey(t.resolvedAt ?? t.openedAt);
      dailyMap.set(d, (dailyMap.get(d) ?? 0) + (t.realizedPnl ?? 0));
    }
    void [...dailyMap.entries()].sort((a, b) => a[0].localeCompare(b[0])).slice(-21);
  });

  timeSync("eqByBot", () => {
    const eqByBot = new Map<string, { day: string; cum: number }[]>();
    for (const s of snapshots) {
      const arr = eqByBot.get(s.botId) ?? [];
      const cum = arr.length ? arr[arr.length - 1].cum + s.total_pnl : s.total_pnl;
      arr.push({ day: s.day, cum });
      eqByBot.set(s.botId, arr);
    }
  });

  timeSync("benchSeries", () => {
    const HYP = 10;
    const benchSeries = new Map<string, { day: string; pnl: number }[]>();
    const pushB = (label: string, day: string, pnl: number) => {
      const arr = benchSeries.get(label) ?? [];
      arr.push({ day, pnl });
      benchSeries.set(label, arr);
    };
    for (const d of decisionStats.reviewed) {
      const day = dayKey(d.createdAt);
      const won = normalizeOutcomeLabel(d.finalOutcome) === normalizeOutcomeLabel(d.outcome);
      const entry = d.detectedPrice;
      const hypo = HYP * (won ? 1 - entry : -entry);
      pushB("Blind copy", day, hypo);
      if (d.decision === "watchlist") pushB("Watchlist (hypo)", day, hypo);
      else if (d.decision === "skip") pushB("Skipped (hypo)", day, hypo);
    }
    for (const c of decisionStats.copies) {
      if (c.realizedPnl !== null) pushB("Bot (actual)", dayKey(c.createdAt), c.realizedPnl);
    }
    void [...benchSeries.entries()].map(([, rows]) => rows.sort((a, b) => a.day.localeCompare(b.day)));
  });

  timeSync("heatmap(etParts)", () => {
    const heat = new Map<string, { v: number; n: number }>();
    for (const t of allResolved) {
      const ms = (t.resolvedAt ?? t.openedAt).getTime();
      const { hour, weekday } = etParts(ms);
      const k = `${weekday}-${hour}`;
      const cur = heat.get(k) ?? { v: 0, n: 0 };
      cur.v += t.realizedPnl ?? 0;
      cur.n++;
      heat.set(k, cur);
    }
  });

  timeSync("cat/venue/version", () => {
    const byCat = new Map<string, number>();
    for (const t of allResolved) {
      const q = t.decision?.observedTrade?.marketQuestion;
      const cat = researchCategoryFor(q ?? null) ?? "uncategorized";
      byCat.set(cat, (byCat.get(cat) ?? 0) + (t.realizedPnl ?? 0));
    }
    const byVenue = new Map<string, number>();
    for (const t of allResolved) {
      const v = t.venue ?? "Polymarket";
      byVenue.set(v, (byVenue.get(v) ?? 0) + (t.realizedPnl ?? 0));
    }
    const byVersion = new Map<string, number>();
    for (const t of allResolved) {
      const v = `v${t.decision?.ruleSetVersion ?? "?"}`;
      byVersion.set(v, (byVersion.get(v) ?? 0) + (t.realizedPnl ?? 0));
    }
  });

  timeSync("wallet maps", () => {
    const winByWallet = new Map<string, number>();
    for (const t of allResolved) {
      const won = (t.realizedPnl ?? 0) > 0 ? 1 : 0;
      winByWallet.set(t.walletAddress, (winByWallet.get(t.walletAddress) ?? 0) + won);
    }
    const countByWallet = new Map<string, number>();
    for (const t of allResolved) {
      countByWallet.set(t.walletAddress, (countByWallet.get(t.walletAddress) ?? 0) + 1);
    }
  });

  const walletStats = await timed("walletStats groupBy", () =>
    prisma.paperTrade.groupBy({
      by: ["walletAddress"],
      where: { status: { in: ["closed", "resolved"] }, realizedPnl: { not: null } },
      _sum: { realizedPnl: true },
      _count: true,
    }),
  );
  void walletStats;

  console.log(`COMPUTE all-passes total       ${(performance.now() - t0).toFixed(0).padStart(6)} ms`);
  void cal;
  void baselineCsv;
  void trackedWallets;
  void insiderScores;
  console.log(`TOTAL data-path (reads+compute) ${(performance.now() - wall0).toFixed(0).padStart(6)} ms`);
  await prisma.$disconnect();
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
