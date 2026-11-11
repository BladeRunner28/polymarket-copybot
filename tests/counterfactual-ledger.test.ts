/**
 * 2026-10-29 (card phil-counterfactual-ledger-primitive) — ONE write path and ONE
 * read for every declined-decision counterfactual.
 *
 * What these pin:
 *   (a) the fill rule is one function, and it refuses to manufacture a windfall
 *       from a non-executable entry;
 *   (b) the primitive bakes in NO lane policy: the same rows read by the drift lane
 *       and the confidence lane produce the SAME totals, and the dust floor only
 *       applies when the caller asks for it — which is exactly the divergence that
 *       motivated the card (drift got a floor on 2026-09-19, lowconf did not);
 *   (c) the declared FILL MODEL is the only thing that may move a lane's money:
 *       a `would_be_size` lane prices its own blocked size, a `fixed_clip` lane
 *       prices a constant;
 *   (d) the canonical row refuses ill-formed writes and cannot be given two
 *       meanings for one canonical field;
 *   (e) the pre-registered read (phil trial A) is fed by ONE adapter, so all lanes
 *       are read identically (and an era-less feed stays UNVERIFIABLE).
 */

import { describe, it, expect } from "vitest";
import * as fs from "fs";
import * as os from "os";
import { join } from "path";
import {
  appendCounterfactualCandidate,
  appendCounterfactualResolve,
  buildCounterfactualRow,
  counterfactualPnl,
  dedupeSignals,
  groupStats,
  readLedger,
  settledDustRead,
  summarizeLedger,
  toShadowReadRows,
} from "../src/lib/counterfactual-ledger";
import { summarizeDrift } from "../src/lib/shadow-drift";
import {
  summarizeLowConf,
  LOWCONF_DUST_MIN_ENTRY,
  LOWCONF_BANNED_TAIL_MAX,
} from "../src/lib/shadow-lowconf";
import { summarizeWalletCap } from "../src/lib/shadow-wallet-cap";
import { evaluateShadowRead } from "../src/lib/shadow-read";

const RECENT = (minutesAgo: number) => new Date(Date.now() - minutesAgo * 60_000).toISOString();

const CAND = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
  ts: RECENT(30),
  type: "candidate",
  marketId: "m1",
  outcome: "YES",
  wallet: "w1",
  currentPrice: 0.5,
  stakeUsd: 10,
  rawConfidence: 0.3,
  ...over,
});

const RESOLVE = (marketId: string, outcome: string, value: number): Record<string, unknown> => ({
  ts: RECENT(1),
  type: "resolve",
  marketId,
  outcome,
  value,
});

describe("counterfactualPnl — the ONE fill rule", () => {
  it("pays (settled - entry) / entry × stake for a winner and loses the notional for a loser", () => {
    expect(counterfactualPnl(0.5, 1, 10)).toBeCloseTo(10, 10);
    expect(counterfactualPnl(0.25, 1, 10)).toBeCloseTo(30, 10);
    expect(counterfactualPnl(0.5, 0, 10)).toBeCloseTo(-10, 10);
  });

  it("returns 0 for a non-executable entry instead of a 2000x windfall", () => {
    expect(counterfactualPnl(0, 1, 10)).toBe(0);
    expect(counterfactualPnl(-0.01, 1, 10)).toBe(0);
  });
});

