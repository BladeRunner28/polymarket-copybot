/**
 * scan:wallets — profile wallets from the latest leaderboard scan: fetch 30d
 * activity, compute scores, set track/watch/ignore status.
 * WALLET_SCAN_LIMIT caps how many wallets are profiled per run (API-friendly).
 */

import { prisma } from "../src/lib/db";
import { getAdapter } from "../src/lib/adapters";
import { getActiveRules } from "../src/lib/rules";
import { scoreWallet, walletStatus } from "../src/lib/scoring/wallet";
import { log, logError } from "../src/lib/redact";
import { sendDiscord } from "../src/lib/discord";
import * as fs from "fs";
import { join } from "path";

const SCAN_LIMIT = Number(process.env.WALLET_SCAN_LIMIT ?? 25);
const LOOKBACK_DAYS = 30;

// 2026-09-20 tuning review #31 rec 3 (user-approved): a partial profile run used
// to be indistinguishable from a clean one — 6 lifetime occurrences, each logging
// a normal completion line, each silently leaving N wallets unprofiled until the
// next cycle. Two artifacts: an append-only event log (one row per partial, so the
// EOD can count a window) and a state file (the latest run, partial or not, so the
// EOD line can print the real coverage). The Discord ping is rate-limited to 6h so
// a transient connector fault cannot spam.
const SCAN_STATE_FILE = join(__dirname, "..", "data", "scan-wallets-state.json");
const SCAN_PARTIALS_FILE = join(__dirname, "..", "data", "scan-partials.jsonl");
const PARTIAL_ALERT_EVERY_MS = 6 * 3_600_000;

