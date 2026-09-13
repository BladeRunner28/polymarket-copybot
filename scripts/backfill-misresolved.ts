/**
 * backfill:misresolved — correct the paper trades that were booked as losses
 * only because the resolver guessed YES/NO on a label-named market.
 *
 * The bug (fixed in src/lib/resolution.ts + the adapter): resolution was
 * `winningOutcome = yesPrice > 0.5 ? "YES" : "NO"` compared against the trade's
 * own token label, so every "Dynasty" / "Under" / "9z" / "Team Liquid" position
 * resolved to a full-stake loss. Independent audit (scripts/audit-misresolved-trades.py,
 * keyless CLOB token/winner data): 70 phantom losses, −$828.38 booked where
 * +$942.34 was owed.
 *
 * Usage:
 *   npx tsx scripts/backfill-misresolved.ts                 # dry run (default)
 *   npx tsx scripts/backfill-misresolved.ts --apply         # write + dump backup
 *   npx tsx scripts/backfill-misresolved.ts --verify-binary-sample=40
 *
 * Deltas mirror resolvePaperTrade's bookkeeping exactly:
 *   booked loss:    realizedPnl += −size,  cashBalance += 0
 *   corrected win:  realizedPnl += pnl,    cashBalance += size + pnl = size/entry
 * so both deltas equal `size/entry` and are derived from the stored `realizedPnl`
 * rather than assumed.
 *
 * Read-only unless --apply. BACKUP: --apply dumps every affected row to
 * data/backfill-misresolved-<date>.json before touching anything.
 */

import * as fs from "fs";
import { join } from "path";
import { prisma } from "../src/lib/db";
import { getAdapter } from "../src/lib/adapters";
import { computePnl, resolvePaperTrade } from "../src/lib/paper";
import { didOutcomeWin, normalizeOutcomeLabel } from "../src/lib/resolution";
import { fetchEventResolution, fetchWinningLabelViaClob } from "../src/lib/dead-market-resolution";
import { log, logError } from "../src/lib/redact";

const APPLY = process.argv.includes("--apply");
const sampleArg = process.argv.find((a) => a.startsWith("--verify-binary-sample="));
const BINARY_SAMPLE = sampleArg ? Number(sampleArg.split("=")[1]) : 40;
const BOTS_WITH_BANKROLL = new Set(["BANKROLL_200"]);

// --dump=<path>: write the fix list (both dry-run and apply) so an independent
// implementation can be diffed against it row for row.
const dumpArg = process.argv.find((a) => a.startsWith("--dump="));
const DUMP_PATH = dumpArg ? dumpArg.split("=")[1] : null;

type Row = {
  id: string;
  botId: string;
  outcome: string;
  entryPrice: number;
  size: number;
  realizedPnl: number | null;
  status: string;
  resolvedAt: Date | null;
  marketId: string;
  conditionId: string | null;
};

type Fix = {
  row: Row;
  winnerLabel: string;
  correctedPnl: number;
  delta: number;
};

