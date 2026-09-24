/**
 * probe-sqlite-pragmas — read the SQLite settings the RUNNING app sees, through the
 * same Prisma client every job uses. Evidence for the DB-contention fix
 * (tuning #35 Rec 1): journal_mode must be `wal` and busy_timeout non-zero per
 * connection, otherwise concurrent writers keep dying with SQLITE_BUSY timeouts.
 *
 *   npx tsx scripts/probe-sqlite-pragmas.ts            # app connection
 *   sqlite3 prisma/dev.db "PRAGMA journal_mode;"       # file-level truth (WAL is persistent)
 *
 * Read-only: only PRAGMA reads and one `SELECT 1` liveness query.
 */

import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();

async function main() {
  const url = process.env.DATABASE_URL ?? "(unset)";
  console.log(`DATABASE_URL in process.env: ${url}`);
  const one = await prisma.$queryRawUnsafe<{ one: number }[]>("SELECT 1 AS one");
  console.log(`liveness SELECT 1 -> ${one[0]?.one}`);
  const jm = await prisma.$queryRawUnsafe<{ journal_mode: string }[]>("PRAGMA journal_mode");
  console.log(`app connection PRAGMA journal_mode = ${jm[0]?.journal_mode}`);
  const bt = await prisma.$queryRawUnsafe<{ timeout: number }[]>("PRAGMA busy_timeout");
  console.log(`app connection PRAGMA busy_timeout = ${bt[0]?.timeout}`);
  const fk = await prisma.$queryRawUnsafe<{ foreign_keys: number }[]>("PRAGMA foreign_keys");
  console.log(`app connection PRAGMA foreign_keys = ${fk[0]?.foreign_keys}`);
  const pages = await prisma.$queryRawUnsafe<{ page_count: number | bigint }[]>("PRAGMA page_count");
  const size = await prisma.$queryRawUnsafe<{ page_size: number | bigint }[]>("PRAGMA page_size");
  const nPages = Number(pages[0]?.page_count ?? 0);
  const nSize = Number(size[0]?.page_size ?? 0);
  console.log(`db: ${nPages} pages x ${nSize} B = ${((nPages * nSize) / 1e9).toFixed(2)} GB`);
}

main()
  .catch((e) => {
    console.error("PROBE FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
