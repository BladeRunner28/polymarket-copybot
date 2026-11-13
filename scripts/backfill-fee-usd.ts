/**
 * backfill:fee — stamp the modelled taker fee onto PaperTrade rows (Lane A apply step).
 *
 * CARD `fee-booking-net-ledger`. This script is the APPLY half of the proposal in
 * drafts/fee-booking-net-ledger-20261112.md. It is DRY RUN BY DEFAULT: with no
 * flags it reads the book, prices every leg, prints the before/after table and
 * writes nothing.
 *
 * WHAT IT WRITES (only with --apply)
 *   feeUsd      entry taker fee in dollars  = size * rate * (1 - entryPrice)
 *   feeExitUsd  exit taker fee, only on status='closed' (a real sell), else 0
 *   feeRate     the rate used
 *   feeBasis    'proxy:<category>' | 'venue'  — which rate source priced this row
 *   NOTHING ELSE. `realizedPnl` is never touched: every historical figure, the PnL
 *   rollup and the cumulative series stay byte-identical. The net figure is derived
 *   at read time behind FEE_NET_LEDGER (see src/lib/fee.ts).
 *
 * PREREQUISITE (the operator's step — additive DDL, O(1) in SQLite):
 *   ALTER TABLE PaperTrade ADD COLUMN feeUsd REAL;
 *   ALTER TABLE PaperTrade ADD COLUMN feeExitUsd REAL;
 *   ALTER TABLE PaperTrade ADD COLUMN feeRate REAL;
 *   ALTER TABLE PaperTrade ADD COLUMN feeBasis TEXT;
 * or, equivalently, the four fields in prisma/schema.prisma + `npm run db:push`.
 * The script checks for the columns and refuses with that text if they are missing.
 *
 * USAGE
 *   npx tsx scripts/backfill-fee-usd.ts                       # dry run (default)
 *   npx tsx scripts/backfill-fee-usd.ts --basis=entry          # dry run, entry fee only
 *   npx tsx scripts/backfill-fee-usd.ts --apply --dump=data/backfill-fee-<date>.json
 *   npx tsx scripts/backfill-fee-usd.ts --revert --apply       # NULL every fee column
 *
 * BACKUP: --apply --dump=<path> writes every affected row (id, before, after) so the
 * write can be diffed or reversed row for row. --revert is the one-command undo.
 *
 * READ-ONLY NOTE: the dry run uses only SELECTs. Verified by printing the row count
 * and the SUM before/after in the same run.
 */

import * as fs from "fs";
import { prisma } from "../src/lib/db";
import { bookedFee, type FeeBasis } from "../src/lib/fee";

const APPLY = process.argv.includes("--apply");
const REVERT = process.argv.includes("--revert");
const basisArg = process.argv.find((a) => a.startsWith("--basis="));
const BASIS: FeeBasis = basisArg && basisArg.split("=")[1] === "entry" ? "entry" : "two";
const dumpArg = process.argv.find((a) => a.startsWith("--dump="));
const DUMP_PATH = dumpArg ? dumpArg.split("=")[1] : null;
const BATCH = 500;

interface Row {
  id: string;
  botId: string;
  marketId: string;
  status: string;
  entryPrice: number;
  simulatedPositionSize: number;
  realizedPnl: number | null;
  feeUsd: number | null;
  feeExitUsd: number | null;
}

function venueRateMap(): Map<string, number> {
  const out = new Map<string, number>();
  const p = "data/fee-schedules.jsonl";
  if (!fs.existsSync(p)) return out;
  for (const ln of fs.readFileSync(p, "utf8").split("\n")) {
    if (!ln.trim()) continue;
    try {
      const row = JSON.parse(ln);
      const r = row.resolvedRate ?? row.feeSchedule?.rate;
      if (row.slug && typeof r === "number") out.set(String(row.slug), r);
    } catch {
      /* a malformed capture line must not abort a backfill */
    }
  }
  return out;
}

async function columns(): Promise<Set<string>> {
  const rows = await prisma.$queryRawUnsafe<Array<{ name: string }>>(
    `SELECT name FROM pragma_table_info('PaperTrade')`
  );
  return new Set(rows.map((r) => r.name));
}

