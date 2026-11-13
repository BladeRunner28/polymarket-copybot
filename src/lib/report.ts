/**
 * Daily report generator. Builds the end-of-day summary Hermes sends to
 * Discord and stores it as a DailyReport row.
 *
 * 2026-09-11 (user-requested): the report covers a LOCAL CALENDAR DAY. It used
 * to take a UTC date label over a rolling "since the previous report" window, so
 * the 22:00 CDT run on Sep 10 stamped itself `2026-09-11` while summing
 * Sep 9 22:00 → Sep 10 22:00 — a figure matching neither the day the dashboard
 * shows nor the day bucket the C-200 phase ladder grades. Verified before the
 * switch: that row stored -105.24 (its own window reproduces it exactly) while
 * calendar Sep 10 closed at -37.97 for the same 52 trades.
 *
 * Semantics now:
 *   date   — local calendar date of the day being reported (never UTC)
 *   window — [00:00, 24:00) of that day, bucketed by `closedAt ?? resolvedAt`
 *            (TR-15 early exits book at closedAt) — the same rule as the
 *            ladder's c200DayKey and the Overview PnL cards, so all three agree
 *   day    — today when the job runs at/after noon, otherwise the day that just
 *            ended, so a 23:5x or a 00:0x schedule is safe either side of midnight
 *   tail   — bookings since the previous report that landed BEFORE the reported
 *            day began. A 22:00 run cannot see its own 22:00-24:00 window, so
 *            that slice is carried into the next report rather than vanishing
 *            (measured 1-6 trades/day, up to -$70.81 on 2026-09-09).
 */

import { prisma } from "./db";
import { computeBenchmarks, beatBlindOnMatchedBasis } from "./benchmarks";
import { computeEdgeCostSnapshot, edgeCostLines } from "./copy-cost";
import { sendDiscord } from "./discord";
import { dayWindow, reportDayOffset, rowsFinishedIn } from "./day-pnl";
import { payoffSummary, payoffCompanionText, type Payoff } from "./payoff";
import { selectionCaveatLine } from "./selection-caveat";
import { dedupeProposalText } from "./rules";
import * as fs from "fs";
import { join } from "path";

const SCAN_STATE_FILE = join(__dirname, "..", "..", "data", "scan-wallets-state.json");
const DRIFT_SUMMARY_FILE = join(__dirname, "..", "..", "data", "drift-shadow-summary.json");

/**
 * Drift-gate counterfactual + the pre-registered decay bar (tuning #31 rec 2,
 * approved 2026-09-20). The rec's verify line expected this value in the EOD log,
 * but the ex-dust figure is written by the hourly shadow marker into
 * copybot-shadow-longshot.log — so the number the bar is judged on never reached the
 * report. Surfaced here, read-only.
 */
