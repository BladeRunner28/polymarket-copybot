import { describe, expect, it } from "vitest";
import {
  readCeiling,
  floorVerdict,
  floorVerdicts,
  saturationFloor,
  depthBucketLabel,
  type DepthObservation,
} from "../src/lib/wallet-depth-ceiling";

const row = (value: number, censored = false): DepthObservation => ({ value, censored });

describe("readCeiling", () => {
  it("derives the ceiling from the rows and measures its tie mass", () => {
    const rows = [row(5), row(40), row(300, true), row(300, true), row(300, true), row(120)];
    const r = readCeiling(rows);
    expect(r.n).toBe(6);
    expect(r.ceiling).toBe(300);
    expect(r.atCeiling).toBe(3);
    expect(r.atCeilingShare).toBeCloseTo(0.5, 10);
    expect(r.censoredAtCeiling).toBe(3);
    expect(r.censoredBelowCeiling).toBe(0);
    expect(r.exactAtCeiling).toBe(0);
  });

  it("separates an EXACT count at the ceiling from a censored one", () => {
    const r = readCeiling([row(300, true), row(300, false)]);
    expect(r.atCeiling).toBe(2);
    expect(r.exactAtCeiling).toBe(1);
    expect(r.censoredAtCeiling).toBe(1);
  });

  it("counts censoring that bound on the OPEN side rather than the closed one", () => {
    const r = readCeiling([row(47, true), row(300, true), row(12)]);
    expect(r.ceiling).toBe(300);
    expect(r.censored).toBe(2);
    expect(r.censoredBelowCeiling).toBe(1);
  });

  it("does not hard-code 100 or 300 — the ceiling follows the data", () => {
    expect(readCeiling([row(100, true), row(100, true)]).ceiling).toBe(100);
    expect(readCeiling([row(900, true)]).ceiling).toBe(900);
  });

  it("is empty-safe", () => {
    const r = readCeiling([]);
    expect(r).toMatchObject({ n: 0, ceiling: 0, atCeiling: 0, atCeilingShare: 0, censored: 0 });
  });
});

describe("floorVerdict", () => {
  const rows = [row(3), row(12, true), row(300, true), row(300, true), row(40)];

  it("passes a censored row truthfully when its LOWER BOUND clears the floor", () => {
    const v = floorVerdict(rows, 100, 300);
    expect(v.pass).toBe(2);
    expect(v.passCensored).toBe(2);
    expect(v.fail).toBe(3);
    expect(v.failIndeterminate).toBe(0);
  });

  it("marks only the ABOVE-ceiling fails as indeterminate", () => {
    const v = floorVerdict(rows, 400, 300);
    expect(v.pass).toBe(0);
    expect(v.fail).toBe(5);
    // 12-censored and both 300-censored rows may exceed 400 in truth; 3 and 40 cannot.
    expect(v.failIndeterminate).toBe(3);
  });

  it("never treats an exact row as indeterminate", () => {
    const v = floorVerdict([row(90, false)], 400, 300);
    expect(v.fail).toBe(1);
    expect(v.failIndeterminate).toBe(0);
  });

  it("places the boundary exactly at the ceiling", () => {
    expect(floorVerdict(rows, 300, 300).failIndeterminate).toBe(0);
    expect(floorVerdict(rows, 301, 300).failIndeterminate).toBeGreaterThan(0);
  });
});

describe("floorVerdicts / saturationFloor", () => {
  it("reports one verdict per floor, ceiling derived once", () => {
    const vs = floorVerdicts([row(5), row(300, true)], [5, 300, 500]);
    expect(vs.map((v) => v.floor)).toEqual([5, 300, 500]);
    expect(vs[2].failIndeterminate).toBe(1);
  });

  it("names the first floor the ceiling can move", () => {
    expect(saturationFloor(300)).toBe(301);
    expect(saturationFloor(0)).toBe(1);
  });
});

describe("depthBucketLabel", () => {
  it("never calls a bucket 'the deep end' and marks the lower bound", () => {
    expect(depthBucketLabel(300, true, 300)).toBe("300+ (lower bound)");
    expect(depthBucketLabel(300, false, 300)).toBe("300+ (exact)");
    expect(depthBucketLabel(120, false, 300)).toBe("100-299");
  });

  it("keeps the thin buckets that carry no ceiling", () => {
    expect(depthBucketLabel(4, false, 300)).toBe("<10");
    expect(depthBucketLabel(12, false, 300)).toBe("10-24");
    expect(depthBucketLabel(40, false, 300)).toBe("25-49");
    expect(depthBucketLabel(60, true, 300)).toBe("50-99");
  });
});
