/**
 * apply:v53 — C-200 change 1 (tuning review #21 rec 1, user-approved
 * 2026-09-13 in the daily-report thread): make the tier-1 stale exit
 * ADVERSE-ONLY.
 *
 * Context: the pre-v53 tier-1 rule closed any C-200 position older than
 * staleExitHours (24) whose winMove < staleExitMinMove (+5%) — i.e. "flat at
 * 24h is a loss". That rule produced the entire Polymarket hole:
 *   24–72h exits: 1,069 rows, −$1,215.72 on $7,152 staked (−17.0% ROI, 44% win)
 *   every other hold window is positive (>168h +$99.32, 72–168h +$100.69,
 *   resolutions +$579.61); excluding the 24–72h cut rows, Polymarket realized
 *   is +$817.81.
 *
 * This apply script flips the new v53 switch so the tier-1 cut fires ONLY on
 * an adverse move (winMove ≤ −15%), leaving flat/slightly-up positions to run
 * to the staleExitHardHours (168h) max-age, which is unchanged.
 *
 * WINDOW CONTAMINATION (explicit user override): the pre-registered Kelly
 * window is Sep 8 – Oct 8. This change lands mid-window, so the Oct 8 read is
 * "Kelly + v53 stale-exit", not a pure Kelly read. Change-level attribution
 * comes from data/calibration-analysis-since-*.json windows, not the window
 * total. Revert = apply-v54 restoring staleExitAdverseOnly 0 (legacy path is
 * kept byte-identical in update-pnl.ts).
 *
 * User decision context (2026-09-13 clarify): trigger variant = adverse-only at
 * ≥24h with winMove ≤ −15%, 168h hard cap kept. Change 2 (ET 08/20 entry-hour
 * gates + 0.60–0.80 band gate) was NOT approved for now — it is queued to the
 * Oct 8 window close with shadow measurement (roadmap card change2-oct8-gates).
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v53.ts
 */

import { prisma } from "../src/lib/db";
import { applyRuleChanges } from "../src/lib/rules";
import { log, logError } from "../src/lib/redact";

const PROPOSALS = [
  {
    field: "staleExitAdverseOnly" as const,
    newValue: 1,
    reason:
      "v53 Change 1 (user-approved 2026-09-13): tier-1 stale exit becomes adverse-only — close at ≥24h only when winMove ≤ −15%, instead of the 'flat is bad' winMove < +5% cut",
    evidence:
      "24–72h exits: 1,069 rows, −$1,215.72 on $7,152 staked (−17.0% ROI, 44% win) — the entire Polymarket hole; all other hold windows positive (resolutions +$579.61, 72–168h +$100.69, >168h +$99.32); excluding the cut rows Polymarket realized = +$817.81. Calibration (N=1,453): 0.20–0.40 shows positive entry edge (excess +0.0754, z=+2.60) yet negative realized PnL (−$208.46) — the early-exit churn signature. Blast radius at apply: of 30 open C-200 rows ≥24h, 29 are already ≥+5% and 1 is ≤−15%.",
  },
  {
    field: "staleExitAdverseMove" as const,
    newValue: -0.15,
    reason:
      "v53 Change 1 (user-approved 2026-09-13): adverse threshold −15% (the value offered in the report; the −10% variant was declined)",
    evidence:
      "User selected 'adverse-only: cut at ≥24h only if winMove ≤ −15% (keep the 168h hard cap)' from the 2026-09-13 option set. staleExitHours stays 24 as the tier-1 age gate; staleExitHardHours stays 168 as the unconditional backstop.",
  },
];

async function main() {
  const before = await prisma.ruleSet.findFirst({ where: { active: true }, orderBy: { version: "desc" } });
  if (before) {
    const j = JSON.parse(before.rulesJson) as Record<string, unknown>;
    log(
      `apply:v53 before — v${before.version} staleExitAdverseOnly=${j.staleExitAdverseOnly ?? "(unset→0 legacy)"} ` +
        `staleExitHours=${j.staleExitHours} staleExitMinMove=${j.staleExitMinMove} staleExitHardHours=${j.staleExitHardHours}`
    );
  }
  const result = await applyRuleChanges(PROPOSALS, "hermes-v53-tr21-change1-approved");
  if (!result) {
    log("No changes applied.");
    return;
  }
  log(
    `RuleSet v${result.newVersion} activated (staleExitAdverseOnly=1, staleExitAdverseMove=-0.15, ` +
      `staleExitHours 24 / staleExitHardHours 168 unchanged). RuleChange audit row written.`
  );
}

main()
  .catch((e) => {
    logError("apply:v53 FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