function driftDecayLine(): string | undefined {
  try {
    const s = JSON.parse(fs.readFileSync(DRIFT_SUMMARY_FILE, "utf-8")) as {
      avgPnlPerTradeExDust?: number;
      marked?: number;
      avgPnlPerTradeExDustPerSignal?: number | null;
      signalsSettled?: number;
      decayBar?: { thresholdUsd?: number; daysRequired?: number; consecutiveDaysAtOrBelow?: number; cohort7d?: number | null; tripped?: boolean };
      decayBarPerSignal?: { consecutiveDaysAtOrBelow?: number; daysRequired?: number; cohort7d?: number | null; tripped?: boolean };
    };
    if (typeof s.avgPnlPerTradeExDust !== "number") return undefined;
    const b = s.decayBar;
    // 2026-10-21 self-audit: this printed `${consecutiveDaysAtOrBelow}/${daysRequired}
    // days` — on live data "16/7 days", a ratio above 1 that reads as "bar met"
    // while tripped=false, with the reason (the trailing-7d COHORT gate) left off
    // the line and a stray backslash from a mis-escaped `\\)`. State the streak
    // against its requirement and name which of the two pre-registered conditions
    // is holding the bar shut.
    const barThreshold = b?.thresholdUsd ?? 0.5;
    // 2026-11-13 self-audit: this line carries TWO cohort7d values — the per-poll
    // arm's and the per-signal arm's — and both printed under the bare label
    // "cohort7d". Live text: "... per-signal ... cohort7d $-0.81) · decay bar: 39
    // consecutive days ... · cohort7d $-0.73 — TRIPPED". Two numbers, one label,
    // no way for a reader (or a scraper) to say which population a cohort7d
    // figure belongs to; the per-signal arm also printed "bar 0/7d" with no
    // verdict at all, so its tripped state was invisible. Every cohort now names
    // its arm, every arm prints its verdict, and a negative amount renders
    // "-$0.81" instead of "$-0.81".
    const usdSigned = (v: number) => `${v < 0 ? "−" : ""}$${Math.abs(v).toFixed(2)}`;
    const cohort = b?.cohort7d;
    const cohortTxt = cohort === null || cohort === undefined ? "—" : usdSigned(cohort);
    const bar = b
      ? ` · decay bar (per-poll): ${b.consecutiveDaysAtOrBelow ?? 0} consecutive days at ≤$${barThreshold.toFixed(2)}` +
        ` (needs ${b.daysRequired ?? 7}) · cohort7d(per-poll) ${cohortTxt}` +
        (cohort !== null && cohort !== undefined && cohort > barThreshold
          ? ` (> bar, so the cohort gate holds it shut)`
          : "") +
        `${b.tripped ? " — TRIPPED" : " — not tripped"}`
      : "";
    // Instrument v2 (2026-10-11): the same counterfactual on its per-signal basis
    // (one row per market|outcome|wallet). The line above is a per-poll average —
    // a market that stays drifted is counted once per 10-minute tick — so quote
    // both, and never compare one against the other.
    const ps =
      typeof s.avgPnlPerTradeExDustPerSignal === "number"
        ? ` · per-signal ${s.avgPnlPerTradeExDustPerSignal >= 0 ? "+" : "−"}$${Math.abs(s.avgPnlPerTradeExDustPerSignal).toFixed(2)}/trade` +
          ` ex-dust (${s.signalsSettled ?? 0} settled signals` +
          `${s.decayBarPerSignal ? `, bar ${s.decayBarPerSignal.consecutiveDaysAtOrBelow ?? 0}/${s.decayBarPerSignal.daysRequired ?? 7}d, cohort7d(per-signal) ${s.decayBarPerSignal.cohort7d === null || s.decayBarPerSignal.cohort7d === undefined ? "—" : usdSigned(s.decayBarPerSignal.cohort7d)} — ${s.decayBarPerSignal.tripped ? "TRIPPED" : "not tripped"}` : ""})`
        : "";
    return `• Drift gate counterfactual: ${s.avgPnlPerTradeExDust >= 0 ? "+" : "−"}$${Math.abs(s.avgPnlPerTradeExDust).toFixed(2)}/trade ex-dust per poll (${s.marked ?? 0} marked)${ps}${bar}`;
  } catch {
    return undefined;
  }
}
const SCAN_PARTIALS_FILE = join(__dirname, "..", "..", "data", "scan-partials.jsonl");

/**
 * Wallet-scan coverage line (2026-09-20 tuning review #31 rec 3, user-approved).
 *
 * A partial profile run is silent otherwise: the scan job still prints a normal
 * completion line, so a report reader cannot tell a quiet cycle from 2 wallets
 * that stopped being profiled. Reads the scan job's own state file (latest run)
 * and event log (one row per partial) — measurement only, no behavior change.
 */
async function walletScanLine(now: Date): Promise<string | undefined> {
  let state: { lastRunAt?: string; profiled?: number; target?: number } | null = null;
  try {
    state = JSON.parse(fs.readFileSync(SCAN_STATE_FILE, "utf-8"));
  } catch {
    return undefined;
  }
  if (!state || typeof state.profiled !== "number") return undefined;
  // 2026-10-21 self-audit: this used to print `${profiled}/${target}` — but target
  // IS WALLET_SCAN_LIMIT (the per-run batch cap), not the pool the scan rotates
  // through. On live data that rendered "25/25 profiled", which reads as "every
  // wallet is profiled" while the pool is 3,540 wallets and the scan only ever
  // takes 25 an hour. The denominator was the batch, so the line could not show a
  // backlog at all. Print the batch, the pool and the >7d-stale count instead — a
  // rotating scan is honest about what it has NOT reached.
  let pool = 0;
  let stale7d = 0;
  try {
    const cutoff = new Date(now.getTime() - 7 * 86400000);
    [pool, stale7d] = await Promise.all([
      prisma.walletProfile.count({ where: { isDemo: false } }),
      prisma.walletProfile.count({
        where: { isDemo: false, OR: [{ lastScannedAt: null }, { lastScannedAt: { lt: cutoff } }] },
      }),
    ]);
  } catch {
    pool = 0;
  }
  // A reader must be able to tell "no partials" from "the partials log could not be
  // read" — the old `catch { partials7d = 0 }` printed a clean 0 either way.
  let partials: string;
  try {
    const cutoff = Date.now() - 7 * 86400000;
    const n = fs
      .readFileSync(SCAN_PARTIALS_FILE, "utf-8")
      .split("\n")
      .filter((l) => l.trim().length > 0)
      .map((l) => JSON.parse(l) as { ts?: string })
      .filter((r) => r.ts && new Date(r.ts).getTime() >= cutoff).length;
    partials = `${n} partial${n === 1 ? "" : "s"} in 7d`;
  } catch {
    partials = "partials log UNREADABLE";
  }
  const short = typeof state.target === "number" && state.profiled < state.target;
  const when = state.lastRunAt
    ? new Date(state.lastRunAt).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false })
    : "?";
  const poolTxt = pool ? ` · pool ${pool.toLocaleString("en-US")}, ${stale7d} stale >7d` : " · pool count UNAVAILABLE";
  return `• Wallet scan: ${short ? "⚠️ " : ""}${state.profiled} profiled last run (${when}${short ? ` of ${state.target} attempted` : ""})${poolTxt} · ${partials}`;
}

