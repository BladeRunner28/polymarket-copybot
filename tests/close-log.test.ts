/**
 * close-log — the early-exit reason sidecar.
 *
 * Pins the property the reviews depend on: every early close leaves a line that can be
 * joined to PaperTrade by id, carrying the reason string that `closePaperTrade` used to
 * discard. Without it, v66's pre-registered refutation ("first 20 ORGANIC stopped legs")
 * cannot be evaluated at all, because `status='closed'` is shared by the stale stop and the
 * dead-slug 404 expiry.
 */
import { describe, expect, it } from "vitest";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { appendCloseReason, closeLogPath, type CloseReasonRecord } from "../src/lib/close-log";

const rec = (o: Partial<CloseReasonRecord> = {}): CloseReasonRecord => ({
  id: "pt_1",
  botId: "STANDARD",
  marketId: "will-x-win",
  outcome: "NO",
  entryPrice: 0.71,
  exitPrice: 0.2,
  sizeUsd: 10.4,
  pnl: -7.42,
  ageHours: 2000,
  reason: "stale 2000h >= 168h scoped stop (entry 0.71 >= 0.60) -- v66",
  ...o,
});

describe("close-reason sidecar", () => {
  it("appends one JSONL line carrying id, botId and the reason verbatim", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "close-log-"));
    const line = appendCloseReason(rec(), dir);
    expect(line).toContain("v66");
    const rows = fs
      .readFileSync(closeLogPath(dir), "utf8")
      .trim()
      .split("\n")
      .map((l) => JSON.parse(l));
    expect(rows).toHaveLength(1);
    expect(rows[0].id).toBe("pt_1");
    expect(rows[0].botId).toBe("STANDARD");
    expect(rows[0].reason).toContain("v66");
    expect(rows[0].ageHours).toBe(2000);
    expect(typeof rows[0].at).toBe("string");
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it("is append-only: two closes leave two lines, in order", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "close-log-"));
    appendCloseReason(rec({ id: "a", reason: "dead slug 404" }), dir);
    appendCloseReason(rec({ id: "b", reason: "stale 200h -- v66" }), dir);
    const ids = fs
      .readFileSync(closeLogPath(dir), "utf8")
      .trim()
      .split("\n")
      .map((l) => JSON.parse(l).id);
    expect(ids).toEqual(["a", "b"]);
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it("never throws when the directory cannot be written", () => {
    // /dev/null/nope is not a directory on any platform we run on.
    expect(appendCloseReason(rec(), "/dev/null/nope")).toBeNull();
  });
});
