/**
 * c200:link-missing — repair the FillIntent links the dispatch/webhook RACE dropped.
 *
 * WHY THIS EXISTS
 *   `scripts/c200-fill-resolve.ts` can only stamp a leg it can reach through
 *   `FillIntent.paperTradeId`. The intent row is written by the SCORING process
 *   (`scripts/score-trades.ts`, right after the sidecar accepts the dispatch) and the leg by
 *   the DASHBOARD's execution-result webhook, on the same SQLite file — so the webhook's link
 *   lookup sometimes runs before the intent insert is visible, finds nothing, returns null,
 *   and nothing retries.
 *
 *   Measured 2026-11-12: 219 of 802 instrument-era C-200 intents unlinked (27.3%), and every
 *   one of them has exactly ONE leg on the exact (decisionJournalId, marketId, outcome, side)
 *   the linker matches — 1:1, zero ambiguity, zero duplicate key tuples. So the population is
 *   repairable; the legs are not garbage, they are unreachable.
 *
 *   `src/lib/fill-intent.ts` now retries the lookup for FUTURE legs. This script is the
 *   historical half, and it is DRY-RUN BY DEFAULT because linking is not a cosmetic repair:
 *   the resolver's next run will then stamp those legs filled/unfilled, `bookedPnl()` forces
 *   $0 on a proven-unfilled leg, and booked PnL -> netWorth -> the equity-linked exposure cap
 *   and the drawdown gate all move. That is LANE A: read the dry run, then decide.
 *
 * SAFETY
 *   - Dry run by default; `--apply` is required to write.
 *   - Writes ONLY `PaperTrade.intentPrice` (nullable shadow column) and
 *     `FillIntent.paperTradeId` / `linkedAt`. No price, size, status, PnL or bankroll row.
 *   - Refuses any key tuple with more than one candidate on either side (ambiguity is a
 *     different bug; guessing would invent a measurement).
 *   - Idempotent: a linked pair is no longer a candidate, so re-runs are no-ops.
 *
 * Run dry:  DATABASE_URL="file:./dev.db" npx tsx scripts/c200-link-missing.ts
 * Apply:    DATABASE_URL="file:./dev.db" npx tsx scripts/c200-link-missing.ts --apply
 */
import { prisma } from "../src/lib/db";
import { log } from "../src/lib/redact";

const LANE = "BANKROLL_200";

interface Pair {
  legId: string;
  legPnl: number;
  legSize: number;
  legSettled: boolean;
  intentId: string;
  intentPrice: number;
  entryPrice: number;
  marketId: string;
}

