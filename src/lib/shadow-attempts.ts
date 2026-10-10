/**
 * Attempt ledger + least-recently-attempted walk rotation for the shadow
 * settlement markers (2026-10-10, card t_81d0a4cb — INSTRUMENT ONLY).
 *
 * WHY THIS EXISTS (measured, not theorised):
 * scripts/mark-shadow-longshot.ts walked each feed's `pending` map oldest-first
 * and took the first MARK_LIMIT (300) entries. The drift feed's head is a
 * September cohort of LONG-DATED MARKETS THAT HAVE NOT SETTLED YET: the first
 * 300 keys in candidate order are all decided 2026-09-17 (the pending block
 * decided on/before 2026-09-26 is 4,545 of 6,165 keys), and re-read through the
 * walk's own path (`getAdapter().fetchMarket` + `fetchEventResolution`) the head
 * is 30/30 still open with live quotes — NFL season series, the November BoE and
 * October Bank-of-Russia rate decisions, the Berlin Abgeordnetenhaus, the
 * Richmond mayoral election, NH-02. `m.resolved` is false on every one of them,
 * so both resolution paths return nothing, `value === undefined`, `continue`,
 * and the same 300 slots were re-attempted every hour while the feed stopped
 * marking: 14 consecutive hourly runs logged `+0 marked` (the live log also
 * shows earlier streaks of 22 and 30), settled frozen at 4,945, while 828
 * candidates decided inside the trailing 7 days sat unreachable behind the head.
 * The pre-registered 2026-09-20 decay bar reads a trailing-7d cohort mean, so it
 * could never be populated: `cohort7dMarked` stayed 0 and the EOD printed
 * "cohort7d —".
 *
 * This is head-of-line blocking, NOT venue archival: the head cannot settle yet,
 * but it will, and none of its rows 404s. The `GET /markets?slug=<slug>` → `[]`
 * body quoted in the original card is the DEPRECATED endpoint, which answers
 * `[]` for live and settled markets alike (it also returns `[]` for markets this
 * walk does mark); the adapter prefers `/markets/slug/<slug>`, which returns the
 * market for every slug the card cited, and the cited Hong Kong temperature
 * market resolves through the walk's own path (resolved: true, "No").
 *
 * WHAT THIS MODULE DOES:
 *  - keeps a per-candidate attempt ledger (last attempt stamp + consecutive
 *    failures + total attempts), persisted to data/shadow-attempt-state.json so
 *    it survives process restarts (the same idea as the v62 observe rotation,
 *    src/lib/wallet-universe.ts `lastObservedAt` + least-recently-first);
 *  - orders each run's walk by LEAST-RECENTLY-ATTEMPTED instead of strictly
 *    oldest-first, so a head of still-open rows cannot monopolise the run's
 *    slots;
 *  - holds a candidate back for ATTEMPT_RETRY_HOURS once it has failed
 *    ATTEMPT_FAIL_LIMIT times in a row, then lets it re-enter the walk at its
 *    (by then old) stamp — a market that resolves late is still re-attempted on
 *    a slow cadence and is never lost.
 *
 * ORDERING, exactly:
 *  1. never-attempted candidates first — they are the least recently attempted
 *     by definition — ordered most-recently-DECIDED first among themselves;
 *  2. then attempted candidates, oldest attempt stamp first;
 *  3. a candidate at/over the failure limit is excluded from the walk (counted
 *     as `heldBack`) until the retry window has elapsed since its last attempt.
 *
 * The recent-decided tie-break for never-attempted rows is load-bearing, not
 * cosmetic: a fresh ledger makes every pending row tie at "never attempted",
 * and this feed adds ~2k candidates a day, so an oldest-first tie-break would
 * reproduce exactly the starvation this module removes — the trailing-7d cohort
 * that justified the fix would sit behind ~5,000 older rows for a whole cycle
 * (~21 h at 300/run). Recently decided candidates are also the ones that can
 * actually resolve at the venue: the stuck head is the long-dated September
 * cohort that has not settled yet, while the rows behind it are short-dated
 * markets that already have (the proof runs marked 276/300 and 295/300 of them).
 *
 * BLAST RADIUS: the ledger is instrument state only. It never changes what a
 * candidate means, never marks, edits or back-fills a candidate row, never
 * writes a `resolve` record, and never touches a trading path. A candidate that
 * cannot be resolved stays pending — it just stops occupying the head of the
 * walk.
 */

import * as fs from "fs";
import { join } from "path";

export const ATTEMPT_STATE_FILE = join(__dirname, "..", "..", "data", "shadow-attempt-state.json");

/** Consecutive failed attempts before a candidate is held back. */
export const ATTEMPT_FAIL_LIMIT = Number(process.env.SHADOW_ATTEMPT_FAIL_LIMIT ?? 3);
/** How long a held-back candidate waits before it is re-attempted. */
export const ATTEMPT_RETRY_HOURS = Number(process.env.SHADOW_ATTEMPT_RETRY_HOURS ?? 24);
export const ATTEMPT_RETRY_MS = ATTEMPT_RETRY_HOURS * 3_600_000;

export interface AttemptStamp {
  /** ISO timestamp of this candidate's most recent attempt. */
  lastAttemptAt: string;
  /** Failed attempts since the last success (a success removes the stamp). */
  consecutiveFailures: number;
  /** Total attempts ever made (observability only). */
  attempts: number;
}

