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
