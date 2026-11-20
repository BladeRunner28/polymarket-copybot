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

import { appendFileSync, existsSync, readFileSync, writeFileSync } from "fs";
import { join } from "path";
import { categoryFeeRate, takerFeePerShare, PRICE_EDGE_SPEC_V1 } from "../src/lib/scoring/price-edge";
import { gammaProvenance, clobWsProvenance } from "../src/lib/provenance";
import { VENUE, asNumber, parseJsonArray, venueGetJson } from "../src/lib/venue-read";
import { log, logError } from "../src/lib/redact";
import {
  capturedSlugs,
  feePerShare,
  parseExportSlugs,
  pickMarketRow,
  resolveVenueFee,
  slugMarketUrl,
} from "../src/lib/fee-capture";

const OUT = join(__dirname, "..", "data", "fee-schedules.jsonl");
const MAX = Number(process.env.FEE_CAPTURE_MAX ?? 25);
const PAGE = Number(process.env.FEE_CAPTURE_PAGE ?? 100);
const WITH_CLOB = String(process.env.FEE_CAPTURE_CLOB ?? "0") === "1";
const DRY = process.argv.includes("--dry");
// 2026-11-20 (card paper-ledger-fee-fidelity, "coverage is the binding gap"):
// capture the venue's schedule for every market the TRAINING EXPORT contains,
// not just the top-volume active ones. Default OFF so the existing hourly-ish
// call keeps its old behaviour and cost.
const FROM_EXPORT = process.argv.includes("--from-export");
const EXPORT_CSV = process.env.FEE_EXPORT_CSV ?? "training_data.csv";
const EXPORT_MAX = Number(process.env.FEE_EXPORT_MAX ?? Number.MAX_SAFE_INTEGER);
const CONCURRENCY = Math.max(1, Number(process.env.FEE_CAPTURE_CONCURRENCY ?? 4));
// Two artifacts, deliberately separate: `...-last-run.json` is what THIS invocation did
// (attempted / captured / the slugs the venue 404'd), `...-report.json` is the state of the
// POPULATION derived from the append-only file. One filename for both meant a 2-row resume run
// looked like the whole population's coverage.
const EXPORT_RUN_REPORT = join(__dirname, "..", "data", "fee-capture-export-last-run.json");
const EXPORT_REPORT = join(__dirname, "..", "data", "fee-capture-export-report.json");

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
/**
 * Gamma -> venue rate. The parsing lives in src/lib/fee-capture.ts so the export
 * walk and the active-market sample cannot drift apart, and so the "`?slug=`
 * hides closed markets" trap is documented one place (it silently returned `[]`
 * for every settled market when this was first written).
 */
