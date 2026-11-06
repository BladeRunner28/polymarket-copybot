import { describe, expect, it } from "vitest";
import {
  INTAKE_EXCLUSION_EPOCH,
  classifyIngestRow,
  decisionEra,
  isUnsluggableMarket,
  summarizeUnsluggableLegs,
  textAndLookalike,
} from "../src/lib/combined-market";

describe("isUnsluggableMarket", () => {
  it("fires on every shape of missing slug, and only those", () => {
    expect(isUnsluggableMarket({ marketId: "" })).toBe(true);
    expect(isUnsluggableMarket({ marketId: "   " })).toBe(true);
    expect(isUnsluggableMarket({ marketId: null })).toBe(true);
    expect(isUnsluggableMarket({})).toBe(true);
    expect(isUnsluggableMarket({ marketId: "will-ann-kao-win-hsinchu-city-and-cheng" })).toBe(false);
  });
});

describe("classifyIngestRow", () => {
  it("calls an unsluggable row that is still copyable a LEAK", () => {
    expect(classifyIngestRow({ marketId: "", observationOnly: false })).toEqual({
      untradeable: true,
      excludedAtIntake: false,
      leakedAsCopyable: true,
    });
  });

  it("does not call the post-fix state a leak", () => {
    expect(classifyIngestRow({ marketId: "", observationOnly: true })).toEqual({
      untradeable: true,
      excludedAtIntake: true,
      leakedAsCopyable: false,
    });
  });

  it("never flags a slugged market, even when observation-only", () => {
    expect(classifyIngestRow({ marketId: "some-slug", observationOnly: true }).leakedAsCopyable).toBe(false);
    expect(classifyIngestRow({ marketId: "some-slug", observationOnly: false }).untradeable).toBe(false);
  });
});

describe("decisionEra", () => {
  const epoch = "2026-10-24T02:55:48Z";

  it("splits on the intake fix to the millisecond", () => {
    expect(INTAKE_EXCLUSION_EPOCH).toBe(epoch);
    expect(decisionEra(new Date(Date.parse(epoch) - 1))).toBe("pre-fix");
    expect(decisionEra(new Date(Date.parse(epoch)))).toBe("post-fix");
    expect(decisionEra(Date.parse(epoch) + 1000)).toBe("post-fix");
  });

  it("accepts the ISO string and Date forms the reader sees", () => {
    expect(decisionEra("2026-10-24T02:50:34.424Z")).toBe("pre-fix");
    expect(decisionEra("2026-11-05T23:59:59Z")).toBe("post-fix");
  });
});

describe("textAndLookalike", () => {
  it("documents the false-positive class rather than excluding anything", () => {
    expect(textAndLookalike("Magic vs. Suns AND Heat vs. Warriors")).toBe(true);
    // the measured false positives — a rule keyed on this text would sweep these in
    expect(textAndLookalike("Will X be between 37m and 40m?")).toBe(false);
    expect(textAndLookalike("Will Ann Kao win Hsinchu City and Cheng Chao-fang win Hsinchu County?")).toBe(false);
    expect(textAndLookalike(null)).toBe(false);
  });
});

describe("summarizeUnsluggableLegs", () => {
  const legs = [
    { botId: "STANDARD", size: 10, realizedPnl: -10, entryPrice: 0.505, outcome: "" },
    { botId: "STANDARD", size: 12.5, realizedPnl: -12.5, entryPrice: 0.535, outcome: "" },
    { botId: "BANKROLL_200", size: 5, realizedPnl: -5, entryPrice: 0.5, outcome: "" },
  ];

  it("counts legs, not decisions, and carries the blank-label count", () => {
    const s = summarizeUnsluggableLegs(legs);
    expect(s.legs).toBe(3);
    expect(s.staked).toBe(27.5);
    expect(s.bookedPnl).toBe(-27.5);
    expect(s.lossShare).toBe(1);
    expect(s.blankOutcome).toBe(3);
    expect(s.byBot.STANDARD).toEqual({ legs: 2, staked: 22.5, pnl: -22.5 });
    expect(s.byBot.BANKROLL_200).toEqual({ legs: 1, staked: 5, pnl: -5 });
  });

  it("treats a null PnL as zero booked rather than as a win", () => {
    const s = summarizeUnsluggableLegs([{ botId: "STANDARD", size: 10, realizedPnl: null, entryPrice: 0.5, outcome: "" }]);
    expect(s.bookedPnl).toBe(0);
    expect(s.lossShare).toBe(0);
  });

  it("does not divide by zero on an empty population", () => {
    expect(summarizeUnsluggableLegs([])).toEqual({
      legs: 0,
      staked: 0,
      bookedPnl: 0,
      lossShare: 0,
      blankOutcome: 0,
      byBot: {},
    });
  });
});
