/**
 * reprice:kalshi-92 — one-off re-price of the 92 legacy Kalshi paper rows
 * (tuning review #16 rec 1, user-approved 2026-09-05).
 *
 * Background: the pre-TR-16 Rust sidecar Kalshi adapter returned a hardcoded
 * Ok(0.52) stub (booked ~$0.50 after the 2¢ maker tweak) whenever its Kalshi
 * depth fetch failed, so every such BANKROLL_200 row was opened at a phantom
 * 0.50 REGARDLESS of the true market price. Rows whose fetch succeeded were
 * booked at the Polymarket reference price (= ObservedTrade.detectedPrice,
 * the price the whale's trade was detected at) — visible in the DB as
 * entry == detectedPrice for those rows. TR-16 (2026-09-03) killed the stub
 * for new rows; this one-off corrects the 92 legacy rows.
 *
 * Correction rule (stub row: booked entry ≈ 0.50 while the honest reference
 * differs by > 1¢):
 *   - entryPrice  := detectedPrice        (honest PM reference at entry time;
 *                                           the Kalshi-side price history is
 *                                           not recoverable — roadmap-sanctioned
 *                                           proxy, see drafts/kalshi-whale-review.md
 *                                           appendix)
 *   - shares recompute at the same risked dollars: shares = S / entryPrice
 *     (computePnl convention in src/lib/paper.ts). simulatedPositionSize S is
 *     KEPT — it is the executed risk decision. NOTE: S itself was band-sized
 *     (mapBankroll200Size) against the phantom 0.50; the parent standard-scale
 *     size is not stored per row, so S is not re-derived. PnL distortion from
 *     that is bounded by the band factor (≤ ×2) and documented in the audit.
 *   - realizedPnl (closed/resolved) := computePnl(newEntry, currentPrice, S)
 *     — exits are REAL Polymarket marks (update-pnl marks both books from the
 *     PM adapter), so exit prices are left untouched; resolved rows already
 *     settled at 1/0.
 *   - open row: unrealizedPnl recomputed the same way (currentPrice stays the
 *     live PM mark).
 *   - BotBankroll ledger: realizedPnl and cashBalance both += Σ(honest−booked)
 *     per closed/resolved row (the ledger is incremented per-close by the same
 *     amounts, so it must follow the row correction to preserve the invariant
 *     cash = principal + realized − open notional).
 *
 * Non-stub rows (entry already ≈ detectedPrice) are untouched.
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/reprice-kalshi-92.ts
 */

import { prisma } from "../src/lib/db";
import { computePnl } from "../src/lib/paper";
import { log, logError } from "../src/lib/redact";
import * as fs from "fs";
import { join } from "path";

const AUDIT_FILE = join(__dirname, "..", "data", "kalshi-reprice-audit.json");
const STUB_TOL = 0.005; // |entry − 0.5| < 0.005 → stub-priced (booked exactly 0.50)
const REF_TOL = 0.01; // honest reference must differ by > 1¢ to matter

interface RepricedRow {
  id: string;
  status: string;
  marketId: string;
  outcome: string;
  sizeUsd: number;
  bookedEntry: number;
  honestEntry: number;
  exitPrice: number;
  bookedPnl: number;
  honestPnl: number;
  delta: number;
}

