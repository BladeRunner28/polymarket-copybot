/**
 * c200-maker-fill-assumption — option (b): the intent-price instrument.
 *
 * Guards the properties that make the measurement trustworthy, and the ones that
 * keep it OUT of the trading path:
 *  1. the gap convention (entry - intent: negative = better than handed-in price)
 *     and the buckets that make "exactly -2c" separable from "no improvement"
 *     and from a genuine bug signature (entry WORSE than intent);
 *  2. legs with no stored intent are counted as unmeasured and contribute NO
 *     opinion to any gap statistic (the instrument has no backfill);
 *  3. linking matches the identity the sidecar's webhook carries, newest-first,
 *     and stamps ONLY the nullable shadow column — no price, size, PnL or status
 *     on the leg moves;
 *  4. neither writer throws: a shadow failure degrades to "no measurement".
 *
 * 3 and 4 drive the real SQL path against an isolated SQLite file (the ordering
 * and the write set are enforced by the queries, so a pure-function test would
 * prove nothing).
 */

import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const TEST_DB = path.join(__dirname, "test.db");
// DATABASE_URL is set to this file by vitest.setup.ts before any import.

import { prisma } from "../src/lib/db";
import {
  GAP_BUCKETS,
  MAKER_IMPROVEMENT,
  gapOf,
  median,
  recordFillIntent,
  renderFillVsIntent,
  stampIntentLink,
  summariseFillVsIntent,
  type IntentLeg,
} from "../src/lib/fill-intent";

const leg = (o: Partial<IntentLeg> = {}): IntentLeg => ({
  intentPrice: 0.5,
  entryPrice: 0.48,
  status: "open",
  openedAtMs: Date.now(),
  ...o,
});

describe("gapOf — the sign convention", () => {
  it("is negative when the booked entry is better than the price handed in", () => {
    expect(gapOf(0.5, 0.48)).toBeCloseTo(-0.02, 9);
  });
  it("is positive when the booked entry is worse (bug signature)", () => {
    expect(gapOf(0.5, 0.51)).toBeCloseTo(0.01, 9);
  });
  it("is zero when no improvement was booked", () => {
    expect(gapOf(0.33, 0.33)).toBe(0);
  });
  it("keeps float noise from reading as an improvement", () => {
    // 0.1 + 0.2 style noise must not land in the "worse" bucket.
    expect(gapOf(0.3, 0.1 + 0.2)).toBe(0);
  });
  it("returns null when the intent was never stored", () => {
    expect(gapOf(null, 0.42)).toBeNull();
  });
});

describe("summariseFillVsIntent — one population, honest denominators", () => {
  it("reports the modelled improvement when every leg carries it", () => {
    const s = summariseFillVsIntent([leg(), leg({ intentPrice: 0.2, entryPrice: 0.18 })]);
    expect(s.measured).toBe(2);
    expect(s.unmeasured).toBe(0);
    expect(s.shareExactImprovement).toBe(1);
    expect(s.meanGap).toBeCloseTo(-0.02, 9);
    expect(s.medianGap).toBeCloseTo(-0.02, 9);
  });

  it("counts legs without a stored intent as unmeasured and lets them vote on nothing", () => {
    const s = summariseFillVsIntent([
      leg(),
      leg({ intentPrice: null, entryPrice: 0.9 }),
      leg({ intentPrice: null, entryPrice: 0.02 }),
    ]);
    expect(s.measured).toBe(1);
    expect(s.unmeasured).toBe(2);
    expect(s.meanGap).toBeCloseTo(-0.02, 9); // the two NULL legs did not move it
    expect(s.shareExactImprovement).toBe(1);
  });

  it("separates no-improvement from improvement and from worse-than-intent", () => {
    const s = summariseFillVsIntent([
      leg(), // -0.02, the model
      leg({ intentPrice: 0.4, entryPrice: 0.4 }), // 0, no improvement
      leg({ intentPrice: 0.4, entryPrice: 0.42 }), // +0.02, unexpected
    ]);
    expect(s.measured).toBe(3);
    expect(s.shareExactImprovement).toBeCloseTo(1 / 3, 9);
    expect(s.shareNoImprovement).toBeCloseTo(1 / 3, 9);
    expect(s.shareWorseThanIntent).toBeCloseTo(1 / 3, 9);
    const worse = s.buckets.find((b) => b.label === "worse (bug signature)")!;
    expect(worse.n).toBe(1);
  });

  it("truncates the improvement on cheap tokens instead of claiming 2c", () => {
    // The sidecar clamps at 0.01, so a 0.02 intent books 0.01 — a real gap of
    // 1c, not the modelled 2c. It must NOT count as the exact improvement.
    const s = summariseFillVsIntent([leg({ intentPrice: 0.02, entryPrice: 0.01 })]);
    expect(s.meanGap).toBeCloseTo(-0.01, 9);
    expect(s.shareExactImprovement).toBe(0);
  });

  it("buckets every leg exactly once", () => {
    const legs = [leg(), leg({ intentPrice: 0.4, entryPrice: 0.4 }), leg({ intentPrice: 0.4, entryPrice: 0.45 })];
    const s = summariseFillVsIntent(legs);
    expect(s.buckets.reduce((a, b) => a + b.n, 0)).toBe(legs.length);
    expect(s.buckets.map((b) => b.label)).toEqual(GAP_BUCKETS.map((b) => b.label));
  });

  it("is empty-safe (no legs yet)", () => {
    const s = summariseFillVsIntent([]);
    expect(s.measured).toBe(0);
    expect(s.shareExactImprovement).toBe(0);
    expect(s.buckets.every((b) => b.n === 0)).toBe(true);
  });
});

