import Link from "next/link";
import { prisma } from "@/lib/db";
import { Card, Stat, Pnl, Badge, Empty } from "@/components/ui";
import { LineChart } from "@/components/chart";

export const dynamic = "force-dynamic";

export default async function Overview() {
  const [openTrades, resolvedTrades, tracked, today, latestReport, latestChanges, snapshots, demoCount, bankrolls] =
    await Promise.all([
      prisma.paperTrade.findMany({ where: { status: "open" } }),
      prisma.paperTrade.findMany({ where: { status: "resolved" } }),
      prisma.walletProfile.count({ where: { status: "track" } }),
      prisma.decisionJournal.count({
        where: {
          decision: "paper_copy",
          createdAt: { gte: new Date(new Date().toISOString().slice(0, 10)) },
        },
      }),
      prisma.dailyReport.findFirst({ orderBy: { date: "desc" } }),
      prisma.ruleChange.findMany({
        orderBy: { createdAt: "desc" },
        take: 3,
        include: { newRuleSet: true },
      }),
      prisma.$queryRaw<Array<{ hour: string; botId: string; total_pnl: number }>>`
        SELECT strftime('%Y-%m-%d %H:00:00', s.collectedAt / 1000, 'unixepoch') as hour, t.botId, SUM(s.pnl) as total_pnl
        FROM PnlSnapshot s
        JOIN PaperTrade t ON s.paperTradeId = t.id
        GROUP BY hour, t.botId
        ORDER BY hour ASC
      `,
      prisma.paperTrade.count({ where: { isDemo: true } }),
      prisma.botBankroll.findMany(),
    ]);

  const stdOpen = openTrades.filter(t => t.botId === "STANDARD");
  const cmpOpen = openTrades.filter(t => t.botId === "BANKROLL_200");
  const stdResolved = resolvedTrades.filter(t => t.botId === "STANDARD");
  const cmpResolved = resolvedTrades.filter(t => t.botId === "BANKROLL_200");

  const stdRealizedPnl = stdResolved.reduce((a, t) => a + (t.realizedPnl ?? 0), 0);
  const stdUnrealizedPnl = stdOpen.reduce((a, t) => a + t.unrealizedPnl, 0);
  const stdTotalPnl = stdRealizedPnl + stdUnrealizedPnl;
  const stdWinRate = stdResolved.length
    ? stdResolved.filter((t) => (t.realizedPnl ?? 0) > 0).length / stdResolved.length
    : 0;

  const cmpRealizedPnl = cmpResolved.reduce((a, t) => a + (t.realizedPnl ?? 0), 0);
  const cmpUnrealizedPnl = cmpOpen.reduce((a, t) => a + t.unrealizedPnl, 0);
  const cmpTotalPnl = cmpRealizedPnl + cmpUnrealizedPnl;
  const cmpWinRate = cmpResolved.length
    ? cmpResolved.filter((t) => (t.realizedPnl ?? 0) > 0).length / cmpResolved.length
    : 0;

  const c200Bankroll = bankrolls.find(b => b.botId === "BANKROLL_200") || { principal: 200 };

  // Cumulative PnL over time from database-aggregated snapshots
  const standardSeries = snapshots
    .filter((s) => s.botId === "STANDARD")
    .map((s) => ({ x: s.hour ? s.hour.slice(5, 13) : "", y: Math.round((s.total_pnl ?? 0) * 100) / 100 }))
    .filter((p) => p.x !== "");

  const compoundingSeries = snapshots
    .filter((s) => s.botId === "BANKROLL_200")
    .map((s) => ({ x: s.hour ? s.hour.slice(5, 13) : "", y: Math.round((s.total_pnl ?? 0) * 100) / 100 }))
    .filter((p) => p.x !== "");

  const chartData = [
    { name: "STANDARD ($0.25 - $20)", points: standardSeries.length ? standardSeries : [{ x: "Now", y: 0 }], strokeColor: "#34d399" }, // green
    { name: "BANKROLL_200 ($0.10 - $10)", points: compoundingSeries.length ? compoundingSeries : [{ x: "Now", y: 0 }], strokeColor: "#3b82f6" }, // blue
  ];

  return (
    <div className="space-y-4">
      {demoCount > 0 && (
        <div className="bg-warn/10 border border-warn/30 text-warn text-sm rounded-xl px-4 py-2">
          ⚠️ Demo data present: some rows below are seeded <strong>[DEMO]</strong> data, not live market research.
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat
          label="Total Paper PnL (Standard)"
          value={`${stdTotalPnl >= 0 ? "+" : ""}$${stdTotalPnl.toFixed(2)}`}
          sub={`realized ${stdRealizedPnl >= 0 ? "+" : ""}$${stdRealizedPnl.toFixed(2)} / open ${stdUnrealizedPnl >= 0 ? "+" : ""}$${stdUnrealizedPnl.toFixed(2)}`}
          tone={stdTotalPnl > 0 ? "pos" : stdTotalPnl < 0 ? "neg" : "neutral"}
        />
        <Stat label="Win Rate" value={`${(stdWinRate * 100).toFixed(1)}%`} sub={`${stdResolved.length} resolved trades`} tone={stdWinRate >= 0.5 ? "pos" : "neg"} />
        <Stat label="Open Positions" value={String(stdOpen.length)} sub="standard bot ($0.25 - $20)" />
        <Stat label="Tracked Wallets" value={String(tracked)} sub={`${today} copy candidates today`} />
        
        <Stat
          label="Total PnL (C-200)"
          value={`${cmpTotalPnl >= 0 ? "+" : ""}$${cmpTotalPnl.toFixed(2)}`}
          sub={`realized ${cmpRealizedPnl >= 0 ? "+" : ""}$${cmpRealizedPnl.toFixed(2)} / open ${cmpUnrealizedPnl >= 0 ? "+" : ""}$${cmpUnrealizedPnl.toFixed(2)}`}
          tone={cmpTotalPnl > 0 ? "pos" : cmpTotalPnl < 0 ? "neg" : "neutral"}
        />
        <Stat label="Win Rate (C-200)" value={`${(cmpWinRate * 100).toFixed(1)}%`} sub={`${cmpResolved.length} resolved trades`} tone={cmpWinRate >= 0.5 ? "pos" : "neg"} />
        <Stat label="Open Positions" value={String(cmpOpen.length)} sub="compounding bot ($0.10 - $10)" />
        <Stat label="Total Capital" value={`$${(c200Bankroll.principal + cmpTotalPnl).toFixed(2)}`} sub={`starting principal: $${c200Bankroll.principal.toFixed(2)}`} tone="neutral" />
      </div>

      <Card title="Paper PnL Over Time">
        <LineChart series={chartData} formatY={(v) => `$${v.toFixed(0)}`} />
      </Card>

      <div className="grid md:grid-cols-2 gap-4">
        <Card title="Latest Rule Changes">
          {latestChanges.length === 0 ? (
            <Empty message="No automatic rule changes yet. The bot changes rules only with evidence." />
          ) : (
            <ul className="space-y-3 text-sm">
              {latestChanges.map((c) => (
                <li key={c.id} className="border-l-2 border-accent pl-3">
                  <div className="text-ink">
                    v{c.newRuleSet.version} — {c.reason}
                  </div>
                  <div className="text-dim text-xs mt-0.5">{c.createdAt.toISOString().slice(0, 16).replace("T", " ")}</div>
                </li>
              ))}
            </ul>
          )}
          <Link href="/rules" className="text-accent text-xs mt-3 inline-block hover:underline">
            View all rules →
          </Link>
        </Card>

        <Card title="End-of-Day Report">
          {!latestReport ? (
            <Empty message="No daily report generated yet. Run `npm run report:daily`." />
          ) : (
            <div className="text-sm space-y-2">
              <div className="flex items-center gap-2">
                <span className="text-dim">{latestReport.date}</span>
                <Badge kind={latestReport.sentToDiscord ? "resolved" : "watch"} />
                <span className="text-xs text-dim">{latestReport.sentToDiscord ? "sent to Discord" : "stored locally"}</span>
              </div>
              <div>
                Day PnL <Pnl value={latestReport.paperPnl} /> · win rate {(latestReport.winRate * 100).toFixed(1)}% ·{" "}
                {latestReport.newSignals} signals
              </div>
              <Link href="/reports" className="text-accent text-xs hover:underline">
                Read full report →
              </Link>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
