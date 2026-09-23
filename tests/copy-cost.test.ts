/**
 * Edge vs cost of copying (roadmap card `polycopy-edge-cost-pair`).
 *
 * Guards the invariants that make the two numbers readable together:
 *  1. BOTH terms come from ONE population (settled legs, same window) — the
 *     card's whole point is that neither number may be quoted alone;
 *  2. the copy-cost sign convention (positive = we paid ABOVE the wallet's own
 *     fill = a real cost; negative = the fill-model artefact, flagged);
 *  3. the edge term is aggregate PnL over committed notional, not an unweighted
 *     per-leg average (the two differ by 3x on the live C-200 book);
 *  4. the rendered line always carries n and the window, per lane.
 */

import { describe, it, expect } from "vitest";
import {
  CopyCostRow,
  LANES,
  edgeCostLines,
  edgeCostLogLine,
  edgeCostSnapshot,
  laneEdgeCost,
  localDay,
  pct1,
} from "../src/lib/copy-cost";

const NOW = new Date("2026-09-23T22:00:00-05:00");
const DAY = 86_400_000;
const recent = NOW.getTime() - 2 * DAY;
const ancient = NOW.getTime() - 90 * DAY;

function leg(o: Partial<CopyCostRow> = {}): CopyCostRow {
  return {
    botId: "BANKROLL_200",
    entryPrice: 0.5,
    sizeUsd: 10,
    realizedPnl: 1,
    settledAtMs: recent,
    openedAtMs: recent,
    walletEntryPrice: 0.5,
    detectedPrice: 0.505,
    ...o,
  };
}

describe("laneEdgeCost — one population for both terms", () => {
  it("keeps only settled legs, and both terms share that n", () => {
    const rows = [
      leg({ entryPrice: 0.55, walletEntryPrice: 0.5 }), // +10% over the fill
      leg({ entryPrice: 0.45, walletEntryPrice: 0.5 }), // -10% under the fill
      leg({ settledAtMs: null }), // open — not in the reported population
      leg({ settledAtMs: null, botId: "STANDARD" }),
      leg({ botId: "STANDARD" }),
    ];
    const c200 = laneEdgeCost(rows, "BANKROLL_200");
    expect(c200.n).toBe(2);
    expect(c200.copyCostPctPerLeg).toBeCloseTo(0, 10);
    // edge aggregates over the SAME two legs
    expect(c200.realizedPnlUsd).toBe(2);
    expect(c200.costUsd).toBe(20);
    expect(c200.edgePctOfCost).toBeCloseTo(10, 10);

    const std = laneEdgeCost(rows, "STANDARD");
    expect(std.n).toBe(1);
    expect(std.copyCostPctPerLeg).toBeCloseTo(0, 10);
  });

  it("excludes legs settled before the window start", () => {
    const rows = [leg({ settledAtMs: ancient }), leg({ settledAtMs: recent })];
    expect(laneEdgeCost(rows, "BANKROLL_200").n).toBe(2);
    expect(laneEdgeCost(rows, "BANKROLL_200", recent - 1000).n).toBe(1);
    expect(laneEdgeCost(rows, "BANKROLL_200", NOW.getTime()).n).toBe(0);
  });

  it("sign convention: entry above the wallet fill is a real cost (positive)", () => {
    const over = laneEdgeCost([leg({ entryPrice: 0.52, walletEntryPrice: 0.5 })], "BANKROLL_200");
    expect(over.copyCostPctPerLeg).toBeCloseTo(4, 10);
    const under = laneEdgeCost([leg({ entryPrice: 0.485, walletEntryPrice: 0.5 })], "BANKROLL_200");
    expect(under.copyCostPctPerLeg).toBeCloseTo(-3, 10);
  });

  it("detection drag is measured against the wallet fill, independently of our entry", () => {
    const s = laneEdgeCost(
      [leg({ entryPrice: 0.9, walletEntryPrice: 0.5, detectedPrice: 0.51 })],
      "BANKROLL_200"
    );
    expect(s.copyCostPctPerLeg).toBeCloseTo(80, 10);
    expect(s.detectionDragPctPerLeg).toBeCloseTo(2, 10);
  });

  it("edge is aggregate PnL / committed notional, not the per-leg average", () => {
    // +10% on $90 and -10% on $10: per-leg mean is 0%, aggregate is +8%.
    const s = laneEdgeCost(
      [
        leg({ sizeUsd: 90, realizedPnl: 9 }),
        leg({ sizeUsd: 10, realizedPnl: -1 }),
      ],
      "BANKROLL_200"
    );
    expect(s.edgePctOfCost).toBeCloseTo(8, 10);
  });

  it("drops a leg with no wallet fill from BOTH terms and counts it", () => {
    const rows = [
      leg({ walletEntryPrice: 0.5 }),
      leg({ walletEntryPrice: null, realizedPnl: 100, sizeUsd: 1000 }),
      leg({ walletEntryPrice: 0 }),
    ];
    const s = laneEdgeCost(rows, "BANKROLL_200");
    expect(s.n).toBe(1);
    expect(s.droppedNoFill).toBe(2);
    expect(s.edgePctOfCost).toBeCloseTo(10, 10); // the $1,000 leg is not in it
    expect(s.copyCostPctPerLeg).toBeCloseTo(0, 10);
  });

  it("returns nulls (not NaN) for an empty lane", () => {
    const s = laneEdgeCost([], "BANKROLL_200");
    expect(s).toMatchObject({ n: 0, edgePctOfCost: null, copyCostPctPerLeg: null });
    expect(s.label).toBe("C-200");
  });
});