/**
 * Sizing range AS SIZED, per bot — 2026-10-21 self-audit.
 *
 * The report used to print two HARDCODED strings: STANDARD "$0.25 - $20.00" and
 * BANKROLL_200 "$0.10 - $10.00". Both were the safety clamp in safety.ts
 * BOT_LIMITS, not what the lanes size, and both were false against the live book:
 * every STANDARD trade opened in the 14 days to 2026-10-21 was exactly $18.00
 * (rules.highScoreCapUsd/sweetSpotSizeUsd = 18), and C-200 opened up to $100.00
 * — ten times the printed ceiling. A hardcoded range also cannot follow a rule
 * change, which is how it drifted. Derived from the opened book instead; the
 * window and n are printed so the number can be re-queried.
 */
const SIZING_RANGE_DAYS = 7;

/**
 * `failed` is carried OUT of the read, not swallowed.
 *
 * 2026-11-13 self-audit: this returned an empty map on any error, and
 * sizingRangeLine renders an empty map as "no <BOT> trade opened in the last
 * 7d" — so a failed aggregate read printed as a CLEAN ZERO, visibly identical
 * to a quiet week. The neighbouring wallet-scan read was fixed for exactly this
 * on 2026-10-21 ("the old `catch { partials7d = 0 }` printed a clean 0 either
 * way"); this one kept the defect. Live on 2026-11-13 the line reads
 * "$4.00–$20.00 (opened last 7d, n=56)", so the happy path is exercised — the
 * failure path is what had no denominator.
 */
type SizingRanges = {
  ranges: Map<string, { min: number; max: number; n: number }>;
  failed: boolean;
  error?: string;
};

async function observedSizingRanges(now: Date): Promise<SizingRanges> {
  const since = new Date(now.getTime() - SIZING_RANGE_DAYS * 86400000);
  const out = new Map<string, { min: number; max: number; n: number }>();
  try {
    const rows = await prisma.paperTrade.groupBy({
      by: ["botId"],
      where: { isDemo: false, openedAt: { gte: since } },
      _min: { simulatedPositionSize: true },
      _max: { simulatedPositionSize: true },
      _count: { _all: true },
    });
    for (const r of rows) {
      const min = r._min.simulatedPositionSize;
      const max = r._max.simulatedPositionSize;
      if (min === null || max === null || r._count._all === 0) continue;
      out.set(r.botId, { min, max, n: r._count._all });
    }
  } catch (e) {
    return { ranges: out, failed: true, error: e instanceof Error ? e.message : String(e) };
  }
  return { ranges: out, failed: false };
}

export function sizingRangeLine(botId: string, r: SizingRanges): string {
  if (r.failed) {
    const why = (r.error ?? "unknown").replace(/\s+/g, " ").slice(0, 90);
    return `• Sizing Range: UNAVAILABLE — the opened-window read FAILED (${why}); this is NOT "no trades"`;
  }
  const s = r.ranges.get(botId);
  if (!s) return `• Sizing Range: no ${botId} trade opened in the last ${SIZING_RANGE_DAYS}d`;
  const span = s.min === s.max ? `$${s.min.toFixed(2)}` : `$${s.min.toFixed(2)}–$${s.max.toFixed(2)}`;
  return `• Sizing Range: ${span} (opened last ${SIZING_RANGE_DAYS}d, n=${s.n})`;
}

/** Local calendar date (YYYY-MM-DD) — the label is the day the report covers. */
function localDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/**
 * Local HH:MM. A count that is only true up to the moment it ran has to say so — the report's
 * header names a calendar day (00:00 → 24:00), and the 22:00 run can never contain the last two
 * hours of it. Measured 2026-10-28: the day closed with 1,011 decisions but the 22:00 report could
 * only see 976 of them, with nothing on the line to say which window the number described.
 */
function localHm(d: Date): string {
  return d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
}

/**
 * One rule decision, one sentence — on the READ side.
 *
 * The writer stopped storing a reason once per field it touched on 2026-10-28 (05836b2), but the
 * rows written before that still hold the repeats, and this report trusts whatever string it finds.
 * Live: v69 stored its reason twice (583 chars), v68 five times (1,477), v29 twenty (2,577). The
 * 10-28 report printed v69's sentence in the "Rule changes" bullet AND again in "Top lesson" —
 * 1,166 of ~4,100 characters — because both lines read `c.reason` verbatim.
 *
 * Collapse exact duplicate " | "-separated segments here rather than rewriting history: every
 * distinct reason survives, in first-seen order, and the text itself is untouched.
 */
