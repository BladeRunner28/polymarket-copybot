/**
 * Open MTM horizon — when does the open mark-to-market actually close?
 *
 * WHY THIS EXISTS (requested 2026-10-04): "Total Capital (live)" carries
 * `openUnreal` (Σ PaperTrade.unrealizedPnl over status='open') and on most days
 * that mark is the biggest single mover on /capital — but it is NOT cash, it
 * moves with the market, and until now nothing on the dashboard said WHEN each
 * position stops marking and becomes booked PnL. The daily report quotes the
 * same figure, so "unreal +$672" with no horizon reads as if it were bankable.
 *
 * The only timing signal in the data is `MarketSnapshot.timeToResolution`
 * (hours to the venue's close, stamped at the moment the snapshot was taken) and
 * that snapshot's `collectedAt`, so the close estimate is
 *
 *     estClose = collectedAt + timeToResolution
 *
 * TWO HONESTY CLAUSES that the card must show, because the estimate is only as
 * good as its snapshot:
 *   1. STALENESS — monitor-trades snapshots a market when it sees a
 *      copy-eligible fill, not on a timer, so a quiet open market's latest
 *      snapshot can be weeks old and its timeToResolution computed from that
 *      older "now". `staleDays` is therefore carried per market and surfaced.
 *   2. OVERDUE — `timeToResolution = 0` (or an estClose already in the past)
 *      with the leg STILL open means the venue's close has passed and the
 *      resolution pass has not booked it yet. That is a data-quality signal
 *      about the resolution pipeline, not a claim about the position's PnL.
 */

import { prisma } from "./db";
import { Prisma } from "@prisma/client";

/** A snapshot older than this is flagged as stale evidence for the estimate. */
export const STALE_DAYS = 3;

export type HorizonBucketId =
  | "overdue"
  | "lt24h"
  | "d1_3"
  | "d3_7"
  | "d7_30"
  | "d30_90"
  | "gt90d"
  | "unknown";

export interface HorizonBucketDef {
  id: HorizonBucketId;
  label: string;
  /** Inclusive upper bound in hours; null = unbounded (or unknown). */
  upperHours: number | null;
  /** Colour used by the bar panel. */
  color: string;
}

/** Ordered horizon buckets — the bar panel renders them left to right. */
export const HORIZON_BUCKETS: HorizonBucketDef[] = [
  { id: "overdue", label: "<0 (overdue)", upperHours: 0, color: "#fbbf24" },
  { id: "lt24h", label: "0–24 h", upperHours: 24, color: "#34d399" },
  { id: "d1_3", label: "1–3 d", upperHours: 72, color: "#4ade80" },
  { id: "d3_7", label: "3–7 d", upperHours: 168, color: "#7aa2f7" },
  { id: "d7_30", label: "7–30 d", upperHours: 720, color: "#60a5fa" },
  { id: "d30_90", label: "30–90 d", upperHours: 2160, color: "#818cf8" },
  { id: "gt90d", label: "> 90 d", upperHours: null, color: "#a78bfa" },
  { id: "unknown", label: "unknown", upperHours: null, color: "#64748b" },
];

/** Which horizon bucket a remaining time falls into. null = no estimate. */
export function bucketOf(remainHours: number | null | undefined): HorizonBucketId {
  if (remainHours === null || remainHours === undefined || Number.isNaN(remainHours)) return "unknown";
  if (remainHours <= 0) return "overdue";
  if (remainHours < 24) return "lt24h";
  if (remainHours < 72) return "d1_3";
  if (remainHours < 168) return "d3_7";
  if (remainHours < 720) return "d7_30";
  if (remainHours < 2160) return "d30_90";
  return "gt90d";
}

/**
 * Absolute estimated close: snapshot time + hours-to-resolution.
 * Returns null when the market never got a usable snapshot / ttr.
 */
export function estimateCloseMs(
  snapshotMs: number | null | undefined,
  ttrHours: number | null | undefined,
): number | null {
  if (snapshotMs === null || snapshotMs === undefined) return null;
  if (ttrHours === null || ttrHours === undefined) return null;
  if (Number.isNaN(snapshotMs) || Number.isNaN(ttrHours)) return null;
  return snapshotMs + ttrHours * 3_600_000;
}

