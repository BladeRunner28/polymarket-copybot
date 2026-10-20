/**
 * category-cohort-report — ROI by REAL market category, for any lane.
 *
 * WHY THIS EXISTS: ObservedTrade.marketCategory looks like a category and is not one. It is the
 * first dash-segment of the event slug, and 33.1% of rows carry a QUESTION word ('highest',
 * 'which', 'next', 'will') rather than a subject; 'highest' alone wraps 14,879 distinct markets.
 * Grouping a book by that column measures slug statistics. A first pass at the ML cohort question
 * did exactly that and reported "weather = 28% of notional", which was really the token 'highest'.
 *
 * This calls the same classifier the live scoring path uses (src/lib/market-category.ts), which is
 * itself a parity-checked port (scripts/verify-market-category.ts), so a cohort claim made here
 * matches what the bot would believe.
 *
 * ACCOUNTING (must match scripts/profit-band-report.py so the two arms are comparable):
 *   - dedupe the first leg per (bot | wallet | market | outcome)
 *   - status IN ('closed','resolved')  [closed = early exit, resolved = natural; PnL ORs both]
 *   - isDemo = 0
 *   - COST BASIS = simulatedPositionSize, which is DOLLARS. Multiplying it by entryPrice
 *     understates cost and inflates ROI — that bug produced a +407% cheap-band read once.
 *   - PnL = COALESCE(realizedPnl, 0)
 *
 * Run:
 *   DATABASE_URL="file:./dev.db" npx tsx scripts/category-cohort-report.ts --bot STANDARD
 *   DATABASE_URL="file:./dev.db" npx tsx scripts/category-cohort-report.ts --bot STANDARD --days 90
 */
import { prisma } from "../src/lib/db";
import { classifyMarketCategory } from "../src/lib/market-category";
import { log } from "../src/lib/redact";

function arg(name: string, def: string): string {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : def;
}

async function main() {
  const bot = arg("bot", "STANDARD");
  const days = Number(arg("days", "0")); // 0 = all time
  const since = days > 0 ? new Date(Date.now() - days * 86_400_000) : undefined;

  const rows = await prisma.paperTrade.findMany({
    where: {
      botId: bot,
      isDemo: false,
      status: { in: ["closed", "resolved"] },
      ...(since ? { openedAt: { gte: since } } : {}),
    },
    select: {
      walletAddress: true,
      marketId: true,
      outcome: true,
      simulatedPositionSize: true,
      realizedPnl: true,
      openedAt: true,
      resolvedAt: true,
      closedAt: true,
    },
    orderBy: { openedAt: "asc" },
  });

  // dedupe first leg per bot|wallet|market|outcome
  const seen = new Set<string>();
  const legs: typeof rows = [];
  for (const r of rows) {
    const k = `${r.walletAddress}|${r.marketId}|${r.outcome}`;
    if (seen.has(k)) continue;
    seen.add(k);
    legs.push(r);
  }

  // market -> question + stored class (stored class is non-null only from ~2026-W39 onward)
  const mids = [...new Set(legs.map((l) => l.marketId))];
  const ot = await prisma.observedTrade.findMany({
    where: { marketId: { in: mids } },
    select: { marketId: true, marketQuestion: true, marketCategoryClass: true },
  });
  const meta = new Map<string, { q: string | null; cls: string | null }>();
  for (const o of ot) {
    if (!meta.has(o.marketId)) {
      meta.set(o.marketId, { q: o.marketQuestion ?? null, cls: o.marketCategoryClass ?? null });
    }
  }

  type Agg = { n: number; cost: number; pnl: number; holds: number[]; stored: number };
  const agg = new Map<string, Agg>();
  let unclassified = 0;
  for (const l of legs) {
    const m = meta.get(l.marketId);
    // stored class wins (it is what the live lane believes); else classify from slug + question
    const coarse = m?.cls ?? classifyMarketCategory(l.marketId, m?.q ?? null).coarse;
    if (!coarse || coarse === "other") unclassified++;
    const a = agg.get(coarse) ?? { n: 0, cost: 0, pnl: 0, holds: [], stored: 0 };
    a.n += 1;
    a.cost += l.simulatedPositionSize ?? 0;
    a.pnl += l.realizedPnl ?? 0;
    if (m?.cls) a.stored += 1;
    const done = l.resolvedAt ?? l.closedAt;
    if (done && l.openedAt) a.holds.push((done.getTime() - l.openedAt.getTime()) / 86_400_000);
    agg.set(coarse, a);
  }

  const med = (v: number[]) => {
    if (!v.length) return NaN;
    const s = [...v].sort((x, y) => x - y);
    return s[Math.floor(s.length / 2)];
  };

  const totalCost = [...agg.values()].reduce((s, a) => s + a.cost, 0);
  log(`lane ${bot}${days ? ` / last ${days}d` : " / all time"} — ${legs.length.toLocaleString()} deduped closed legs, $${totalCost.toLocaleString()}`);
  log(`classified via stored marketCategoryClass: ${[...agg.values()].reduce((s, a) => s + a.stored, 0).toLocaleString()} of ${legs.length.toLocaleString()}`);
  log("");
  log(`${"category".padEnd(12)} ${"legs".padStart(6)} ${"notional".padStart(11)} ${"PnL".padStart(10)} ${"ROI".padStart(9)} ${"medhold".padStart(8)} ${"share".padStart(7)}`);
  for (const [cat, a] of [...agg.entries()].sort((x, y) => y[1].cost - x[1].cost)) {
    const roi = a.cost ? (a.pnl / a.cost) * 100 : NaN;
    const share = totalCost ? (a.cost / totalCost) * 100 : NaN;
    log(
      `${cat.padEnd(12)} ${String(a.n).padStart(6)} ${("$" + Math.round(a.cost).toLocaleString()).padStart(11)} ` +
        `${("$" + Math.round(a.pnl).toLocaleString()).padStart(10)} ${(roi.toFixed(1) + "%").padStart(9)} ` +
        `${(med(a.holds).toFixed(1) + "d").padStart(8)} ${(share.toFixed(1) + "%").padStart(7)}`
    );
  }
  log("");
  log(`'other' / unclassified share of legs: ${unclassified.toLocaleString()} of ${legs.length.toLocaleString()} = ${((unclassified / legs.length) * 100).toFixed(1)}%`);
}

main()
  .catch((e) => {
    log("category-cohort-report FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
