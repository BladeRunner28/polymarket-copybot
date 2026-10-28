/**
 * close-log — append-only sidecar for EARLY EXIT reasons.
 *
 * 2026-10-28 (Lane B, instrument repair). `closePaperTrade` received a `reason` argument and
 * then threw it away: every early exit lands in the DB as `status='closed'` with nothing to
 * distinguish a v66 stale stop from a dead-slug 404 expiry or a C-200 recycle. Consequences
 * measured the same day:
 *
 *   - v66's own pre-registered refutation ("the first 20 ORGANIC stopped legs realise worse
 *     than hold by more than 1% of notional") is NOT computable from the DB. The 2026-10-24
 *     sweep could only be priced because it happened at a single timestamp and was the only
 *     non-404 close STANDARD had ever taken; the next stop would be invisible.
 *   - The profit review's one usable split (stale stop -$831.70 alpha vs 404 expiry +$210.73
 *     on 6,503 legs) was reconstructed BY ELIMINATION, which stops working the moment the
 *     rail fires a second time.
 *
 * No schema change, no prisma write, no decision influence: one JSONL line per close,
 * append-only, joined to PaperTrade by id. Writes are best-effort by design -- an
 * observability ledger must never be able to fail a paper close.
 */
import fs from "node:fs";
import path from "node:path";

export interface CloseReasonRecord {
  id: string;
  botId: string;
  marketId: string;
  outcome: string;
  entryPrice: number;
  exitPrice: number;
  sizeUsd: number;
  pnl: number;
  ageHours: number;
  reason: string;
}

export function closeLogPath(dir = process.env.DATA_DIR || "data"): string {
  return path.join(dir, "close-reasons.jsonl");
}

/** Append one close to the sidecar. Returns the line written, or null if it failed. */
export function appendCloseReason(
  rec: CloseReasonRecord,
  dir = process.env.DATA_DIR || "data"
): string | null {
  try {
    fs.mkdirSync(dir, { recursive: true });
    const line = JSON.stringify({ ...rec, at: new Date().toISOString() });
    fs.appendFileSync(closeLogPath(dir), line + "\n");
    return line;
  } catch {
    return null;
  }
}
