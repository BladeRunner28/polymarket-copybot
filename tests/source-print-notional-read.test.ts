/**
 * source-print-notional read — pins the instrument, not the verdict
 * (roadmap card `research-source-print-notional`, Lane B, read-only).
 *
 * The card asked whether a C-200 leg copied from a big source print returns less
 * than one copied from a small print. Two ways an instrument like this lies:
 *   (a) it prints a stake-confounded $/leg without saying so, and
 *   (b) it gets the SIGN of the gap backwards and reports the hypothesis as
 *       confirmed (this actually happened in the first draft of the script: the
 *       matched gap was computed big - control, i.e. NEGATIVE of the documented
 *       small - big).
 * Both are pinned here against a fixture book whose answer is known by
 * construction (big prints -0.40/$1, small +0.10/$1, one matching cell):
 *   1. the module's own self-test passes;
 *   2. the planted effect reads +0.500/$1 with the documented sign;
 *   3. with no plant the same harness reads 0.000/$1 (negative control);
 *   4. an epoch with no legs exits 2 and says so — never a clean-looking zero;
 *   5. the artifact states population, clock, level and the notional basis, and
 *      carries the card's six pre-registered conditions plus the fires flag.
 */
import { describe, it, expect, beforeAll } from "vitest";
import { spawnSync } from "child_process";
import fs from "fs";
import os from "os";
import path from "path";

const ROOT = path.join(__dirname, "..");
const SCRIPT = path.join(ROOT, "scripts", "source-print-notional-read.py");
const FIXTURE = path.join(ROOT, "tests", "fixtures", "source-print-notional-fixture.py");

let dir = "";
let planted: any = {};
let nullArm: any = {};
let plantedOut = "";
let emptyOut = "";
let emptyStatus: number | null = null;

function readFixture(dbName: string, plant: boolean, outName: string) {
  const db = path.join(dir, dbName);
  const out = path.join(dir, outName);
  const args = [FIXTURE, db];
  if (plant) args.push("--plant");
  const f = spawnSync("python3", args, { encoding: "utf8" });
  expect(f.status).toBe(0);
  const res = spawnSync(
    "python3",
    [SCRIPT, "--db", db, "--out", out, "--reps", "200", "--no-clusters"],
    { encoding: "utf8" }
  );
  const artifact = fs.existsSync(out) ? JSON.parse(fs.readFileSync(out, "utf8")) : {};
  return { res, artifact };
}

beforeAll(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "srcprint-"));
  const p = readFixture("planted.db", true, "planted.json");
  planted = p.artifact;
  plantedOut = p.res.stdout;
  const n = readFixture("null.db", false, "null.json");
  nullArm = n.artifact;
  const e = spawnSync("python3", [SCRIPT, "--db", path.join(dir, "null.db"), "--epoch", "2027-01-01", "--no-write"], {
    encoding: "utf8",
  });
  emptyOut = e.stdout;
  emptyStatus = e.status;
});

describe("source-print-notional-read", () => {
  it("self-test passes (7/7)", () => {
    const res = spawnSync("python3", [SCRIPT, "--self-test"], { encoding: "utf8" });
    expect(res.status).toBe(0);
    expect(res.stdout).toContain("self-test 7/7 PASS");
  });

  it("planted effect reads with the documented sign: small - big = +0.500/$1", () => {
    expect(planted.matched_roi.n_matched).toBe(6);
    expect(planted.matched_roi.coverage).toBe(1);
    expect(planted.matched_roi.gap).toBeCloseTo(0.5, 6);
    expect(plantedOut).toContain("gap +0.500/$1");
  });

  it("negative control: no plant reads zero on the same harness", () => {
    expect(Math.abs(nullArm.matched_roi.gap)).toBeLessThan(0.02);
  });

  it("an epoch with no legs fails loud instead of printing a clean zero", () => {
    expect(emptyStatus).toBe(2);
    expect(emptyOut).toContain("NO LEGS");
  });

  it("states population, clock, level and the notional basis", () => {
    expect(planted.basis.population).toMatch(/non-demo C-200 legs/);
    expect(planted.basis.clock).toMatch(/openedAt >= 2026-09-04/);
    expect(planted.basis.level).toMatch(/one leg/);
    expect(planted.basis.notional).toMatch(/USDC/);
    expect(planted.basis.notional).toMatch(/never size\*price/);
  });

  it("carries the card's pre-registered conditions and a fires flag", () => {
    const c = planted.rule.conditions;
    expect(Object.keys(c).sort()).toEqual(
      [
        "coverage_ge_0.80",
        "literal_matched_2se_below_gap",
        "literal_raw_gap_ge_1.50_per_leg",
        "n_big_ge_60",
        "primary_2se_below_gap",
        "primary_gap_ge_1.50_per_leg_at_big_stake",
      ].sort()
    );
    // the fixture has 6 big legs, so the n>=60 condition must fail and nothing may change
    expect(c.n_big_ge_60).toBe(false);
    expect(planted.rule.fires).toBe(false);
    expect(planted.rule.decision).toMatch(/DROP the axis/);
  });
});
