/**
 * frozen-artifact-tripwire — trip it, or it is a wish.
 *
 * Card: `phil-frozen-artifact-tripwire`. Checks data/frozen-artifacts.json (the dated frozen set)
 * against the bytes on disk, against the digest pin, and — when handed a change set — against the
 * paths a commit is about to touch. Every failure prints the freeze's own reason and its window,
 * so the trip explains itself.
 *
 * Usage
 *   npx tsx scripts/frozen-artifact-tripwire.ts                 # verify the working tree + pin
 *   npx tsx scripts/frozen-artifact-tripwire.ts --changed HEAD~1..HEAD
 *   npx tsx scripts/frozen-artifact-tripwire.ts --digest        # digest to paste into the pin
 *   npx tsx scripts/frozen-artifact-tripwire.ts --self-test     # negative control: prove it trips
 *
 * Exit 0 clean, 1 tripped/pin-problem, 2 self-test could not prove itself.
 *
 * ROLLBACK: delete data/frozen-artifacts.json, data/frozen-artifacts.pin.json, data/frozen/ and this
 * script + its lib/test. Nothing else reads them, so the bot's behaviour is unchanged either way.
 */

import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, unlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import {
  canonicalJson,
  checkFrozen,
  checkTouchedPaths,
  digestManifest,
  sha256Hex,
  verifyPin,
  type FreezeManifest,
  type FreezePin,
} from "../src/lib/frozen-artifacts";

const ROOT = path.resolve(__dirname, "..");
const MANIFEST = path.join(ROOT, "data/frozen-artifacts.json");
const PIN = path.join(ROOT, "data/frozen-artifacts.pin.json");

const readRel = (rel: string): Buffer | null => {
  try {
    return readFileSync(path.join(ROOT, rel));
  } catch {
    return null;
  }
};

function loadJson<T>(file: string): T {
  return JSON.parse(readFileSync(file, "utf8")) as T;
}

function changedPaths(range: string): string[] {
  const out = execFileSync("git", ["diff", "--name-only", range], { cwd: ROOT, encoding: "utf8" });
  return out.split("\n").map((s) => s.trim()).filter(Boolean);
}

function report(manifest: FreezeManifest, pin: FreezePin, now: Date, touched: string[]): number {
  const r = checkFrozen({ manifest, readFile: readRel, now });
  const pinCheck = verifyPin(manifest, pin, now);
  const touchedViolations = checkTouchedPaths(touched, manifest, now);

  console.log(
    `frozen-artifacts: ${manifest.entries.length} entries, ${r.enforced.length} enforced at ${now.toISOString()}, ` +
      `${r.expired.length} expired`,
  );
  for (const e of r.enforced) console.log(`  ENFORCED  ${e.id}  (${e.paths.length} file${e.paths.length === 1 ? "" : "s"})`);
  for (const e of r.expired) console.log(`  EXPIRED   ${e.id}  window closed ${e.frozenUntil}  -> retire or renew`);

  for (const v of [...r.violations, ...touchedViolations]) {
    console.log("");
    console.log(`TRIPPED [${v.kind}] ${v.path}`);
    console.log(`  freeze:  ${v.freezeId}${v.frozenUntil ? ` (through ${v.frozenUntil})` : " (open-ended)"}`);
    console.log(`  reason:  ${v.reason}`);
    if (v.kind === "changed") console.log(`  digest:  recorded ${v.expected}\n           on disk  ${v.actual}`);
    if (v.kind === "missing") console.log(`  digest:  recorded ${v.expected}, file is GONE`);
    if (v.kind === "touched") console.log(`  digest:  recorded ${v.expected} — this change would land ON a frozen file`);
  }

  let exit = 0;
  if (r.violations.length + touchedViolations.length > 0) {
    console.log(`\nFAIL — ${r.violations.length + touchedViolations.length} frozen-artifact trip(s).`);
    exit = 1;
  }
  if (!pinCheck.ok) {
    console.log("\nFAIL — frozen set / pin disagreement:");
    for (const p of pinCheck.problems) console.log(`  - ${p}`);
    exit = 1;
  }
  if (exit === 0) console.log("\nOK — every enforced freeze matches its recorded digest.");
  return exit;
}

/**
 * NEGATIVE CONTROL. A tripwire nobody has tripped is a wish, so this builds a throwaway manifest
 * over a throwaway file and asserts all four arms fire — including that the printed violation
 * carries the freeze's reason. If this mode ever prints FAIL, the wire is decorative.
 */