export function oneReason(reason: string): string {
  return dedupeProposalText(String(reason ?? "").split(" | "));
}

/**
 * Drop a rule reason's OWN leading version token, because the caller already prints one.
 *
 * 2026-11-04 (self-audit): the "Rule changes" bullet renders `v${version}: ${reason}` — but 14 of
 * the 70 stored reasons already open with their own version ("v71: the band map was lane-blind",
 * "v64 (user-approved 2026-10-20): give STANDARD the open-position..."), so the bullet printed the
 * version twice. Live on the 11-03 dry run: "v71: v71: the band map was lane-blind". The token is
 * stripped ONLY when it names the row's own version: v69's reason opens "v68 gave the same 1.5x
 * up-weight" and v70's opens "v66's standard stale exit recycles capital" — those are references to
 * an EARLIER version and must survive verbatim, so a version-blind regex would corrupt them.
 */
export function withoutOwnVersion(reason: string, version: number | string): string {
  const text = String(reason ?? "");
  const stripped = text.replace(new RegExp(`^\\s*v${String(version)}(?![0-9])\\s*:?\\s*`), "");
  // Never hand back an empty reason (a bare "v71:" row would otherwise erase the sentence).
  return stripped.trim().length > 0 ? stripped : text;
}

export type { Payoff } from "./payoff";

/**
 * 2026-10-28 (self-audit, prereg Part C): the EOD report printed "Win Rate: 63.5%" with no
 * population, no clock and no payoff companions, directly under a header that says the report covers
 * one calendar day — so a LIFETIME figure read as today's. That is the exact reporting defect that
 * turned a deliberate shift toward higher-payoff positions into "a large drop in wins": win rate fell
 * 71.7% (Jul) -> 41.2% (Oct) while ROI rose to the best month in the series, because average win went
 * $6.67 -> $23.30 against average loss -$9.05 -> -$12.80.
 *
 * 2026-11-03 (winrate-payoff-companion-reporting): the companions are no longer a SECOND line that a
 * reader could skip. They ride on the win-rate line itself via payoffCompanionText, and the
 * arithmetic moved to src/lib/payoff.ts — the same function the dashboard home, the rule-change
 * evidence and the fact sheet use, so the four surfaces cannot drift into different populations.
 */
export function payoffStats(
  rows: { realizedPnl: number | null; simulatedPositionSize: number; closedAt: Date | null; resolvedAt: Date | null }[]
): Payoff {
  return payoffSummary(
    rows.map((t) => ({
      pnl: t.realizedPnl,
      stake: t.simulatedPositionSize ?? 0,
      at: t.closedAt ?? t.resolvedAt,
    }))
  );
}

/**
 * The win rate WITH its clock, population, level and payoff companions, on ONE line (prereg Part C).
 * A caller cannot print the rate without them, because this is the only thing that renders one.
 */
export function winRateLine(p: Payoff, openCount: number): string {
  const rate = p.n ? `• Win Rate: ${(p.winRate * 100).toFixed(1)}%` : "• Win Rate: undefined";
  const basis = payoffCompanionText(p, localDate);
  return (
    `${rate} (${basis}) | Open Positions: ${openCount}` +
    ` — win rate alone cannot separate payoff from decay; the three beside it can`
  );
}

