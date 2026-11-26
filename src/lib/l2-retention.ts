/**
 * l2-retention — a retention POLICY for the L2 book corpus, expressed in the quantity
 * disk actually pays, with the evidence that would be lost named on every plan.
 *
 * WHY THIS EXISTS (2026-11-25, card `l2-retention-cron`):
 * `data/l2/` is an append-only corpus — one JSONL file per CLOB asset id, one top-25
 * book snapshot every 5s (scripts/record-l2.ts). Nothing anywhere in cron or scripts
 * pruned or rotated it, so by 2026-09-03..2026-11-25 it had reached 59,316 files /
 * 30.67 GB apparent (30.92 GB allocated). It is gitignored, so unlike the Kalshi tape
 * it costs only disk, not the object store.
 *
 * THE THING THAT MAKES THIS A POLICY AND NOT A `rm`:
 * these files are the ONLY book windows that exist for the days they cover. Four
 * instruments read them by token id at a past instant (c200-printthrough,
 * c200-bookwalk-taker, standard-fill-stamp, c200-intent-watch), and 12,490 of 13,517
 * non-demo paper legs carry fillStatus = NULL — i.e. the corpus is still the input the
 * fill adjudication would use if it were re-run over the back book. A delete is
 * irreversible and cannot be re-recorded, so this module NEVER deletes: it plans, and
 * every plan carries the byte count of what would be destroyed.
 *
 * SECOND LIMIT, MEASURED AND PRINTED RATHER THAN ASSUMED:
 * 26,520 of 59,316 files (6.31 GB) have no market in data/l2-asset-map.jsonl, because
 * the map is appended by record-l2.ts only from the commit that added it (~2026-09-27);
 * every file older than 60d predates it. A file that cannot be attributed cannot be
 * reasoned about (is it a market we traded? one we refused?), so those files are kept
 * unless the caller explicitly allows unattributed deletion.
 *
 * BASIS, stated once: level = one L2 file (one CLOB asset id); clock = file mtime
 * (append-only, so mtime is the last observation); size = apparent bytes (st_size).
 * On this volume apparent bytes and allocated blocks agree to <1% (30.67 vs 30.92 GB).
 */

export type L2File = {
  tokenId: string;
  bytes: number;
  mtimeMs: number;
};

export type L2RetentionPolicy = {
  /** Never plan a delete for a file younger than this. Also the window the live instruments read. */
  minAgeDays: number;
  /** Total apparent bytes the corpus is allowed to occupy. */
  ceilingBytes: number;
  /** Plan unattributed files for deletion too. Default false: see the second limit above. */
  allowUnattributed: boolean;
};

export const DAY_MS = 86_400_000;

/**
 * 60 days / 24 GiB. The ceiling is chosen so it is EXCEEDED by today's corpus (30.67 GB):
 * a ceiling that today's number already sits under would be decoration. 60 days covers
 * every window the fill instruments read (the oldest dispatch a fill read touches is
 * 30d) with a 2x margin, and is long enough that a re-run of any published read from
 * the last two months still has its raw material.
 */
export const DEFAULT_L2_POLICY: L2RetentionPolicy = {
  minAgeDays: 60,
  ceilingBytes: 24 * 1024 ** 3,
  allowUnattributed: false,
};

export type L2Verdict =
  | "keep_young"
  | "keep_unattributed"
  | "keep_protected"
  | "keep_under_ceiling"
  | "delete";

export type L2PlanRow = {
  tokenId: string;
  marketId: string | null;
  bytes: number;
  mtimeMs: number;
  ageDays: number;
  verdict: L2Verdict;
};

export type L2Plan = {
  rows: L2PlanRow[];
  totalFiles: number;
  totalBytes: number;
  deleteFiles: number;
  deleteBytes: number;
  /** Bytes the plan destroys that belong to files it could not attribute. Must be 0 unless allowUnattributed. */
  deleteUnattributedBytes: number;
  overCeilingBytes: number;
  /** Over-ceiling bytes the guards would not let the plan reach. Non-zero is the honest answer, not a failure. */
  unreachableBytes: number;
  unattributedFiles: number;
  unattributedBytes: number;
  protectedFiles: number;
  protectedBytes: number;
  youngFiles: number;
  youngBytes: number;
  oldestAgeDays: number;
};