describe("maker credit — the Rust sidecar's 2¢ assumption (C-200 only)", () => {
  it("values re-pricing the C-200 entry at entry+0.02, holding the exit price fixed", () => {
    // entry 0.50, size $10 → 20 shares; realized +$4 ⇒ exit = $0.70.
    // At entry 0.52 the same $10 buys 19.2308 shares ⇒ 19.2308 × 0.70 − 10 = $3.4615
    // so the 2¢ improvement is worth 4 − 3.4615 = $0.5385 → $0.54 (rounded to cents).
    const s = laneEdgeCost([leg({ entryPrice: 0.5, sizeUsd: 10, realizedPnl: 4 })], "BANKROLL_200");
    expect(s.makerCreditUsd).toBe(0.54);
  });

  it("is zero for STANDARD, which writes its own fills (no sidecar dispatch)", () => {
    const s = laneEdgeCost([leg({ botId: "STANDARD", entryPrice: 0.5, sizeUsd: 10, realizedPnl: 4 })], "STANDARD");
    expect(s.makerCreditUsd).toBe(0);
  });

  it("only counts settled legs inside the window, like every other term", () => {
    const rows = [
      leg({ entryPrice: 0.5, sizeUsd: 10, realizedPnl: 4 }),
      leg({ entryPrice: 0.5, sizeUsd: 10, realizedPnl: 4, settledAtMs: ancient }),
    ];
    const life = laneEdgeCost(rows, "BANKROLL_200");
    const win = laneEdgeCost(rows, "BANKROLL_200", recent - 1000);
    expect(life.makerCreditUsd).toBe(1.08); // 2 × $0.5385
    expect(win.makerCreditUsd).toBe(0.54);
  });

  it("credits nothing for legs booked before the sidecar's maker path existed", () => {
    const pre = Date.UTC(2026, 6, 22); // 893 dual-lane pairs booked before it
    const s = laneEdgeCost(
      [leg({ entryPrice: 0.5, sizeUsd: 10, realizedPnl: 4, openedAtMs: pre, settledAtMs: pre })],
      "BANKROLL_200"
    );
    expect(s.makerCreditUsd).toBe(0);
    expect(s.exMakerEdgePctOfCost).toBeNull();
    expect(s.edgePctOfCost).toBeCloseTo(40, 10); // the edge itself is unchanged
  });
});

describe("edgeCostSnapshot", () => {
  it("reports lifetime and trailing-30d over the same rows, per lane", () => {
    const rows = [
      leg({ entryPrice: 0.55 }), // lifetime + 30d
      leg({ settledAtMs: NOW.getTime() - 45 * DAY, entryPrice: 0.45 }), // lifetime only
      leg({ botId: "STANDARD", entryPrice: 0.525 }), // +5% cost, 30d
    ];
    const snap = edgeCostSnapshot(rows, NOW);
    expect(snap.lifetime.map((l) => l.botId)).toEqual([...LANES]);
    const c200life = snap.lifetime.find((l) => l.botId === "BANKROLL_200")!;
    const c200d30 = snap.d30.find((l) => l.botId === "BANKROLL_200")!;
    expect(c200life.n).toBe(2);
    expect(c200life.copyCostPctPerLeg).toBeCloseTo(0, 10); // (+10 -10)/2
    expect(c200d30.n).toBe(1);
    expect(c200d30.copyCostPctPerLeg).toBeCloseTo(10, 10);
    const std = snap.d30.find((l) => l.botId === "STANDARD")!;
    expect(std.n).toBe(1);
    expect(std.copyCostPctPerLeg).toBeCloseTo(5, 10);
    expect(localDay(snap.lifetimeStartMs!)).toBe(localDay(NOW.getTime() - 45 * DAY));
  });
});

