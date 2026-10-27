/**
 * The ML-1 bar restatement (card `ml1-price-baseline-drift`). These tests pin the ARITHMETIC and
 * the falsifiable claim — that the restated bar reproduces the in-force constants on the
 * population those constants were measured on — not any measured market result.
 */
import { describe, expect, it } from "vitest";
import {
  BAR_SLACK,
  clearsBar,
  demandedMargin,
  relativeBar,
  reproducesInForceBar,
  type BarRead,
} from "../src/lib/ml1-bar";

const BAR: BarRead = { auc: 0.729, brier: 0.212 };
/** The price-only read recorded on the bar's own population, 2026-09-13 (decision-dataset). */
const PRICE_ON_BAR_POP = { auc: 0.7285, brier: 0.2115 };

describe("ml1 bar restatement", () => {
  it("reproduces the in-force bar on the population it was measured on", () => {
    expect(reproducesInForceBar(PRICE_ON_BAR_POP, BAR)).toBe(true);
    expect(relativeBar(PRICE_ON_BAR_POP)).toEqual({ auc: 0.729, brier: 0.212 });
  });

  it("fails its own reproduction check when the price basis is not that population", () => {
    // The re-pointed book's price read — not where the constants came from.
    expect(reproducesInForceBar({ auc: 0.7095, brier: 0.2196 }, BAR)).toBe(false);
  });

  it("demands 0.0195 AUC of headroom where the absolute bar meets the re-pointed book", () => {
    const m = demandedMargin({ auc: 0.7095, brier: 0.2196 }, BAR);
    expect(m.auc).toBeCloseTo(0.0195, 4);
    // negative: price is already above the Brier ceiling, so the absolute bar is unreachable
    expect(m.brier).toBeCloseTo(-0.0076, 4);
    expect(m.brier).toBeLessThan(0);
  });

  it("demands only the rounding slack on the bar's own population", () => {
    const m = demandedMargin(PRICE_ON_BAR_POP, BAR);
    expect(Math.abs(m.auc)).toBeLessThan(0.001);
    expect(Math.abs(m.brier)).toBeLessThan(0.001);
    expect(BAR_SLACK).toEqual({ auc: 0.0005, brier: 0.0005 });
  });

  it("a candidate identical to price fails on the AUC leg — the slack is a tolerance, not a margin", () => {
    const price = { auc: 0.7095, brier: 0.2196 };
    const verdict = clearsBar(price, relativeBar(price));
    expect(verdict.auc).toBe(false);
    // equal to price on Brier sits inside the +0.0005 tolerance, so Brier alone never disqualifies
    expect(verdict.brier).toBe(true);
    expect(verdict.both).toBe(false);
  });

  it("a candidate that beats price by the slack clears the relative bar", () => {
    const price = { auc: 0.7095, brier: 0.2196 };
    const verdict = clearsBar({ auc: 0.7101, brier: 0.2200 }, relativeBar(price));
    expect(verdict.both).toBe(true);
  });

  it("leaves the Brier leg undecided for a non-probability score rather than passing it", () => {
    const price = { auc: 0.7095, brier: 0.2196 };
    const verdict = clearsBar({ auc: 0.72, brier: null }, relativeBar(price));
    expect(verdict.auc).toBe(true);
    expect(verdict.brier).toBeNull();
    expect(verdict.both).toBeNull();
  });
});
