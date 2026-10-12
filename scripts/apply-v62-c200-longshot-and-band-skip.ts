/**
 * apply:v62 — C-200 daily report 2026-10-11, changes 1 + 2 (BOTH user-approved in the
 * Discord thread: "Turning recommendations approved").
 *
 *   change 1  c200LongshotBandFactor  2.5 → 3.5   (<0.20 entries, +40% on the band map)
 *   change 2  c200SkipBandRange       ""  → "0.4-0.6"  (NEW FIELD: hard-skip 0.40–0.60)
 *
 * EVIDENCE (report 2026-10-11 18:00, local-day basis, `closedAt ?? resolvedAt`):
 *   Change 1 — <0.20 is the only significantly positive band: excess +18.73pp, z=+6.38
 *   (p<0.0001, 240 legs, +$5,785.23 as recorded; all-time +$5,783.98 on $6,888.57 staked),
 *   and it carries 94% of the 14d book PnL (+$3,443.03 of +$3,671.01) on $1,752 of flow.
 *   Every other band is flat-to-negative. Capital is NOT the constraint: open exposure
 *   $3.74 against a $3,882 cap ⇒ ~$3,878 idle headroom, so this is sizing on a proven
 *   edge, not a leverage increase.
 *
 *   Change 2 — 0.40–0.60 is the largest loss bucket all-time (−7.4% ROI over 1,048 legs,
 *   −$321.10) and produced **0.1% of PnL on 51% of the last 14d's legs** while spending
 *   `maxCopiesPerCycle` (50), `maxCopiesPerWalletPerDay` (40) and `maxOpenPositions` (225)
 *   that the +EV bands need. It is NOT a sizing question any more: the dead-zone factor is
 *   already 0.125 and `clampPaperSize` floors a clip at $0.25–$1.25, so a zero factor would
 *   still book a token leg and still spend the levers. Hence a new, versioned, one-field-
 *   revertible BAND SKIP rather than another haircut.
 *
 * ARITHMETIC CAVEAT (from the same report, recorded so this is not read as "the gate
 * closes"): even with +40% long-shot size plus a full dead-zone skip the book projects to
 * ~$360/day against the $500/day Phase-1 gate, because the <0.20 band runs only ~3.4
 * legs/day. The remaining gap is long-shot FLOW, which is a funnel measurement, not a
 * threshold — carded separately.
 *
 * REVERT: change 1 → 2.5 (`c200LongshotBandFactor`), change 2 → `""`
 * (`c200SkipBandRange`). Both are plain rule fields; DEFAULT_RULES ships the pre-v62
 * behavior (2.0 / ""), so a ruleset missing the fields behaves exactly as before.
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v62-c200-longshot-and-band-skip.ts
 */

import { prisma } from "../src/lib/db";
import { applyRuleChanges } from "../src/lib/rules";
import { log, logError } from "../src/lib/redact";

const PROPOSALS = [
  {
    field: "c200LongshotBandFactor" as const,
    newValue: 3.5,
    reason:
      "v62 change 1 (user-approved 2026-10-11): deepen the only significantly positive band — <0.20 carries 94% of the 14d book PnL on 28% of its flow while ~$3,878 of exposure cap sits idle",
    evidence:
      "<0.20: excess +18.73pp, z=+6.38 (p<0.0001, 240 legs, +$5,785.23). 14d: 48 legs, $1,752.33 staked, +$3,443.03 (+196% ROI) = 94% of book PnL. Open exposure $3.74 vs cap $3,882, so the size increase is funded by headroom, not by other bands.",
  },
  {
    field: "c200SkipBandRange" as const,
    newValue: "0.4-0.6",
    reason:
      "v62 change 2 (user-approved 2026-10-11): hard-skip new C-200 copies entering 0.40–0.60 — the largest loss bucket, spending the binding per-cycle/wallet/open-position levers for 0.1% of PnL",
    evidence:
      "0.40–0.60 all-time: 1,048 legs, −$321.10, −7.4% ROI; last 14d: 172 legs (51% of all legs), $209.33 staked, +$3.81 (0.1% of PnL); calibration excess −2.42pp (z=−1.53, not significant) with an all-time ROI that is decisively negative. Dead-zone sizing is already floored at $0.25–$1.25 (clampPaperSize), so a factor of 0 would not remove the leg — this skip does, and records a legBlock so it lands in the skip histogram.",
  },
];

async function main() {
  const before = await prisma.ruleSet.findFirst({ where: { active: true }, orderBy: { version: "desc" } });
  if (before) {
    const j = JSON.parse(before.rulesJson) as Record<string, unknown>;
    log(
      `apply:v62 before — v${before.version} c200LongshotBandFactor=${j.c200LongshotBandFactor ?? "(unset→2.0)"} ` +
        `c200SkipBandRange=${j.c200SkipBandRange ?? "(unset→'')"} ` +
        `(dead zone stays ×${j.c200DeadZoneBandFactor ?? "(unset→0.25)"}; v60 band factor ${j.c200BandSizeFactor ?? 1} on "${j.c200BandSizeFactorRange ?? ""}"; c200MaxEntryPrice ${j.c200MaxEntryPrice ?? "(unset)"})`
    );
  }
  const result = await applyRuleChanges(PROPOSALS, "hermes-v62-c200-approved-20261011");
  if (!result) {
    log("No changes applied.");
    return;
  }
  const active = await prisma.ruleSet.findFirst({ where: { active: true }, orderBy: { version: "desc" } });
  const j = JSON.parse(active?.rulesJson ?? "{}") as Record<string, unknown>;
  log(
    `RuleSet v${result.newVersion} activated (C-200: long-shot ×${j.c200LongshotBandFactor}, band skip "${j.c200SkipBandRange}"). ` +
      `RuleChange audit row written. Revert = 2.5 / "".`
  );
}

main()
  .catch((e) => {
    logError("apply:v62 FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
