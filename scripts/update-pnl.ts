/**
 * paper:update-pnl — hourly PnL refresh for open paper trades. Fetches the
 * current market price, snapshots PnL, and resolves trades whose markets
 * have resolved.
 */

import { prisma } from "../src/lib/db";
import { getAdapter } from "../src/lib/adapters";
import { getActiveRules } from "../src/lib/rules";
import { updatePaperTradePrice, resolvePaperTrade, closePaperTrade } from "../src/lib/paper";
import { fetchEventResolution } from "../src/lib/dead-market-resolution";
import { log, logError } from "../src/lib/redact";
import * as fs from "fs";
import { join } from "path";

// v41 (tuning review #12, 2026-09-01, approved): persistent 404 negative-cache.
// v44 note (tuning review #13): verified live — cache at the 24-slug cap;
// remaining "404 failures" in logs are first-time dead slugs being cached.
// Gamma purges dead/renamed slugs; remembering the last 24 lets hourly runs
// skip the doomed fetch and jump straight to event-resolution recovery.
const DEAD_SLUG_CACHE_FILE = join(__dirname, "..", "data", "dead-slug-cache.json");
const MAX_DEAD_SLUGS = 24;

async function main() {
  const adapter = getAdapter();
  const { rules } = await getActiveRules();
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
    expired = 0,
    recycled = 0;
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

  let deadSlugs: Set<string>;
  try {
    const cached = JSON.parse(fs.readFileSync(DEAD_SLUG_CACHE_FILE, "utf-8"));
    deadSlugs = new Set(Array.isArray(cached) ? cached.slice(-MAX_DEAD_SLUGS) : []);
  } catch {
    deadSlugs = new Set();
  }
  const rememberDeadSlug = (marketId: string) => {
    const slugs = [...deadSlugs];
    if (!slugs.includes(marketId)) slugs.push(marketId);
    while (slugs.length > MAX_DEAD_SLUGS) slugs.shift();
    deadSlugs = new Set(slugs);
    fs.writeFileSync(DEAD_SLUG_CACHE_FILE, JSON.stringify(slugs));
  };

  // Shared recovery for dead markets: try the parent-event resolution first;
  // only when the outcome is genuinely unavailable close positions older than
  // 24h at the last known mark — carrying them is pure drag.
  const recoverDeadMarket = async (marketId: string, trades: typeof open) => {
    const outcome = await fetchEventResolution(marketId);
    if (outcome) {
      for (const t of trades) {
        if (t.status !== "open") continue;
        await resolvePaperTrade(t.id, outcome === t.outcome);
        resolved++;
      }
      return;
    }
    const dayAgo = Date.now() - 86_400_000;
    for (const t of trades) {
      if (t.openedAt.getTime() < dayAgo) {
        await closePaperTrade(t.id, t.currentPrice, "market 404 (dead slug) >24h — expired; outcome unavailable");
        expired++;
      }
    }
  };

  for (const [marketId, trades] of [...byMarket.entries()]) {
    if (deadSlugs.has(marketId)) {
      // Cached 404 — skip the doomed fetch entirely.
      await recoverDeadMarket(marketId, trades);
      continue;
    }
    let m;
    try {
      m = await adapter.fetchMarket(marketId);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (msg.includes("404") || msg.includes("not found")) {
        rememberDeadSlug(marketId);
        await recoverDeadMarket(marketId, trades);
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

        // v29/v33 capital recycling: C-200 positions must not park capital.
        // Tier 2 (v33): hard max-age — anything open past staleExitHardHours
        // closes at last price regardless of move (v29 tier-1 never fires:
        // every position that survives 72h has already drifted ≥5%, so the
        // real drag is stuck winners on markets that never resolve).
        // Tier 1 (v29): 72h old and hasn't moved ≥ staleExitMinMove toward
        // the winning outcome (BUY-side model → win direction is price up).
        // Reuses closePaperTrade (same path as dead-market expiry) so cash
        // and realized PnL book consistently.
        if (t.botId === "BANKROLL_200") {
          const ageHours = (Date.now() - t.openedAt.getTime()) / 3_600_000;
          // Move toward the winning outcome, signed by position side. BUY (all
          // current positions, incl. NO holders): position value = the held
          // outcome's price, so a rising price IS winning — for a NO holder
          // that's noPrice rising. SELL (future-proof): winning means price
          // falls. The v29 "BUY-side only" report finding was a misread; this
          // makes the intent explicit.
          const winMove =
            t.side === "SELL"
              ? (t.entryPrice - price) / t.entryPrice
              : (price - t.entryPrice) / t.entryPrice;
          if (ageHours >= rules.staleExitHardHours) {
            await closePaperTrade(
              t.id,
              price,
              `stale ${ageHours.toFixed(0)}h ≥ ${rules.staleExitHardHours}h hard max-age — v33 capital recycling`
            );
            recycled++;
          } else if (ageHours >= rules.staleExitHours && winMove < rules.staleExitMinMove) {
            await closePaperTrade(
              t.id,
              price,
              `stale ${ageHours.toFixed(0)}h, winMove ${(winMove * 100).toFixed(1)}% < ${(rules.staleExitMinMove * 100).toFixed(0)}% — v29 capital recycling`
            );
            recycled++;
          }
        }
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
    `PnL update complete: ${updated} updated, ${resolved} resolved, ${expired} expired (dead markets), ${recycled} recycled (v29/v33 stale exit), ` +
      `${byMarket.size} markets in ${((Date.now() - startedAt) / 1000).toFixed(0)}s.`
  );
}

main()
  .catch((e) => {
    logError("paper:update-pnl FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
