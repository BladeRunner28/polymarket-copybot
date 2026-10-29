/**
 * sell-log — append-only sidecar for the SELL prints the monitor currently discards.
 *
 * 2026-10-29 (Lane B, instrument repair). `scripts/monitor-trades.ts:130` reads
 *
 *     if (t.side !== "BUY") continue; // copy entries only, not exits
 *
 * so every SELL print by a tracked wallet is fetched from the data API and dropped. The
 * database is the proof: ObservedTrade holds 4,660,889 BUY rows and **10** SELL rows over
 * 2026-06-18 -> 2026-10-29.
 *
 * On Polymarket a SELL of YES at 0.85 is economically a BUY of NO at 0.15, so the filter is
 * not "one direction of exposure" — it removes the only thesis-linked exit signal the book
 * could have, and it makes the wallets' realised behaviour unmeasurable at our own cadence.
 * Measured 2026-10-29 from the data API directly (scripts/profit-sellside.py §SS.1/SS.2):
 * 245 SELL prints in a 3,000-print window per tracked wallet = 3.6% of prints but 9.7% of
 * notional, and 155 round trips with a **median hold of 2.5h at +41.9pp** — against a book
 * whose open legs have a weighted age of ~76 days.
 *
 * This ledger changes NOTHING that the bot decides: no prisma write, no ObservedTrade row,
 * no scoring input, no RuleSet field. It exists so the next review can ask whether a
 * wallet's exit carries information, which cannot be asked retroactively because the prints
 * were never kept. Best-effort by design — an observability ledger must never fail the
 * monitor loop.
 *
 * DUPLICATES ARE EXPECTED: the monitor re-reads a trailing window on every poll and this
 * append happens before the DB dedupe (`seen`), so the same print can land more than once.
 * Dedupe on (wallet, marketId, outcome, side, timestamp, price, size) when reading.
 */
import fs from "node:fs";
import path from "node:path";

export interface SellPrintRecord {
  walletAddress: string;
  marketId: string;
  outcome: string;
  side: string;
  price: number;
  size: number;
  /** Venue print time, ms since epoch — the field every join uses. */
  printTs: number;
  observationOnly: boolean;
}

export function sellLogPath(dir = process.env.DATA_DIR || "data"): string {
  return path.join(dir, "wallet-sells.jsonl");
}

/** Append one non-BUY print to the sidecar. Returns the line written, or null on failure. */
export function appendSellPrint(
  rec: SellPrintRecord,
  dir = process.env.DATA_DIR || "data"
): string | null {
  try {
    fs.mkdirSync(dir, { recursive: true });
    const line = JSON.stringify({ ...rec, loggedAt: new Date().toISOString() });
    fs.appendFileSync(sellLogPath(dir), line + "\n");
    return line;
  } catch {
    return null;
  }
}
