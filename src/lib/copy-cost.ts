/**
 * EDGE vs the COST OF COPYING — the pair the daily report must quote together
 * (roadmap card `polycopy-edge-cost-pair`, carded 2026-09-23 from the Polycopy
 * research review; baseline measured the same day).
 *
 * WHY THIS EXISTS
 * The daily report quotes realized PnL and implicitly treats our modelled fill
 * as free. Polycopy's Sep-8 2026 report (scraped, archived in
 * data/vendor-research/) makes the opposite point on the top-100 of both
 * Polymarket leaderboards: MEDIAN per-position edge 1.39% (30d) / 2.07%
 * (all-time) against a MEDIAN modelled cost of copying of 4.12% / 3.51% — 77%
 * of the measurable traders go negative once costs are applied. An edge figure
 * quoted without its cost term is therefore not readable, and every later
 * sizing/Kelly decision inherits the error.
 *
 * THE TWO NUMBERS (both over the SAME settled legs, so neither can be quoted alone)
 *   edge        — realized PnL as a % of the notional committed:
 *                 SUM(realizedPnl) / SUM(simulatedPositionSize), settled legs.
 *                 Aggregate, not per-leg-average: the C-200 lane sizes winners
 *                 up (Kelly + price bands), and the report's question is "what
 *                 did the book earn on the money it committed".
 *   copyCost    — mean per leg of (our booked entry − the wallet's own fill) /
 *                 the wallet's own fill. Sign: POSITIVE = we paid ABOVE the
 *                 wallet's own fill, i.e. a real cost of copying. NEGATIVE =
 *                 our booked entry sat BELOW the wallet's fill, which no real
 *                 copier can rely on: the booked entry is `currentPrice` — a
 *                 QUOTE read at scoring time (scripts/score-trades.ts, adapter
 *                 fetchMarket), not a taker fill. A negative term is an
 *                 artefact of the fill model, never "capture".
 *   detectionDrag — mean per leg of (detectedPrice − wallet fill)/wallet fill:
 *                 the adverse move between the wallet's fill and our own
 *                 detection of it. This is the one drag every copier pays
 *                 regardless of fill model, and it is a LOWER BOUND on the true
 *                 cost: the paper fill crosses no spread and pays no fee, and
 *                 neither is in this term.
 *
 * WHY C-200's COPY COST IS NEGATIVE (root-caused 2026-09-23, measured)
 * The C-200 lane does not write its own fills: src/lib/paper.ts dispatches an
 * execution intent to the Rust sidecar (:3014) and the sidecar's webhook writes
 * the PaperTrade row. rust-sidecar/src/main.rs "Phase 6 ImMike's Maker Copying"
 * then books every BANKROLL_200 fill 2¢ BETTER than the price the lane was
 * handed — `maker_improvement = 0.02`, `executed_price - maker_improvement` for
 * BUYs (clamped at 0.01) — modelling a maker limit order parked inside the
 * spread. Evidence in our own book: for the 1,120 decisions both lanes booked,
 * the C-200 entry is the STANDARD entry (same decision, same openedAt) minus
 * exactly $0.02 whenever the two price reads agree, and C-200 entries sit below
 * the detection price on 96% of v49+ legs (median −4.1%). On a $0.50 token 2¢
 * is 4% of the entry; on a $0.05 token it is 40% — which is why the C-200
 * copy-cost term is negative and why its edge reads so high. STANDARD writes
 * directly and carries none of it.
 * `makerCreditUsd` values the assumption: re-pricing each settled leg booked
 * while the maker path was live (opened ≥ MAKER_FEATURE_START_MS) at entry+2¢
 * (shares = size/entry) and re-running the same realized PnL moves the book by
 * Σ (realizedPnl + size) × 0.02 / (entry + 0.02) — $1,526 of the $2,426 lifetime
 * C-200 PnL at the 2026-09-23 read, i.e. the C-200 edge is +16.3% as booked and
 * +6.1% without the assumption. That number is NOT a measurement of a real fill;
 * it is the size of a modelled assumption, and it is surfaced so the edge term
 * above it is never read alone.
 * Changing that assumption is a PnL-model change, not a measurement — it needs
 * its own approval and its own card; this module only publishes the number.
 *
 * WINDOWS: the settled population is small (~40 C-200 / ~75 STANDARD legs a day)
 * and the edge figure is window-sensitive by measurement — 2026-09-23:
 * C-200 +16.3% lifetime vs +23.3% trailing 30d, STANDARD +9.0% vs +0.1%. So the
 * report prints BOTH a lifetime and a trailing-30d read, each with its own n.
 *
 * MEASUREMENT ONLY. Nothing consumes these numbers: no threshold, no rule, no
 * sizing, no gate. Read-only SQL; no writes, no schema change.
 *
 * Populated by scripts/edge-copy-cost.ts (the reviewer's re-runnable form) and
 * rendered into the daily report by src/lib/report.ts.
 */

