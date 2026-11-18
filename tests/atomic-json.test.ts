import { mkdtempSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { writeJsonAtomic } from "../src/lib/atomic-json";

/**
 * 2026-11-18 self-audit: `fs.writeFileSync(path, json)` opens with O_TRUNC, so a run
 * killed between truncate and (partial) write leaves a prefix. The property that matters
 * for a REPORT reader is not "the write succeeds" but "a failed write never destroys the
 * previous contents" — that is what these pin.
 */
describe("writeJsonAtomic", () => {
  const dir = mkdtempSync(path.join(tmpdir(), "atomic-json-"));

  it("replaces the file with parseable JSON and leaves no temp file", () => {
    const f = path.join(dir, "state.json");
    writeJsonAtomic(f, { a: 1 });
    writeJsonAtomic(f, { a: 2, b: "x" });
    expect(JSON.parse(readFileSync(f, "utf-8"))).toEqual({ a: 2, b: "x" });
    expect(readdirSync(dir).filter((n) => n.includes(".tmp-"))).toEqual([]);
  });

  it("a FAILED write leaves the previous contents intact (the naive write did not)", () => {
    const f = path.join(dir, "keep.json");
    writeJsonAtomic(f, { good: true });
    // unwritable target: the temp path points into a directory that does not exist
    expect(() => writeJsonAtomic(path.join(dir, "nope", "keep.json"), { good: false })).toThrow();
    expect(JSON.parse(readFileSync(f, "utf-8"))).toEqual({ good: true });
    expect(readdirSync(dir).filter((n) => n.includes(".tmp-"))).toEqual([]);
  });

  it("reproduces the truncation the old code could leave behind (control)", () => {
    // what a kill between O_TRUNC and the write body looks like to the reader
    const f = path.join(dir, "half.json");
    writeFileSync(f, '{"lastRunAt":"2026-11-14T06:55:55-06:00","profi');
    expect(() => JSON.parse(readFileSync(f, "utf-8"))).toThrow();
    // and the atomic writer can still repair it from a full object
    writeJsonAtomic(f, { lastRunAt: "2026-11-14T06:55:55-06:00", profiled: 25 });
    expect(JSON.parse(readFileSync(f, "utf-8"))).toEqual({ lastRunAt: "2026-11-14T06:55:55-06:00", profiled: 25 });
  });
});
