/**
 * ruleupdater-exit-labeled-winrate — the auto-tuner's `minCopyScore` gate is read on two bases.
 *
 * What is pinned here:
 *  1. the arithmetic of both bases, including that an undeterminable settlement is EXCLUDED (not
 *     guessed) and reported as coverage;
 *  2. that `gateVerdict` is a faithful mirror of the two `minCopyScore` arms in rule-updater.ts;
 *  3. that the evidence line can no longer print a win rate without naming its basis — the actual
 *     defect this card exists for;
 *  4. that the gate's DECISION is unchanged: same samples, same thresholds, same proposal — only
 *     the printed evidence grew.
 */
import { describe, it, expect } from "vitest";
import {
  exitBasisRead,
  outcomeBasisRead,
  settlementDisagreement,
  settlementPnl,
  gateVerdict,
  compareGateBasis,
  gateBasisText,
  GateLeg,
} from "../src/lib/gate-winrate-basis";
import { proposeRuleChanges } from "../src/lib/rule-updater";
import { DEFAULT_RULES } from "../src/lib/rules";

const leg = (o: Partial<GateLeg> = {}): GateLeg => ({
  pnl: 5,
  stake: 10,
  entryPrice: 0.5,
  at: new Date("2026-11-01T00:00:00Z"),
  outcomeWin: true,
  ...o,
});

describe("exitBasisRead — the gate's live input", () => {
  it("counts realizedPnl > 0 and treats a null PnL as a non-win, exactly as the gate does", () => {
    const r = exitBasisRead([leg(), leg({ pnl: -3 }), leg({ pnl: 0 }), leg({ pnl: null })]);
    expect(r.n).toBe(4);
    expect(r.wins).toBe(1);
    expect(r.rate).toBe(0.25);
    expect(r.pnl).toBeCloseTo(2, 10);
  });

  it("reports an undefined rate as null, never 0%", () => {
    expect(exitBasisRead([]).rate).toBeNull();
  });
});

describe("outcomeBasisRead — the settlement label", () => {
  it("excludes undeterminable legs from the rate and reports them as coverage", () => {
    const r = outcomeBasisRead([
      leg({ outcomeWin: true }),
      leg({ outcomeWin: false }),
      leg({ outcomeWin: null }),
      leg({ outcomeWin: null }),
    ]);
    expect(r.n).toBe(2);
    expect(r.wins).toBe(1);
    expect(r.rate).toBe(0.5);
    expect(r.undetermined).toBe(2);
    expect(r.coverage).toBe(0.5);
  });
});

describe("settlementDisagreement — where the two labels part company", () => {
  it("separates exit-wins that settled LOSSES from exit-losses that settled WINS", () => {
    const d = settlementDisagreement([
      leg({ pnl: 5, outcomeWin: false }), // sold up, settled down -> the inflation case
      leg({ pnl: -5, outcomeWin: true }), // sold down, settled up -> gave up a winner
      leg({ pnl: 5, outcomeWin: true }),
      leg({ pnl: -5, outcomeWin: false }),
      leg({ pnl: 5, outcomeWin: null }),
    ]);
    expect(d.exitWinOutcomeLoss.n).toBe(1);
    expect(d.exitWinOutcomeLoss.pnl).toBeCloseTo(5, 10);
    expect(d.exitLossOutcomeWin.n).toBe(1);
    expect(d.bothWon).toBe(1);
    expect(d.bothLost).toBe(1);
    expect(d.unknown).toBe(1);
  });
});

describe("settlementPnl — the hold-to-settlement counterfactual", () => {
  it("pays (1-p)/p per $1 on a winner and -$1 on a loser", () => {
    expect(settlementPnl(leg({ entryPrice: 0.5, stake: 10, outcomeWin: true }))).toBeCloseTo(10, 10);
    expect(settlementPnl(leg({ entryPrice: 0.25, stake: 10, outcomeWin: true }))).toBeCloseTo(30, 10);
    expect(settlementPnl(leg({ entryPrice: 0.25, stake: 10, outcomeWin: false }))).toBeCloseTo(-10, 10);
  });

  it("returns null rather than guessing on an unknown outcome or an impossible price", () => {
    expect(settlementPnl(leg({ outcomeWin: null }))).toBeNull();
    expect(settlementPnl(leg({ entryPrice: 0 }))).toBeNull();
    expect(settlementPnl(leg({ entryPrice: 1.5 }))).toBeNull();
  });
});

