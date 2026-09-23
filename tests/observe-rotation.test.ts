/**
 * v62 (tuning review #34 rec 1, user-approved 2026-09-23) — the OBSERVE sweep
 * ROTATES instead of re-taking the newest demotions.
 *
 * Baseline it fixes (measured 2026-09-23): `observeOnlyWallets()` ordered by
 * `lastTrackedAt desc` under a 40-wallet cap, so all 40 awards went to wallets
 * demoted in the last ~4 h while 108 of 175 eligible wallets got zero
 * observation rows in 24 h, and a deferred wallet (lastTrackedAt never
 * refreshed) waited forever.
 *
 * These tests drive the real SQL path against an isolated SQLite file — the
 * ordering is enforced by the query, so a pure-function comparator test would
 * prove nothing.
 */

import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const TEST_DB = path.join(__dirname, "test.db");
// DATABASE_URL is set to this file by vitest.setup.ts before any import.

import { prisma } from "../src/lib/db";
import {
  MAX_OBSERVE,
  observeEligibleCount,
  observeOnlyWallets,
  stampObserved,
} from "../src/lib/wallet-universe";

const hoursAgo = (h: number) => new Date(Date.now() - h * 3_600_000);

type Seed = {
  address: string;
  status?: string;
  lastTrackedAt: Date | null;
  lastObservedAt?: Date | null;
  isDemo?: boolean;
};

const seed = (rows: Seed[]) =>
  Promise.all(
    rows.map((r) =>
      prisma.walletProfile.create({
        data: {
          address: r.address,
          status: r.status ?? "watch",
          lastTrackedAt: r.lastTrackedAt,
          lastObservedAt: r.lastObservedAt ?? null,
          isDemo: r.isDemo ?? false,
        },
      })
    )
  );

const addresses = (rows: { address: string }[]) => rows.map((r) => r.address);

beforeAll(async () => {
  if (fs.existsSync(TEST_DB)) fs.unlinkSync(TEST_DB);
  execSync("npx prisma db push --skip-generate", {
    cwd: path.join(__dirname, ".."),
    env: { ...process.env, DATABASE_URL: `file:${TEST_DB}` },
    stdio: "pipe",
  });
  await seed([
    // The two NEWEST demotions — under the old `lastTrackedAt desc` ordering
    // these held the first two awards in every cycle, forever.
    { address: "0xnew-b", lastTrackedAt: hoursAgo(0.2) },
    { address: "0xnew-a", lastTrackedAt: hoursAgo(1) },
    // Older demotions that the old ordering could never reach.
    { address: "0xstale-6h", lastTrackedAt: hoursAgo(48), lastObservedAt: hoursAgo(6) },
    { address: "0xstale-30m", lastTrackedAt: hoursAgo(72), lastObservedAt: hoursAgo(0.5) },
    // Must never enter the OBSERVE set:
    { address: "0xtracked", status: "track", lastTrackedAt: hoursAgo(0.1) },
    { address: "0xexpired", lastTrackedAt: hoursAgo(24 * 8) },
    { address: "0xdemo", lastTrackedAt: hoursAgo(1), isDemo: true },
  ]);
});

afterAll(async () => {
  await prisma.$disconnect();
  if (fs.existsSync(TEST_DB)) fs.unlinkSync(TEST_DB);
});

describe("observeOnlyWallets (v62 rotation)", () => {
  it("lists only demoted live wallets inside the trailing window", async () => {
    expect(await observeEligibleCount()).toBe(4);
    const rows = await observeOnlyWallets();
    expect(addresses(rows).sort()).toEqual(
      ["0xnew-a", "0xnew-b", "0xstale-30m", "0xstale-6h"].sort()
    );
    expect(addresses(rows)).not.toContain("0xtracked");
    expect(addresses(rows)).not.toContain("0xexpired");
    expect(addresses(rows)).not.toContain("0xdemo");
  });

  it("takes never-observed wallets first, then the least recently observed", async () => {
    const rows = await observeOnlyWallets();
    // NULLs first (never observed), address asc as the tiebreak; then oldest stamp.
    expect(addresses(rows)).toEqual([
      "0xnew-a",
      "0xnew-b",
      "0xstale-6h",
      "0xstale-30m",
    ]);
  });

  it("rotates after a stamped sweep — the newest demotion goes LAST, not first", async () => {
    // The sweep covered the two never-observed wallets.
    expect(await stampObserved(["0xnew-a", "0xnew-b"])).toBe(2);
    const next = await observeOnlyWallets();
    expect(addresses(next)).toEqual([
      "0xstale-6h",
      "0xstale-30m",
      "0xnew-a",
      "0xnew-b",
    ]);
    // Nothing leaves the pool: the window still lists the same 4.
    expect(await observeEligibleCount()).toBe(4);
  });

  it("walks the whole pool in ~ceil(pool / MAX_OBSERVE) cycles", async () => {
    // 41 extra eligible wallets, all never observed (worst case for coverage).
    await seed(
      Array.from({ length: 41 }, (_, i) => ({
        address: `0xfiller-${String(i).padStart(2, "0")}`,
        lastTrackedAt: hoursAgo(2),
      }))
    );
    const pool = await observeEligibleCount();
    expect(pool).toBe(45);
    const firstCycle = await observeOnlyWallets();
    expect(firstCycle.length).toBe(MAX_OBSERVE); // capped
    // Sweep every cycle, in the order the monitor would, and count distinct
    // wallets covered — the whole pool must appear within ceil(pool / cap) cycles.
    const covered = new Set<string>();
    for (let cycle = 0; cycle < Math.ceil(pool / MAX_OBSERVE); cycle++) {
      const rows = await observeOnlyWallets();
      expect(rows.length).toBeGreaterThan(0);
      addresses(rows).forEach((a) => covered.add(a));
      await stampObserved(addresses(rows));
    }
    expect(covered.size).toBe(pool);
  });
});