describe("canonical row — one write shape, no lane policy inside", () => {
  const base = {
    lane: "late_drift_gate",
    file: "/dev/null",
    marketId: "m1",
    outcome: "YES",
    side: "BUY",
    walletAddress: "w1",
    entryPrice: 0.42,
    fill: { kind: "fixed_clip" as const, stakeUsd: 10 },
  };

  it("records identity, entry price, stake and the declared fill model", () => {
    const row = buildCounterfactualRow({ ...base, extras: { source: "late_drift_gate" } });
    expect(row.type).toBe("candidate");
    expect(row.lane).toBe("late_drift_gate");
    expect(row.entryPrice).toBe(0.42);
    expect(row.stakeUsd).toBe(10);
    expect(row.fillKind).toBe("fixed_clip");
    expect(row.wallet).toBe("w1");
    expect(row.source).toBe("late_drift_gate");
    // No threshold, band, dust floor or lane stake is invented at write time.
    expect(row).not.toHaveProperty("dustMinEntry");
    expect(row).not.toHaveProperty("maxDrift");
  });

  it("refuses an ill-formed stake or entry rather than writing an unpriceable row", () => {
    expect(() => buildCounterfactualRow({ ...base, fill: { kind: "fixed_clip", stakeUsd: 0 } })).toThrow(/stakeUsd/);
    expect(() => buildCounterfactualRow({ ...base, entryPrice: Number.NaN })).toThrow(/entryPrice/);
  });

  it("still records a zero entry (non-executable) instead of dropping the decision", () => {
    const row = buildCounterfactualRow({ ...base, entryPrice: 0 });
    expect(row.entryPrice).toBe(0);
    expect(counterfactualPnl(0, 1, 10)).toBe(0);
  });

  it("refuses an extra that would redefine a canonical field", () => {
    expect(() =>
      buildCounterfactualRow({ ...base, extras: { stakeUsd: 999, fillKind: "would_be_size" } })
    ).toThrow(/collides/);
  });

  it("refuses a settlement that is not a binary token outcome", () => {
    expect(() => appendCounterfactualResolve("/dev/null", "m1", "YES", 0.5)).toThrow(/0 or 1/);
  });

  it("round-trips through the append-only feed and prices end to end", () => {
    const dir = fs.mkdtempSync(join(os.tmpdir(), "cf-ledger-"));
    const file = join(dir, "feed.jsonl");
    appendCounterfactualCandidate({
      ...base,
      file,
      reason: "price drifted 0.0100 > max 0.004 (too late)",
    });
    appendCounterfactualResolve(file, "m1", "YES", 1);
    const rows = readLedger(file);
    expect(rows).toHaveLength(2);
    const s = summarizeLedger(rows);
    expect(s.marked).toBe(1);
    expect(s.wouldHavePnl).toBeCloseTo((1 - 0.42) / 0.42 * 10, 2);
    // One row, one meaning: the written stake is the one the read prices.
    expect(rows[0].stakeUsd).toBe(10);
    fs.rmSync(dir, { recursive: true, force: true });
  });
});

describe("summarizeLedger — one read, so lanes cannot drift apart", () => {
  // m1 polled twice (same signal), m2 once, m3 is a dust entry, m4 never settles.
  const rows = [
    CAND({ ts: RECENT(50), marketId: "m1", currentPrice: 0.5 }),
    CAND({ ts: RECENT(40), marketId: "m1", currentPrice: 0.6 }),
    CAND({ ts: RECENT(30), marketId: "m2", outcome: "NO", wallet: "w2", currentPrice: 0.4 }),
    CAND({ ts: RECENT(20), marketId: "m3", wallet: "w3", currentPrice: 0.02 }),
    CAND({ ts: RECENT(10), marketId: "m4", wallet: "w4", currentPrice: 0.5 }),
    RESOLVE("m1", "YES", 1),
    RESOLVE("m2", "NO", 0),
    RESOLVE("m3", "YES", 1),
  ];

  it("prices the row-level ticket stream and the per-signal book from the same rows", () => {
    const s = summarizeLedger(rows);
    expect(s.candidates).toBe(5);
    expect(s.marked).toBe(4); // m1 twice, m2, m3
    expect(s.awaitingResolution).toBe(1); // m4
    // row-level: +10, +6.6667, -10, +490 = +496.67
    expect(s.wouldHavePnl).toBeCloseTo(496.67, 2);
    // per signal: earliest poll per (market|outcome|wallet): m1 @0.5, m2 @0.4, m3 @0.02
    expect(s.signals).toBe(4); // includes the unsettled m4
    expect(s.signalsSettled).toBe(3);
    expect(s.perOpportunity.wouldHavePnlPerSignal).toBeCloseTo(490 + 10 - 10, 2);
    expect(s.perOpportunity.markets).toBe(3);
  });

  it("applies the dust floor only when asked, and reports what it excluded", () => {
    const noFloor = summarizeLedger(rows);
    expect(noFloor.exDust.minEntryPrice).toBeNull();
    expect(noFloor.exDust.excluded).toBe(0);
    expect(noFloor.exDust.avgPnlPerTrade).toBe(noFloor.avgPnlPerTrade);

    const floored = summarizeLedger(rows, { dustMinEntry: 0.1 });
    expect(floored.exDust.excluded).toBe(1); // the 0.02 entry
    expect(floored.exDust.marked).toBe(3);
    // (+10 + 6.6667 - 10) / 3
    expect(floored.exDust.avgPnlPerTrade).toBeCloseTo(2.22, 2);
    // the per-signal basis carries the same floor
    expect(floored.perSignal.dustExcluded).toBe(1);
    expect(floored.perSignal.exDustMarked).toBe(2);
  });

  it("the drift lane and the confidence lane read identical rows identically", () => {
    const drift = summarizeDrift(rows);
    const low = summarizeLowConf(rows);
    expect(low.marked).toBe(drift.marked);
    expect(low.wins).toBe(drift.wins);
    expect(low.winRate).toBe(drift.winRate);
    expect(low.wouldHavePnl).toBe(drift.wouldHavePnl);
    expect(low.avgPnlPerTrade).toBe(drift.avgPnlPerTrade);
    // The ex-dust read the confidence lane did not have before the port now matches
    // the drift lane's floor exactly — the bug class this card is about.
    expect(low.dust.avgPnlPerTrade).toBe(drift.avgPnlPerTradeExDust);
    expect(low.dust.rowsExcluded).toBe(drift.dustExcluded);
    expect(low.dust.wouldHavePnl).toBe(
      Math.round((drift.wouldHavePnl - low.dust.rowPnlExcluded) * 100) / 100
    );
  });

  it("the declared fill model is the only thing that moves a lane's money", () => {
    const sized = [
      CAND({ marketId: "m1", currentPrice: 0.5, sizeUsd: 25, stakeUsd: undefined }),
      RESOLVE("m1", "YES", 1),
    ];
    const wallet = summarizeWalletCap(sized);
    expect(wallet.wouldHavePnl).toBeCloseTo(25, 6); // (1 - 0.5)/0.5 × $25 blocked
    expect(wallet.stakedUsd).toBeCloseTo(25, 6);
  });

  it("dedupes on marketId|outcome|wallet and keeps the earliest poll", () => {
    const sig = dedupeSignals(rows);
    expect(sig.get("m1|YES|w1")?.currentPrice).toBe(0.5);
  });

  it("groups by band with settled-only money and all-candidate counts", () => {
    const g = groupStats(rows, (c) => (Number(c.currentPrice) < 0.2 ? "0-0.2" : "0.4-0.6"));
    expect(g["0-0.2"]).toEqual({ n: 1, marked: 1, wouldHavePnl: 490 });
    expect(g["0.4-0.6"]).toEqual({ n: 4, marked: 3, wouldHavePnl: 6.67 });
  });
});

