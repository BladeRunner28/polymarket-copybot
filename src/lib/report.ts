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
import { computeBenchmarks } from "./benchmarks";
import { computeEdgeCostSnapshot, edgeCostLines } from "./copy-cost";
import { sendDiscord } from "./discord";
import { dayWindow, reportDayOffset, rowsFinishedIn } from "./day-pnl";
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
      decayBar?: { thresholdUsd?: number; daysRequired?: number; consecutiveDaysAtOrBelow?: number; cohort7d?: number | null; tripped?: boolean };
    };
    if (typeof s.avgPnlPerTradeExDust !== "number") return undefined;
    const b = s.decayBar;
    const bar = b
      ? ` · decay bar ${b.consecutiveDaysAtOrBelow ?? 0}/${b.daysRequired ?? 7} days at ≤$${(b.thresholdUsd ?? 0.5).toFixed(2)}` +
        ` (cohort7d ${b.cohort7d === null || b.cohort7d === undefined ? "—" : "$" + b.cohort7d.toFixed(2)}\)${b.tripped ? " — TRIPPED" : ""}`
      : "";
    return `• Drift gate counterfactual: ${s.avgPnlPerTradeExDust >= 0 ? "+" : "−"}$${Math.abs(s.avgPnlPerTradeExDust).toFixed(2)}/trade ex-dust (${s.marked ?? 0} marked)${bar}`;
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
function walletScanLine(): string | undefined {
  let state: { lastRunAt?: string; profiled?: number; target?: number } | null = null;
  try {
    state = JSON.parse(fs.readFileSync(SCAN_STATE_FILE, "utf-8"));
  } catch {
    return undefined;
  }
  if (!state || typeof state.profiled !== "number") return undefined;
  let partials7d = 0;
  try {
    const cutoff = Date.now() - 7 * 86400000;
    partials7d = fs
      .readFileSync(SCAN_PARTIALS_FILE, "utf-8")
      .split("\n")
      .filter((l) => l.trim().length > 0)
      .map((l) => JSON.parse(l) as { ts?: string })
      .filter((r) => r.ts && new Date(r.ts).getTime() >= cutoff).length;
  } catch {
    partials7d = 0;
  }
  const covered = `${state.profiled}/${state.target ?? "?"}`;
  const complete = state.profiled === state.target;
  const when = state.lastRunAt
    ? new Date(state.lastRunAt).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false })
    : "?";
  return `• Wallet scan: ${complete ? "" : "⚠️ "}${covered} profiled (last run ${when}) · ${partials7d} partial${partials7d === 1 ? "" : "s"} in 7d`;
}

