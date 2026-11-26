import { describe, expect, it } from "vitest";
import {
  DAY_MS,
  DEFAULT_L2_POLICY,
  ceilingVerdict,
  mergeAssetMaps,
  parseAssetMap,
  planL2Retention,
  recentBytesPerDayUpperBound,
  type L2File,
} from "../src/lib/l2-retention";

const NOW = Date.UTC(2026, 10, 25, 20, 0, 0); // 2026-11-25T20:00Z
const GB = 1024 ** 3;
const f = (tokenId: string, bytes: number, ageDays: number): L2File => ({
  tokenId,
  bytes,
  mtimeMs: NOW - ageDays * DAY_MS,
});

describe("planL2Retention guards", () => {
  it("keeps every file younger than minAgeDays even when the corpus is far over the ceiling", () => {
    const files = [f("young-a", 40 * GB, 1), f("young-b", 40 * GB, 59)];
    const plan = planL2Retention(files, {
      nowMs: NOW,
      policy: { ...DEFAULT_L2_POLICY, ceilingBytes: 1 * GB },
    });
    expect(plan.deleteFiles).toBe(0);
    expect(plan.youngFiles).toBe(2);
    expect(plan.overCeilingBytes).toBe(79 * GB);
    expect(plan.unreachableBytes).toBe(79 * GB);
  });

  it("keeps unattributed files by default, and plans them only when told to", () => {
    const files = [f("orphan", 40 * GB, 200)];
    const strict = planL2Retention(files, { nowMs: NOW, policy: { ...DEFAULT_L2_POLICY, ceilingBytes: 1 * GB } });
    expect(strict.deleteFiles).toBe(0);
    expect(strict.unattributedBytes).toBe(40 * GB);

    const loose = planL2Retention(files, {
      nowMs: NOW,
      policy: { ...DEFAULT_L2_POLICY, ceilingBytes: 1 * GB, allowUnattributed: true },
    });
    expect(loose.deleteFiles).toBe(1);
    expect(loose.deleteUnattributedBytes).toBe(40 * GB);
  });

  it("keeps a market with an open or un-stamped leg, at any age", () => {
    const files = [f("t-open", 40 * GB, 200), f("t-null", 40 * GB, 200), f("t-free", 40 * GB, 200)];
    const plan = planL2Retention(files, {
      nowMs: NOW,
      policy: { ...DEFAULT_L2_POLICY, ceilingBytes: 1 * GB },
      tokenToMarket: new Map([
        ["t-open", "mkt-open"],
        ["t-null", "mkt-null"],
        ["t-free", "mkt-free"],
      ]),
      protectedMarkets: new Set(["mkt-open", "mkt-null"]),
    });
    const verdicts = Object.fromEntries(plan.rows.map((r) => [r.tokenId, r.verdict]));
    expect(verdicts["t-open"]).toBe("keep_protected");
    expect(verdicts["t-null"]).toBe("keep_protected");
    expect(verdicts["t-free"]).toBe("delete");
    expect(plan.protectedBytes).toBe(80 * GB);
    expect(plan.deleteBytes).toBe(40 * GB);
  });

  it("deletes nothing at all when the corpus is inside its ceiling, however old it is", () => {
    const files = [f("old-a", 1 * GB, 400), f("old-b", 1 * GB, 300)];
    const plan = planL2Retention(files, {
      nowMs: NOW,
      policy: { ...DEFAULT_L2_POLICY, ceilingBytes: 10 * GB },
      tokenToMarket: new Map([
        ["old-a", "m1"],
        ["old-b", "m2"],
      ]),
    });
    expect(plan.overCeilingBytes).toBe(0);
    expect(plan.deleteFiles).toBe(0);
    expect(plan.rows.every((r) => r.verdict === "keep_under_ceiling")).toBe(true);
  });

  it("frees only as much as the ceiling needs, oldest first", () => {
    const files = [f("a", 1 * GB, 100), f("b", 1 * GB, 200), f("c", 1 * GB, 150)];
    const plan = planL2Retention(files, {
      nowMs: NOW,
      policy: { ...DEFAULT_L2_POLICY, ceilingBytes: 2 * GB },
      tokenToMarket: new Map([
        ["a", "ma"],
        ["b", "mb"],
        ["c", "mc"],
      ]),
    });
    // 3 GB corpus, 2 GB ceiling -> 1 GB must go, and the OLDEST file (b, 200d) is the one.
    expect(plan.deleteFiles).toBe(1);
    expect(plan.rows.find((r) => r.verdict === "delete")?.tokenId).toBe("b");
    expect(plan.unreachableBytes).toBe(0);
  });

  it("stops short of the ceiling rather than deleting a protected file to reach it", () => {
    const files = [f("free", 1 * GB, 200), f("prot", 1 * GB, 300)];
    const plan = planL2Retention(files, {
      nowMs: NOW,
      policy: { ...DEFAULT_L2_POLICY, ceilingBytes: 0 },
      tokenToMarket: new Map([
        ["free", "mf"],
        ["prot", "mp"],
      ]),
      protectedMarkets: new Set(["mp"]),
    });
    expect(plan.deleteFiles).toBe(1);
    expect(plan.deleteBytes).toBe(1 * GB);
    expect(plan.unreachableBytes).toBe(1 * GB);
  });

  it("counts are internally consistent: verdicts partition the corpus", () => {
    const files = [f("a", 3, 10), f("b", 5, 61), f("c", 7, 90), f("d", 11, 500)];
    const plan = planL2Retention(files, {
      nowMs: NOW,
      policy: { ...DEFAULT_L2_POLICY, ceilingBytes: 10 },
      tokenToMarket: new Map([
        ["b", "mb"],
        ["c", "mc"],
      ]),
      protectedMarkets: new Set(["mc"]),
    });
    const sumBytes = plan.rows.reduce((s, r) => s + r.bytes, 0);
    expect(sumBytes).toBe(plan.totalBytes);
    expect(plan.totalFiles).toBe(4);
    expect(plan.youngFiles + plan.unattributedFiles + plan.protectedFiles + plan.rows.filter((r) => r.verdict === "keep_under_ceiling" || r.verdict === "delete").length).toBe(4);
  });

  it("MUTATION CONTROL: an age-only pruner deletes a protected file that this policy keeps", () => {
    const files = [f("young", 1, 10), f("prot", 1, 200), f("orphan", 1, 300)];
    const naive = files.filter((x) => (NOW - x.mtimeMs) / DAY_MS >= 60).map((x) => x.tokenId);
    expect(naive).toEqual(["prot", "orphan"]); // the pre-policy rule a reviewer would have written

    const plan = planL2Retention(files, {
      nowMs: NOW,
      policy: { ...DEFAULT_L2_POLICY, ceilingBytes: 0 },
      tokenToMarket: new Map([["prot", "mp"]]),
      protectedMarkets: new Set(["mp"]),
    });
    const planned = plan.rows.filter((r) => r.verdict === "delete").map((r) => r.tokenId);
    expect(planned).toEqual([]); // both the protected file AND the unattributed one survive
    expect(plan.unreachableBytes).toBe(3);
  });
});