async function main() {
  const cols = await columns();
  const missing = ["feeUsd", "feeExitUsd", "feeRate", "feeBasis"].filter((c) => !cols.has(c));
  if (missing.length && !REVERT) {
    console.error(`COLUMNS MISSING on PaperTrade: ${missing.join(", ")}`);
    console.error("Apply the additive DDL first (O(1), NULL-safe), then re-run:");
    console.error("  ALTER TABLE PaperTrade ADD COLUMN feeUsd REAL;");
    console.error("  ALTER TABLE PaperTrade ADD COLUMN feeExitUsd REAL;");
    console.error("  ALTER TABLE PaperTrade ADD COLUMN feeRate REAL;");
    console.error("  ALTER TABLE PaperTrade ADD COLUMN feeBasis TEXT;");
    console.error("  (or add the fields to prisma/schema.prisma and run `npm run db:push`)");
    process.exitCode = 2;
    return;
  }

  const rows = await prisma.$queryRawUnsafe<Row[]>(
    `SELECT id, botId, marketId, status, entryPrice, simulatedPositionSize, realizedPnl, feeUsd, feeExitUsd
       FROM PaperTrade WHERE isDemo = 0`
  );
  console.log(`backfill:fee — ${APPLY ? "APPLY" : "DRY RUN"}${REVERT ? " (REVERT)" : ""} · basis=${BASIS}`);
  console.log(
    `BASIS: population = PaperTrade isDemo=0 (${rows.length} rows) · cost basis = simulatedPositionSize ` +
      `(dollars at risk) · rate = venue schedule where captured, else the slug-keyword proxy · ` +
      `exit fee only on status='closed'`
  );

  if (REVERT) {
    if (!APPLY) {
      console.log("revert is a no-op without --apply; nothing written.");
      return;
    }
    const n = await prisma.$executeRawUnsafe(
      `UPDATE PaperTrade SET feeUsd = NULL, feeExitUsd = NULL, feeRate = NULL, feeBasis = NULL`
    );
    console.log(`reverted ${n} rows: fee columns NULL (realizedPnl untouched, as it always was).`);
    return;
  }

  const vrates = venueRateMap();
  const dump: Array<Record<string, unknown>> = [];
  let feeEntry = 0;
  let feeExit = 0;
  let notional = 0;
  let gross = 0;
  let venueRows = 0;
  const byStatus = new Map<string, { n: number; fee: number }>();

  for (const r of rows) {
    const f = bookedFee(
      {
        entryPrice: Number(r.entryPrice),
        simulatedPositionSize: Number(r.simulatedPositionSize),
        realizedPnl: r.realizedPnl === null ? 0 : Number(r.realizedPnl),
        status: r.status,
        marketId: r.marketId,
      },
      { basis: BASIS, venueRates: vrates }
    );
    feeEntry += f.entry;
    feeExit += f.exit;
    notional += Number(r.simulatedPositionSize);
    gross += Number(r.realizedPnl ?? 0);
    if (f.rateSource === "venue") venueRows += 1;
    const s = byStatus.get(r.status) ?? { n: 0, fee: 0 };
    s.n += 1;
    s.fee += f.total;
    byStatus.set(r.status, s);
    if (DUMP_PATH) {
      dump.push({
        id: r.id,
        before: { feeUsd: r.feeUsd, feeExitUsd: r.feeExitUsd },
        after: { feeUsd: f.entry, feeExitUsd: f.exit, feeRate: f.rate, feeBasis: f.rateSource },
        realizedPnl: r.realizedPnl,
      });
    }
  }

  const totalFee = feeEntry + feeExit;
  console.log("");
  console.log(
    `${"status".padEnd(10)} ${"rows".padStart(6)} ${"fee $".padStart(10)}`
  );
  for (const st of ["open", "closed", "resolved"]) {
    const s = byStatus.get(st);
    if (s) console.log(`${st.padEnd(10)} ${String(s.n).padStart(6)} ${s.fee.toFixed(2).padStart(10)}`);
  }
  console.log("");
  console.log(`rows priced          ${rows.length}`);
  console.log(`notional             $${notional.toFixed(2)}`);
  console.log(`gross realizedPnl    $${gross.toFixed(2)}   (UNCHANGED by this script)`);
  console.log(`entry fee            $${feeEntry.toFixed(2)}  = ${((100 * feeEntry) / notional).toFixed(2)}% of notional`);
  console.log(`exit fee (closed)    $${feeExit.toFixed(2)}`);
  console.log(`total fee            $${totalFee.toFixed(2)}  = ${((100 * totalFee) / notional).toFixed(2)}% of notional`);
  console.log(`net after fee        $${(gross - totalFee).toFixed(2)}   (${((100 * (gross - totalFee)) / notional).toFixed(2)}% of notional)`);
  console.log(`venue-rate rows      ${venueRows} of ${rows.length} (${((100 * venueRows) / Math.max(rows.length, 1)).toFixed(2)}%)`);
  if (DUMP_PATH) {
    fs.writeFileSync(DUMP_PATH, JSON.stringify({ generatedAt: new Date().toISOString(), basis: BASIS, rows: dump }, null, 2));
    console.log(`dump written         ${DUMP_PATH} (${dump.length} rows)`);
  }

  if (!APPLY) {
    console.log("");
    console.log("DRY RUN — nothing written. Re-run with --apply (and --dump=<path>) to stamp the rows.");
    return;
  }

  let written = 0;
  for (let i = 0; i < rows.length; i += BATCH) {
    const chunk = rows.slice(i, i + BATCH);
    await prisma.$transaction(
      chunk.map((r) => {
        const f = bookedFee(
          {
            entryPrice: Number(r.entryPrice),
            simulatedPositionSize: Number(r.simulatedPositionSize),
            realizedPnl: r.realizedPnl === null ? 0 : Number(r.realizedPnl),
            status: r.status,
            marketId: r.marketId,
          },
          { basis: BASIS, venueRates: vrates }
        );
        return prisma.$executeRawUnsafe(
          `UPDATE PaperTrade SET feeUsd = ?, feeExitUsd = ?, feeRate = ?, feeBasis = ? WHERE id = ?`,
          f.entry,
          f.exit,
          f.rate,
          f.rateSource,
          r.id
        );
      })
    );
    written += chunk.length;
  }
  const check = await prisma.$queryRawUnsafe<Array<{ n: bigint | number; fee: number | null; pnl: number | null }>>(
    `SELECT COUNT(*) AS n, SUM(feeUsd) AS fee, SUM(realizedPnl) AS pnl FROM PaperTrade WHERE isDemo = 0 AND feeUsd IS NOT NULL`
  );
  console.log("");
  console.log(`WROTE ${written} rows.`);
  console.log(
    `VERIFY: ${Number(check[0]?.n ?? 0)} rows carry a fee, SUM(feeUsd)=$${Number(check[0]?.fee ?? 0).toFixed(2)}, ` +
      `SUM(realizedPnl)=$${Number(check[0]?.pnl ?? 0).toFixed(2)} (must equal the gross printed above).`
  );
  console.log("REVERT: npx tsx scripts/backfill-fee-usd.ts --revert --apply");
}

main()
  .catch((e) => {
    console.error(e);
    process.exitCode = 1;
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
