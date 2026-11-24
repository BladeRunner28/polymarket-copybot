/**
 * Settlement basis for the Kalshi venue-shadow ledger (card
 * kalshi-venue-shadow-pnl-exit-sign-basis, 2026-11-24).
 *
 * WHY THIS EXISTS: scripts/kalshi-venue-shadow.ts set `won = realizedPnl > 0` — the sign of OUR
 * paper leg's EXIT — and then priced the Kalshi book from it. That field is named `won`, so the
 * printed `kalshiPnl` / `delta` read as a cross-venue SETTLEMENT comparison while they are in fact
 * an exit-sign comparison: an early close books a "loss" on a contract that settled as a win.
 * The exit-sign figures are the historical record and stay exactly where they are; this module
 * gives the ledger a SECOND, honestly-named basis priced off the venue's own `result`.
 *
 * The two bases must never be mixed in one number: `venueLegPnl` is only ever fed a venue win,
 * and every caller must print which basis a figure came from.
 */

/** Kalshi `/markets/<ticker>` reports `result` as "yes" | "no" once finalized, "" before. */
export type KalshiResult = "yes" | "no" | null;

export function normaliseKalshiResult(raw: unknown): KalshiResult {
  const v = typeof raw === "string" ? raw.trim().toLowerCase() : "";
  return v === "yes" || v === "no" ? (v as "yes" | "no") : null;
}

/**
 * Did OUR side of the contract win, per the venue? `ourSideIsYes` is the resolved strike-level
 * side flag (Kalshi binary contracts are YES/NO; we may hold either side of the same market).
 * Returns null — never a guess — when either input is unknown.
 */
export function venueSideWon(result: KalshiResult, ourSideIsYes: boolean | null | undefined): boolean | null {
  if (result !== "yes" && result !== "no") return null;
  if (ourSideIsYes !== true && ourSideIsYes !== false) return null;
  return (result === "yes") === ourSideIsYes;
}

/**
 * Gross PnL of one Kalshi leg under a win/loss that came from the VENUE (not from an exit sign).
 * Same contract-payout arithmetic as the exit-sign arm so the two are directly comparable; the
 * caller applies the fee itself, so no fee input moves here.
 */
export function venueGross(size: number, entry: number, won: boolean): number | null {
  if (!Number.isFinite(size) || !Number.isFinite(entry) || entry <= 0) return null;
  return won ? size * (1 / entry - 1) : -size;
}

export type BasisVerdict = "agree" | "exit_loss_venue_win" | "exit_win_venue_loss" | "venue_unknown" | "exit_unknown";

/** Compare the exit-sign reading of one leg with its venue reading. */
export function compareBases(exitWon: boolean | null | undefined, venueWon: boolean | null | undefined): BasisVerdict {
  if (venueWon !== true && venueWon !== false) return "venue_unknown";
  if (exitWon !== true && exitWon !== false) return "exit_unknown";
  if (exitWon === venueWon) return "agree";
  return venueWon ? "exit_loss_venue_win" : "exit_win_venue_loss";
}

export type BasisSummary = {
  population: number;
  known: number;
  agree: number;
  exitLossVenueWin: number;
  exitWinVenueLoss: number;
  venueUnknown: number;
  exitUnknown: number;
  /** the headline: how many legs read differently on the two bases */
  disagree: number;
  exitWins: number;
  venueWins: number;
};

/**
 * Leg-level summary. Level = one ledger leg; the caller owns the population/clock and must print
 * them beside the result. Every leg lands in exactly one bucket, so the counts always sum.
 */
export function summariseBasis(
  legs: Array<{ exitWon: boolean | null | undefined; venueWon: boolean | null | undefined }>,
): BasisSummary {
  const out: BasisSummary = {
    population: legs.length, known: 0, agree: 0, exitLossVenueWin: 0, exitWinVenueLoss: 0,
    venueUnknown: 0, exitUnknown: 0, disagree: 0, exitWins: 0, venueWins: 0,
  };
  for (const l of legs) {
    const v = compareBases(l.exitWon, l.venueWon);
    if (v === "venue_unknown") { out.venueUnknown++; continue; }
    if (v === "exit_unknown") { out.exitUnknown++; continue; }
    out.known++;
    if (l.exitWon === true) out.exitWins++;
    if (l.venueWon === true) out.venueWins++;
    if (v === "agree") out.agree++;
    else if (v === "exit_loss_venue_win") out.exitLossVenueWin++;
    else out.exitWinVenueLoss++;
  }
  out.disagree = out.exitLossVenueWin + out.exitWinVenueLoss;
  return out;
}

/**
 * The "which side do we hold" question is NOT answered here. scripts/kalshi-pair-settlement-read.py
 * adjudicates it once (our outcome's name vs the contract subject, with the venue token list as a
 * tie-break) and writes the answer per pair; this module only consumes that answer.
 *
 * WHY THAT MATTERS: the ledger's own `detOurSideIsYes` disagrees with our outcome's side on 13 of
 * the 41 determinable pairs (data/kalshi-pair-settlement.json, read 2026-11-24). A second, quieter
 * derivation inside the ledger would have turned those into fabricated settlement flips.
 */
export type PairJudgement = {
  sideYes?: boolean | null;
  kalshiResult?: KalshiResult;
  pmWinner?: boolean | null;
};

export type VenueVerdict = { won: boolean | null; source: "kalshi_side" | "pm_token" | null };

/** Join key for a ledger row against the pair-settlement artifact. */
export function pairKey(marketId: string, outcome: string, ticker: string): string {
  return `${marketId}|${(outcome ?? "").trim()}|${ticker}`;
}

/** Settlement of OUR leg, from the adjudicated pair. Kalshi's own result is preferred; PM's token
 *  winner is the fallback when the Kalshi side is not final. Unknown stays unknown. */
export function venueWonFromPair(p: PairJudgement | null | undefined): VenueVerdict {
  if (!p) return { won: null, source: null };
  const side = p.sideYes;
  if ((p.kalshiResult === "yes" || p.kalshiResult === "no") && (side === true || side === false)) {
    return { won: (p.kalshiResult === "yes") === side, source: "kalshi_side" };
  }
  if (p.pmWinner === true || p.pmWinner === false) return { won: p.pmWinner, source: "pm_token" };
  return { won: null, source: null };
}
