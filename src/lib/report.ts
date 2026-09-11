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
import { sendDiscord } from "./discord";
import { dayWindow, reportDayOffset, rowsFinishedIn } from "./day-pnl";

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
    ``,
    `**⚖️ BANKROLL_200 Bot (Compounding Pool):**`,
    `• PnL Today: ${fmt(cmpPnlToday)} | Total PnL: ${fmt(cmpTotalPnl)}`,
    `• Win Rate: ${(cmpWinRate * 100).toFixed(1)}% | Open Positions: ${compoundOpen.length}`,
    `• Sizing Range: $0.10 - $10.00`,
    `• Available Cash: $${cmpBankroll ? Math.max(0, cmpBankroll.cashBalance).toFixed(2) : "0.00"} | Current Net Worth: $${totalCmpCapital.toFixed(2)}`,
    ledgerNote,
    ``,
    `**System Activity:**`,
    `• Signals today: ${decisionsToday.length} (copy ${copied} / watch ${watched} / skip ${skipped})`,
    best ? `• Best trade: ${short(best.walletAddress)} ${fmt(best.realizedPnl ?? 0)} on ${best.marketId}` : `• Best trade: none resolved today`,
    `• Bot vs blind copy: ${beatBlind ? "✅ bot beat blind copying" : "⚠️ blind copy did better"} (bot avg ${fmt(bench.botFiltered.avgPnl)}/trade vs blind ${fmt(bench.blindCopy.avgPnl)}/trade)`,
    ruleChangesToday.length
      ? `• Rule changes: ${ruleChangesToday.length} — ${ruleChangesToday.map((c) => `v${c.newRuleSet.version}: ${c.reason}`).join("; ")}`
      : `• Rule changes: none`,
    `• Top lesson: ${lesson}`,
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
