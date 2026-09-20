/**
 * shadow:longshot-mark — resolve pending long-shot shadow-ladder candidates and
 * publish the shadow-book summary (2026-09-11 C-200 daily report Change 1,
 * approved; freeze-allowed instrumentation).
 *
 * Reads data/longshot-shadow.jsonl (written by score-trades), resolves every
 * would-admit candidate whose market has settled (adapter market state, then
 * the parent-event fallback for dead/renamed slugs), appends one `resolve`
 * record per settled row, and writes data/longshot-shadow-summary.json.
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/mark-shadow-longshot.ts
 */

import { getAdapter } from "../src/lib/adapters";
import { fetchEventResolution } from "../src/lib/dead-market-resolution";
import { didOutcomeWin } from "../src/lib/resolution";
import { readShadowRows, summarizeShadow, SHADOW_FILE, SHADOW_SUMMARY_FILE } from "../src/lib/shadow-longshot";
import {
  readDriftRows,
  summarizeDrift,
  DRIFT_SHADOW_FILE,
  DRIFT_SHADOW_SUMMARY_FILE,
} from "../src/lib/shadow-drift";
import {
  readWalletCapRows,
  summarizeWalletCap,
  WALLET_CAP_SHADOW_FILE,
  WALLET_CAP_SHADOW_SUMMARY_FILE,
} from "../src/lib/shadow-wallet-cap";
import { log, logError } from "../src/lib/redact";
import * as fs from "fs";
import { join } from "path";

/**
 * Bound the work per run. The drift feed grows ~2k candidates/day (the gate is
 * the book's largest volume blocker) and the marker was spending its whole hourly
 * slot walking the backlog — 4,176 awaiting on 2026-09-18. Oldest-first, capped,
 * so each run finishes and the backlog drains steadily.
 */
const MARK_LIMIT = Number(process.env.MARK_LIMIT ?? 300);

// 2026-09-20 tuning review #31 rec 2 (user-approved): PRE-REGISTERED DECAY BAR on
// the drift gate's counterfactual edge. The gate is the book's largest volume
// blocker and its expectancy has decayed three windows running
// (avgPnlPerTradeExDust $1.29 -> $0.88 -> $0.67), so a relaxation is only justified
// if the edge is actually gone. Rule, fixed now and not to be re-tuned at the read:
//   IF avgPnlPerTradeExDust <= $0.50 on 7 CONSECUTIVE days,
//   THEN a maxPriceDrift / longshotDriftPct relaxation is brought forward,
//   attributed by ruleSetVersion (never as one total across v55-v59).
// Until the bar trips, maxPriceDrift keeps its value. Dated series: one row per run
// (the day's LAST row is the day's value), so the 7-day condition is computable.
const DRIFT_DECAY_SERIES_FILE = join(__dirname, "..", "data", "drift-decay-series.jsonl");
const DRIFT_DECAY_BAR_USD = Number(process.env.DRIFT_DECAY_BAR_USD ?? 0.5);
const DRIFT_DECAY_DAYS = Number(process.env.DRIFT_DECAY_DAYS ?? 7);

function capPending<T>(m: Map<string, T>, limit = MARK_LIMIT): Map<string, T> {
  if (m.size <= limit) return m;
  return new Map([...m].slice(0, limit));
}