/** One open market (all of a bot's open legs in it folded together). */
export interface HorizonGroup {
  marketId: string;
  question: string | null;
  legs: number;
  /** Σ simulatedPositionSize — what is tied up until it closes. */
  cost: number;
  /** Σ unrealizedPnl — the mark that stops moving when this closes. */
  unrealized: number;
  openedAtMs: number | null;
  isDemo: boolean;
  /** Latest snapshot we hold for the market (evidence for the estimate). */
  snapshotMs: number | null;
  ttrHours: number | null;
  estCloseMs: number | null;
  /** Hours from `now` until estClose; negative = overdue. null = unknown. */
  remainHours: number | null;
  /** Age of the evidence snapshot in days. null = no snapshot at all. */
  staleDays: number | null;
  bucket: HorizonBucketId;
}

export interface HorizonBucketRow extends HorizonBucketDef {
  groups: number;
  legs: number;
  cost: number;
  /** Signed Σ unrealizedPnl in the bucket. */
  unrealized: number;
  /** Σ |unrealizedPnl| — how much mark actually moves, sign-cancellation free. */
  grossUnrealized: number;
}

/** Cumulative "how much of the open mark has stopped moving by time T".
 *  Signed, cumulative, and INCLUSIVE of everything already past its close: a
 *  market in the `overdue` bucket has already reached its close, so it counts
 *  from the first step (`hours = 0`) rather than at some future horizon. */
export interface HorizonStep {
  /** Horizon bound in hours (0 = overdue only, Infinity = every dated market). */
  hours: number;
  label: string;
  /** Cumulative SIGNED unrealized closed by then. */
  cumUnrealized: number;
  /** Cumulative Σ |unrealized| closed by then. */
  cumGross: number;
  legs: number;
}

export interface HorizonSummary {
  botId: string;
  nowMs: number;
  groups: HorizonGroup[];
  buckets: HorizonBucketRow[];
  steps: HorizonStep[];
  totals: {
    groups: number;
    legs: number;
    cost: number;
    unrealized: number;
    grossUnrealized: number;
    /** Groups with a usable estimate. */
    timed: number;
    /** Unrealized in groups with no usable estimate. */
    untimedUnrealized: number;
    overdueGroups: number;
    overdueLegs: number;
    overdueCost: number;
    overdueUnrealized: number;
    /** Unrealized closing within 24 h / 7 d / 30 d. */
    within24h: number;
    within7d: number;
    within30d: number;
    /** Unrealized beyond 30 d (long-dated, still marking). */
    beyond30d: number;
    /** Max remaining hours among timed groups. */
    longestHours: number;
    longestMarketId: string | null;
    /** Oldest evidence snapshot among open markets, in days. */
    oldestEvidenceDays: number | null;
    /** Groups whose estimate rests on a stale snapshot. */
    staleGroups: number;
    /** Share of open unrealized in the single largest market. */
    topShare: number;
    topMarketId: string | null;
  };
  warnings: string[];
}

/** Unlock ladder bounds. First step is "now" (the overdue marks), last is every
 *  dated market — the ladder must reconcile to the open mark, so it needs a
 *  final unbounded step for positions further out than a year. */
const LADDER = [
  { hours: 0, label: "now (overdue)" },
  { hours: 24, label: "24 h" },
  { hours: 168, label: "7 d" },
  { hours: 720, label: "30 d" },
  { hours: 2160, label: "90 d" },
  { hours: 8760, label: "1 y" },
  { hours: Infinity, label: "all dated" },
];

function fmtH(hours: number): string {
  if (hours < 48) return `${hours.toFixed(1)} h`;
  const days = hours / 24;
  if (days < 60) return `${days.toFixed(1)} d`;
  if (days < 730) return `${(days / 30.44).toFixed(1)} mo`;
  return `${(days / 365.25).toFixed(1)} y`;
}

export function formatHorizon(hours: number | null | undefined): string {
  if (hours === null || hours === undefined || Number.isNaN(hours)) return "unknown";
  if (hours <= 0) return `${fmtH(Math.abs(hours))} overdue`;
  return fmtH(hours);
}

/**
 * Pure aggregation: groups (already carrying their estimate fields) → buckets,
 * unlock ladder and totals. Split out from the DB read so tests can drive it
 * with fixtures and the page can render without re-deriving anything.
 */
