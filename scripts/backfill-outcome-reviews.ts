/**
 * backfill:outcome-reviews — re-derive the stored judgements on existing
 * OutcomeReview rows.
 *
 * WHY: review-outcomes.ts decided `won` with a raw `winningOutcome === outcome`
 * comparison. The stored label is API-cased ("No", "Over", "Spain") while the
 * stored trade outcome is uppercased ("NO", "OVER", "SPAIN"), so `won` was ALWAYS
 * false (0/688 exact matches vs 509/688 case-insensitive). Consequences baked into
 * the stored rows:
 *   - watchlist/skip rows: `good = !won` was forced TRUE — every one of them is
 *     stamped "judged good" with an "Avoided loser" lesson regardless of what
 *     actually happened;
 *   - uncopied rows: `simulatedPnl = computePnl(entry, 0, 10)` = −$10 always;
 *   - paper_copy rows whose trade was booked as a phantom loss: `good` was false.
 *
 * The stored `finalOutcome` itself is the venue's real token label (they all came
 * from the CLOB fallback, which returns labels — the adapter's "YES"/"NO" guess
 * never appears), so it is treated as the winning label and NO network calls are
 * needed: `didOutcomeWin(outcome, { winningLabel: finalOutcome })` is enough.
 *
 * Usage:
 *   npx tsx scripts/backfill-outcome-reviews.ts            # dry run (default)
 *   npx tsx scripts/backfill-outcome-reviews.ts --apply    # write + backup dump
 *
 * Read-only unless --apply. Backup: data/backfill-outcome-reviews-<date>.json
 */

import * as fs from "fs";
import { join } from "path";
import { prisma } from "../src/lib/db";
import { computePnl } from "../src/lib/paper";
import { didOutcomeWin } from "../src/lib/resolution";
import { log, logError } from "../src/lib/redact";

const APPLY = process.argv.includes("--apply");
const dumpArg = process.argv.find((a) => a.startsWith("--dump="));
const DUMP_PATH = dumpArg ? dumpArg.split("=")[1] : null;
const HYPOTHETICAL_SIZE = 10;

type Change = {
  reviewId: string;
  decisionId: string;
  decision: string;
  venue: string;
  market: string;
  bought: string;
  winningLabel: string;
  won: boolean;
  before: { simulatedPnl: number | null; wasDecisionGood: boolean | null; lessonsJson: string };
  after: { simulatedPnl: number; wasDecisionGood: boolean; lessonsJson: string };
  fieldsChanged: string[];
};

