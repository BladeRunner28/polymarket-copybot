/**
 * 2026-10-27 (self-audit) — the weather sampler's freshness probe must actually be able to FAIL.
 *
 * Defect this pins (scripts/weather-nowcast-freshness.py): the wrapper's contract says "the newest
 * row in THIS city's file must be from THIS run", but the check only had an UPPER bound
 * (`--max-age-min 75`). With hourly ticks, a run that wrote nothing leaves the PREVIOUS tick's row
 * ~60 min old — under the bar — so the probe printed nothing and exited 0. Measured on a fixture
 * holding only the previous tick's rows: silent, healthy-looking. A dead city would have taken two
 * ticks to surface, and a one-venue outage never surfaced at all (see the sampler's gate).
 *
 * Second defect found while writing the fix: the wrapper passes its stamp as
 * `date +%Y-%m-%dT%H:%M:%S%z` -> "2026-10-27T06:44:34-0500", which
 * `datetime.fromisoformat` REJECTS (it wants -05:00). The first version of the "this tick" bound
 * parsed the stamp to None and switched itself off — a probe that cannot fail, again. The third
 * test pins the compact-offset parse so that cannot come back.
 */

import { describe, it, expect } from "vitest";
import { execFileSync } from "child_process";
import fs from "fs";
import os from "os";
import path from "path";

const SCRIPT = path.join(__dirname, "..", "scripts", "weather-nowcast-freshness.py");

function isoMinus(minutes: number): string {
  return new Date(Date.now() - minutes * 60_000).toISOString().replace(/\.\d+Z$/, "+00:00");
}

/** A tick file: one bracket row + the coverage row the sampler always writes last. */
function writeTick(dir: string, name: string, ts: string, coverage: Record<string, unknown> = {}): string {
  const p = path.join(dir, name);
  const rows = [
    { kind: "bracket", venue: "polymarket", ts, instrument: "x", bracket_high: 90 },
    {
      kind: "coverage",
      ts,
      et_hour: 6,
      kalshi_cycles: 1,
      kalshi_brackets: 6,
      pm_cycles: 2,
      pm_brackets: 22,
      errors: [],
      dropped: [],
      ...coverage,
    },
  ];
  fs.writeFileSync(p, rows.map((r) => JSON.stringify(r)).join("\n") + "\n");
  return p;
}

/** `+%Y-%m-%dT%H:%M:%S%z` in local time — exactly what the wrapper passes. */
function wrapperStamp(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  const off = -d.getTimezoneOffset();
  const sign = off >= 0 ? "+" : "-";
  const oh = p(Math.floor(Math.abs(off) / 60));
  const om = p(Math.abs(off) % 60);
  return (
    `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}` +
    `T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}${sign}${oh}${om}`
  );
}

function run(file: string, stamp: string): string {
  try {
    return execFileSync("python3", [SCRIPT, file, stamp, "nyc"], { encoding: "utf8" }).trim();
  } catch (e: any) {
    // the probe exits 0 by design; a throw here is a real failure
    return `THREW: ${e?.message ?? e}`;
  }
}

describe("weather-nowcast-freshness: 'must be from THIS tick'", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "wx-fresh-"));

  it("alerts when the newest row is the PREVIOUS tick's (60 min old, inside the 75 min window)", () => {
    const f = writeTick(dir, "prev.jsonl", isoMinus(60));
    const out = run(f, wrapperStamp(new Date()));
    expect(out).toMatch(/wrote nothing THIS tick/);
    expect(out).toMatch(/60 min old/);
  });

  it("stays silent when the newest row IS from this tick", () => {
    const f = writeTick(dir, "now.jsonl", isoMinus(0));
    expect(run(f, wrapperStamp(new Date()))).toBe("");
  });

  it("parses the wrapper's compact -0500 stamp (the bound must not disable itself)", () => {
    // row from the previous tick, stamp written the way `date +%Y-%m-%dT%H:%M:%S%z` writes it
    const f = writeTick(dir, "compact.jsonl", isoMinus(60));
    const stamp = wrapperStamp(new Date());
    expect(stamp).toMatch(/[+-]\d{4}$/); // no colon — the form fromisoformat used to reject
    expect(run(f, stamp)).toMatch(/wrote nothing THIS tick/);
  });

  it("still alerts on an old row through the max-age branch", () => {
    const f = writeTick(dir, "old.jsonl", isoMinus(180));
    expect(run(f, wrapperStamp(new Date()))).toMatch(/min old at .* - the lane wrote nothing this tick/);
  });

  it("still alerts when the file is missing entirely", () => {
    expect(run(path.join(dir, "nope.jsonl"), wrapperStamp(new Date()))).toMatch(/no readable sample row/);
  });
});