function resolveFromGamma(m: GammaMarket): { rate?: number; exponent?: number; rebate?: number; source: FeeRow["feeSource"] } {
  const f = resolveVenueFee(m);
  return { rate: f.rate, exponent: f.exponent, rebate: f.rebate, source: f.source };
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

function countBy(xs: string[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const x of xs) out[x] = (out[x] ?? 0) + 1;
  return Object.fromEntries(Object.entries(out).sort((a, b) => b[1] - a[1]));
}

/** One capture row, from a Gamma market row. Shared by both modes. */
async function buildFeeRow(m: GammaMarket, opts: { fetchClob: boolean }): Promise<FeeRow | undefined> {
  const slug = String(m.slug ?? "");
  if (!slug) return undefined;
  const resolved = resolveFromGamma(m);
  const tokens = parseJsonArray(m.clobTokenIds) ?? [];
  const tokenId = tokens.length > 0 ? String(tokens[0]) : undefined;

  let clobRaw: unknown;
  let rate = resolved.rate;
  let exponent = resolved.exponent ?? 1;
  let source = resolved.source;
  if (opts.fetchClob && tokenId) {
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

  // A CLOSED market's outcomePrices are the SETTLEMENT MARK (0/1), not a trade
  // price: pricing a fee-per-share off it would manufacture a 0.25 x rate delta
  // that no trade ever paid. Closed rows therefore carry RATES only, and the
  // money impact is measured where the real entry prices are — the export re-run.
  const closed = m.closed === true;
  const prices = parseJsonArray(m.outcomePrices);
  const yes = !closed && prices && prices.length > 0 ? asNumber(prices[0]) : undefined;
  const no = !closed && prices && prices.length > 1 ? asNumber(prices[1]) : undefined;
  const mid = yes !== undefined && no !== undefined ? (yes + no) / 2 : yes;

  const proxyRate = categoryFeeRate(`${slug} ${String(m.question ?? "")}`);
  const proxyFee = mid !== undefined ? takerFeePerShare(mid, proxyRate) : undefined;
  const resolvedFee = mid !== undefined && rate !== undefined ? takerFeePerShare(mid, rate) : undefined;

  return {
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
      ...(closed ? ["closed_market_price_is_settlement_mark"] : []),
      ...(rate === undefined ? ["no_venue_fee_schedule_found"] : []),
      ...(mid === undefined && !closed ? ["mid_price_unavailable"] : []),
      ...feeQualityFlags(m, rate, source),
    ].filter(Boolean),
  };
}

function summarize(rows: FeeRow[]): void {
  const withResolved = rows.filter((r) => r.resolvedRate !== undefined);
  const differing = withResolved.filter((r) => Math.abs(r.resolvedRate! - r.proxyRate) > 1e-9);
  log(
    `[fees] rows=${rows.length} venue_schedule_found=${withResolved.length} ` +
      `rate_differs_from_proxy=${differing.length}` +
      (withResolved.length ? ` (${((100 * differing.length) / withResolved.length).toFixed(1)}% of found)` : "")
  );
  const byRate = new Map<string, number>();
  for (const r of withResolved) byRate.set(String(r.resolvedRate), (byRate.get(String(r.resolvedRate)) ?? 0) + 1);
  if (byRate.size > 0) {
    log(
      `[fees] venue rates: ` +
        [...byRate.entries()].sort((a, b) => b[1] - a[1]).map(([r, n]) => `${r}=${n}`).join(" ")
    );
  }
  const byType = new Map<string, number>();
  for (const r of withResolved) byType.set(r.feeType ?? "(none)", (byType.get(r.feeType ?? "(none)") ?? 0) + 1);
  if (byType.size > 0) {
    log(
      `[fees] feeType: ` +
        [...byType.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12).map(([t, n]) => `${t}=${n}`).join(" ")
    );
  }
  if (withResolved.length > 0) {
    const deltas = withResolved.filter((r) => r.feePerShareDelta !== undefined).map((r) => r.feePerShareDelta!);
    if (deltas.length > 0) {
      const mean = deltas.reduce((a, b) => a + b, 0) / deltas.length;
      log(
        `[fees] open-market per-share delta (proxy - venue), n=${deltas.length}: mean=${mean.toFixed(4)} ` +
          `min=${Math.min(...deltas).toFixed(4)} max=${Math.max(...deltas).toFixed(4)}`
      );
    }
  }
}

function appendRows(rows: FeeRow[]): void {
  if (rows.length === 0) return;
  appendFileSync(OUT, rows.map((r) => JSON.stringify(r)).join("\n") + "\n");
}

/** Mode 1 (default): the venue's top-volume ACTIVE markets. Unchanged behaviour. */
async function captureActive(): Promise<number> {
  const universe = await fetchUniverse(PAGE);
  const ranked = [...universe]
    .sort((a, b) => (asNumber(b.volume24hr) ?? 0) - (asNumber(a.volume24hr) ?? 0))
    .slice(0, MAX);
  log(`[fees] universe=${universe.length} sampling=${ranked.length} clob=${WITH_CLOB ? "on" : "off"}${DRY ? " dry" : ""}`);

  const rows: FeeRow[] = [];
  for (const m of ranked) {
    const row = await buildFeeRow(m, { fetchClob: WITH_CLOB });
    if (row) rows.push(row);
  }
  if (!DRY) appendRows(rows);
  summarize(rows);
  log(`[fees] ${DRY ? "dry run — nothing written" : `appended ${rows.length} rows -> ${OUT}`}`);
  return 0;
}

/**
 * Mode 2 (`--from-export`): every distinct market_id in the training export.
 *
 * The export's `market_id` is the venue SLUG, and the population is mostly
 * CLOSED — which is why this mode uses `/markets/slug/<slug>` rather than the
 * `?slug=` query (that form returns `[]` for closed markets; see
 * src/lib/fee-capture.ts). Already-captured slugs are skipped, so the file stays
 * append-only, a re-run is cheap, and an interrupted run resumes as a prefix.
 */
async function captureExport(): Promise<number> {
  if (!existsSync(EXPORT_CSV)) throw new Error(`export not found: ${EXPORT_CSV}`);
  const allSlugs = parseExportSlugs(readFileSync(EXPORT_CSV, "utf8"));
  const have = existsSync(OUT) ? capturedSlugs(readFileSync(OUT, "utf8")) : new Set<string>();
  const todo = allSlugs.filter((s) => !have.has(s)).slice(0, EXPORT_MAX);
  log(
    `[fees] export=${EXPORT_CSV} distinct_markets=${allSlugs.length} already_captured=${allSlugs.filter((s) => have.has(s)).length} ` +
      `todo=${todo.length} concurrency=${CONCURRENCY} clob=${WITH_CLOB ? "on" : "off"}${DRY ? " dry" : ""}`
  );

  // Every captured row is kept for the SUMMARY; a splice-and-append copy is what
  // goes to disk. The first cut summarized the final partial flush instead (128
  // of 4,388 rows), which reported a run total that was really a tail.
  const collected: FeeRow[] = [];
  const rows: FeeRow[] = []; // write buffer, flushed every 250 rows
  const failedSlugs: Array<{ slug: string; error: string }> = [];
  let missing = 0;
  let failed = 0;
  let done = 0;
  const queue = [...todo];
  const worker = async (): Promise<void> => {
    for (;;) {
      const slug = queue.shift();
      if (slug === undefined) return;
      // 429 / 5xx retry: one attempt is the rule for a MEASUREMENT script, but a
      // cap read that gives up on the first throttle would file a partial
      // population as complete. 4xx-other is not retried, and is counted.
      let payload: unknown;
      let lastErr: unknown;
      for (let attempt = 1; attempt <= 4; attempt++) {
        try {
          payload = await venueGetJson(slugMarketUrl(VENUE.gamma, slug));
          lastErr = undefined;
          break;
        } catch (e) {
          lastErr = e;
          const msg = e instanceof Error ? e.message : String(e);
          const retryable = /-> (429|5\d\d)\b/.test(msg);
          if (!retryable || attempt === 4) break;
          await new Promise((r) => setTimeout(r, 400 * attempt * attempt));
        }
      }
      if (lastErr) {
        failed++;
        const msg = lastErr instanceof Error ? lastErr.message : String(lastErr);
        failedSlugs.push({ slug, error: msg.slice(0, 200) });
        if (failed <= 10) logError(`[fees] ${slug}: ${msg}`);
        continue;
      }
      const m = pickMarketRow(payload);
      if (!m) {
        missing++;
        continue;
      }
      const row = await buildFeeRow(m, { fetchClob: WITH_CLOB });
      if (row) {
        collected.push(row);
        rows.push(row);
      }
      done++;
      if (rows.length > 0 && rows.length % 250 === 0) {
        if (!DRY) {
          appendRows(rows.splice(0, rows.length));
        }
        log(`[fees] progress ${done}/${todo.length} (found=${collected.length} missing=${missing} failed=${failed})`);
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(CONCURRENCY, Math.max(1, todo.length)) }, () => worker()));

  if (!DRY) appendRows(rows);
  summarize(collected);
  const report = {
    capturedAt: new Date().toISOString(),
    exportCsv: EXPORT_CSV,
    distinctMarketsInExport: allSlugs.length,
    alreadyCaptured: allSlugs.length - todo.length,
    attempted: todo.length,
    answered: done,
    captured: collected.length,
    missingRow: missing,
    failed,
    failedSlugs,
    rates: countBy(collected.map((r) => (r.resolvedRate === undefined ? "none" : String(r.resolvedRate)))),
    feeTypes: countBy(collected.map((r) => r.feeType ?? "(none)")),
    proxyDisagreements: collected.filter((r) => r.resolvedRate !== undefined && Math.abs(r.resolvedRate - r.proxyRate) > 1e-9).length,
    proxyDisagreementsByRate: countBy(
      collected
        .filter((r) => r.resolvedRate !== undefined && Math.abs(r.resolvedRate - r.proxyRate) > 1e-9)
        .map((r) => `proxy ${r.proxyRate} -> venue ${r.resolvedRate}`)
    ),
  };
  if (!DRY) writeFileSync(EXPORT_RUN_REPORT, JSON.stringify(report, null, 2) + "\n");
  log(
    `[fees] ${DRY ? "dry run — nothing written" : `appended ${collected.length} rows -> ${OUT}`} ` +
      `| attempted=${todo.length} answered=${done} captured=${collected.length} missing=${missing} failed=${failed}`
  );
  log(`[fees] run report -> ${EXPORT_RUN_REPORT}`);
  return failed > 0 && collected.length === 0 ? 1 : 0;
}

/**
 * `--summarize-only`: re-print the aggregate for the markets the export contains,
 * from the capture file alone (no network). This is what makes the population
 * claim re-checkable after the fact instead of living in a terminal scrollback.
 */
function summarizeOnly(): number {
  if (!existsSync(OUT)) throw new Error(`capture file not found: ${OUT}`);
  const exportSlugs = new Set(parseExportSlugs(readFileSync(EXPORT_CSV, "utf8")));
  const inExport: FeeRow[] = [];
  let outside = 0;
  for (const line of readFileSync(OUT, "utf8").split("\n")) {
    const t = line.trim();
    if (!t) continue;
    try {
      const r = JSON.parse(t) as FeeRow;
      if (!r || typeof r.slug !== "string") continue;
      if (exportSlugs.has(r.slug)) inExport.push(r);
      else outside++;
    } catch {
      /* malformed line: skipped, as everywhere else in this file */
    }
  }
  const capturedSet = new Set(inExport.map((r) => r.slug));
  const uncaptured = [...exportSlugs].filter((s) => !capturedSet.has(s));
  log(
    `[fees] capture rows in export=${inExport.length} distinct=${capturedSet.size} of ${exportSlugs.size} export markets ` +
      `(rows outside export: ${outside}, markets with no capture row: ${uncaptured.length})`
  );
  summarize(inExport);
  // Same artifact the capture writes, derived from the file — so the population claim is
  // re-checkable in one command instead of living in a terminal scrollback.
  const report = {
    capturedAt: new Date().toISOString(),
    source: "capture-file",
    exportCsv: EXPORT_CSV,
    distinctMarketsInExport: exportSlugs.size,
    captured: inExport.length,
    capturedDistinctMarkets: capturedSet.size,
    uncapturedMarkets: uncaptured,
    rowsOutsideExport: outside,
    rates: countBy(inExport.map((r) => (r.resolvedRate === undefined ? "none" : String(r.resolvedRate)))),
    feeTypes: countBy(inExport.map((r) => r.feeType ?? "(none)")),
    proxyDisagreements: inExport.filter(
      (r) => r.resolvedRate !== undefined && Math.abs(r.resolvedRate - r.proxyRate) > 1e-9
    ).length,
    proxyDisagreementsByRate: countBy(
      inExport
        .filter((r) => r.resolvedRate !== undefined && Math.abs(r.resolvedRate - r.proxyRate) > 1e-9)
        .map((r) => `proxy ${r.proxyRate} -> venue ${r.resolvedRate}`)
    ),
  };
  writeFileSync(EXPORT_REPORT, JSON.stringify(report, null, 2) + "\n");
  log(`[fees] report -> ${EXPORT_REPORT}`);
  return 0;
}

async function main(): Promise<number> {
  if (process.argv.includes("--summarize-only")) return summarizeOnly();
  return FROM_EXPORT ? captureExport() : captureActive();
}

main()
  .then((code) => process.exit(code))
  .catch((e) => {
    logError(`[fees] fatal: ${e instanceof Error ? e.message : e}`);
    process.exit(1);
  });
