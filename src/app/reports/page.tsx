import { prisma } from "@/lib/db";
import { Card, Badge, Empty, Pnl } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function Reports() {
  const reports = await prisma.dailyReport.findMany({ orderBy: { date: "desc" }, take: 30 });

  // Weekly rollup from daily reports
  const weeks = new Map<string, { pnl: number; days: number; signals: number }>();
  for (const r of reports) {
    const d = new Date(r.date + "T00:00:00Z");
    const weekStart = new Date(d);
    weekStart.setUTCDate(d.getUTCDate() - d.getUTCDay());
    const key = weekStart.toISOString().slice(0, 10);
    const cur = weeks.get(key) ?? { pnl: 0, days: 0, signals: 0 };
    cur.pnl += r.paperPnl;
    cur.days++;
    cur.signals += r.newSignals;
    weeks.set(key, cur);
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">Reports</h1>

      <Card title="Weekly Summary">
        {weeks.size === 0 ? (
          <Empty message="No reports yet. Run `npm run report:daily`." />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-dim uppercase border-b border-edge">
                <th className="py-2 pr-3">Week of</th>
                <th className="py-2 pr-3">Paper PnL</th>
                <th className="py-2 pr-3">Reported Days</th>
                <th className="py-2">Signals</th>
              </tr>
            </thead>
            <tbody>
              {[...weeks.entries()].map(([week, v]) => (
                <tr key={week} className="border-b border-edge/40">
                  <td className="py-2 pr-3 font-mono text-xs">{week}</td>
                  <td className="py-2 pr-3"><Pnl value={v.pnl} /></td>
                  <td className="py-2 pr-3 font-mono text-xs">{v.days}</td>
                  <td className="py-2 font-mono text-xs">{v.signals}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {reports.map((r) => {
        const bestWallets = JSON.parse(r.bestWalletsJson) as { address: string; pnl: number }[];
        const worstWallets = JSON.parse(r.worstWalletsJson) as { address: string; pnl: number }[];
        const ruleChanges = JSON.parse(r.ruleChangesJson) as { version: number; reason: string }[];
        return (
          <Card key={r.id} title={`End of Day — ${r.date}`}>
            <div className="flex items-center gap-2 mb-3">
              <Badge kind={r.sentToDiscord ? "resolved" : "watch"} />
              <span className="text-xs text-dim">{r.sentToDiscord ? "delivered to Discord" : "stored locally"}</span>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm mb-3">
              <div><span className="text-dim block text-xs">Day PnL</span><Pnl value={r.paperPnl} /></div>
              <div><span className="text-dim block text-xs">Win rate</span>{(r.winRate * 100).toFixed(1)}%</div>
              <div><span className="text-dim block text-xs">Open positions</span>{r.openPositions}</div>
              <div><span className="text-dim block text-xs">Signals (c/w/s)</span>{r.copiedSignals}/{r.watchedSignals}/{r.skippedSignals}</div>
            </div>
            {(bestWallets.length > 0 || worstWallets.length > 0) && (
              <div className="text-xs text-dim mb-3">
                {bestWallets[0] && <span>Best wallet: <span className="text-pos font-mono">{bestWallets[0].address.slice(0, 10)}… (+${bestWallets[0].pnl.toFixed(2)})</span></span>}
                {worstWallets[0] && worstWallets[0].pnl < 0 && (
                  <span className="ml-4">Worst wallet: <span className="text-neg font-mono">{worstWallets[0].address.slice(0, 10)}… (${worstWallets[0].pnl.toFixed(2)})</span></span>
                )}
              </div>
            )}
            {ruleChanges.length > 0 && (
              <div className="text-xs mb-3">
                <span className="text-dim uppercase">Rule updates: </span>
                {ruleChanges.map((c, i) => (
                  <span key={i} className="text-accent">v{c.version}: {c.reason}{i < ruleChanges.length - 1 ? "; " : ""}</span>
                ))}
              </div>
            )}
            <pre className="text-xs text-dim whitespace-pre-wrap bg-base rounded-lg border border-edge p-3 font-mono">{r.summary}</pre>
          </Card>
        );
      })}
    </div>
  );
}
