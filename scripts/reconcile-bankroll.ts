/**
 * reconcile:bankroll — verify BotBankroll.cashBalance against the paper-trade
 * ledger invariant:
 *
 *     expectedCash = principal + realizedPnl − Σ(open position sizes)
 *
 * (Every open trade decrements cash by its size; every close/resolve credits
 * cash by size+pnl and adds pnl to realizedPnl.) Report-only by default;
 * pass --apply to correct cashBalance. If the gap is a real capital injection
 * that was never mirrored in `principal`, add it to principal instead.
 */

import { prisma } from "../src/lib/db";
import { log, logError } from "../src/lib/redact";

async function main() {
  const apply = process.argv.includes("--apply");
  const bankrolls = await prisma.botBankroll.findMany();
  let changed = 0;

  for (const b of bankrolls) {
    if (b.botId === "STANDARD") {
      log(`[${b.botId}] infinite pool — no cash ledger to reconcile.`);
      continue;
    }
    const openAgg = await prisma.paperTrade.aggregate({
      where: { botId: b.botId, status: "open" },
      _sum: { simulatedPositionSize: true },
    });
    const deployed = openAgg._sum.simulatedPositionSize ?? 0;
    const expected = Math.round((b.principal + b.realizedPnl - deployed) * 100) / 100;
    const actual = Math.round(b.cashBalance * 100) / 100;
    const diff = Math.round((actual - expected) * 100) / 100;

    log(
      `[${b.botId}] principal=${b.principal.toFixed(2)} realized=${b.realizedPnl.toFixed(2)} ` +
        `openNotional=${deployed.toFixed(2)} => expected cash=${expected.toFixed(2)}, ` +
        `actual=${actual.toFixed(2)}, diff=${diff >= 0 ? "+" : ""}${diff.toFixed(2)}`
    );

    if (Math.abs(diff) < 0.01) {
      log(`  ✓ in balance`);
      continue;
    }
    if (apply) {
      await prisma.botBankroll.update({
        where: { botId: b.botId },
        data: { cashBalance: expected },
      });
      changed++;
      log(`  ✏️  cashBalance corrected ${actual.toFixed(2)} -> ${expected.toFixed(2)}`);
    } else {
      log(
        `  ⚠️  out of balance. Re-run with --apply to set cashBalance to the ledger value, ` +
          `or if this gap is a capital injection, add $${diff.toFixed(2)} to principal instead.`
      );
    }
  }

  log(apply ? `Reconciliation complete (${changed} corrected).` : "Report only — pass --apply to correct.");
}

main()
  .catch((e) => {
    logError("reconcile:bankroll FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
