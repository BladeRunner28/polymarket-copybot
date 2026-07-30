import Link from "next/link";
import { prisma } from "@/lib/db";
import { Card, Badge, Addr, Empty, ScoreBar } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function Wallets() {
  const [wallets, lastScan] = await Promise.all([
    prisma.walletProfile.findMany({
      orderBy: [{ globalScore: "desc" }],
      take: 500,
    }),
    prisma.leaderboardScan.findFirst({ orderBy: { scannedAt: "desc" } }),
  ]);

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between flex-wrap gap-2">
        <h1 className="text-xl font-bold">Wallet Rankings</h1>
        <div className="text-xs text-dim">
          {lastScan
            ? `Last leaderboard scan: ${lastScan.scannedAt.toISOString().slice(0, 16).replace("T", " ")} · ${lastScan.walletCount} wallets · source: ${lastScan.source}${lastScan.source === "demo" ? " [DEMO]" : ""}`
            : "No leaderboard scan yet — run `npm run scan:leaderboard`"}
        </div>
      </div>

      <Card>
        {wallets.length === 0 ? (
          <Empty message="No wallets yet. Run `npm run scan:leaderboard` then `npm run scan:wallets`." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-dim uppercase tracking-wide border-b border-edge">
                  <th className="py-2 pr-3">#</th>
                  <th className="py-2 pr-3">Wallet</th>
                  <th className="py-2 pr-3">Status</th>
                  <th className="py-2 pr-3">Global</th>
                  <th className="py-2 pr-3">ROI 30d</th>
                  <th className="py-2 pr-3">Consistency</th>
                  <th className="py-2 pr-3">Copyability</th>
                  <th className="py-2 pr-3">1-Hit Penalty</th>
                  <th className="py-2 pr-3">Best Category</th>
                  <th className="py-2">Reason</th>
                </tr>
              </thead>
              <tbody>
                {wallets.map((w, i) => (
                  <tr key={w.id} className="border-b border-edge/50 hover:bg-edge/20">
                    <td className="py-2 pr-3 text-dim font-mono text-xs">{w.sourceRank ?? i + 1}</td>
                    <td className="py-2 pr-3">
                      <Link href={`/wallets/${w.address}`} className="hover:text-accent">
                        <Addr address={w.address} label={w.label} />
                      </Link>
                      {w.isDemo && (
                        <span className="ml-2">
                          <Badge kind="demo" />
                        </span>
                      )}
                    </td>
                    <td className="py-2 pr-3">
                      <Badge kind={w.status} />
                    </td>
                    <td className="py-2 pr-3">
                      <ScoreBar score={w.globalScore} />
                    </td>
                    <td className={`py-2 pr-3 font-mono text-xs ${w.roi30d > 0 ? "text-pos" : w.roi30d < 0 ? "text-neg" : "text-dim"}`}>
                      {(w.roi30d * 100).toFixed(1)}%
                    </td>
                    <td className="py-2 pr-3">
                      <ScoreBar score={w.consistencyScore} />
                    </td>
                    <td className="py-2 pr-3">
                      <ScoreBar score={w.copyabilityScore} />
                    </td>
                    <td className={`py-2 pr-3 font-mono text-xs ${w.oneHitWonderPenalty > 60 ? "text-neg" : "text-dim"}`}>
                      {w.oneHitWonderPenalty.toFixed(0)}
                    </td>
                    <td className="py-2 pr-3 text-xs text-dim">{w.bestCategory ?? "—"}</td>
                    <td className="py-2 text-xs text-dim max-w-[240px] truncate" title={w.copyabilityNotes ?? ""}>
                      {w.copyabilityNotes ?? "not profiled yet"}
                    </td>
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
