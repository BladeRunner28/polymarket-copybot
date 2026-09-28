/**
 * dead-slug-cache — the SHARED 404 negative-cache (tuning review #38 rec 3,
 * user-approved 2026-09-28).
 *
 * Gamma permanently purges dead/renamed slugs, and every consumer that fetches a
 * market per position pays to re-learn that. The v41 cache (#12, 2026-09-01) was
 * consulted ONLY by scripts/update-pnl.ts, so the scorer re-probed 109 dead slugs
 * 299 times in one 24 h window (29 -> 78 -> 299 across three windows).
 *
 * Two things changed here, and the second matters as much as the first:
 *   1. READS — the scorer consults the same file before `adapter.fetchMarket`.
 *   2. WRITES — the scorer also REMEMBERS a fresh 404. update-pnl only ever
 *      fetches markets the book HOLDS, so the slugs the scorer trips over
 *      (detected but unfillable markets) never entered the cache at all; that is
 *      why "none of the repeaters are in the 24-slot cache" (#38 evidence).
 *
 * FIFO cap 24 -> 200: one window produced 109 distinct dead slugs, so a 24-slot
 * FIFO evicts a slug before it can be reused.
 *
 * Writes are best-effort and atomic (tmp + rename): the monitor and the hourly
 * pnl job both write this file, and a torn write could otherwise be re-read by
 * the other process. Any unreadable/malformed content reads as an empty cache by
 * design — a lost entry costs one doomed fetch, never a run.
 */
import * as fs from "fs";
import { join } from "path";

export const MAX_DEAD_SLUGS = 200;
export const DEAD_SLUG_CACHE_FILE = join(__dirname, "..", "..", "data", "dead-slug-cache.json");

/** Load the FIFO (oldest first). Never throws. */
export function loadDeadSlugs(): Set<string> {
  try {
    const cached = JSON.parse(fs.readFileSync(DEAD_SLUG_CACHE_FILE, "utf-8"));
    return new Set(Array.isArray(cached) ? (cached as string[]).slice(-MAX_DEAD_SLUGS) : []);
  } catch {
    return new Set();
  }
}

/**
 * Record a slug that returned a clean 404 and persist the FIFO. Idempotent;
 * callers pass the Set they loaded (and reuse it for `has` checks in the run).
 * A failed write is swallowed — the cache is an optimisation, never a gate.
 */
export function rememberDeadSlug(cache: Set<string>, marketId: string): void {
  if (cache.has(marketId)) return;
  cache.add(marketId);
  const kept = [...cache].slice(-MAX_DEAD_SLUGS);
  cache.clear();
  for (const s of kept) cache.add(s);
  const tmp = `${DEAD_SLUG_CACHE_FILE}.tmp-${process.pid}`;
  try {
    fs.writeFileSync(tmp, JSON.stringify(kept));
    fs.renameSync(tmp, DEAD_SLUG_CACHE_FILE);
  } catch {
    try {
      fs.unlinkSync(tmp);
    } catch {
      /* ignore */
    }
  }
}
