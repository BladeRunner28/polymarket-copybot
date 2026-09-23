/**
 * wallet-depth-field-clamp (approved 2026-09-23): the depth walk must be exact
 * when the record ends inside its budget, honestly flagged when it does not, and
 * free when the scoring sample already covered the whole record.
 */
import { describe, expect, it, vi } from "vitest";
import { countPaged, measureDepth, type WalletDepthOptions } from "../src/lib/scoring/wallet-depth";

/** A paged record of `total` rows served `pageSize` at a time. */
function paged(total: number, pageSize: number, onCall?: () => void) {
  return async (offset: number) => {
    onCall?.();
    return Array.from({ length: Math.max(0, Math.min(pageSize, total - offset)) }, (_, i) => offset + i);
  };
}

describe("countPaged", () => {
  it("counts an exact record that ends inside the budget", async () => {
    const r = await countPaged(paged(120, 50), 50, 6);
    expect(r.count).toBe(120);
    expect(r.censored).toBe(false);
    expect(r.requests).toBe(3); // 50 + 50 + 20
  });

  it("flags a count that hits the walk budget instead of presenting it as the truth", async () => {
    const r = await countPaged(paged(10_000, 50), 50, 6);
    expect(r.count).toBe(300);
    expect(r.censored).toBe(true);
    expect(r.requests).toBe(6);
  });

  it("treats an empty first page as an exact zero", async () => {
    const r = await countPaged(paged(0, 50), 50, 6);
    expect(r).toMatchObject({ count: 0, censored: false, requests: 1 });
  });
});

describe("measureDepth", () => {
  const base: WalletDepthOptions = {
    sampledClosed: 0,
    sampledOpen: 0,
    sampleClosedCap: 100,
    sampleOpenCap: 100,
    closedPageSize: 50,
    openPageSize: 100,
    maxClosedPages: 6,
    maxOpenPages: 6,
  };

  it("costs zero requests when the sample already is the whole record", async () => {
    const closed = vi.fn(paged(10_000, 50));
    const open = vi.fn(paged(10_000, 100));
    const d = await measureDepth(closed, open, { ...base, sampledClosed: 29, sampledOpen: 88 });
    expect(d).toMatchObject({ closedCount: 29, openCount: 88, totalCount: 117, censored: false, requests: 0 });
    expect(closed).not.toHaveBeenCalled();
    expect(open).not.toHaveBeenCalled();
  });

  it("walks only the side whose sample came back at its ceiling", async () => {
    const closed = vi.fn(paged(180, 50));
    const open = vi.fn(paged(10_000, 100));
    const d = await measureDepth(closed, open, { ...base, sampledClosed: 100, sampledOpen: 41 });
    expect(d.closedCount).toBe(180);
    expect(d.openCount).toBe(41);
    expect(d.totalCount).toBe(221);
    expect(d.closedCensored).toBe(false); // 180 fits inside the 6 x 50 = 300 budget
    expect(d.requests).toBe(4);
    expect(open).not.toHaveBeenCalled();
  });

  it("marks each side censored independently and names the budget", async () => {
    const d = await measureDepth(paged(10_000, 50), paged(70, 100), {
      ...base,
      sampledClosed: 100,
      sampledOpen: 100,
    });
    expect(d).toMatchObject({
      closedCount: 300,
      openCount: 70,
      closedCensored: true,
      openCensored: false,
      censored: true,
      capNote: "closed<=300/open<=600",
    });
    expect(d.requests).toBe(6 + 1);
  });
});