async function main() {
  const adapter = getAdapter();
  const rows = readShadowRows();
  const candidates = rows.filter((r) => r.type === "candidate" && r.wouldAdmit === true);
  const already = new Set(
    rows.filter((r) => r.type === "resolve").map((r) => `${r.marketId}|${r.outcome}`)
  );

  const pending = new Map<string, { marketId: string; outcome: string }>();
  for (const c of candidates) {
    const key = `${c.marketId}|${c.outcome}`;
    if (!already.has(key)) pending.set(key, { marketId: String(c.marketId), outcome: String(c.outcome) });
  }

  log(`shadow-longshot: ${candidates.length} admits, ${already.size} resolved, ${pending.size} pending.`);
  let resolvedNow = 0;

  for (const { marketId, outcome } of capPending(pending).values()) {
    let value: number | undefined;
    try {
      const m = await adapter.fetchMarket(marketId);
      // Label-aware: shadow candidates on labelled tokens ("Vitality"/"Under")
      // must not be marked 0 by the old YES/NO guess (see src/lib/resolution.ts).
      const winnerLabel = m.winningLabel ?? m.winningOutcome;
      if (m.resolved && winnerLabel) {
        const won = didOutcomeWin(outcome, { winningLabel: winnerLabel, yesPrice: m.yesPrice });
        if (won !== null) value = won ? 1 : 0;
      }
    } catch {
      // fall through to the event-resolution path
    }
    if (value === undefined) {
      try {
        const ev = await fetchEventResolution(marketId);
        if (ev) {
          const won = didOutcomeWin(outcome, { winningLabel: ev });
          if (won !== null) value = won ? 1 : 0;
        }
      } catch {
        /* leave unresolved */
      }
    }
    if (value === undefined) continue;
    fs.appendFileSync(
      SHADOW_FILE,
      JSON.stringify({ ts: new Date().toISOString(), type: "resolve", marketId, outcome, value }) + "\n"
    );
    resolvedNow++;
  }

  // ---- Late-drift gate shadow (2026-09-16 Change 2) -------------------------
  // Same marking machinery, different feed: every would-have-copied entry the
  // drift gate blocked, marked to settlement so the gate's counterfactual stops
  // being an assumption.
  const dRows = readDriftRows();
  const dCandidates = dRows.filter((r) => r.type === "candidate");
  const dAlready = new Set(dRows.filter((r) => r.type === "resolve").map((r) => `${r.marketId}|${r.outcome}`));
  const dPending = new Map<string, { marketId: string; outcome: string }>();
  for (const c of dCandidates) {
    const key = `${c.marketId}|${c.outcome}`;
    if (!dAlready.has(key)) dPending.set(key, { marketId: String(c.marketId), outcome: String(c.outcome) });
  }
  let dResolved = 0;
  for (const { marketId, outcome } of capPending(dPending).values()) {
    let value: number | undefined;
    try {
      const m = await adapter.fetchMarket(marketId);
      const winnerLabel = m.winningLabel ?? m.winningOutcome;
      if (m.resolved && winnerLabel) {
        const won = didOutcomeWin(outcome, { winningLabel: winnerLabel, yesPrice: m.yesPrice });
        if (won !== null) value = won ? 1 : 0;
      }
    } catch {
      /* fall through to the event-resolution path */
    }
    if (value === undefined) {
      try {
        const ev = await fetchEventResolution(marketId);
        if (ev) {
          const won = didOutcomeWin(outcome, { winningLabel: ev });
          if (won !== null) value = won ? 1 : 0;
        }
      } catch {
        /* leave unresolved */
      }
    }
    if (value === undefined) continue;
    fs.appendFileSync(
      DRIFT_SHADOW_FILE,
      JSON.stringify({ ts: new Date().toISOString(), type: "resolve", marketId, outcome, value }) + "\n"
    );
    dResolved++;
  }
  const dSummary = summarizeDrift(readDriftRows());

  // ---- rec 2: dated series + the pre-registered bar --------------------------
  const decayRow = {
    ts: new Date().toISOString(),
    day: new Date().toISOString().slice(0, 10),
    avgPnlPerTradeExDust: dSummary.avgPnlPerTradeExDust,
    marked: dSummary.marked,
    dustExcluded: dSummary.dustExcluded,
  };
  let decaySeries: Array<{ day: string; avgPnlPerTradeExDust: number | null }> = [];
  try {
    fs.appendFileSync(
      DRIFT_DECAY_SERIES_FILE,
      JSON.stringify(decayRow) + "\n"
    );
    decaySeries = fs
      .readFileSync(DRIFT_DECAY_SERIES_FILE, "utf-8")
      .split("\n")
      .filter((l) => l.trim().length > 0)
      .map((l) => JSON.parse(l) as { day: string; avgPnlPerTradeExDust: number | null });
    // the day's LAST reading is the day's value (a day can be marked many times)
    const byDay = new Map<string, { day: string; avgPnlPerTradeExDust: number | null }>();
    for (const r of decaySeries) byDay.set(r.day, r);
    decaySeries = [...byDay.values()].sort((a, b) => (a.day < b.day ? -1 : 1));
  } catch (e) {
    logError(`[DRIFT-DECAY] series write/read failed: ${e instanceof Error ? e.message : e}`);
  }
  const lastN = decaySeries.slice(-DRIFT_DECAY_DAYS);
  let consecutive = 0;
  for (let i = decaySeries.length - 1; i >= 0; i--) {
    const v = decaySeries[i].avgPnlPerTradeExDust;
    if (v !== null && v <= DRIFT_DECAY_BAR_USD) consecutive++;
    else break;
  }
  // The bar requires BOTH reads to be at/below the threshold: the cumulative mean
  // drifts mechanically as settled rows accumulate, the trailing 7-day cohort does
  // not. Pre-registered 2026-09-20 (before either number was ever read).
  const cohortValue = dSummary.avgPnlPerTradeExDustLast7dCohort;
  const cohortOk = cohortValue !== null && cohortValue <= DRIFT_DECAY_BAR_USD;
  const decayBar = {
    thresholdUsd: DRIFT_DECAY_BAR_USD,
    daysRequired: DRIFT_DECAY_DAYS,
    consecutiveDaysAtOrBelow: consecutive,
    cohort7d: cohortValue,
    cohort7dMarked: dSummary.cohort7dMarked,
    cohortAtOrBelow: cohortOk,
    tripped: consecutive >= DRIFT_DECAY_DAYS && cohortOk,
    seriesDays: decaySeries.length,
    recent: lastN.map((r) => ({ day: r.day, avgPnlPerTradeExDust: r.avgPnlPerTradeExDust })),
    rule:
      "PRE-REGISTERED 2026-09-20 (tuning #31 rec 2): if avgPnlPerTradeExDust <= $" +
      DRIFT_DECAY_BAR_USD +
      " for " +
      DRIFT_DECAY_DAYS +
      " consecutive days AND the trailing-7d cohort mean is also <= that bar (the cumulative mean drifts mechanically as settled rows accumulate, so it alone must not trip the bar), a maxPriceDrift/longshotDriftPct relaxation is brought forward, attributed by ruleSetVersion (v55-v59 sub-windows), never as one total. Until then maxPriceDrift keeps its value.",
  };
  fs.writeFileSync(
    DRIFT_SHADOW_SUMMARY_FILE,
    JSON.stringify({ ...dSummary, decayBar }, null, 2)
  );
  log(
    `shadow-drift: +${dResolved} marked this run (cap ${MARK_LIMIT}/run, backlog ${dPending.size}). ` +
      `Gate counterfactual: ${dSummary.candidates} would-have entries, ` +
      `${dSummary.marked} settled (${dSummary.wins} wins, ` +
      `${dSummary.winRate === null ? "—" : (dSummary.winRate * 100).toFixed(1) + "%"}), ` +
      `$${dSummary.wouldHavePnl.toFixed(2)} @ $${dSummary.stakeUsd}/trade (` +
      `${dSummary.avgPnlPerTrade === null ? "—" : "$" + dSummary.avgPnlPerTrade.toFixed(2)}/trade, ` +
      `${dSummary.avgPnlPerTradeExDust === null ? "—" : "$" + dSummary.avgPnlPerTradeExDust.toFixed(2)}/trade ex-dust ` +
      `[${dSummary.dustExcluded} rows below $${dSummary.dustMinEntryPrice}]). ` +
      `Summary: ${DRIFT_SHADOW_SUMMARY_FILE}`
  );

  // ---- Per-wallet ceiling shadow (2026-09-19 daily report rec 1a) -----------
  // v58's ceiling binds HARD on the wallet that was already above it, so every
  // would-be copy from that wallet is vetoed (109 in the first 15h). This marks
  // each vetoed would-be entry to settlement so the cost of the rail is a
  // measured number (per band and per wallet) instead of a veto count.
  const wRows = readWalletCapRows();
  const wCandidates = wRows.filter((r) => r.type === "candidate");
  const wAlready = new Set(
    wRows.filter((r) => r.type === "resolve").map((r) => `${r.marketId}|${r.outcome}`)
  );
  const wPending = new Map<string, { marketId: string; outcome: string }>();
  for (const c of wCandidates) {
    const key = `${c.marketId}|${c.outcome}`;
    if (!wAlready.has(key)) wPending.set(key, { marketId: String(c.marketId), outcome: String(c.outcome) });
  }
  let wResolved = 0;
  for (const { marketId, outcome } of capPending(wPending).values()) {
    let value: number | undefined;
    try {
      const m = await adapter.fetchMarket(marketId);
      const winnerLabel = m.winningLabel ?? m.winningOutcome;
      if (m.resolved && winnerLabel) {
        const won = didOutcomeWin(outcome, { winningLabel: winnerLabel, yesPrice: m.yesPrice });
        if (won !== null) value = won ? 1 : 0;
      }
    } catch {
      /* fall through to the event-resolution path */
    }
    if (value === undefined) {
      try {
        const ev = await fetchEventResolution(marketId);
        if (ev) {
          const won = didOutcomeWin(outcome, { winningLabel: ev });
          if (won !== null) value = won ? 1 : 0;
        }
      } catch {
        /* leave unresolved */
      }
    }
    if (value === undefined) continue;
    fs.appendFileSync(
      WALLET_CAP_SHADOW_FILE,
      JSON.stringify({ ts: new Date().toISOString(), type: "resolve", marketId, outcome, value }) + "\n"
    );
    wResolved++;
  }
  const wSummary = summarizeWalletCap(readWalletCapRows());
  fs.writeFileSync(WALLET_CAP_SHADOW_SUMMARY_FILE, JSON.stringify(wSummary, null, 2));
  const bandLine = Object.entries(wSummary.byBand)
    .map(([b, v]) => `${b}: ${v.n} (${v.marked} marked, $${v.wouldHavePnl.toFixed(2)})`)
    .join(" | ");
  log(
    `shadow-wallet-cap: +${wResolved} marked this run (backlog ${wPending.size}). ` +
      `Ceiling counterfactual: ${wSummary.candidates} would-be entries, ` +
      `${wSummary.marked} settled (${wSummary.wins} wins, ` +
      `${wSummary.winRate === null ? "—" : (wSummary.winRate * 100).toFixed(1) + "%"}), ` +
      `$${wSummary.wouldHavePnl.toFixed(2)} on $${wSummary.stakedUsd.toFixed(2)} staked ` +
      `(${wSummary.avgPnlPerTrade === null ? "—" : "$" + wSummary.avgPnlPerTrade.toFixed(2)}/trade) | ${bandLine}. ` +
      `Summary: ${WALLET_CAP_SHADOW_SUMMARY_FILE}`
  );

  const summary = summarizeShadow(readShadowRows());
  fs.writeFileSync(SHADOW_SUMMARY_FILE, JSON.stringify(summary, null, 2));
  log(
    `shadow-longshot: +${resolvedNow} resolved this run. Book: ${summary.wouldAdmit} admits, ` +
      `${summary.resolved} resolved (${summary.wins} wins, ` +
      `${summary.winRate === null ? "—" : (summary.winRate * 100).toFixed(1) + "%"}), ` +
      `PnL $${summary.totalPnl.toFixed(2)} @ $${summary.stakeUsd}/trade (` +
      `${summary.avgPnlPerTrade === null ? "—" : "$" + summary.avgPnlPerTrade.toFixed(2)}/trade). ` +
      `Summary: ${SHADOW_SUMMARY_FILE}`
  );
}

main()
  .catch((e) => {
    logError("shadow:longshot-mark FAILED:", e);
    process.exit(1);
  })
  .finally(() => process.exit(0));
