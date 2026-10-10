/**
 * _perf-variants.ts — A/B the /analytics biggest read: wide `include` vs the
 * narrow `select` of only the fields the page consumes. Read-only.
 */
import { prisma } from "@/lib/db";

const WHERE = { status: { in: ["closed", "resolved"] as string[] }, realizedPnl: { not: null } };

async function bench(label: string, fn: () => Promise<unknown>, runs = 3) {
  const times: number[] = [];
  let rows = 0;
  let bytes = 0;
  for (let i = 0; i < runs; i++) {
    const t0 = performance.now();
    const r = await fn();
    times.push(performance.now() - t0);
    rows = Array.isArray(r) ? r.length : 0;
    bytes = JSON.stringify(r).length;
  }
  times.sort((a, b) => a - b);
  console.log(
    `${label.padEnd(26)} median=${times[Math.floor(runs / 2)].toFixed(0).padStart(5)}ms  min=${times[0].toFixed(0).padStart(5)}ms  rows=${rows}  jsonMB=${(bytes / 1e6).toFixed(1)}`,
  );
  return rows;
}

async function main() {
  // warm
  await prisma.paperTrade.findMany({ where: WHERE, select: { id: true }, take: 1 });

  await bench("WIDE include (current)", () =>
    prisma.paperTrade.findMany({
      where: WHERE,
      include: { decision: { include: { observedTrade: true } } },
    }),
  );

  await bench("include->select observedTrade", () =>
    prisma.paperTrade.findMany({
      where: WHERE,
      include: { decision: { select: { ruleSetVersion: true, observedTrade: true } } },
    }),
  );

  await bench("NARROW select (candidate)", () =>
    prisma.paperTrade.findMany({
      where: WHERE,
      select: {
        realizedPnl: true,
        resolvedAt: true,
        openedAt: true,
        venue: true,
        walletAddress: true,
        decision: {
          select: { ruleSetVersion: true, observedTrade: { select: { marketQuestion: true } } },
        },
      },
    }),
  );

  await bench("scalar-only (no joins)", () =>
    prisma.paperTrade.findMany({
      where: WHERE,
      select: { realizedPnl: true, resolvedAt: true, openedAt: true, venue: true, walletAddress: true },
    }),
  );

  await prisma.$disconnect();
}
main().catch((e) => {
  console.error(e);
  process.exit(1);
});
