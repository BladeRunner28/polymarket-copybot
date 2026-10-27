/**
 * 2026-10-27 (self-audit) — every cron-health-watch alert stamped its local wall time with the
 * literal label "CDT", all year. America/Chicago switches to CST on 2026-11-01, so from that date
 * each alert would read e.g. "04:30 CDT" for 10:30Z: the hour would be right for CST but the label
 * would claim a zone that puts it at 05:30 — an hour of confusion exactly when an operator is
 * trying to correlate an outage against UTC logs.
 *
 * Measured before the fix (TZ=America/Chicago): fmt(2026-12-15T10:30Z) -> '2026-12-15 04:30 CDT'.
 * The fix takes the abbreviation from the same astimezone() conversion as the hour (%Z), so the
 * two cannot disagree, while an explicit tzname argument still wins (nothing passes one today).
 */

import { describe, it, expect } from "vitest";
import { execFileSync } from "child_process";
import fs from "fs";
import os from "os";
import path from "path";

const SCRIPT = path.join(__dirname, "..", "scripts", "cron-scripts", "cron-health-watch.py");

function fmtOf(isoUtc: string): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "chw-fmt-"));
  const driver = path.join(dir, "driver.py");
  fs.writeFileSync(
    driver,
    [
      "import importlib.util, sys",
      "from datetime import datetime",
      "spec = importlib.util.spec_from_file_location('chw', sys.argv[1])",
      "mod = importlib.util.module_from_spec(spec)",
      "spec.loader.exec_module(mod)",
      "print(mod.fmt(datetime.fromisoformat(sys.argv[2])))",
    ].join("\n")
  );
  return execFileSync("python3", [driver, SCRIPT, isoUtc], {
    encoding: "utf8",
    env: { ...process.env, TZ: "America/Chicago" },
  }).trim();
}

describe("cron-health-watch fmt(): the zone label must match the hour it is labelling", () => {
  it("labels a December timestamp CST (10:30Z -> 04:30 CST), not CDT", () => {
    expect(fmtOf("2026-12-15T10:30:00+00:00")).toBe("2026-12-15 04:30 CST");
  });

  it("still labels a July timestamp CDT (10:30Z -> 05:30 CDT)", () => {
    expect(fmtOf("2026-07-15T10:30:00+00:00")).toBe("2026-07-15 05:30 CDT");
  });

  it("changes label across the 2026-11-01 DST boundary", () => {
    expect(fmtOf("2026-10-31T10:30:00+00:00")).toMatch(/CDT$/);
    expect(fmtOf("2026-11-02T10:30:00+00:00")).toMatch(/CST$/);
  });
});