describe("pre-registered read (phil trial A) — one adapter for every lane", () => {
  const rows = [
    CAND({ marketId: "m1", currentPrice: 0.5 }),
    CAND({ marketId: "m2", wallet: "w2", currentPrice: 0.5 }),
    RESOLVE("m1", "YES", 1),
    RESOLVE("m2", "YES", 0),
  ];

  it("emits one ShadowReadRow per SETTLED decision, clustered by market", () => {
    const readRows = toShadowReadRows(rows);
    expect(readRows).toHaveLength(2);
    expect(readRows[0].cluster).toBe("m1");
    expect(readRows[0].ret).toBeCloseTo(1, 10); // +$10 on $10 staked
    expect(readRows[1].ret).toBeCloseTo(-1, 10);
    expect(readRows[0].era).toBeNull();
  });

  it("reports an era-less feed as UNVERIFIABLE rather than passing it", () => {
    const res = evaluateShadowRead(toShadowReadRows(rows), { minBets: 1, minSettledPerArm: 1 });
    expect(res.bets).toBe(2);
    expect(res.criterionD).toBeNull();
    expect(res.reasons.some((r) => r.includes("UNVERIFIABLE"))).toBe(true);
  });

  it("honours the same bet filter the lane summary uses", () => {
    const admits = rows.map((r) =>
      r.type === "candidate" ? { ...r, wouldAdmit: r.marketId === "m1" } : r
    );
    expect(toShadowReadRows(admits, { betFilter: (r) => r.wouldAdmit === true })).toHaveLength(1);
  });
});