/** Local calendar date (YYYY-MM-DD) — the label is the day the report covers. */
function localDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export async function generateDailyReport(
  opts: { dryRun?: boolean } = {}
): Promise<{ id: string; summary: string; sent: boolean }> {
  const now = new Date();
  const dayOffset = reportDayOffset(now);
  const { start: dayStart, end: dayEnd } = dayWindow(dayOffset, now);
  const date = localDate(dayStart);

  // Carry-over slice of the previous day that ran after its own report:
  // [previous report, dayStart). No previous report ⇒ nothing to carry.
  const prevReport = await prisma.dailyReport.findFirst({ orderBy: { createdAt: "desc" } });
  const tailStart =
    prevReport?.createdAt && prevReport.createdAt < dayStart ? prevReport.createdAt : dayStart;

  const [openTrades, finishedFetched, decisionsToday, ruleChangesToday, allFinished, bankrolls] =
    await Promise.all([
      prisma.paperTrade.findMany({ where: { status: "open" } }),
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
      prisma.decisionJournal.findMany({ where: { createdAt: { gte: dayStart } } }),
      prisma.ruleChange.findMany({
        where: { createdAt: { gte: dayStart } },
        include: { newRuleSet: true },
      }),
      // v52 (tuning review #19 rec 3, user-approved 2026-09-08): lifetime
      // totals must include early-exit 'closed' rows — realized PnL books at
      // closedAt (resolvedAt NULL), so a resolved-only filter overstated C-200
      // EOD net worth (~$960: its closed-at-a-loss early exits were missing)
      // and understated STANDARD (~$1,082: its closed winners were missing).
      prisma.paperTrade.findMany({ where: { status: { in: ["resolved", "closed"] } } }),
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
  const stdWinRate = stdFinished.length
    ? stdFinished.filter((t) => (t.realizedPnl ?? 0) > 0).length / stdFinished.length
    : 0;

  const cmpPnlToday = cmpResolvedToday.reduce((a, t) => a + (t.realizedPnl ?? 0), 0);
  const cmpTotalPnl =
    cmpFinished.reduce((a, t) => a + (t.realizedPnl ?? 0), 0) +
    compoundOpen.reduce((a, t) => a + t.unrealizedPnl, 0);
  const cmpWinRate = cmpFinished.length
    ? cmpFinished.filter((t) => (t.realizedPnl ?? 0) > 0).length / cmpFinished.length
    : 0;

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
  const worst = [...stdResolvedToday].sort((a, b) => (a.realizedPnl ?? 0) - (b.realizedPnl ?? 0))[0];

  // Wallet performance today (Standard strategy used for benchmarks)
  const byWallet = new Map<string, number>();
  for (const t of stdResolvedToday) {
    byWallet.set(t.walletAddress, (byWallet.get(t.walletAddress) ?? 0) + (t.realizedPnl ?? 0));
  }
  const walletsSorted = [...byWallet.entries()].sort((a, b) => b[1] - a[1]);
  const bestWallets = walletsSorted.slice(0, 3).map(([a, p]) => ({ address: a, pnl: p }));
  const worstWallets = walletsSorted.slice(-3).reverse().map(([a, p]) => ({ address: a, pnl: p }));

  const bench = await computeBenchmarks();
  const beatBlind = bench.botFiltered.avgPnl > bench.blindCopy.avgPnl;

  // polycopy-edge-cost-pair (2026-09-23): the report quoted realized PnL as if
  // our modelled fill were free. It is not — the booked entry is a QUOTE read at
  // scoring time and lands BELOW the wallet's own fill on C-200 (measured
  // −3.03%/leg lifetime, 2026-09-23), the opposite sign a real copier sees. Both
  // numbers are printed on the same legs so neither can be read alone.
  // Measurement only: no threshold, rule, sizing or gate consumes this.
  const edgeCost = await computeEdgeCostSnapshot(now);
  const edgeBlock = edgeCostLines(edgeCost);

  const lesson =
    ruleChangesToday.length > 0
      ? ruleChangesToday[0].reason
      : bench.avoidedLosers > bench.missedWinners
        ? "Filtering is avoiding more losers than it misses winners — filters are earning their keep"
        : "Watch for missed winners — filters may be too strict";

  const fmt = (n: number) => `${n >= 0 ? "+" : ""}$${n.toFixed(2)}`;
  const short = (a: string) => `${a.slice(0, 6)}…${a.slice(-4)}`;

  const summary = [
    `**📊 CopyBot Comparative EOD Report — ${date}**`,
    `_${date} 00:00 → 24:00 local · calendar day (closedAt ?? resolvedAt)${dayOffset < 0 ? " — day that just ended" : ""}_`,
    ``, 
    `**🤖 STANDARD Bot (Infinite Pool):**`,
    `• PnL Today: ${fmt(stdPnlToday)} | Total PnL: ${fmt(stdTotalPnl)}`,
    `• Win Rate: ${(stdWinRate * 100).toFixed(1)}% | Open Positions: ${standardOpen.length}`,
    `• Sizing Range: $0.25 - $20.00`,
    `• Net of legacy duplicate stacks: ${fmt(stdNetOfStacks)} (day ${fmt(stdPnlToday)} − ${fmt(stackedDayPnl)} from ${stackedDayRows.length} stacked row${stackedDayRows.length === 1 ? "" : "s"}; stack = key with >1 row in the book)`,
    largestStack && largestStackShare > 0.5
      ? `• ⚠️ Largest single stack ${fmt(largestStack[1])} = ${(largestStackShare * 100).toFixed(0)}% of the day's STANDARD PnL (${largestStack[0].split("|")[1]}) — do not read it as edge`
      : undefined,
    ``,
    `**⚖️ BANKROLL_200 Bot (Compounding Pool):**`,
    `• PnL Today: ${fmt(cmpPnlToday)} | Total PnL: ${fmt(cmpTotalPnl)}`,
    `• Win Rate: ${(cmpWinRate * 100).toFixed(1)}% | Open Positions: ${compoundOpen.length}`,
    `• Sizing Range: $0.10 - $10.00`,
    `• Available Cash: $${cmpBankroll ? Math.max(0, cmpBankroll.cashBalance).toFixed(2) : "0.00"} | Current Net Worth: $${totalCmpCapital.toFixed(2)}`,
    ledgerNote,
    ...(edgeBlock.length ? [``, ...edgeBlock] : []),
    ``,
    `**System Activity:**`,
    `• Signals today: ${decisionsToday.length} (copy ${copied} / watch ${watched} / skip ${skipped})`,
    best ? `• Best trade: ${short(best.walletAddress)} ${fmt(best.realizedPnl ?? 0)} on ${best.marketId}` : `• Best trade: none resolved today`,
    `• Bot vs blind copy: ${beatBlind ? "✅ bot beat blind copying" : "⚠️ blind copy did better"} (bot avg ${fmt(bench.botFiltered.avgPnl)}/trade vs blind ${fmt(bench.blindCopy.avgPnl)}/trade)`,
    ruleChangesToday.length
      ? `• Rule changes: ${ruleChangesToday.length} — ${ruleChangesToday.map((c) => `v${c.newRuleSet.version}: ${c.reason}`).join("; ")}`
      : `• Rule changes: none`,
    `• Top lesson: ${lesson}`,
    walletScanLine(),
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
