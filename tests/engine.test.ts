/**
 * DB-backed tests: paper trade creation, hourly PnL updates, rule versioning,
 * automatic rule changes, benchmark comparison. Uses an isolated SQLite file.
 */

import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const TEST_DB = path.join(__dirname, "test.db");
// DATABASE_URL is set to this file by vitest.setup.ts before any import.

// The Prisma client binds to the test DB via vitest.setup.ts.
import { prisma } from "../src/lib/db";
import { openPaperTrade, updatePaperTradePrice, resolvePaperTrade, computePnl } from "../src/lib/paper";
import { getActiveRules, applyRuleChanges, DEFAULT_RULES } from "../src/lib/rules";
import { proposeRuleChanges } from "../src/lib/rule-updater";
import { computeBenchmarks } from "../src/lib/benchmarks";

async function makeDecision(decision = "paper_copy", outcome = "YES", detectedPrice = 0.5) {
  const observed = await prisma.observedTrade.create({
    data: {
      walletAddress: "0xtestwallet",
      marketId: `test-market-${Math.random().toString(36).slice(2)}`,
      marketQuestion: "Test?",
      outcome,
      side: "BUY",
      walletEntryPrice: 0.48,
      detectedPrice,
      size: 100,
      timestamp: new Date(),
    },
  });
  return prisma.decisionJournal.create({
    data: {
      observedTradeId: observed.id,
      walletAddress: "0xtestwallet",
      marketId: observed.marketId,
      decision,
      copyScore: 70,
      confidence: 0.7,
    },
  });
}

beforeAll(async () => {
  if (fs.existsSync(TEST_DB)) fs.unlinkSync(TEST_DB);
  execSync("npx prisma db push --skip-generate", {
    cwd: path.join(__dirname, ".."),
    env: { ...process.env, DATABASE_URL: `file:${TEST_DB}` },
    stdio: "pipe",
  });
  await prisma.walletProfile.create({
    data: { address: "0xtestwallet", label: "Test Wallet", status: "track" },
  });
});

afterAll(async () => {
  await prisma.$disconnect();
  if (fs.existsSync(TEST_DB)) fs.unlinkSync(TEST_DB);
});

describe("paper trade creation", () => {
  it("creates an open paper trade with clamped size", async () => {
    const d = await makeDecision();
    const t = await openPaperTrade({
      decisionJournalId: d.id,
      walletAddress: "0xtestwallet",
      marketId: d.marketId,
      outcome: "YES",
      side: "BUY",
      entryPrice: 0.5,
      simulatedPositionSize: 999, // absurd — must clamp to 20
    });
    expect(t.status).toBe("open");
    expect(t.simulatedPositionSize).toBeLessThanOrEqual(20);
    expect(t.simulatedPositionSize).toBeGreaterThanOrEqual(0.25);
    expect(t.unrealizedPnl).toBe(0);
  });
});

describe("hourly PnL updates", () => {
  it("updates PnL and writes a snapshot", async () => {
    const d = await makeDecision();
    const t = await openPaperTrade({
      decisionJournalId: d.id,
      walletAddress: "0xtestwallet",
      marketId: d.marketId,
      outcome: "YES",
      side: "BUY",
      entryPrice: 0.5,
      simulatedPositionSize: 10,
    });
    const updated = await updatePaperTradePrice(t.id, 0.6);
    // $10 at 0.5 = 20 shares; at 0.6 -> $12 -> +$2
    expect(updated.unrealizedPnl).toBeCloseTo(2, 1);
    const snaps = await prisma.pnlSnapshot.findMany({ where: { paperTradeId: t.id } });
    expect(snaps.length).toBe(1);
    expect(snaps[0].price).toBe(0.6);
  });

  it("computePnl handles wins and losses correctly", () => {
    expect(computePnl(0.5, 1, 10)).toBeCloseTo(10, 2); // win doubles at 0.5
    expect(computePnl(0.5, 0, 10)).toBeCloseTo(-10, 2); // loss loses stake
    expect(computePnl(0.25, 1, 10)).toBeCloseTo(30, 2); // 4x at 0.25
  });

  it("resolves a paper trade with realized PnL", async () => {
    const d = await makeDecision();
    const t = await openPaperTrade({
      decisionJournalId: d.id,
      walletAddress: "0xtestwallet",
      marketId: d.marketId,
      outcome: "YES",
      side: "BUY",
      entryPrice: 0.5,
      simulatedPositionSize: 10,
    });
    const resolved = await resolvePaperTrade(t.id, true);
    expect(resolved.status).toBe("resolved");
    expect(resolved.realizedPnl).toBeCloseTo(10, 1);
    expect(resolved.resolvedAt).not.toBeNull();
  });
});