async function main() {
  const apply = process.argv.includes("--apply");

  const intents = await prisma.fillIntent.findMany({
    where: { botId: LANE },
    select: {
      id: true,
      decisionJournalId: true,
      marketId: true,
      outcome: true,
      side: true,
      intentPrice: true,
      paperTradeId: true,
    },
  });
  const linkedTradeIds = new Set<string>();
  for (const i of intents) if (i.paperTradeId) linkedTradeIds.add(i.paperTradeId);

  const legs = await prisma.paperTrade.findMany({
    where: { botId: LANE, isDemo: false },
    select: {
      id: true,
      decisionJournalId: true,
      marketId: true,
      outcome: true,
      side: true,
      entryPrice: true,
      realizedPnl: true,
      simulatedPositionSize: true,
      status: true,
    },
  });

  const k = (r: { decisionJournalId: string; marketId: string; outcome: string; side: string }) =>
    `${r.decisionJournalId}\u0001${r.marketId}\u0001${r.outcome}\u0001${r.side}`;

  const legsByKey = new Map<string, typeof legs>();
  for (const l of legs) {
    const key = k(l);
    const arr = legsByKey.get(key) ?? [];
    arr.push(l);
    legsByKey.set(key, arr);
  }

  const pairs: Pair[] = [];
  const ambiguous: string[] = [];
  const noLeg: string[] = [];
  const inverted: Pair[] = [];
  const seenKeys = new Set<string>();

  // The intent price is the LEVEL the resolver tests, and on ~5% of instrument-era legs it is
  // recorded on the COMPLEMENT's frame (entry = 1 - intent; named-outcome markets — team,
  // player, UNDER labels). Linking one of those would hand the resolver a level a dollar away
  // from the booked one, so they are refused here and priced separately: restamping them is a
  // measurement change (Lane A), not a link repair.
  const isInverted = (entry: number, intent: number) =>
    Math.abs(entry - (1 - intent)) <= 0.012 && Math.abs(entry - intent) >= 0.05;

  for (const i of intents) {
    if (i.paperTradeId) continue;
    const key = k(i);
    if (seenKeys.has(key)) continue;
    seenKeys.add(key);
    // Two intents on one key is ambiguity: refuse the whole key rather than guess which
    // dispatch the leg came from.
    const sameKey = intents.filter((x) => !x.paperTradeId && k(x) === key);
    const cands = (legsByKey.get(key) ?? []).filter((l) => !linkedTradeIds.has(l.id));
    if (cands.length === 0) {
      noLeg.push(key);
      continue;
    }
    if (sameKey.length !== 1 || cands.length !== 1) {
      ambiguous.push(key);
      continue;
    }
    const l = cands[0];
    const pair: Pair = {
      legId: l.id,
      legPnl: l.realizedPnl ?? 0,
      legSize: l.simulatedPositionSize,
      legSettled: l.status === "closed" || l.status === "resolved",
      intentId: i.id,
      intentPrice: i.intentPrice,
      entryPrice: l.entryPrice,
      marketId: i.marketId,
    };
    if (isInverted(l.entryPrice, i.intentPrice)) inverted.push(pair);
    else pairs.push(pair);
  }

  const notional = pairs.reduce((a, p) => a + p.legSize, 0);
  const booked = pairs.reduce((a, p) => a + p.legPnl, 0);
  const settled = pairs.filter((p) => p.legSettled).length;
  const linkedCount = intents.filter((i) => i.paperTradeId).length;

  log("");
  log(`C-200 intent links — ${intents.length} intents, ${legs.length} legs`);
  log(`  already linked          : ${linkedCount}`);
  log(`  unlinked intents        : ${intents.length - linkedCount}`);
  log(`  REPAIRABLE 1:1 pairs    : ${pairs.length}   notional $${notional.toFixed(2)}   booked PnL $${booked.toFixed(2)}   settled ${settled}`);
  log(`  ambiguous (refused)     : ${ambiguous.length} keys`);
  log(`  unlinked intent, no leg : ${noLeg.length} (the dispatch never booked a row — expected)`);
  if (inverted.length) {
    const invNot = inverted.reduce((a, p) => a + p.legSize, 0);
    const invPnl = inverted.reduce((a, p) => a + p.legPnl, 0);
    log(
      `  REFUSED, complement frame: ${inverted.length} pairs  notional $${invNot.toFixed(2)}  ` +
        `booked PnL $${invPnl.toFixed(2)}  (entry = 1 - intent; linking would hand the resolver a level a dollar away)`
    );
  }
  if (pairs.length) {
    const gaps = pairs.map((p) => p.entryPrice - p.intentPrice).sort((a, b) => a - b);
    log(
      `  entry - intent on the pairs: median ${gaps[Math.floor(gaps.length / 2)].toFixed(4)} ` +
        `min ${gaps[0].toFixed(4)} max ${gaps[gaps.length - 1].toFixed(4)}`
    );
    for (const p of pairs.slice(0, 5)) {
      log(`    ${p.legId} ${p.marketId.slice(0, 38)} entry=${p.entryPrice.toFixed(4)} intent=${p.intentPrice.toFixed(4)} pnl=${p.legPnl.toFixed(2)}`);
    }
  }

  if (!apply) {
    log("");
    log("DRY RUN — nothing written. Applying links lets the resolver stamp these legs on its next");
    log("run, which moves booked PnL -> netWorth -> the exposure cap and the drawdown gate (LANE A).");
    log(`Re-run with --apply to link ${pairs.length} pair(s).`);
    return;
  }

  let wrote = 0;
  for (const p of pairs) {
    try {
      await prisma.$transaction([
        prisma.paperTrade.update({ where: { id: p.legId }, data: { intentPrice: p.intentPrice } }),
        prisma.fillIntent.update({
          where: { id: p.intentId },
          data: { paperTradeId: p.legId, linkedAt: new Date() },
        }),
      ]);
      wrote++;
    } catch (e: any) {
      log(`  FAILED ${p.legId}: ${e?.message ?? e}`);
    }
  }
  log(`DONE. ${wrote}/${pairs.length} pairs linked. The resolver's next run will now see them.`);
}

main()
  .catch((e) => {
    log(`FAILED: ${e instanceof Error ? e.message : e}`);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