describe("edgeCostLines — the report block", () => {
  it("prints nothing when nothing has settled", () => {
    expect(edgeCostLines(edgeCostSnapshot([leg({ settledAtMs: null })], NOW))).toEqual([]);
  });

  it("states the window, both numbers and n for every lane, plus the sign legend", () => {
    const rows = [
      leg({ entryPrice: 0.485, walletEntryPrice: 0.5, detectedPrice: 0.505 }), // negative cost
      leg({ botId: "STANDARD", entryPrice: 0.51, walletEntryPrice: 0.5 }),
    ];
    const lines = edgeCostLines(edgeCostSnapshot(rows, NOW));
    expect(lines.length).toBe(4); // header + 2 lanes + legend
    expect(lines[0]).toContain("settled legs");
    expect(lines[0]).toContain("last 30d");
    expect(lines[0]).toContain(localDay(recent));
    const c200 = lines.find((l) => l.startsWith("• C-200"))!;
    const std = lines.find((l) => l.startsWith("• STANDARD"))!;
    for (const line of [c200, std]) {
      expect(line).toContain("edge"); // (a) realized PnL as % of cost
      expect(line).toContain("copy cost"); // (b) the copy-cost term
      expect(line).toContain("n=1"); // population stated
      expect(line).toContain("of cost");
    }
    expect(c200).toContain("-3.0%"); // non-adverse ⇒ signed, visible
    expect(std).toContain("+2.0%");
    expect(lines[3]).toContain("BELOW the wallet's own fill");
    expect(lines[3]).toContain("LOWER BOUND");
  });

  it("names the maker assumption and its dollar value when a lane is sidecar-routed", () => {
    const rows = [
      leg({ entryPrice: 0.5, sizeUsd: 10, realizedPnl: 4 }), // C-200: credit $0.54
      leg({ botId: "STANDARD", entryPrice: 0.51 }),
    ];
    const lines = edgeCostLines(edgeCostSnapshot(rows, NOW));
    const legend = lines[lines.length - 1];
    expect(legend).toContain("maker_improvement");
    expect(legend).toContain("$1"); // ≈$1 of the $4 lifetime C-200 PnL
    expect(legend).toContain("Ex that assumption");
    expect(legend).toMatch(/C-200 reads [+-]\d+\.\d% of cost \(lifetime\)/);
  });

  it("uses the plain legend when every lane paid above the wallet's fill", () => {
    const rows = [leg({ entryPrice: 0.55 }), leg({ botId: "STANDARD", entryPrice: 0.55 })];
    const lines = edgeCostLines(edgeCostSnapshot(rows, NOW));
    expect(lines[lines.length - 1]).toContain("positive = we paid above the wallet");
    expect(lines[lines.length - 1]).not.toContain("BELOW");
  });

  it("omits the 30d segment when the trailing window is empty", () => {
    const rows = [leg({ settledAtMs: ancient })];
    const lines = edgeCostLines(edgeCostSnapshot(rows, NOW));
    const c200 = lines.find((l) => l.startsWith("• C-200"))!;
    expect(c200).toContain("n=1");
    expect(c200).not.toContain("→");
    expect(c200).not.toContain("—");
  });
});

describe("formatters", () => {
  it("renders one decimal with an ASCII sign and an em dash for null", () => {
    expect(pct1(16.345)).toBe("+16.3");
    expect(pct1(-3.032)).toBe("-3.0");
    expect(pct1(0)).toBe("+0.0");
    expect(pct1(null)).toBe("—");
  });

  it("the EOD log line carries both numbers with n, per lane", () => {
    const rows = [leg({ entryPrice: 0.485 }), leg({ botId: "STANDARD", entryPrice: 0.51 })];
    const line = edgeCostLogLine(edgeCostSnapshot(rows, NOW));
    expect(line).toContain("C-200 edge");
    expect(line).toContain("copy cost");
    expect(line).toContain("STANDARD edge");
    expect(line.match(/n=1/g)?.length).toBeGreaterThanOrEqual(4);
  });
});
