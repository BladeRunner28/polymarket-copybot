/**
 * Automatic rule updater — the self-improvement loop.
 * Analyzes resolved paper trades + outcome reviews and proposes evidence-based
 * threshold changes. Applies them WITHOUT asking approval (paper-trading only),
 * but every change is versioned and logged via applyRuleChanges().
 */

import { prisma } from "./db";
import { getActiveRules, applyRuleChanges, RuleChangeProposal, Rules } from "./rules";

interface ResolvedSample {
  pnl: number;
  spread: number | null;
  liquidity: number | null;
  drift: number;
  walletScore: number;
}

const MIN_SAMPLES = 6; // don't change rules on tiny evidence

async function collectSamples(): Promise<ResolvedSample[]> {
  const trades = await prisma.paperTrade.findMany({
    where: { status: "resolved", realizedPnl: { not: null } },
    include: { decision: { include: { observedTrade: true } } },
  });
  const samples: ResolvedSample[] = [];
  for (const t of trades) {
    const d = t.decision;
    const snap = await prisma.marketSnapshot.findFirst({
      where: { marketId: t.marketId },
      orderBy: { collectedAt: "desc" },
    });
    samples.push({
      pnl: t.realizedPnl ?? 0,
      spread: snap?.spread ?? null,
      liquidity: snap?.liquidity ?? null,
      drift: Math.abs(d.observedTrade.detectedPrice - d.observedTrade.walletEntryPrice),
      walletScore: d.walletQualityScore,
    });
  }
  return samples;
}

export function proposeRuleChanges(samples: ResolvedSample[], rules: Rules): RuleChangeProposal[] {
  const proposals: RuleChangeProposal[] = [];
  if (samples.length < MIN_SAMPLES) return proposals;

  const round = (v: number, d = 4) => Math.round(v * 10 ** d) / 10 ** d;

  // 1) Spread: if wide-spread trades underperform, tighten maxSpread.
  const wide = samples.filter((s) => (s.spread ?? 0) > rules.maxSpread * 0.6);
  const tight = samples.filter((s) => (s.spread ?? 0) <= rules.maxSpread * 0.6);
  if (wide.length >= 3 && tight.length >= 3) {
    const wideAvg = wide.reduce((a, s) => a + s.pnl, 0) / wide.length;
    const tightAvg = tight.reduce((a, s) => a + s.pnl, 0) / tight.length;
    if (wideAvg < 0 && wideAvg < tightAvg - 1) {
      proposals.push({
        field: "maxSpread",
        newValue: round(rules.maxSpread * 0.8),
        reason: "Wide-spread trades underperform tighter ones",
        evidence: `avg PnL wide=${wideAvg.toFixed(2)} vs tight=${tightAvg.toFixed(2)} over ${samples.length} resolved trades`,
      });
    }
  }

  // 2) Liquidity: if low-liquidity trades lose, raise minLiquidity.
  const lowLiq = samples.filter((s) => (s.liquidity ?? Infinity) < rules.minLiquidity * 2);
  const highLiq = samples.filter((s) => (s.liquidity ?? 0) >= rules.minLiquidity * 2);
  if (lowLiq.length >= 3 && highLiq.length >= 3) {
    const lowAvg = lowLiq.reduce((a, s) => a + s.pnl, 0) / lowLiq.length;
    const highAvg = highLiq.reduce((a, s) => a + s.pnl, 0) / highLiq.length;
    if (lowAvg < 0 && lowAvg < highAvg - 1) {
      proposals.push({
        field: "minLiquidity",
        newValue: Math.round(rules.minLiquidity * 1.5),
        reason: "Low-liquidity trades perform poorly",
        evidence: `avg PnL lowLiq=${lowAvg.toFixed(2)} vs highLiq=${highAvg.toFixed(2)}`,
      });
    }
  }

  // 3) Late entries: if high-drift trades lose, reduce maxPriceDrift.
  const late = samples.filter((s) => s.drift > rules.maxPriceDrift * 0.6);
  const early = samples.filter((s) => s.drift <= rules.maxPriceDrift * 0.6);
  if (late.length >= 3 && early.length >= 3) {
    const lateAvg = late.reduce((a, s) => a + s.pnl, 0) / late.length;
    const earlyAvg = early.reduce((a, s) => a + s.pnl, 0) / early.length;
    if (lateAvg < 0 && lateAvg < earlyAvg - 1) {
      proposals.push({
        field: "maxPriceDrift",
        newValue: round(rules.maxPriceDrift * 0.75),
        reason: "Late entries (large price drift since wallet entry) lose money",
        evidence: `avg PnL late=${lateAvg.toFixed(2)} vs early=${earlyAvg.toFixed(2)}`,
      });
    }
  }

  // 4) Overall losing streak: raise the copy bar.
  const totalPnl = samples.reduce((a, s) => a + s.pnl, 0);
  const winRate = samples.filter((s) => s.pnl > 0).length / samples.length;
  if (totalPnl < 0 && winRate < 0.45 && rules.minCopyScore < 85) {
    proposals.push({
      field: "minCopyScore",
      newValue: Math.min(85, rules.minCopyScore + 3),
      reason: "Overall paper performance negative — raising copy threshold",
      evidence: `total PnL ${totalPnl.toFixed(2)}, win rate ${(winRate * 100).toFixed(0)}% across ${samples.length} resolved trades`,
    });
  }

  // 5) Winning comfortably: relax threshold slightly to catch more signals.
  // v31: never relax below the sweet-spot floor — scores < sweetSpotMinScore
  // are the losing tail (55–69 was −$0.99/trade, −24% edge in Aug 2026 data).
  // v37: the floor follows the current best-known bar — highScoreCapMin (80)
  // is the proven best bucket in 30d data (+$0.57/trade), so a hot streak
  // can't erode the v37 quality bar back to the sweet-spot floor.
  const copyFloor = Math.max(rules.highScoreCapMin, rules.sweetSpotMinScore, 55);
  if (totalPnl > 20 && winRate > 0.6 && rules.minCopyScore > copyFloor) {
    proposals.push({
      field: "minCopyScore",
      newValue: Math.max(copyFloor, rules.minCopyScore - 2),
      reason: "Strategy is winning — cautiously widening the funnel",
      evidence: `total PnL +${totalPnl.toFixed(2)}, win rate ${(winRate * 100).toFixed(0)}%`,
    });
  }

  return proposals;
}

/** Full self-improvement pass. Returns what changed (or null). */
export async function runRuleUpdate(): Promise<{ newVersion: number; changes: RuleChangeProposal[] } | null> {
  const { rules } = await getActiveRules();
  const samples = await collectSamples();
  const proposals = proposeRuleChanges(samples, rules);
  if (proposals.length === 0) return null;
  const applied = await applyRuleChanges(proposals, "hermes");
  if (!applied) return null;

  // Downgrade wallets with poor recent paper performance.
  const badWallets = await prisma.paperTrade.groupBy({
    by: ["walletAddress"],
    where: { status: "resolved" },
    _sum: { realizedPnl: true },
    _count: { id: true },
  });
  for (const w of badWallets) {
    if ((w._count.id ?? 0) >= 3 && (w._sum.realizedPnl ?? 0) < -10) {
      await prisma.walletProfile.updateMany({
        where: { address: w.walletAddress, status: "track" },
        data: {
          status: "watch",
          riskNotes: `Downgraded by rule updater: paper PnL ${w._sum.realizedPnl?.toFixed(2)} over ${w._count.id} resolved copies`,
        },
      });
    }
  }

  return { newVersion: applied.newVersion, changes: proposals };
}
