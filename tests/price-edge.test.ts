import { describe, it, expect } from "vitest";
import * as fs from "fs";
import * as path from "path";
import {
  PRICE_EDGE_SPEC_V1,
  priceEdgeProbability,
  priceEdge,
  takerFeePerShare,
  categoryFeeRate,
  type PriceEdgeSpec,
} from "../src/lib/scoring/price-edge";

/**
 * Reference values produced by scripts/fit-price-edge.py against the emitted
 * spec (data/score-spec-v1.json). If the fit changes, both move together — the
 * spec-integrity test below is what keeps the TS constants honest.
 */
const EXPECTED_P = [
  { price: 0.02, pWin: 0.071411 },
  { price: 0.05, pWin: 0.126925 },
  { price: 0.10, pWin: 0.193693 },
  { price: 0.19, pWin: 0.284153 },
  { price: 0.25, pWin: 0.334531 },
  { price: 0.35, pWin: 0.409649 },
  { price: 0.50, pWin: 0.512664 },
  { price: 0.65, pWin: 0.614615 },
  { price: 0.80, pWin: 0.727597 },
  { price: 0.90, pWin: 0.821644 },
  { price: 0.95, pWin: 0.883887 },
  { price: 0.98, pWin: 0.935024 },
];

describe("price-edge v1 spec integrity", () => {
  const specPath = path.resolve(__dirname, "../data/score-spec-v1.json");

  it("is still marked shadow-only in code", () => {
    expect(PRICE_EDGE_SPEC_V1.status).toBe("shadow");
  });

  it("matches data/score-spec-v1.json exactly (constants may not drift from the fit)", () => {
    const spec = JSON.parse(fs.readFileSync(specPath, "utf8"));
    expect(PRICE_EDGE_SPEC_V1.specVersion).toBe(spec.spec_version);
    expect(PRICE_EDGE_SPEC_V1.mean).toBe(spec.model.parameters.mean);
    expect(PRICE_EDGE_SPEC_V1.sd).toBe(spec.model.parameters.sd);
    expect(PRICE_EDGE_SPEC_V1.a).toBe(spec.model.parameters.a);
    expect(PRICE_EDGE_SPEC_V1.b).toBe(spec.model.parameters.b);
    expect(PRICE_EDGE_SPEC_V1.margin).toBe(spec.decision_rule.margin);
    expect(spec.acceptance_criteria.result).toBe("FAIL"); // flips to PASS only with a new spec version
  });

  it("records that the spec failed acceptance, so nobody wires it up by accident", () => {
    const spec = JSON.parse(fs.readFileSync(specPath, "utf8"));
    expect(spec.deployment).toMatch(/shadow/i);
    expect(spec.acceptance_criteria.detail.W_wallet_blocked.a2_ci_excludes_zero).toBe(false);
  });
});

describe("priceEdgeProbability", () => {
  it("reproduces the reference probabilities from the fit", () => {
    for (const { price, pWin } of EXPECTED_P) {
      expect(priceEdgeProbability(price)!).toBeCloseTo(pWin, 5);
    }
  });

  it("is strictly increasing in price (monotone in the market's own information)", () => {
    const prices = [0.01, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99];
    const ps = prices.map((p) => priceEdgeProbability(p)!);
    for (let i = 1; i < ps.length; i++) expect(ps[i]).toBeGreaterThan(ps[i - 1]);
  });

  it("stays inside (0, 1) across the whole price range", () => {
    for (let p = 0.001; p < 1; p += 0.001) {
      const v = priceEdgeProbability(p)!;
      expect(v).toBeGreaterThan(0);
      expect(v).toBeLessThan(1);
    }
  });

  it("returns null (never 0 or 0.5) for unusable prices", () => {
    for (const bad of [0, 1, -0.1, 1.5, NaN, Infinity]) {
      expect(priceEdgeProbability(bad)).toBeNull();
    }
  });
});

describe("takerFeePerShare", () => {
  it("implements shares * rate * p * (1-p) per share", () => {
    expect(takerFeePerShare(0.5, 0.05)).toBeCloseTo(0.0125, 10);
    expect(takerFeePerShare(0.1, 0.05)).toBeCloseTo(0.0045, 10);
    expect(takerFeePerShare(0.98, 0.05)).toBeCloseTo(0.00098, 10);
  });

  it("costs nothing at the extremes and most at p=0.5", () => {
    expect(takerFeePerShare(0, 0.05)).toBe(0);
    expect(takerFeePerShare(1, 0.05)).toBe(0);
    expect(takerFeePerShare(0.5, 0.05)).toBeGreaterThan(takerFeePerShare(0.7, 0.05));
  });

  it("scales with the category rate", () => {
    expect(takerFeePerShare(0.4, 0.07)).toBeCloseTo(takerFeePerShare(0.4, 0.035) * 2, 10);
  });
});

describe("categoryFeeRate", () => {
  it("maps crypto, politics/finance and everything else to the published coefficients", () => {
    expect(categoryFeeRate("Will BTC close above $100k this week?")).toBe(0.07);
    expect(categoryFeeRate("Will the Fed cut rates in September?")).toBe(0.04);
    expect(categoryFeeRate("Will Vålerenga Fotball win on 2026-07-16?")).toBe(0.05);
    expect(categoryFeeRate(null)).toBe(0.05);
  });
});

describe("priceEdge gate", () => {
  it("admits cheap longshots that clear the margin and rejects fair-priced copies", () => {
    const cheap = priceEdge(0.10)!;
    expect(cheap.admit).toBe(true);
    expect(cheap.edge).toBeCloseTo(0.089193, 5);

    const mid = priceEdge(0.50)!;
    expect(mid.admit).toBe(false);
    expect(mid.edge).toBeCloseTo(0.000164, 5);

    const favorite = priceEdge(0.90)!;
    expect(favorite.admit).toBe(false);
    expect(favorite.edge).toBeCloseTo(-0.082856, 5);
  });

  it("uses a strict comparison at the margin boundary", () => {
    const spec: PriceEdgeSpec = { ...PRICE_EDGE_SPEC_V1, margin: 0.089193 };
    const atBoundary = priceEdge(0.10, { spec })!;
    expect(atBoundary.edge).toBeCloseTo(0.089193, 5);
    expect(atBoundary.admit).toBe(false); // edge === margin is not admitted
    const justBelow = priceEdge(0.095, { spec })!;
    if (justBelow.edge > spec.margin) expect(justBelow.admit).toBe(true);
  });

  it("flags every result as shadow and reports the spec version", () => {
    const r = priceEdge(0.12)!;
    expect(r.shadow).toBe(true);
    expect(r.specVersion).toBe(1);
    expect(r.reason).toMatch(/price-edge v1/);
  });

  it("honours an explicit fee rate and returns null for bad prices", () => {
    const a = priceEdge(0.2, { feeRate: 0.04 })!;
    const b = priceEdge(0.2, { feeRate: 0.07 })!;
    expect(a.feePerShare).toBeLessThan(b.feePerShare);
    expect(a.edge).toBeGreaterThan(b.edge);
    expect(priceEdge(0)).toBeNull();
    expect(priceEdge(1.2)).toBeNull();
  });

  it("keeps edge === pWin - price - fee (the quantity the fit's loss used)", () => {
    for (const p of [0.03, 0.15, 0.33, 0.5, 0.72, 0.94]) {
      const r = priceEdge(p)!;
      expect(r.edge).toBeCloseTo(r.pWin - r.price - r.feePerShare, 10);
    }
  });
});
