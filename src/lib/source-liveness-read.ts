/**
 * The DB side of research-source liveness. Kept apart from
 * `source-liveness.ts` so the classification stays pure and testable, and shared
 * by BOTH surfaces that must show the alarm: the standalone check
 * (`npm run research:source-liveness`) and the EOD report. One query set, so the
 * two can never disagree about whether a source is alive.
 *
 * BASIS, stated once here because every caller inherits it: population =
 * RegulatorySignal rows (the table has no demo flag — the layer reads every
 * row), clock = processedAt UTC, level = one source, "opinionated" =
 * |sentimentScore| >= 0.30 (the aggregation's own threshold).
 */

import { prisma } from "./db";
import {
  LIVENESS_OPINIONATED_THRESHOLD as T,
  classifyAll,
  livenessLine,
  type SourceEmission,
} from "./source-liveness";

export async function readSourceEmissions(since: Date): Promise<SourceEmission[]> {
  const [allTime, allTimeOp, win, winOp] = await Promise.all([
    prisma.regulatorySignal.groupBy({ by: ["source"], _count: { _all: true }, _max: { processedAt: true } }),
    prisma.regulatorySignal.groupBy({
      by: ["source"],
      where: { OR: [{ sentimentScore: { gte: T } }, { sentimentScore: { lte: -T } }] },
      _count: { _all: true },
    }),
    prisma.regulatorySignal.groupBy({ by: ["source"], where: { processedAt: { gte: since } }, _count: { _all: true } }),
    prisma.regulatorySignal.groupBy({
      by: ["source"],
      where: { processedAt: { gte: since }, OR: [{ sentimentScore: { gte: T } }, { sentimentScore: { lte: -T } }] },
      _count: { _all: true },
    }),
  ]);

  const n = (rows: Array<{ source: string; _count: { _all: number } }>, src: string) =>
    rows.find((r) => r.source === src)?._count._all ?? 0;

  return allTime.map((r) => ({
    source: r.source,
    rows: r._count._all,
    opinionatedRows: n(allTimeOp, r.source),
    windowRows: n(win, r.source),
    windowOpinionated: n(winOp, r.source),
    lastEmitAt: r._max.processedAt ?? null,
  }));
}

/**
 * The EOD line. On a failed read it returns a LOUD line rather than nothing:
 * "the instrument could not read" and "every source is healthy" must not print
 * the same way (the silent-alert class this board keeps repairing).
 */
export async function researchLivenessLine(now: Date, windowDays = 7): Promise<string> {
  try {
    const since = new Date(now.getTime() - windowDays * 86_400_000);
    const readings = classifyAll(await readSourceEmissions(since), now);
    return livenessLine(readings, now);
  } catch (e) {
    return `• ⚠️ Research sources: read FAILED (${e instanceof Error ? e.message : String(e)}) — supply cannot be judged this run`;
  }
}