export function summarizeHorizon(
  botId: string,
  groups: HorizonGroup[],
  nowMs: number,
): HorizonSummary {
  const buckets = HORIZON_BUCKETS.map((b) => ({
    ...b,
    groups: 0,
    legs: 0,
    cost: 0,
    unrealized: 0,
    grossUnrealized: 0,
  }));

  const timed: HorizonGroup[] = [];
  let untimedUnrealized = 0;
  let overdueGroups = 0;
  let overdueLegs = 0;
  let overdueCost = 0;
  let overdueUnrealized = 0;
  let staleGroups = 0;
  let oldestEvidenceDays: number | null = null;
  let longestHours = -Infinity;
  let longestMarketId: string | null = null;

  for (const g of groups) {
    const row = buckets.find((b) => b.id === g.bucket) ?? buckets[buckets.length - 1];
    row.groups += 1;
    row.legs += g.legs;
    row.cost += g.cost;
    row.unrealized += g.unrealized;
    row.grossUnrealized += Math.abs(g.unrealized);

    if (g.estCloseMs === null || g.remainHours === null) {
      untimedUnrealized += g.unrealized;
    } else {
      timed.push(g);
      if (g.remainHours > longestHours) {
        longestHours = g.remainHours;
        longestMarketId = g.marketId;
      }
    }
    if (g.bucket === "overdue") {
      overdueGroups += 1;
      overdueLegs += g.legs;
      overdueCost += g.cost;
      overdueUnrealized += g.unrealized;
    }
    if (g.staleDays !== null) {
      if (g.staleDays > STALE_DAYS) staleGroups += 1;
      if (oldestEvidenceDays === null || g.staleDays > oldestEvidenceDays) oldestEvidenceDays = g.staleDays;
    }
  }

  const sorted = [...timed].sort((a, b) => (a.remainHours as number) - (b.remainHours as number));
  const steps: HorizonStep[] = LADDER.map((l) => {
    const upto = sorted.filter((g) => (g.remainHours as number) <= l.hours);
    return {
      hours: l.hours,
      label: l.label,
      cumUnrealized: upto.reduce((a, g) => a + g.unrealized, 0),
      cumGross: upto.reduce((a, g) => a + Math.abs(g.unrealized), 0),
      legs: upto.reduce((a, g) => a + g.legs, 0),
    };
  });

  const unrealized = groups.reduce((a, g) => a + g.unrealized, 0);
  const grossUnrealized = groups.reduce((a, g) => a + Math.abs(g.unrealized), 0);
  const top = [...groups].sort((a, b) => Math.abs(b.unrealized) - Math.abs(a.unrealized))[0];
  const uncertain = (h: number) =>
    sorted.filter((g) => {
      const r = g.remainHours as number;
      return r > 0 && r <= h;
    });
  /** Σ mark of groups still inside h hours of their close — overdue excluded:
   *  it is already past its close, so counting it as "closes within 24 h" would
   *  overstate future unlocks (it gets its own tile and the ladder's first step). */
  const within = (h: number) => uncertain(h).reduce((a, g) => a + g.unrealized, 0);
  const within30d = within(720);
  const beyond30d = sorted
    .filter((g) => (g.remainHours as number) > 720)
    .reduce((a, g) => a + g.unrealized, 0);

  const warnings: string[] = [];
  if (overdueGroups > 0) {
    warnings.push(
      `${overdueGroups} open market${overdueGroups === 1 ? "" : "s"} (${overdueLegs} leg${overdueLegs === 1 ? "" : "s"}, $${overdueCost.toFixed(2)} cost) are past their scheduled close and still open — the venue has not resolved them yet (or the resolution pass could not determine a winner), so their mark keeps counting with no future close date. Verified on 2026-10-04: such markets are still active/trading at the venue, so this is a venue-side wait, not a booking gap.`,
    );
  }
  if (staleGroups > 0) {
    warnings.push(
      `${staleGroups} of ${groups.length} open markets rest on a snapshot older than ${STALE_DAYS} d (oldest ${oldestEvidenceDays?.toFixed(1)} d) — the monitor snapshots a market on a copy-eligible fill, not on a timer, so quiet markets carry the oldest evidence.`,
    );
  }
  if (groups.length - timed.length > 0) {
    warnings.push(
      `${groups.length - timed.length} open market${groups.length - timed.length === 1 ? "" : "s"} ($${untimedUnrealized.toFixed(2)} mark) have no usable time-to-resolution — they can only be closed by an exit rule, not by the venue clock.`,
    );
  }

  return {
    botId,
    nowMs,
    groups: [...groups].sort((a, b) => {
      const am = a.remainHours === null ? Infinity : a.remainHours;
      const bm = b.remainHours === null ? Infinity : b.remainHours;
      return am - bm;
    }),
    buckets,
    steps,
    totals: {
      groups: groups.length,
      legs: groups.reduce((a, g) => a + g.legs, 0),
      cost: groups.reduce((a, g) => a + g.cost, 0),
      unrealized,
      grossUnrealized,
      timed: timed.length,
      untimedUnrealized,
      overdueGroups,
      overdueLegs,
      overdueCost,
      overdueUnrealized,
      within24h: within(24),
      within7d: within(168),
      within30d,
      beyond30d,
      longestHours: Number.isFinite(longestHours) ? longestHours : 0,
      longestMarketId,
      oldestEvidenceDays,
      staleGroups,
      topShare: unrealized !== 0 && top ? Math.abs(top.unrealized) / Math.abs(unrealized) : 0,
      topMarketId: top?.marketId ?? null,
    },
    warnings,
  };
}

