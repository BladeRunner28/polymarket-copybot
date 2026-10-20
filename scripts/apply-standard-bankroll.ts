/**
 * apply:standard-bankroll — populate STANDARD's BotBankroll row from MEASURED CONTRIBUTION.
 *
 * User-approved 2026-10-20 ("Measured contribution"). Lane A, because principal sets the
 * denominator every ratio rail divides by.
 *
 * WHY THIS ROW MATTERS AT ALL
 * `BotBankroll.principal` for STANDARD has been 0.00 since inception. `effectiveExposureCap()`
 * returns the bare base whenever `principal <= 0` ("can't verify recovery against an unknown
 * baseline"), so for the lane carrying 87% of the book's notional there was no accounting
 * identity: the exposure cap, any notional-per-cash limit, and any return-on-capital figure
 * were all UNDEFINED. Measured contribution is the most conservative of the three candidate
 * bases and the only one derived entirely from realised numbers rather than a judgement call.
 *
 * WHAT "MEASURED CONTRIBUTION" MEANS HERE, precisely:
 *   principal     = realised PnL + unrealised PnL   (what the lane has actually contributed)
 *   realizedPnl   = realised PnL                    (closed + resolved)
 *   cashBalance   = principal + realizedPnl - open notional
 *
 * The cash formula is the project's OWN invariant, verified against the C-200 row before use:
 *   1,900.00 + 5,944.60 - 80.90 = 7,763.70  ==  BotBankroll.cashBalance for BANKROLL_200  (exact)
 *
 * WHAT THIS DOES NOT DO — stated plainly because it is the whole point:
 *   - It changes NO decision. `score-trades.ts:104` fetches `botId: "BANKROLL_200"`
 *     hardcoded, so STANDARD's row is never read by the drawdown or exposure machinery.
 *     This is bookkeeping that makes a future rail expressible, not a behaviour change.
 *   - It does NOT apply the exposure cap. Porting the cap was measured and REFUSED
 *     (drafts/exposure-cap-porting-20261020.md): with principal at 0 it would have given
 *     STANDARD a $250 ceiling against $13,566 of open notional — a 54x halt, as a portfolio
 *     gate that would have frozen C-200 too.
 *   - It does NOT make the lane cap-compliant. The derived cap under the C-200 formula is
 *     printed below so nobody mistakes a populated denominator for headroom.
 *
 * Usage:
 *   npx tsx scripts/apply-standard-bankroll.ts            # dry run (default)
 *   npx tsx scripts/apply-standard-bankroll.ts --apply    # write
 */

import { prisma } from "../src/lib/db";
import { effectiveExposureCap } from "../src/lib/exposure-cap";

const log = (...a: unknown[]) => console.log(...a);

const APPLY = process.argv.includes("--apply");

async function measure() {
  const realized = await prisma.paperTrade.aggregate({
    where: { botId: "STANDARD", isDemo: false, status: { in: ["closed", "resolved"] } },
    _sum: { realizedPnl: true },
    _count: true,
  });
  const open = await prisma.paperTrade.aggregate({
    where: { botId: "STANDARD", isDemo: false, status: "open" },
    _sum: { simulatedPositionSize: true, unrealizedPnl: true },
    _count: true,
  });
  const realizedPnl = realized._sum.realizedPnl ?? 0;
  const unrealizedPnl = open._sum.unrealizedPnl ?? 0;
  const openNotional = open._sum.simulatedPositionSize ?? 0;

  const principal = realizedPnl + unrealizedPnl;
  const cashBalance = principal + realizedPnl - openNotional;

  return {
    realizedPnl,
    unrealizedPnl,
    openNotional,
    principal,
    cashBalance,
    finishedLegs: realized._count,
    openLegs: open._count,
  };
}

async function main() {
  const before = await prisma.botBankroll.findUnique({ where: { botId: "STANDARD" } });
  if (!before) {
    log("No STANDARD BotBankroll row exists — seed it first rather than inventing one here.");
    process.exit(1);
  }
  const m = await measure();

  log("=== measured contribution, STANDARD ===");
  log(`  finished legs (closed+resolved) : ${m.finishedLegs.toLocaleString()}`);
  log(`  realised PnL                    : $${m.realizedPnl.toFixed(2)}`);
  log(`  open legs                       : ${m.openLegs.toLocaleString()}`);
  log(`  open notional                   : $${m.openNotional.toFixed(2)}`);
  log(`  unrealised PnL                  : $${m.unrealizedPnl.toFixed(2)}`);
  log("");
  log("=== values to write ===");
  log(`  principal    ${before.principal.toFixed(2).padStart(12)}  ->  ${m.principal.toFixed(2).padStart(12)}`);
  log(`  cashBalance  ${before.cashBalance.toFixed(2).padStart(12)}  ->  ${m.cashBalance.toFixed(2).padStart(12)}`);
  log(`  realizedPnl  ${before.realizedPnl.toFixed(2).padStart(12)}  ->  ${m.realizedPnl.toFixed(2).padStart(12)}`);
  log("");

  // Coherence check: what a cap built on THIS denominator would be. Not applied — printed so the
  // row is not mistaken for headroom.
  const rules = await prisma.ruleSet.findFirst({ where: { active: true }, orderBy: { version: "desc" } });
  const base = Number(JSON.parse(rules?.rulesJson ?? "{}").maxGrossExposureUsd ?? 0);
  const nwMtm = m.principal + m.realizedPnl + m.unrealizedPnl;
  const derivedCap = effectiveExposureCap(base, nwMtm, m.principal);
  log("=== what a cap on this denominator would be (NOT applied) ===");
  log(`  base (maxGrossExposureUsd)      : $${base.toFixed(0)}`);
  log(`  net worth (mtm)                 : $${nwMtm.toFixed(2)}`);
  log(`  derived cap                     : $${derivedCap.toFixed(2)}`);
  log(`  open notional / derived cap     : ${(m.openNotional / derivedCap).toFixed(1)}x`);
  log(
    m.openNotional > derivedCap
      ? "  => the lane is STILL over a cap built on its own contribution. Populating this row does NOT\n     make STANDARD cap-compliant, and the cap is deliberately not applied."
      : "  => the lane would sit under this cap."
  );
  log("");

  if (!APPLY) {
    log("DRY RUN — nothing written. Re-run with --apply to write.");
    return;
  }

  await prisma.botBankroll.update({
    where: { botId: "STANDARD" },
    data: {
      principal: m.principal,
      cashBalance: m.cashBalance,
      realizedPnl: m.realizedPnl,
    },
  });
  const after = await prisma.botBankroll.findUnique({ where: { botId: "STANDARD" } });
  log("=== written ===");
  log(`  principal ${after?.principal.toFixed(2)} | cash ${after?.cashBalance.toFixed(2)} | realized ${after?.realizedPnl.toFixed(2)}`);
  log("");
  log("  Verification: no RuleSet field changed; no decision path reads this row.");
  log("  Revert (restores the never-populated state):");
  log("    npx tsx -e 'import{prisma}from\"./src/lib/db\";prisma.botBankroll.update({where:{botId:\"STANDARD\"},data:{principal:0,cashBalance:0,realizedPnl:0}})'");
}

main()
  .catch((e) => {
    console.error("apply:standard-bankroll FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
