/**
 * Sentiment evidence adapter — maps RegulatorySignal rows to forecasting
 * EvidenceItems and aggregates a category's recent opinionated signals into a
 * calibrated edge (Phase A2, v39).
 *
 * Mapping (per the Polyseer audit, drafts/polyseer-audit.md):
 *   polarity       = sentimentScore          (-1..1)
 *   typeCap        = SOURCE_TIER_CAPS[source] (evidence tier A/B/C/D)
 *   verifiability  = confidence              (0..1)
 *   corroboration  = 1 − e^(−k₀·k), k = distinct other SOURCES agreeing
 *   consistency    = share of the batch sharing this signal's sign
 *   recency        = 1/(1 + days/120)        (processedAt age)
 *   cluster        = source                  (correlated evidence shares a cluster)
 *
 * The aggregation runs in YES-frame: `aggregateSentimentForCategory` returns
 * the calibrated edge for YES (posterior − market). Callers flip the sign for
 * NO outcomes / SELL sides.
 */

import { prisma } from "../db";
import {
  aggregateEvidenceItems,
  corroborationFactor,
  recencyFactor,
  type AggregateResult,
  type EvidenceItem,
} from "./index";

/** Evidence-tier caps (A=1.0, B=0.6, C=0.3, D=0.2) per research source. */
export const SOURCE_TIER_CAPS: Record<string, number> = {
  quiver_congress_trade: 1.0, // verifiable congressional trade disclosures
  congress_gov_api: 1.0, // official legislative data (bills, actions)
  govinfo_fr_notice: 0.6, // Federal Register notices — official but procedural
};

/** Default tier for unknown sources: C (0.3). */
export const DEFAULT_TIER_CAP = 0.3;

/** The RegulatorySignal fields the adapter consumes (DB row shape). */
export interface SignalRow {
  source: string;
  sentimentScore: number;
  confidence: number;
  processedAt: Date;
}

/** Pure: rows → evidence items (unit-tested without a DB). */
export function buildEvidenceItems(rows: SignalRow[], now: Date): EvidenceItem[] {
  const n = rows.length;
  const signOf = (s: number) => (s > 0 ? 1 : s < 0 ? -1 : 0);

  const items: EvidenceItem[] = rows.map((r) => ({
    cluster: r.source,
    polarity: r.sentimentScore,
    typeCap: SOURCE_TIER_CAPS[r.source] ?? DEFAULT_TIER_CAP,
    verifiability: Math.min(1, Math.max(0, r.confidence)),
    corroboration: 0, // filled below
    consistency: 0, // filled below
    recency: recencyFactor((now.getTime() - r.processedAt.getTime()) / 86_400_000),
  }));

  for (const it of items) {
    const s = signOf(it.polarity);
    // Corroboration: distinct OTHER sources agreeing with this signal's sign.
    // Same-cluster (same-source) items are correlated, not corroboration —
    // the cluster ρ-correction already handles their redundancy.
    const agreeingSources = new Set(
      items
        .filter((o) => o !== it && o.cluster !== it.cluster && signOf(o.polarity) === s)
        .map((o) => o.cluster)
    );
    it.corroboration = corroborationFactor(agreeingSources.size);
    // Consistency: share of the batch sharing this signal's sign.
    const sameSign = items.filter((o) => signOf(o.polarity) === s).length;
    it.consistency = n === 0 ? 0 : sameSign / n;
  }

  return items;
}

export interface SentimentAggregationOpts {
  /** Lookback window in days. */
  windowDays?: number;
  /** Min opinionated signals required to engage (else null). */
  minSignals?: number;
  /** |sentimentScore| threshold for "opinionated". */
  opinionatedThreshold?: number;
}

/**
 * Aggregate a research category's recent opinionated RegulatorySignals into a
 * calibrated YES-frame edge. Returns null when the window has too few signals
 * (caller then scores without a sentiment adjustment).
 */
export async function aggregateSentimentForCategory(
  category: string,
  yesPrice: number,
  opts: SentimentAggregationOpts = {}
): Promise<AggregateResult | null> {
  const { windowDays = 7, minSignals = 1, opinionatedThreshold = 0.3 } = opts;
  const since = new Date(Date.now() - windowDays * 86_400_000);

  const rows = await prisma.regulatorySignal.findMany({
    where: {
      marketCategory: category,
      processedAt: { gte: since },
      OR: [
        { sentimentScore: { gte: opinionatedThreshold } },
        { sentimentScore: { lte: -opinionatedThreshold } },
      ],
    },
    orderBy: { processedAt: "asc" },
    select: { source: true, sentimentScore: true, confidence: true, processedAt: true },
  });

  if (rows.length < minSignals) return null;

  const items = buildEvidenceItems(rows, new Date());
  return aggregateEvidenceItems(items, yesPrice);
}
