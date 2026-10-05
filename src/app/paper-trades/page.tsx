import { prisma } from "@/lib/db";
import { Card, Badge, Addr, Empty, Pnl } from "@/components/ui";
import { OpenMtmHorizonCard } from "@/components/open-mtm-horizon";
import { loadOpenMtmHorizon } from "@/lib/open-mtm-horizon";
import Link from "next/link";

export const dynamic = "force-dynamic";

/** Lanes shown on this page, in the order the daily report names them. */
const LANES = [
  { botId: "BANKROLL_200", label: "C-200" },
  { botId: "STANDARD", label: "STANDARD" },
];

export default async function PaperTrades() {
  const trades = await prisma.paperTrade.findMany({
    orderBy: { openedAt: "desc" },
    take: 200,
    include: { decision: true, pnlSnapshots: { orderBy: { collectedAt: "desc" }, take: 1 } },
  });

  // When does what is still open actually close? (2026-10-04, user request.)
  const horizons = await Promise.all(LANES.map((l) => loadOpenMtmHorizon({ botId: l.botId })));

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">Paper Trades</h1>
      <p className="text-sm text-dim">
        Simulated positions only — $.25 to $20 each, no real money involved.
      </p>

      <Card title="Open MTM — when it closes">
        <div className="space-y-6">
          {LANES.map((lane, i) => (
            <div key={lane.botId}>
              <h3 className="text-xs font-semibold text-dim uppercase tracking-wide mb-2">
                {lane.label} · {horizons[i].totals.legs} open legs in {horizons[i].totals.groups} markets · mark{" "}
                {horizons[i].totals.unrealized >= 0 ? "+" : "-"}${Math.abs(horizons[i].totals.unrealized).toFixed(2)}
              </h3>
              <OpenMtmHorizonCard summary={horizons[i]} label={lane.label} />
            </div>
          ))}
        </div>
      </Card>

      <Card>
        {trades.length === 0 ? (
          <Empty message="No paper trades yet. paper_copy decisions create them automatically." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-dim uppercase tracking-wide border-b border-edge">
                  <th className="py-2 pr-3">Opened</th>
                  <th className="py-2 pr-3">Bot</th>
                  <th className="py-2 pr-3">Venue</th>
                  <th className="py-2 pr-3">Wallet</th>
                  <th className="py-2 pr-3">Market</th>
                  <th className="py-2 pr-3">Outcome</th>
                  <th className="py-2 pr-3">Size</th>
                  <th className="py-2 pr-3">Entry</th>
                  <th className="py-2 pr-3">Current</th>
                  <th className="py-2 pr-3">PnL</th>
                  <th className="py-2 pr-3">Status</th>
                  <th className="py-2">Score</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t) => {
                  const pnl = t.realizedPnl ?? t.unrealizedPnl;
                  const reasons = JSON.parse(t.decision.reasonsJson) as string[];
                  const lastSnap = t.pnlSnapshots[0];
                  return (
                    <tr key={t.id} className="border-b border-edge/50 hover:bg-edge/20">
                      <td className="py-2 pr-3 text-xs text-dim font-mono whitespace-nowrap">
                        {t.openedAt.toISOString().slice(5, 16).replace("T", " ")}
                        {t.isDemo && <div><Badge kind="demo" /></div>}
                      </td>
                      <td className="py-2 pr-3 text-xs text-dim">
                        {t.botId === "STANDARD" ? "STD" : t.botId === "BANKROLL_200" ? "C-200" : t.botId}
                      </td>
                      <td className="py-2 pr-3 text-xs text-dim">
                        {t.venue}
                      </td>
                        <td className="py-2 pr-3">
                        <Link href={`/wallets/${t.walletAddress}`} className="hover:text-accent">
                          <Addr address={t.walletAddress} />
                        </Link>
                      </td>
                      <td className="py-2 pr-3 max-w-[240px] truncate font-mono text-xs" title={t.marketId}>{t.marketId}</td>
                      <td className="py-2 pr-3 text-xs">{t.outcome}</td>
                      <td className="py-2 pr-3 font-mono text-xs">${t.simulatedPositionSize.toFixed(2)}</td>
                      <td className="py-2 pr-3 font-mono text-xs">{t.entryPrice.toFixed(3)}</td>
                      <td className="py-2 pr-3 font-mono text-xs">{t.currentPrice.toFixed(3)}</td>
                      <td className="py-2 pr-3"><Pnl value={pnl} /></td>
                      <td className="py-2 pr-3"><Badge kind={t.status} /></td>
                      <td className="py-2 pr-3 text-xs text-dim font-mono whitespace-nowrap">
                        {lastSnap ? lastSnap.collectedAt.toISOString().slice(5, 16).replace("T", " ") : "—"}
                      </td>
                      <td className="py-2 text-xs text-dim max-w-[200px] truncate" title={reasons.join("; ")}>
                        {reasons[0] ?? "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
