import { prisma } from "@/lib/db";
import { getActiveRules } from "@/lib/rules";
import { Card, Empty } from "@/components/ui";

export const dynamic = "force-dynamic";

const RULE_DESCRIPTIONS: Record<string, string> = {
  maxSpread: "Skip trades when bid/ask spread exceeds this",
  minLiquidity: "Skip markets with less liquidity (USD) than this",
  maxPriceDrift: "Skip when price moved further than this since wallet entry",
  minTimeToResolutionHours: "Skip markets resolving sooner than this (hours)",
  minCopyScore: "Minimum score to paper-copy a trade",
  watchlistScore: "Minimum score to watchlist a trade",
  minWalletGlobalScore: "Ignore signals from wallets scoring below this",
  minResolvedTrades: "Wallets with fewer resolved trades are capped as unproven",
  weightRoi: "Wallet scoring weight: ROI",
  weightConsistency: "Wallet scoring weight: consistency",
  weightCopyability: "Wallet scoring weight: copyability",
  baseSizeUsd: "Base simulated position size (USD)",
  confidenceSizeBonus: "Extra simulated USD per confidence point above 0.5",
};

export default async function Rules() {
  const { rules, version } = await getActiveRules();
  const [changes, history] = await Promise.all([
    prisma.ruleChange.findMany({
      orderBy: { createdAt: "desc" },
      include: { newRuleSet: true, oldRuleSet: true },
    }),
    prisma.ruleSet.findMany({ orderBy: { version: "desc" } }),
  ]);

  return (
    <div className="space-y-4">
      <div className="flex items-baseline gap-3">
        <h1 className="text-xl font-bold">Rules</h1>
        <span className="text-sm text-accent font-mono">active: v{version}</span>
      </div>
      <p className="text-sm text-dim">
        The bot updates these automatically based on paper-trade evidence. Every change is versioned below — nothing changes silently.
      </p>

      <Card title={`Active Thresholds (v${version})`}>
        <div className="grid md:grid-cols-2 gap-x-8 gap-y-2 text-sm">
          {Object.entries(rules).map(([k, v]) => (
            <div key={k} className="flex justify-between border-b border-edge/40 py-1.5">
              <span>
                <span className="font-mono text-accent">{k}</span>
                <span className="block text-xs text-dim">{RULE_DESCRIPTIONS[k] ?? ""}</span>
              </span>
              <span className="font-mono">{typeof v === "number" ? v : String(v)}</span>
            </div>
          ))}
        </div>
      </Card>

      <Card title="Rule Change Log">
        {changes.length === 0 ? (
          <Empty message="No automatic rule changes yet. Changes require enough resolved-trade evidence." />
        ) : (
          <div className="space-y-4">
            {changes.map((c) => {
              const before = JSON.parse(c.beforeJson) as Record<string, number>;
              const after = JSON.parse(c.afterJson) as Record<string, number>;
              return (
                <div key={c.id} className="border-l-2 border-accent pl-4">
                  <div className="text-sm">
                    <span className="font-mono text-accent">v{c.oldRuleSet?.version ?? "?"} → v{c.newRuleSet.version}</span>
                    <span className="text-dim text-xs ml-2">{c.createdAt.toISOString().slice(0, 16).replace("T", " ")} · by {c.changedBy}</span>
                  </div>
                  <div className="text-sm mt-1">{c.reason}</div>
                  <div className="text-xs text-dim mt-1">Evidence: {c.evidenceSummary}</div>
                  <div className="flex gap-2 flex-wrap mt-2">
                    {Object.keys(after).map((k) => (
                      <span key={k} className="text-xs font-mono bg-edge/50 border border-edge rounded px-2 py-1">
                        {k}: <span className="text-neg line-through">{before[k]}</span> → <span className="text-pos">{after[k]}</span>
                      </span>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Card>

      <Card title="Version History">
        <div className="flex gap-2 flex-wrap">
          {history.map((h) => (
            <span
              key={h.id}
              className={`text-xs font-mono px-2 py-1 rounded border ${h.active ? "border-pos/40 text-pos bg-pos/10" : "border-edge text-dim"}`}
            >
              v{h.version} {h.active && "● active"}
            </span>
          ))}
        </div>
      </Card>
    </div>
  );
}