/**
 * Plan (never perform) the deletion of L2 files.
 *
 * Order of the guards matters and is the whole design:
 *   1. young        -> keep, unconditionally (a ceiling never justifies deleting a window
 *                      an instrument may still be reading);
 *   2. unattributed -> keep unless allowUnattributed (cannot be reasoned about);
 *   3. protected    -> keep (the market has an open leg, an un-stamped leg, or a live intent);
 *   4. remaining    -> delete OLDEST FIRST, and only until the ceiling is met. A corpus
 *                      under its ceiling deletes nothing, no matter how old it is.
 */
export function planL2Retention(
  files: L2File[],
  opts: {
    nowMs: number;
    policy?: L2RetentionPolicy;
    tokenToMarket?: Map<string, string>;
    protectedMarkets?: Set<string>;
  },
): L2Plan {
  const policy = opts.policy ?? DEFAULT_L2_POLICY;
  const tokenToMarket = opts.tokenToMarket ?? new Map<string, string>();
  const protectedMarkets = opts.protectedMarkets ?? new Set<string>();

  const rows: L2PlanRow[] = [];
  let totalBytes = 0;
  let totalFiles = 0;
  let unattributedFiles = 0;
  let unattributedBytes = 0;
  let protectedFiles = 0;
  let protectedBytes = 0;
  let youngFiles = 0;
  let youngBytes = 0;
  let oldestAgeDays = 0;

  for (const f of files) {
    const ageDays = (opts.nowMs - f.mtimeMs) / DAY_MS;
    const marketId = tokenToMarket.get(f.tokenId) ?? null;
    totalFiles += 1;
    totalBytes += f.bytes;
    if (ageDays > oldestAgeDays) oldestAgeDays = ageDays;

    let verdict: L2Verdict;
    if (ageDays < policy.minAgeDays) {
      verdict = "keep_young";
      youngFiles += 1;
      youngBytes += f.bytes;
    } else if (marketId === null && !policy.allowUnattributed) {
      verdict = "keep_unattributed";
      unattributedFiles += 1;
      unattributedBytes += f.bytes;
    } else if (marketId !== null && protectedMarkets.has(marketId)) {
      verdict = "keep_protected";
      protectedFiles += 1;
      protectedBytes += f.bytes;
    } else {
      verdict = "keep_under_ceiling"; // provisional: the ceiling pass decides
    }
    rows.push({ tokenId: f.tokenId, marketId, bytes: f.bytes, mtimeMs: f.mtimeMs, ageDays, verdict });
  }

  // Ceiling pass: oldest first, only as far as needed.
  const overCeilingBytes = Math.max(0, totalBytes - policy.ceilingBytes);
  const candidates = rows
    .filter((r) => r.verdict === "keep_under_ceiling")
    .sort((a, b) => b.ageDays - a.ageDays || a.tokenId.localeCompare(b.tokenId));

  let need = overCeilingBytes;
  let deleteFiles = 0;
  let deleteBytes = 0;
  let deleteUnattributedBytes = 0;
  for (const r of candidates) {
    if (need <= 0) break;
    r.verdict = "delete";
    deleteFiles += 1;
    deleteBytes += r.bytes;
    if (r.marketId === null) deleteUnattributedBytes += r.bytes;
    need -= r.bytes;
  }

  return {
    rows,
    totalFiles,
    totalBytes,
    deleteFiles,
    deleteBytes,
    deleteUnattributedBytes,
    overCeilingBytes,
    unreachableBytes: Math.max(0, need),
    unattributedFiles,
    unattributedBytes,
    protectedFiles,
    protectedBytes,
    youngFiles,
    youngBytes,
    oldestAgeDays,
  };
}

/**
 * Bytes written per day over the last `days`, as the sum of the CURRENT size of every
 * file whose mtime falls inside the window, divided by `days`. That is an UPPER bound:
 * a file touched once today contributes its whole size even if it was 99% written
 * earlier. Named as a bound so nobody quotes it as an exact rate.
 */
export function recentBytesPerDayUpperBound(files: L2File[], nowMs: number, days = 7): number {
  const from = nowMs - days * DAY_MS;
  let bytes = 0;
  for (const f of files) if (f.mtimeMs >= from) bytes += f.bytes;
  return bytes / days;
}

