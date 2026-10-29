/**
 * Outcome resolution — did the token this copy bought actually win?
 *
 * WHY THIS EXISTS: Polymarket markets are binary *token* markets, but the token
 * labels are not always Yes/No. Sports, esports, handicaps and totals carry the
 * real names — "Vitality", "9z", "Dynasty", "Under", "Team Liquid". The old code
 * hard-coded `winningOutcome = yesPrice > 0.5 ? "YES" : "NO"` and compared it to
 * the trade's stored label, which could never match for those markets, so
 * EVERY such position was booked as a full-stake loss regardless of the truth
 * (audited 2026-09-13: 70 confirmed phantom losses, −$828 booked where +$942 was
 * owed). The same guess was in five call sites with three different casings.
 *
 * CONTRACT: `didOutcomeWin` answers true / false / **null**. null means "this
 * data cannot determine the outcome" and callers MUST NOT book a loss on it —
 * leave the position alone and retry. Booking a loss on unknown data is what
 * created the phantom losses in the first place.
 */

/** Compare tokens by alphanumerics only, uppercased: "Team Liquid" = "TEAMLIQUID" = "team liquid". */
export function normalizeOutcomeLabel(value: string | null | undefined): string {
  if (!value) return "";
  return String(value).replace(/[^a-z0-9]/gi, "").toUpperCase();
}

export type ResolutionInput = {
  /**
   * Label of the winning token as the venue reports it ("Yes", "Under",
   * "Vitality"). Preferred — it is the ground truth when present.
   */
  winningLabel?: string | null;
  /**
   * Fallback for markets that expose no labels: price of the first (YES) token.
   * Only used when the trade's own outcome label is YES/NO, so binary behaviour
   * stays exactly as it always was.
   */
  yesPrice?: number | null;
};

/** Terminal band for a settled binary TOKEN price. Venues leave 0.001/0.999
 *  residue, so 1c is the practical floor and ceiling. */
export const SETTLED_MARK_HI = 0.99;
export const SETTLED_MARK_LO = 0.01;

/**
 * `won` for a CLOSED-POSITION row out of the data API.
 *
 * WHY THIS IS NOT `curPrice > 0.5 || realizedPnl > 0` (the expression it
 * replaces): a closed position is not a settled one. `curPrice` is a MARK, and
 * `realizedPnl > 0` is our own EXIT price — crediting either as a settled win
 * says "we sold at a profit" or "the mark was above .5", never "the token this
 * wallet held actually resolved in its favour". Measured on 607 closed legs
 * from 16 wallets (30d lookback, fetched 2026-10-29T01:05Z): the old expression
 * booked 411 wins (67.7%) where the settlement read is 66.6%, i.e. 7 of 601
 * settlement-knowable legs (1.2%) were awarded a win they did not earn, and 0
 * settled wins were called losses.
 *
 * @returns true (settled on the winning side), false (settled on the losing
 *          side), or null when the mark is inside the band — the market is not
 *          settled, so this row cannot state a win at all.
 */
export function settledWinFromMark(curPrice: number | null | undefined): boolean | null {
  if (typeof curPrice !== "number" || !Number.isFinite(curPrice)) return null;
  if (curPrice >= SETTLED_MARK_HI) return true;
  if (curPrice <= SETTLED_MARK_LO) return false;
  return null;
}

/**
 * Did the token labelled `tradeOutcome` win?
 *
 * @returns true (won), false (lost), or null when undeterminable.
 */
export function didOutcomeWin(tradeOutcome: string | null | undefined, input: ResolutionInput): boolean | null {
  const want = normalizeOutcomeLabel(tradeOutcome);
  if (!want) return null; // empty/absent label — nothing to compare against

  const winner = normalizeOutcomeLabel(input.winningLabel);
  if (winner) {
    if (winner === want) return true;
    // A binary Yes/No market can only ever resolve to YES or NO, so a non-binary
    // trade label against it means the labels describe different markets — do
    // not guess. (Symmetrically: a non-binary winner against a YES/NO trade.)
    const binary = (s: string) => s === "YES" || s === "NO";
    if (binary(winner) !== binary(want)) return null;
    return false;
  }

  // No labels available: legacy binary fallback, only for YES/NO trades.
  if ((want === "YES" || want === "NO") && typeof input.yesPrice === "number" && !Number.isNaN(input.yesPrice)) {
    return want === "YES" ? input.yesPrice > 0.5 : input.yesPrice <= 0.5;
  }
  return null;
}

/**
 * Settlement value of a trade's token: 1 (won), 0 (lost), or undefined when the
 * outcome cannot be determined (callers MUST leave those positions unjudged —
 * booking 0 on undeterminable data is the phantom-loss failure mode).
 *
 * This is the `hold-to-settlement` comparison of the band-exit counterfactual:
 * the venue's winning label arrives in the venue's own casing ("No", "Under",
 * "Team Liquid") while the stored outcome is uppercased at ingest ("NO",
 * "UNDER"), so it goes through didOutcomeWin's normalised compare.
 */
export function settlementValue(
  tradeOutcome: string | null | undefined,
  input: ResolutionInput
): 0 | 1 | undefined {
  const won = didOutcomeWin(tradeOutcome, input);
  return won === null ? undefined : won ? 1 : 0;
}