import { prisma } from "./db";

/** One booked leg joined to the wallet fill it was copied from. */
export interface CopyCostRow {
  botId: string;
  entryPrice: number;
  sizeUsd: number;
  realizedPnl: number | null;
  /** closedAt ?? resolvedAt, Unix ms (TR-15: early exits only carry closedAt) */
  settledAtMs: number | null;
  /** booking time, Unix ms — decides whether the sidecar's maker assumption was
   * in force for this leg (see MAKER_FEATURE_START_MS) */
  openedAtMs: number | null;
  walletEntryPrice: number | null;
  detectedPrice: number | null;
}

export interface LaneEdgeCost {
  botId: string;
  label: string;
  /** SAME n feeds every term in this object — that is the point of the card. */
  n: number;
  /** settled legs dropped for a missing/invalid wallet fill (0 in every read
   * so far: 0 of 12,110 legs, checked 2026-09-23). Dropped from BOTH terms so
   * the pair keeps one population; surfaced so a non-zero value is visible. */
  droppedNoFill: number;
  /** realized PnL as % of committed notional (aggregate over the same n) */
  edgePctOfCost: number | null;
  /** mean (our entry − wallet fill)/wallet fill as % (positive = real cost) */
  copyCostPctPerLeg: number | null;
  /** mean (detected price − wallet fill)/wallet fill as % — lower bound on cost */
  detectionDragPctPerLeg: number | null;
  /** Value of the Rust sidecar's fixed 2¢ maker assumption across this lane's
   * settled legs: Σ (realizedPnl + size) × 0.02 / (entry + 0.02). Zero for lanes
   * that write their own fills (STANDARD). See the module header. */
  makerCreditUsd: number;
  /** SENSITIVITY, not a measurement: the same edge with makerCreditUsd removed
   * from realized PnL. Null for lanes with no credit to remove. */
  exMakerEdgePctOfCost: number | null;
  realizedPnlUsd: number;
  costUsd: number;
}

/** rust-sidecar/src/main.rs: `maker_improvement = 0.02` — the modelled inside-
 * spread improvement applied to every BANKROLL_200 BUY fill. */
export const MAKER_IMPROVEMENT_USD = 0.02;

/** First day the sidecar's maker path is observable in our own book: in every
 * dual-lane decision (same decision, same openedAt) booked on/after 2026-08-28,
 * the C-200 entry is the STANDARD entry minus exactly $0.02 — 221 of 228 pairs;
 * the other 7 are pairs whose two price reads themselves differ. The 893 pairs
 * booked before that date carry IDENTICAL entries (no maker improvement), so the
 * credit is only counted for legs opened from here on, and never before. */
export const MAKER_FEATURE_START_MS = Date.UTC(2026, 7, 28); // 2026-08-28T00:00Z

/** Lanes whose fills are written by the Rust sidecar (src/lib/paper.ts
 * dispatch to :3014) and therefore carry MAKER_IMPROVEMENT_USD. */
export const SIDECAR_LANES = ["BANKROLL_200"];

export interface EdgeCostSnapshot {
  lifetime: LaneEdgeCost[];
  d30: LaneEdgeCost[];
  /** earliest settled leg in the population — the lifetime window's start */
  lifetimeStartMs: number | null;
  /** now − 30d, the trailing window's start */
  d30StartMs: number;
  totalSettledLegs: number;
}

