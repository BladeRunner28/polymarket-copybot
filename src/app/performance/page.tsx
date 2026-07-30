import { prisma } from "@/lib/db";
import { computeBenchmarks } from "@/lib/benchmarks";
import { Card, Stat, Empty, Pnl, Addr } from "@/components/ui";
import { LineChart } from "@/components/chart";
import Link from "next/link";

export const dynamic = "force-dynamic";

export default async function Performance() {
  const [snapshots, resolved, bench] = await Promise.all([
    prisma.$queryRaw<Array<{ hour: string; botId: string; total_pnl: number }>>`
      SELECT strftime('%Y-%m-%d %H:00:00', s.collectedAt / 1000, 'unixepoch') as hour, t.botId, SUM(s.pnl) as total_pnl
      FROM PnlSnapshot s
      JOIN PaperTrade t ON s.paperTradeId = t.id
      GROUP BY hour, t.botId
      ORDER BY hour ASC
    `,
    prisma.paperTrade.findMany({ where: { status: "resolved" }, orderBy: { resolvedAt: "asc" } }),
    computeBenchmarks(),
  ]);

  // Cumulative PnL chart from database-aggregated snapshots
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

  // Rolling win rate chart
  const wrPoints: { x: string; y: number }[] = [];
  let wins = 0;
  resolved.forEach((t, i) => {
    if ((t.realizedPnl ?? 0) > 0) wins++;
    wrPoints.push({ x: (t.resolvedAt ?? t.openedAt).toISOString().slice(5, 10), y: Math.round((wins / (i + 1)) * 1000) / 10 });
  });

  // Per-wallet and per-category performance
  const byWallet = new Map<string, { pnl: number; n: number }>();
  for (const t of resolved) {
    if (t.botId !== "STANDARD") continue; // only show standard for benchmarks
    const cur = byWallet.get(t.walletAddress) ?? { pnl: 0, n: 0 };
    cur.pnl += t.realizedPnl ?? 0;
    cur.n++;
    byWallet.set(t.walletAddress, cur);
  }
  const walletRows = [...byWallet.entries()].sort((a, b) => b[1].pnl - a[1].pnl);

  const decisions = await prisma.decisionJournal.findMany({
    where: { paperTrades: { some: { status: "resolved", botId: "STANDARD" } } },
    include: { observedTrade: true, paperTrades: true },
  });
  const byCat = new Map<string, { pnl: number; n: number }>();
  for (const d of decisions) {
    const cat = d.observedTrade.marketCategory ?? "uncategorized";
    const pnl = d.paperTrades[0]?.realizedPnl ?? 0;
    const cur = byCat.get(cat) ?? { pnl: 0, n: 0 };
    cur.pnl += pnl;
    cur.n++;
    byCat.set(cat, cur);
  }

  const buckets = [bench.botFiltered, bench.blindCopy, bench.watchlist, bench.skipped];

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">Performance</h1>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Missed Winners" value={String(bench.missedWinners)} sub="skipped/watched, would have won" tone="neg" />
        <Stat label="Avoided Losers" value={String(bench.avoidedLosers)} sub="skipped/watched, would have lost" tone="pos" />
        <Stat label="Bad Copies" value={String(bench.badCopies)} sub="copies that lost" tone={bench.badCopies > 0 ? "neg" : "neutral"} />
        <Stat label="Good Skips" value={String(bench.goodSkips)} sub="skips that dodged losses" tone="pos" />
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <Card title="Paper PnL (hourly snapshots)">
          <LineChart series={chartData} formatY={(v) => `$${v.toFixed(0)}`} />
        </Card>
        <Card title="Rolling Win Rate %">
          <LineChart points={wrPoints} formatY={(v) => `${v.toFixed(0)}%`} />
        </Card>
      </div>

      <Card title="Strategy Benchmark: Bot vs Blind Copy vs Watchlist vs Skips">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-dim uppercase border-b border-edge">
                <th className="py-2 pr-3">Strategy</th>
                <th className="py-2 pr-3">Signals</th>
                <th className="py-2 pr-3">Resolved</th>
                <th className="py-2 pr-3">Total PnL</th>
                <th className="py-2 pr-3">Avg PnL/trade</th>
                <th className="py-2">Win Rate</th>
              </tr>
            </thead>
            <tbody>
              {buckets.map((b) => (
                <tr key={b.label} className={`border-b border-edge/40 ${b.label.startsWith("Bot") ? "bg-accent/5" : ""}`}>
                  <td className="py-2 pr-3">{b.label}</td>
                  <td className="py-2 pr-3 font-mono text-xs">{b.count}</td>
                  <td className="py-2 pr-3 font-mono text-xs">{b.resolvedCount}</td>
                  <td className="py-2 pr-3"><Pnl value={b.totalPnl} /></td>
                  <td className="py-2 pr-3"><Pnl value={b.avgPnl} /></td>
                  <td className="py-2 font-mono text-xs">{(b.winRate * 100).toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-dim mt-2">
          Watchlist/skipped/blind PnL is hypothetical ($10 flat positions at detection price). Bot-filtered uses actual simulated sizes.
        </p>
      </Card>

      <div className="grid md:grid-cols-2 gap-4">
        <Card title="Per-Wallet Paper PnL">
          {walletRows.length === 0 ? (
            <Empty message="No resolved paper trades yet." />
          ) : (
            <table className="w-full text-sm">
              <tbody>
                {walletRows.slice(0, 12).map(([addr, v]) => (
                  <tr key={addr} className="border-b border-edge/40">
                    <td className="py-1.5">
                      <Link href={`/wallets/${addr}`} className="hover:text-accent"><Addr address={addr} /></Link>
                    </td>
                    <td className="py-1.5 text-xs text-dim font-mono">{v.n} trades</td>
                    <td className="py-1.5 text-right"><Pnl value={v.pnl} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card title="Per-Category Paper PnL">
          {byCat.size === 0 ? (
            <Empty message="No resolved paper trades yet." />
          ) : (
            <table className="w-full text-sm">
              <tbody>
                {[...byCat.entries()].sort((a, b) => b[1].pnl - a[1].pnl).map(([cat, v]) => (
                  <tr key={cat} className="border-b border-edge/40">
                    <td className="py-1.5">{cat}</td>
                    <td className="py-1.5 text-xs text-dim font-mono">{v.n} trades</td>
                    <td className="py-1.5 text-right"><Pnl value={v.pnl} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </div>
  );
}
