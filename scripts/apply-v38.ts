/**
 * apply:v38 — one-off activation of RuleSet v38 (Phase A: Wang-Transform
 * premium overlay parameters). The overlay is measurement-first: sizes are
 * adjusted by the calibrated λ̂ table and every C-200 copy carries a premium
 * risk tag. See drafts/wang-calibration-audit.md.
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v38.ts
 */

import { prisma } from "../src/lib/db";
import { applyRuleChanges } from "../src/lib/rules";
import { log, logError } from "../src/lib/redact";

const PROPOSALS = [
  {
    field: "premiumOverlayEnabled" as const,
    newValue: 1,
    reason:
      "Enable Phase-A premium overlay (measurement-first): size × clamp(1 − k·λ̂) on C-200 main-lane copies using the Wang-Transform calibrated λ̂ table; risk-tag every C-200 copy",
    evidence:
      "2026-08-31 calibration (WangMLE on 8,388 finished copybot trades): C-200 λ̂ by band <0.20 −1.20, 0.2–0.4 −0.24, 0.4–0.6 −0.02, 0.6–0.8 +0.25, 0.8–1.0 +0.35; Kalshi +0.31 (premium drag)",
  },
  {
    field: "premiumOverlayK" as const,
    newValue: 0.5,
    reason: "Size-factor sensitivity: λ̂=−1.20 → ×1.60; λ̂=+0.35 → ×0.83",
    evidence: "Calibrated λ̂ distribution (see audit); conservative k to stay measurement-first",
  },
  {
    field: "premiumOverlayMinFactor" as const,
    newValue: 0.5,
    reason: "Floor the overlay factor (never shrink a copy below half size)",
    evidence: "Paper-only sizing guard; half-Kelly-style conservatism",
  },
  {
    field: "premiumOverlayMaxFactor" as const,
    newValue: 2.0,
    reason: "Ceiling the overlay factor (never more than 2× from premium edge)",
    evidence: "Bounded by the existing 45.00 hard cap in score-trades",
  },
];

async function main() {
  const result = await applyRuleChanges(PROPOSALS, "hermes-v38-premium-overlay");
  if (!result) {
    log("No changes applied.");
    return;
  }
  log(`RuleSet v${result.newVersion} activated (premium overlay params). RuleChange audit row written.`);
}

main()
  .catch((e) => {
    logError("apply:v38 FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