export const LANES = ["BANKROLL_200", "STANDARD"] as const;
export const TRAILING_WINDOW_DAYS = 30;

/** The book's own name for BANKROLL_200 (EOD wallet-status line uses it too). */
export function laneLabel(botId: string): string {
  return botId === "BANKROLL_200" ? "C-200" : botId;
}

/**
 * Read the settled book joined to the wallet fill behind each leg.
 *
 * Only settled legs (status closed|resolved with a booking stamp) carry
 * realized PnL; the copy-cost terms are measurable on every leg, but the card
 * requires both numbers over the same population, so open legs are excluded
 * here. (scripts/edge-copy-cost.ts prints the all-legs form for reconciliation
 * with the card's baseline, which included open legs.)
 *
 * Raw SQL rather than a Prisma include: the include would pull every
 * ObservedTrade row with its rawTradeJson for ~12k legs, and this query needs
 * seven columns.
 */
export async function fetchCopyCostRows(): Promise<CopyCostRow[]> {
  const rows = await prisma.$queryRawUnsafe<
    Array<{
      botId: string;
      entryPrice: number;
      sizeUsd: number;
      realizedPnl: number | null;
      settledAtMs: number | bigint | null;
      openedAtMs: number | bigint | null;
      walletEntryPrice: number | null;
      detectedPrice: number | null;
    }>
  >(`
    SELECT p.botId                                        AS botId,
           p.entryPrice                                   AS entryPrice,
           p.simulatedPositionSize                        AS sizeUsd,
           p.realizedPnl                                  AS realizedPnl,
           COALESCE(p.closedAt, p.resolvedAt)             AS settledAtMs,
           p.openedAt                                     AS openedAtMs,
           o.walletEntryPrice                             AS walletEntryPrice,
           o.detectedPrice                                AS detectedPrice
    FROM PaperTrade p
    JOIN DecisionJournal d ON d.id = p.decisionJournalId
    JOIN ObservedTrade o   ON o.id = d.observedTradeId
    WHERE p.isDemo = 0
      AND p.status IN ('closed', 'resolved')
      AND COALESCE(p.closedAt, p.resolvedAt) IS NOT NULL
  `);
  return rows.map((r) => ({
    botId: r.botId,
    entryPrice: r.entryPrice,
    sizeUsd: r.sizeUsd,
    realizedPnl: r.realizedPnl,
    settledAtMs: r.settledAtMs === null ? null : Number(r.settledAtMs),
    openedAtMs: r.openedAtMs === null ? null : Number(r.openedAtMs),
    walletEntryPrice: r.walletEntryPrice,
    detectedPrice: r.detectedPrice,
  }));
}

/**
 * Per-lane stats over settled legs from `windowStartMs` onwards (null = the
 * whole book). Pure — no I/O — so tests can drive it with fixtures.
 */
