import { mkdtempSync, writeFileSync as fsWriteFileSync, readFileSync as fsReadFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { walletScanLine, walletScanLineText } from "../src/lib/report";

/**
 * 2026-11-14 self-audit.
 *
 * `data/scan-wallets-state.json` is written at the END of a successful run. Between
 * 2026-11-13 11:08 and 2026-11-14 05:17 ten scheduled runs were killed at the harness'
 * 3600 s ceiling and nothing was profiled for 20 h — yet the daily line read
 *   `• Wallet scan: 25 profiled last run (11:08) · pool 3,903, 0 stale >7d · 0 partials in 7d`
 * i.e. a dead job rendered exactly like a fresh one: no date, and the killed attempts had
 * no representation at all. These cases pin the three states apart: a completed run, a
 * completed run whose figures are stale, and an attempt that never completed.
 */
const NOW = new Date("2026-11-14T07:30:00-06:00"); // run time of the audit
const opts = { pool: 3903, stale7d: 0, partials: "0 partials in 7d", now: NOW };

describe("wallet-scan line tells a killed attempt from a completed run", () => {
  it("a fresh completed run prints its time-of-day without a date (same local day)", () => {
    const line = walletScanLineText(
      { lastRunAt: "2026-11-14T06:55:55-06:00", lastAttemptAt: "2026-11-14T06:46:00-06:00", profiled: 25, target: 25 },
      opts
    );
    expect(line).toBe("• Wallet scan: 25 profiled last run 06:55 (34m ago) · pool 3,903, 0 stale >7d · 0 partials in 7d");
    // The old rendering of this exact state — the defect being closed:
    expect(line).not.toBe("• Wallet scan: 25 profiled last run (06:55) · pool 3,903, 0 stale >7d · 0 partials in 7d");
    expect(line).not.toContain("did NOT complete");
  });

  it("a run from a PREVIOUS day names the day — the old line printed a bare 11:08", () => {
    const line = walletScanLineText({ lastRunAt: "2026-11-13T11:08:44-06:00", profiled: 25, target: 25 }, opts);
    expect(line).toContain("last run 11-13 11:08 (20.4h ago)");
    expect(line).not.toContain("last run 11:08 (");
  });

  it("an attempt that never completed is its own state, never a clean quiet cycle (the 2026-11-14 defect)", () => {
    const line = walletScanLineText(
      {
        lastRunAt: "2026-11-13T11:08:44-06:00",
        lastAttemptAt: "2026-11-14T06:17:44-06:00", // 10th killed attempt
        profiled: 25,
        target: 25,
      },
      opts
    );
    expect(line).toContain("⚠️ last attempt 06:17 (1.2h ago) did NOT complete");
    expect(line).toContain("last completion 11-13 11:08 (20.4h ago)");
    // The old rendering of this exact state — the defect being closed:
    expect(line).not.toBe("• Wallet scan: 25 profiled last run (11:08) · pool 3,903, 0 stale >7d · 0 partials in 7d");
    expect(line).not.toContain("25 profiled last run 06:17");
  });

  it("an attempt with NO completion on record says so instead of printing a bogus run", () => {
    const line = walletScanLineText({ lastAttemptAt: "2026-11-14T06:17:44-06:00" }, opts);
    expect(line).toContain("did NOT complete — no completed run on record");
  });

  it("an attempt INSIDE the harness ceiling is a run in progress, not a warning", () => {
    // The scan legitimately takes ~9 min; calling that "did NOT complete" would be the
    // mirror-image lie of the defect being closed.
    const line = walletScanLineText(
      { lastRunAt: "2026-11-14T05:00:00-06:00", lastAttemptAt: "2026-11-14T07:28:00-06:00", profiled: 25, target: 25 },
      opts
    );
    expect(line).not.toContain("did NOT complete");
    expect(line).toBe("• Wallet scan: 25 profiled last run 05:00 (2.5h ago) · pool 3,903, 0 stale >7d · 0 partials in 7d");
  });

  it("a state file written before 2026-11-14 (no lastAttemptAt) still renders", () => {
    const line = walletScanLineText({ lastRunAt: "2026-11-14T06:00:00-06:00", profiled: 25, target: 25 }, opts);
    expect(line).toBe("• Wallet scan: 25 profiled last run 06:00 (1.5h ago) · pool 3,903, 0 stale >7d · 0 partials in 7d");
  });

  it("a short batch still flags the batch cap it fell short of", () => {
    const line = walletScanLineText(
      { lastRunAt: "2026-11-14T06:55:00-06:00", profiled: 17, target: 25 },
      opts
    );
    expect(line).toContain("⚠️ 17 profiled last run 06:55");
    expect(line).toContain("of 25 attempted");
  });

  it("no state at all prints nothing rather than a fabricated line", () => {
    expect(walletScanLineText({}, opts)).toBeUndefined();
  });
});

/**
 * 2026-11-18 self-audit: the READ side of the same file. `walletScanLine` returned
 * undefined on an unreadable state file, and the report drops undefined lines — so a
 * truncated JSON (the file was written non-atomically, at the START of every run) made
 * the whole wallet-scan row disappear rather than say it could not be judged.
 */
describe("wallet-scan line never disappears, it degrades loudly", () => {
  const dir = mkdtempSync(path.join(tmpdir(), "scanline-"));
  const write = (name: string, body: string) => {
    const f = path.join(dir, name);
    fsWriteFileSync(f, body);
    return f;
  };

  it("an ABSENT state file says no run is on record", async () => {
    const line = await walletScanLine(NOW, path.join(dir, "absent.json"));
    expect(line).toContain("NO STATE ON RECORD");
    expect(line).toContain("NOT a quiet cycle");
  });

  it("a TRUNCATED state file (killed mid-write) says UNAVAILABLE, not silence", async () => {
    const f = write("half.json", '{"lastRunAt":"2026-11-14T06:55:55-06:00","profi');
    const line = await walletScanLine(NOW, f);
    expect(line).toContain("UNAVAILABLE");
    expect(line).toContain("damaged");
    expect(line).toContain("NOT a quiet cycle");
  });

  it("a state file with no figures at all says UNMEASURED", async () => {
    const f = write("nofigures.json", JSON.stringify({ lastAlertAtMs: 1 }));
    expect(await walletScanLine(NOW, f)).toContain("UNMEASURED");
  });

  it("a healthy state file renders the pre-fix line (pool segment comes from the live DB)", async () => {
    const f = write(
      "ok.json",
      JSON.stringify({ lastRunAt: "2026-11-14T06:55:55-06:00", lastAttemptAt: "2026-11-14T06:46:00-06:00", profiled: 25, target: 25 })
    );
    const line = await walletScanLine(NOW, f);
    const expectedHead = walletScanLineText(
      JSON.parse(fsReadFileSync(f, "utf-8")),
      opts
    )!.split(" · pool ")[0];
    expect(line.split(" · pool ")[0]).toBe(expectedHead);
    expect(line).toContain("25 profiled last run 06:55");
  });
});
