/**
 * frozen-artifacts — the machine that enforces "we agreed not to touch this".
 *
 * Card: `phil-frozen-artifact-tripwire`. The freeze discipline in this repo has been prose: a
 * roadmap note says a band is unresolved until a date, or that an artifact is a frozen copy, and
 * the only thing standing between that artifact and an edit is reviewer attention. Two things
 * follow from that, and both have already happened here: (1) a frozen copy gets rewritten by the
 * very run it was meant to judge (scripts/snapshot-kalshi-shadow-oos.py documents that failure —
 * the 7d refit erased the OOS verdict, hence data/shadow-score-model-frozen-*.json); (2) a freeze
 * silently outlives or predeceases its window, because nothing computes the window.
 *
 * THE DESIGN IS DELIBERATELY DUMB: the frozen set is a dated JSON list with a sha256 per artifact.
 * Not a prose rule, not a review checklist — a digest. The set is therefore machine-visible
 * (requirement b), the failure quotes the freeze's own reason (requirement a), and the manifest is
 * digest-pinned by a separate file so editing the set is a visible, separately-committed act
 * (requirement c, to the limit of what this repo can express — there is no CI here; see the
 * card note).
 *
 * THREE KINDS OF FAILURE, kept apart on purpose:
 *   changed  a file on the list no longer hashes to its recorded digest
 *   missing  a file on the list is gone
 *   touched  a caller-supplied change set (a commit range, a staged diff) names a frozen path
 *            while its window is open — this is the pre-commit/CI shape, and it is the only arm
 *            that can catch a GOOD edit before it lands
 *
 * EXPIRY IS NOT A VIOLATION, IT IS A LINT THAT MUST BE ANSWERED. A window that has closed is
 * reported as `expired` and the caller is expected to retire or renew it in the same pass; the
 * gate refuses to treat an expired entry as protection, so a freeze cannot quietly become
 * permanent by neglect. Similarly a freeze whose window is open is ENFORCED even if the entry is
 * old — the window is derived from the entry's own dates, never from "we last looked at it".
 *
 * Pure: no DB, no clock read, no filesystem access. The caller supplies `readFile` and `now`, so
 * the CLI, the test suite and a future CI hook all share one definition of "violated".
 */

import { createHash } from "node:crypto";

export type FreezeApproval = {
  /** ISO date (YYYY-MM-DD) on which a human said yes, and in what words. */
  date: string;
  by: string;
  quote: string;
};

export type FrozenArtifact = {
  path: string;
  sha256: string;
  /** Why THIS file, one line. Empty means the entry's reason covers it. */
  note?: string;
};

export type FreezeEntry = {
  id: string;
  /** The freeze's own reason, printed verbatim on a trip. */
  reason: string;
  /** YYYY-MM-DD, inclusive. */
  frozenFrom: string;
  /** YYYY-MM-DD, inclusive; null = open-ended (a settled artifact that must never change). */
  frozenUntil: string | null;
  approval: FreezeApproval;
  artifacts: FrozenArtifact[];
};

export type FreezeManifest = {
  version: number;
  updatedAt: string;
  entries: FreezeEntry[];
};

/** The digest pin. Any edit to the manifest must be accompanied by an edit here. */
export type FreezePin = {
  manifestSha256: string;
  /** ids whose window is expected to be CLOSED today. A surprise here is a hard failure. */
  expectedExpired: string[];
  note: string;
};

export type Violation = {
  kind: "changed" | "missing" | "touched";
  freezeId: string;
  path: string;
  expected?: string;
  actual?: string | null;
  /** Printed verbatim so a trip explains itself without the reader consulting the roadmap. */
  reason: string;
  frozenUntil: string | null;
};

export type FreezeReport = {
  violations: Violation[];
  expired: Array<{ id: string; frozenUntil: string }>;
  enforced: Array<{ id: string; paths: string[] }>;
};

/** Deterministic JSON: object keys sorted at every depth. Digest stability is the whole point. */
export function canonicalJson(value: unknown): string {
  const walk = (v: unknown): unknown => {
    if (Array.isArray(v)) return v.map(walk);
    if (v && typeof v === "object") {
      const out: Record<string, unknown> = {};
      for (const k of Object.keys(v as Record<string, unknown>).sort()) {
        out[k] = walk((v as Record<string, unknown>)[k]);
      }
      return out;
    }
    return v;
  };
  return JSON.stringify(walk(value));
}

export function sha256Hex(input: string | Buffer): string {
  return createHash("sha256").update(input).digest("hex");
}

export function digestManifest(manifest: FreezeManifest): string {
  return sha256Hex(canonicalJson(manifest));
}

