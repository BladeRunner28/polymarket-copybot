#!/usr/bin/env node
/**
 * combined-market-census — is a market with no slug still reaching the decision path?
 *
 * WHY THIS EXISTS (roadmap card `parlay-rows-in-decision-path`, Lane B):
 * Polymarket "AND" parlays (combined markets) arrive on the wallet tape with an EMPTY
 * marketId. The card measured 572 such rows in a 30d window and reported them as rows
 * that "reach score-trades, the market fetch throws on the blank-slug guard, and the gate
 * stack judges a market that has no slug". This script answers that as a TEST rather than
 * a claim, and it separates HISTORY from a LIVE path.
 *
 * THREE QUESTIONS, EACH WITH ITS OWN POPULATION / CLOCK / LEVEL
 *   A. INTAKE   level=ObservedTrade row — how many unsluggable rows are stored, how many
 *               are stamped observation-only, and when did the last un-stamped one land?
 *   B. DECISIONS level=DecisionJournal row — do those rows still get journalled, by era?
 *               `INTAKE_EXCLUSION_EPOCH` (tuning #64, 2026-10-24T02:55:48Z) is the line
 *               between history and a regression.
 *   C. LEGS     level=PaperTrade leg — what did the class actually cost, and does the
 *               booked number have a settlement basis?
 *   D. CONTROL  level=row, 30d — how many rows would a naive `" AND "` text rule sweep in?
 *               Printed so the false-positive class can never be mistaken for the identity.
 *
 * A NEGATIVE ANSWER IS THE POINT: this instrument exits 0 when the class is closed, so
 * "no parlays reach the decision path" is a reproducible claim rather than a memory.
 *
 * Usage:
 *   npx tsx scripts/combined-market-census.ts                 # census (default 30d control window)
 *   npx tsx scripts/combined-market-census.ts --days=90
 *   npx tsx scripts/combined-market-census.ts --self-test      # exit 1 if the class reopened
 *
 * READ-ONLY: SELECTs only. No rule, threshold, sizing input, gate or booking path imports it.
 */

import { prisma } from "../src/lib/db";
import {
  INTAKE_EXCLUSION_EPOCH,
  classifyIngestRow,
  decisionEra,
  summarizeUnsluggableLegs,
  textAndLookalike,
} from "../src/lib/combined-market";

const args = new Set(process.argv.slice(2));
const SELF_TEST = args.has("--self-test");
const daysArg = process.argv.find((a) => a.startsWith("--days="));
const DAYS = daysArg ? Math.max(1, Number(daysArg.split("=")[1])) : 30;
const EPOCH_MS = Date.parse(INTAKE_EXCLUSION_EPOCH);
const NOW_MS = Date.now();
const WINDOW_START_MS = NOW_MS - DAYS * 86_400_000;

const iso = (ms: number) => new Date(ms).toISOString().replace(".000Z", "Z");
const n = (v: unknown) => Number(v ?? 0);

let failures = 0;
function check(ok: boolean, message: string) {
  if (ok) return;
  failures++;
  console.error(`[census] FAIL — ${message}`);
}

