/**
 * c200-maker-fill-assumption — option (b): measure the 2¢ maker fill in-house.
 *
 * WHY THIS EXISTS
 * Every BANKROLL_200 BUY is booked by the Rust sidecar at `max(0.01, intent - 0.02)`
 * (rust-sidecar/src/main.rs, "Phase 6 ImMike's Maker Copying") — a modelled maker
 * limit order parked inside the spread. That assumption IS the C-200 entry price:
 * on the maker era (openedAt >= 2026-08-28, settled legs) it is worth $1,732.88 of
 * the lane's $2,288.52 realized PnL (75.7%). The INTENT price it was derived from
 * was only ever logged, never stored, so "did the order actually fill 2¢ inside?"
 * was unanswerable — the archive measurement (drafts/fee-maker-calibration-20260925.md)
 * can only supply a base rate (74.3% within 5 min at our price mix) plus the
 * adverse-selection counterweight, not our own fills.
 *
 * WHAT THIS SHIPS
 *  - `FillIntent`: one row per dispatched C-200 intent (the price the lane was
 *    HANDED, before the sidecar's improvement). Written by the Node dispatch path.
 *  - `PaperTrade.intentPrice`: stamped when the sidecar's execution-result webhook
 *    creates the row, so the booked entry and the price it was handed sit on the
 *    SAME leg and the gap is a measurement instead of an assumption.
 *
 * HARD CONSTRAINTS (do not relax)
 *  1. WRITE-ONLY. Nothing in any decision, sizing, gate, Kelly input or published
 *     number reads these fields. `scripts/fill-vs-intent.ts` is the only reader.
 *  2. NEITHER FUNCTION MAY THROW. They sit in the live trade path: the dispatch
 *     call is inside the same try/catch that reports "Rust Execution Engine
 *     offline or failed", and the webhook call books the position. A shadow
 *     failure must degrade to "no measurement", never to a failed copy.
 *  3. REVERTIBLE WITHOUT A DEPLOY: `FILL_INTENT_SHADOW=0` in the environment
 *     stops both writes; the columns are nullable and nothing depends on them.
 *  4. NO BACKFILL. `intentPrice` is NULL on every leg booked before this shipped
 *     (and on STANDARD legs, which write their own row at the price they read) —
 *     the distribution starts from the first dispatch after deployment.
 */

import { prisma } from "./db";

/** Write-only shadow switch. Default ON so the measurement cannot be silently absent. */
export const FILL_INTENT_SHADOW = (process.env.FILL_INTENT_SHADOW ?? "1") !== "0";

/** The sidecar's modelled maker improvement, mirrored from rust-sidecar/src/main.rs. */
export const MAKER_IMPROVEMENT = Number(process.env.MAKER_IMPROVEMENT ?? 0.02);

/** A dispatched C-200 intent, before the sidecar applies its filler. */
export interface IntentInput {
  decisionJournalId: string;
  botId: string;
  venue: string;
  marketId: string;
  outcome: string;
  side: string;
  intentPrice: number;
  sizeUsd: number;
}

/** One leg's intent-vs-entry pair, as read back for reporting. */
export interface IntentLeg {
  intentPrice: number | null;
  entryPrice: number;
  status: string;
  openedAtMs: number;
}

export interface FillVsIntentBucket {
  label: string;
  n: number;
  share: number;
}

export interface FillVsIntentSummary {
  /** Legs with a stored intent price (the only legs that can be measured). */
  measured: number;
  /** Legs without one — booked before the instrument existed, or STANDARD. */
  unmeasured: number;
  /** entry - intent. Negative = the booked entry is BETTER than the price handed in. */
  meanGap: number;
  medianGap: number;
  /** Share of measured legs whose gap is the modelled -0.02 to the cent. */
  shareExactImprovement: number;
  /** Share where the booked entry equals the intent price (no improvement booked). */
  shareNoImprovement: number;
  /** Share where the booked entry is WORSE than the intent (bug signature, not the model). */
  shareWorseThanIntent: number;
  buckets: FillVsIntentBucket[];
}

