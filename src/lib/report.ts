/**
 * Daily report generator. Builds the end-of-day summary Hermes sends to
 * Discord and stores it as a DailyReport row.
 */

import { prisma } from "./db";
import { computeBenchmarks } from "./benchmarks";
import { sendDiscord } from "./discord";

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export async function generateDailyReport(): Promise<{ id: string; summary: string; sent: boolean }> {
  const date = today();

  // Rolling window: count activity since the previous report run instead of a
  // UTC calendar day. The EOD job runs at 22:00 local (03:00 UTC), so a
  // UTC-midnight window silently dropped every resolution detected between
  // 03:00 and 24:00 UTC (~21h/day) — reports showed "$0.00 today" even on days
  // with real wins. Fallback: trailing 24h on the first run.
  const prevReport = await prisma.dailyReport.findFirst({ orderBy: { createdAt: "desc" } });
  const windowStart = prevReport?.createdAt ?? new Date(Date.now() - 86_400_000);

  const [openTrades, resolvedToday, decisionsToday, ruleChangesToday, allResolved, bankrolls] =
    await Promise.all([
      prisma.paperTrade.findMany({ where: { status: "open" } }),
      prisma.paperTrade.findMany({
        where: { status: "resolved", resolvedAt: { gte: windowStart } },
      }),
      prisma.decisionJournal.findMany({ where: { createdAt: { gte: windowStart } } }),
      prisma.ruleChange.findMany({
        where: { createdAt: { gte: windowStart } },
        include: { newRuleSet: true },
      }),
      prisma.paperTrade.findMany({ where: { status: "resolved" } }),
      prisma.botBankroll.findMany(),
    ]);

  const standardOpen = openTrades.filter((t) => t.botId === "STANDARD");
  const compoundOpen = openTrades.filter((t) => t.botId === "BANKROLL_200");
  
  const stdResolvedToday = resolvedToday.filter((t) => t.botId === "STANDARD");
  const cmpResolvedToday = resolvedToday.filter((t) => t.botId === "BANKROLL_200");
  
  const stdAllResolved = allResolved.filter((t) => t.botId === "STANDARD");
  const cmpAllResolved = allResolved.filter((t) => t.botId === "BANKROLL_200");

  const stdPnlToday = stdResolvedToday.reduce((a, t) => a + (t.realizedPnl ?? 0), 0);
  const stdTotalPnl =
    stdAllResolved.reduce((a, t) => a + (t.realizedPnl ?? 0), 0) +
    standardOpen.reduce((a, t) => a + t.unrealizedPnl, 0);
  const stdWinRate = stdAllResolved.length
    ? stdAllResolved.filter((t) => (t.realizedPnl ?? 0) > 0).length / stdAllResolved.length
    : 0;

  const cmpPnlToday = cmpResolvedToday.reduce((a, t) => a + (t.realizedPnl ?? 0), 0);
  const cmpTotalPnl =
    cmpAllResolved.reduce((a, t) => a + (t.realizedPnl ?? 0), 0) +
    compoundOpen.reduce((a, t) => a + t.unrealizedPnl, 0);
  const cmpWinRate = cmpAllResolved.length
    ? cmpAllResolved.filter((t) => (t.realizedPnl ?? 0) > 0).length / cmpAllResolved.length
    : 0;

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
  ]
    .filter((line) => line !== undefined && line !== null)
    .join("\n");

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
