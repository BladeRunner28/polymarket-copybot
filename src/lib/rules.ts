/**
 * Versioned rule sets. Rules govern scoring thresholds and can be changed
 * automatically by the rule updater — but every change is recorded in
 * RuleChange with reason, evidence, and before/after values.
 */

import { prisma } from "./db";

export interface Rules {
  // Trade-level gates
  maxSpread: number; // skip if spread wider than this
  minLiquidity: number; // skip if market liquidity below this (USD)
  maxPriceDrift: number; // skip if price moved more than this since wallet entry
  minTimeToResolutionHours: number; // skip if resolving too soon to copy
  minCopyScore: number; // paper_copy threshold (0..100)
  watchlistScore: number; // watchlist threshold (0..100)
  maxEntryPrice: number; // skip if price beyond this certainty band (also mirrored low side)
  maxCopiesPerCycle: number; // per scoring-run cap on new paper copies
  maxCopiesPerWalletPerDay: number; // per-wallet daily paper-copy cap
  // Wallet-level gates
  minWalletGlobalScore: number; // ignore signals from wallets below this
  minResolvedTrades: number; // wallets with fewer resolved trades are unproven
  // Scoring weights (wallet)
  weightRoi: number;
  weightConsistency: number;
  weightCopyability: number;
  // Sizing
  baseSizeUsd: number; // base paper size
  confidenceSizeBonus: number; // extra USD per point of confidence above 0.5
}

export const DEFAULT_RULES: Rules = {
  maxSpread: 0.05,
  minLiquidity: 5000,
  maxPriceDrift: 0.08,
  minTimeToResolutionHours: 12,
  minCopyScore: 65,
  watchlistScore: 45,
  maxEntryPrice: 0.88,
  maxCopiesPerCycle: 50,
  maxCopiesPerWalletPerDay: 10,
  minWalletGlobalScore: 55,
  minResolvedTrades: 5,
  weightRoi: 0.35,
  weightConsistency: 0.35,
  weightCopyability: 0.3,
  baseSizeUsd: 8,
  confidenceSizeBonus: 20,
};

export async function getActiveRules(): Promise<{ rules: Rules; version: number; id: string }> {
  let active = await prisma.ruleSet.findFirst({ where: { active: true }, orderBy: { version: "desc" } });
  if (!active) {
    active = await prisma.ruleSet.create({
      data: { version: 1, active: true, rulesJson: JSON.stringify(DEFAULT_RULES) },
    });
  }
  const parsed = { ...DEFAULT_RULES, ...(JSON.parse(active.rulesJson) as Partial<Rules>) };
  return { rules: parsed, version: active.version, id: active.id };
}

export interface RuleChangeProposal {
  field: keyof Rules;
  newValue: number;
  reason: string;
  evidence: string;
}

/**
 * Apply proposals as a new rule version. Old version is deactivated, the new
 * one activated, and a RuleChange row records everything.
 */
export async function applyRuleChanges(
  proposals: RuleChangeProposal[],
  changedBy = "hermes"
): Promise<{ newVersion: number } | null> {
  if (proposals.length === 0) return null;
  const { rules, version, id: oldId } = await getActiveRules();
  const before: Record<string, number> = {};
  const after: Record<string, number> = {};
  const newRules: Rules = { ...rules };
  for (const p of proposals) {
    before[p.field] = rules[p.field];
    (newRules as unknown as Record<string, number>)[p.field] = p.newValue;
    after[p.field] = p.newValue;
  }
  const newVersion = version + 1;
  const created = await prisma.$transaction(async (tx) => {
    await tx.ruleSet.update({ where: { id: oldId }, data: { active: false } });
    const ns = await tx.ruleSet.create({
      data: { version: newVersion, active: true, rulesJson: JSON.stringify(newRules) },
    });
    await tx.ruleChange.create({
      data: {
        oldRuleSetId: oldId,
        newRuleSetId: ns.id,
        changedBy,
        reason: proposals.map((p) => p.reason).join(" | "),
        evidenceSummary: proposals.map((p) => p.evidence).join(" | "),
        beforeJson: JSON.stringify(before),
        afterJson: JSON.stringify(after),
      },
    });
    return ns;
  });
  return { newVersion: created.version };
}