async function main() {
  const reviews = await prisma.outcomeReview.findMany({
    where: { finalOutcome: { not: null } },
    include: {
      decision: { include: { observedTrade: true, paperTrades: true } },
    },
  });
  log(`backfill:outcome-reviews — ${reviews.length} reviewed decisions (${APPLY ? "APPLY" : "dry run"})`);

  const changes: Change[] = [];
  const unmappable: string[] = [];
  const tally = { simulatedPnl: 0, wasDecisionGood: 0, lessonsJson: 0, unchanged: 0, goodTrueToFalse: 0, goodFalseToTrue: 0 };

  for (const r of reviews) {
    const d = r.decision;
    const winningLabel = r.finalOutcome as string;
    const won = didOutcomeWin(d.observedTrade.outcome, { winningLabel });
    if (won === null) {
      unmappable.push(`${r.id}: bought '${d.observedTrade.outcome}' vs winner '${winningLabel}'`);
      continue;
    }

    // Same arithmetic as scripts/review-outcomes.ts (keep in lockstep).
    const pt = d.paperTrades[0];
    const simulatedPnl =
      pt?.realizedPnl ?? computePnl(d.observedTrade.detectedPrice, won ? 1 : 0, HYPOTHETICAL_SIZE);

    let good: boolean;
    const lessons: string[] = [];
    if (d.decision === "paper_copy") {
      good = simulatedPnl > 0;
      lessons.push(
        good
          ? `Copy won ${simulatedPnl.toFixed(2)} — wallet signal + filters aligned`
          : `Copy lost ${simulatedPnl.toFixed(2)} — check whether entry drift or wallet quality was the miss`
      );
    } else {
      // For watchlist/skip: good if the market went against the wallet.
      good = !won;
      lessons.push(
        won
          ? `Missed winner (+${simulatedPnl.toFixed(2)} hypothetical) — decision was ${d.decision}, review which gate blocked it`
          : `Avoided loser (${simulatedPnl.toFixed(2)} hypothetical) — ${d.decision} was correct`
      );
    }
    const lessonsJson = JSON.stringify(lessons);

    const fieldsChanged: string[] = [];
    if (Math.abs((r.simulatedPnl ?? 0) - simulatedPnl) > 0.005) fieldsChanged.push("simulatedPnl");
    if (r.wasDecisionGood !== good) fieldsChanged.push("wasDecisionGood");
    if (r.lessonsJson !== lessonsJson) fieldsChanged.push("lessonsJson");
    if (fieldsChanged.length === 0) {
      tally.unchanged++;
      continue;
    }
    if (fieldsChanged.includes("simulatedPnl")) tally.simulatedPnl++;
    if (fieldsChanged.includes("wasDecisionGood")) {
      tally.wasDecisionGood++;
      if (r.wasDecisionGood === true && good === false) tally.goodTrueToFalse++;
      if (r.wasDecisionGood === false && good === true) tally.goodFalseToTrue++;
    }
    if (fieldsChanged.includes("lessonsJson")) tally.lessonsJson++;

    changes.push({
      reviewId: r.id,
      decisionId: d.id,
      decision: d.decision,
      venue: d.venue,
      market: d.observedTrade.marketQuestion.slice(0, 70),
      bought: d.observedTrade.outcome,
      winningLabel,
      won,
      before: { simulatedPnl: r.simulatedPnl, wasDecisionGood: r.wasDecisionGood, lessonsJson: r.lessonsJson },
      after: { simulatedPnl, wasDecisionGood: good, lessonsJson },
      fieldsChanged,
    });
  }

  const byDecision = new Map<string, number>();
  for (const c of changes) byDecision.set(c.decision, (byDecision.get(c.decision) ?? 0) + 1);
  log(
    `rows needing changes: ${changes.length} of ${reviews.length} (unchanged ${tally.unchanged})` +
      (unmappable.length ? ` | unmappable ${unmappable.length}` : "")
  );
  log(`field diffs: simulatedPnl=${tally.simulatedPnl} wasDecisionGood=${tally.wasDecisionGood} lessonsJson=${tally.lessonsJson}`);
  log(`wasDecisionGood flips: true->false ${tally.goodTrueToFalse}, false->true ${tally.goodFalseToTrue}`);
  log(`by decision type: ${[...byDecision.entries()].map(([k, v]) => `${k}=${v}`).join(", ") || "none"}`);
  for (const u of unmappable.slice(0, 5)) logError(`  unmappable: ${u}`);

  const before = { good: 0, bad: 0, pnl: 0 };
  const after = { good: 0, bad: 0, pnl: 0 };
  for (const r of reviews) {
    if (r.wasDecisionGood === true) before.good++;
    if (r.wasDecisionGood === false) before.bad++;
    before.pnl += r.simulatedPnl ?? 0;
  }
  for (const r of reviews) {
    const c = changes.find((x) => x.reviewId === r.id);
    const good = c ? c.after.wasDecisionGood : r.wasDecisionGood === true;
    const pnl = c ? c.after.simulatedPnl : r.simulatedPnl ?? 0;
    if (good) after.good++;
    else after.bad++;
    after.pnl += pnl;
  }
  console.log("");
  console.log(`  wasDecisionGood: ${before.good} good / ${before.bad} bad  ->  ${after.good} good / ${after.bad} bad`);
  console.log(`  summed simulatedPnl: ${before.pnl.toFixed(2)}  ->  ${after.pnl.toFixed(2)}`);

  if (DUMP_PATH) {
    fs.writeFileSync(DUMP_PATH, JSON.stringify(changes, null, 2));
    log(`change list written: ${DUMP_PATH}`);
  }

  if (!APPLY) {
    log("dry run — nothing written. Re-run with --apply to write.");
    await prisma.$disconnect();
    return;
  }
  if (changes.length === 0) {
    log("nothing to fix.");
    await prisma.$disconnect();
    return;
  }

  const backupPath = join(__dirname, "..", "data", `backfill-outcome-reviews-${new Date().toISOString().slice(0, 10)}.json`);
  fs.writeFileSync(
    backupPath,
    JSON.stringify(
      {
        generatedAt: new Date().toISOString(),
        reason: "re-derive outcome-review judgements after the outcome-label comparison fix (drafts/resolution-label-bug-plan.md)",
        rows: changes,
      },
      null,
      2
    )
  );
  log(`backup written: ${backupPath}`);

  let applied = 0;
  for (const c of changes) {
    await prisma.outcomeReview.update({
      where: { id: c.reviewId },
      data: { simulatedPnl: c.after.simulatedPnl, wasDecisionGood: c.after.wasDecisionGood, lessonsJson: c.after.lessonsJson },
    });
    applied++;
  }
  log(`applied ${applied} review corrections`);

  // Read back
  const post = await prisma.outcomeReview.findMany({ where: { finalOutcome: { not: null } }, select: { wasDecisionGood: true, simulatedPnl: true } });
  const good = post.filter((r) => r.wasDecisionGood === true).length;
  log(
    `post-write: ${post.length} reviews, ${good} judged good / ${post.length - good} bad, summed simulatedPnl ${post
      .reduce((a, r) => a + (r.simulatedPnl ?? 0), 0)
      .toFixed(2)}`
  );
  await prisma.$disconnect();
}

main().catch(async (e) => {
  logError(`backfill:outcome-reviews FAILED: ${e instanceof Error ? e.message : String(e)}`);
  await prisma.$disconnect().catch(() => {});
  process.exit(1);
});