async function main() {
  const trades = await prisma.paperTrade.findMany({
    where: { venue: "Kalshi", botId: "BANKROLL_200" },
    include: { decision: { include: { observedTrade: true } } },
  });
  log(`Loaded ${trades.length} Kalshi BANKROLL_200 rows.`);

  const before =
    (await prisma.paperTrade.aggregate({
      where: { botId: "BANKROLL_200", venue: "Kalshi", status: { in: ["closed", "resolved"] } },
      _sum: { realizedPnl: true },
    }))._sum.realizedPnl ?? 0;

  const audit: { ranAt: string; beforeRealized: number; rows: RepricedRow[]; skipped: string[] } = {
    ranAt: new Date().toISOString(),
    beforeRealized: before,
    rows: [],
    skipped: [],
  };

  let ledgerDelta = 0;
  let repriced = 0;

  for (const t of trades) {
    const dP = t.decision?.observedTrade?.detectedPrice;
    const isStub = Math.abs(t.entryPrice - 0.5) < STUB_TOL;
    const refDiffers = dP !== null && dP !== undefined && dP > 0 && dP < 1 && Math.abs(dP - t.entryPrice) > REF_TOL;
    if (!isStub || !refDiffers) {
      audit.skipped.push(`${t.id} (entry ${t.entryPrice}${isStub ? ", ref within tol" : ", not stub"} — untouched)`);
      continue;
    }
    const honestEntry = Math.round(dP! * 10000) / 10000;
    const exit = t.currentPrice; // real PM mark; 1/0 for resolved rows
    const honestPnl = computePnl(honestEntry, exit, t.simulatedPositionSize);
    const bookedPnl = t.realizedPnl ?? 0;
    audit.rows.push({
      id: t.id,
      status: t.status,
      marketId: t.marketId,
      outcome: t.outcome,
      sizeUsd: t.simulatedPositionSize,
      bookedEntry: t.entryPrice,
      honestEntry,
      exitPrice: exit,
      bookedPnl: t.status === "open" ? 0 : bookedPnl,
      honestPnl: t.status === "open" ? 0 : honestPnl,
      delta: t.status === "open" ? 0 : honestPnl - bookedPnl,
    });

    await prisma.paperTrade.update({
      where: { id: t.id },
      data: {
        entryPrice: honestEntry,
        ...(t.status === "open"
          ? { unrealizedPnl: computePnl(honestEntry, t.currentPrice, t.simulatedPositionSize) }
          : { realizedPnl: honestPnl }),
      },
    });
    if (t.status !== "open") {
      ledgerDelta += honestPnl - bookedPnl;
    }
    repriced++;
    log(
      `${t.status} ${t.id.slice(0, 13)}: entry ${t.entryPrice.toFixed(4)} → ${honestEntry.toFixed(4)} ` +
        `(ref ${dP!.toFixed(4)}), pnl ${bookedPnl.toFixed(2)} → ${honestPnl.toFixed(2)} (Δ ${(honestPnl - bookedPnl).toFixed(2)})`
    );
  }

  // Ledger follows the row correction (same per-close increments it applied).
  if (Math.abs(ledgerDelta) > 0.001) {
    await prisma.botBankroll.update({
      where: { botId: "BANKROLL_200" },
      data: { realizedPnl: { increment: ledgerDelta }, cashBalance: { increment: ledgerDelta } },
    });
  }

  const after =
    (await prisma.paperTrade.aggregate({
      where: { botId: "BANKROLL_200", venue: "Kalshi", status: { in: ["closed", "resolved"] } },
      _sum: { realizedPnl: true },
    }))._sum.realizedPnl ?? 0;

  fs.writeFileSync(AUDIT_FILE, JSON.stringify(audit, null, 2));

  const bankroll = await prisma.botBankroll.findUniqueOrThrow({ where: { botId: "BANKROLL_200" } });
  log(
    `\nRe-priced ${repriced} stub rows (${trades.length - repriced} untouched). ` +
      `kalshiRealized ${before.toFixed(2)} → ${after.toFixed(2)} (Δ ${(after - before).toFixed(2)}). ` +
      `Ledger: realized ${(bankroll.realizedPnl ?? 0).toFixed(2)}, cash ${bankroll.cashBalance.toFixed(2)} ` +
      `(adjusted by ${ledgerDelta.toFixed(2)}). Audit: ${AUDIT_FILE}`
  );
  if (after < -50) {
    throw new Error(`kalshiRealized ${after.toFixed(2)} still below the −$50 breaker floor — check the re-price.`);
  }
}

main()
  .catch((e) => {
    logError("reprice:kalshi-92 FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