function selfTest(): number {
  console.log("self-test: proving each arm trips");
  const dir = mkdtempSync(path.join(tmpdir(), "frozen-selftest-"));
  const victim = path.join(dir, "victim.json");
  const manifestPath = path.join(dir, "manifest.json");
  const reason = "SELF-TEST freeze reason: this file is the thing under judgement";
  let failures = 0;
  const expect = (label: string, cond: boolean, detail = "") => {
    console.log(`  ${cond ? "PASS" : "FAIL"}  ${label}${detail ? `  (${detail})` : ""}`);
    if (!cond) failures += 1;
  };

  try {
    writeFileSync(victim, '{"fit":"original"}\n');
    const digest = sha256Hex(readFileSync(victim));
    const manifest: FreezeManifest = {
      version: 1,
      updatedAt: "2026-01-01T00:00:00Z",
      entries: [
        {
          id: "self-test-entry",
          reason,
          frozenFrom: "2026-01-01",
          frozenUntil: "2999-12-31",
          approval: { date: "2026-01-01", by: "self-test", quote: "self-test" },
          artifacts: [{ path: victim, sha256: digest }],
        },
      ],
    };
    writeFileSync(manifestPath, canonicalJson(manifest));
    const now = new Date("2026-06-01T00:00:00Z");
    const readAbs = (p: string) => {
      try { return p === victim || p === manifestPath ? readFileSync(p) : null; } catch { return null; }
    };

    const clean = checkFrozen({ manifest, readFile: readAbs, now });
    expect("untouched file passes", clean.violations.length === 0);

    writeFileSync(victim, '{"fit":"refit-overwrote-it"}\n');
    const changed = checkFrozen({ manifest, readFile: readAbs, now });
    expect("edited file trips CHANGED", changed.violations.length === 1 && changed.violations[0].kind === "changed");
    expect("trip quotes the freeze reason", changed.violations[0]?.reason === reason);

    unlinkSync(victim);
    const missing = checkFrozen({ manifest, readFile: readAbs, now });
    expect("deleted file trips MISSING", missing.violations.length === 1 && missing.violations[0].kind === "missing");

    const touched = checkTouchedPaths([victim], manifest, now);
    expect("a commit touching the path trips TOUCHED", touched.length === 1 && touched[0].kind === "touched");
    const untouched = checkTouchedPaths(["src/lib/rules.ts"], manifest, now);
    expect("an unrelated path does not trip", untouched.length === 0);

    const afterWindow = checkFrozen({ manifest, readFile: () => Buffer.from("anything"), now: new Date("3000-01-01T00:00:00Z") });
    expect("an expired window stops enforcing", afterWindow.violations.length === 0 && afterWindow.expired.length === 1);

    const pinOk = verifyPin(manifest, { manifestSha256: digestManifest(manifest), expectedExpired: [], note: "" }, now);
    expect("matching pin passes", pinOk.ok);
    const pinBad = verifyPin(manifest, { manifestSha256: "0".repeat(64), expectedExpired: [], note: "" }, now);
    expect("an edited manifest trips the pin", !pinBad.ok);
    const pinExpiredMismatch = verifyPin(
      manifest,
      { manifestSha256: digestManifest(manifest), expectedExpired: [], note: "" },
      new Date("3000-01-01T00:00:00Z"),
    );
    expect("a newly expired freeze trips the pin's expiry list", !pinExpiredMismatch.ok);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }

  if (failures > 0) {
    console.log(`\nSELF-TEST FAIL — ${failures} arm(s) did not trip. The wire is decorative until fixed.`);
    return 2;
  }
  console.log("\nSELF-TEST PASS — every arm trips with its reason quoted.");
  return 0;
}

function main(): void {
  const argv = process.argv.slice(2);
  if (argv.includes("--self-test")) process.exit(selfTest());
  if (argv.includes("--digest")) {
    console.log(digestManifest(loadJson<FreezeManifest>(MANIFEST)));
    return;
  }
  const i = argv.indexOf("--changed");
  const touched = i >= 0 && argv[i + 1] ? changedPaths(argv[i + 1]) : [];
  if (i >= 0 && touched.length === 0 && !argv[i + 1]) {
    console.log("FAIL — --changed needs a git range (e.g. HEAD~1..HEAD)");
    process.exit(1);
  }
  const now = new Date();
  process.exit(report(loadJson<FreezeManifest>(MANIFEST), loadJson<FreezePin>(PIN), now, touched));
}

main();