async function main() {
  const adapter = getAdapter();

  const rows = (await prisma.paperTrade.findMany({
    where: { status: "resolved" },
    select: {
      id: true,
      botId: true,
      outcome: true,
      entryPrice: true,
      simulatedPositionSize: true,
      realizedPnl: true,
      status: true,
      resolvedAt: true,
      decision: { select: { observedTrade: { select: { marketId: true, conditionId: true } } } },
    },
  })) as unknown as Array<{
    id: string;
    botId: string;
    outcome: string;
    entryPrice: number;
    simulatedPositionSize: number;
    realizedPnl: number | null;
    status: string;
    resolvedAt: Date | null;
    decision: { observedTrade: { marketId: string; conditionId: string | null } } | null;
  }>;

  log(`backfill:misresolved — ${rows.length} resolved trades to re-check (${APPLY ? "APPLY" : "dry run"})`);

  // Group by the label this copy bought, so we fetch each market once.
  const byMarket = new Map<string, Row[]>();
  for (const r of rows) {
    const marketId = r.decision?.observedTrade?.marketId ?? "";
    const key = marketId || `condition:${r.decision?.observedTrade?.conditionId ?? "unknown"}`;
    const list = byMarket.get(key) ?? [];
    list.push({
      id: r.id,
      botId: r.botId,
      outcome: r.outcome,
      entryPrice: r.entryPrice,
      size: r.simulatedPositionSize,
      realizedPnl: r.realizedPnl,
      status: r.status,
      resolvedAt: r.resolvedAt,
      marketId,
      conditionId: r.decision?.observedTrade?.conditionId ?? null,
    });
    byMarket.set(key, list);
  }

  const fixes: Fix[] = [];
  const undeterminable: Array<{ row: Row; reason: string }> = [];
  const unchanged = { correct: 0, alreadyRight: 0 };
  let marketsFetched = 0;
  const routeCounts = new Map<string, number>();
  let marketsUnavailable = 0;
  const binaryMarketsSeen: string[] = [];

  for (const [key, trades] of byMarket) {
    let winningLabel: string | undefined;
    let yesPrice: number | undefined;
    let labels: string[] | undefined;
    let source = "none";

    // Resolution routes, in order of preference. Gamma's /markets?slug purges
    // sports/daily markets once resolved, so for those the parent-event route
    // and finally the CLOB-by-conditionId route carry the answer.
    if (trades[0].marketId) {
      try {
        const m = await adapter.fetchMarket(trades[0].marketId);
        if (m.resolved) {
          winningLabel = m.winningLabel ?? m.winningOutcome;
          yesPrice = m.yesPrice;
          labels = m.outcomeLabels;
          source = labels ? "gamma-slug(labels)" : "gamma-slug(price)";
        }
      } catch {
        /* fall through to the event route */
      }
    }
    if (!winningLabel && trades[0].marketId) {
      const ev = await fetchEventResolution(trades[0].marketId).catch(() => null);
      if (ev) {
        winningLabel = ev;
        source = "gamma-event";
      }
    }
    if (!winningLabel) {
      const clob = await fetchWinningLabelViaClob(trades[0].conditionId).catch(() => null);
      if (clob) {
        winningLabel = clob;
        source = "clob-conditionId";
      }
    }
    if (winningLabel) {
      marketsFetched++;
      routeCounts.set(source, (routeCounts.get(source) ?? 0) + 1);
      const looksBinary = !labels || labels.every((l) => normalizeOutcomeLabel(l) === "YES" || normalizeOutcomeLabel(l) === "NO");
      if (looksBinary) binaryMarketsSeen.push(key);
    } else {
      marketsUnavailable++;
    }

    for (const row of trades) {
      const won = didOutcomeWin(row.outcome, { winningLabel, yesPrice });
      if (won === null) {
        undeterminable.push({
          row,
          reason: !winningLabel
            ? `market unresolved/unavailable (labels=${labels ? labels.join("/") : "none"})`
            : `label mismatch: bought '${row.outcome}' vs winner '${winningLabel}'`,
        });
        continue;
      }
      if (!won) {
        unchanged.correct++;
        continue;
      }
      const correctedPnl = computePnl(row.entryPrice, 1, row.size);
      const booked = row.realizedPnl ?? 0;
      if (Math.abs(correctedPnl - booked) < 0.005) {
        unchanged.alreadyRight++;
        continue;
      }
      fixes.push({ row, winnerLabel: winningLabel!, correctedPnl, delta: correctedPnl - booked });
    }
  }

  // ---- report ----
  log(`markets grouped=${byMarket.size} resolved=${marketsFetched} unavailable=${marketsUnavailable}`);
  log(`resolution routes: ${[...routeCounts.entries()].map(([k, v]) => `${k}=${v}`).join(", ") || "none"}`);
  const byBotSummary = new Map<string, { n: number; booked: number; corrected: number }>();
  for (const f of fixes) {
    const s = byBotSummary.get(f.row.botId) ?? { n: 0, booked: 0, corrected: 0 };
    s.n++;
    s.booked += f.row.realizedPnl ?? 0;
    s.corrected += f.correctedPnl;
    byBotSummary.set(f.row.botId, s);
  }
  console.log("");
  console.log("  bot            n   booked      -> corrected     delta");
  for (const [bot, s] of [...byBotSummary.entries()].sort()) {
    console.log(
      `  ${bot.padEnd(13)} ${String(s.n).padStart(3)}  ${s.booked.toFixed(2).padStart(9)}  -> ${s.corrected.toFixed(2).padStart(9)}  ${(s.corrected - s.booked).toFixed(2).padStart(9)}`
    );
  }
  const totals = [...byBotSummary.values()].reduce(
    (a, s) => ({ n: a.n + s.n, booked: a.booked + s.booked, corrected: a.corrected + s.corrected }),
    { n: 0, booked: 0, corrected: 0 }
  );
  console.log(
    `  ${"ALL".padEnd(13)} ${String(totals.n).padStart(3)}  ${totals.booked.toFixed(2).padStart(9)}  -> ${totals.corrected.toFixed(2).padStart(9)}  ${(totals.corrected - totals.booked).toFixed(2).padStart(9)}`
  );
  console.log("");
  log(`unchanged: correct losses=${unchanged.correct} already-right=${unchanged.alreadyRight} undeterminable=${undeterminable.length}`);

  if (undeterminable.length) {
    log("undeterminable rows (left untouched — no evidence either way):");
    const reasons = new Map<string, number>();
    for (const u of undeterminable) reasons.set(u.reason, (reasons.get(u.reason) ?? 0) + 1);
    for (const [reason, n] of [...reasons.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8)) {
      log(`  ${n.toString().padStart(4)}x ${reason}`);
    }
  }

  if (BINARY_SAMPLE > 0) {
    log(`binary-market sample check: ${binaryMarketsSeen.length} of ${marketsFetched} fetched markets carry Yes/No labels`);
  }

  // ---- impact on the live gate inputs ----
  const br = await prisma.botBankroll.findUnique({ where: { botId: "BANKROLL_200" } });
  const openUnreal = await prisma.paperTrade.aggregate({ where: { botId: "BANKROLL_200", status: "open" }, _sum: { unrealizedPnl: true } });
  const c200Delta = byBotSummary.get("BANKROLL_200")?.corrected !== undefined
    ? (byBotSummary.get("BANKROLL_200")!.corrected - byBotSummary.get("BANKROLL_200")!.booked)
    : 0;
  let peak = 0;
  try {
    peak = JSON.parse(fs.readFileSync(join(__dirname, "..", "data", "c200-drawdown.json"), "utf8")).peak ?? 0;
  } catch { /* not seeded */ }
  const nwNow = (br?.principal ?? 0) + (br?.realizedPnl ?? 0) + (openUnreal._sum.unrealizedPnl ?? 0);
  const nwAfter = nwNow + c200Delta;
  // Bound the corrected peak instead of inventing a series: corrections landing
  // BEFORE the stored high-water mark also raise the peak (worst case).
  const peakAfterMax = peak + Math.max(0, c200Delta);
  console.log("");
  log(`BANKROLL_200: realized ${(br?.realizedPnl ?? 0).toFixed(2)} -> ${((br?.realizedPnl ?? 0) + c200Delta).toFixed(2)} | cash ${(br?.cashBalance ?? 0).toFixed(2)} -> ${((br?.cashBalance ?? 0) + c200Delta).toFixed(2)}`);
  log(`net worth ${nwNow.toFixed(2)} -> ${nwAfter.toFixed(2)} | drawdown vs stored peak ${peak.toFixed(2)}: ${(((peak - nwNow) / peak) * 100).toFixed(1)}% -> ${(((peak - nwAfter) / peak) * 100).toFixed(1)}%`);
  log(`drawdown WORST CASE (peak also rises by the correction) ${peakAfterMax.toFixed(2)}: ${(((peakAfterMax - nwAfter) / peakAfterMax) * 100).toFixed(1)}%`);

  if (DUMP_PATH) {
    fs.writeFileSync(
      DUMP_PATH,
      JSON.stringify(
        fixes.map((f) => ({
          id: f.row.id, botId: f.row.botId, bought: f.row.outcome, winnerLabel: f.winnerLabel,
          marketId: f.row.marketId, conditionId: f.row.conditionId, entryPrice: f.row.entryPrice,
          size: f.row.size, booked: f.row.realizedPnl, corrected: f.correctedPnl, delta: f.delta,
        })),
        null,
        2
      )
    );
    log(`fix list written: ${DUMP_PATH} (${fixes.length} rows)`);
  }

  if (!APPLY) {
    log("dry run — nothing written. Re-run with --apply to write.");
    await prisma.$disconnect();
    return;
  }

  if (fixes.length === 0) {
    log("nothing to fix.");
    await prisma.$disconnect();
    return;
  }

  const backupPath = join(__dirname, "..", "data", `backfill-misresolved-${new Date().toISOString().slice(0, 10)}.json`);
  fs.writeFileSync(
    backupPath,
    JSON.stringify(
      {
        generatedAt: new Date().toISOString(),
        reason: "phantom losses from YES/NO resolution guess on label-named markets (see drafts/resolution-label-bug-plan.md)",
        rows: fixes.map((f) => ({
          id: f.row.id,
          botId: f.row.botId,
          bought: f.row.outcome,
          winnerLabel: f.winnerLabel,
          marketId: f.row.marketId,
          conditionId: f.row.conditionId,
          entryPrice: f.row.entryPrice,
          size: f.row.size,
          bookedRealizedPnl: f.row.realizedPnl,
          correctedRealizedPnl: f.correctedPnl,
          delta: f.delta,
          resolvedAt: f.row.resolvedAt,
        })),
      },
      null,
      2
    )
  );
  log(`backup written: ${backupPath}`);

  // SQLite write locks are normal here (monitor/score + update-pnl run on cron);
  // retry rather than abort half-way.
  const withRetry = async <T,>(fn: () => Promise<T>, label: string): Promise<T> => {
    let lastErr: unknown;
    for (let attempt = 1; attempt <= 4; attempt++) {
      try {
        return await fn();
      } catch (e) {
        lastErr = e;
        const msg = e instanceof Error ? e.message : String(e);
        if (!/busy|locked|SQLITE_BUSY/i.test(msg) || attempt === 4) break;
        log(`  ${label}: db busy (attempt ${attempt}) — retrying in ${attempt}s`);
        await new Promise((r) => setTimeout(r, attempt * 1000));
      }
    }
    throw lastErr;
  };

  let applied = 0;
  for (const f of fixes) {
    await withRetry(() => prisma.$transaction(async (tx) => {
      await tx.paperTrade.update({
        where: { id: f.row.id },
        data: { realizedPnl: f.correctedPnl, currentPrice: 1, unrealizedPnl: 0, status: "resolved" },
      });
      if (BOTS_WITH_BANKROLL.has(f.row.botId)) {
        await tx.botBankroll.update({
          where: { botId: f.row.botId },
          data: { cashBalance: { increment: f.delta }, realizedPnl: { increment: f.delta } },
        });
      }
    }), f.row.id);
    applied++;
    if (applied % 25 === 0) log(`  …${applied}/${fixes.length}`);
  }
  log(`applied ${applied} corrections`);

  // Read back to prove the writes landed.
  const after = await prisma.botBankroll.findUnique({ where: { botId: "BANKROLL_200" } });
  const verify = await prisma.paperTrade.aggregate({ where: { id: { in: fixes.map((f) => f.row.id) } }, _sum: { realizedPnl: true } });
  log(
    `post-write: corrected rows realized ${verify._sum.realizedPnl?.toFixed(2)} | BANKROLL_200 realized ${after?.realizedPnl.toFixed(2)} cash ${after?.cashBalance.toFixed(2)}`
  );
  logError(`NOTE: re-run scripts/audit-misresolved-trades.py to confirm 0 phantom losses remain.`);
  await prisma.$disconnect();
}

main().catch(async (e) => {
  logError(`backfill:misresolved FAILED: ${e instanceof Error ? e.message : String(e)}`);
  await prisma.$disconnect().catch(() => {});
  process.exit(1);
});

void resolvePaperTrade;
