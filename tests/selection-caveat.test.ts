import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { pickClaim, selectionCaveatLine, type SelectionRead } from "../src/lib/selection-caveat";

const artifact = (over: Partial<SelectionRead> = {}): SelectionRead => ({
  generatedAt: "2026-11-12T15:03:45+00:00",
  legs: 12823,
  claims: [
    {
      claim: "BANKROLL_200 lane [leg clock]",
      level: "leg",
      n_trials: 72,
      p: 1.0,
      sr0: 0.5965,
      verdict: "NOT_DISTINGUISHABLE_FROM_SELECTION",
      moments: { n: 2818, mean: 0.0718, sr: 0.0501 },
    },
    {
      claim: "STANDARD lane [leg clock]",
      level: "leg",
      n_trials: 72,
      p: 1.0,
      sr0: 0.5965,
      verdict: "NOT_DISTINGUISHABLE_FROM_SELECTION",
      moments: { n: 10005, mean: 0.0943, sr: 0.0799 },
    },
  ],
  ...over,
});

function write(obj: unknown): string {
  const dir = mkdtempSync(path.join(tmpdir(), "selcaveat-"));
  const f = path.join(dir, "read.json");
  writeFileSync(f, typeof obj === "string" ? obj : JSON.stringify(obj));
  return f;
}

describe("selection caveat (deflated Sharpe -> report text)", () => {
  it("prints the measured NOT-DISTINGUISHABLE verdict with its basis", () => {
    const line = selectionCaveatLine(write(artifact()));
    expect(line).toContain("N=72");
    expect(line).toContain("NOT distinguishable from selection");
    expect(line).toContain("p=1.0000");
    expect(line).toContain("SR0 0.597");
    expect(line).toContain("12823 settled legs");
    expect(line).toContain("gross of fees");
    expect(line).toContain("no claim survives");
  });

  it("says SURVIVES when a claim clears the bar — the same code path can go both ways", () => {
    const a = artifact();
    a.claims![0] = { ...a.claims![0], p: 0.002, verdict: "SURVIVES" };
    const line = selectionCaveatLine(write(a));
    expect(line).toContain("C-200 SURVIVES");
    expect(line).toContain("survives: BANKROLL_200 lane [leg clock]");
  });

  it("a missing artifact is NOT a clean bill of health — it must print NOT MEASURED", () => {
    const line = selectionCaveatLine(write({}) /* no claims */);
    expect(line).toContain("NOT MEASURED");
    expect(line).not.toContain("distinguishable from selection");
  });

  it("an unreadable file does not throw and does not read as measured", () => {
    const line = selectionCaveatLine(write("{not json"));
    expect(line).toContain("NOT MEASURED");
    expect(line).toContain("unreadable");
  });

  it("an absent file path is reported, not swallowed", () => {
    const line = selectionCaveatLine(path.join(tmpdir(), "definitely-absent-selection-read.json"));
    expect(line).toContain("NOT MEASURED");
  });

  it("picks the leg-clock claim for a lane even when a day claim appears first", () => {
    const a = artifact();
    a.claims!.unshift({
      claim: "BANKROLL_200 lane [exit-day clock]",
      level: "day",
      n_trials: 72,
      p: 1.0,
      verdict: "NOT_DISTINGUISHABLE_FROM_SELECTION",
      moments: { n: 100, sr: 0.2857 },
    });
    const picked = pickClaim(a, "BANKROLL_200");
    expect(picked?.level).toBe("leg");
    expect(picked?.moments?.n).toBe(2818);
  });
});
