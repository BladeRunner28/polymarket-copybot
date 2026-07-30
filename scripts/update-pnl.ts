/**
 * paper:update-pnl — hourly PnL refresh for open paper trades. Fetches the
 * current market price, snapshots PnL, and resolves trades whose markets
 * have resolved.
 */

import { prisma } from "../src/lib/db";
import { getAdapter } from "../src/lib/adapters";
import { updatePaperTradePrice, resolvePaperTrade, closePaperTrade } from "../src/lib/paper";
import { log, logError } from "../src/lib/redact";

async function main() {
  const adapter = getAdapter();
  // In live mode, only update live trades; demo markets don't exist on-chain.
  const open = await prisma.paperTrade.findMany({
    where: adapter.isDemo ? { status: "open" } : { status: "open", isDemo: false },
  });
  if (open.length === 0) {
    log("No open paper trades.");
    return;
  }

  log(`Updating PnL for ${open.length} open paper trades…`);
  const startedAt = Date.now();
  let updated = 0,
    resolved = 0,
    expired = 0;
  const failures: string[] = [];

  // Dedupe: one market fetch per distinct slug (thousands of positions often
  // span far fewer markets), then apply the result to every trade in it.
  const byMarket = new Map<string, typeof open>();
  for (const t of open) {
    const list = byMarket.get(t.marketId) ?? [];
    list.push(t);
    byMarket.set(t.marketId, list);
  }
  log(`${byMarket.size} distinct markets to fetch.`);

  for (const [marketId, trades] of [...byMarket.entries()]) {
    let m;
    try {
      m = await adapter.fetchMarket(marketId);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      // Dead market (404): close positions older than 24h at last known price —
      // the slug will never resolve via the API, so carrying them is pure drag.
      if (msg.includes("404") || msg.includes("not found")) {
        const dayAgo = Date.now() - 86_400_000;
        for (const t of trades) {
          if (t.openedAt.getTime() < dayAgo) {
            await closePaperTrade(t.id, t.currentPrice, "market 404 (dead slug) >24h — expired");
            expired++;
          }
        }
      }
      failures.push(`${marketId}: ${msg}`);
      continue;
    }
    for (const t of trades) {
      try {
        if (m.resolved && m.winningOutcome) {
          await resolvePaperTrade(t.id, m.winningOutcome === t.outcome);
          resolved++;
          continue;
        }
        const price = t.outcome === "NO" ? m.noPrice : m.yesPrice;
        if (price === undefined) {
          failures.push(`${marketId}: no price available`);
          continue;
        }
        await updatePaperTradePrice(t.id, price);
        updated++;
      } catch (e) {
        failures.push(`${marketId}: ${e instanceof Error ? e.message : e}`);
      }
    }
  }

  if (failures.length) {
    logError(`Failures (${failures.length}):\n` + failures.slice(0, 5).join("\n"));
    if (updated === 0 && resolved === 0) {
      throw new Error("All PnL updates failed — see errors above.");
    }
  }
  // Completion line last so `tail -N` log capture always includes it.
  log(
    `PnL update complete: ${updated} updated, ${resolved} resolved, ${expired} expired (dead markets), ` +
      `${byMarket.size} markets in ${((Date.now() - startedAt) / 1000).toFixed(0)}s.`
  );
}

main()
  .catch((e) => {
    logError("paper:update-pnl FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