describe("median", () => {
  it("handles even and odd counts without mutating the input", () => {
    const xs = [3, 1, 2];
    expect(median(xs)).toBe(2);
    expect(median([4, 1, 3, 2])).toBe(2.5);
    expect(xs).toEqual([3, 1, 2]);
    expect(median([])).toBe(0);
  });
});

describe("renderFillVsIntent", () => {
  it("always states the measured denominator and the shadow's standing", () => {
    const lines = renderFillVsIntent(summariseFillVsIntent([leg()]), "all legs");
    expect(lines[0]).toContain("measured legs 1");
    expect(lines[0]).toContain("all legs");
    expect(lines.join("\n")).toContain(`-$${MAKER_IMPROVEMENT.toFixed(2)}`);
    expect(lines.join("\n")).toContain("no backfill exists");
  });
});

// ---------------------------------------------------------------------------
// DB-backed: the write path itself
// ---------------------------------------------------------------------------

async function makeDecision(marketId: string) {
  // DecisionJournal.observedTradeId is a real FK — seed the observed trade first.
  const obs = await prisma.observedTrade.create({
    data: {
      walletAddress: "0xwallet",
      marketId,
      marketQuestion: "test market",
      outcome: "YES",
      side: "BUY",
      walletEntryPrice: 0.5,
      detectedPrice: 0.51,
      size: 100,
      timestamp: new Date(),
    },
  });
  return prisma.decisionJournal.create({
    data: {
      observedTradeId: obs.id,
      walletAddress: "0xwallet",
      marketId,
      decision: "paper_copy",
      copyScore: 80,
      confidence: 0.8,
    },
  });
}

