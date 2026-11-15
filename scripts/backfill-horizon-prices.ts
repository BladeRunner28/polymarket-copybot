/**
 * backfill:horizon-prices — populate OutcomeReview.priceAfter1h/6h/24h from the
 * venue's own fill tape.
 *
 * WHY: the card `data2-per-decision-provenance` gates on those three columns being
 * populated for at least the paper_copy rows. They shipped in the schema and were
 * never written by anything (11,774 review rows, 0 populated, 0 readers anywhere in
 * the repo on 2026-11-14), so "nothing can learn timing" was literally true. The
 * live writer is now in review:outcomes; this fills the rows already judged.
 *
 * BASIS (stated because every number below carries it): population = OutcomeReview
 * rows joined to their DecisionJournal and ObservedTrade; level = one review row;
 * clock = the journal row's createdAt (UTC), horizons measured from it; price =
 * the held token's LAST print at or before the horizon within 90 minutes, from CLOB
 * /prices-history; settlement marks (exactly 0 or 1) and stale windows are refused
 * and stay NULL. A NULL means "the tape cannot say", never "zero".
 *
 * NOT a rule, not a size, not a gate: nothing here is read by any decision path.
 * Read-only unless --apply.
 *
 *   npx tsx scripts/backfill-horizon-prices.ts --limit 50            # dry run
 *   npx tsx scripts/backfill-horizon-prices.ts --limit 50 --apply    # write
 */
import * as fs from "fs";
import { prisma } from "../src/lib/db";
import { log, logError } from "../src/lib/redact";
import { horizonPricesFor } from "../src/lib/clob-horizon";

const APPLY = process.argv.includes("--apply");
const limitArg = process.argv.find((a) => a.startsWith("--limit=")) ?? process.argv[process.argv.indexOf("--limit") + 1];
const LIMIT = Math.max(0, Number(limitArg ?? 50) || 0);
const ARTIFACT = "data/horizon-price-backfill.json";

async function main() {
  if (!LIMIT) {
    logError("usage: --limit N [--apply]");
    process.exit(1);
  }
  // paper_copy rows first: the card names them as the population that must be
  // populated. Oldest-first so repeated runs advance instead of re-reading the head.
  const rows = await prisma.outcomeReview.findMany({
    where: { priceAfter1h: null, priceAfter6h: null, priceAfter24h: null, finalOutcome: { not: null } },
    include: { decision: { include: { observedTrade: true } } },
    // paper_copy FIRST (the card names it as the population that must be populated;
    // "paper_copy" sorts before "skip"/"watchlist"), then newest-first. Oldest-first was
    // tried and is wrong here: it lands on the 2026-07-14 head-of-line cohort, whose
    // markets died within the hour, so 6h/24h read "stale" for 12/12 and nothing about
    // the live book is learned.
    orderBy: [{ decision: { decision: "asc" } }, { createdAt: "desc" }],
    take: LIMIT * 10, // over-fetch: rows with no conditionId cannot be priced
  });
  const priceableAll = rows
    .filter((r) => r.decision?.observedTrade?.conditionId)
    .filter((r) => !r.decision.isDemo);
  const priceable = priceableAll.slice(0, LIMIT);
  // Two different reasons for a row not being here — a blank conditionId (cannot be
  // priced at all) and the --limit cut (priced next run). Conflating them would make
  // the artifact claim a coverage gap that does not exist.
  const unpriceable = rows.length - priceableAll.length;
  const cappedByLimit = priceableAll.length - priceable.length;

  const results: Array<{
    reviewId: string;
    decision: string;
    outcome: string;
    decidedAt: string;
    h1: number | null;
    h6: number | null;
    h24: number | null;
    reasons: Record<string, string>;
    applied: boolean;
  }> = [];
  let wrote = 0;
  let noToken = 0;

  for (const r of priceable) {
    const trade = r.decision.observedTrade;
    const set = await horizonPricesFor(trade.conditionId, trade.outcome, r.decision.createdAt.getTime());
    const row = {
      reviewId: r.id,
      decision: r.decision.decision,
      outcome: trade.outcome,
      decidedAt: r.decision.createdAt.toISOString(),
      h1: set?.["1h"].price ?? null,
      h6: set?.["6h"].price ?? null,
      h24: set?.["24h"].price ?? null,
      reasons: (set
        ? { "1h": set["1h"].reason, "6h": set["6h"].reason, "24h": set["24h"].reason }
        : { token: "unresolved" }) as Record<string, string>,
      applied: false,
    };
    if (!set) {
      noToken++;
    } else if (APPLY && (row.h1 !== null || row.h6 !== null || row.h24 !== null)) {
      await prisma.outcomeReview.update({
        where: { id: r.id },
        data: { priceAfter1h: row.h1, priceAfter6h: row.h6, priceAfter24h: row.h24 },
      });
      row.applied = true;
      wrote++;
    }
    results.push(row);
  }

  const filled = (k: "h1" | "h6" | "h24") => results.filter((x) => x[k] !== null).length;
  const summary = {
    generatedAt: new Date().toISOString(),
    applied: APPLY,
    limit: LIMIT,
    candidatesScanned: rows.length,
    priced: priceable.length,
    skippedNoConditionIdOrDemo: unpriceable,
    cappedByLimit,
    tokenUnresolved: noToken,
    rowsWritten: wrote,
    filled: { h1: filled("h1"), h6: filled("h6"), h24: filled("h24") },
    basis: {
      population: "OutcomeReview with all three horizon columns NULL and finalOutcome set",
      level: "one review row",
      clock: "DecisionJournal.createdAt UTC, horizons measured from it",
      price: "held token's last CLOB print at/before the horizon within 90 min; 0/1 and stale refused",
    },
    rows: results,
  };
  fs.writeFileSync(ARTIFACT, JSON.stringify(summary, null, 2));
  log(
    `HORIZON BACKFILL (${APPLY ? "APPLIED" : "dry run"}): scanned ${rows.length}, priceable ${priceable.length}, ` +
      `written ${wrote}; price present 1h ${summary.filled.h1}, 6h ${summary.filled.h6}, 24h ${summary.filled.h24}; ` +
      `${noToken} had no resolvable token, ${unpriceable} had no conditionId/demo, ${cappedByLimit} left for a later run by --limit. Artifact: ${ARTIFACT}`
  );
}

main()
  .catch((e) => {
    logError("backfill:horizon-prices FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
