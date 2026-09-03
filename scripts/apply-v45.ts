/**
 * apply:v45 — activation of RuleSet v45 with the execution-leak Step 2 fixes
 * (2026-09-03, user-approved: "proceed with the fix").
 *
 * v45 adds four mechanisms (all flag-revertible via a rule change):
 *   1. c200Blacklist / standardBlacklist — per-bot market-category blacklists
 *      for the structural −EV slug set. Verified per-bot PnL 2026-09-03:
 *      C-200 −$801 recoverable (423 trades in these slugs), STANDARD −$4.4k+
 *      (cs2/lol alone −$3,945). Per-bot because dota2/elon are C-200-POSITIVE
 *      (+$87/+$30) while STANDARD-negative (−$212/−$635) — a shared list would
 *      have destroyed C-200's best categories. Question-fragment slugs
 *      (what/of/the/where/which) deliberately NOT blacklisted — each wraps
 *      100s of real markets (Bitcoin, elections, movies) and blacklisting them
 *      would kill legitimate signals for <$20 of noise.
 *   2. maxMarketSlugPositions — per-raw-slug open-position cap for C-200
 *      (closes the v41 hole where esports maps to uncapped research-category
 *      "Other"). 15 = cap.
 *   3. whaleSizeUsd 500 / whaleCategoryFitCap 60 — caps the category-fit score
 *      component for whale-size wallet trades (liquidity, not edge).
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v45.ts
 */

import { prisma } from "../src/lib/db";
import { applyRuleChanges } from "../src/lib/rules";
import { log, logError } from "../src/lib/redact";

const PROPOSALS = [
  {
    field: "c200Blacklist" as const,
    newValue: [
      "cs2", "lol", "nfl", "val", "swe2", "clacton", "bitcoin",
      "sea", "itf", "mls", "clf", "nevada",
    ],
    reason:
      "C-200 market-category blacklist (execution-leak Step 2, approved): structural −EV slug set — every category where C-200's own realized PnL is deeply negative and STANDARD loses too (or is flat), regardless of venue",
    evidence:
      "C-200 realized in these slugs: cs2 −$183, lol −$312, nfl −$70, val −$64, swe2 −$38, clacton −$24, bitcoin −$16, sea −$22, itf −$15, mls −$10, clf −$33, nevada −$14 = −$801 recoverable (2026-09-03, resolved trades). STANDARD loses in cs2/lol too (−$2,255/−$1,690). 80–89 band in lol/cs2 is the worst cell in the system (−$3.81/t). Fragments what/of/the/where/which excluded (wrap real markets).",
  },
  {
    field: "standardBlacklist" as const,
    newValue: [
      "cs2", "lol", "nfl", "swe2", "bitcoin", "clacton", "itf", "mls",
      "sea", "elon", "mex", "dota2", "crichundred",
    ],
    reason:
      "STANDARD market-category blacklist (execution-leak Step 2, approved): slugs where STANDARD's own realized PnL is deeply negative (shared −EV set + STANDARD-only bleeders elon/mex/dota2/crichundred). dota2/elon are C-200-positive so they stay C-200-eligible",
    evidence:
      "STANDARD realized: cs2 −$2,255, lol −$1,690, elon −$635, mex −$246, dota2 −$212, nfl −$115, crichundred −$103, swe2 −$68, bitcoin −$77, clacton −$63, itf −$60, mls −$64, sea −$37 = −$5.6k recoverable (2026-09-03, resolved trades). C-200 dota2 +$87 / elon +$30 → excluded from C-200 list.",
  },
  {
    field: "maxMarketSlugPositions" as const,
    newValue: 15,
    reason:
      "Per-raw-market-slug open cap for C-200 — the v41 research-category gate maps esports to uncapped 'Other', letting lol/cs2 concentrate without a gate",
    evidence:
      "v41 maxCategoryPositions (40) applies to research categories only; researchCategoryFor returns undefined for lol/cs2/val → uncapped. Raw-slug cap of 15 limits per-slug concentration (verified 2026-09-03).",
  },
  {
    field: "whaleSizeUsd" as const,
    newValue: 500,
    reason:
      "Whale-liquidity guard ON — wallets trading >$500 in their home category are often the liquidity, not the edge; cap their category-fit score component",
    evidence:
      "C-200 regular-funnel copies follow large wallets (avg $608 trade) and lose −$0.26/t; +EV lane follows small wallets ($40) at −$0.03/t. Category-fit (0.15 weight) inflates whale scores to 78–82 (2026-09-03).",
  },
  {
    field: "whaleCategoryFitCap" as const,
    newValue: 60,
    reason: "Cap for the category-fit component under the whale guard",
    evidence: "60 keeps a genuine whale's other components (wallet quality 0.3, timing 0.2, liquidity 0.15) dominant while removing category-fit inflation.",
  },
];

async function main() {
  const result = await applyRuleChanges(PROPOSALS, "hermes-v45-execution-leak-step2");
  if (!result) {
    log("No changes applied.");
    return;
  }
  log(
    `RuleSet v${result.newVersion} activated: c200Blacklist(${(PROPOSALS[0].newValue as string[]).length} slugs), ` +
      `standardBlacklist(${(PROPOSALS[1].newValue as string[]).length} slugs), ` +
      `maxMarketSlugPositions=${PROPOSALS[2].newValue}, whaleSizeUsd=${PROPOSALS[3].newValue}. ` +
      `RuleChange audit row written.`
  );
}

main()
  .catch((e) => {
    logError("apply:v45 FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
