/**
 * apply:v64 — STANDARD open-position cap (user-approved 2026-10-20: "both approved").
 *
 *   standardMaxOpenPositions   0  →  1300   (NEW FIELD: the open-position ceiling STANDARD never had)
 *
 * WHAT WAS APPROVED vs WHAT IS IMPLEMENTED, stated plainly because they differ.
 *
 * The approved item was "extend the per-slug concentration cap to STANDARD". Measured before
 * writing code, that instrument is wrong for this lane:
 *   - the cap keys on the raw `marketCategory` slug token, and the top tokens in STANDARD's open
 *     book are QUESTION WORDS — `how` 188, `ballon` 133, `brazil` 113, `next` 64, `what` 60,
 *     `which` 47 — so it would cap artefact strings, not leagues;
 *   - keyed on the real fine class instead, a cap of 15 or 30 would have blocked **~55% of the
 *     last 30 days of new flow**, because classes are already at/over any such cap;
 *   - and 39.5% of that new flow lands in the `other` catch-all bucket, so most of the throttling
 *     would fall on markets the classifier cannot even name. That is a lane brake, not a
 *     concentration rail.
 *
 * Meanwhile the quantity that IS out of control had no rail at all: STANDARD holds **1,263 open
 * positions** against `maxOpenPositions = 225`, which `score-trades.ts:723` guards with
 * `botId === "BANKROLL_200"`. This is the fifth confirmed instance of that scoping pattern, after
 * the v62 band skip, the stale-exit block, the per-slug cap and the per-market ceiling.
 *
 * THE NUMBERS (measured 2026-10-20):
 *   open STANDARD positions          1,263   (cap that governs it: 225, C-200 only → 5.6x over)
 *   new STANDARD legs, trailing 30d    147   = 4.90/day → ~150 legs/month, no ceiling
 *   notional at risk                $13,623 against $7,900 cash (~1.7x gross)
 *   lane ROI, all time                +3.09%   (canonical accounting, src/lib/accounting.ts)
 *   median time-to-resolution of the open book   115.3 days
 *
 * WHY 1300 AND NOT 225: the C-200 value would be a HALT, not a brake. With a 115-day median TTR
 * the book decays too slowly to fall from 1,263 to 225 in any reasonable period, so STANDARD would
 * simply stop trading. 1,300 permits ~37 more legs and then freezes the book at today's size. The
 * intent is unambiguous: **STANDARD does not grow until this book proves itself**, and the phase
 * gate is currently unreachable by configuration anyway.
 *
 * WHAT THIS IS NOT: it is not a liquidation, it touches no existing position, and it does not
 * change sizing. It is a ceiling on new entries only.
 *
 * NEXT RAIL, not included here: the exposure cap (base $1,000, v50, +50% × max(0, netWorth −
 * principal)) is also C-200-scoped, and notional-per-dollar-of-cash is the more meaningful
 * constraint than leg count. Recorded for a separate proposal.
 *
 * REVERT: set standardMaxOpenPositions back to 0 — one field; DEFAULT_RULES ships 0, so a ruleset
 * lacking the field behaves exactly as pre-v64.
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v64-standard-open-cap.ts
 */

import { prisma } from "../src/lib/db";
import { applyRuleChanges } from "../src/lib/rules";
import { log, logError } from "../src/lib/redact";

const PROPOSALS = [
  {
    field: "standardMaxOpenPositions" as const,
    newValue: 1300,
    reason:
      "v64 (user-approved 2026-10-20): give STANDARD the open-position ceiling it never had — it held 1,263 open legs against a 225 cap scoped to C-200 only (5.6x over), growing ~150 legs/month with no rail",
    evidence:
      "Measured 2026-10-20: open STANDARD 1,263 legs; maxOpenPositions=225 enforced only for BANKROLL_200 (score-trades.ts:723 — 5th confirmed botId scoping gap after v62 band skip, stale-exit block, per-slug cap, per-market ceiling); new legs 147/30d = 4.90/day; notional $13,623 vs $7,900 cash (~1.7x gross); lane ROI +3.09% all-time; open-book median TTR 115.3d. The approved per-slug cap was measured and REJECTED as the instrument: it keys on raw slug tokens whose top entries are question words (how 188, ballon 133, brazil 113, next 64, what 60, which 47), and keyed on fine class a cap of 15-30 would have blocked ~55% of 30d flow with 39.5% of that flow in the 'other' catch-all. 1300 = freeze-at-current-size; the C-200 value of 225 would be a halt rather than a brake given the 115-day TTR.",
  },
];

async function main() {
  const before = await prisma.ruleSet.findFirst({ where: { active: true }, orderBy: { version: "desc" } });
  if (before) {
    const j = JSON.parse(before.rulesJson) as Record<string, unknown>;
    const openNow = await prisma.paperTrade.count({ where: { botId: "STANDARD", status: "open" } });
    log(
      `apply:v64 before — v${before.version} standardMaxOpenPositions=${j.standardMaxOpenPositions ?? "(unset→0, disabled)"} ` +
        `| STANDARD open now: ${openNow.toLocaleString()} | C-200 maxOpenPositions=${j.maxOpenPositions ?? "?"} (unchanged)`
    );
    if (openNow >= 1300) {
      log(`NOTE: STANDARD is ALREADY at/over 1300 (${openNow.toLocaleString()}) — the rail will block new entries immediately.`);
    } else {
      log(`Headroom before the rail binds: ${(1300 - openNow).toLocaleString()} legs (~${((1300 - openNow) / 4.9).toFixed(0)} days at 4.90 legs/day).`);
    }
  }
  const result = await applyRuleChanges(PROPOSALS, "hermes-v64-standard-open-cap-approved-20261020");
  if (!result) {
    log("No changes applied.");
    return;
  }
  const active = await prisma.ruleSet.findFirst({ where: { active: true }, orderBy: { version: "desc" } });
  const j = JSON.parse(active?.rulesJson ?? "{}") as Record<string, unknown>;
  log(
    `RuleSet v${result.newVersion} activated (standardMaxOpenPositions=${j.standardMaxOpenPositions}). ` +
      `RuleChange audit row written. Revert = 0. C-200 rails untouched.`
  );
}

main()
  .catch((e) => {
    logError("apply:v64 FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
