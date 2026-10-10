/**
 * 2026-10-10 (card t_81d0a4cb) — the drift shadow walk must ROTATE.
 *
 * Baseline it fixes (measured in logs/cron/copybot-shadow-longshot.log): the
 * drift walk took the first MARK_LIMIT entries of an oldest-first pending map.
 * The oldest 300 pending candidates were all decided 2026-09-17/18 and their
 * slugs are archived at the venue (gamma answers with an empty body), so 20
 * consecutive hourly runs logged `+0 marked` and settled froze at 4,945 while
 * 828 candidates decided inside the trailing 7 days stayed unreachable — the
 * decay bar's cohort could never be populated (cohort7dMarked: 0).
 *
 * These tests pin the ordering that removes the head-of-line block: least
 * recently attempted first, never-attempted before that (most recent decision
 * first), a row held back only after ATTEMPT_FAIL_LIMIT consecutive failures,
 * and full coverage of the pending set across runs — a row cannot be starved.
 */

import { describe, it, expect } from "vitest";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  ATTEMPT_FAIL_LIMIT,
  ATTEMPT_RETRY_HOURS,
  ATTEMPT_RETRY_MS,
  attemptKey,
  pruneAttemptLedger,
  readAttemptLedger,
  recordAttemptOutcome,
  selectPendingForRun,
  writeAttemptLedger,
  type AttemptLedger,
  type PendingEntry,
} from "../src/lib/shadow-attempts";

const FEED = "drift";
const DAY = 86_400_000;
/** Decision time helper: `dec("2026-10-04")`. */
const dec = (day: string) => Date.parse(`${day}T00:00:00.000Z`);
const entry = (marketId: string, outcome: string, decidedAt: number): PendingEntry => ({
  marketId,
  outcome,
  decidedAt,
});
const keys = (rows: PendingEntry[]) => rows.map((r) => `${r.marketId}|${r.outcome}`).sort();

/** Simulate one marker run's attempts: nothing resolves, everything is stamped. */
function runWalk(pending: PendingEntry[], ledger: AttemptLedger, limit: number, now: number) {
  const sel = selectPendingForRun(FEED, pending, ledger, { limit, now });
  recordAttemptOutcome(
    FEED,
    sel.selected.map((e) => ({ marketId: e.marketId, outcome: e.outcome, resolved: false })),
    ledger,
    now
  );
  return sel;
}

