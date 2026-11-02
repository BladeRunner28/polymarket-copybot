/**
 * Skip-reason levels — the fact sheet printed one population twice and captioned
 * it as two (2026-11-02, Lane B instrument repair).
 *
 * scripts/research-collect.py prints the skip-reason mix at "DECISION level" and at
 * "ENTRY level". Every observed run printed character-identical top-5 counts, while
 * the ENTRY caption claimed "these SUMS exceed the row count" — i.e. the caption
 * promised a difference it never showed — and the DECISION caption ("one count per
 * skipped decision") read as if its counts summed to the decision count.
 *
 * Measured live 2026-11-02 (24h, 400 newest skips, DecisionJournal.createdAt):
 * 916 tag entries over 400 rows, 353/400 rows carry more than one entry, so the
 * ENTRY totals really do exceed the row count; within-row duplicate entries = 0,
 * which is why the two lists agree tag-for-tag. Across 30d the same rate is
 * 0/75,958 entries, so the agreement is a measured property, not a construction.
 *
 * This file pins both halves:
 *   (1) the instrument must DETECT divergence when a decision repeats a tag
 *       (fixture s2) — otherwise its "0 duplicates" reading on live data is
 *       unfalsifiable, which is the defect class this card exists for;
 *   (2) the fact-sheet caption must print the measured reconciliation numbers
 *       and must not go back to asserting them.
 */
import { describe, it, expect, beforeAll } from "vitest";
import { execFileSync } from "child_process";
import fs from "fs";
import os from "os";
import path from "path";

const ROOT = path.join(__dirname, "..");
const SCRIPT = path.join(ROOT, "scripts", "skip-reason-level-read.py");
const FIXTURE = path.join(ROOT, "tests", "fixtures", "skip-reason-fixture.py");
const COLLECT = path.join(ROOT, "scripts", "research-collect.py");

let out = "";
let dbPath = "";

beforeAll(() => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "skiplvl-"));
  dbPath = path.join(dir, "fixture.db");
  execFileSync("python3", [FIXTURE, dbPath], { encoding: "utf8" });
  out = execFileSync("python3", [SCRIPT, "--db", dbPath, "--hours", "100000"], { encoding: "utf8" });
});

describe("skip-reason level read", () => {
  it("excludes non-refusals and reports the population honestly", () => {
    expect(out).toContain("4 rows");
    expect(out).toContain("tagged 3");
    expect(out).toContain("bare 1");
  });

  it("measures entry inflation (entries > rows) and within-row duplicates separately", () => {
    expect(out).toMatch(/L2 entries: 6 tag entries over 4 rows/);
    expect(out).toMatch(/L3 within-row duplicate entries: 1/);
  });

  it("DETECTS divergence on the repeated tag (the levels are not the same number here)", () => {
    expect(out).toContain("VERDICT: levels DIVERGE on 1 tag(s)");
    expect(out).toMatch(/v45 blacklist category "cs2" dec=1\/ent=2/);
  });

  it("prints a basis line for every number", () => {
    expect(out).toContain("BASIS: every count above is refusal-level");
  });

  it("self-test proves the detector can fail", () => {
    const st = execFileSync("python3", [SCRIPT, "--self-test"], { encoding: "utf8" });
    expect(st).toContain("PASS");
    expect(st).toContain("repeat case seen (dec/ent/dup) = (1, 2, 1)");
  });
});

describe("research-collect skip-reason caption", () => {
  const src = fs.readFileSync(COLLECT, "utf8");

  it("no longer asserts a relationship it does not print", () => {
    expect(src).not.toContain("these SUMS exceed the row count");
    expect(src).not.toContain("one count per skipped decision; ");
  });

  it("prints the measured reconciliation inline", () => {
    expect(src).toContain("n_dups += len(items) - len(seen_here)");
    expect(src).toContain("within-row duplicate entries");
    expect(src).toContain("these counts sum to {sum(dec_cnt.values())} entries");
    expect(src).toContain("lines differ ONLY where a decision repeats a tag");
  });
});
