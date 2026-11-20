/**
 * fee-capture — the venue's PUBLISHED fee schedule, read at export scale.
 *
 * WHY THIS EXISTS (card paper-ledger-fee-fidelity, 2026-11-20): the export's fee
 * columns were wired to venue truth on 2026-10-26 (approved), but the capture
 * only ever sampled the venue's TOP-VOLUME ACTIVE markets — 40 markets against
 * an export that spans ~4,400. So 8 markets of truth and ~5,300 rows of keyword
 * proxy. The card named the binding gap as COVERAGE, not code, and left the
 * capture across the export's market set as the unfinished step.
 *
 * TWO THINGS THE FIRST VERSION OF THE CAPTURE COULD NOT DO, both measured live
 * on 2026-11-20 and both fixed here:
 *
 *  1. `GET /markets?slug=<slug>` returns `[]` for every CLOSED market unless
 *      `&closed=true` is also passed (open-only is the endpoint default). A
 *      capture built on the obvious filter silently finds nothing for the whole
 *      settled book — which is exactly the population a fee-fidelity read needs.
 *      `GET /markets/slug/<slug>` returns the row for open AND closed markets,
 *      so that is what this module builds.
 *  2. The paged universe (`limit=500&offset=N&closed=true`) runs dry a little
 *      past offset 20,000, so paging is not a substitute for a slug walk: it
 *      cannot reach a named market reliably.
 *
 * Nothing here decides anything. The output is a rate column with its basis
 * labelled; no rule, size, gate or threshold is read from it.
 */

/**
 * The venue's rate + exponent for one market row, or `undefined` when the venue
 * published none. Mirrors the 2026-09-28 findings:
 *  - `feeSchedule.rate` is market truth and `feeType` is the discriminator;
 *  - `takerBaseFee` / `makerBaseFee` / CLOB `/fee-rate.base_fee` are a static
 *    1000 on ~85% of markets regardless of schedule, so the `base/10000`
 *    fallback is reported with `source: "clob"` and flagged by the caller.
 */
export type VenueFee = {
  rate?: number;
  exponent?: number;
  rebate?: number;
  feeType?: string;
  feesEnabled?: boolean;
  source: "market" | "clob" | "none";
};

function num(v: unknown): number | undefined {
  if (v === null || v === undefined || v === "") return undefined;
  const n = Number(v);
  return Number.isFinite(n) ? n : undefined;
}

function parseMaybeJson(v: unknown): unknown {
  if (typeof v !== "string") return v;
  try {
    return JSON.parse(v);
  } catch {
    return undefined;
  }
}

export function resolveVenueFee(m: Record<string, unknown>): VenueFee {
  const feeType = m.feeType === undefined || m.feeType === null ? undefined : String(m.feeType);
  const feesEnabled = m.feesEnabled === undefined ? undefined : Boolean(m.feesEnabled);
  if (m.feesEnabled === false) return { rate: 0, exponent: 1, feeType, feesEnabled, source: "market" };
  const sched = parseMaybeJson(m.feeSchedule);
  if (sched && typeof sched === "object" && !Array.isArray(sched)) {
    const s = sched as Record<string, unknown>;
    const rate = num(s.rate);
    if (rate !== undefined) {
      return {
        rate,
        exponent: num(s.exponent) ?? 1,
        rebate: num(s.rebateRate),
        feeType,
        feesEnabled,
        source: "market",
      };
    }
  }
  const base = num(m.takerBaseFee);
  if (base !== undefined) {
    return { rate: base / 10000, exponent: 1, feeType, feesEnabled, source: "market" };
  }
  return { feeType, feesEnabled, source: "none" };
}

/**
 * Distinct markets of the training export, in first-seen order.
 *
 * The export's `market_id` IS the venue slug (the export script says so: its
 * join against the venue is slug-keyed, and a conditionId join returns 0). The
 * column is located BY NAME, never by position, so an added column cannot shift
 * the read. Blank ids and the header are dropped; order is preserved so a
 * partial run is a prefix of the next run's work, not a random sample.
 */
export function parseExportSlugs(csv: string): string[] {
  const lines = csv.split("\n");
  if (lines.length === 0) return [];
  const header = lines[0].replace(/\r$/, "").split(",");
  const ix = header.indexOf("market_id");
  if (ix < 0) throw new Error("training export has no market_id column — refusing to guess a position");
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of lines.slice(1)) {
    if (!raw.trim()) continue;
    const slug = (raw.replace(/\r$/, "").split(",")[ix] ?? "").trim();
    if (!slug || seen.has(slug)) continue;
    seen.add(slug);
    out.push(slug);
  }
  return out;
}

/** Slugs already carrying a venue rate in the append-only capture file. */
export function capturedSlugs(jsonl: string): Set<string> {
  const out = new Set<string>();
  for (const line of jsonl.split("\n")) {
    const t = line.trim();
    if (!t) continue;
    try {
      const o = JSON.parse(t) as { slug?: unknown; resolvedRate?: unknown };
      if (typeof o.slug === "string" && typeof o.resolvedRate === "number" && Number.isFinite(o.resolvedRate)) {
        out.add(o.slug);
      }
    } catch {
      /* a malformed line is skipped, not fatal: the capture is append-only */
    }
  }
  return out;
}

/**
 * The rate URL for one market. `/markets/slug/<slug>` (not `?slug=`) because the
 * query form hides every closed market unless `closed=true` is added — see the
 * module note. Percent-encoding is required: slugs are ASCII, but a caller that
 * ever passes something else must not silently match a different market.
 */
export function slugMarketUrl(base: string, slug: string): string {
  return `${base}/markets/slug/${encodeURIComponent(slug)}`;
}

/**
 * Venue row out of a `/markets/slug/<slug>` response. The endpoint returns one
 * object; the list form returns an array. Both are accepted so the two call
 * shapes cannot disagree.
 */
export function pickMarketRow(payload: unknown): Record<string, unknown> | undefined {
  if (Array.isArray(payload)) {
    const first = payload[0];
    return first && typeof first === "object" ? (first as Record<string, unknown>) : undefined;
  }
  if (payload && typeof payload === "object") return payload as Record<string, unknown>;
  return undefined;
}

/**
 * Fee per share under `rate` at `mid`, on the venue's own curve
 * `shares × rate × p × (1-p)`. Computed here (rather than importing the scoring
 * spec) so the capture can state a delta for a rate the live spec cannot
 * express — 0.03 is such a rate, and it is the whole point of the capture.
 */
export function feePerShare(price: number, rate: number): number {
  return rate * price * (1 - price);
}
