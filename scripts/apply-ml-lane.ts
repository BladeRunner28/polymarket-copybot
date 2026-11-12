/**
 * apply:ml-lane — stand up the ML paper lane with C-200-identical capital machinery.
 *
 * User request 2026-10-20: "It also needs to start paper trading with $2,500 in capital to work
 * with. All other capital rules need to mirror c-200 to give an accurate read against our capital
 * flow architecture."
 *
 * WHAT THIS DOES (idempotent, re-runnable):
 *   1. BotBankroll row for ML_LANE: principal $2,500, cash $2,500, realized $0 (CREATE only — once
 *      the row exists, a re-run moves NOTHING but the two display-only size columns).
 *      min/max are ML_LANE's own EFFECTIVE rails, from `effectiveSizeLimits` in src/lib/safety.ts:
 *      ML_LANE has no BOT_LIMITS entry, so it falls back to STANDARD's {0.25, 20}, and it cannot
 *      take the Kelly path (`isKellyCandidate` in score-trades.ts is `botId === "BANKROLL_200"`),
 *      so `kellyMaxSizeUsd` is NOT its ceiling. The first version of this script mirrored
 *      `max(BOT_LIMITS.max, kellyMaxSizeUsd)` anyway and advertised $0.10 / $100 against an
 *      effective $0.25 / $20 from 2026-10-20 until 2026-11-12 (found 2026-10-29, kanban
 *      t_b8913619 / repaired by t_a25f8a45) — a stale display row that scripts/profit-velocity.py
 *      printed as `clip $min-$max`. The arithmetic is now imported, not re-derived.
 *   2. A `capital-ledger.json` opening entry of $2,500 tagged botId ML_LANE, so the daily-deposit
 *      series has dated provenance instead of seeding from the standing principal (which emits a
 *      warning and gives the first day's capital no provenance).
 *
 * WHAT IT DELIBERATELY DOES NOT DO
 *   - It does NOT duplicate any rule value. The ML lane reads C-200's own Kelly/exposure fields at
 *     scoring time, because two copies of a number drift apart — the BotBankroll maxPositionSize
 *     false rail was fixed for exactly that reason today. "Mirror C-200" means SHARE its fields,
 *     not copy their values.
 *   - It does not re-set principal / cashBalance / realizedPnl on an existing row: only the two
 *     display columns move. `minPositionSize`/`maxPositionSize` are read by NOTHING.
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
import { BOT_LIMITS, effectiveSizeLimits } from "../src/lib/safety";

const APPLY = process.argv.includes("--apply");
const START_CAPITAL = 2500;
const LEDGER = join(process.cwd(), "data", "capital-ledger.json");
const log = (...a: unknown[]) => console.log(...a);

async function main() {
  const rules = await prisma.ruleSet.findFirst({ where: { active: true }, orderBy: { version: "desc" } });
  const j = JSON.parse(rules?.rulesJson ?? "{}") as Record<string, unknown>;
  const kellyMaxSizeUsd = Number(j.kellyMaxSizeUsd ?? 0);

  // ML_LANE's OWN effective rails — the same function verify-botbankroll-limits.ts checks against.
  // Kelly sizing is C-200-only, so `kellyMaxSizeUsd` is deliberately NOT part of this lane's
  // ceiling: mirroring it here is what advertised $100 on a lane that clamps at $20.
  const { min: mirrorMin, max: mirrorMax } = effectiveSizeLimits(ML_BOT, kellyMaxSizeUsd);

  log(`active RuleSet v${rules?.version}: kellyMaxSizeUsd=${kellyMaxSizeUsd}`);
  log(
    `ML_LANE effective rails -> min $${mirrorMin} max $${mirrorMax} ` +
      `(${BOT_LIMITS[ML_BOT] ? "own BOT_LIMITS entry" : "no BOT_LIMITS entry -> STANDARD fallback"}, ` +
      `legacy path only; Kelly is C-200-only)\n`
  );

  const existing = await prisma.botBankroll.findUnique({ where: { botId: ML_BOT } });
  log(`BotBankroll.${ML_BOT}: ${existing ? `EXISTS (principal $${existing.principal})` : "absent"}`);

  const raw = existsSync(LEDGER) ? JSON.parse(readFileSync(LEDGER, "utf8")) : { note: "", entries: [] };
  const entries: Array<Record<string, unknown>> = Array.isArray(raw.entries) ? raw.entries : [];
  const hasOpening = entries.some((e) => e.botId === ML_BOT && e.kind === "opening");
  log(`ledger opening entry for ${ML_BOT}: ${hasOpening ? "EXISTS" : "absent"}`);

  if (!APPLY) {
    log("\nDRY RUN — would write:");
    log(existing
      ? `  update BotBankroll ${ML_BOT} -> min ${mirrorMin}, max ${mirrorMax} (principal/cash/realized untouched)`
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
    // Display columns ONLY on re-run: principal/cash/realized are seeded once at create and are
    // not this script's to re-state (a repair of the size columns must not move capital).
    update: { minPositionSize: mirrorMin, maxPositionSize: mirrorMax },
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