describe("rule versioning", () => {
  it("bootstraps v1 with defaults", async () => {
    const { rules, version } = await getActiveRules();
    expect(version).toBeGreaterThanOrEqual(1);
    expect(rules.maxSpread).toBeGreaterThan(0);
  });

  it("applies changes as a new version with full audit trail", async () => {
    const before = await getActiveRules();
    const result = await applyRuleChanges([
      {
        field: "maxSpread",
        newValue: 0.03,
        reason: "test tightening",
        evidence: "test evidence",
      },
    ]);
    expect(result!.newVersion).toBe(before.version + 1);

    const after = await getActiveRules();
    expect(after.rules.maxSpread).toBe(0.03);
    expect(after.version).toBe(before.version + 1);

    const change = await prisma.ruleChange.findFirst({ orderBy: { createdAt: "desc" } });
    expect(change!.reason).toContain("test tightening");
    expect(JSON.parse(change!.beforeJson).maxSpread).toBe(before.rules.maxSpread);
    expect(JSON.parse(change!.afterJson).maxSpread).toBe(0.03);

    // exactly one active ruleset
    const active = await prisma.ruleSet.findMany({ where: { active: true } });
    expect(active.length).toBe(1);
  });
});

describe("automatic rule changes", () => {
  it("does not change rules without enough evidence", () => {
    const proposals = proposeRuleChanges([], DEFAULT_RULES);
    expect(proposals).toEqual([]);
  });

  it("tightens maxSpread when wide-spread trades lose", () => {
    const samples = [
      // wide-spread losers
      ...Array.from({ length: 4 }, () => ({ pnl: -8, spread: 0.045, liquidity: 50_000, drift: 0.01, walletScore: 70 })),
      // tight-spread winners
      ...Array.from({ length: 4 }, () => ({ pnl: 6, spread: 0.01, liquidity: 50_000, drift: 0.01, walletScore: 70 })),
    ];
    const proposals = proposeRuleChanges(samples, DEFAULT_RULES);
    const spreadChange = proposals.find((p) => p.field === "maxSpread");
    expect(spreadChange).toBeDefined();
    expect(spreadChange!.newValue).toBeLessThan(DEFAULT_RULES.maxSpread);
    expect(spreadChange!.evidence).toContain("avg PnL");
  });

  it("raises minLiquidity when low-liquidity trades lose", () => {
    const samples = [
      ...Array.from({ length: 4 }, () => ({ pnl: -7, spread: 0.01, liquidity: 6000, drift: 0.01, walletScore: 70 })),
      ...Array.from({ length: 4 }, () => ({ pnl: 5, spread: 0.01, liquidity: 80_000, drift: 0.01, walletScore: 70 })),
    ];
    const proposals = proposeRuleChanges(samples, DEFAULT_RULES);
    const liqChange = proposals.find((p) => p.field === "minLiquidity");
    expect(liqChange).toBeDefined();
    expect(liqChange!.newValue).toBeGreaterThan(DEFAULT_RULES.minLiquidity);
  });

  it("reduces maxPriceDrift when late entries lose", () => {
    const samples = [
      ...Array.from({ length: 4 }, () => ({ pnl: -9, spread: 0.01, liquidity: 50_000, drift: 0.07, walletScore: 70 })),
      ...Array.from({ length: 4 }, () => ({ pnl: 4, spread: 0.01, liquidity: 50_000, drift: 0.01, walletScore: 70 })),
    ];
    const proposals = proposeRuleChanges(samples, DEFAULT_RULES);
    const driftChange = proposals.find((p) => p.field === "maxPriceDrift");
    expect(driftChange).toBeDefined();
    expect(driftChange!.newValue).toBeLessThan(DEFAULT_RULES.maxPriceDrift);
  });

  it("raises the copy bar during losing streaks", () => {
    const samples = Array.from({ length: 8 }, () => ({ pnl: -5, spread: 0.01, liquidity: 50_000, drift: 0.01, walletScore: 70 }));
    const proposals = proposeRuleChanges(samples, DEFAULT_RULES);
    const scoreChange = proposals.find((p) => p.field === "minCopyScore");
    expect(scoreChange).toBeDefined();
    expect(scoreChange!.newValue).toBeGreaterThan(DEFAULT_RULES.minCopyScore);
  });
});

describe("benchmark comparison", () => {
  it("separates bot-filtered vs blind copy vs watchlist vs skipped", async () => {
    // A skipped decision whose market resolved against the wallet = avoided loser.
    const skipDecision = await makeDecision("skip", "YES", 0.5);
    await prisma.outcomeReview.create({
      data: {
        decisionJournalId: skipDecision.id,
        finalOutcome: "NO", // wallet bought YES, market resolved NO
        simulatedPnl: -10,
        wasDecisionGood: true,
        lessonsJson: JSON.stringify(["avoided loser"]),
      },
    });
    // A watchlist decision whose market resolved with the wallet = missed winner.
    const watchDecision = await makeDecision("watchlist", "YES", 0.5);
    await prisma.outcomeReview.create({
      data: {
        decisionJournalId: watchDecision.id,
        finalOutcome: "YES",
        simulatedPnl: 10,
        wasDecisionGood: false,
        lessonsJson: JSON.stringify(["missed winner"]),
      },
    });

    const bench = await computeBenchmarks();
    expect(bench.avoidedLosers).toBeGreaterThanOrEqual(1);
    expect(bench.missedWinners).toBeGreaterThanOrEqual(1);
    expect(bench.botFiltered.label).toContain("Bot");
    expect(bench.blindCopy.count).toBeGreaterThanOrEqual(
      bench.botFiltered.count
    );
  });
});
