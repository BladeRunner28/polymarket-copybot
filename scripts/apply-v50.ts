/**
 * apply:v50 — one-off activation of RuleSet v50 (2026-09-06 C-200 daily report
 * operational changes 1–2, user-approved "I approve" → caps-only scope
 * confirmed via clarify 2026-09-06).
 *
 * v50 raises the C-200 physical ceiling (pure paper risk — the report's
 * structural case: $500/day is +45% of the bankroll; with a $400 gross cap
 * and $60 Kelly max the best sampled day was ~+$207, so a $500 streak day is
 * physically impossible under v49's caps):
 *   - maxGrossExposureUsd 400 → 1,000  (equity-linked base; NW $1,651 <
 *     $1,900 principal → effective cap = base = $1,000 until the realized
 *     hole repays; un-starves the Kelly window before it opens Sep 8)
 *   - kellyMaxSizeUsd 60 → 100         (per-position hard cap — funds the
 *     ≤0.20 (λ̂=−0.91) and 0.20–0.40 (λ̂=−0.21) bands harder)
 *   - dailyLossLimitUsd −150 → −300    (daily halt guardrail scaled with the
 *     bigger book, per the report's "scale the guardrail proportionally")
 *
 * Explicitly NOT changed (verified against live v49 architecture, user chose
 * caps-only): deadZone/longshot size factors stay neutralized at 1.0 (v39
 * design — paper.ts mapBankroll200Size owns the legacy tilt; Kelly sizes
 * main-lane copies from the same band λ̂ and already skips 0.40–0.60
 * (λ̂=+0.03 → f*<0) and ≥0.60 (λ̂=+0.21/0.37) while funding <0.20);
 * premiumOverlayEnabled stays 0 (inert under Kelly — Kelly IS the λ̂
 * mechanism); hour gates stay as-is (10:00 ET 50% haircut v41, 20:00 ET
 * blackout v44/v48 — both already live).
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v50.ts
 */

import { prisma } from "../src/lib/db";
import { applyRuleChanges } from "../src/lib/rules";
import { log, logError } from "../src/lib/redact";

const PROPOSALS = [
  {
    field: "maxGrossExposureUsd" as const,
    newValue: 1000,
    reason:
      "C-200 physical ceiling (2026-09-06 daily report op-change 2, approved; caps-only scope): gross exposure base $400 → $1,000 — $500/day is +45% of bankroll; the v49 $400 cap pins the book at $401–408 and caps realistic good days near ~$200. Equity-link unchanged: NW $1,651 < $1,900 principal → effective cap = base until the realized hole repays.",
    evidence:
      "Sep-6 calibration N=1,176: best sampled day +$206.78 (Aug 29); 7×$500 streak physically impossible under v49 caps. Also un-starves the Kelly window (0 [KELLY] lines in v49's first 5h — main-lane admits exposure-vetoed at the $400 pin).",
  },
  {
    field: "kellyMaxSizeUsd" as const,
    newValue: 100,
    reason:
      "Kelly per-position hard cap $60 → $100 (op-change 2): funds the calibrated-edge bands (≤0.20 λ̂=−0.91, 0.20–0.40 λ̂=−0.21) harder; still bounded by fractional-Kelly f*, 10%-bankroll cap, and the $1,000 gross exposure cap.",
    evidence: "Same Sep-6 calibration; Kelly main-lane sizing is cap-bound at $60 for its best edges.",
  },
  {
    field: "dailyLossLimitUsd" as const,
    newValue: -300,
    reason:
      "Daily-loss guardrail scaled with the bigger book (op-change 2): −$150 → −$300 so the v40 daily halt doesn't fire at the old scale while the book can now run ~2.5× gross.",
    evidence: "Report: 'scale the guardrail proportionally'. Pure paper risk; phase gate unchanged (still 7 consecutive ≥$500 realized days).",
  },
];

async function main() {
  const result = await applyRuleChanges(PROPOSALS, "hermes-v50-c200-report");
  if (!result) {
    log("No changes applied.");
    return;
  }
  log(
    `RuleSet v${result.newVersion} activated (gross cap $1,000 · Kelly max $100 · daily loss −$300). RuleChange audit row written.`
  );
}

main()
  .catch((e) => {
    logError("apply:v50 FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
