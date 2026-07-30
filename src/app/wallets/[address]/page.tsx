import { prisma } from "@/lib/db";
import { Card, Stat, Badge, Addr, Empty, Pnl, ScoreBar } from "@/components/ui";
import { notFound } from "next/navigation";

export const dynamic = "force-dynamic";

export default async function WalletProfilePage({ params }: { params: { address: string } }) {
  const address = decodeURIComponent(params.address).toLowerCase();
  const wallet = await prisma.walletProfile.findUnique({ where: { address } });
  if (!wallet) notFound();

  const [recentTrades, paperTrades] = await Promise.all([
    prisma.observedTrade.findMany({
      where: { walletAddress: address },
      orderBy: { timestamp: "desc" },
      take: 20,
    }),
    prisma.paperTrade.findMany({
      where: { walletAddress: address },
      orderBy: { openedAt: "desc" },
    }),
  ]);

  const paperPnl = paperTrades.reduce((a, t) => a + (t.realizedPnl ?? t.unrealizedPnl), 0);
  let cats: Record<string, { trades: number; winRate: number; pnl: number }> = {};
  try {
    cats = JSON.parse(wallet.categoryStrengthsJson);
  } catch { /* empty */ }

  const copyVerdict =
    wallet.copyabilityScore >= 60
      ? { text: "Copyable", tone: "pos" as const }
      : wallet.averageLiquidity < 5000
        ? { text: "Too illiquid to copy", tone: "neg" as const }
        : wallet.oneHitWonderPenalty > 60
          ? { text: "One-hit wonder — not repeatable", tone: "neg" as const }
          : wallet.bestCategory && Object.keys(cats).length === 1
            ? { text: `Category-specific (${wallet.bestCategory} only)`, tone: "neutral" as const }
            : { text: "Marginal — watch, don't copy", tone: "neutral" as const };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-xl font-bold">
          <Addr address={wallet.address} label={wallet.label} />
        </h1>
        <Badge kind={wallet.status} />
        {wallet.isDemo && <Badge kind="demo" />}
        <span className={`text-sm ${copyVerdict.tone === "pos" ? "text-pos" : copyVerdict.tone === "neg" ? "text-neg" : "text-warn"}`}>
          {copyVerdict.text}
        </span>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="ROI 30d" value={`${(wallet.roi30d * 100).toFixed(1)}%`} tone={wallet.roi30d > 0 ? "pos" : "neg"} />
        <Stat label="Trades 30d" value={String(wallet.tradeCount30d)} sub={`${wallet.resolvedTradeCount30d} resolved`} />
        <Stat label="Win Rate (resolved)" value={`${(wallet.winRate30d * 100).toFixed(1)}%`} tone={wallet.winRate30d >= 0.5 ? "pos" : "neg"} />
        <Stat label="Avg Trade Size" value={`$${wallet.averageTradeSize.toFixed(0)}`} />
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <Card title="Scores">
          <div className="space-y-3 text-sm">
            {[
              ["Global", wallet.globalScore],
              ["Consistency", wallet.consistencyScore],
              ["Copyability", wallet.copyabilityScore],
              ["One-hit-wonder penalty", wallet.oneHitWonderPenalty],
            ].map(([label, v]) => (
              <div key={label as string} className="flex items-center justify-between">
                <span className="text-dim">{label}</span>
                <ScoreBar score={v as number} />
              </div>
            ))}
            <div className="flex items-center justify-between">
              <span className="text-dim">Avg liquidity</span>
              <span className="font-mono text-xs">${wallet.averageLiquidity.toFixed(0)}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-dim">Avg spread</span>
              <span className="font-mono text-xs">{wallet.averageSpread.toFixed(3)}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-dim">Avg entry timing</span>
              <span className="font-mono text-xs">{wallet.averageEntryTiming < 0.35 ? "early" : wallet.averageEntryTiming > 0.65 ? "late" : "mid"}</span>
            </div>
          </div>
        </Card>

        <Card title="Category Strengths">
          {Object.keys(cats).length === 0 ? (
            <Empty message="No category data yet." />
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-dim uppercase border-b border-edge">
                  <th className="py-1.5">Category</th>
                  <th className="py-1.5">Trades</th>
                  <th className="py-1.5">Win Rate</th>
                  <th className="py-1.5">PnL</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(cats).map(([c, v]) => (
                  <tr key={c} className="border-b border-edge/40">
                    <td className="py-1.5">{c}{c === wallet.bestCategory && <span className="text-warn ml-1">★</span>}</td>
                    <td className="py-1.5 font-mono text-xs">{v.trades}</td>
                    <td className="py-1.5 font-mono text-xs">{(v.winRate * 100).toFixed(0)}%</td>
                    <td className="py-1.5"><Pnl value={v.pnl} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>

      <Card title={`Paper Performance if Copied (${paperTrades.length} trades)`}>
        {paperTrades.length === 0 ? (
          <Empty message="No paper trades linked to this wallet yet." />
        ) : (
          <div className="text-sm">
            Total paper PnL from this wallet: <Pnl value={paperPnl} />
          </div>
        )}
      </Card>

      <Card title="Notes">
        <div className="text-sm space-y-1">
          <div><span className="text-dim">Copyability:</span> {wallet.copyabilityNotes ?? "—"}</div>
          <div><span className="text-dim">Risks:</span> <span className="text-warn">{wallet.riskNotes ?? "—"}</span></div>
        </div>
      </Card>

      <Card title="Recent Trades">
        {recentTrades.length === 0 ? (
          <Empty message="No observed trades for this wallet yet." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-dim uppercase border-b border-edge">
                  <th className="py-2 pr-3">Time</th>
                  <th className="py-2 pr-3">Market</th>
                  <th className="py-2 pr-3">Side</th>
                  <th className="py-2 pr-3">Outcome</th>
                  <th className="py-2 pr-3">Entry</th>
                  <th className="py-2">Size</th>
                </tr>
              </thead>
              <tbody>
                {recentTrades.map((t) => (
                  <tr key={t.id} className="border-b border-edge/40">
                    <td className="py-2 pr-3 text-xs text-dim font-mono">{t.timestamp.toISOString().slice(5, 16).replace("T", " ")}</td>
                    <td className="py-2 pr-3 max-w-[320px] truncate" title={t.marketQuestion}>{t.marketQuestion}</td>
                    <td className="py-2 pr-3 text-xs">{t.side}</td>
                    <td className="py-2 pr-3 text-xs">{t.outcome}</td>
                    <td className="py-2 pr-3 font-mono text-xs">{t.walletEntryPrice.toFixed(3)}</td>
                    <td className="py-2 font-mono text-xs">${t.size.toFixed(0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