/** `feed|marketId|outcome` → stamp. Only feeds that opt into rotation appear. */
export type AttemptLedger = Record<string, AttemptStamp>;

export interface PendingEntry {
  marketId: string;
  outcome: string;
  /** Decision time of the candidate (ms). For duplicate keys, the most recent. */
  decidedAt: number;
}

export interface RotationResult {
  selected: PendingEntry[];
  /** Pending rows that were eligible this run (before the cap). */
  eligible: number;
  /** Rows withheld because they are inside the failure-limit retry window. */
  heldBack: number;
  /** Selected rows that carry no stamp yet (never attempted before). */
  neverAttempted: number;
}

export interface AttemptOutcome {
  marketId: string;
  outcome: string;
  /** True when this attempt produced a settlement value (the candidate is done). */
  resolved: boolean;
}

export function attemptKey(feed: string, marketId: string, outcome: string): string {
  return `${feed}|${marketId}|${outcome}`;
}

export function readAttemptLedger(file: string = ATTEMPT_STATE_FILE): AttemptLedger {
  try {
    const parsed = JSON.parse(fs.readFileSync(file, "utf-8")) as unknown;
    if (!parsed || typeof parsed !== "object") return {};
    const out: AttemptLedger = {};
    for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
      const stamp = v as Partial<AttemptStamp>;
      if (!stamp || typeof stamp.lastAttemptAt !== "string") continue;
      out[k] = {
        lastAttemptAt: stamp.lastAttemptAt,
        consecutiveFailures: Number(stamp.consecutiveFailures ?? 0),
        attempts: Number(stamp.attempts ?? 0),
      };
    }
    return out;
  } catch {
    // No ledger yet (first run) or an unreadable/corrupt file: start from empty
    // rather than fail the marker — a fresh ledger only costs re-attempts.
    return {};
  }
}

/**
 * Write the ledger. Atomic (temp + rename): the marker can be killed mid-walk
 * and a half-written ledger would silently re-order the next run's walk.
 */
export function writeAttemptLedger(ledger: AttemptLedger, file: string = ATTEMPT_STATE_FILE): void {
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(ledger));
  fs.renameSync(tmp, file);
}

/** Keep only stamps whose key is still pending — resolved rows drop out. */
export function pruneAttemptLedger(ledger: AttemptLedger, pendingKeys: Iterable<string>): AttemptLedger {
  const keep = new Set(pendingKeys);
  for (const key of Object.keys(ledger)) if (!keep.has(key)) delete ledger[key];
  return ledger;
}

/**
 * Pick this run's walk. Never-attempted first (most recent decision first),
 * then least-recently-attempted, skipping rows inside the failure retry window.
 */
export function selectPendingForRun(
  feed: string,
  pending: PendingEntry[],
  ledger: AttemptLedger,
  opts: { limit: number; now: number; failLimit?: number; retryMs?: number }
): RotationResult {
  const failLimit = opts.failLimit ?? ATTEMPT_FAIL_LIMIT;
  const retryMs = opts.retryMs ?? ATTEMPT_RETRY_MS;
  const ranked: Array<{ entry: PendingEntry; never: boolean; lastAt: number; key: string }> = [];
  let heldBack = 0;

  for (const entry of pending) {
    const key = attemptKey(feed, entry.marketId, entry.outcome);
    const stamp = ledger[key];
    if (!stamp) {
      ranked.push({ entry, never: true, lastAt: 0, key });
      continue;
    }
    const parsed = Date.parse(stamp.lastAttemptAt);
    const lastAt = Number.isFinite(parsed) ? parsed : 0;
    if (stamp.consecutiveFailures >= failLimit && opts.now - lastAt < retryMs) {
      heldBack++;
      continue;
    }
    ranked.push({ entry, never: false, lastAt, key });
  }

  ranked.sort((a, b) => {
    if (a.never !== b.never) return a.never ? -1 : 1;
    if (a.never) {
      if (a.entry.decidedAt !== b.entry.decidedAt) return b.entry.decidedAt - a.entry.decidedAt;
    } else if (a.lastAt !== b.lastAt) {
      return a.lastAt - b.lastAt;
    }
    return a.key < b.key ? -1 : a.key > b.key ? 1 : 0;
  });

  const selected = ranked.slice(0, Math.max(0, opts.limit));
  return {
    selected: selected.map((r) => r.entry),
    eligible: ranked.length,
    heldBack,
    neverAttempted: selected.filter((r) => r.never).length,
  };
}

/**
 * Fold one run's attempts into the ledger: a resolved candidate leaves the
 * ledger (and `pending`) entirely; a failed attempt increments the streak so the
 * failure limit can hold it back.
 */
export function recordAttemptOutcome(
  feed: string,
  outcomes: AttemptOutcome[],
  ledger: AttemptLedger,
  now: number
): void {
  for (const o of outcomes) {
    const key = attemptKey(feed, o.marketId, o.outcome);
    if (o.resolved) {
      delete ledger[key];
      continue;
    }
    const prev = ledger[key];
    ledger[key] = {
      lastAttemptAt: new Date(now).toISOString(),
      consecutiveFailures: (prev?.consecutiveFailures ?? 0) + 1,
      attempts: (prev?.attempts ?? 0) + 1,
    };
  }
}