async function main() {
  console.log(
    `[combined-market-census] clock=${iso(NOW_MS)} intake-exclusion-epoch=${INTAKE_EXCLUSION_EPOCH} ` +
      `control-window=${DAYS}d`
  );

  // NEGATIVE CONTROL FIRST: a detector that cannot see the defect it is looking for
  // reports "closed" forever. This runs the classifier on a known-leaking row and
  // demands the LEAK verdict, so a broken instrument fails loudly instead of agreeing.
  check(
    classifyIngestRow({ marketId: "", observationOnly: false }).leakedAsCopyable &&
      !classifyIngestRow({ marketId: "", observationOnly: true }).leakedAsCopyable,
    "the leak detector is broken: it cannot separate a copyable unsluggable row from an excluded one"
  );

  // ---------------------------------------------------------------- A. INTAKE
  const intake = await prisma.$queryRawUnsafe<
    Array<{ total: number; stamped: number; leaked: number; lastLeaked: number | null }>
  >(
    `SELECT COUNT(*) AS total,
            SUM(CASE WHEN observationOnly = 1 THEN 1 ELSE 0 END) AS stamped,
            SUM(CASE WHEN observationOnly = 0 THEN 1 ELSE 0 END) AS leaked,
            MAX(CASE WHEN observationOnly = 0 THEN "timestamp" ELSE NULL END) AS lastLeaked
     FROM ObservedTrade WHERE isDemo = 0 AND LENGTH(marketId) = 0`
  );
  const i = intake[0] ?? { total: 0, stamped: 0, leaked: 0, lastLeaked: null };
  const leakedAfter = await prisma.$queryRawUnsafe<Array<{ c: number }>>(
    `SELECT COUNT(*) AS c FROM ObservedTrade
     WHERE isDemo = 0 AND LENGTH(marketId) = 0 AND observationOnly = 0 AND "timestamp" > ?`,
    EPOCH_MS
  );
  const leakedPost = n(leakedAfter[0]?.c);
  console.log(
    `\nA. INTAKE  level=row, population=ObservedTrade isDemo=0 with an empty marketId, clock=lifetime` +
      `\n   unsluggable rows stored        ${n(i.total)}` +
      `\n   stamped observationOnly        ${n(i.stamped)} (${pct(n(i.stamped), n(i.total))})` +
      `\n   stored COPYABLE (the defect)   ${n(i.leaked)} — newest ${i.lastLeaked ? iso(n(i.lastLeaked)) : "none"}` +
      `\n   copyable AFTER the fix epoch   ${leakedPost}`
  );
  check(leakedPost === 0, `${leakedPost} unsluggable row(s) stored copyable after ${INTAKE_EXCLUSION_EPOCH}`);

  // ------------------------------------------------------------- B. DECISIONS
  const decisions = await prisma.$queryRawUnsafe<Array<{ decision: string; c: number }>>(
    `SELECT dj.decision AS decision, COUNT(*) AS c
     FROM DecisionJournal dj JOIN ObservedTrade o ON o.id = dj.observedTradeId
     WHERE LENGTH(o.marketId) = 0 GROUP BY dj.decision`
  );
  const decRows = await prisma.$queryRawUnsafe<Array<{ createdAt: number }>>(
    `SELECT dj.createdAt AS createdAt
     FROM DecisionJournal dj JOIN ObservedTrade o ON o.id = dj.observedTradeId
     WHERE LENGTH(o.marketId) = 0 ORDER BY dj.createdAt`
  );
  const eras = { "pre-fix": 0, "post-fix": 0 };
  for (const r of decRows) eras[decisionEra(n(r.createdAt), INTAKE_EXCLUSION_EPOCH)]++;
  const lastDecision = decRows.length ? n(decRows[decRows.length - 1].createdAt) : null;
  console.log(
    `\nB. DECISIONS  level=decision, population=DecisionJournal rows joined to an empty-marketId ObservedTrade, clock=decision createdAt` +
      `\n   journalled                     ${decRows.length} — ${decisions.map((d) => `${d.decision} ${n(d.c)}`).join(", ") || "none"}` +
      `\n   era split                      pre-fix ${eras["pre-fix"]} / post-fix ${eras["post-fix"]}` +
      `\n   newest decision                ${lastDecision ? iso(lastDecision) : "none"}` +
      `\n   days since the newest          ${lastDecision ? ((NOW_MS - lastDecision) / 86_400_000).toFixed(1) : "—"}`
  );
  check(eras["post-fix"] === 0, `${eras["post-fix"]} decision(s) journalled on an unsluggable row after the intake fix`);

  // -------------------------------------------------------------------- C. LEGS
  const legRows = await prisma.$queryRawUnsafe<
    Array<{
      botId: string;
      size: number;
      pnl: number | null;
      entryPrice: number;
      outcome: string;
      status: string;
      openedAt: number;
      resolvedAt: number | null;
      marketId: string;
    }>
  >(
    `SELECT pt.botId AS botId, pt.simulatedPositionSize AS size, pt.realizedPnl AS pnl,
            pt.entryPrice AS entryPrice, pt.outcome AS outcome, pt.status AS status,
            pt.openedAt AS openedAt, pt.resolvedAt AS resolvedAt, pt.marketId AS marketId
     FROM PaperTrade pt
     JOIN DecisionJournal dj ON dj.id = pt.decisionJournalId
     JOIN ObservedTrade o ON o.id = dj.observedTradeId
     WHERE LENGTH(o.marketId) = 0`
  );
  const summary = summarizeUnsluggableLegs(
    legRows.map((r) => ({
      botId: r.botId,
      size: n(r.size),
      realizedPnl: r.pnl === null ? null : n(r.pnl),
      entryPrice: n(r.entryPrice),
      outcome: r.outcome,
    }))
  );
  const resolveMinutes = new Set(
    legRows.map((r) => (r.resolvedAt ? new Date(n(r.resolvedAt)).toISOString().slice(0, 16) : "open"))
  );
  const slugsOnLegs = legRows.filter((r) => r.marketId && r.marketId.trim() !== "").length;
  console.log(
    `\nC. LEGS  level=leg, population=PaperTrade booked off an empty-marketId ObservedTrade, clock=openedAt` +
      `\n   legs / staked / booked PnL     ${summary.legs} / $${summary.staked.toFixed(2)} / $${summary.bookedPnl.toFixed(2)}` +
      ` (loss share ${(summary.lossShare * 100).toFixed(1)}%)` +
      `\n   by lane                        ${Object.entries(summary.byBot).map(([k, v]) => `${k} ${v.legs} legs $${v.staked.toFixed(2)} → $${v.pnl.toFixed(2)}`).join("; ") || "none"}` +
      `\n   legs opened                    ${legRows.length ? iso(Math.min(...legRows.map((r) => n(r.openedAt)))) + " .. " + iso(Math.max(...legRows.map((r) => n(r.openedAt)))) : "none"}` +
      `\n   blank outcome label            ${summary.blankOutcome}/${summary.legs} — no venue label, so no settlement basis` +
      `\n   distinct resolve minutes       ${resolveMinutes.size} (one batch = a backfill, not 40 venue verdicts)`
  );
  check(slugsOnLegs === 0, `${slugsOnLegs} booked leg(s) carry a slug — the leg query is not selecting the class it claims`);

  // ----------------------------------------------------------------- D. CONTROL
  const control = await prisma.$queryRawUnsafe<Array<{ c: number; sluggedAnd: number }>>(
    `SELECT COUNT(*) AS c,
            SUM(CASE WHEN LENGTH(marketId) > 0 THEN 1 ELSE 0 END) AS sluggedAnd
     FROM ObservedTrade
     WHERE isDemo = 0 AND "timestamp" >= ? AND marketQuestion LIKE '% AND %'`,
    WINDOW_START_MS
  );
  const cAll = n(control[0]?.c);
  const cSlug = n(control[0]?.sluggedAnd);
  const samples = await prisma.$queryRawUnsafe<Array<{ marketQuestion: string; marketId: string }>>(
    `SELECT marketQuestion AS marketQuestion, MAX(marketId) AS marketId
     FROM ObservedTrade
     WHERE isDemo = 0 AND "timestamp" >= ? AND LENGTH(marketId) > 0 AND marketQuestion LIKE '% AND %'
     GROUP BY marketQuestion ORDER BY MAX("timestamp") DESC LIMIT 3`,
    WINDOW_START_MS
  );
  console.log(
    `\nD. CONTROL  level=row, population=ObservedTrade isDemo=0, clock=last ${DAYS}d, test=question contains " AND "` +
      `\n   rows matching the naive rule  ${cAll} — of which WITH a slug ${cSlug} (${pct(cSlug, cAll)})` +
      `\n   → a text rule is NOT the classifier; it would exclude tradeable compound markets:` +
      samples.map((s) => `\n     "${truncate(s.marketQuestion, 96)}"`).join("") +
      `\n   sanity                        uppercase rule: textAndLookalike("A vs B AND C vs D") = ${textAndLookalike("A vs B AND C vs D")}, ` +
      `ordinary English: textAndLookalike("between 37m and 40m") = ${textAndLookalike("between 37m and 40m")}` +
      `\n   note                          SQLite LIKE is CASE-INSENSITIVE, so the count above is the widest possible` +
      ` read of the naive rule — a case-sensitive " AND " arm would still sweep match-vs-match compounds`
  );
  check(cAll > 0, "the control query returned no rows — the false-positive class went unmeasured, so this run proves nothing about the text rule");

  console.log(
    `\nVERDICT  ${failures === 0 ? "class CLOSED at intake; no unsluggable leg reaches the decision path" : `${failures} check(s) FAILED — see above`}`
  );
  return failures === 0 ? 0 : 1;
}

function pct(a: number, b: number): string {
  return b > 0 ? `${((a / b) * 100).toFixed(1)}%` : "—";
}
function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

main()
  .then((code) => {
    if (SELF_TEST && code !== 0) {
      console.error("[census] self-test FAILED — the unsluggable class is open; see the failing check above");
      process.exit(1);
    }
    process.exit(code);
  })
  .catch((e) => {
    console.error(`[census] error: ${e instanceof Error ? e.message : String(e)}`);
    process.exit(1);
  });
