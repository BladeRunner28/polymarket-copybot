/**
 * Fee exit basis — both fee instruments charged an exit at the leg's ENTRY price
 * (2026-11-02, card `fee-exit-basis-instruments`, Lane B instrument repair).
 *
 * scripts/c200-fee-reprice-archive.py set `ex_docs = entry_docs` and
 * scripts/fee-sign-flip-test.py did `cur *= 2.0`. The fee law is p*(1-p), which goes to
 * zero at the payoff extremes, so an entry-priced exit inflated the exit leg ~4x on the
 * legs this book actually leaves (83.4% of closed legs step out below 0.05 or above 0.80).
 *
 * Both instruments now price the exit through scripts/lib/fee_exit.py at the leg's own
 * exit price (PaperTrade.currentPrice, identity c = p*(1+pnl/size) as fallback) and print
 * the per-basis counts. This file pins four things:
 *   1. the shared module's own self-test passes;
 *   2. it FAILS when the old defect is restored — a detector that cannot fail is the
 *      exact instrument this card exists to replace;
 *   3. both instruments, run end to end on a fixture book, bill the exit at the exit
 *      (hand-computed arithmetic, no magic totals);
 *   4. neither instrument prints the withdrawn basis as current truth without labelling it.
 */
import { describe, it, expect, beforeAll } from "vitest";
import { execFileSync, spawnSync } from "child_process";
import fs from "fs";
import os from "os";
import path from "path";

const ROOT = path.join(__dirname, "..");
const MODULE = path.join(ROOT, "scripts", "lib", "fee_exit.py");
const FIXTURE = path.join(ROOT, "tests", "fixtures", "fee-exit-fixture.py");
const NEGCTL = path.join(ROOT, "tests", "fixtures", "fee-exit-negctl.py");
const C200 = path.join(ROOT, "scripts", "c200-fee-reprice-archive.py");
const FLIP = path.join(ROOT, "scripts", "fee-sign-flip-test.py");

const RATE = 0.05; // fixture markets resolve to category "other" in both instruments
const LEGS = {
  a: { p: 0.57, c: 0.02, size: 10 },  // stepped out at 0.02 — the leg the bug inflated ~12x
  b: { p: 0.30, size: 5 },            // resolved at 0: entry fee only, no sale
  c: { p: 0.53, c: 0.90, size: 5 },
};

function ppFee(entry: number, exit: number, size: number): number {
  const shares = size / entry;
  return shares * RATE * exit * (1 - exit);
}

// corrected: every exit priced at the price it traded at
const EXPECTED_CORRECTED =
  ppFee(LEGS.a.p, LEGS.a.p, LEGS.a.size) + ppFee(LEGS.a.p, LEGS.a.c, LEGS.a.size) +
  ppFee(LEGS.b.p, LEGS.b.p, LEGS.b.size) +
  ppFee(LEGS.c.p, LEGS.c.p, LEGS.c.size) + ppFee(LEGS.c.p, LEGS.c.c, LEGS.c.size);
// withdrawn: exit charged at the entry price
const EXPECTED_WITHDRAWN =
  2 * ppFee(LEGS.a.p, LEGS.a.p, LEGS.a.size) +
  ppFee(LEGS.b.p, LEGS.b.p, LEGS.b.size) +
  2 * ppFee(LEGS.c.p, LEGS.c.p, LEGS.c.size);

let c200Out = "";
let flipOut = "";
let flipJson: any = {};
let dir = "";

beforeAll(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "feeexit-"));
  const db = path.join(dir, "fixture.db");
  const cache = path.join(dir, "cache.json");
  const out = path.join(dir, "flip.json");
  execFileSync("python3", [FIXTURE, db], { encoding: "utf8" });
  fs.writeFileSync(cache, JSON.stringify({
    "0xcondlegA": { state: "ok", taker: 1000, maker: 0 },
    "0xcondlegB": { state: "ok", taker: 1000, maker: 0 },
    "0xcondlegC": { state: "ok", taker: 1000, maker: 0 },
  }));
  c200Out = execFileSync("python3", [C200, "--db", db], { encoding: "utf8" });
  flipOut = execFileSync("python3", [FLIP, "--db", db, "--cache", cache, "--out", out], { encoding: "utf8" });
  flipJson = JSON.parse(fs.readFileSync(out, "utf8"));
});

describe("fee_exit module", () => {
  it("self-test passes", () => {
    const res = spawnSync("python3", [MODULE], { encoding: "utf8" });
    expect(res.status).toBe(0);
    expect(res.stdout).toContain("self-test OK");
  });

  it("self-test FAILS when the old entry-priced exit is restored (the detector can fail)", () => {
    const res = spawnSync("python3", [NEGCTL], { encoding: "utf8" });
    expect(res.status).toBe(1);
    expect(res.stdout).toContain("SELF-TEST FAILED");
    expect(res.stdout).toContain("far cheaper than exit-at-entry");
  });
});

describe("c200-fee-reprice-archive", () => {
  it("names the exit basis with population, clock and level", () => {
    expect(c200Out).toMatch(/EXIT PRICE BASIS: observed PaperTrade\.currentPrice 2, identity fallback 0, undetermined 0/);
    expect(c200Out).toContain("level=leg");
    expect(c200Out).toMatch(/closed-leg clock: closedAt up to \d{4}-\d{2}-\d{2}T/);
  });

  it("bills the exit at the exit, and prints the withdrawn basis beside it", () => {
    const corrected = EXPECTED_CORRECTED.toFixed(2);
    const withdrawn = EXPECTED_WITHDRAWN.toFixed(2);
    expect(corrected).not.toBe(withdrawn);
    expect(c200Out).toContain(corrected);
    expect(c200Out).toContain(withdrawn);
    expect(c200Out).toContain("WITHDRAWN basis (exit charged at entry)");
  });

  it("does not silently restate the old total as the live one", () => {
    // the two-fee docs model must be the corrected number, not 2x the entry fee
    expect(flipJson.feeCurrentUsd).toBeCloseTo(EXPECTED_CORRECTED, 2);
    expect(flipJson.feeCurrentUsd).not.toBeCloseTo(EXPECTED_WITHDRAWN, 2);
  });
});

describe("fee-sign-flip-test", () => {
  it("charges both arms at the leg's own exit price", () => {
    expect(flipJson.feeCurrentUsd).toBeCloseTo(EXPECTED_CORRECTED, 2);
    expect(flipJson.feeVenueUsd).toBeCloseTo(EXPECTED_CORRECTED, 2);
    expect(flipJson.withdrawnBasisFeeCurrentUsd).toBeCloseTo(EXPECTED_WITHDRAWN, 2);
  });

  it("reports the exit-price basis and the cross-check in the artifact", () => {
    expect(flipJson.exitBasis.observedCurrentPrice).toBe(2);
    expect(flipJson.exitBasis.undetermined).toBe(0);
    expect(flipJson.exitBasis.crossChecked).toBe(2);
    expect(flipJson.exitBasis.disagreements).toBe(0);
  });

  it("says the withdrawn basis overstated the bill instead of quoting it as a fee", () => {
    expect(flipOut).toContain("WITHDRAWN basis (exit charged at entry)");
    expect(flipOut).toMatch(/overstated the fee bill by \$0\.27/);
    expect(flipOut).toContain(`whole history in ${path.join(dir, "fixture.db")}`);
  });
});
