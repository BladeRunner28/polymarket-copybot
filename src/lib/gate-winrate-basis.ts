/**
 * gate-winrate-basis — the win rate the auto-rule-updater GATES `minCopyScore` on, read on both
 * bases side by side.
 *
 * Card `ruleupdater-exit-labeled-winrate` (surfaced 2026-10-07, worked 2026-11-04).
 *
 * WHY THIS EXISTS. `update:rules` computes `winRate = samples.filter(s => s.pnl > 0) / n` over the
 * v52-widened population (status closed|resolved, i.e. EARLY EXITS INCLUDED) and then decides
 * `minCopyScore` from it (src/lib/rule-updater.ts, arms 4 and 5). `pnl > 0` on a leg that we SOLD
 * at a profit is an EXIT sign, not the market's outcome: the leg can have settled against us. So a
 * printed number labelled "win rate" is really "share of legs we closed above our entry", and the
 * gate that moves the copy threshold is tuned on our own exit policy rather than on signal quality.
 *
 * WHAT THIS MODULE DOES NOT DO. It does not change the gate. Both verdicts are computed and
 * reported; the gate still reads the EXIT arm until the user approves otherwise (Lane A). What
 * changes here is only that the number can no longer be printed without its basis.
 *
 * BASIS, stated once and reused everywhere:
 *   level      = the leg (one PaperTrade row)
 *   population = whatever the caller passes; the script uses the rule-updater's own query
 *                (status IN ('closed','resolved') AND realizedPnl NOT NULL, no demo rows exist)
 *   clock      = settlement: COALESCE(closedAt, resolvedAt)
 *   EXIT win   = realizedPnl > 0 (the gate's current input)
 *   OUTCOME win= didOutcomeWin(leg.outcome, {winningLabel: the outcome review's finalOutcome});
 *                null (undeterminable) legs are EXCLUDED from the rate and counted as coverage,
 *                never guessed — booking a guess is what created the phantom losses of 2026-09.
 */

export type GateLeg = {
  /** realizedPnl — the EXIT-or-settlement book value; `null` is read as 0, as the gate does. */
  pnl: number | null;
  /** our stake on the leg (USD). */
  stake?: number | null;
  /** entry price paid (0..1). Needed only for the hold-to-settlement counterfactual. */
  entryPrice?: number | null;
  /** settlement clock: COALESCE(closedAt, resolvedAt). */
  at?: Date | null;
  /** venue settlement read for THIS leg's token: true / false / null = undeterminable. */
  outcomeWin: boolean | null;
};

export type BasisRead = {
  n: number;
  wins: number;
  /** wins / n; null when n = 0 (undefined, not 0%) */
  rate: number | null;
  pnl: number;
  cost: number;
};

/** The gate's current input: every leg, `realizedPnl > 0`. */
export function exitBasisRead(legs: GateLeg[]): BasisRead {
  const n = legs.length;
  const wins = legs.filter((l) => (l.pnl ?? 0) > 0).length;
  return {
    n,
    wins,
    rate: n ? wins / n : null,
    pnl: legs.reduce((a, l) => a + (l.pnl ?? 0), 0),
    cost: legs.reduce((a, l) => a + (l.stake ?? 0), 0),
  };
}

/**
 * The settlement read: only legs whose outcome the venue can determine. `coverage` is the share of
 * the population that could be judged — printed with the rate because a rate on 69% of the book is
 * not the book's rate.
 */
export function outcomeBasisRead(legs: GateLeg[]): BasisRead & { undetermined: number; coverage: number } {
  const judged = legs.filter((l) => l.outcomeWin === true || l.outcomeWin === false);
  const wins = judged.filter((l) => l.outcomeWin === true).length;
  return {
    n: judged.length,
    wins,
    rate: judged.length ? wins / judged.length : null,
    pnl: judged.reduce((a, l) => a + (l.pnl ?? 0), 0),
    cost: judged.reduce((a, l) => a + (l.stake ?? 0), 0),
    undetermined: legs.length - judged.length,
    coverage: legs.length ? judged.length / legs.length : 0,
  };
}

export type Disagreement = {
  /** exit said win, the market settled it a LOSS — the inflation the card is about */
  exitWinOutcomeLoss: { n: number; pnl: number; cost: number };
  /** exit said loss (or flat), the market settled it a WIN — exits that gave up a winner */
  exitLossOutcomeWin: { n: number; pnl: number; cost: number };
  bothWon: number;
  bothLost: number;
  unknown: number;
};

export function settlementDisagreement(legs: GateLeg[]): Disagreement {
  const acc = {
    exitWinOutcomeLoss: { n: 0, pnl: 0, cost: 0 },
    exitLossOutcomeWin: { n: 0, pnl: 0, cost: 0 },
    bothWon: 0,
    bothLost: 0,
    unknown: 0,
  };
  for (const l of legs) {
    if (l.outcomeWin !== true && l.outcomeWin !== false) {
      acc.unknown += 1;
      continue;
    }
    const exitWin = (l.pnl ?? 0) > 0;
    if (exitWin && l.outcomeWin) acc.bothWon += 1;
    else if (!exitWin && !l.outcomeWin) acc.bothLost += 1;
    else if (exitWin && !l.outcomeWin) {
      acc.exitWinOutcomeLoss.n += 1;
      acc.exitWinOutcomeLoss.pnl += l.pnl ?? 0;
      acc.exitWinOutcomeLoss.cost += l.stake ?? 0;
    } else {
      acc.exitLossOutcomeWin.n += 1;
      acc.exitLossOutcomeWin.pnl += l.pnl ?? 0;
      acc.exitLossOutcomeWin.cost += l.stake ?? 0;
    }
  }
  return acc;
}

