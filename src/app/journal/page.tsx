import { prisma } from "@/lib/db";
import { Card, Badge, Addr, Empty } from "@/components/ui";
import Link from "next/link";

export const dynamic = "force-dynamic";

export default async function Journal() {
  const decisions = await prisma.decisionJournal.findMany({
    orderBy: { createdAt: "desc" },
    take: 100,
    include: { observedTrade: true, outcomeReviews: true },
  });

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">Decision Journal</h1>
      <p className="text-sm text-dim">Every decision, its score breakdown, and whether hindsight judged it good.</p>
      {decisions.length === 0 ? (
        <Card><Empty message="No decisions yet." /></Card>
      ) : (
        decisions.map((d) => {
          const reasons = JSON.parse(d.reasonsJson) as string[];
          const risks = JSON.parse(d.risksJson) as string[];
          const review = d.outcomeReviews.find((r) => r.wasDecisionGood !== null);
          const lessons: string[] = review ? JSON.parse(review.lessonsJson) : [];
          const parts: [string, number][] = [
            ["wallet", d.walletQualityScore],
            ["category", d.categoryFitScore],
            ["timing", d.entryTimingScore],
            ["spread", d.spreadScore],
            ["liquidity", d.liquidityScore],
            ["thesis", d.thesisScore],
          ];
          return (
            <Card key={d.id}>
              <div className="flex items-start justify-between gap-4 flex-wrap">
                <div className="space-y-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <Badge kind={d.decision} />
                    {d.isDemo && <Badge kind="demo" />}
                    <span className="font-mono text-xs text-dim">score {d.copyScore.toFixed(0)} · conf {(d.confidence * 100).toFixed(0)}% · rules v{d.ruleSetVersion ?? "?"}</span>
                    {review && (
                      <span className={`text-xs font-semibold ${review.wasDecisionGood ? "text-pos" : "text-neg"}`}>
                        {review.wasDecisionGood ? "✓ judged good" : "✗ judged bad"}
                      </span>
                    )}
                  </div>
                  <div className="text-sm truncate max-w-xl" title={d.observedTrade.marketQuestion}>
                    {d.observedTrade.marketQuestion}
                  </div>
                  <div className="text-xs text-dim">
                    <Link href={`/wallets/${d.walletAddress}`} className="hover:text-accent">
                      <Addr address={d.walletAddress} />
                    </Link>{" "}
                    · {d.createdAt.toISOString().slice(0, 16).replace("T", " ")}
                    {d.simulatedPositionSize && ` · std $${d.simulatedPositionSize.toFixed(2)}`}
                    {d.simulatedPositionSize && ` · c-200 $${(0.10 + ((d.simulatedPositionSize - 0.25) / (20.00 - 0.25)) * (10.00 - 0.10)).toFixed(2)}`}
                  </div>
                </div>
                <div className="flex gap-2 flex-wrap text-[10px] font-mono">
                  {parts.map(([k, v]) => (
                    <span key={k} className={`px-1.5 py-0.5 rounded border ${v >= 60 ? "border-pos/30 text-pos" : v >= 40 ? "border-warn/30 text-warn" : "border-neg/30 text-neg"}`}>
                      {k} {v.toFixed(0)}
                    </span>
                  ))}
                </div>
              </div>
              {(reasons.length > 0 || risks.length > 0 || lessons.length > 0) && (
                <div className="mt-3 grid md:grid-cols-3 gap-3 text-xs">
                  {reasons.length > 0 && (
                    <div>
                      <div className="text-dim uppercase mb-1">Reasons</div>
                      <ul className="space-y-0.5 text-pos">{reasons.map((r, i) => <li key={i}>• {r}</li>)}</ul>
                    </div>
                  )}
                  {risks.length > 0 && (
                    <div>
                      <div className="text-dim uppercase mb-1">Risks</div>
                      <ul className="space-y-0.5 text-neg">{risks.map((r, i) => <li key={i}>• {r}</li>)}</ul>
                    </div>
                  )}
                  {lessons.length > 0 && (
                    <div>
                      <div className="text-dim uppercase mb-1">Learned</div>
                      <ul className="space-y-0.5 text-accent">{lessons.map((l, i) => <li key={i}>• {l}</li>)}</ul>
                    </div>
                  )}
                </div>
              )}
            </Card>
          );
        })
      )}
    </div>
  );
}
