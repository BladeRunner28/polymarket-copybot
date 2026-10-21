/**
 * verify:botbankroll-limits — do BotBankroll's min/max match the ceilings that actually bind?
 *
 * WHY THIS EXISTS
 * `BotBankroll.minPositionSize` / `maxPositionSize` are read by NOTHING. The enforced ceilings are:
 *
 *   legacy path   clampPaperSize(usd, botId)          -> BOT_LIMITS in src/lib/safety.ts
 *   Kelly path    clampPaperSize(usd, botId, maxUsd)  -> hi = max(limits.min, rules.kellyMaxSizeUsd)
 *
 * so the Kelly path can raise C-200's ceiling from BOT_LIMITS' $20 to `kellyMaxSizeUsd` ($100).
 * The table said $30.
 *
 * That stale number was then read as a rail — twice on 2026-10-20, in a report that described
 * "STANDARD max $20 / C-200 max $30" as the sizing stack while the book had already booked **69
 * C-200 clips above $30** (max $100, one that same day). A field nobody enforces, sitting next to
 * fields that are enforced, is a trap: it reads as authority and is not.
 *
 * This script makes the drift loud instead of silent. It exits non-zero when the table stops
 * matching the code, so the next reader gets a failure rather than a false rail.
 *
 * Usage: npx tsx scripts/verify-botbankroll-limits.ts
 */

import { prisma } from "../src/lib/db";
import { BOT_LIMITS } from "../src/lib/safety";

/** The HIGHEST ceiling any sizing path permits, per bot. This is what maxPositionSize mirrors. */
function effectiveMax(botId: string, kellyMaxSizeUsd: number): number {
  const limits = BOT_LIMITS[botId] ?? BOT_LIMITS.STANDARD;
  // Kelly sizing is C-200 ONLY -- `isKellyCandidate` in score-trades.ts is
  // `botId === "BANKROLL_200" && lane !== "short_ttr" && kellyEnabled === 1`, and STANDARD
  // "keeps legacy sizing". An earlier draft of this verifier applied the Kelly ceiling to
  // BOTH bots and wrongly flagged STANDARD's correct $20 as drift.
  if (botId !== "BANKROLL_200") return limits.max;
  // Kelly path: hi = max(limits.min, maxUsd). Legacy fallback: limits.max. Mirror the larger.
  return Math.max(limits.max, Math.max(limits.min, kellyMaxSizeUsd));
}

function effectiveMin(botId: string): number {
  return (BOT_LIMITS[botId] ?? BOT_LIMITS.STANDARD).min;
}

async function main() {
  const rules = await prisma.ruleSet.findFirst({ where: { active: true }, orderBy: { version: "desc" } });
  const j = JSON.parse(rules?.rulesJson ?? "{}") as Record<string, unknown>;
  const kellyMaxSizeUsd = Number(j.kellyMaxSizeUsd ?? 0);
  console.log(`active RuleSet v${rules?.version} kellyMaxSizeUsd=${kellyMaxSizeUsd}`);
  console.log(`BOT_LIMITS: ${JSON.stringify(BOT_LIMITS)}\n`);

  const rows = await prisma.botBankroll.findMany({ orderBy: { botId: "asc" } });
  if (rows.length === 0) {
    console.error("FAIL: no BotBankroll rows");
    process.exit(1);
  }

  let bad = 0;
  console.log("bot            field   table      effective   verdict");
  for (const r of rows) {
    const expMin = effectiveMin(r.botId);
    const expMax = effectiveMax(r.botId, kellyMaxSizeUsd);
    for (const [field, actual, expected] of [
      ["min", r.minPositionSize, expMin],
      ["max", r.maxPositionSize, expMax],
    ] as const) {
      const ok = Math.abs(actual - expected) < 1e-9;
      if (!ok) bad++;
      console.log(
        `${r.botId.padEnd(14)} ${field.padEnd(6)} ${String(actual).padStart(9)} ${String(expected).padStart(11)}   ${ok ? "ok" : "DRIFT"}`
      );
    }
  }

  if (bad > 0) {
    console.error(
      `\nFAIL: ${bad} value(s) drift from the enforced ceilings. These columns are DISPLAY-ONLY —\n` +
        `nothing reads them — so a stale number here is not a safety issue, it is a MISREADING hazard:\n` +
        `it reads like a rail and is not one. Fix the row to the effective values, or delete the columns.`
    );
    process.exit(1);
  }
  console.log(
    `\nPASS: the table matches the enforced ceilings. Reminder: these columns remain DISPLAY-ONLY —\n` +
      `enforcement is BOT_LIMITS (legacy) and rules.kellyMaxSizeUsd (Kelly), both in code, not in this table.`
  );
}

main()
  .catch((e) => {
    console.error("verify:botbankroll-limits FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
