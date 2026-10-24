/**
 * apply:v67 — floor the C-200 long-shot band multiplier at 0.05.
 * (profit-recs #1, user-approved 2026-10-24: "Longshot floor")
 *
 * WHAT THIS CHANGES
 *   c200LongshotBandFloor   0 -> 0.05
 *
 * Nothing else. c200LongshotBandFactor stays at 3.5, the dead zone stays at 0.25, and
 * the 0.05-0.20 cell keeps its full multiplier.
 *
 * WHY
 * mapBankroll200Size applied the long-shot multiplier to `entryPrice < 0.20` with no lower
 * bound, and applyKellyBandRails then did Math.max below 0.20, so Kelly could not shrink a
 * long-shot back down either — the code was written to protect the boost. The ruleset's
 * LARGEST factor therefore landed hardest at the smallest prices: the book put its biggest
 * clip on its longest odds.
 *
 * MEASURED (profit-recs 2026-10-24, truths re-priced at archived CLOB resolution, 91.4%
 * coverage, validated against realizedPnl to $0.005 on 3,177 resolved legs)
 *   below 0.05 : 66 legs / 33 markets / $1,694 notional, clip $25.66 (LARGEST in the book),
 *                avgP 0.034, settlement hit 0.0% vs a 3.39% break-even, -$1,041 (-61%)
 *                C-200 alone: $47.62 average clip, $100 max
 *   0.05-0.20  : +98% to +102% on truth; 0.15-0.20 survives every tail cut
 *                (+49.9% ex-top-10, +30.5% ex-3-markets) at a SMALLER clip ($13.69)
 * Decision-rule conditions, all met: >=50 settled legs, hit below the break-even price,
 * clip >=1.5x the 0.05-0.20 cell.
 *
 * SCOPE CORRECTION, recorded because the proposal said "both lanes" and that is wrong:
 * mapBankroll200Size is reached only under `botId === "BANKROLL_200"` in openPaperTrade, so
 * STANDARD's sub-0.05 legs NEVER received the 3.5x — they are sized by the standard path.
 * There is nothing for this floor to do on STANDARD. If the intent is also to stop STANDARD
 * entering below 0.05, that is a different rule (an admission floor), was not measured, and
 * is NOT implemented here.
 *
 * PRE-REGISTERED REFUTATION (carried)
 *   (a) blocked sub-0.05 candidates win >=3 of 60 forward (>=5%, above break-even), or
 *   (b) 0.05-0.20's truth ROI goes <0% on a 60-day read.
 *   Either => revert to 0.
 *
 * Run dry:  DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v67.ts
 * Apply:    DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v67.ts --apply
 */

import { prisma } from "../src/lib/db";
import { getActiveRules, applyRuleChanges } from "../src/lib/rules";
import { log } from "../src/lib/redact";

const REASON =
  "The C-200 long-shot multiplier had no lower bound (entryPrice < 0.20, nothing underneath) and applyKellyBandRails Math.max-ed Kelly back up to it, so the ruleset's largest factor (3.5x) landed hardest at the smallest prices. Below 0.05: 66 legs / $1,694 at a $25.66 clip (largest in the book), settlement hit 0.0% vs a 3.39% break-even, -$1,041 realized. The 0.05-0.20 cell earns +98%..+102% and is untouched";
const EVIDENCE =
  "profit-recs 2026-10-24, 12,199 finished legs re-priced at archived CLOB resolution (91.4% coverage; truth PnL == realizedPnl to $0.005 on 3,177 resolved legs). below 0.05: 66 legs / 33 markets / $1,694 / clip $25.66 / avgP 0.034 / hit 0.0% vs 3.39% break-even / -$1,041 (-61%); C-200 alone $47.62 avg, $100 max. 0.05-0.20 +98%..+102%; 0.15-0.20 ex-top-10 +49.9%. Conditions met: >=50 settled legs, hit below break-even, clip >=1.5x the 0.05-0.20 cell. Refutation: blocked sub-0.05 candidates win >=3 of 60 forward, or 0.05-0.20 truth ROI <0% on a 60d read";

async function populations(floor: number) {
  const [open, settled] = await Promise.all([
    prisma.paperTrade.findMany({
      where: { isDemo: false, botId: "BANKROLL_200", status: "open", entryPrice: { lt: floor } },
      select: { entryPrice: true, simulatedPositionSize: true },
    }),
    prisma.paperTrade.findMany({
      where: {
        isDemo: false,
        botId: "BANKROLL_200",
        status: { in: ["closed", "resolved"] },
        entryPrice: { lt: floor },
      },
      select: { entryPrice: true, simulatedPositionSize: true, realizedPnl: true },
    }),
  ]);
  const sum = (xs: { simulatedPositionSize: number }[]) =>
    xs.reduce((s, r) => s + r.simulatedPositionSize, 0);
  return {
    openLegs: open.length,
    openNotional: sum(open),
    openMaxClip: open.length ? Math.max(...open.map((r) => r.simulatedPositionSize)) : 0,
    settledLegs: settled.length,
    settledNotional: sum(settled),
    settledPnl: settled.reduce((s, r) => s + (r.realizedPnl ?? 0), 0),
  };
}

async function main() {
  const apply = process.argv.includes("--apply");
  const beforeQ = await getActiveRules();
  const before = beforeQ.rules;
  const floor = before.c200LongshotBandFloor ?? 0;
  log(
    `active rules v${beforeQ.version}: c200LongshotBandFloor=${floor} ` +
      `c200LongshotBandFactor=${before.c200LongshotBandFactor}`
  );
  if (floor === 0.05) {
    log("already 0.05 — nothing to do.");
    return;
  }

  const p = await populations(0.05);
  log("");
  log("PLANNED CHANGE (single field):");
  log("  c200LongshotBandFloor  0 -> 0.05");
  log("  effect: entries below 0.05 stop receiving the 3.5x long-shot multiplier");
  log("          (they fall through to x1.0, the same size as a 0.20-0.40 entry)");
  log("  untouched: c200LongshotBandFactor 3.5, dead zone 0.25, the whole 0.05-0.20 cell");
  log("");
  log("POPULATION ALREADY BELOW 0.05 (C-200 only — the factor is not reachable on STANDARD):");
  log(`  open    : ${p.openLegs} leg(s), $${p.openNotional.toFixed(2)} notional, max clip $${p.openMaxClip.toFixed(2)}`);
  log(
    `  settled : ${p.settledLegs} leg(s), $${p.settledNotional.toFixed(2)} notional, ` +
      `realized $${p.settledPnl.toFixed(2)}`
  );
  log("");
  log("NOTE: this does NOT close or resize anything already open. It changes FUTURE sizing");
  log("only, so there is no stock clearing and no PnL is booked by activating it.");
  log("");
  log("  revert: c200LongshotBandFloor -> 0");
  log("");

  if (!apply) {
    log("DRY RUN — nothing written. Re-run with --apply to activate.");
    return;
  }

  const result = await applyRuleChanges(
    [{ field: "c200LongshotBandFloor", newValue: 0.05, reason: REASON, evidence: EVIDENCE }],
    "hermes-v67-longshot-floor"
  );
  if (!result) {
    log("no changes applied (empty proposal list).");
    return;
  }
  log(`RuleSet v${result.newVersion} activated; c200LongshotBandFloor=0.05. Audit row written.`);
}

main()
  .catch((e) => {
    log(`FAILED: ${e instanceof Error ? e.message : e}`);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
