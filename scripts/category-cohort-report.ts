/**
 * category-cohort-report — ROI by REAL market category, for any lane.
 *
 * ACCOUNTING is not defined here. It comes from src/lib/accounting.ts, the single canonical
 * definition both arms use (dedupe first leg per wallet|market|outcome, terminal statuses only,
 * cost basis = simulatedPositionSize in DOLLARS, market-clustered CIs). This script carried its
 * own copy of those rules until Phase 0b — which is exactly how the project ended up with two
 * accounting paths that disagreed with each other.
 *
 * WHY THE CLASSIFIER AND NOT ObservedTrade.marketCategory: that column looks like a category and
 * is not one — it is the first dash-segment of the event slug, and 33.1% of rows carry a QUESTION
 * word ('highest', 'which', 'next', 'will'); 'highest' alone wraps 14,879 distinct markets.
 * Grouping a book by it measures slug statistics. A first pass at this very question did that and
 * reported "weather = 28% of notional", which was really the token 'highest'.
 *
 * Categories resolve as: stored marketCategoryClass (ground truth the live lane believes, now
 * backfilled for effectively all history) -> else the live classifier -> else 'other'.
 *
 * Run:
 *   DATABASE_URL="file:./dev.db" npx tsx scripts/category-cohort-report.ts --bot STANDARD
 *   DATABASE_URL="file:./dev.db" npx tsx scripts/category-cohort-report.ts --bot STANDARD --days 90
 */
import { prisma } from "../src/lib/db";
import { classifyMarketCategory } from "../src/lib/market-category";
import { loadLaneLegs, summarise, clusterBootstrapCI, type LaneLeg } from "../src/lib/accounting";
import { log } from "../src/lib/redact";

function arg(name: string, def: string): string {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : def;
}

async function main() {
  const bot = arg("bot", "STANDARD");
  const days = Number(arg("days", "0")); // 0 = all time
  const by = arg("by", "coarse") as "coarse" | "fine";
  const since = days > 0 ? new Date(Date.now() - days * 86_400_000) : undefined;

  // canonical population + accounting
  const legs = await loadLaneLegs(bot, { since });

  // market -> question + stored class (chunked: the closed book can hold thousands of markets)
  const mids = [...new Set(legs.map((l) => l.marketId))];
  const meta = new Map<string, { q: string | null; cls: string | null }>();
  let stored = 0;
  for (let i = 0; i < mids.length; i += 800) {
    const chunk = mids.slice(i, i + 800);
    const ot = await prisma.observedTrade.findMany({
      where: { marketId: { in: chunk } },
      select: { marketId: true, marketQuestion: true, marketCategoryClass: true },
    });
    for (const o of ot) {
      if (!meta.has(o.marketId)) {
        meta.set(o.marketId, { q: o.marketQuestion ?? null, cls: o.marketCategoryClass ?? null });
      }
    }
  }

  const groups = new Map<string, LaneLeg[]>();
  for (const l of legs) {
    const m = meta.get(l.marketId);
    const resolved = classifyMarketCategory(l.marketId, m?.q ?? null);
    // stored class is coarse-only; fine always comes from the classifier
    const cat = by === "fine" ? resolved.fine : (m?.cls ?? resolved.coarse);
    if (m?.cls) stored++;
    const arr = groups.get(cat);
    if (arr) arr.push(l);
    else groups.set(cat, [l]);
  }

  const whole = summarise(legs);
  log(
    `lane ${bot}${days ? ` / last ${days}d` : " / all time"} — ${whole.legs.toLocaleString()} deduped legs, ` +
      `$${Math.round(whole.notional).toLocaleString()} notional, ROI ${whole.roi.toFixed(2)}%`
  );
  log(`accounting: src/lib/accounting.ts · grouping by ${by} · stored class for ${stored.toLocaleString()}/${legs.length.toLocaleString()} legs, classifier for the rest\n`);
  log(
    `${"category".padEnd(12)} ${"legs".padStart(6)} ${"notional".padStart(11)} ${"PnL".padStart(10)} ${"ROI".padStart(9)} ${"95% CI (mkt-clustered)".padStart(24)} ${"hold".padStart(7)} ${"share".padStart(7)}`
  );
  const ordered = [...groups.entries()].sort((a, b) => summarise(b[1]).notional - summarise(a[1]).notional);
  for (const [cat, gl] of ordered) {
    const s = summarise(gl);
    const ci = gl.length >= 5 ? clusterBootstrapCI(gl, { iterations: 1500 }) : null;
    const ciStr = ci ? `[${ci.lo.toFixed(1)}, ${ci.hi.toFixed(1)}]` : "n<5";
    const share = whole.notional ? (s.notional / whole.notional) * 100 : NaN;
    log(
      `${cat.padEnd(12)} ${String(s.legs).padStart(6)} ${("$" + Math.round(s.notional).toLocaleString()).padStart(11)} ` +
        `${("$" + Math.round(s.pnl).toLocaleString()).padStart(10)} ${(s.roi.toFixed(1) + "%").padStart(9)} ` +
        `${ciStr.padStart(24)} ${(s.medianHoldDays.toFixed(1) + "d").padStart(7)} ${(share.toFixed(1) + "%").padStart(7)}`
    );
  }
}

main()
  .catch((e) => {
    log("category-cohort-report FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
