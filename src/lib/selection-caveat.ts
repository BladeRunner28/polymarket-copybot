/**
 * selection-caveat — carry the multiple-testing verdict INTO the report text.
 *
 * WHY (roadmap card tradememory-deflated-sharpe, APPROVED 2026-10-21, Lane B)
 *   Every rule version v2..v72 was admitted on a measured edge, and each was
 *   chosen after seeing the previous versions' results. The card's pre-registered
 *   decision rule: p >= 0.05 or INSUFFICIENT_DATA => every ladder/phase claim
 *   carries the explicit caveat "not distinguishable from selection".
 *
 *   `scripts/deflated-sharpe-read.py` measures it and writes
 *   `data/deflated-sharpe-read.json`. This module is the only reader: the report
 *   prints the measured verdict, and prints "NOT MEASURED" when the artifact is
 *   missing or unreadable — a missing measurement must never look like a clean
 *   bill of health (the silent-alert defect class this board keeps repairing).
 *
 * READ-ONLY: no decision, rule, size or gate reads this. It is text only.
 */

import { readFileSync } from "node:fs";

export const SELECTION_CAVEAT_FILE = "data/deflated-sharpe-read.json";

/** Subset of data/deflated-sharpe-read.json that the report needs. */
export interface SelectionClaim {
  claim: string;
  level: "leg" | "day";
  n_trials: number;
  p: number | null;
  sr0?: number;
  verdict: string;
  moments?: { n?: number; mean?: number; sr?: number | null };
}

export interface SelectionRead {
  generatedAt?: string;
  legs?: number;
  claims?: SelectionClaim[];
  basis?: Record<string, string>;
}

const f = (x: number | null | undefined, dp = 3): string =>
  typeof x === "number" && Number.isFinite(x) ? x.toFixed(dp) : "—";

/** Pick the lane claim on the leg clock — the most conservative published arm. */
export function pickClaim(read: SelectionRead, lane: string): SelectionClaim | undefined {
  const claims = read.claims ?? [];
  return (
    claims.find((c) => c.claim.toLowerCase().startsWith(lane.toLowerCase()) && c.level === "leg") ??
    claims.find((c) => c.claim.toLowerCase().startsWith(lane.toLowerCase()))
  );
}

/**
 * One report line. Returns a NOT-MEASURED line (never undefined) when the
 * measurement is absent or unreadable.
 */
export function selectionCaveatLine(file: string = SELECTION_CAVEAT_FILE): string {
  let read: SelectionRead;
  try {
    read = JSON.parse(readFileSync(file, "utf8")) as SelectionRead;
  } catch (e) {
    const why = e instanceof Error ? e.message : String(e);
    return `• ⚠️ Multiple-testing caveat: NOT MEASURED (${file} unreadable: ${why}) — run scripts/deflated-sharpe-read.py before quoting any ladder claim`;
  }
  const c200 = pickClaim(read, "BANKROLL_200");
  const std = pickClaim(read, "STANDARD");
  if (!c200 || typeof c200.p !== "number") {
    return `• ⚠️ Multiple-testing caveat: NOT MEASURED (${file} carries no BANKROLL_200 claim) — do not quote ladder claims as edge`;
  }
  const survivors = (read.claims ?? []).filter((c) => c.verdict === "SURVIVES").map((c) => c.claim);
  const n = read.legs ?? c200.moments?.n;
  const head = `• Multiple-testing (deflated Sharpe, N=${c200.n_trials} committed rule variants, lower bound): `;
  const body =
    c200.p < 0.05
      ? `C-200 SURVIVES (p=${f(c200.p, 4)}, SR ${f(c200.moments?.sr)} vs best-of-N SR0 ${f(c200.sr0)})`
      : `C-200 NOT distinguishable from selection (p=${f(c200.p, 4)}: SR ${f(c200.moments?.sr)} vs best-of-N SR0 ${f(c200.sr0)})`;
  const stdTxt =
    std && typeof std.p === "number"
      ? ` · STANDARD p=${f(std.p, 4)}`
      : "";
  const surv = survivors.length ? ` · survives: ${survivors.join("; ")}` : " · no claim survives";
  return `${head}${body}${stdTxt}${surv} · basis: ${n ?? "?"} settled legs, regime=journal ruleSetVersion, per $1 staked gross of fees, read ${read.generatedAt?.slice(0, 16).replace("T", " ") ?? "undated"}Z`;
}