describe("ceiling arithmetic", () => {
  it("upper-bounds the daily rate by whole file size inside the window", () => {
    const files = [f("a", 100, 1), f("b", 200, 6), f("c", 400, 8)];
    expect(recentBytesPerDayUpperBound(files, NOW, 7)).toBeCloseTo(300 / 7, 6);
  });

  it("reports over / inside / projection without inventing a rate", () => {
    expect(ceilingVerdict(30 * GB, 24 * GB, 1)).toEqual({ status: "over", overBytes: 6 * GB, projectedDaysToCeiling: null });
    expect(ceilingVerdict(4 * GB, 24 * GB, 1 * GB)).toEqual({ status: "inside", overBytes: 0, projectedDaysToCeiling: 20 });
    expect(ceilingVerdict(4 * GB, 24 * GB, 0).projectedDaysToCeiling).toBeNull();
  });
});

describe("asset-map sources (recorder + backfill, card l2-asset-map-backfill)", () => {
  it("parses recorder rows into one entry per asset id", () => {
    const text = JSON.stringify({ ts: 1, marketId: "m1", assetIds: ["a", "b"] }) + "\n";
    const p = parseAssetMap(text, "recorder");
    expect(p.rows).toBe(1);
    expect(p.map.size).toBe(2);
    expect(p.map.get("b")).toBe("m1");
  });

  it("attributes a backfill token only when the row says resolved", () => {
    const text = [
      JSON.stringify({ tokenId: "t1", status: "resolved", marketId: "m1", via: "gamma:clob_token_ids&closed=true" }),
      JSON.stringify({ tokenId: "t2", status: "notfound", reason: "gamma_empty" }),
      JSON.stringify({ tokenId: "t3", status: "error", reason: "http_429" }),
      JSON.stringify({ tokenId: "t4", status: "mismatch", reason: "token_absent_from_returned_market" }),
    ].join("\n");
    const p = parseAssetMap(text, "backfill");
    expect(p.rows).toBe(1);
    expect([...p.map.keys()]).toEqual(["t1"]);
    // A measured absence is NOT an attribution: `notfound` must never become a market id.
    expect(p.map.has("t2")).toBe(false);
    expect(p.skipped).toBe(3);
  });

  it("survives a torn last line and counts it as skipped, not as data", () => {
    const text = JSON.stringify({ tokenId: "t1", status: "resolved", marketId: "m1" }) + '\n{"tokenId":"t2","sta';
    const p = parseAssetMap(text, "backfill");
    expect(p.rows).toBe(1);
    expect(p.skipped).toBe(1);
  });

  it("merge: the recorder wins and a disagreement is REPORTED", () => {
    const rec = new Map([
      ["a", "m1"],
      ["b", "m2"],
    ]);
    const back = new Map([
      ["a", "m1"],
      ["b", "DIFFERENT"],
      ["c", "m3"],
    ]);
    const merged = mergeAssetMaps(rec, back);
    expect(merged.map.get("b")).toBe("m2"); // primary wins
    expect(merged.map.get("c")).toBe("m3"); // secondary fills a hole
    expect(merged.fromSecondary).toBe(1);
    expect(merged.conflicts).toEqual([{ tokenId: "b", primary: "m2", secondary: "DIFFERENT" }]);
  });

  it("MUTATION ARM: a file the recorder never saw is unattributable alone and attributable once merged", () => {
    const files = [f("old-token", 40 * GB, 200)];
    const policy = { ...DEFAULT_L2_POLICY, ceilingBytes: 1 * GB };

    const recorderOnly = planL2Retention(files, { nowMs: NOW, policy, tokenToMarket: new Map() });
    expect(recorderOnly.unattributedFiles).toBe(1);
    expect(recorderOnly.deleteFiles).toBe(0); // the guard refuses to plan it

    const backfill = parseAssetMap(
      JSON.stringify({ tokenId: "old-token", status: "resolved", marketId: "m-old" }) + "\n",
      "backfill",
    );
    const merged = mergeAssetMaps(new Map(), backfill.map);
    const planned = planL2Retention(files, { nowMs: NOW, policy, tokenToMarket: merged.map });
    // Now it is a normal over-ceiling candidate: reasoned about, and deletable under policy.
    expect(planned.unattributedFiles).toBe(0);
    expect(planned.deleteFiles).toBe(1);
    expect(planned.rows[0].marketId).toBe("m-old");
  });

  it("MUTATION ARM: a notfound token keeps the file in the unattributed guard", () => {
    const files = [f("gone-token", 40 * GB, 200)];
    const backfill = parseAssetMap(JSON.stringify({ tokenId: "gone-token", status: "notfound" }) + "\n", "backfill");
    const merged = mergeAssetMaps(new Map(), backfill.map);
    const planned = planL2Retention(files, {
      nowMs: NOW,
      policy: { ...DEFAULT_L2_POLICY, ceilingBytes: 1 * GB },
      tokenToMarket: merged.map,
    });
    expect(merged.map.size).toBe(0);
    expect(planned.unattributedFiles).toBe(1);
    expect(planned.deleteFiles).toBe(0);
  });
});
