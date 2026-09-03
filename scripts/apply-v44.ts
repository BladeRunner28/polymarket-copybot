/**
 * apply:v44 — one-off activation of RuleSet v44 with the tuning review #13
 * recommendations (2026-09-02, user-approved: "Approved for all 6").
 *
 * v44 adds the STANDARD high-side entry cap field:
 *   - standardMaxEntryPrice 0.85: per-leg STANDARD gate in score-trades.ts —
 *     entries ≥ 0.85 skip the STANDARD book only. NOT the shared maxEntryPrice
 *     (symmetric [1−max, max]; lowering it would kill the <0.15 long-shot
 *     edge). C-200 de-risks ≥0.60 via band sizing instead.
 * Other #13 recs are code (hour blackout for STANDARD, 48h auto-tune lockout,
 * monitor parallelism, API_DELAY_MS trim) — see drafts/tuning-review-13-implementation.md.
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v44.ts
 */

import { prisma } from "../src/lib/db";
import { applyRuleChanges } from "../src/lib/rules";
import { log, logError } from "../src/lib/redact";

const PROPOSALS = [
  {
    field: "standardMaxEntryPrice" as const,
    newValue: 0.85,
    reason:
      "STANDARD high-side entry cap (tuning review #13 rec 4, approved): entries 0.80–1.01 are STANDARD's worst band — per-leg gate so the symmetric shared maxEntryPrice (0.95, band 0.05–0.95) can't kill the <0.15 long-shot edge",
    evidence:
      "STANDARD 3rd consecutive down day; window-opened −$622 worst on record; EOD calibration 0.80–1.01 band excess −0.0865 (z=−2.50, p=0.013); premium-drag effect corroborated on C-200 (z=−2.42/−2.50 across refits)",
  },
];

async function main() {
  const result = await applyRuleChanges(PROPOSALS, "hermes-v44-tuning-review13");
  if (!result) {
    log("No changes applied.");
    return;
  }
  log(`RuleSet v${result.newVersion} activated (standardMaxEntryPrice 0.85). RuleChange audit row written.`);
}

main()
  .catch((e) => {
    logError("apply:v44 FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
