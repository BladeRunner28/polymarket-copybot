/**
 * apply:v57 — 2026-09-18 C-200 daily report changes A + B (both user-approved).
 *
 *   A. longshotDriftPct 0 → 0.08     (price-relative drift tolerance in the <0.20 band)
 *   B. (code only — applyKellyBandRails now caps [0.20, 0.60); no rule field)
 *
 * A — WHY: 245 of 405 C-200 vetoes in 24h were `price drifted … > 0.004`. A flat
 * 0.4c tolerance is 0.7% of price at 0.60 but 2–8% of price at 0.05–0.20, so the
 * band carrying the widest measured edge (excess +22.5pp, z=+5.79) was the most
 * drift-starved: 5 long-shot entries worth $330 in 24h while the losing 0.20–0.40
 * band got 11 worth $405. Tolerance becomes max(maxPriceDrift, pct × price) capped
 * at longshotDriftCap (0.02) — 0.004 at 5c, 0.012 at 15c, 0.016 at 20c.
 *
 * B — WHY: 0.20–0.40 shows a significant POSITIVE entry edge (+6.4pp, z=+2.37) yet
 * −$429.77 realized, and the 14d clip-size split explains it: ≤$15 → +$149 on 84
 * trades, $15–30 → −$116 on 17, ≥$30 → −$331 on 8. Its band map is ×1.0 so Kelly
 * rode it to the $100 ceiling. The rail now caps it at the legacy-equivalent size.
 *
 * WINDOW CAVEAT (explicit): A moves the drift gate mid-Kelly-window, which the
 * 09-16 report itself flagged as contaminating the Oct 8 read (the pre-Kelly
 * baseline was measured at drift 0.004). Every journal row now carries
 * ruleSetVersion v57, so attribute A by window (`analyze-calibration.py --since`),
 * not by the Oct 8 total.
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v57.ts
 */

import { prisma } from "../src/lib/db";
import { applyRuleChanges } from "../src/lib/rules";
import { log, logError } from "../src/lib/redact";

const PROPOSALS = [
  {
    field: "longshotDriftPct" as const,
    newValue: 0.08,
    reason:
      "v57 change A (user-approved 2026-09-18): make the drift tolerance price-relative inside the long-shot band, where a flat 0.4c is 2-8% of price instead of 0.7%",
    evidence:
      "245 of 405 C-200 vetoes/24h were the drift gate; 24h flow 5 long-shot entries ($330) vs 11 in the losing 0.20-0.40 band ($405); the band's all-time excess is +22.5pp (z=+5.79). Tolerance = max(maxPriceDrift, 0.08 x price) capped at longshotDriftCap 0.02 -> 0.004 at 5c, 0.012 at 15c, 0.016 at 20c.",
  },
];

async function main() {
  const before = await prisma.ruleSet.findFirst({ where: { active: true }, orderBy: { version: "desc" } });
  if (before) {
    const j = JSON.parse(before.rulesJson) as Record<string, unknown>;
    log(
      `apply:v57 before — v${before.version} longshotDriftPct=${j.longshotDriftPct ?? "(unset→0)"} ` +
        `longshotDriftCap=${j.longshotDriftCap ?? "(unset→0.02)"} maxPriceDrift=${j.maxPriceDrift}`
    );
  }
  const result = await applyRuleChanges(PROPOSALS, "hermes-v57-daily-rep-changesAB-approved");
  if (!result) {
    log("No changes applied.");
    return;
  }
  log(
    `RuleSet v${result.newVersion} activated (long-shot drift tolerance = 8% of price, capped 0.02; ` +
      `change B ships in code — applyKellyBandRails caps [0.20, 0.60)). RuleChange audit row written.`
  );
}

main()
  .catch((e) => {
    logError("apply:v57 FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
