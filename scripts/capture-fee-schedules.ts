/**
 * capture:fees — append-only capture of RESOLVED fee schedules per market.
 *
 * WHY (audit §P2, draft drafts/polyterm-audit-2026-09-28.md):
 * our admission gate prices the taker fee with `takerFeePerShare(price, feeRate)`
 * (src/lib/scoring/price-edge.ts) — the right curve, but the RATE is a proxy:
 * `PRICE_EDGE_SPEC_V1.defaultFeeRate = 0.05` plus a keyword table (crypto .07,
 * politics/finance .04) inferred from text because `MarketSnapshot.category` is
 * NULL on every row. The venue publishes the real per-market schedule
 * (`feesEnabled`, `feeSchedule{rate, exponent, takerOnly, rebateRate}`) and a
 * per-token CLOB `/fee-rate`. Capturing both lets the fee assumption be
 * measured instead of assumed — the backtest design already prices the missing
 * vig at gross +$5,397.60 -> net +$2,933.77 with 238 winner->loser flips.
 *
 * WHAT THIS DOES NOT DO: it changes no rule, no size, no gate and no published
 * number. The Kelly measurement window is frozen through 2026-10-08 and this is
 * data acquisition only (explicitly allowed mid-freeze). Nothing in the live
 * path reads the output file.
 *
 * MODES
 *   (default)   fetch the top-N active markets, append one JSONL row per market
 *   --dry       print the summary, write nothing
 *
 * ENV
 *   FEE_CAPTURE_MAX     markets to sample (default 25)
 *   FEE_CAPTURE_CLOB    "1" to also query CLOB /fee-rate per token (default 0)
 *   FEE_CAPTURE_PAGE    Gamma page size for the universe pull (default 100)
 */

import { appendFileSync } from "fs";
import { join } from "path";
import { categoryFeeRate, takerFeePerShare, PRICE_EDGE_SPEC_V1 } from "../src/lib/scoring/price-edge";
import { gammaProvenance, clobWsProvenance } from "../src/lib/provenance";
import { VENUE, asNumber, parseJsonArray, venueGetJson } from "../src/lib/venue-read";
import { log, logError } from "../src/lib/redact";

const OUT = join(__dirname, "..", "data", "fee-schedules.jsonl");
const MAX = Number(process.env.FEE_CAPTURE_MAX ?? 25);
const PAGE = Number(process.env.FEE_CAPTURE_PAGE ?? 100);
const WITH_CLOB = String(process.env.FEE_CAPTURE_CLOB ?? "0") === "1";
const DRY = process.argv.includes("--dry");

type GammaMarket = Record<string, unknown>;

/** Market universe: the venue's own top-N by trailing 24h volume, active only. */
async function fetchUniverse(limit: number): Promise<GammaMarket[]> {
  const url =
    `${VENUE.gamma}/markets?limit=${limit}&active=true&closed=false&archived=false` +
    `&order=volume24hr&ascending=false`;
  const data = await venueGetJson(url);
  if (!Array.isArray(data)) throw new Error(`unexpected gamma shape: ${typeof data}`);
  return data as GammaMarket[];
}

type FeeRow = {
  capturedAt: string;
  slug: string;
  conditionId?: string;
  tokenId?: string;
  /** Venue-side truth. */
  feesEnabled?: boolean;
  /**
   * The venue's own discriminator (`zero_fees`, `sports_fees_v3`,
   * `crypto_fees_v2`, `economics_fees`, `politics_fees`, …). Measured
   * 2026-09-28: rate is a pure function of this field, so it — not a keyword
   * match on the slug — is what a fee model should key on.
   */
  feeType?: string;
  feeSchedule?: unknown;
  takerBaseFee?: number;
  makerBaseFee?: number;
  resolvedRate?: number;
  resolvedExponent?: number;
  rebateRate?: number;
  feeSource: "market" | "clob" | "none";
  clobFeeRate?: unknown;
  /** Our side, as the live gate would price it today. */
  proxyRate: number;
  proxySource: string;
  /** Fee per share at the observed mid, both ways — the number that matters. */
  midPrice?: number;
  proxyFeePerShare?: number;
  resolvedFeePerShare?: number;
  feePerShareDelta?: number;
  volume24hr?: number;
  liquidity?: number;
  provenance: unknown;
  qualityFlags: string[];
};