describe("shadow attempt rotation (card t_81d0a4cb)", () => {
  it("uses the documented defaults: 3 consecutive failures, 24h retry", () => {
    expect(ATTEMPT_FAIL_LIMIT).toBe(3);
    expect(ATTEMPT_RETRY_HOURS).toBe(24);
    expect(ATTEMPT_RETRY_MS).toBe(24 * 3_600_000);
  });

  it("a never-attempted candidate outranks an already-attempted one", () => {
    const ledger: AttemptLedger = {};
    const tried = entry("tried", "Yes", dec("2026-10-09"));
    const fresh = entry("fresh", "Yes", dec("2026-09-20"));
    // The attempted row is the more recent decision, and it is still second.
    recordAttemptOutcome(FEED, [{ marketId: "tried", outcome: "Yes", resolved: false }], ledger, dec("2026-10-09"));
    const sel = selectPendingForRun(FEED, [tried, fresh], ledger, { limit: 5, now: dec("2026-10-10") });
    expect(keys(sel.selected)).toEqual([`fresh|Yes`, `tried|Yes`]);
    expect(sel.neverAttempted).toBe(1);
  });

  it("never-attempted candidates are walked most-recently-decided first", () => {
    const pending = [entry("old", "Yes", dec("2026-09-17")), entry("new", "Yes", dec("2026-10-09")), entry("mid", "Under", dec("2026-10-01"))];
    const sel = selectPendingForRun(FEED, pending, {}, { limit: 1, now: dec("2026-10-10") });
    expect(keys(sel.selected)).toEqual([`new|Yes`]);
    expect(sel.eligible).toBe(3);
  });

  it("the attempted set rotates across consecutive runs — a failing head cannot hold the cap", () => {
    // 600 pending rows, every one decided a different day, cap 3.
    const pending = Array.from({ length: 600 }, (_, i) => entry(`m${i}`, "Yes", dec("2026-09-17") + i * 3_600_000));
    const ledger: AttemptLedger = {};
    const now = dec("2026-10-10");
    const first = runWalk(pending, ledger, 3, now);
    const second = runWalk(pending, ledger, 3, now + 3_600_000);
    expect(first.selected).toHaveLength(3);
    expect(second.selected).toHaveLength(3);
    // Disjoint sets: the run-2 walk is NOT the run-1 walk retried.
    const firstKeys = new Set(keys(first.selected));
    expect(keys(second.selected).filter((k) => firstKeys.has(k))).toEqual([]);
    // Both runs took the most recent decisions available at their turn.
    expect(keys(first.selected)).toEqual(keys(pending.slice(-3)));
    expect(keys(second.selected)).toEqual(keys(pending.slice(-6, -3)));
  });

  it("holds a row back only after N consecutive failures, then re-attempts it on the slow cadence", () => {
    const ledger: AttemptLedger = {};
    const stuck = entry("archived-head", "Yes", dec("2026-09-17"));
    const failures = [{ marketId: "archived-head", outcome: "Yes", resolved: false }];
    const t0 = dec("2026-10-10");
    // The hourly marker retries it until the failure limit is reached.
    for (let i = 0; i < ATTEMPT_FAIL_LIMIT; i++) {
      const now = t0 + i * 3_600_000;
      const sel = selectPendingForRun(FEED, [stuck], ledger, { limit: 5, now });
      expect(sel.selected.map((s) => s.marketId)).toEqual(["archived-head"]);
      recordAttemptOutcome(FEED, failures, ledger, now);
    }
    expect(ledger[attemptKey(FEED, "archived-head", "Yes")].consecutiveFailures).toBe(ATTEMPT_FAIL_LIMIT);

    // Inside the retry window it is excluded from the walk (and reported).
    const lastAttemptAt = t0 + (ATTEMPT_FAIL_LIMIT - 1) * 3_600_000;
    const held = selectPendingForRun(FEED, [stuck], ledger, { limit: 5, now: lastAttemptAt + 3_600_000 });
    expect(held.selected).toEqual([]);
    expect(held.heldBack).toBe(1);
    const justBefore = selectPendingForRun(FEED, [stuck], ledger, { limit: 5, now: lastAttemptAt + ATTEMPT_RETRY_MS - 1 });
    expect(justBefore.heldBack).toBe(1);

    // After the window it re-enters, ahead of a row attempted more recently.
    const recent = entry("recent", "Yes", dec("2026-10-09"));
    recordAttemptOutcome(FEED, [{ marketId: "recent", outcome: "Yes", resolved: false }], ledger, lastAttemptAt + 3_600_000);
    const retried = selectPendingForRun(FEED, [stuck, recent], ledger, { limit: 5, now: lastAttemptAt + ATTEMPT_RETRY_MS });
    expect(retried.selected.map((s) => s.marketId)).toEqual(["archived-head", "recent"]);
    expect(retried.heldBack).toBe(0);
  });

  it("covers the whole pending set across runs — no candidate is starved", () => {
    const pending = Array.from({ length: 10 }, (_, i) => entry(`m${i}`, "Yes", dec("2026-10-01") + i * DAY));
    const ledger: AttemptLedger = {};
    const seen = new Set<string>();
    for (let run = 0; run < 4; run++) {
      const sel = runWalk(pending, ledger, 3, dec("2026-10-10") + run * DAY);
      for (const s of sel.selected) seen.add(`${s.marketId}|${s.outcome}`);
    }
    expect([...seen].sort()).toEqual(keys(pending));
  });

  it("a resolved candidate leaves the ledger and pruning keeps the file to pending rows", () => {
    const ledger: AttemptLedger = {};
    recordAttemptOutcome(
      FEED,
      [
        { marketId: "won", outcome: "Yes", resolved: true },
        { marketId: "stuck", outcome: "Yes", resolved: false },
      ],
      ledger,
      dec("2026-10-10")
    );
    expect(ledger[attemptKey(FEED, "won", "Yes")]).toBeUndefined();
    expect(ledger[attemptKey(FEED, "stuck", "Yes")].consecutiveFailures).toBe(1);

    pruneAttemptLedger(ledger, [attemptKey(FEED, "other", "Yes")]);
    expect(Object.keys(ledger)).toEqual([]);
  });

  it("survives a restart: the stamp round-trips through the state file", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "shadow-attempts-"));
    const file = path.join(dir, "state.json");
    try {
      const pending = [entry("a", "Yes", dec("2026-09-17")), entry("b", "Under", dec("2026-10-09"))];
      const ledger: AttemptLedger = {};
      const t0 = dec("2026-10-10");
      const sel = selectPendingForRun(FEED, pending, ledger, { limit: 1, now: t0 });
      expect(keys(sel.selected)).toEqual(["b|Under"]);
      recordAttemptOutcome(
        FEED,
        sel.selected.map((e) => ({ marketId: e.marketId, outcome: e.outcome, resolved: false })),
        ledger,
        t0
      );
      writeAttemptLedger(ledger, file);

      // A NEW process reads the file back: same state, same next walk.
      const reloaded = readAttemptLedger(file);
      expect(reloaded).toEqual(ledger);
      const next = selectPendingForRun(FEED, pending, reloaded, { limit: 1, now: t0 + 3_600_000 });
      const withoutRestart = selectPendingForRun(FEED, pending, ledger, { limit: 1, now: t0 + 3_600_000 });
      expect(keys(next.selected)).toEqual(keys(withoutRestart.selected));
      expect(keys(next.selected)).toEqual(["a|Yes"]); // b was taken by the first run
      // No stray temp file from the atomic write.
      expect(fs.readdirSync(dir).sort()).toEqual(["state.json"]);
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });
});
