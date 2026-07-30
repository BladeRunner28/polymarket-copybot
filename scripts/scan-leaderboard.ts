/**
 * scan:leaderboard — pull the leaderboard (top 500 by default) and upsert
 * wallet stubs. Fails loudly on API errors; never fakes data.
 */

import { prisma } from "../src/lib/db";
import { getAdapter } from "../src/lib/adapters";
import { log, logError } from "../src/lib/redact";

const LIMIT = Number(process.env.LEADERBOARD_LIMIT ?? 500);
const LOOKBACK_DAYS = 30;

async function main() {
  const adapter = getAdapter();
  log(`Scanning ${adapter.source} leaderboard (top ${LIMIT}, ${LOOKBACK_DAYS}d window)${adapter.isDemo ? " [DEMO DATA]" : ""}…`);

  const entries = await adapter.fetchLeaderboard(LIMIT);
  if (entries.length === 0) {
    throw new Error("Leaderboard returned 0 entries — refusing to continue with empty data.");
  }

  await prisma.leaderboardScan.create({
    data: {
      source: adapter.source,
      walletCount: entries.length,
      lookbackDays: LOOKBACK_DAYS,
      rawSummaryJson: JSON.stringify({
        top10: entries.slice(0, 10).map((e) => ({ address: e.address, label: e.label, pnl: e.pnl })),
        fetchedAt: new Date().toISOString(),
      }),
    },
  });

  let created = 0;
  let updated = 0;
  for (const e of entries) {
    const existing = await prisma.walletProfile.findUnique({ where: { address: e.address } });
    if (existing) {
      await prisma.walletProfile.update({
        where: { address: e.address },
        data: { sourceRank: e.rank, label: e.label ?? existing.label },
      });
      updated++;
    } else {
      await prisma.walletProfile.create({
        data: {
          address: e.address,
          label: e.label,
          sourceRank: e.rank,
          status: "watch",
          isDemo: adapter.isDemo,
        },
      });
      created++;
    }
  }
  log(`Leaderboard scan complete: ${entries.length} wallets (${created} new, ${updated} updated).`);
}

main()
  .catch((e) => {
    logError("scan:leaderboard FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