describe("intent recording and linking (real SQL path)", () => {
  beforeAll(async () => {
    if (fs.existsSync(TEST_DB)) fs.unlinkSync(TEST_DB);
    execSync("npx prisma db push --skip-generate", {
      cwd: path.join(__dirname, ".."),
      env: { ...process.env, DATABASE_URL: `file:${TEST_DB}` },
      stdio: "pipe",
    });
    // ObservedTrade.walletAddress is a real FK — seed the wallet first.
    await prisma.walletProfile.create({
      data: { address: "0xwallet", label: "Test Wallet", status: "track" },
    });
  });

  afterAll(async () => {
    await prisma.$disconnect();
    if (fs.existsSync(TEST_DB)) fs.unlinkSync(TEST_DB);
  });

  it("records the intent price it was handed, not the booked one", async () => {
    const d = await makeDecision("mkt-record");
    const id = await recordFillIntent({
      decisionJournalId: d.id,
      botId: "BANKROLL_200",
      venue: "Polymarket",
      marketId: "mkt-record",
      outcome: "YES",
      side: "BUY",
      intentPrice: 0.61,
      sizeUsd: 12,
    });
    expect(id).toBeTruthy();
    const row = await prisma.fillIntent.findUnique({ where: { id: id! } });
    expect(row?.intentPrice).toBe(0.61);
    expect(row?.paperTradeId).toBeNull();
  });

  it("ignores lanes that book their own price (STANDARD)", async () => {
    const d = await makeDecision("mkt-standard");
    const id = await recordFillIntent({
      decisionJournalId: d.id,
      botId: "STANDARD",
      venue: "Polymarket",
      marketId: "mkt-standard",
      outcome: "YES",
      side: "BUY",
      intentPrice: 0.4,
      sizeUsd: 10,
    });
    expect(id).toBeNull();
  });

  it("stamps the leg and moves NOTHING else on it", async () => {
    const d = await makeDecision("mkt-link");
    await recordFillIntent({
      decisionJournalId: d.id,
      botId: "BANKROLL_200",
      venue: "Polymarket",
      marketId: "mkt-link",
      outcome: "YES",
      side: "BUY",
      intentPrice: 0.52,
      sizeUsd: 15,
    });
    const before = await prisma.paperTrade.create({
      data: {
        botId: "BANKROLL_200",
        venue: "Polymarket",
        decisionJournalId: d.id,
        walletAddress: "0xwallet",
        marketId: "mkt-link",
        outcome: "YES",
        side: "BUY",
        entryPrice: 0.5, // what the sidecar booked: intent - 0.02
        currentPrice: 0.5,
        simulatedPositionSize: 15,
      },
    });

    const stamped = await stampIntentLink({
      paperTradeId: before.id,
      decisionJournalId: d.id,
      marketId: "mkt-link",
      outcome: "YES",
      side: "BUY",
      venue: "Polymarket",
      botId: "BANKROLL_200",
    });
    expect(stamped).toBe(0.52);

    const after = await prisma.paperTrade.findUnique({ where: { id: before.id } });
    expect(after?.intentPrice).toBe(0.52);
    // The only field the shadow moves is the nullable shadow column.
    const FIELDS = [
      "entryPrice",
      "currentPrice",
      "simulatedPositionSize",
      "unrealizedPnl",
      "realizedPnl",
      "status",
      "botId",
      "venue",
      "marketId",
      "outcome",
      "side",
      "isDemo",
      "openedAt",
      "closedAt",
      "resolvedAt",
    ] as const;
    for (const f of FIELDS) {
      expect((after as any)[f]).toEqual((before as any)[f]);
    }

    const linked = await prisma.fillIntent.findFirst({ where: { decisionJournalId: d.id } });
    expect(linked?.paperTradeId).toBe(before.id);
    expect(linked?.linkedAt).toBeTruthy();
    expect(linked?.intentPrice).toBe(0.52);
  });

  it("links the NEWEST unlinked intent when a decision dispatched more than once", async () => {
    const d = await makeDecision("mkt-twice");
    for (const p of [0.30, 0.44]) {
      await recordFillIntent({
        decisionJournalId: d.id,
        botId: "BANKROLL_200",
        venue: "Polymarket",
        marketId: "mkt-twice",
        outcome: "NO",
        side: "BUY",
        intentPrice: p,
        sizeUsd: 10,
      });
      await new Promise((r) => setTimeout(r, 5)); // distinct dispatchedAt
    }
    const trade = await prisma.paperTrade.create({
      data: {
        botId: "BANKROLL_200",
        decisionJournalId: d.id,
        walletAddress: "0xw",
        marketId: "mkt-twice",
        outcome: "NO",
        side: "BUY",
        entryPrice: 0.42,
        currentPrice: 0.42,
        simulatedPositionSize: 10,
      },
    });
    const stamped = await stampIntentLink({
      paperTradeId: trade.id,
      decisionJournalId: d.id,
      marketId: "mkt-twice",
      outcome: "NO",
      side: "BUY",
      venue: "Polymarket",
      botId: "BANKROLL_200",
    });
    expect(stamped).toBe(0.44);
    expect(await prisma.fillIntent.count({ where: { decisionJournalId: d.id, paperTradeId: null } })).toBe(1);
  });

  it("degrades to null instead of throwing when the leg does not exist", async () => {
    const d = await makeDecision("mkt-missing");
    await recordFillIntent({
      decisionJournalId: d.id,
      botId: "BANKROLL_200",
      venue: "Polymarket",
      marketId: "mkt-missing",
      outcome: "YES",
      side: "BUY",
      intentPrice: 0.5,
      sizeUsd: 10,
    });
    await expect(
      stampIntentLink({
        paperTradeId: "does-not-exist",
        decisionJournalId: d.id,
        marketId: "mkt-missing",
        outcome: "YES",
        side: "BUY",
        venue: "Polymarket",
        botId: "BANKROLL_200",
      })
    ).resolves.toBeNull();
  });

  it("refuses a non-finite intent price rather than storing a lie", async () => {
    const d = await makeDecision("mkt-bad-price");
    const id = await recordFillIntent({
      decisionJournalId: d.id,
      botId: "BANKROLL_200",
      venue: "Polymarket",
      marketId: "mkt-bad-price",
      outcome: "YES",
      side: "BUY",
      intentPrice: Number.NaN,
      sizeUsd: 10,
    });
    expect(id).toBeNull();
  });
});
