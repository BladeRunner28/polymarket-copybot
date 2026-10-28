/**
 * 2026-10-28 (self-audit) — three instrument defects in the per-market leg-cap read.
 *
 * scripts/permarket-leg-cap-read.py produced the pre-registered NO CHANGE verdict for the per-market
 * leg cap. The answer was right; three of the numbers it was justified by were not.
 *
 * DEFECT 1 — SHRINKING DENOMINATOR. Condition (ii) "worst day improved >=50%" compared ABSOLUTE
 * dollars between the uncapped book and a capped book holding 47-83% of its notional, so a cap earned
 * a smaller worst day simply by holding less. Measured live: cap 3 all-time reads +70% on dollars and
 * +44% per dollar at risk — PASS becomes FAIL. Both bases now print; absolute stays the deciding basis
 * because that is what the prereg registered. Changing the deciding basis is Lane A, not a repair.
 *
 * DEFECT 2 — SIGN COLLISION. The per-market table printed the dropped legs' PnL POSITIVE under a name
 * (`dPnl@5`) all but identical to the main table's `dPnL`, which is capped-minus-base and therefore
 * NEGATIVE for the same quantity. Fixture below pins both markets: m-a (dropped legs LOSE money, so
 * the cap helps, +300) and m-d (dropped legs MAKE money, so the cap gives it up, -100). The old
 * output printed those as -300 and +100.
 *
 * DEFECT 3 — MISSING POPULATION. The read only ever loaded settled legs, so the OPEN book — the
 * population a leg cap would actually bind on — was invisible. The prereg's Part A is entirely about
 * bounding risk on that book.
 *
 * Also asserted: $/1k-capital-day, which the prereg's Measurement item 2 requires and which was never
 * printed; and the window-structure block, because the "both windows" gate is one window plus a
 * 15-day July slice on a book only 104 days long.
 */

import { describe, it, expect, beforeAll } from "vitest";
import { execFileSync } from "child_process";
import fs from "fs";
import os from "os";
import path from "path";

const ROOT = path.join(__dirname, "..");
const SCRIPT = path.join(ROOT, "scripts", "permarket-leg-cap-read.py");
const FIXTURE = path.join(ROOT, "tests", "fixtures", "legcap-fixture.py");

let out = "";
let dbPath = "";

beforeAll(() => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "legcap-"));
  dbPath = path.join(dir, "fixture.db");
  execFileSync("python3", [FIXTURE, dbPath], { encoding: "utf8" });
  out = execFileSync("python3", [SCRIPT, "--db", dbPath], { encoding: "utf8" });
});

/** The main table's row for one cap: [legs, kept%, ntl%, pnl, dPnL, pnlPct]. */
function mainRow(cap: number): { pnl: number; dPnl: number } {
  const line = out
    .split("\n")
    .find((l) => new RegExp(`^\\s+${cap}\\s+\\d+\\s+\\d+%\\s+\\d+%`).test(l));
  if (!line) throw new Error(`no main-table row for cap ${cap}`);
  const nums = line.trim().split(/\s+/);
  // cap legs kept% ntl% pnl dPnL PnL% ROI% worst$ wd%ntl wdImp$ wdImp%ntl ex10ROI $/1k-cd
  return { pnl: Number(nums[4].replace(/,/g, "")), dPnl: Number(nums[5].replace(/,/g, "")) };
}

/** The per-market table's last column for one market (signed capped-minus-base). */
function marketDPnl(market: string): number {
  const line = out.split("\n").find((l) => l.trim().startsWith(`${market} `));
  if (!line) throw new Error(`no per-market row for ${market}`);
  const nums = line.trim().split(/\s+/);
  return Number(nums[nums.length - 1].replace(/,/g, ""));
}

describe("permarket-leg-cap-read: the per-market column must share the main table's sign", () => {
  it("prints a POSITIVE delta for a market whose dropped legs lose money (capping helps)", () => {
    expect(marketDPnl("m-a")).toBe(300);
  });

  it("prints a NEGATIVE delta for a market whose dropped legs make money (capping gives it up)", () => {
    // the old code printed +100 here — same magnitude, opposite sign
    expect(marketDPnl("m-d")).toBe(-100);
  });

  it("reconciles: the per-market column sums to the main table's dPnL at the same N", () => {
    const sum = marketDPnl("m-a") + marketDPnl("m-b") + marketDPnl("m-d");
    expect(sum).toBe(mainRow(5).dPnl);
    expect(mainRow(5).dPnl).toBe(200); // -340 uncapped -> -140 at cap 5
  });
});

describe("permarket-leg-cap-read: the tail test must print both denominators", () => {
  it("names which basis decides, and prints the per-dollar basis beside it", () => {
    expect(out).toMatch(/\(ii\) worst day >=50%: .* on registered abs\$/);
    expect(out).toMatch(/per \$ at risk/);
  });

  it("does not report the two bases as the same number when the book shrinks", () => {
    // cap 3 keeps 62% of notional, so the per-dollar improvement must be strictly smaller
    const line = out.split("\n").find((l) => /^\s+3\s+\d+\s+\d+%\s+62%/.test(l))!;
    expect(line).toBeTruthy();
    const nums = line.trim().split(/\s+/);
    const absImp = Number(nums[10].replace(/[+,%]/g, ""));
    const normImp = Number(nums[11].replace(/[+,%]/g, ""));
    expect(absImp).toBe(94);
    expect(normImp).toBe(90);
    expect(normImp).toBeLessThan(absImp);
  });

  it("prints the $/1k-capital-day the prereg's Measurement item 2 requires", () => {
    expect(out).toMatch(/\$\/1k-cd/);
  });
});

describe("permarket-leg-cap-read: the population a cap binds on", () => {
  it("censuses the OPEN book, not just settled history", () => {
    expect(out).toMatch(/OPEN BOOK NOW/);
    expect(out).toMatch(/open: 1 legs \/ 1 markets \/ \$500 notional/);
  });

  it("states which cap levels would actually refuse legs today", () => {
    expect(out).toMatch(/would be refused/);
  });

  it("exposes how much of the all-time veto is the slice the 90d window excludes", () => {
    expect(out).toMatch(/WINDOW STRUCTURE/);
    expect(out).toMatch(/cost from EXCLUDED slice/);
    expect(out).toMatch(/Lane A question/);
  });
});
