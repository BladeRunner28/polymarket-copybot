/**
 * provenance-persistence-read — is the DataProvenance stamp actually ON the rows?
 * Read-only. Evidence for card `polyterm-p1-provenance-persistence` (2026-11-09, Lane B).
 *
 * WHY. The card's complaint is a claim that was made and not true: the C-200 print-through
 * work was called "auditable", while the lag label lived only in memory (src/lib/provenance.ts)
 * and died with the process. Persisting it is half the fix; this instrument is the other half,
 * because "we added columns" is not evidence that a single row carries one.
 *
 * THE RULE IT ENFORCES (epoch rule, src/lib/provenance-persistence.ts):
 *   rows written BEFORE the first stamped row are legacy NULL by design (the class is not
 *   derivable per historical row, so a backfill would be an invented label);
 *   rows written AT OR AFTER it must carry a readable stamp, because every writer since
 *   then runs the stamping code. Any such row without one is a writer that bypasses the
 *   ingest path — RED, not a rounding note.
 *
 * BASIS (printed on every run, never implied):
 *   population = ObservedTrade rows (all isDemo, split reported) — the row class the monitor
 *                writes from the LAGGED data-api activity surface;
 *   level      = one observed print;
 *   clock      = ObservedTrade.createdAt (INGEST time, UTC) — the epoch rule is about when
 *                the writer ran, not when the venue printed.
 *
 * The lifetime totals are SQL aggregates (the table is millions of rows); the epoch verdict
 * is computed on the most recent NEWEST_WINDOW rows through the same pure functions the tests
 * pin, so a stale writer shows up within one poll window rather than in a full scan.
 *
 * Exit: 0 = OK, 1 = RED (unstamped rows after the epoch, or no stamp anywhere), 2 = the
 * columns are missing on this database (prints the exact ALTER TABLE to apply).
 *
 * Run: npx tsx scripts/provenance-persistence-read.ts [--probe]
 */

import { prisma } from "../src/lib/db";
import { coverageVerdict, readProvenanceColumns, summarizeCoverage, type StampObservation } from "../src/lib/provenance-persistence";

const NEWEST_WINDOW = 500;

const pct = (a: number, b: number) => (b > 0 ? `${((100 * a) / b).toFixed(1)}%` : "n/a");
const num = (n: number) => n.toLocaleString("en-US");
const iso = (ms: number | null) => (ms == null ? "none" : new Date(Number(ms)).toISOString().replace(".000Z", "Z"));

interface Totals {
  total: number;
  stamped: number;
  epoch_ms: number | null;
  lastUnstamped_ms: number | null;
  demoStamped: number;
}