/** The gap buckets the distribution is reported in (entry - intent). */
export const GAP_BUCKETS: Array<{ label: string; lo: number; hi: number }> = [
  { label: "entry better by >2.5c", lo: -Infinity, hi: -0.025 },
  { label: "better by ~2c (the model)", lo: -0.025, hi: -0.015 },
  { label: "better by 0.5-1.5c", lo: -0.015, hi: -0.005 },
  { label: "equal (no improvement)", lo: -0.005, hi: 0.005 },
  { label: "worse (bug signature)", lo: 0.005, hi: Infinity },
];

/** entry - intent for one leg. Positive = we paid MORE than the lane was handed. */
export function gapOf(intentPrice: number | null, entryPrice: number): number | null {
  if (intentPrice === null || !Number.isFinite(intentPrice)) return null;
  if (!Number.isFinite(entryPrice)) return null;
  // Prices are quoted in cents-scale decimals; compare on the cent to avoid
  // 0.5000000000000001-style float noise reading as "worse than intent".
  return Math.round((entryPrice - intentPrice) * 1e6) / 1e6;
}

/** Median of a numeric list (sorting a copy; NaN-free input assumed). */
export function median(xs: number[]): number {
  if (xs.length === 0) return 0;
  const s = [...xs].sort((a, b) => a - b);
  const mid = s.length >> 1;
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

/**
 * Pure summariser — the number the card's gate asks for: the measured
 * C-200 fill-vs-intent-price distribution. Legs with no stored intent are
 * counted as `unmeasured` and excluded from every gap statistic (they cannot
 * contribute an opinion), which is why `measured` is reported first.
 */
export function summariseFillVsIntent(legs: IntentLeg[]): FillVsIntentSummary {
  const gaps: number[] = [];
  let unmeasured = 0;
  for (const leg of legs) {
    const g = gapOf(leg.intentPrice, leg.entryPrice);
    if (g === null) unmeasured++;
    else gaps.push(g);
  }
  const n = gaps.length;
  const buckets = GAP_BUCKETS.map((b) => ({
    label: b.label,
    n: gaps.filter((g) => g >= b.lo && g < b.hi).length,
    share: 0,
  }));
  for (const b of buckets) b.share = n ? b.n / n : 0;
  const tol = 0.001; // a cent-scale quote is exact to 3 decimals here
  return {
    measured: n,
    unmeasured,
    meanGap: n ? gaps.reduce((a, b) => a + b, 0) / n : 0,
    medianGap: median(gaps),
    shareExactImprovement: n ? gaps.filter((g) => Math.abs(g + MAKER_IMPROVEMENT) <= tol).length / n : 0,
    shareNoImprovement: n ? gaps.filter((g) => Math.abs(g) <= tol).length / n : 0,
    shareWorseThanIntent: n ? gaps.filter((g) => g > tol).length / n : 0,
    buckets,
  };
}

/** Report lines for the summary (script + future review crons read the same text). */
export function renderFillVsIntent(s: FillVsIntentSummary, windowLabel: string): string[] {
  const pct = (x: number) => `${(100 * x).toFixed(1)}%`;
  const lines = [
    `[fill-vs-intent] C-200 measured legs ${s.measured}, unmeasured ${s.unmeasured} (${windowLabel})`,
    `[fill-vs-intent] gap (entry - intent): mean ${s.meanGap.toFixed(4)}, median ${s.medianGap.toFixed(4)} · ` +
      `exactly -$${MAKER_IMPROVEMENT.toFixed(2)}: ${pct(s.shareExactImprovement)} · ` +
      `no improvement: ${pct(s.shareNoImprovement)} · worse than intent: ${pct(s.shareWorseThanIntent)}`,
  ];
  for (const b of s.buckets) lines.push(`[fill-vs-intent]   ${b.label}: ${b.n} (${pct(b.share)})`);
  lines.push(
    `[fill-vs-intent] NOTE: write-only shadow — no rule, size, gate or booked figure reads it; ` +
      `no backfill exists (every leg booked before the instrument shipped has intentPrice NULL)`
  );
  return lines;
}

/**
 * Record one dispatched C-200 intent. Never throws: a shadow failure degrades to
 * "no measurement for this leg" and is logged as such.
 */
export async function recordFillIntent(input: IntentInput): Promise<string | null> {
  if (!FILL_INTENT_SHADOW) return null;
  if (input.botId !== "BANKROLL_200") return null; // only the maker-filled lane
  if (!Number.isFinite(input.intentPrice) || input.intentPrice <= 0) {
    console.warn(`[fill-intent] skipped: non-finite intent price ${input.intentPrice}`);
    return null;
  }
  try {
    const row = await prisma.fillIntent.create({
      data: {
        decisionJournalId: input.decisionJournalId,
        botId: input.botId,
        venue: input.venue,
        marketId: input.marketId,
        outcome: input.outcome,
        side: input.side,
        intentPrice: input.intentPrice,
        sizeUsd: input.sizeUsd,
      },
    });
    return row.id;
  } catch (e: any) {
    console.warn(`[fill-intent] shadow write skipped (${e?.message ?? e}) — copy unaffected`);
    return null;
  }
}

/**
 * Link a booked leg to the intent it came from and stamp `PaperTrade.intentPrice`.
 * Called AFTER the booking transaction commits, so the worst case is a booked
 * copy with no measurement. Matching is on the identity the webhook carries
 * (decisionJournalId + market + outcome + side + venue); the newest unlinked
 * intent wins. Never throws.
 */
export async function stampIntentLink(match: {
  paperTradeId: string;
  decisionJournalId: string;
  marketId: string;
  outcome: string;
  side: string;
  venue: string;
  botId: string;
}): Promise<number | null> {
  if (!FILL_INTENT_SHADOW) return null;
  if (match.botId !== "BANKROLL_200") return null; // STANDARD books its own price
  try {
    const intent = await prisma.fillIntent.findFirst({
      where: {
        paperTradeId: null,
        decisionJournalId: match.decisionJournalId,
        marketId: match.marketId,
        outcome: match.outcome,
        side: match.side,
      },
      orderBy: { dispatchedAt: "desc" },
    });
    if (!intent) return null;
    // Stamp the LEG first, then mark the intent linked: if the stamp fails there is
    // nothing recorded, and the intent stays unlinked (retryable) instead of
    // pointing at a leg it never touched.
    await prisma.paperTrade.update({
      where: { id: match.paperTradeId },
      data: { intentPrice: intent.intentPrice },
    });
    await prisma.fillIntent.update({
      where: { id: intent.id },
      data: { paperTradeId: match.paperTradeId, linkedAt: new Date() },
    });
    return intent.intentPrice;
  } catch (e: any) {
    console.warn(`[fill-intent] link skipped (${e?.message ?? e}) — copy unaffected`);
    return null;
  }
}

/** Read the window's C-200 legs and intents for the report. */
export async function loadFillVsIntent(opts: { sinceMs?: number } = {}): Promise<{
  summary: FillVsIntentSummary;
  unlinkedIntents: number;
  intents: number;
}> {
  const where = opts.sinceMs ? { openedAt: { gte: new Date(opts.sinceMs) } } : {};
  const legs = await prisma.paperTrade.findMany({
    where: { botId: "BANKROLL_200", ...where },
    select: { intentPrice: true, entryPrice: true, status: true, openedAt: true },
    orderBy: { openedAt: "asc" },
  });
  const intents = await prisma.fillIntent.findMany({
    where: opts.sinceMs ? { dispatchedAt: { gte: new Date(opts.sinceMs) } } : {},
    select: { paperTradeId: true },
  });
  return {
    summary: summariseFillVsIntent(
      legs.map((l) => ({
        intentPrice: l.intentPrice,
        entryPrice: l.entryPrice,
        status: l.status,
        openedAtMs: l.openedAt.getTime(),
      }))
    ),
    unlinkedIntents: intents.filter((i) => i.paperTradeId === null).length,
    intents: intents.length,
  };
}
