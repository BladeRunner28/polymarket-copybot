/**
 * dedupe:opens — duplicate-open cleanup + structural unique index
 * (tuning review #22 rec 1, user-approved 2026-09-11).
 *
 * Background: the v52 option-A guard blocks new same-key duplicates, but
 * unjournaled coalesced fills stayed "unscored" and could re-book once per run
 * (5 post-guard leak pairs). The journal fix (score-trades v54) closes that.
 * This script:
 *   --report       list duplicate OPEN keys split by era (pre/post guard)
 *   --clean-leaks  close the POST-GUARD leak opens (openedAt >= 2026-09-09
 *                  09:00Z), keeping the oldest per key — genuine leaks only;
 *                  the 242 legacy pre-guard accumulations are left alone
 *                  (they are pre-v52 copy behavior, not defects; closing them
 *                  would be portfolio surgery, not cleanup)
 *   --ensure-index create the partial unique index on OPEN (botId,
 *                  walletAddress, marketId, outcome) — ONLY when the book has
 *                  zero duplicate open keys (the index cannot exist otherwise)
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/dedupe-open-copies.ts [flags]
 */

import { prisma } from "../src/lib/db";
import { closePaperTrade } from "../src/lib/paper";
import { log, logError } from "../src/lib/redact";

const GUARD_LIVE_MS = Date.UTC(2026, 8, 9, 9, 0, 0); // v52 option-A guard live ~Sep 9 10:03 CDT
const INDEX_SQL =
  'CREATE UNIQUE INDEX IF NOT EXISTS "PaperTrade_open_key_uniq" ON "PaperTrade"("botId","walletAddress","marketId","outcome") WHERE "status" = \'open\'';

interface DupKey {
  botId: string;
  walletAddress: string;
  marketId: string;
  outcome: string;
  n: number;
  oldest: number;
  newest: number;
}

async function dupKeys(): Promise<DupKey[]> {
  const rows = await prisma.$queryRawUnsafe<DupKey[]>(`
    SELECT botId, walletAddress, marketId, outcome, COUNT(*) n,
           MIN(openedAt) oldest, MAX(openedAt) newest
    FROM PaperTrade WHERE status='open'
    GROUP BY botId, walletAddress, marketId, outcome
    HAVING COUNT(*) > 1
    ORDER BY n DESC`);
  return rows;
}

async function main() {
  const args = process.argv.slice(2);
  const cleanLeaks = args.includes("--clean-leaks");
  const ensureIndex = args.includes("--ensure-index");

  const dups = await dupKeys();
  const postGuard = dups.filter((d) => Number(d.newest) >= GUARD_LIVE_MS);
  const preGuard = dups.filter((d) => Number(d.newest) < GUARD_LIVE_MS);
  log(
    `duplicate open keys: ${dups.length} total — ${postGuard.length} post-guard (leaks), ${preGuard.length} legacy (pre-v52 accumulations)`
  );
  for (const d of dups.slice(0, 8)) {
    const era = Number(d.newest) >= GUARD_LIVE_MS ? "LEAK" : "legacy";
    log(`  [${era}] ${d.botId} ${d.walletAddress.slice(0, 8)}… ${d.marketId.slice(0, 34)} ${d.outcome} ×${d.n}`);
  }

  if (cleanLeaks) {
    let closed = 0;
    for (const d of postGuard) {
      const rows = await prisma.paperTrade.findMany({
        where: { botId: d.botId, walletAddress: d.walletAddress, marketId: d.marketId, outcome: d.outcome, status: "open" },
        orderBy: { openedAt: "asc" },
      });
      // Keep the oldest; close the later leak copies at their current mark.
      for (const t of rows.slice(1)) {
        await closePaperTrade(t.id, t.currentPrice, "v54 duplicate-open cleanup (post-guard leak; journal fix prevents recurrence)");
        closed++;
        log(`  closed ${t.id.slice(0, 14)} … ${d.marketId} ${d.outcome} @ ${t.currentPrice.toFixed(3)}`);
      }
    }
    log(`clean-leaks: closed ${closed} post-guard duplicate opens.`);
  }

  if (ensureIndex) {
    const remaining = (await dupKeys()).length;
    if (remaining > 0) {
      log(`ensure-index: SKIPPED — ${remaining} duplicate open key(s) still block the unique index (legacy pre-v52 accumulations; they clear as positions resolve).`);
    } else {
      await prisma.$executeRawUnsafe(INDEX_SQL);
      log("ensure-index: PaperTrade_open_key_uniq created (duplicate opens are now structurally impossible).");
    }
  }
}

main()
  .catch((e) => {
    logError("dedupe:opens FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