/** Build one group from its open rows + latest snapshot evidence. */
export function toGroup(input: {
  marketId: string;
  legs: number;
  cost: number;
  unrealized: number;
  openedAtMs: number | null;
  isDemo: boolean;
  question: string | null;
  snapshotMs: number | null;
  ttrHours: number | null;
  nowMs: number;
}): HorizonGroup {
  const estCloseMs = estimateCloseMs(input.snapshotMs, input.ttrHours);
  const remainHours =
    estCloseMs === null ? null : (estCloseMs - input.nowMs) / 3_600_000;
  return {
    marketId: input.marketId,
    question: input.question,
    legs: input.legs,
    cost: input.cost,
    unrealized: input.unrealized,
    openedAtMs: input.openedAtMs,
    isDemo: input.isDemo,
    snapshotMs: input.snapshotMs,
    ttrHours: input.ttrHours,
    estCloseMs,
    remainHours,
    staleDays: input.snapshotMs === null ? null : (input.nowMs - input.snapshotMs) / 86_400_000,
    bucket: bucketOf(remainHours),
  };
}

type OpenGroupRow = {
  marketId: string;
  _sum: { simulatedPositionSize: number | null; unrealizedPnl: number | null };
  _count: { _all: number };
  _min: { openedAt: Date | null };
};

type LatestSnap = {
  marketId: string;
  collectedAt: number | bigint | string | Date | null;
  timeToResolution: number | null;
  question: string | null;
  isDemo: number | boolean | null;
};

/** SQLite DATETIME columns in this DB hold Unix-ms integers; raw reads may
 *  hand them back as number/bigint/Date depending on the driver path. */
function toMs(value: LatestSnap["collectedAt"]): number | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "number") return value;
  if (typeof value === "bigint") return Number(value);
  if (value instanceof Date) return value.getTime();
  const n = Number(value);
  return Number.isNaN(n) ? null : n;
}

/**
 * Load the horizon for one bot. Groups open legs by market (a market can hold
 * many legs — the Bolsonaro market alone carries 111 STANDARD legs) and joins
 * the latest snapshot per market in ONE aggregate query: MarketSnapshot is the
 * 15.8M-row / 8.6 GB table, so a per-market round trip is not an option.
 */
export async function loadOpenMtmHorizon(opts: {
  botId: string;
  nowMs?: number;
}): Promise<HorizonSummary> {
  const nowMs = opts.nowMs ?? Date.now();
  const grouped = (await prisma.paperTrade.groupBy({
    by: ["marketId"],
    where: { botId: opts.botId, status: "open" },
    _sum: { simulatedPositionSize: true, unrealizedPnl: true },
    _count: { _all: true },
    _min: { openedAt: true },
  })) as unknown as OpenGroupRow[];

  if (grouped.length === 0) return summarizeHorizon(opts.botId, [], nowMs);

  const marketIds = grouped.map((g) => g.marketId);
  const snaps = await prisma.$queryRaw<LatestSnap[]>(Prisma.sql`
    SELECT marketId, MAX(collectedAt) AS collectedAt, timeToResolution, question, isDemo
    FROM MarketSnapshot
    WHERE marketId IN (${Prisma.join(marketIds)})
    GROUP BY marketId
  `);
  const latest = new Map(snaps.map((s) => [s.marketId, s]));

  const groups = grouped.map((g) => {
    const snap = latest.get(g.marketId);
    return toGroup({
      marketId: g.marketId,
      legs: g._count._all,
      cost: g._sum.simulatedPositionSize ?? 0,
      unrealized: g._sum.unrealizedPnl ?? 0,
      openedAtMs: g._min.openedAt ? new Date(g._min.openedAt).getTime() : null,
      isDemo: Boolean(snap?.isDemo),
      question: snap?.question ?? null,
      snapshotMs: snap ? toMs(snap.collectedAt) : null,
      ttrHours: snap?.timeToResolution ?? null,
      nowMs,
    });
  });

  return summarizeHorizon(opts.botId, groups, nowMs);
}