describe("settledDustRead — the floor, the level basis and the concentration rule live once", () => {
  // m1 dust (0.02, settles 1), m2 dust (0.04, settles 1), m3 solid (0.5, settles 1),
  // m4 solid (0.5, settles 0), m5 never settles. m1 is polled twice, later and dearer.
  const rows = [
    CAND({ ts: RECENT(90), marketId: "m1", currentPrice: 0.02 }),
    CAND({ ts: RECENT(80), marketId: "m1", currentPrice: 0.10 }),
    CAND({ ts: RECENT(70), marketId: "m2", wallet: "w2", currentPrice: 0.04 }),
    CAND({ ts: RECENT(60), marketId: "m3", wallet: "w3", currentPrice: 0.5 }),
    CAND({ ts: RECENT(50), marketId: "m4", wallet: "w4", currentPrice: 0.5 }),
    CAND({ ts: RECENT(40), marketId: "m5", wallet: "w5", currentPrice: 0.5 }),
    RESOLVE("m1", "YES", 1),
    RESOLVE("m2", "YES", 1),
    RESOLVE("m3", "YES", 1),
    RESOLVE("m4", "YES", 0),
  ];

  it("keys the level basis on the earliest SETTLED poll and prices the dust out of all three levels", () => {
    const d = settledDustRead(rows, {
      dustMinEntry: 0.1,
      bannedTailMax: 0.05,
      defaultStakeUsd: 10,
    });
    // Row level: m1@0.02 (+490), m1@0.10 (+90), m2@0.04 (+240), m3 (+10), m4 (-10).
    expect(d.row.marked).toBe(5);
    expect(d.row.wouldHavePnl).toBeCloseTo(820, 6);
    expect(d.row.dustExcluded).toBe(2);
    expect(d.row.dustWouldHavePnl).toBeCloseTo(730, 6);
    expect(d.row.exDustWouldHavePnl).toBeCloseTo(90, 6);
    expect(d.row.exDustMarked).toBe(3);
    expect(d.row.exDustAvgPnlPerTrade).toBeCloseTo(30, 6);
    // Signal level: earliest poll per signal — m1's 0.02 is the one that counts, dust.
    expect(d.signal.settled).toBe(4);
    expect(d.signal.dustExcluded).toBe(2);
    expect(d.signal.exDustWouldHavePnl).toBeCloseTo(0, 6);
    // Market level: earliest settled poll per market — m1@0.02, m2@0.04 are dust.
    expect(d.market.settled).toBe(4);
    expect(d.market.dustExcluded).toBe(2);
    expect(d.market.exDustMarkets).toBe(2);
    expect(d.market.exDustWouldHavePnl).toBeCloseTo(0, 6);
    expect(d.market.exTopNWouldHavePnl).toBeCloseTo(0, 6);
    // Both dust markets sit inside the v67-banned sub-0.05 tail.
    expect(d.market.bannedTailMarkets).toBe(2);
    expect(d.market.bannedTailWouldHavePnl).toBeCloseTo(730, 6);
  });

  it("is the SAME arithmetic the confidence lane publishes", () => {
    const d = settledDustRead(rows, {
      dustMinEntry: LOWCONF_DUST_MIN_ENTRY,
      bannedTailMax: LOWCONF_BANNED_TAIL_MAX,
      defaultStakeUsd: 10,
    });
    const s = summarizeLowConf(rows);
    expect(s.dust.rowsExcluded).toBe(d.row.dustExcluded);
    expect(s.dust.rowPnlExcluded).toBeCloseTo(d.row.dustWouldHavePnl, 6);
    expect(s.dust.wouldHavePnl).toBeCloseTo(d.row.exDustWouldHavePnl, 6);
    expect(s.dust.signalsExcluded).toBe(d.signal.dustExcluded);
    expect(s.dust.marketsExcluded).toBe(d.market.dustExcluded);
    expect(s.dust.wouldHavePnlOneBetPerMarket).toBeCloseTo(d.market.exDustWouldHavePnl, 6);
    expect(s.dust.topMarketId).toBe(d.market.topMarketId);
    expect(s.dust.bannedTailOneBetPerMarket).toBeCloseTo(d.market.bannedTailWouldHavePnl, 6);
    expect(s.basis.wouldHavePnlPerSignal).toBeCloseTo(d.signal.wouldHavePnl, 6);
    expect(s.basis.wouldHavePnlOneBetPerMarket).toBeCloseTo(d.market.wouldHavePnl, 6);
  });

  it("removes the N largest contributors from the market-level total, not the smallest", () => {
    const many = [] as Array<Record<string, unknown>>;
    for (let i = 0; i < 4; i++) {
      many.push(RESOLVE(`p${i}`, "YES", 1), CAND({ marketId: `p${i}`, wallet: `w${i}`, currentPrice: 0.5 }));
    }
    const d = settledDustRead(many, { dustMinEntry: 0.1, topN: 2 });
    // four equal +$10 markets: ex-top-2 leaves +$20
    expect(d.market.exDustWouldHavePnl).toBeCloseTo(40, 6);
    expect(d.market.exTopNWouldHavePnl).toBeCloseTo(20, 6);
    expect(d.market.topMarketShare).toBeCloseTo(0.25, 6);
  });
});