export function laneEdgeCost(
  rows: CopyCostRow[],
  botId: string,
  windowStartMs: number | null = null
): LaneEdgeCost {
  const inWindow = rows.filter(
    (r) =>
      r.botId === botId &&
      r.settledAtMs !== null &&
      (windowStartMs === null || r.settledAtMs >= windowStartMs)
  );
  // One population for both terms: a leg whose wallet fill is unknown or
  // non-positive cannot contribute to the copy-cost mean, and letting it feed
  // the edge term alone would be exactly the "one number without the other"
  // failure this card exists to prevent. Counted, never silently dropped.
  const legs = inWindow.filter((r) => r.walletEntryPrice !== null && r.walletEntryPrice > 0);
  const droppedNoFill = inWindow.length - legs.length;

  let realizedPnlUsd = 0;
  let costUsd = 0;
  let copyCostSum = 0;
  let dragSum = 0;
  let dragN = 0;
  let makerCreditUsd = 0;
  const sidecar = SIDECAR_LANES.includes(botId);

  for (const leg of legs) {
    const pnl = leg.realizedPnl ?? 0;
    realizedPnlUsd += pnl;
    costUsd += leg.sizeUsd ?? 0;
    const fill = leg.walletEntryPrice as number;
    copyCostSum += (leg.entryPrice - fill) / fill;
    if (leg.detectedPrice !== null) {
      dragSum += (leg.detectedPrice - fill) / fill;
      dragN += 1;
    }
    // Value of the sidecar's 2¢ improvement on this leg: hold the exit price
    // fixed and re-price the entry at entry+0.02 (so shares = size/(entry+0.02)).
    // Only legs booked while the maker path was live — see MAKER_FEATURE_START_MS.
    if (sidecar && leg.entryPrice > 0 && (leg.openedAtMs ?? 0) >= MAKER_FEATURE_START_MS) {
      makerCreditUsd += ((pnl + (leg.sizeUsd ?? 0)) * MAKER_IMPROVEMENT_USD) / (leg.entryPrice + MAKER_IMPROVEMENT_USD);
    }
  }

  const makerCredit = Math.round(makerCreditUsd * 100) / 100;
  return {
    botId,
    label: laneLabel(botId),
    n: legs.length,
    droppedNoFill,
    edgePctOfCost: costUsd > 0 ? (realizedPnlUsd / costUsd) * 100 : null,
    copyCostPctPerLeg: legs.length > 0 ? (copyCostSum / legs.length) * 100 : null,
    detectionDragPctPerLeg: dragN > 0 ? (dragSum / dragN) * 100 : null,
    makerCreditUsd: makerCredit,
    exMakerEdgePctOfCost:
      costUsd > 0 && makerCredit > 0 ? ((realizedPnlUsd - makerCredit) / costUsd) * 100 : null,
    realizedPnlUsd: Math.round(realizedPnlUsd * 100) / 100,
    costUsd: Math.round(costUsd * 100) / 100,
  };
}

/** Lifetime + trailing-30d read for both lanes. */
export function edgeCostSnapshot(rows: CopyCostRow[], now: Date = new Date()): EdgeCostSnapshot {
  const settled = rows.filter((r) => r.settledAtMs !== null);
  const lifetimeStartMs = settled.length
    ? Math.min(...settled.map((r) => r.settledAtMs as number))
    : null;
  const d30StartMs = now.getTime() - TRAILING_WINDOW_DAYS * 86_400_000;
  return {
    lifetime: LANES.map((botId) => laneEdgeCost(rows, botId, null)),
    d30: LANES.map((botId) => laneEdgeCost(rows, botId, d30StartMs)),
    lifetimeStartMs,
    d30StartMs,
    totalSettledLegs: settled.length,
  };
}

export async function computeEdgeCostSnapshot(now: Date = new Date()): Promise<EdgeCostSnapshot> {
  return edgeCostSnapshot(await fetchCopyCostRows(), now);
}

/** "+16.3" / "-3.0" — one decimal, ASCII sign so the line stays greppable. */
export function pct1(n: number | null): string {
  if (n === null || !Number.isFinite(n)) return "—";
  const s = Math.abs(n).toFixed(1);
  return `${n < 0 ? "-" : "+"}${s}`;
}

