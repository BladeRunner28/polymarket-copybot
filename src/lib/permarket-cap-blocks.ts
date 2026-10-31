/**
 * permarket-cap-blocks — the v55 per-market rail, read back out of the journal,
 * and the price of the legs it refused.
 *
 * WHY THIS EXISTS (2026-10-30, permarket-legs-rail-finding):
 * The card's evidence came from `scripts/replay-market-cap.ts --days 30`, a
 * time-ordered replay over C-200 legs AS BOOKED. That instrument has two basis
 * defects on this rail, and both make its headline unreproducible:
 *
 *   1. It cannot see a refused leg. A leg the rail blocked never becomes a
 *      PaperTrade, so the replay can only ever price the book's OWN duplicates —
 *      a counterfactual about legs the rail already admitted, not the effect of
 *      the rail. Re-run on 2026-10-30, `--days 30` reports 0 blocked legs while
 *      the journal records 46 leg-clause refusals in the same 30 days.
 *   2. Its window excludes pre-window stock. The rail counts legs that are OPEN
 *      (`status: "open"` rows, scripts/score-trades.ts ~line 212), whatever their
 *      vintage; the replay counts legs OPENED inside the window. Every stack the
 *      rail is actually holding back is invisible to it: the book's 90d window
 *      shows the same defect in the other direction (391 legs "blocked" at the
 *      replay's window-cumulative leg count vs 366 on a real open-seat basis).
 *
 * The leg the rail actually refused is in the journal: DecisionJournal.risksJson
 * carries `BANKROLL_200: v55 per-market cap (legs 3 > max 2)` (or the notional
 * clause). That is the population this module reads.
 *
 * The rail ALSO has the phantom-seat defect the v45 slug cap had (see
 * slug-cap-blocks.ts): the seat is taken when the decision PASSES this gate
 * (score-trades.ts ~line 1059) and is never released when a LATER gate refuses
 * the copy, so one run can fill the two seats with refused attempts. The live
 * count is therefore not the journal's count, and every refusal is classified
 * against the book's own open/close intervals.
 */

/** Which clause of the v55 rail refused the leg. */
export type PerMarketClause = "legs" | "notional";

/** One refused leg, parsed from a journal `risksJson` blob. */
export type PerMarketCapBlock = {
  clause: PerMarketClause;
  /** the open-leg count the decision would have made (legs clause) */
  wouldBeLegs?: number;
  /** the cap in force at decision time (legs clause) */
  maxLegs?: number;
  /** projected per-market notional had the leg been taken (notional clause) */
  projectedNotional?: number;
  /** the notional ceiling in force at decision time (notional clause) */
  notionalCap?: number;
};

// Anchored on the exact strings scripts/score-trades.ts writes (~line 1057). A
// looser pattern would also match prose about the rail inside a card note.
const BLOCK_RE =
  /v55 per-market cap \((legs (\d+) > max (\d+)|notional \$([\d.]+) > cap \$([\d.]+))\)/g;

/** Every per-market-cap block recorded on one decision row (usually 0 or 1). */
export function parsePerMarketCapBlocks(risksJson: string | null | undefined): PerMarketCapBlock[] {
  if (!risksJson) return [];
  const out: PerMarketCapBlock[] = [];
  BLOCK_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = BLOCK_RE.exec(risksJson)) !== null) {
    if (m[2] !== undefined) {
      const wouldBeLegs = Number(m[2]);
      const maxLegs = Number(m[3]);
      if (!Number.isFinite(wouldBeLegs) || !Number.isFinite(maxLegs)) continue;
      out.push({ clause: "legs", wouldBeLegs, maxLegs });
    } else {
      const projectedNotional = Number(m[4]);
      const notionalCap = Number(m[5]);
      if (!Number.isFinite(projectedNotional) || !Number.isFinite(notionalCap)) continue;
      out.push({ clause: "notional", projectedNotional, notionalCap });
    }
  }
  return out;
}

export function isPerMarketCapBlock(risksJson: string | null | undefined): boolean {
  return parsePerMarketCapBlocks(risksJson).length > 0;
}

/**
 * Was this refusal a REAL seat, or a seat held by a copy that a later gate
 * refused? `openAt` is the true state of this marketId at decision time,
 * reconstructed from the booked legs' own open/close intervals; `sizeUsd` is the
 * size the refused copy would have taken (the caller's own sizing, null when
 * unknown).
 *
 * `unknown` is a real answer, not a fallback: it is returned whenever the caller
 * cannot reconstruct the ground truth, so an unclassifiable refusal can never be
 * counted as evidence for either arm.
 */
export type BlockClass = "genuine" | "phantom" | "unknown";

export type OpenAtDecision = { legs: number; notional: number };

export function classifyBlock(
  block: PerMarketCapBlock,
  openAt: OpenAtDecision | null,
  sizeUsd: number | null
): BlockClass {
  if (openAt === null) return "unknown";
  if (block.clause === "legs") {
    const max = block.maxLegs ?? 0;
    if (max <= 0) return "unknown";
    return openAt.legs >= max ? "genuine" : "phantom";
  }
  const cap = block.notionalCap ?? 0;
  if (cap <= 0) return "unknown";
  // The size the refused copy would have taken is often absent from the journal
  // (77 of 79 refusals carry no simulatedPositionSize). That does not make every
  // notional refusal unclassifiable: if the market ALREADY held more than the
  // ceiling, the rail was right whatever the size, so the answer is genuine. Only
  // the ambiguous middle is left unknown.
  if (sizeUsd === null) return openAt.notional >= cap ? "genuine" : "unknown";
  return openAt.notional + sizeUsd > cap ? "genuine" : "phantom";
}

/**
 * Human line for a refusal's cause, used in the artifact and the stdout table.
 * Kept next to the parser so a label can never drift from the string it names.
 */
export function describeBlock(b: PerMarketCapBlock): string {
  if (b.clause === "legs") return `legs ${b.wouldBeLegs} > max ${b.maxLegs}`;
  return `notional $${(b.projectedNotional ?? 0).toFixed(2)} > cap $${(b.notionalCap ?? 0).toFixed(2)}`;
}
