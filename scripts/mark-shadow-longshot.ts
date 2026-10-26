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
  DRIFT_DECAY_SERIES_PER_SIGNAL_FILE,
  consecutiveDaysAtOrBelow,
} from "../src/lib/shadow-drift";
import {
  readWalletCapRows,
  summarizeWalletCap,
  WALLET_CAP_SHADOW_FILE,
  WALLET_CAP_SHADOW_SUMMARY_FILE,
} from "../src/lib/shadow-wallet-cap";
import {
  readLowConfRows,
  summarizeLowConf,
  LOWCONF_SHADOW_FILE,
  LOWCONF_SHADOW_SUMMARY_FILE,
} from "../src/lib/shadow-lowconf";
import { log, logError } from "../src/lib/redact";
import {
  ATTEMPT_FAIL_LIMIT,
  ATTEMPT_RETRY_HOURS,
  attemptKey,
  pruneAttemptLedger,
  readAttemptLedger,
  recordAttemptOutcome,
  selectPendingForRun,
  writeAttemptLedger,
  type PendingEntry,
} from "../src/lib/shadow-attempts";
import * as fs from "fs";
import { join } from "path";

/**
 * Bound the work per run. The drift feed grows ~2k candidates/day (the gate is
 * the book's largest volume blocker) and the marker was spending its whole hourly
 * slot walking the backlog — 4,176 awaiting on 2026-09-18. Oldest-first, capped,
 * so each run finishes and the backlog drains steadily.
 */
const MARK_LIMIT = Number(process.env.MARK_LIMIT ?? 300);

/**
 * Drift feed id in the attempt ledger (src/lib/shadow-attempts.ts).
 *
 * 2026-10-10 (card t_81d0a4cb): the drift walk is LEAST-RECENTLY-ATTEMPTED, not
 * oldest-first. Oldest-first let a head that cannot settle YET hold the same 300
 * slots every hour — the head of the pending map is a September cohort of
 * long-dated markets that are STILL OPEN at the venue with live quotes, so both
 * resolution paths return nothing (`resolved === false`). The pre-fix
 * `capPending` window (the first 300 pending keys) is 2026-09-17..2026-09-26,
 * seven distinct decision days with 239 of the 300 decided 2026-09-17 (the first
 * 300 CANDIDATE ROWS are all 2026-09-17 — a different window); 4,526 of the
 * 6,147 pending keys in this branch's snapshot are decided on/before 2026-09-26
 * and 1,127 on/after 2026-10-01 (live copy: 4,526 / 1,145 of 6,165). 14
 * consecutive hourly runs logged `+0 marked`, settled froze at 4,945, and the
 * 827 pending keys decided inside the trailing 7 days (cut 2026-10-10T08:00Z)
 * stayed unreachable behind the head. That is why
 * data/drift-shadow-summary.json reported cohort7dMarked: 0 / cohort7d: null
 * and the pre-registered 2026-09-20 decay bar could never trip. The walk now
 * rotates on a persisted attempt stamp (skip after N=3 consecutive failures,
 * re-attempt once a day) so the trailing-7d cohort is walked every run.
 */
const DRIFT_FEED = "drift";

/** Bounded proof runs: caps the DRIFT walk alone so the other three markers'
 *  output stays comparable (see the exit criteria on card t_81d0a4cb). */