/** Resolve the venue's rate + exponent from a Gamma market row. */
function resolveFromGamma(m: GammaMarket): { rate?: number; exponent?: number; rebate?: number; source: FeeRow["feeSource"] } {
  if (m.feesEnabled === false) return { rate: 0, exponent: 1, source: "market" };
  const sched = typeof m.feeSchedule === "string" ? safeParse(m.feeSchedule) : m.feeSchedule;
  if (sched && typeof sched === "object" && !Array.isArray(sched)) {
    const s = sched as Record<string, unknown>;
    const rate = asNumber(s.rate);
    if (rate !== undefined) {
      return {
        rate,
        exponent: asNumber(s.exponent) ?? 1,
        rebate: asNumber(s.rebateRate),
        source: "market",
      };
    }
  }
  const base = asNumber(m.takerBaseFee);
  if (base !== undefined) return { rate: base / 10000, exponent: 1, source: "market" };
  return { source: "none" };
}

function safeParse(s: string): unknown {
  try {
    return JSON.parse(s);
  } catch {
    return undefined;
  }
}

/**
 * Quality flags that encode what the 2026-09-28 capture learned about these
 * fields, so a later reader does not have to re-derive it:
 *
 *  - `takerBaseFee` / `makerBaseFee` / CLOB `/fee-rate.base_fee` are a STATIC
 *    1000 on every market measured (34/40), including markets whose schedule
 *    says rate 0. They are not market truth; `feeSchedule.rate` is. A fallback
 *    that reads base_fee as a rate would charge ~0.10/share and reject trades
 *    the venue charges nothing for.
 *  - `feeType` is the discriminator the venue actually uses, and 6/40 markets
 *    carried none, so a consumer must handle its absence explicitly.
 */
function feeQualityFlags(m: GammaMarket, rate: number | undefined, source: FeeRow["feeSource"]): string[] {
  const flags: string[] = [];
  const feeType = m.feeType === undefined || m.feeType === null ? "" : String(m.feeType);
  if (!feeType) flags.push("fee_type_missing");
  if (feeType === "zero_fees") flags.push("venue_zero_fee_market");
  const base = asNumber(m.takerBaseFee);
  if (base !== undefined && base > 0 && rate === 0) flags.push("base_fee_field_disagrees_with_schedule");
  if (source === "clob") flags.push("clob_fallback_unit_unverified");
  return flags;
}

async function clobFeeRate(tokenId: string): Promise<unknown> {
  return venueGetJson(`${VENUE.clob}/fee-rate?token_id=${encodeURIComponent(tokenId)}`);
}