describe("gateVerdict — a mirror of rule-updater's two minCopyScore arms", () => {
  const rules = { minCopyScore: 65, highScoreCapMin: 80, sweetSpotMinScore: 70 };

  it("tightens only on a losing book with a sub-45% rate, and never past 85", () => {
    expect(gateVerdict(-5, 0.4, rules).tightens).toBe(true);
    expect(gateVerdict(-5, 0.5, rules).tightens).toBe(false); // rate too high
    expect(gateVerdict(5, 0.4, rules).tightens).toBe(false); // book profitable
    expect(gateVerdict(-5, 0.4, { ...rules, minCopyScore: 85 }).tightens).toBe(false);
  });

  it("relaxes only above a +$20 book and a 60% rate, and never below the floor", () => {
    expect(gateVerdict(25, 0.7, { ...rules, minCopyScore: 82 }).relaxes).toBe(true);
    expect(gateVerdict(25, 0.7, rules).copyFloor).toBe(80);
    // A bar already AT the floor cannot be relaxed: 80 > 80 is false. That is the live shape today
    // (v71 minCopyScore 80, floor 80) — the relax arm is structurally dead, measured not assumed.
    expect(gateVerdict(25, 0.7, { ...rules, minCopyScore: 80 }).relaxes).toBe(false);
    expect(gateVerdict(10, 0.7, { ...rules, minCopyScore: 82 }).relaxes).toBe(false);
  });
});

describe("compareGateBasis — does the basis change the verdict?", () => {
  it("computes the flip instead of asserting one", () => {
    // 10 legs: 7 closed above entry (EXIT 70%), only 2 settled as wins (OUTCOME 20%) -> the live
    // arm sees a comfortable book, the settlement arm sees a losing one.
    const legs = Array.from({ length: 10 }, (_, i) =>
      leg({ pnl: i < 7 ? 5 : -5, outcomeWin: i < 2 })
    );
    const c = compareGateBasis(legs, { minCopyScore: 65, highScoreCapMin: 80, sweetSpotMinScore: 70 });
    expect(c.exit.rate).toBe(0.7);
    expect(c.outcomeOnExitBook.rate).toBe(0.2);
    expect(c.verdictLive.tightens).toBe(false);
    expect(c.verdictSettleBook?.tightens).toBe(true);
    expect(c.verdictFlips).toBe(true);
  });

  it("reports no flip when the two bases agree", () => {
    const legs = Array.from({ length: 10 }, (_, i) => leg({ pnl: i < 7 ? 5 : -5, outcomeWin: i < 7 }));
    const c = compareGateBasis(legs, { minCopyScore: 65, highScoreCapMin: 80, sweetSpotMinScore: 70 });
    expect(c.verdictFlips).toBe(false);
  });
});

describe("gateBasisText — the printed number can never again be read as a probability", () => {
  it("names EXIT basis and OUTCOME basis with n and coverage", () => {
    const legs = Array.from({ length: 10 }, (_, i) => leg({ pnl: i < 7 ? 5 : -5, outcomeWin: i < 2 }));
    const text = gateBasisText(compareGateBasis(legs, { minCopyScore: 65, highScoreCapMin: 80, sweetSpotMinScore: 70 }));
    expect(text).toContain("EXIT basis 70.0%");
    expect(text).toContain("realizedPnl>0");
    expect(text).toContain("OUTCOME basis 20.0%");
    expect(text).toContain("n=10");
    expect(text).toContain("judgeable");
  });
});

describe("rule-updater — the label grew, the decision did not", () => {
  const samples = Array.from({ length: 10 }, (_, i) => ({
    pnl: i < 3 ? 2 : -4,
    stake: 10,
    at: new Date("2026-11-02T00:00:00Z"),
    spread: null,
    liquidity: null,
    drift: 0,
    walletScore: 70,
    // 3 exit-wins, but only 1 of those 3 actually settled a win
    outcomeWin: i === 0 ? true : i === 1 ? false : false,
    entryPrice: 0.5,
  }));

  it("still proposes the same minCopyScore raise on the same EXIT-basis rate", () => {
    const proposals = proposeRuleChanges(samples, DEFAULT_RULES);
    const raise = proposals.find((p) => p.field === "minCopyScore");
    expect(raise).toBeDefined();
    expect(raise!.newValue).toBe(Math.min(85, DEFAULT_RULES.minCopyScore + 3));
    expect(raise!.reason).toContain("raising copy threshold");
  });

  it("prints both bases on the evidence line", () => {
    const proposals = proposeRuleChanges(samples, DEFAULT_RULES);
    const raise = proposals.find((p) => p.field === "minCopyScore")!;
    expect(raise.evidence).toContain("EXIT basis 30.0%");
    expect(raise.evidence).toContain("OUTCOME basis");
    expect(raise.evidence).toContain("avg win");
  });
});
