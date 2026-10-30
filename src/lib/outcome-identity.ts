/**
 * Canonical OUTCOME IDENTITY for keys that answer "same economic position?" or
 * "same fill?".
 *
 * WHY THIS EXISTS (data-api-v2-outcome-normalisation, Lane B): an outcome label is
 * free text supplied by the venue, and the venue respells the same token. MEASURED
 * on prisma/dev.db at 2026-10-29T23:10Z, level = token text over ObservedTrade,
 * population 4,740,734 rows: 7,245 distinct outcome texts collapse to 7,231
 * alnum-only identities, i.e. 14 twin pairs spell one token two ways (NONGSHIM RED
 * FORCE / NONGSHIM REDFORCE, PORTLAND FIRE / PORTLANDFIRE, TEAM SECRET / "TEAM
 * SECRET " with a trailing space, MACCABI TEL AVIV / MACCABI TEL-AVIV, ...).
 * Those pairs are NOT a post-v2 artefact: their date ranges interleave inside
 * single eras, so the cause is venue name variance. And no stored row anywhere
 * carries an apostrophe (0 of 4,740,734), so the 2026-10-19 cutover punctuation
 * strip left no trace in the book -- the card that predicted a pre/post join break
 * named a mechanism that never fired.
 *
 * Any key built from RAW outcome text split one position into two the moment the
 * venue respelled the token. MEASURED cost so far: 0. No (wallet, market, identity)
 * group in ObservedTrade (1,278,671 positions) or PaperTrade (4,966 positions)
 * carries two spellings, and 0 unscored fills sit on a position whose copy spells
 * the token differently. So this is a LATENT hole, not a live loss: routing the
 * keys through normalizeOutcomeLabel changes no decision today and only stops the
 * split from ever happening.
 */
import { normalizeOutcomeLabel } from "./resolution";

/** Token identity: letters and digits only, uppercased. Empty string for a blank label. */
export function outcomeIdentity(outcome: string | null | undefined): string {
  return normalizeOutcomeLabel(outcome);
}

/**
 * The ONE shape for "this fill is already stored".
 *
 * Mirrors `@@unique([walletAddress, marketId, outcome, side, timestamp])` except
 * that the outcome participates as an identity rather than as text. A blank
 * marketId is "" for every parlay leg, so the question stands in for the missing
 * slug -- keying on the blank id alone would collapse distinct legs and drop them.
 */
export function fillIdentityKey(parts: {
  marketId: string | null | undefined;
  marketQuestion: string | null | undefined;
  outcome: string | null | undefined;
  side: string | null | undefined;
  ts: number;
}): string {
  const marketId = parts.marketId ?? "";
  const head = marketId.trim() !== "" ? marketId : `blank:${parts.marketQuestion ?? ""}`;
  return `${head}|${outcomeIdentity(parts.outcome)}|${parts.side ?? ""}|${parts.ts}`;
}

/**
 * The ONE shape for "same open position": (wallet, market, token identity). Used by
 * the v52 sweep-dedupe (one economic intent per position) and by the leg dedupe in
 * accounting.
 */
export function positionIdentityKey(
  walletAddress: string | null | undefined,
  marketId: string | null | undefined,
  outcome: string | null | undefined
): string {
  return `${walletAddress ?? ""}|${marketId ?? ""}|${outcomeIdentity(outcome)}`;
}
