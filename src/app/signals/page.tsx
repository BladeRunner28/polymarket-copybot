import { prisma } from "@/lib/db";
import { Card, Badge, Addr, Empty } from "@/components/ui";
import Link from "next/link";

export const dynamic = "force-dynamic";

export default async function Signals() {
  const decisions = await prisma.decisionJournal.findMany({
    orderBy: { createdAt: "desc" },
    take: 100,
    include: { observedTrade: true },
  });

  // Latest market snapshot per market for spread/liquidity/ttr display
  const marketIds = [...new Set(decisions.map((d) => d.marketId))];
  const snaps = await prisma.marketSnapshot.findMany({
    where: { marketId: { in: marketIds } },
    orderBy: { collectedAt: "desc" },
  });
  const latestSnap = new Map<string, (typeof snaps)[number]>();
  for (const s of snaps) if (!latestSnap.has(s.marketId)) latestSnap.set(s.marketId, s);

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">Trade Signals</h1>
      <Card>
        {decisions.length === 0 ? (
          <Empty message="No signals yet. Run monitor:trades then score:trades." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-dim uppercase tracking-wide border-b border-edge">
                  <th className="py-2 pr-3">Detected</th>
                  <th className="py-2 pr-3">Wallet</th>
                  <th className="py-2 pr-3">Market</th>
                  <th className="py-2 pr-3">Entry→Now</th>
                  <th className="py-2 pr-3">Drift</th>
                  <th className="py-2 pr-3">Spread</th>
                  <th className="py-2 pr-3">Liquidity</th>
                  <th className="py-2 pr-3">TTR</th>
                  <th className="py-2 pr-3">Decision</th>
                  <th className="py-2 pr-3">Score</th>
                  <th className="py-2">Reason / Risk</th>
                </tr>
              </thead>
              <tbody>
                {decisions.map((d) => {
                  const t = d.observedTrade;
                  const snap = latestSnap.get(d.marketId);
                  const drift = t.detectedPrice - t.walletEntryPrice;
                  const reasons = JSON.parse(d.reasonsJson) as string[];
                  const risks = JSON.parse(d.risksJson) as string[];
                  return (
                    <tr key={d.id} className="border-b border-edge/50 hover:bg-edge/20 align-top">
                      <td className="py-2 pr-3 text-xs text-dim font-mono whitespace-nowrap">
                        {d.createdAt.toISOString().slice(5, 16).replace("T", " ")}
                        {d.isDemo && <div><Badge kind="demo" /></div>}
                      </td>
                      <td className="py-2 pr-3">
                        <Link href={`/wallets/${t.walletAddress}`} className="hover:text-accent">
                          <Addr address={t.walletAddress} />
                        </Link>
                      </td>
                      <td className="py-2 pr-3 max-w-[260px]">
                        <div className="truncate" title={t.marketQuestion}>{t.marketQuestion}</div>
                        <div className="text-xs text-dim">{t.outcome} · {t.side}</div>
                      </td>
                      <td className="py-2 pr-3 font-mono text-xs whitespace-nowrap">
                        {t.walletEntryPrice.toFixed(3)} → {t.detectedPrice.toFixed(3)}
                      </td>
                      <td className={`py-2 pr-3 font-mono text-xs ${Math.abs(drift) > 0.05 ? "text-warn" : "text-dim"}`}>
                        {drift >= 0 ? "+" : ""}{drift.toFixed(3)}
                      </td>
                      <td className="py-2 pr-3 font-mono text-xs text-dim">{snap?.spread?.toFixed(3) ?? "—"}</td>
                      <td className="py-2 pr-3 font-mono text-xs text-dim">{snap?.liquidity ? `$${(snap.liquidity / 1000).toFixed(0)}k` : "—"}</td>
                      <td className="py-2 pr-3 font-mono text-xs text-dim">
                        {snap?.timeToResolution != null ? `${(snap.timeToResolution / 24).toFixed(1)}d` : "—"}
                      </td>
                      <td className="py-2 pr-3"><Badge kind={d.decision} /></td>
                      <td className="py-2 pr-3 font-mono text-xs">{d.copyScore.toFixed(0)}</td>
                      <td className="py-2 text-xs max-w-[220px]">
                        {reasons[0] && <div className="text-pos truncate" title={reasons.join("; ")}>{reasons[0]}</div>}
                        {risks[0] && <div className="text-neg truncate" title={risks.join("; ")}>{risks[0]}</div>}
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