async function main() {
  const probe = process.argv.includes("--probe");

  let totals: Totals;
  let lateUnstamped: number;
  try {
    const t = await prisma.$queryRawUnsafe<
      Array<{ total: number | bigint; stamped: number | bigint; epoch_ms: number | bigint | null; lastUnstamped_ms: number | bigint | null; demoStamped: number | bigint }>
    >(
      `SELECT COUNT(*) AS total,
              SUM(CASE WHEN provenanceSource IS NOT NULL THEN 1 ELSE 0 END) AS stamped,
              MIN(CASE WHEN provenanceSource IS NOT NULL THEN createdAt END) AS epoch_ms,
              MAX(CASE WHEN provenanceSource IS NULL THEN createdAt END) AS lastUnstamped_ms,
              SUM(CASE WHEN provenanceSource IS NOT NULL AND isDemo = 1 THEN 1 ELSE 0 END) AS demoStamped
         FROM ObservedTrade`
    );
    const row = t[0];
    totals = {
      total: Number(row.total),
      stamped: Number(row.stamped ?? 0),
      epoch_ms: row.epoch_ms == null ? null : Number(row.epoch_ms),
      lastUnstamped_ms: row.lastUnstamped_ms == null ? null : Number(row.lastUnstamped_ms),
      demoStamped: Number(row.demoStamped ?? 0),
    };
    const late = await prisma.$queryRawUnsafe<Array<{ n: number | bigint }>>(
      `SELECT COUNT(*) AS n FROM ObservedTrade
        WHERE provenanceSource IS NULL
          AND createdAt >= (SELECT MIN(createdAt) FROM ObservedTrade WHERE provenanceSource IS NOT NULL)`
    );
    lateUnstamped = Number(late[0]?.n ?? 0);
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    console.error(`COLUMNS MISSING or unreadable on this database: ${msg}`);
    console.error(
      "Apply (additive, NULL-safe, O(1) in SQLite):\n" +
        "  ALTER TABLE ObservedTrade ADD COLUMN provenanceSource TEXT;\n" +
        "  ALTER TABLE ObservedTrade ADD COLUMN provenanceLagged BOOLEAN;\n" +
        "  ALTER TABLE ObservedTrade ADD COLUMN provenanceFlags TEXT;"
    );
    process.exitCode = 2;
    return;
  }

  console.log("provenance persistence — ObservedTrade rows carrying the lag stamp");
  console.log(
    `BASIS: population = ObservedTrade (level = one observed print); clock = createdAt (ingest, UTC); ` +
      `source = data-api activity surface (lagged, never the live CLOB tape)`
  );
  console.log(
    `LIFETIME: ${num(totals.total)} rows | stamped ${num(totals.stamped)} (${pct(totals.stamped, totals.total)}) | ` +
      `unstamped ${num(totals.total - totals.stamped)} (legacy NULL by design)`
  );
  console.log(
    `EPOCH: first stamped row createdAt ${iso(totals.epoch_ms)} | last unstamped row createdAt ${iso(totals.lastUnstamped_ms)} | ` +
      `unstamped at/after epoch ${num(lateUnstamped)}`
  );
  console.log(`DEMO SPLIT: ${num(totals.demoStamped)} of ${num(totals.stamped)} stamped rows are isDemo=1 (reporting only, not a gap)`);

  // Newest window through the same pure functions the tests pin.
  const newest = await prisma.$queryRawUnsafe<
    Array<{ createdAt: number | bigint; provenanceSource: string | null; provenanceLagged: number | bigint | null; provenanceFlags: string | null; side: string }>
  >(
    `SELECT createdAt, provenanceSource, provenanceLagged, provenanceFlags, side
       FROM ObservedTrade ORDER BY createdAt DESC LIMIT ${NEWEST_WINDOW}`
  );
  if (newest.length === 0) {
    console.log("NEWEST WINDOW: empty — no rows to judge.");
    process.exitCode = 1;
    return;
  }
  const obs: StampObservation[] = newest.map((r) => ({
    at: new Date(Number(r.createdAt)),
    stamped:
      readProvenanceColumns({
        provenanceSource: r.provenanceSource,
        provenanceLagged: r.provenanceLagged == null ? null : Number(r.provenanceLagged) === 1,
        provenanceFlags: r.provenanceFlags,
      }) !== null,
  }));
  const frame = summarizeCoverage(obs);
  const verdict = coverageVerdict(frame);
  const oldest = newest[newest.length - 1];
  const newestRow = newest[0];
  console.log(
    `NEWEST WINDOW: n=${num(newest.length)} rows, createdAt ${iso(Number(oldest.createdAt))} .. ${iso(Number(newestRow.createdAt))} | ` +
      `stamped ${num(frame.stamped)} (${pct(frame.stamped, frame.total)}) | epoch ${iso(frame.epoch ? frame.epoch.getTime() : null)}`
  );
  console.log(
    `FLAGS ON NEWEST ROW: ${JSON.stringify(
      readProvenanceColumns({
        provenanceSource: newestRow.provenanceSource,
        provenanceLagged: newestRow.provenanceLagged == null ? null : Number(newestRow.provenanceLagged) === 1,
        provenanceFlags: newestRow.provenanceFlags,
      })
    )}`
  );

  let probeFailed = false;
  if (probe) {
    // Does the stamp still travel from the venue read to a caller? One tracked wallet, one
    // page — keyless, read-only. A failure here is reported, not swallowed.
    const w = await prisma.walletProfile.findFirst({
      where: { isDemo: false, status: "track" },
      select: { address: true },
      orderBy: { lastScannedAt: "desc" },
    });
    if (!w) {
      console.log("PROBE: no tracked wallet to read — skipped.");
    } else {
      try {
        const { PolymarketAdapter } = await import("../src/lib/adapters/polymarket");
        const adapter = new PolymarketAdapter();
        const rows = await adapter.fetchWalletActivity(w.address, 1);
        const stamped = rows.filter((r) => readProvenanceColumns(provenanceToColumns(r.provenance)) !== null).length;
        console.log(
          `PROBE: ${num(rows.length)} activity row(s) for ${w.address} over 24h — ${num(stamped)} carry a readable stamp ` +
            `(${pct(stamped, rows.length)}) | sample ${rows[0] ? JSON.stringify(rows[0].provenance ?? null) : "none"}`
        );
        if (rows.length > 0 && stamped !== rows.length) probeFailed = true;
      } catch (e) {
        console.log(`PROBE FAILED (real error, not suppressed): ${e instanceof Error ? e.message : e}`);
        probeFailed = true;
      }
    }
  }

  console.log(`VERDICT: ${verdict.reason}${probeFailed ? " | PROBE arm failed — see above" : ""}`);
  if (!verdict.ok || probeFailed) process.exitCode = 1;
}

/**
 * Adapter rows already carry the columns shape in memory (`provenance`), so the probe maps
 * the live object through the same converter rather than re-implementing the label.
 */
function provenanceToColumns(p: DataProvenanceLike | undefined): ProvenanceColumnsLike {
  if (!p) return { provenanceSource: null, provenanceLagged: null, provenanceFlags: null };
  return {
    provenanceSource: p.source,
    provenanceLagged: p.lagged,
    provenanceFlags: p.qualityFlags.length ? JSON.stringify(p.qualityFlags) : null,
  };
}

type DataProvenanceLike = { source: string; lagged: boolean; qualityFlags: string[] };
type ProvenanceColumnsLike = { provenanceSource: string | null; provenanceLagged: boolean | null; provenanceFlags: string | null };

main()
  .catch((e) => {
    console.error(e);
    process.exitCode = 1;
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