/** End of the entry's last frozen day (UTC), or null for open-ended. */
export function freezeEndsAt(entry: FreezeEntry): Date | null {
  if (!entry.frozenUntil) return null;
  const end = new Date(`${entry.frozenUntil}T23:59:59.999Z`);
  if (Number.isNaN(end.getTime())) {
    throw new Error(`freeze ${entry.id}: unparseable frozenUntil ${entry.frozenUntil}`);
  }
  return end;
}

export function isEnforced(entry: FreezeEntry, now: Date): boolean {
  const start = new Date(`${entry.frozenFrom}T00:00:00.000Z`);
  if (Number.isNaN(start.getTime())) {
    throw new Error(`freeze ${entry.id}: unparseable frozenFrom ${entry.frozenFrom}`);
  }
  if (now.getTime() < start.getTime()) return false;
  const end = freezeEndsAt(entry);
  return end === null ? true : now.getTime() <= end.getTime();
}

export type CheckDeps = {
  manifest: FreezeManifest;
  /** Return the file's bytes, or null when it does not exist. */
  readFile: (relPath: string) => Buffer | null;
  now: Date;
};

/** Verify every enforced entry against the bytes on disk. */
export function checkFrozen({ manifest, readFile, now }: CheckDeps): FreezeReport {
  const violations: Violation[] = [];
  const expired: Array<{ id: string; frozenUntil: string }> = [];
  const enforced: Array<{ id: string; paths: string[] }> = [];

  for (const entry of manifest.entries) {
    if (!isEnforced(entry, now)) {
      if (entry.frozenUntil) expired.push({ id: entry.id, frozenUntil: entry.frozenUntil });
      continue;
    }
    const paths: string[] = [];
    for (const artifact of entry.artifacts) {
      paths.push(artifact.path);
      const buf = readFile(artifact.path);
      if (buf === null) {
        violations.push({
          kind: "missing",
          freezeId: entry.id,
          path: artifact.path,
          expected: artifact.sha256,
          actual: null,
          reason: entry.reason,
          frozenUntil: entry.frozenUntil,
        });
        continue;
      }
      const actual = sha256Hex(buf);
      if (actual !== artifact.sha256) {
        violations.push({
          kind: "changed",
          freezeId: entry.id,
          path: artifact.path,
          expected: artifact.sha256,
          actual,
          reason: entry.reason,
          frozenUntil: entry.frozenUntil,
        });
      }
    }
    enforced.push({ id: entry.id, paths });
  }

  return { violations, expired, enforced };
}

/**
 * The commit/CI shape: given the paths a change is about to touch, report every one that sits on
 * an enforced freeze. This catches a good edit before it lands, which the on-disk check cannot.
 */
export function checkTouchedPaths(
  paths: string[],
  manifest: FreezeManifest,
  now: Date,
): Violation[] {
  const out: Violation[] = [];
  const active = manifest.entries.filter((e) => isEnforced(e, now));
  const seen = new Set<string>();
  for (const p of paths) {
    for (const entry of active) {
      for (const artifact of entry.artifacts) {
        const key = `${entry.id}\u0000${artifact.path}`;
        if (seen.has(key)) continue;
        if (p === artifact.path || p.endsWith(`/${artifact.path}`)) {
          seen.add(key);
          out.push({
            kind: "touched",
            freezeId: entry.id,
            path: artifact.path,
            expected: artifact.sha256,
            reason: entry.reason,
            frozenUntil: entry.frozenUntil,
          });
        }
      }
    }
  }
  return out;
}

/** Manifest-editing bypass check: the pin must describe the manifest that is actually on disk. */
export function verifyPin(
  manifest: FreezeManifest,
  pin: FreezePin,
  now: Date,
): { ok: boolean; problems: string[] } {
  const problems: string[] = [];
  const digest = digestManifest(manifest);
  if (digest !== pin.manifestSha256) {
    problems.push(
      `manifest digest ${digest} != pinned ${pin.manifestSha256} — the frozen set changed; ` +
        `that is an approval-visible act (update the pin in its own commit, with the approval quote)`,
    );
  }
  const expected = [...pin.expectedExpired].sort();
  const actual = manifest.entries
    .filter((e) => !isEnforced(e, now) && e.frozenUntil)
    .map((e) => e.id)
    .sort();
  if (expected.join(",") !== actual.join(",")) {
    problems.push(
      `expired freeze set is [${actual.join(", ") || "none"}] but pinned to [${expected.join(", ") || "none"}] ` +
        `— retire or renew the closed window(s) in the manifest`,
    );
  }
  return { ok: problems.length === 0, problems };
}