async function main() {
  const adapter = getAdapter();
  const { rules } = await getActiveRules();

  // Profile the least-recently-scanned wallets first. Demo wallets are never
  // profiled against the live API (their addresses don't exist on-chain).
  const wallets = await prisma.walletProfile.findMany({
    where: adapter.isDemo ? {} : { isDemo: false },
    orderBy: [{ lastScannedAt: { sort: "asc", nulls: "first" } }, { sourceRank: "asc" }],
    take: SCAN_LIMIT,
  });
  if (wallets.length === 0) {
    log("No wallets to scan. Run `npm run scan:leaderboard` first.");
    return;
  }

  log(`Profiling ${wallets.length} wallets (${LOOKBACK_DAYS}d activity)${adapter.isDemo ? " [DEMO DATA]" : ""}…`);
  let profiled = 0;
  const failures: string[] = [];

  for (const w of wallets) {
    try {
      // TR-17 (tuning review #15, approved): retry-once after a short pause —
      // the 02:11 all-fetch data-api failure was transient (self-recovered
      // next run); one in-run retry avoids burning the whole hourly cycle.
      let trades;
      try {
        trades = await adapter.fetchWalletActivity(w.address, LOOKBACK_DAYS);
      } catch {
        await new Promise((r) => setTimeout(r, 5000));
        trades = await adapter.fetchWalletActivity(w.address, LOOKBACK_DAYS);
      }
      const score = scoreWallet(trades, rules);
      const { status, reason } = walletStatus(score, rules);
      await prisma.walletProfile.update({
        where: { id: w.id },
        data: {
          status,
          roi30d: score.roi30d,
          consistencyScore: score.consistencyScore,
          copyabilityScore: score.copyabilityScore,
          oneHitWonderPenalty: score.oneHitWonderPenalty,
          globalScore: score.globalScore,
          bestCategory: score.bestCategory,
          categoryStrengthsJson: JSON.stringify(score.categoryStrengths),
          averageTradeSize: score.averageTradeSize,
          tradeCount30d: score.tradeCount30d,
          resolvedTradeCount30d: score.resolvedTradeCount30d,
          winRate30d: score.winRate30d,
          averageLiquidity: score.averageLiquidity,
          averageSpread: score.averageSpread,
          averageEntryTiming: score.averageEntryTiming,
          copyabilityNotes: `${reason}. ${score.copyabilityNotes}`,
          riskNotes: score.riskNotes,
          lastScannedAt: new Date(),
        },
      });
      profiled++;
    } catch (e) {
      failures.push(`${w.address}: ${e instanceof Error ? e.message : e}`);
    }
  }

  // Cap tracked wallets: keep only the strongest MAX_TRACKED as `track`,
  // demote the rest to `watch` (prevents monitor/score pipeline flooding).
  const MAX_TRACKED = Number(process.env.MAX_TRACKED_WALLETS ?? 25);
  const tracked = await prisma.walletProfile.findMany({
    where: { status: "track", ...(adapter.isDemo ? {} : { isDemo: false }) },
    orderBy: { globalScore: "desc" },
  });
  if (tracked.length > MAX_TRACKED) {
    const demote = tracked.slice(MAX_TRACKED);
    await prisma.walletProfile.updateMany({
      where: { id: { in: demote.map((w) => w.id) } },
      data: { status: "watch" },
    });
    log(`Tracked-wallet cap: kept top ${MAX_TRACKED}, demoted ${demote.length} to watch.`);
  }

  // v33 (tuning review #9): demo wallets are inert in live mode (monitor only
  // watches isDemo:false) but are excluded from the cap query above, so stale
  // demo `track` rows can accumulate and inflate the tracked count (observed:
  // 31 marked track vs 25 cap = 25 live + 6 demo). Demote them so the count is
  // truthful. Non-destructive — data is retained, just no longer "tracked".
  if (!adapter.isDemo) {
    const demoDemoted = await prisma.walletProfile.updateMany({
      where: { status: "track", isDemo: true },
      data: { status: "watch" },
    });
    if (demoDemoted.count > 0) {
      log(`Demo-track cleanup: demoted ${demoDemoted.count} demo wallets to watch.`);
    }
  }

  if (failures.length) {
    logError(`Failures (${failures.length}):\n` + failures.slice(0, 5).join("\n"));
    if (profiled === 0) {
      throw new Error("All wallet profile fetches failed — see errors above.");
    }
  }
  // Completion line last so `tail -N` log capture always includes it.
  log(`Wallet scan complete: ${profiled}/${wallets.length} profiled.`);

  // rec 3: the partial condition is the whole point of this block — it is
  // emitted AFTER the completion line so the runner's `tail -6` keeps it.
  const partial = profiled < wallets.length;
  const nowIso = new Date().toISOString();
  try {
    if (partial) {
      log(
        `[SCAN PARTIAL] profiled ${profiled}/${wallets.length} — ${wallets.length - profiled} wallet(s) NOT profiled this run ` +
          `(first failure: ${failures[0] ?? "unknown"})`
      );
      fs.appendFileSync(
        SCAN_PARTIALS_FILE,
        JSON.stringify({ ts: nowIso, profiled, target: wallets.length, failures: failures.slice(0, 5) }) + "\n"
      );
    }
    let prev: { lastAlertAtMs?: number; lastPartialAt?: string | null } = {};
    try {
      prev = JSON.parse(fs.readFileSync(SCAN_STATE_FILE, "utf-8"));
    } catch {
      prev = {};
    }
    const lastAlertAtMs = partial ? prev.lastAlertAtMs ?? 0 : prev.lastAlertAtMs;
    fs.writeFileSync(
      SCAN_STATE_FILE,
      JSON.stringify(
        {
          lastRunAt: nowIso,
          profiled,
          target: wallets.length,
          partial,
          failures: failures.slice(0, 5),
          lastPartialAt: partial ? nowIso : prev.lastPartialAt ?? null,
          lastAlertAtMs,
        },
        null,
        2
      )
    );
    if (partial && Date.now() - (lastAlertAtMs ?? 0) > PARTIAL_ALERT_EVERY_MS) {
      await sendDiscord(
        [
          "⚠️ **Wallet scan PARTIAL** _(paper only)_",
          `**Profiled:** ${profiled}/${wallets.length} — ${wallets.length - profiled} wallet(s) skipped this cycle`,
          `**First failure:** ${(failures[0] ?? "unknown").slice(0, 180)}`,
          "_Those wallets keep their last scores until the next hourly run; repeated partials mean an API or DB fault, not a quiet cycle._",
        ].join("\n")
      );
      const state = JSON.parse(fs.readFileSync(SCAN_STATE_FILE, "utf-8"));
      state.lastAlertAtMs = Date.now();
      fs.writeFileSync(SCAN_STATE_FILE, JSON.stringify(state, null, 2));
    }
  } catch (e) {
    logError(`[SCAN PARTIAL] reporting failed: ${e instanceof Error ? e.message : e}`);
  }
}

main()
  .catch((e) => {
    logError("scan:wallets FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