export async function generateDailyReport(
  opts: { dryRun?: boolean } = {}
): Promise<{ id: string; summary: string; sent: boolean }> {
  const now = new Date();
  const dayOffset = reportDayOffset(now);
  const { start: dayStart, end: dayEnd } = dayWindow(dayOffset, now);
  const date = localDate(dayStart);
  // False on the normal 22:00 run: the reported day still has its last hours to come, so every
  // count scoped to [dayStart, dayEnd) is a partial day and says so on the line.
  const dayElapsed = now >= dayEnd;

  // Carry-over slice of the previous day that ran after its own report:
  // [previous report, dayStart). No previous report ⇒ nothing to carry.
  const prevReport = await prisma.dailyReport.findFirst({ orderBy: { createdAt: "desc" } });
  const tailStart =
    prevReport?.createdAt && prevReport.createdAt < dayStart ? prevReport.createdAt : dayStart;

  const [openTrades, finishedFetched, decisionsToday, ruleChangesToday, allFinished, bankrolls] =
    await Promise.all([
      // 2026-10-28 (self-audit): isDemo=false. Without it the printed "Open Positions" counted 18
      // seeded demo rows (487 shown, 469 real), and any demo row would have entered lifetime PnL and
      // win rate. Every other read script in the repo already scopes on isDemo=0; the EOD report was
      // the only instrument that did not.
      prisma.paperTrade.findMany({ where: { status: "open", isDemo: false } }),
      // Fetched from tailStart so one query serves both the reported day and the
      // carry-over slice; bucketing happens in JS because Prisma cannot express
      // `closedAt ?? resolvedAt` in a where clause.
      prisma.paperTrade.findMany({
        where: {
          status: { in: ["closed", "resolved"] },
          // TR-15 (2026-09-03): include early-exit trades — realized PnL books
          // at closedAt (resolvedAt NULL), so a resolvedAt-only filter under-
          // stated "today" for both bots on exit-bleed days.
          OR: [{ resolvedAt: { gte: tailStart } }, { closedAt: { gte: tailStart } }],
        },
      }),
      // 2026-10-29 (self-audit): the day's own CEILING. Both of these reads carried `gte: dayStart`
      // alone, so "today" was really "midnight onward": a run after midnight swept the next day's
      // rows into the reported day, and the same rows were then counted AGAIN in their own day's
      // report. Measured on the 10-28 dry run at 06:50 on 10-29: "Signals today: 1071 (copy 16 /
      // watch 0 / skip 1055)" against 1011 decisions that actually fall inside 10-28 (copy 11 /
      // watch 0 / skip 1000) — 60 phantom rows, all of 10-29. The catch-up chain
      // (copybot-eod-catchup.sh) re-runs report:daily by design, so this was not hypothetical.
      // isDemo: false on the journal for the same reason the open-position read needed it — 24
      // seeded demo decisions exist and none of them are signals we acted on.
      prisma.decisionJournal.findMany({
        where: { createdAt: { gte: dayStart, lt: dayEnd }, isDemo: false },
      }),
      prisma.ruleChange.findMany({
        where: { createdAt: { gte: dayStart, lt: dayEnd } },
        include: { newRuleSet: true },
      }),
      // v52 (tuning review #19 rec 3, user-approved 2026-09-08): lifetime
      // totals must include early-exit 'closed' rows — realized PnL books at
      // closedAt (resolvedAt NULL), so a resolved-only filter overstated C-200
      // EOD net worth (~$960: its closed-at-a-loss early exits were missing)
      // and understated STANDARD (~$1,082: its closed winners were missing).
      prisma.paperTrade.findMany({ where: { status: { in: ["resolved", "closed"] }, isDemo: false } }),
      prisma.botBankroll.findMany(),
    ]);

  // Calendar-day bucket and the carry-over tail, both on the ladder's rule
  // (closedAt ?? resolvedAt). Nothing later in this report may re-window them.
  const resolvedToday = rowsFinishedIn(finishedFetched, dayStart, dayEnd);
  const tailRows = tailStart < dayStart ? rowsFinishedIn(finishedFetched, tailStart, dayStart) : [];

  const standardOpen = openTrades.filter((t) => t.botId === "STANDARD");
  // kalshi-reprice-92 (2026-09-05, approved): legacy Kalshi rows re-priced off
  // the phantom 0.52 stub (kalshiRealized −$50.70 → −$37.99, breaker floor −$50
  // cleared) — TR-17 venue exclusion lifted, Kalshi re-joins C-200 PnL.
  const compoundOpen = openTrades.filter((t) => t.botId === "BANKROLL_200");

  const stdResolvedToday = resolvedToday.filter((t) => t.botId === "STANDARD");
  const cmpResolvedToday = resolvedToday.filter((t) => t.botId === "BANKROLL_200");

  const stdFinished = allFinished.filter((t) => t.botId === "STANDARD");
  const cmpFinished = allFinished.filter((t) => t.botId === "BANKROLL_200");

  const stdPnlToday = stdResolvedToday.reduce((a, t) => a + (t.realizedPnl ?? 0), 0);
  const stdTotalPnl =
    stdFinished.reduce((a, t) => a + (t.realizedPnl ?? 0), 0) +
    standardOpen.reduce((a, t) => a + t.unrealizedPnl, 0);
  const stdPayoff = payoffStats(stdFinished);
  const cmpPayoff = payoffStats(cmpFinished);
  // Win rate and its companions now share one source, so the printed rate cannot drift from the
  // payoff printed beside it (prereg Part C, 2026-10-28).
  const stdWinRate = stdPayoff.winRate;

  const cmpPnlToday = cmpResolvedToday.reduce((a, t) => a + (t.realizedPnl ?? 0), 0);
  const cmpTotalPnl =
    cmpFinished.reduce((a, t) => a + (t.realizedPnl ?? 0), 0) +
    compoundOpen.reduce((a, t) => a + t.unrealizedPnl, 0);
  const cmpWinRate = cmpPayoff.winRate;

  // Tail totals reported separately so the two bots' day figures stay clean.
  const tailCmp = tailRows.filter((t) => t.botId === "BANKROLL_200").reduce((a, t) => a + (t.realizedPnl ?? 0), 0);
  const tailStd = tailRows.filter((t) => t.botId === "STANDARD").reduce((a, t) => a + (t.realizedPnl ?? 0), 0);

  const cmpBankroll = bankrolls.find((b) => b.botId === "BANKROLL_200");
  const totalCmpCapital = cmpBankroll ? cmpBankroll.principal + cmpTotalPnl : 0;

  // Bankroll ledger invariant: cash should equal principal + realized − open
  // notional. Surface drift so accounting bugs show up in the daily report.
  let ledgerNote: string | undefined;
  if (cmpBankroll) {
    const openNotional = compoundOpen.reduce((a, t) => a + t.simulatedPositionSize, 0);
    const expectedCash = cmpBankroll.principal + (cmpBankroll.realizedPnl ?? 0) - openNotional;
    const cashGap = Math.round((cmpBankroll.cashBalance - expectedCash) * 100) / 100;
    if (Math.abs(cashGap) > 5) {
      ledgerNote = `• ⚠️ BANKROLL_200 cash ledger off by $${cashGap.toFixed(2)} vs paper-trade ledger (run reconcile-bankroll)`;
    }
  }

  const copied = decisionsToday.filter((d) => d.decision === "paper_copy").length;
  const watched = decisionsToday.filter((d) => d.decision === "watchlist").length;
  const skipped = decisionsToday.filter((d) => d.decision === "skip").length;

  // 2026-09-15 tuning review #26 rec 5 (user-approved): STANDARD's book is 73.3%
  // of open rows / 69.1% of open cost in legacy duplicate stacks — a
  // (wallet, market, outcome) group can hold a dozen rows from the July
  // accumulation era, so one stack can look like edge. Report the day both ways
  // and name the biggest stack when it dominates. A day row counts as "stacked"
  // when its key holds more than one row in the STANDARD book (open or finished)
  // — the group, not an "open twin", is what makes it a stack; the review's
  // verify line reconciles against whichever figure is printed (day − stacked).
  const stackKey = (t: { walletAddress: string; marketId: string; outcome: string }) =>
    `${t.walletAddress}|${t.marketId}|${t.outcome}`;
  const bookKeyCounts = new Map<string, number>();
  for (const t of [...standardOpen, ...stdFinished]) {
    const k = stackKey(t);
    bookKeyCounts.set(k, (bookKeyCounts.get(k) ?? 0) + 1);
  }
  const isStack = (t: { walletAddress: string; marketId: string; outcome: string }) =>
    (bookKeyCounts.get(stackKey(t)) ?? 0) > 1;
  const stackedDayRows = stdResolvedToday.filter(isStack);
  const stackedDayPnl = stackedDayRows.reduce((a, t) => a + (t.realizedPnl ?? 0), 0);
  const stdNetOfStacks = stdPnlToday - stackedDayPnl;
  const byStackKey = new Map<string, number>();
  for (const t of stdResolvedToday.filter(isStack)) {
    const k = stackKey(t);
    byStackKey.set(k, (byStackKey.get(k) ?? 0) + (t.realizedPnl ?? 0));
  }
  const largestStack = [...byStackKey.entries()].sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))[0];
  const largestStackShare = largestStack && stdPnlToday !== 0 ? Math.abs(largestStack[1] / stdPnlToday) : 0;

  const best = [...stdResolvedToday].sort((a, b) => (b.realizedPnl ?? 0) - (a.realizedPnl ?? 0))[0];
  // (a `worst` twin was computed here and never printed anywhere — removed
  // 2026-11-13 so the line a reader trusts is not sitting next to dead code)

  // Wallet performance today (Standard strategy used for benchmarks)
  const byWallet = new Map<string, number>();
  for (const t of stdResolvedToday) {
    byWallet.set(t.walletAddress, (byWallet.get(t.walletAddress) ?? 0) + (t.realizedPnl ?? 0));
  }
  const walletsSorted = [...byWallet.entries()].sort((a, b) => b[1] - a[1]);
  const bestWallets = walletsSorted.slice(0, 3).map(([a, p]) => ({ address: a, pnl: p }));
  const worstWallets = walletsSorted.slice(-3).reverse().map(([a, p]) => ({ address: a, pnl: p }));

  const bench = await computeBenchmarks();
  // MATCHED BASIS (2026-10-29, label-integrity-bot-vs-blind-bases): the verdict compares
  // like with like -- the copy decisions priced hold-to-resolution (OUTCOME) against blind
  // copy on the same formula and the same flat stake. The exit book is printed below,
  // labelled, and is NOT part of this verdict: it answers a different question (what our
  // exits earned).
  const beatBlind = beatBlindOnMatchedBasis(bench);

  // polycopy-edge-cost-pair (2026-09-23): the report quoted realized PnL as if
  // our modelled fill were free. It is not — the booked entry is a QUOTE read at
  // scoring time and lands BELOW the wallet's own fill on C-200 (measured
  // −3.03%/leg lifetime, 2026-09-23), the opposite sign a real copier sees. Both
  // numbers are printed on the same legs so neither can be read alone.
  // Measurement only: no threshold, rule, sizing or gate consumes this.
  const edgeCost = await computeEdgeCostSnapshot(now);
  const edgeBlock = edgeCostLines(edgeCost);

  // 2026-11-04 (self-audit): the lesson used to BE the rule reason — `oneReason(c.reason)` — so a
  // day with a rule change printed the same 245-char sentence twice, once under "Rule changes" and
  // again under "Top lesson" (the exact defect the 10-28 note above describes, which only collapsed
  // repeats WITHIN one string). The rule bullet is the place that sentence lives; this line points
  // at it. Filter read is unchanged and still printed on days with no rule change.
  const lesson =
    ruleChangesToday.length > 0
      ? `the rule change above (v${ruleChangesToday[0].newRuleSet.version}) is the day's lesson — its evidence is on that line, not restated here`
      : bench.avoidedLosers > bench.missedWinners
        ? "Filtering is avoiding more losers than it misses winners — filters are earning their keep"
        : "Watch for missed winners — filters may be too strict";

  // 2026-11-13 self-audit: `fmt` printed the sign AFTER the dollar sign — live
  // 2026-11-12 report read "PnL Today: $-9.00" and "Best trade: ... $-9.00" — so
  // the one number a reader parses at a glance was malformed on every losing
  // lane. Sign now leads: "−$9.00". Zero still prints without a sign.
  const fmt = (n: number) => `${n > 0 ? "+" : n < 0 ? "−" : ""}$${Math.abs(n).toFixed(2)}`;
  // A value printed AFTER a literal "−" must not carry its own sign: `fmt(-24.4)` there read
  // "day +$93.22 − $-24.40" (2026-11-11 report), a double negative in an arithmetic line the
  // reader is invited to check. Parenthesise, don't strip, so the sign of the subtracted term
  // stays visible: "− (−$24.40)".
  const fmtSub = (n: number) => (n < 0 ? `(−$${Math.abs(n).toFixed(2)})` : fmt(n));
  // A stake is not a signed number: `fmt` would print "$121,712.42 staked" as "+$121712.42 staked".
  const usd = (n: number) => `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const short = (a: string) => `${a.slice(0, 6)}…${a.slice(-4)}`;
  // Derived, not hardcoded (2026-10-21 self-audit — see observedSizingRanges).
  const sizingRanges = await observedSizingRanges(now);
  const walletScan = await walletScanLine(now);

  const summary = [
    `**📊 CopyBot Comparative EOD Report — ${date}**`,
    `_${date} 00:00 → 24:00 local · calendar day (closedAt ?? resolvedAt)${dayOffset < 0 ? " — day that just ended" : ""}_`,
    ``, 
    `**🤖 STANDARD Bot (Infinite Pool):**`,
    `• PnL Today: ${fmt(stdPnlToday)} | Total PnL: ${fmt(stdTotalPnl)}`,
    winRateLine(stdPayoff, standardOpen.length),
    sizingRangeLine("STANDARD", sizingRanges),
    `• Net of legacy duplicate stacks: ${fmt(stdNetOfStacks)} (day ${fmt(stdPnlToday)} − ${fmtSub(stackedDayPnl)} from ${stackedDayRows.length} stacked row${stackedDayRows.length === 1 ? "" : "s"}; stack = key with >1 row in the book)`,
    largestStack && largestStackShare > 0.5
      ? `• ⚠️ Largest single stack ${fmt(largestStack[1])} = ${(largestStackShare * 100).toFixed(0)}% of the day's STANDARD PnL (${largestStack[0].split("|")[1]}) — do not read it as edge`
      : undefined,
    ``,
    `**⚖️ BANKROLL_200 Bot (Compounding Pool):**`,
    `• PnL Today: ${fmt(cmpPnlToday)} | Total PnL: ${fmt(cmpTotalPnl)}`,
    winRateLine(cmpPayoff, compoundOpen.length),
    sizingRangeLine("BANKROLL_200", sizingRanges),
    `• Available Cash: $${cmpBankroll ? Math.max(0, cmpBankroll.cashBalance).toFixed(2) : "0.00"} | Current Net Worth: $${totalCmpCapital.toFixed(2)}`,
    ledgerNote,
    ...(edgeBlock.length ? [``, ...edgeBlock] : []),
    ``,
    `**System Activity:**`,
    `• Signals today: ${decisionsToday.length} (copy ${copied} / watch ${watched} / skip ${skipped})${dayElapsed ? "" : ` — counted 00:00→${localHm(now)} local; the rest of the day is not in this count`}`,
    // 2026-11-13 self-audit: this read "Best trade: 0x885f…8ed9 $-9.00" on 2026-11-12 —
    // the day's best STANDARD trade was a LOSS, because the day had exactly ONE
    // resolved STANDARD trade. "Best" over a sample of one is arithmetically right and
    // reads as a winner; the population and the lane were both unstated. Name them.
    best
      ? `• Best trade (STANDARD, best of ${stdResolvedToday.length} resolved today): ${short(best.walletAddress)} ${fmt(best.realizedPnl ?? 0)} on ${best.marketId}`
      : `• Best trade: none resolved today`,
    `• Bot vs blind copy (matched basis: hold to resolution, flat $10 both sides): ${beatBlind ? "✅ bot beat blind copying" : "⚠️ blind copy did better"} per dollar staked — copied decisions ${(bench.botFilteredOutcome.roi * 100).toFixed(2)}% of ${usd(bench.botFilteredOutcome.totalCost)} (n=${bench.botFilteredOutcome.resolvedCount} reviewed copies of ${bench.botFilteredOutcome.count}; unreviewed copies are not imputed) vs blind ${(bench.blindCopy.roi * 100).toFixed(2)}% of ${usd(bench.blindCopy.totalCost)} (n=${bench.blindCopy.resolvedCount} of ${bench.blindCopy.count} signals — the reviewed ones)`,
    `• Book on its own basis (EXIT: early exits count, own stake): ${(bench.botFiltered.roi * 100).toFixed(2)}% of ${usd(bench.botFiltered.totalCost)} staked, n=${bench.botFiltered.resolvedCount} settled legs — NOT comparable to the blind arm above`,
    // tradememory-deflated-sharpe (APPROVED 2026-10-21, Lane B): the pre-registered
    // decision rule says p >= 0.05 => every ladder/phase claim carries the
    // "not distinguishable from selection" caveat in the report itself. Read from
    // the measured artifact, and say NOT MEASURED if it is missing -- a missing
    // measurement must not read as a clean verdict.
    selectionCaveatLine(),
    ruleChangesToday.length
      ? `• Rule changes: ${ruleChangesToday.length} — ${ruleChangesToday.map((c) => `v${c.newRuleSet.version}: ${withoutOwnVersion(oneReason(c.reason), c.newRuleSet.version)}`).join("; ")}`
      : `• Rule changes: none`,
    `• Top lesson: ${lesson}`,
    walletScan,
    driftDecayLine(),
    tailRows.length > 0
      ? `• Late tail carried from ${localDate(tailStart)} (booked after its previous report): C-200 ${fmt(tailCmp)} / STANDARD ${fmt(tailStd)} — ${tailRows.length} trades`
      : undefined,
  ]
    .filter((line) => line !== undefined && line !== null)
    .join("\n");

  // Dry run (report-daily.ts --dry-run): build and print the report but touch
  // neither Discord nor the DailyReport table.
  if (opts.dryRun) {
    return { id: "dry-run", summary, sent: false };
  }

  const sent = await sendDiscord(summary);

  const report = await prisma.dailyReport.upsert({
    where: { date },
    create: {
      date,
      paperPnl: Math.round(stdPnlToday * 100) / 100,
      winRate: Math.round(stdWinRate * 1000) / 1000,
      compoundingPnl: Math.round(cmpPnlToday * 100) / 100,
      compoundingWinRate: Math.round(cmpWinRate * 1000) / 1000,
      openPositions: openTrades.length,
      newSignals: decisionsToday.length,
      copiedSignals: copied,
      watchedSignals: watched,
      skippedSignals: skipped,
      bestWalletsJson: JSON.stringify(bestWallets),
      worstWalletsJson: JSON.stringify(worstWallets),
      ruleChangesJson: JSON.stringify(
        ruleChangesToday.map((c) => ({ version: c.newRuleSet.version, reason: c.reason }))
      ),
      summary,
      sentToDiscord: sent,
    },
    update: {
      paperPnl: Math.round(stdPnlToday * 100) / 100,
      winRate: Math.round(stdWinRate * 1000) / 1000,
      compoundingPnl: Math.round(cmpPnlToday * 100) / 100,
      compoundingWinRate: Math.round(cmpWinRate * 1000) / 1000,
      openPositions: openTrades.length,
      newSignals: decisionsToday.length,
      copiedSignals: copied,
      watchedSignals: watched,
      skippedSignals: skipped,
      summary,
      sentToDiscord: sent,
    },
  });

  return { id: report.id, summary, sent };
}