export function localDay(ms: number): string {
  const d = new Date(ms);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate()
  ).padStart(2, "0")}`;
}

const n0 = (n: number) => n.toLocaleString("en-US");

/** "$1,760" / "-$37" — whole dollars, the granularity that matters for a
 * modelled assumption. */
export function usd(v: number): string {
  const sign = v < 0 ? "-" : "";
  return `${sign}$${Math.round(Math.abs(v)).toLocaleString("en-US")}`;
}

/**
 * The report block: one line per lane carrying BOTH numbers for BOTH windows,
 * plus a legend whenever a copy-cost term is non-adverse. Returns [] when there
 * is nothing settled in either window (a fresh install must not print NaN).
 */
export function edgeCostLines(snap: EdgeCostSnapshot): string[] {
  const lanes = snap.lifetime.filter((l) => l.n > 0 || (snap.d30.find((d) => d.botId === l.botId)?.n ?? 0) > 0);
  if (lanes.length === 0) return [];

  const since = snap.lifetimeStartMs !== null ? ` since ${localDay(snap.lifetimeStartMs)}` : "";
  const header =
    `**📐 Edge vs cost of copying** — settled legs (closed|resolved); both numbers per lane run on the ` +
    `SAME legs (lifetime${since} → last ${TRAILING_WINDOW_DAYS}d), n given per window:`;

  const bullets = lanes.map((life) => {
    const d30 = snap.d30.find((d) => d.botId === life.botId && d.n > 0);
    const edge30 = d30 ? ` → ${pct1(d30.edgePctOfCost)}% (n=${n0(d30.n)})` : "";
    const cc30 = d30 ? ` → ${pct1(d30.copyCostPctPerLeg)}%` : "";
    const drag30 = d30 ? ` → ${pct1(d30.detectionDragPctPerLeg)}%` : "";
    const drag =
      life.detectionDragPctPerLeg === null
        ? ""
        : ` | detection drag ${pct1(life.detectionDragPctPerLeg)}%${drag30}`;
    return (
      `• ${life.label}: edge ${pct1(life.edgePctOfCost)}% of cost (n=${n0(life.n)})${edge30}` +
      ` | copy cost ${pct1(life.copyCostPctPerLeg)}%/leg${cc30}${drag}`
    );
  });

  const nonAdverse = [...snap.lifetime, ...snap.d30].filter(
    (l) => l.copyCostPctPerLeg !== null && l.copyCostPctPerLeg <= 0
  );
  const makerLanes = snap.lifetime.filter((l) => l.makerCreditUsd > 0);
  const makerNote = makerLanes.length
    ? ` Cause is measured on ${makerLanes
        .map((l) => l.label)
        .join("/")}: the Rust sidecar books every BUY 2¢ better (maker_improvement, rust-sidecar/src/main.rs) — worth ` +
      `≈${usd(makerLanes.reduce((a, l) => a + l.makerCreditUsd, 0))} of the ${usd(
        makerLanes.reduce((a, l) => a + l.realizedPnlUsd, 0)
      )} lifetime ${makerLanes.map((l) => l.label).join("/")} PnL. Ex that assumption ${makerLanes
        .map((l) => {
          const d30 = snap.d30.find((d) => d.botId === l.botId && d.n > 0);
          return `${l.label} reads ${pct1(l.exMakerEdgePctOfCost)}% of cost (lifetime)${
            d30 ? ` / ${pct1(d30.exMakerEdgePctOfCost)}% (30d)` : ""
          }`;
        })
        .join("; ")}.`
    : ` The booked entry is a quote read at scoring time, not a taker fill.`;
  const legend =
    nonAdverse.length > 0
      ? `_⚠️ A NEGATIVE copy cost means our booked entry sat BELOW the wallet's own fill.${makerNote} Neither lane ` +
        `crosses a spread or pays a fee, so both cost terms are a LOWER BOUND on the real cost of copying._`
      : `_Copy cost is (our booked entry − the wallet's own fill)/its fill, mean per leg; positive = we paid above the wallet._`;

  return [header, ...bullets, legend];
}

/**
 * One-line form for the EOD log (the reviewer's greppable artifact, same
 * convention as scripts/wallet-status-split.ts).
 */
export function edgeCostLogLine(snap: EdgeCostSnapshot): string {
  const parts = snap.lifetime.map((life) => {
    const d30 = snap.d30.find((d) => d.botId === life.botId);
    return (
      `${life.label} edge ${pct1(life.edgePctOfCost)}% of cost (n=${n0(life.n)}) / copy cost ` +
      `${pct1(life.copyCostPctPerLeg)}%/leg (n=${n0(life.n)})` +
      (life.makerCreditUsd > 0
        ? ` / 2c maker credit ${usd(life.makerCreditUsd)} of ${usd(life.realizedPnlUsd)} realized (ex-maker edge ${pct1(life.exMakerEdgePctOfCost)}%)`
        : "") +
      (d30
        ? ` | 30d edge ${pct1(d30.edgePctOfCost)}% (n=${n0(d30.n)}) / copy cost ${pct1(
            d30.copyCostPctPerLeg
          )}%` + (d30.makerCreditUsd > 0 ? ` / maker credit ${usd(d30.makerCreditUsd)}` : "")
        : "")
    );
  });
  return `edge vs copy cost (settled legs): ${parts.join(" | ")}`;
}
