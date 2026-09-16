/**
 * backfill-copy-labels — 2026-09-16 tuning review #27 rec 2 (user-approved).
 *
 * Before the Rec 1 fix (2026-09-15 17:09Z) the journal row was written with
 * decision='paper_copy' BEFORE any gate ran, so ~5k rows say "copy" although no
 * leg ever opened — the Sep 15 EOD printed "copy 381" against 108 real opens.
 * Rec 1 fixed it going forward; this relabels the historical rows so old
 * windows, the ML-1 decision sample and the EOD copy line stop over-reporting.
 *
 * Two distinct causes, tagged separately on the row (risksJson):
 *   "fill coalesced into an existing open position" — a same (wallet, market,
 *      outcome) position exists within ±2h: the v52 sweep-dedupe merged this
 *      fill into an already-open copy, so no NEW leg was created.
 *   "no leg ever opened" — no matching position at all: gate-blocked or the
 *      C-200 dispatch failed. Neither is a copy by outcome.
 *
 * Safety: only rows older than MIN_AGE_HOURS are touched (a leg booked by the
 * sidecar webhook can lag its decision row), and every row keeps its original
 * label in the appended risk string.
 *
 * Run (dry run first — writes nothing):
 *   DATABASE_URL="file:./dev.db" npx tsx scripts/backfill-copy-labels.ts
 *   DATABASE_URL="file:./dev.db" npx tsx scripts/backfill-copy-labels.ts --apply
 */

import { prisma } from "../src/lib/db";
import { log, logError } from "../src/lib/redact";

const MIN_AGE_HOURS = 2;
const BATCH = 200;
const COALESCE_WINDOW_MS = 2 * 60 * 60 * 1000;

async function withRetry<T>(fn: () => Promise<T>, label: string, attempts = 6): Promise<T> {
  let last: unknown;
  for (let i = 1; i <= attempts; i++) {
    try {
      return await fn();
    } catch (e) {
      last = e;
      const msg = e instanceof Error ? e.message : String(e);
      if (!/locked|busy|timeout/i.test(msg)) throw e;
      await new Promise((r) => setTimeout(r, 400 * i));
    }
  }
  throw new Error(`${label} failed after ${attempts} attempts: ${last instanceof Error ? last.message : last}`);
}

async function main() {
  const apply = process.argv.includes("--apply");
  const cutoff = new Date(Date.now() - MIN_AGE_HOURS * 3_600_000);

  const rows = await withRetry(
    () =>
      prisma.decisionJournal.findMany({
        where: {
          isDemo: false,
          decision: "paper_copy",
          createdAt: { lt: cutoff },
          paperTrades: { none: {} },
        },
        // outcome lives on the observed trade (DecisionJournal has no own column)
        select: {
          id: true,
          walletAddress: true,
          marketId: true,
          createdAt: true,
          risksJson: true,
          observedTrade: { select: { outcome: true } },
        },
        orderBy: { createdAt: "asc" },
      }),
    "select childless copy rows"
  );

  log(`backfill-copy-labels: ${rows.length} childless copy rows older than ${MIN_AGE_HOURS}h${apply ? "" : " (DRY RUN — nothing written)"}`);
  if (rows.length === 0) return;

  const byDay = new Map<string, number>();
  for (const r of rows) {
    const d = r.createdAt.toISOString().slice(0, 10);
    byDay.set(d, (byDay.get(d) ?? 0) + 1);
  }
  const days = [...byDay.entries()].sort();
  log(`  span ${days[0][0]} … ${days[days.length - 1][0]} across ${days.length} days; largest: ${days.sort((a, b) => b[1] - a[1]).slice(0, 3).map(([d, n]) => `${d}=${n}`).join(" ")}`);

  let coalesced = 0;
  let neverOpened = 0;
  let written = 0;
  let failed = 0;

  for (const r of rows) {
    try {
      const twin = await withRetry(
        () =>
          prisma.paperTrade.findFirst({
            where: {
              walletAddress: r.walletAddress,
              marketId: r.marketId,
              outcome: r.observedTrade.outcome,
              openedAt: {
                gte: new Date(r.createdAt.getTime() - COALESCE_WINDOW_MS),
                lte: new Date(r.createdAt.getTime() + COALESCE_WINDOW_MS),
              },
            },
            select: { id: true },
          }),
        `twin lookup ${r.id}`
      );
      const reason = twin
        ? "backfilled 2026-09-16 (tuning #27 rec 2): relabelled copy→skip — fill coalesced into an existing open position (v52 sweep-dedupe), no new leg"
        : "backfilled 2026-09-16 (tuning #27 rec 2): relabelled copy→skip — no leg ever opened (gate-blocked or dispatch failed)";
      if (twin) coalesced++;
      else neverOpened++;

      if (!apply) continue;

      let risks: unknown[] = [];
      try {
        risks = JSON.parse(r.risksJson ?? "[]") as unknown[];
        if (!Array.isArray(risks)) risks = [];
      } catch {
        risks = [];
      }
      await withRetry(
        () =>
          prisma.decisionJournal.update({
            where: { id: r.id },
            data: { decision: "skip", simulatedPositionSize: null, risksJson: JSON.stringify([...risks, reason]) },
          }),
        `update ${r.id}`
      );
      written++;
      if (written % BATCH === 0) log(`  … ${written}/${rows.length} relabelled`);
    } catch (e) {
      failed++;
      if (failed <= 5) logError(`  row ${r.id} failed: ${e instanceof Error ? e.message : e}`);
    }
  }

  log(
    `backfill-copy-labels: ${coalesced} coalesced into an existing position, ${neverOpened} never opened` +
      (apply ? ` — ${written} rows relabelled, ${failed} failed` : " (dry run: no writes)")
  );
}

main()
  .catch((e) => {
    logError("backfill-copy-labels FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
