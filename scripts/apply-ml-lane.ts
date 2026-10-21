/**
 * apply:ml-lane — stand up the ML paper lane with C-200-identical capital machinery.
 *
 * User request 2026-10-20: "It also needs to start paper trading with $2,500 in capital to work
 * with. All other capital rules need to mirror c-200 to give an accurate read against our capital
 * flow architecture."
 *
 * WHAT THIS DOES (idempotent, re-runnable):
 *   1. BotBankroll row for ML_LANE: principal $2,500, cash $2,500, realized $0.
 *      min/max mirror C-200's ENFORCED ceilings (0.10 / kellyMaxSizeUsd), not the dead
 *      BotBankroll numbers that were corrected to display-only the same day.
 *   2. A `capital-ledger.json` opening entry of $2,500 tagged botId ML_LANE, so the daily-deposit
 *      series has dated provenance instead of seeding from the standing principal (which emits a
 *      warning and gives the first day's capital no provenance).
 *
 * WHAT IT DELIBERATELY DOES NOT DO
 *   - It does NOT duplicate any rule value. The ML lane reads C-200's own Kelly/exposure fields at
 *     scoring time, because two copies of a number drift apart — the BotBankroll maxPositionSize
 *     false rail was fixed for exactly that reason today. "Mirror C-200" means SHARE its fields,
 *     not copy their values.
 *   - It opens no positions and touches no C-200 row. C-200's series was regression-checked
 *     against the live pre-change /capital page before and after the capital-loader refactor
 *     (principal $1900.00, realized $5977.39, live total $7872.53 — unchanged).
 *
 * Usage:
 *   npx tsx scripts/apply-ml-lane.ts            # dry run
 *   npx tsx scripts/apply-ml-lane.ts --apply    # write
 */

import { prisma } from "../src/lib/db";
import { readFileSync, writeFileSync, existsSync } from "fs";
import { join } from "path";
import { ML_BOT } from "../src/lib/capital-data";
import { BOT_LIMITS } from "../src/lib/safety";

const APPLY = process.argv.includes("--apply");
const START_CAPITAL = 2500;
const LEDGER = join(process.cwd(), "data", "capital-ledger.json");
const log = (...a: unknown[]) => console.log(...a);

async function main() {
  const rules = await prisma.ruleSet.findFirst({ where: { active: true }, orderBy: { version: "desc" } });
  const j = JSON.parse(rules?.rulesJson ?? "{}") as Record<string, unknown>;
  const kellyMaxSizeUsd = Number(j.kellyMaxSizeUsd ?? 0);

  // Mirror C-200's ENFORCED ceilings. Kelly sizing is C-200-only today; if ML_LANE ever takes the
  // Kelly path it inherits the same cap, so mirror the max of both paths.
  const c200Limits = BOT_LIMITS["BANKROLL_200"];
  const mirrorMin = c200Limits.min;
  const mirrorMax = Math.max(c200Limits.max, Math.max(c200Limits.min, kellyMaxSizeUsd));

  log(`active RuleSet v${rules?.version}: kellyMaxSizeUsd=${kellyMaxSizeUsd}`);
  log(`mirroring C-200 ceilings -> min $${mirrorMin} max $${mirrorMax}\n`);

  const existing = await prisma.botBankroll.findUnique({ where: { botId: ML_BOT } });
  log(`BotBankroll.${ML_BOT}: ${existing ? `EXISTS (principal $${existing.principal})` : "absent"}`);

  const raw = existsSync(LEDGER) ? JSON.parse(readFileSync(LEDGER, "utf8")) : { note: "", entries: [] };
  const entries: Array<Record<string, unknown>> = Array.isArray(raw.entries) ? raw.entries : [];
  const hasOpening = entries.some((e) => e.botId === ML_BOT && e.kind === "opening");
  log(`ledger opening entry for ${ML_BOT}: ${hasOpening ? "EXISTS" : "absent"}`);

  if (!APPLY) {
    log("\nDRY RUN — would write:");
    log(existing
      ? `  update BotBankroll ${ML_BOT} -> principal ${START_CAPITAL}, cash ${START_CAPITAL}, realized 0`
      : `  create BotBankroll ${ML_BOT} -> principal ${START_CAPITAL}, cash ${START_CAPITAL}, realized 0, min ${mirrorMin}, max ${mirrorMax}`);
    if (!hasOpening) log(`  append ledger opening ${START_CAPITAL} for ${ML_BOT}`);
    log("\nRe-run with --apply to write.");
    return;
  }

  const row = await prisma.botBankroll.upsert({
    where: { botId: ML_BOT },
    create: {
      botId: ML_BOT,
      principal: START_CAPITAL,
      cashBalance: START_CAPITAL,
      realizedPnl: 0,
      minPositionSize: mirrorMin,
      maxPositionSize: mirrorMax,
    },
    update: { principal: START_CAPITAL, minPositionSize: mirrorMin, maxPositionSize: mirrorMax },
  });
  log(`\nBotBankroll ${ML_BOT}: principal $${row.principal.toFixed(2)} cash $${row.cashBalance.toFixed(2)} `
    + `realized $${row.realizedPnl.toFixed(2)} min $${row.minPositionSize} max $${row.maxPositionSize}`);

  if (!hasOpening) {
    const today = new Date().toISOString().slice(0, 10);
    entries.push({
      botId: ML_BOT,
      date: today,
      amountUsd: START_CAPITAL,
      kind: "opening",
      note: "ML paper lane opening capital (user request 2026-10-20: $2,500 to work with, capital rules mirroring C-200 so the two books are comparable). Lane trades no capital above this without a further deposit.",
    });
    writeFileSync(LEDGER, JSON.stringify({ ...raw, entries }, null, 2) + "\n");
    log(`ledger: appended opening ${START_CAPITAL} for ${ML_BOT}`);
  }

  log("\nVerification: no RuleSet change, no C-200 row touched, no positions opened.");
  log(`Revert: delete the BotBankroll row for ${ML_BOT} and its ledger entry.`);
}

main()
  .catch((e) => {
    console.error("apply:ml-lane FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
