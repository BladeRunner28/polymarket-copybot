/**
 * 2026-11-19 (card profit-longshot-token-basis) — the long-shot summary must publish
 * BETS as well as TICKETS.
 *
 * Why this exists: the ladder logs one candidate row per observed trade, so the same
 * side of the same market is counted again every time a tracked wallet touches it.
 * Measured on the live feed 2026-11-19: 135 resolved tickets over 64 distinct
 * market|outcome bets (2.11x, one market seen 16 times), and the headline PnL fell
 * from $1,891.93 to $939.62 -- and to -$977.44 ex-top-10 -- once tickets collapsed to
 * bets. The token-basis re-mark in the same pass found ZERO label/token disagreements
 * on 135/135 tickets, i.e. the BASIS was never the defect; the multiplicity was.
 *
 * These tests pin the second basis so a future reader cannot mistake one for the other.
 */
import { describe, it, expect } from "vitest";
import { summarizeShadow } from "../src/lib/shadow-longshot";

const cand = (marketId: string, outcome: string, entryPrice: number, ts: string) => ({
  ts,
  type: "candidate",
  marketId,
  outcome,
  side: "BUY",
  wallet: "0xabc",
  entryPrice,
  stakeUsd: 20,
  wouldAdmit: true,
});

const res = (marketId: string, outcome: string, value: 0 | 1, ts: string) => ({
  ts,
  type: "resolve",
  marketId,
  outcome,
  value,
});

describe("long-shot summary: tickets vs bets", () => {
  it("collapses repeated sightings of one side into one bet", () => {
    const rows = [
      // market A, same side logged three times: one win at a 5x payoff
      cand("m-a", "YES", 0.2, "2026-11-01T00:00:00Z"),
      cand("m-a", "YES", 0.2, "2026-11-01T01:00:00Z"),
      cand("m-a", "YES", 0.2, "2026-11-01T02:00:00Z"),
      // market B, one loss
      cand("m-b", "NO", 0.2, "2026-11-01T03:00:00Z"),
      res("m-a", "YES", 1, "2026-11-02T00:00:00Z"),
      res("m-b", "NO", 0, "2026-11-02T00:00:00Z"),
    ];
    const s = summarizeShadow(rows);
    expect(s.resolved).toBe(4);          // tickets, as filed
    expect(s.wins).toBe(3);
    expect(s.totalPnl).toBe(3 * 80 - 20); // 3 winning tickets at 0.2 + one loser
    // bets: 1 win + 1 loss on one ticket each
    expect(s.perOpportunity.markets).toBe(2);
    expect(s.perOpportunity.wouldHavePnl).toBe(80 - 20);
    expect(s.ticketsPerMarket).toBe(2);
  });

  it("counts an unresolved market as no bet at all", () => {
    const rows = [
      cand("m-a", "YES", 0.1, "2026-11-01T00:00:00Z"),
      cand("m-b", "YES", 0.1, "2026-11-01T01:00:00Z"),
      res("m-a", "YES", 1, "2026-11-02T00:00:00Z"),
    ];
    const s = summarizeShadow(rows);
    expect(s.resolved).toBe(1);
    expect(s.perOpportunity.markets).toBe(1);
    expect(s.ticketsPerMarket).toBe(1);
  });

  it("publishes null (never 0) for tickets-per-market when nothing has settled", () => {
    const s = summarizeShadow([cand("m-a", "YES", 0.1, "2026-11-01T00:00:00Z")]);
    expect(s.resolved).toBe(0);
    expect(s.perOpportunity.markets).toBe(0);
    expect(s.ticketsPerMarket).toBeNull();
    expect(s.winRate).toBeNull();
  });

  it("the bet basis cannot exceed the ticket basis on a duplicated book", () => {
    const rows = [
      cand("m-a", "YES", 0.1, "2026-11-01T00:00:00Z"),
      cand("m-a", "YES", 0.1, "2026-11-01T01:00:00Z"),
      cand("m-a", "YES", 0.1, "2026-11-01T02:00:00Z"),
      cand("m-a", "YES", 0.1, "2026-11-01T03:00:00Z"),
      res("m-a", "YES", 1, "2026-11-02T00:00:00Z"),
    ];
    const s = summarizeShadow(rows);
    expect(s.totalPnl).toBeCloseTo(4 * 180, 6);
    expect(s.perOpportunity.wouldHavePnl).toBeCloseTo(180, 6);
    expect(s.perOpportunity.wouldHavePnl).toBeLessThan(s.totalPnl);
    expect(s.ticketsPerMarket).toBe(4);
  });
});
