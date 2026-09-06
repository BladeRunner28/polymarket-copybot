/**
 * apply:v49 — Phase B Kelly sizing activation (drafts/phase-b-kelly-design.md,
 * user-approved "keep going" 2026-09-05; ship window opens Tue 2026-09-08).
 *
 * Activates the 6 Kelly RuleSet fields (kellyEnabled=1 + sizer params) and
 * disables the v38 premium overlay (premiumOverlayEnabled=0) in ONE ruleset
 * version, per design §4 — Kelly's λ̂-based edge makes the overlay's
 * size × clamp(1 − k·λ̂) redundant; both are revertible by rule change
 * (kellyEnabled→0 restores the legacy sizing path byte-identical).
 *
 * Wiring (code, shipped with this activation):
 *   - scripts/score-trades.ts: Kelly decides size AND skip for C-200
 *     main-lane copies; replaces the ×3 confidence boost; premium-overlay
 *     resize skipped on Kelly-sized copies; [KELLY] log line per decision.
 *   - src/lib/paper.ts openPaperTrade: `kelly` param bypasses the v41 band
 *     remap and clamps at kellyMaxSizeUsd (executor cap override — the real
 *     legacy per-position cap was BOT_LIMITS $20, not the doc's "$45").
 *   - src/lib/safety.ts clampPaperSize: optional per-call max override.
 *   - src/lib/kelly.ts + tests/kelly.test.ts: pure sizer (18 tests).
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v49.ts
 */

import { prisma } from "../src/lib/db";
import { applyRuleChanges } from "../src/lib/rules";
import { log, logError } from "../src/lib/redact";

const PROPOSALS = [
  {
    field: "kellyEnabled" as const,
    newValue: 1,
    reason:
      "Phase B activation (drafts/phase-b-kelly-design.md, approved): Kelly sizing for C-200 main-lane copies — the calibrated edge (band λ̂, biweekly Wang refit) decides size AND skip. Replaces the ×3 confidence boost + v38 premium overlay with f* = (q−p)/(1−p) on the bought token",
    evidence:
      "Sep-1 λ̂ table aligns with realized band PnL (2026-09-05): <0.20 λ̂=−0.91/+$93 and 0.20–0.40 λ̂=−0.21/+$62 size; 0.40–0.60 λ̂≈0 skips the −$434 mid-band by construction; ≥0.60 skipped. Pre-registered window Sep 8–Oct 8 (phase-b-kelly-design.md §6)",
  },
  {
    field: "kellyFraction" as const,
    newValue: 0.5,
    reason: "Phase B: half-Kelly multiplier — full Kelly is too aggressive for a still-validating edge (design §3/§5)",
    evidence: "Thorp (2006) fractional-Kelly guidance; cap structure §5 table (default 0.5)",
  },
  {
    field: "kellyMaxBankrollPct" as const,
    newValue: 0.1,
    reason: "Phase B: per-position cap as 10% of available (free-cash) bankroll — second binding cap above kellyMaxSizeUsd at current book sizes",
    evidence: "Design §5 default; keeps single-position concentration < 1/9 of the book",
  },
  {
    field: "kellyMaxSizeUsd" as const,
    newValue: 60,
    reason:
      "Phase B: hard per-position USD cap for Kelly-sized copies. Replaces the legacy $20 executor cap (BOT_LIMITS) via clamp override on the Kelly path — required for the capacity measurement (does the long-shot edge survive at $60/copy vs the historical ~$5–20?)",
    evidence: "Design §5/§7 risk note: $60 → 6–15% of the ~$400–1,100 available book; legacy path (kellyEnabled=0) unchanged at $20",
  },
  {
    field: "kellyMinBetUsd" as const,
    newValue: 2.0,
    reason: "Phase B: skip dust below $2 — sub-$2 positions are noise against spread costs",
    evidence: "Design §5 default; kelly.test.ts dust test locks behavior",
  },
  {
    field: "kellyMinEdgePct" as const,
    newValue: 0.02,
    reason: "Phase B: skip when f* < 2% — near-zero-edge positions don't clear spread/execution frictions",
    evidence: "Design §5 default; kelly.test.ts minEdgePct test locks behavior",
  },
  {
    field: "premiumOverlayEnabled" as const,
    newValue: 0,
    reason:
      "Phase B (design §4): the v38 overlay's size × clamp(1 − k·λ̂) is redundant with Kelly's λ̂-based edge — applying both would double-apply the premium signal. Code additionally skips the overlay on Kelly-sized copies; this flag disables it for the whole C-200 book",
    evidence: "Same λ̂ table drives both; kelly.ts computes the edge directly (fair q = Φ(Φ⁻¹(p) − λ̂))",
  },
];

async function main() {
  const result = await applyRuleChanges(PROPOSALS, "hermes-v49-phase-b-kelly");
  if (!result) {
    log("No changes applied.");
    return;
  }
  log(
    `RuleSet v${result.newVersion} activated: kellyEnabled=1 (fraction 0.5, maxBankrollPct 0.10, maxSizeUsd 60, minBetUsd 2, minEdgePct 0.02), premiumOverlayEnabled=0. RuleChange audit row written.`
  );
}

main()
  .catch((e) => {
    logError("apply:v49 FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
