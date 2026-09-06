/**
 * apply:v48 — one-off activation of RuleSet v48 with the 2026-09-04 daily
 * report recommendations (user-approved: "Both approved").
 *
 * v48 adds band-aware admission floors for the <0.20 long-shot band:
 *   - longshotMinCopyScore 70 (global minCopyScore stays 80)
 *   - longshotMinConfidence 0.55 (global minConfidence stays 0.7)
 * The band (z=+3.81, the only +PnL band: +$94.59 on 64 trades) is
 * structurally anti-selected by win-rate-derived bars — post-v37 floors
 * admitted 3 of 64 of its signals. Relaxed floors apply ONLY when the entry
 * price < longshotMaxPrice; spread/liquidity/drift and the v47 ≤0.80 cap
 * stay global. Code in src/lib/scoring/trade.ts; 0 disables per-field.
 *
 * Rec 2 (hour gating) was a CODE change (hour-policy.ts: 23:00 un-gated —
 * phantom-Kalshi artifact; 20:00 stays) + analyze-calibration.py venue
 * filter. No ruleset fields.
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v48.ts
 */

import { prisma } from "../src/lib/db";
import { applyRuleChanges } from "../src/lib/rules";
import { log, logError } from "../src/lib/redact";

const PROPOSALS = [
  {
    field: "longshotMinCopyScore" as const,
    newValue: 70,
    reason:
      "Band-aware admission (2026-09-04 daily report rec 1, approved): relax the copy-score floor to 70 for <0.20 entries — the only +PnL band is structurally anti-selected by the win-rate-derived 80 bar (low win rate is why long-shots are priced at ~12¢)",
    evidence:
      "Calibration N=1,167 (2026-09-04): <0.20 z=+3.81, excess +22.6pp, +$94.59 on 64 trades; median historical copyScore 72 — the 80-bar admitted 3/64; post-v37 the band got 4 entries in 4.5 days",
  },
  {
    field: "longshotMinConfidence" as const,
    newValue: 0.55,
    reason:
      "Band-aware admission (rec 1): relax the confidence floor to 0.55 for <0.20 entries (median historical confidence 0.57 — the 0.7 floor admitted 2/64)",
    evidence: "Same calibration split; measure 7–10 days then re-run analyze-calibration.py; re-tighten if the edge doesn't survive at the old rate",
  },
];

async function main() {
  const result = await applyRuleChanges(PROPOSALS, "hermes-v48-daily-report");
  if (!result) {
    log("No changes applied.");
    return;
  }
  log(`RuleSet v${result.newVersion} activated (long-shot band floors 70/0.55). RuleChange audit row written.`);
}

main()
  .catch((e) => {
    logError("apply:v48 FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
