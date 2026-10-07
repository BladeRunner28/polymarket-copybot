/**
 * Evidence harness (read-only, no writes) for the band-exit settlement fix.
 *
 * Reads the market-settlement rows of the shipped all-time 0.20-0.40 JSON, whose
 * `settlementValue` was produced by the PRE-FIX raw `winnerLabel === outcome`
 * compare, re-resolves each market through the adapter / event fallback, and
 * prints the value the fixed `settlementValue()` would give instead.
 *
 * Run: DATA_MODE=live DATABASE_URL="file:/Users/xsnyde2/polymarket-copybot/prisma/dev.db?immutable=1" \
 *      npx tsx verify-band-settlement-fix.ts
 */
import { prisma } from "./src/lib/db";
import { getAdapter } from "./src/lib/adapters";
import { fetchEventResolution } from "./src/lib/dead-market-resolution";
import { settlementValue } from "./src/lib/resolution";
import * as fs from "fs";
import { join } from "path";

const SRC = join(__dirname, "data", "band-exit-exemption-alltime-0.2-0.4.json");

async function main() {
  const doc = JSON.parse(fs.readFileSync(SRC, "utf8")) as { rows: any[] };
  const rows = doc.rows.filter((r) => r.settlementSource === "market-settlement");
  const ids = [...new Set(rows.map((r) => r.tradeId))] as string[];
  const trades = await prisma.paperTrade.findMany({
    where: { id: { in: ids } },
    select: { id: true, marketId: true, outcome: true },
  });
  const byId = new Map(trades.map((t) => [t.id, t]));
  const adapter = getAdapter();

  let changed = 0,
    same = 0,
    nolabel = 0;
  for (const r of rows) {
    const t = byId.get(r.tradeId);
    if (!t) {
      console.log(`  ?? trade ${r.tradeId} not found`);
      continue;
    }
    let label: string | undefined;
    let source = "gamma";
    try {
      const m = await adapter.fetchMarket(t.marketId);
      if (m.resolved) label = m.winningLabel ?? m.winningOutcome;
    } catch {
      /* try event route */
    }
    if (label === undefined) {
      try {
        const ev = await fetchEventResolution(t.marketId);
        if (ev) {
          label = ev;
          source = "event";
        }
      } catch {
        /* leave */
      }
    }
    if (label === undefined) {
      nolabel++;
      console.log(`  ${String(t.outcome).padEnd(16)} no label now (pre-fix value ${r.settlementValue})  ${t.marketId}`);
      continue;
    }
    const fixed = settlementValue(t.outcome, { winningLabel: label });
    const pre = r.settlementValue as 0 | 1 | null;
    if (pre !== fixed) changed++;
    else same++;
    console.log(
      `  stored=${String(t.outcome).padEnd(16)} venue=${String(label).padEnd(16)} [${source}] pre-fix=${pre}  fixed=${fixed}  ${t.marketId}`
    );
  }
  console.log(`\nmarket-settlement rows re-checked: ${rows.length}  changed=${changed}  unchanged=${same}  no-label-now=${nolabel}`);
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