/**
 * Hold-to-settlement PnL per leg at OUR stake: a winning token pays $1/share, so a $S stake bought
 * at p returns S*(1-p)/p; a loser returns -S. No fee, no slippage (both stated in the caller's
 * basis line as zero rather than silently priced). COUNTERFACTUAL: it is not our book.
 */
export function settlementPnl(leg: GateLeg): number | null {
  const p = leg.entryPrice;
  if (typeof p !== "number" || !Number.isFinite(p) || p <= 0 || p > 1) return null;
  const stake = leg.stake ?? 0;
  if (leg.outcomeWin !== true && leg.outcomeWin !== false) return null;
  return leg.outcomeWin ? (stake * (1 - p)) / p : -stake;
}

export type GateThresholds = {
  minCopyScore: number;
  highScoreCapMin: number;
  sweetSpotMinScore: number;
};

export type GateVerdict = {
  /** arm 4 of proposeRuleChanges: raise the copy bar */
  tightens: boolean;
  /** arm 5: relax the bar toward the floor */
  relaxes: boolean;
  /** the floor arm 5 may not cross — mirrors rule-updater's copyFloor exactly */
  copyFloor: number;
};

/**
 * A verbatim mirror of the two `minCopyScore` arms in src/lib/rule-updater.ts. Kept here so the
 * comparison can be computed for a hypothetical (totalPnl, winRate) pair without touching the
 * updater. If either side's constants move, tests/gate-winrate-basis.test.ts (which imports the
 * updater's own thresholds through DEFAULT_RULES) is the place that breaks.
 */
export function gateVerdict(totalPnl: number, winRate: number, rules: GateThresholds): GateVerdict {
  const copyFloor = Math.max(rules.highScoreCapMin, rules.sweetSpotMinScore, 55);
  return {
    tightens: totalPnl < 0 && winRate < 0.45 && rules.minCopyScore < 85,
    relaxes: totalPnl > 20 && winRate > 0.6 && rules.minCopyScore > copyFloor,
    copyFloor,
  };
}

export type BasisComparison = {
  exit: BasisRead;
  /**
   * The label swapped on the SAME book (same realizedPnl) — isolates the label's contribution.
   * Never null: a population with no judgeable leg reports n=0 / rate=null, which is an answer.
   */
  outcomeOnExitBook: BasisRead & { undetermined: number; coverage: number };
  /** the fully consistent settlement book (hold-to-settlement at our stake) — counterfactual */
  settleBook: (BasisRead & { undetermined: number; coverage: number }) | null;
  verdictLive: GateVerdict;
  /** only the win rate swapped, PnL left as the live exit book */
  verdictOutcomeLabel: GateVerdict | null;
  verdictSettleBook: GateVerdict | null;
  /** true when the LIVE verdict and the settlement-book verdict disagree */
  verdictFlips: boolean;
  disagreement: Disagreement;
};

/**
 * Everything the card asks for, on one population: both rates with n and coverage, both gate
 * verdicts, and the legs the two labels disagree on.
 */
export function compareGateBasis(legs: GateLeg[], rules: GateThresholds): BasisComparison {
  const exit = exitBasisRead(legs);
  const outcomeOnExitBook = outcomeBasisRead(legs);

  const settled = legs.filter((l) => settlementPnl(l) !== null);
  const settleBook = settled.length
    ? {
        ...outcomeBasisRead(settled),
        pnl: settled.reduce((a, l) => a + (settlementPnl(l) ?? 0), 0),
      }
    : null;

  const verdictLive = gateVerdict(exit.pnl, exit.rate ?? 0, rules);
  const verdictOutcomeLabel =
    outcomeOnExitBook.rate === null
      ? null
      : gateVerdict(exit.pnl, outcomeOnExitBook.rate, rules);
  const verdictSettleBook =
    settleBook && settleBook.rate !== null
      ? gateVerdict(settleBook.pnl, settleBook.rate, rules)
      : null;

  return {
    exit,
    outcomeOnExitBook,
    settleBook,
    verdictLive,
    verdictOutcomeLabel,
    verdictSettleBook,
    // ANY arm flipping is a flip: tighten and relax are alternatives, never both, so an `&&`
    // here would report "no flip" on exactly the case that matters (tighten appearing).
    verdictFlips:
      !!verdictSettleBook &&
      (verdictSettleBook.tightens !== verdictLive.tightens ||
        verdictSettleBook.relaxes !== verdictLive.relaxes),
    disagreement: settlementDisagreement(legs),
  };
}

const pct = (r: number | null) => (r === null ? "n/a" : `${(100 * r).toFixed(1)}%`);

/**
 * The one-line fragment the rule updater appends to any arm whose evidence carries a win rate.
 * It names BOTH bases and the coverage, so the number can never be read as a probability again.
 */
export function gateBasisText(c: BasisComparison): string {
  const out = c.outcomeOnExitBook;
  const outPart = out.rate !== null
    ? `OUTCOME basis ${pct(out.rate)} (n=${out.n.toLocaleString("en-US")}, ${(100 * out.coverage).toFixed(1)}% of legs judgeable)`
    : `OUTCOME basis n/a (no judgeable legs)`;
  return `win rate EXIT basis ${pct(c.exit.rate)} (n=${c.exit.n.toLocaleString("en-US")}, realizedPnl>0) | ${outPart}`;
}