export type CeilingVerdict = {
  status: "inside" | "over";
  overBytes: number;
  /** Days until the ceiling is reached at the measured upper-bound rate. null = not growing, or already over. */
  projectedDaysToCeiling: number | null;
};

export function ceilingVerdict(
  totalBytes: number,
  ceilingBytes: number,
  growthBytesPerDay: number,
): CeilingVerdict {
  const overBytes = Math.max(0, totalBytes - ceilingBytes);
  if (overBytes > 0) return { status: "over", overBytes, projectedDaysToCeiling: null };
  if (growthBytesPerDay <= 0) return { status: "inside", overBytes: 0, projectedDaysToCeiling: null };
  return {
    status: "inside",
    overBytes: 0,
    projectedDaysToCeiling: (ceilingBytes - totalBytes) / growthBytesPerDay,
  };
}

/* ------------------------------------------------------------------ attribution sources
 *
 * SECOND SOURCE (2026-11-26, card `l2-asset-map-backfill`): the recorder's map only starts
 * ~2026-09-27, so 26,520 files recorded before it had no market. scripts/l2-asset-backfill.py
 * attributes those through gamma (`?clob_token_ids=<tok>&closed=true`, accepted only when the
 * returned market's own clobTokenIds contain the token) into a SEPARATE ledger, because
 * appending to a file a live process also appends to is how a ledger gets a torn line in the
 * middle. The retention read merges both, and the merge DECLARES its precedence: the recorder
 * wins, and a disagreement is COUNTED rather than silently resolved, because two sources that
 * disagree about one token is a defect somebody has to look at.
 */

export type AssetMapSource = "recorder" | "backfill";

export type ParsedAssetMap = {
  map: Map<string, string>;
  /** Parsed rows that contributed at least one token. */
  rows: number;
  /** Rows that were present but contributed nothing (unparsable, or a non-resolved backfill row). */
  skipped: number;
};

/**
 * Parse one source. Tolerant by design: an append-only file can end mid-line, and a skip is
 * counted, never thrown — a failed parse that throws would stop a read-only measurement.
 *
 *   recorder rows: {marketId, assetIds:[...]}
 *   backfill rows: {tokenId, status:"resolved"|"notfound"|"mismatch"|"error", marketId?}
 *                  ONLY `resolved` with a marketId attributes a file. `notfound` is a measured
 *                  absence (gamma has no market for that token) and must never be read as one.
 */
export function parseAssetMap(text: string, source: AssetMapSource): ParsedAssetMap {
  const map = new Map<string, string>();
  let rows = 0;
  let skipped = 0;
  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    let row: Record<string, unknown>;
    try {
      row = JSON.parse(line) as Record<string, unknown>;
    } catch {
      skipped += 1; // torn last line
      continue;
    }
    if (source === "recorder") {
      const mid = row.marketId;
      const ids = row.assetIds;
      if (typeof mid !== "string" || !Array.isArray(ids)) {
        skipped += 1;
        continue;
      }
      for (const a of ids) if (typeof a === "string") map.set(a, mid);
      rows += 1;
    } else {
      const tok = row.tokenId;
      if (typeof tok !== "string") {
        skipped += 1;
        continue;
      }
      if (row.status !== "resolved" || typeof row.marketId !== "string") {
        skipped += 1; // notfound/mismatch/error: an absence, not an attribution
        continue;
      }
      map.set(tok, row.marketId);
      rows += 1;
    }
  }
  return { map, rows, skipped };
}

export type AssetMapConflict = { tokenId: string; primary: string; secondary: string };

/**
 * Merge two sources, primary wins. Conflicts are returned, not swallowed: on this corpus the
 * backfill and the recorder must agree, so a non-zero count means one of them is wrong.
 */
export function mergeAssetMaps(
  primary: Map<string, string>,
  secondary: Map<string, string>,
): { map: Map<string, string>; conflicts: AssetMapConflict[]; fromSecondary: number } {
  const map = new Map(primary);
  const conflicts: AssetMapConflict[] = [];
  let fromSecondary = 0;
  for (const [tok, mid] of secondary) {
    const existing = map.get(tok);
    if (existing === undefined) {
      map.set(tok, mid);
      fromSecondary += 1;
    } else if (existing !== mid) {
      conflicts.push({ tokenId: tok, primary: existing, secondary: mid });
    }
  }
  return { map, conflicts, fromSecondary };
}