const DRIFT_TEST_LIMIT = process.env.DRIFT_TEST_LIMIT ? Number(process.env.DRIFT_TEST_LIMIT) : null;
const driftLimit = DRIFT_TEST_LIMIT ?? MARK_LIMIT;

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
  //
  // 2026-10-10 (card t_81d0a4cb): this feed walks LEAST-RECENTLY-ATTEMPTED
  // (src/lib/shadow-attempts.ts) instead of oldest-first, so a head of
  // long-dated, still-open September markets cannot hold the cap. The three
  // feeds below keep their oldest-first walk untouched: they mark ~91% of their
  // backlog and have no stuck head.
  const dRows = readDriftRows();
  const dCandidates = dRows.filter((r) => r.type === "candidate");
  const dAlready = new Set(dRows.filter((r) => r.type === "resolve").map((r) => `${r.marketId}|${r.outcome}`));
  const dPending = new Map<string, PendingEntry>();
  for (const c of dCandidates) {
    const key = `${c.marketId}|${c.outcome}`;
    if (dAlready.has(key)) continue;
    const parsed = Date.parse(String(c.ts));
    const decidedAt = Number.isFinite(parsed) ? parsed : 0;
    const prev = dPending.get(key);
    // Duplicate keys (a market|outcome decided more than once) are walked once
    // and ranked by their MOST RECENT decision — the row the summary counts
    // towards the trailing-7d cohort.
    if (!prev || decidedAt > prev.decidedAt) {
      dPending.set(key, { marketId: String(c.marketId), outcome: String(c.outcome), decidedAt });
    }
  }
  const attemptLedger = readAttemptLedger();
  const walkNow = Date.now();
  const walk = selectPendingForRun(DRIFT_FEED, [...dPending.values()], attemptLedger, {
    limit: driftLimit,
    now: walkNow,
  });
  const pendingLedgerKeys = [...dPending.values()].map((e) => attemptKey(DRIFT_FEED, e.marketId, e.outcome));
  const attempted: Array<{ marketId: string; outcome: string; decidedAt: number; resolved: boolean }> = [];
  let folded = 0;
  // Fold attempts into the ledger as the walk proceeds: this is a long network
  // loop and the marker is killable, so a killed run must not lose the stamps
  // the ordering depends on.
  const foldAttempts = () => {
    if (folded === attempted.length) return;
    recordAttemptOutcome(DRIFT_FEED, attempted.slice(folded), attemptLedger, walkNow);
    folded = attempted.length;
    pruneAttemptLedger(attemptLedger, pendingLedgerKeys);
    writeAttemptLedger(attemptLedger);
  };
  let dResolved = 0;
  for (const { marketId, outcome, decidedAt } of walk.selected) {
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
    if (value !== undefined) {
      fs.appendFileSync(
        DRIFT_SHADOW_FILE,
        JSON.stringify({ ts: new Date().toISOString(), type: "resolve", marketId, outcome, value }) + "\n"
      );
      dResolved++;
    }
    attempted.push({ marketId, outcome, decidedAt, resolved: value !== undefined });
    if (attempted.length - folded >= 50) foldAttempts();
  }
  foldAttempts();
  // What the walk actually touched this run — the operator's only way to tell
  // "the cohort is empty because nothing recent was reachable" apart from "the
  // cohort is empty because nothing recent was attempted".
  const walkDay = (ms: number) => new Date(ms).toISOString().slice(0, 10);
  const decidedTimes = attempted.map((a) => a.decidedAt);
  const walkWindow =
    decidedTimes.length > 0 ? `${walkDay(Math.min(...decidedTimes))}..${walkDay(Math.max(...decidedTimes))}` : "—";
  const cohortCutoff = walkNow - 7 * 86400000;
  const cohortAttempted = attempted.filter((a) => a.decidedAt >= cohortCutoff).length;
  const cohortResolved = attempted.filter((a) => a.decidedAt >= cohortCutoff && a.resolved).length;
  const dSummary = summarizeDrift(readDriftRows());
  const cohortNote =
    dSummary.cohort7dMarked > 0
      ? ""
      : cohortAttempted === 0
        ? " — trailing-7d cohort still empty: no candidate decided inside the window was attempted this run"
        : ` — trailing-7d cohort still empty: ${cohortResolved}/${cohortAttempted} of the attempted candidates decided inside the window resolved at the venue (the rest are still open or archived)`;

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
  const consecutive = consecutiveDaysAtOrBelow(decaySeries, DRIFT_DECAY_BAR_USD);
  // ---- instrument v2 (2026-10-11): the SECOND series, one row per SIGNAL ------
  // Same rule, same shape, different basis. The pre-registered bar above keeps
  // reading the poll-row series (that is the quantity it was pre-registered
  // against on 2026-09-20); this one is published alongside it so a
  // per-opportunity read exists at all.
  let perSignalSeries: Array<{ day: string; avgPnlPerTradeExDust: number | null }> = [];
  const perSignalRow = {
    ts: new Date().toISOString(),
    day: new Date().toISOString().slice(0, 10),
    avgPnlPerTradeExDust: dSummary.avgPnlPerTradeExDustPerSignal,
    marked: dSummary.signalsSettled,
    dustExcluded: dSummary.dustExcludedPerSignal,
    basis: "per_signal",
  };
  try {
    fs.appendFileSync(DRIFT_DECAY_SERIES_PER_SIGNAL_FILE, JSON.stringify(perSignalRow) + "\n");
    const byDay = new Map<string, { day: string; avgPnlPerTradeExDust: number | null }>();
    for (const r of fs
      .readFileSync(DRIFT_DECAY_SERIES_PER_SIGNAL_FILE, "utf-8")
      .split("\n")
      .filter((l) => l.trim().length > 0)
      .map((l) => JSON.parse(l) as { day: string; avgPnlPerTradeExDust: number | null })) {
      byDay.set(r.day, r);
    }
    perSignalSeries = [...byDay.values()].sort((a, b) => (a.day < b.day ? -1 : 1));
  } catch (e) {
    logError(`[DRIFT-DECAY] per-signal series write/read failed: ${e instanceof Error ? e.message : e}`);
  }
  const perSignalConsecutive = consecutiveDaysAtOrBelow(perSignalSeries, DRIFT_DECAY_BAR_USD);
  const perSignalCohort = dSummary.avgPnlPerTradeExDustLast7dCohortPerSignal;
  const perSignalCohortOk = perSignalCohort !== null && perSignalCohort <= DRIFT_DECAY_BAR_USD;
  const decayBarPerSignal = {
    thresholdUsd: DRIFT_DECAY_BAR_USD,
    daysRequired: DRIFT_DECAY_DAYS,
    consecutiveDaysAtOrBelow: perSignalConsecutive,
    cohort7d: perSignalCohort,
    cohort7dMarked: dSummary.cohort7dMarkedPerSignal,
    cohortAtOrBelow: perSignalCohortOk,
    tripped: perSignalConsecutive >= DRIFT_DECAY_DAYS && perSignalCohortOk,
    seriesDays: perSignalSeries.length,
    recent: perSignalSeries.slice(-DRIFT_DECAY_DAYS).map((r) => ({ day: r.day, avgPnlPerTradeExDust: r.avgPnlPerTradeExDust })),
    basis: "per_signal (one row per marketId|outcome|wallet, earliest poll)",
    rule: "Same pre-registered 2026-09-20 rule and threshold, read on the per-signal basis. Published ALONGSIDE decayBar, which keeps reading the poll-row series the rule was pre-registered against; repointing decayBar at this basis is a separate, un-taken decision (card drift-shadow-instrument-defects).",
  };
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
    JSON.stringify({ ...dSummary, decayBar, decayBarPerSignal }, null, 2)
  );
  log(
    `shadow-drift: +${dResolved} marked this run (cap ${driftLimit}/run${DRIFT_TEST_LIMIT === null ? "" : " via DRIFT_TEST_LIMIT"}, ` +
      `backlog ${dPending.size}; walk ${attempted.length}/${walk.eligible} eligible, decided ${walkWindow}, ` +
      `${walk.neverAttempted} never attempted before, ${walk.heldBack} held by the ${ATTEMPT_FAIL_LIMIT}-fail/${ATTEMPT_RETRY_HOURS}h retry; ` +
      `trailing-7d attempted ${cohortAttempted}, resolved ${cohortResolved}${cohortNote}). ` +
      `Gate counterfactual: ${dSummary.candidates} would-have entries, ` +
      `${dSummary.marked} settled (${dSummary.wins} wins, ` +
      `${dSummary.winRate === null ? "—" : (dSummary.winRate * 100).toFixed(1) + "%"}), ` +
      `$${dSummary.wouldHavePnl.toFixed(2)} @ $${dSummary.stakeUsd}/trade (` +
      `${dSummary.avgPnlPerTrade === null ? "—" : "$" + dSummary.avgPnlPerTrade.toFixed(2)}/trade, ` +
      `${dSummary.avgPnlPerTradeExDust === null ? "—" : "$" + dSummary.avgPnlPerTradeExDust.toFixed(2)}/trade ex-dust ` +
      `[${dSummary.dustExcluded} rows below $${dSummary.dustMinEntryPrice}]). ` +
      `Per-signal: ${dSummary.signalsSettled} settled of ${dSummary.signals} signals, ` +
      `${dSummary.avgPnlPerTradeExDustPerSignal === null ? "—" : "$" + dSummary.avgPnlPerTradeExDustPerSignal.toFixed(2)}/trade ex-dust ` +
      `[cohort7d ${dSummary.avgPnlPerTradeExDustLast7dCohortPerSignal === null ? "—" : "$" + dSummary.avgPnlPerTradeExDustLast7dCohortPerSignal.toFixed(2)} ` +
      `over ${dSummary.cohort7dMarkedPerSignal}]. ` +
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

  // ---- minConfidence gate shadow (2026-09-20 change 2) ----------------------
  // Same machinery again: every decision the confidence bar rejected, marked to
  // settlement so the bar can be judged on outcomes instead of mention counts.
  const lRows = readLowConfRows();
  const lCandidates = lRows.filter((r) => r.type === "candidate");
  const lAlready = new Set(
    lRows.filter((r) => r.type === "resolve").map((r) => `${r.marketId}|${r.outcome}`)
  );
  const lPending = new Map<string, { marketId: string; outcome: string }>();
  for (const c of lCandidates) {
    const key = `${c.marketId}|${c.outcome}`;
    if (!lAlready.has(key)) lPending.set(key, { marketId: String(c.marketId), outcome: String(c.outcome) });
  }
  let lResolved = 0;
  for (const { marketId, outcome } of capPending(lPending).values()) {
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
      LOWCONF_SHADOW_FILE,
      JSON.stringify({ ts: new Date().toISOString(), type: "resolve", marketId, outcome, value }) + "\n"
    );
    lResolved++;
  }
  const lSummary = summarizeLowConf(readLowConfRows());
  fs.writeFileSync(LOWCONF_SHADOW_SUMMARY_FILE, JSON.stringify(lSummary, null, 2));
  const bucketLine = Object.entries(lSummary.byConfidenceBucket)
    .map(([b, v]) => `${b}: ${v.n} (${v.marked} marked, $${v.wouldHavePnl.toFixed(2)})`)
    .join(" | ");
  log(
    `shadow-lowconf: +${lResolved} marked this run (backlog ${lPending.size}). ` +
      `Confidence-gate counterfactual: ${lSummary.candidates} rejected rows (` +
      `${lSummary.confidenceOnlyCandidates} blocked by confidence ALONE), ` +
      `${lSummary.marked} marked rows on ${lSummary.basis.markets} markets ` +
      `(${lSummary.basis.signals} copy signals), ` +
      `$${lSummary.wouldHavePnl.toFixed(2)} at $${lSummary.stakeUsd}/ticket ROW-LEVEL ` +
      `(one ticket per market|outcome|wallet: $${lSummary.basis.wouldHavePnlPerSignal.toFixed(2)}) ` +
      `(${lSummary.avgPnlPerTrade === null ? "—" : "$" + lSummary.avgPnlPerTrade.toFixed(2)}/row; ` +
      `confidence-only $${lSummary.confidenceOnly.wouldHavePnl.toFixed(2)} on ${lSummary.confidenceOnly.marked} settled) | ${bucketLine}. ` +
      `Summary: ${LOWCONF_SHADOW_SUMMARY_FILE}`
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