async function main(): Promise<number> {
  const universe = await fetchUniverse(PAGE);
  const ranked = [...universe]
    .sort((a, b) => (asNumber(b.volume24hr) ?? 0) - (asNumber(a.volume24hr) ?? 0))
    .slice(0, MAX);
  log(`[fees] universe=${universe.length} sampling=${ranked.length} clob=${WITH_CLOB ? "on" : "off"}${DRY ? " dry" : ""}`);

  const rows: FeeRow[] = [];
  for (const m of ranked) {
    const slug = String(m.slug ?? "");
    if (!slug) continue;
    const resolved = resolveFromGamma(m);
    const tokens = parseJsonArray(m.clobTokenIds) ?? [];
    const tokenId = tokens.length > 0 ? String(tokens[0]) : undefined;

    let clobRaw: unknown;
    let rate = resolved.rate;
    let exponent = resolved.exponent ?? 1;
    let source = resolved.source;
    if (WITH_CLOB && tokenId) {
      try {
        clobRaw = await clobFeeRate(tokenId);
        const base = asNumber((clobRaw as Record<string, unknown>)?.base_fee);
        if (base !== undefined && rate === undefined) {
          rate = base / 10000;
          exponent = 1;
          source = "clob";
        }
      } catch (e) {
        logError(`[fees] clob fee-rate failed for ${slug}: ${e instanceof Error ? e.message : e}`);
      }
    }

    const prices = parseJsonArray(m.outcomePrices);
    const yes = prices && prices.length > 0 ? asNumber(prices[0]) : undefined;
    const no = prices && prices.length > 1 ? asNumber(prices[1]) : undefined;
    const mid = yes !== undefined && no !== undefined ? (yes + no) / 2 : yes;

    const proxyRate = categoryFeeRate(`${slug} ${String(m.question ?? "")}`);
    const proxyFee = mid !== undefined ? takerFeePerShare(mid, proxyRate) : undefined;
    const resolvedFee = mid !== undefined && rate !== undefined ? takerFeePerShare(mid, rate) : undefined;

    rows.push({
      capturedAt: new Date().toISOString(),
      slug,
      conditionId: m.conditionId ? String(m.conditionId) : undefined,
      tokenId,
      feesEnabled: m.feesEnabled === undefined ? undefined : Boolean(m.feesEnabled),
      feeType: m.feeType === undefined || m.feeType === null ? undefined : String(m.feeType),
      feeSchedule: m.feeSchedule,
      takerBaseFee: asNumber(m.takerBaseFee),
      makerBaseFee: asNumber(m.makerBaseFee),
      resolvedRate: rate,
      resolvedExponent: exponent,
      rebateRate: resolved.rebate,
      feeSource: source,
      clobFeeRate: clobRaw,
      proxyRate,
      proxySource: `price-edge.ts defaultFeeRate ${PRICE_EDGE_SPEC_V1.defaultFeeRate} + keyword table`,
      midPrice: mid,
      proxyFeePerShare: proxyFee,
      resolvedFeePerShare: resolvedFee,
      feePerShareDelta: proxyFee !== undefined && resolvedFee !== undefined ? proxyFee - resolvedFee : undefined,
      volume24hr: asNumber(m.volume24hr),
      liquidity: asNumber(m.liquidityNum) ?? asNumber(m.liquidity),
      provenance: rate !== undefined && source === "clob" ? clobWsProvenance(["fee_rate_endpoint"]) : gammaProvenance(["fee_schedule"]),
      qualityFlags: [
        "capture_only",
        "not_read_by_live_path",
        ...(rate === undefined ? ["no_venue_fee_schedule_found"] : []),
        ...(mid === undefined ? ["mid_price_unavailable"] : []),
        ...feeQualityFlags(m, rate, source),
      ].filter(Boolean),
    });
  }

  if (!DRY) {
    appendFileSync(OUT, rows.map((r) => JSON.stringify(r)).join("\n") + "\n");
  }

  const withResolved = rows.filter((r) => r.resolvedRate !== undefined);
  const differing = withResolved.filter((r) => Math.abs((r.feePerShareDelta ?? 0)) > 1e-9);
  log(`[fees] rows=${rows.length} venue_schedule_found=${withResolved.length} proxy_differs=${differing.length}`);
  if (withResolved.length > 0) {
    const deltas = differing.map((r) => r.feePerShareDelta ?? 0);
    const mean = deltas.length ? deltas.reduce((a, b) => a + b, 0) / deltas.length : 0;
    log(
      `[fees] per-share delta (proxy - venue) on differing markets: mean=${mean.toFixed(4)} ` +
        `min=${Math.min(...deltas, 0).toFixed(4)} max=${Math.max(...deltas, 0).toFixed(4)}`
    );
    for (const r of withResolved.slice(0, 10)) {
      log(
        `[fees]   ${r.slug.slice(0, 46)} type=${r.feeType ?? "-"} venue_rate=${r.resolvedRate} exp=${r.resolvedExponent} rebate=${r.rebateRate ?? "-"} ` +
          `proxy_rate=${r.proxyRate} delta/share=${(r.feePerShareDelta ?? 0).toExponential(3)}`
      );
    }
  }
  log(`[fees] ${DRY ? "dry run — nothing written" : `appended ${rows.length} rows -> ${OUT}`}`);
  return 0;
}

main()
  .then((code) => process.exit(code))
  .catch((e) => {
    logError(`[fees] fatal: ${e instanceof Error ? e.message : e}`);
    process.exit(1);
  });
