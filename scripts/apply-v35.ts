/**
 * apply:v35 — one-off activation of RuleSet v35 (C-200 daily report
 * 2026-08-29 18:07 recommendations): staleExitHours 72→48 + highScoreCapUsd
 * 10→18. Versioned, audited path. See drafts/v33-draft.md (v35 section).
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v35.ts
 */

import { prisma } from "../src/lib/db";
import { applyRuleChanges } from "../src/lib/rules";
import { log, logError } from "../src/lib/redact";

const REASON_TIGHTEN =
  "Tighten stale-exit tier-1 72→48h: capital-recycling sweep must turn over faster — every recycled dollar feeds the 70–79/80+ sweet spot (report: ~96% of bankroll was stranded in 9.4d-avg positions)";
const EVIDENCE_TIGHTEN =
  "2026-08-29 18:07 report: 160 open, avg age 9.4d, ~$980 capital-equivalent stranded; v33 hard max-age swept 80 (Aug 29 21:15, +$112 realized); tier-1 tighten is the ongoing turnover gate";
const REASON_SIZING =
  "Raise highScoreCapUsd 10→18 to match sweetSpotSizeUsd: fresh 30d data has the ≥80 band as the BEST bucket (+$0.57/trade, 256) — the v29 penalty cap was sizing winners smallest; drift ceiling 0.004 stays as the quality gate";
const EVIDENCE_SIZING =
  "2026-08-29 18:07 report bucket data (30d): 80+ +$0.57/trade (256), 70–79 +$0.36 (454), 55–69 −$0.84 (already cut by v31 minCopyScore 70)";

async function main() {
  const result = await applyRuleChanges(
    [
      { field: "staleExitHours", newValue: 48, reason: REASON_TIGHTEN, evidence: EVIDENCE_TIGHTEN },
      { field: "highScoreCapUsd", newValue: 18, reason: REASON_SIZING, evidence: EVIDENCE_SIZING },
    ],
    "hermes-v35-daily-report"
  );
  if (!result) {
    log("No changes applied.");
    return;
  }
  log(`RuleSet v${result.newVersion} activated (staleExitHours 48, highScoreCapUsd 18). RuleChange audit row written.`);
}

main()
  .catch((e) => {
    logError("apply:v35 FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
