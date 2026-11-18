/**
 * Atomic JSON writes for small state files that a REPORT reads.
 *
 * WHY (2026-11-18 self-audit): `data/scan-wallets-state.json` was written with
 * `fs.writeFileSync(path, json)`, which opens with O_TRUNC — the old contents are gone
 * before the new bytes are written. A run killed inside that window (this job's runs
 * were killed 10 times in a row at the harness ceiling on 2026-11-13) leaves a truncated
 * file. The EOD report then could not parse it, and the wallet-scan row vanished from
 * the report entirely rather than reporting a damaged record.
 *
 * Write to a sibling temp file, fsync-free but same-filesystem, then rename over the
 * target: rename(2) is atomic, so a reader always sees either the complete old file or
 * the complete new one — never a prefix. If the write fails, the ORIGINAL file is
 * untouched (that is the property the naive version lacked).
 */

import { renameSync, unlinkSync, writeFileSync } from "node:fs";

export function writeJsonAtomic(path: string, obj: unknown, pretty = true): void {
  const tmp = `${path}.tmp-${process.pid}`;
  try {
    writeFileSync(tmp, pretty ? JSON.stringify(obj, null, 2) : JSON.stringify(obj));
    renameSync(tmp, path);
  } catch (e) {
    // never leave a partial temp file behind for the next reader to trip on
    try {
      unlinkSync(tmp);
    } catch {
      /* the temp file may never have been created */
    }
    throw e;
  }
}
