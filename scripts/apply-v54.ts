/**
 * apply:v54 — C-200 band reallocation (2026-09-15 C-200 daily report Rec 1,
 * user-approved): move size out of the mid-price dead zone into the long-shot
 * band.
 *
 *   c200LongshotBandFactor  2.0  → 2.5    (<0.20 entries, +25% on the band map)
 *   c200DeadZoneBandFactor  0.25 → 0.125  (0.40–0.60 entries, −50%)
 *
 * Evidence (daily report 2026-09-15, Polymarket-only, decision-level checked):
 *   ≤0.20 is the only positive-ROI band all-time (+$100 on $2,370 = +4.23%) and
 *   the only band significant-positive in BOTH the row-level and decision-level
 *   cuts (row-level z=+4.56). 0.40–0.60 is the biggest loss bucket (−$325 on
 *   $3,884 = −8.36%; last 14d −11.5%). Capital-neutral against the binding
 *   exposure cap: the shrunk dead-zone notional funds the larger long-shot clips.
 *
 * SCOPE — why these are NEW fields and not the existing v37 rules-layer factors:
 *   deadZoneSizeFactor / longshotSizeFactor are read by the SHARED scorer
 *   (src/lib/scoring/trade.ts) for every bot, so flipping them would resize
 *   STANDARD too and would double-apply on the C-200 legacy path (the v41
 *   neutralization to 1.0 exists to prevent exactly that). The C-200 fields are
 *   consumed only by paper.ts mapBankroll200Size, and the Kelly rails compare
 *   against the same factors so both C-200 paths move together.
 *
 * WINDOW CAVEAT (explicit): this lands mid-Kelly-window (Sep 8–Oct 8), so it
 * tags itself on every journal row via ruleSetVersion v54 — attribute by window
 * (`analyze-calibration.py --since`), not by the Oct 8 total. Revert is one field
 * each; defaults in DEFAULT_RULES reproduce pre-v54 sizing exactly.
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v54.ts
 */

import { prisma } from "../src/lib/db";
import { applyRuleChanges } from "../src/lib/rules";
import { log, logError } from "../src/lib/redact";

const PROPOSALS = [
  {
    field: "c200LongshotBandFactor" as const,
    newValue: 2.5,
    reason:
      "v54 Rec 1 (user-approved 2026-09-15): reallocate size into the long-shot band — the only positive-ROI band all-time and the only one significant-positive in both sample cuts",
    evidence:
      "≤0.20: +$100 on $2,370 (+4.23% ROI), row-level z=+4.56, decision-level z=+2.99. Funded by the dead-zone cut below; capital-neutral against the binding exposure cap.",
  },
  {
    field: "c200DeadZoneBandFactor" as const,
    newValue: 0.125,
    reason:
      "v54 Rec 1 (user-approved 2026-09-15): halve the dead-zone size again to fund the long-shot increase — 0.40–0.60 is the largest loss bucket in the book",
    evidence:
      "0.40–0.60: −$325 on $3,884 (−8.36% all-time, −11.5% over the last 14d); decision-level excess −0.0791 (z=−2.87). Kelly already skips the band via λ̂=+0.03, so this bites the legacy + short-TTR-lane path and hardens the Kelly dead-zone rail.",
  },
];

async function main() {
  const before = await prisma.ruleSet.findFirst({ where: { active: true }, orderBy: { version: "desc" } });
  if (before) {
    const j = JSON.parse(before.rulesJson) as Record<string, unknown>;
    log(
      `apply:v54 before — v${before.version} c200LongshotBandFactor=${j.c200LongshotBandFactor ?? "(unset→2.0)"} ` +
        `c200DeadZoneBandFactor=${j.c200DeadZoneBandFactor ?? "(unset→0.25)"} ` +
        `(shared v37 factors untouched: longshotSizeFactor=${j.longshotSizeFactor}, deadZoneSizeFactor=${j.deadZoneSizeFactor})`
    );
  }
  const result = await applyRuleChanges(PROPOSALS, "hermes-v54-daily-rep-rec1-approved");
  if (!result) {
    log("No changes applied.");
    return;
  }
  log(
    `RuleSet v${result.newVersion} activated (C-200 band map: long-shot ×2.5, dead zone ×0.125; ` +
      `premium ≥0.60 stays ×0.5). RuleChange audit row written.`
  );
}

main()
  .catch((e) => {
    logError("apply:v54 FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
