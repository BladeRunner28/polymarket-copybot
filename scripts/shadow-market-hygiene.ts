/**
 * shadow:hygiene — offline market-hygiene scores (wash trade, risk grade,
 * holder concentration). ADVISORY ONLY.
 *
 * WHY (audit §P3/§P5, draft drafts/polyterm-audit-2026-09-28.md):
 * we have no market-hygiene prior at all — `grep -rniE "wash" src/lib src/app`
 * = 0, and no market-level risk grade. polyterm ships deterministic, unit-tested
 * formulas for both (core/wash_trade_detector.py, core/risk_score.py), and the
 * Data API exposes per-market holder lists we never read (`/holders`, 0 matches
 * in our repo).
 *
 * WHAT THIS DOES NOT DO: nothing here is a gate input. The scores are labelled
 * `heuristic` + `advisory_only`, written to their own JSONL, and read by no
 * live path. Promotion requires the audit's pre-registered read (rank
 * correlation vs realized copies, per ruleSetVersion era, at window close) —
 * not this script's output being "interesting".
 *
 * ENV
 *   HYGIENE_MAX_MARKETS   markets to score (default 25)
 *   HYGIENE_HOLDERS       "0" to skip Data API /holders (default on)
 *   HYGIENE_HOLDER_LIMIT  holders per page (default 500; v2 accepts up to 1000)
 *   HYGIENE_HOLDER_MAX_PAGES  pages to walk per market (default 20; see src/lib/holders-read.ts)
 *   HYGIENE_PAGE          Gamma page size for the universe pull (default 100)
 *
 * HOLDERS ENDPOINT (repaired 2026-11-11, card polyterm-p5-holders-concentration).
 * The Data API v1 route `${dataApi}/holders?market=<conditionId>` was RETIRED — it answers
 * `410 {"error":"Data API v1 has been retired"}` — so every row this script wrote after that
 * retirement carried `holder_concentration_unavailable` and a zeroed concentration block. It now
 * reads `/v2/holders?conditionId=...`, follows `pagination.next_cursor` to EXHAUSTION, and passes
 * the enumerated sum as the outcome's supply, because "top-N share" is only a supply share when
 * the denominator is the whole holder list. A truncated walk still writes its rows, but flagged
 * `holder_supply_truncated` with `supplyComplete: false` so nobody reads an upper bound as a share.
 *
 * MODES
 *   (default)   score the top-N active markets, append JSONL
 *   --dry       print the summary, write nothing
 */

import { appendFileSync } from "fs";
import { join } from "path";
import { classifyMarketCategory } from "../src/lib/market-category";
import { holderConcentration, hygieneRow, type HolderRow, type HygieneMarketInput } from "../src/lib/market-hygiene";
import { readOutcomeHolders } from "../src/lib/holders-read";
import { gammaProvenance } from "../src/lib/provenance";
import { VENUE, asNumber, parseJsonArray, venueGetJson } from "../src/lib/venue-read";
import { log, logError } from "../src/lib/redact";

const OUT = join(__dirname, "..", "data", "market-hygiene.jsonl");
const MAX = Number(process.env.HYGIENE_MAX_MARKETS ?? 25);
const PAGE = Number(process.env.HYGIENE_PAGE ?? 100);
const WITH_HOLDERS = String(process.env.HYGIENE_HOLDERS ?? "1") !== "0";
const HOLDER_LIMIT = Number(process.env.HYGIENE_HOLDER_LIMIT ?? 500);
const HOLDER_MAX_PAGES = Number(process.env.HYGIENE_HOLDER_MAX_PAGES ?? 20);
const DRY = process.argv.includes("--dry");

type GammaMarket = Record<string, unknown>;

async function fetchUniverse(limit: number): Promise<GammaMarket[]> {
  const url =
    `${VENUE.gamma}/markets?limit=${limit}&active=true&closed=false&archived=false` +
    `&order=volume24hr&ascending=false`;
  const data = await venueGetJson(url);
  if (!Array.isArray(data)) throw new Error(`unexpected gamma shape: ${typeof data}`);
  return data as GammaMarket[];
}

/** One outcome's holder list, with the supply it accounts for when the walk reached the end. */
type OutcomeHolders = {
  outcomeIndex?: number;
  holders: HolderRow[];
  /** Sum of every listed holder amount. The supply only when `complete`. */
  supplyShares: number;
  /** True when the cursor walk reached `has_more: false` — the list is the whole holder base. */
  complete: boolean;
};

type HoldersRead =
  | { ok: true; outcomes: OutcomeHolders[]; pages: number; truncated: boolean; provenance: unknown }
  | { ok: false; error: string };

/**
 * Holders for one market, from the LAGGED Data API v2 — the v1 route is retired (410 Gone), so the
 * old `${dataApi}/holders?market=` read was returning nothing and every row silently carried a
 * zeroed concentration block. The walk lives in `src/lib/holders-read.ts` because the coverage read
 * over our own traded markets needs the identical pagination.
 */
async function fetchHolders(conditionId: string): Promise<HoldersRead> {
  return readOutcomeHolders(conditionId, { limit: HOLDER_LIMIT, maxPages: HOLDER_MAX_PAGES });
}

function inputFrom(market: GammaMarket): HygieneMarketInput {
  const slug = String(market.slug ?? "");
  const question = market.question === undefined ? undefined : String(market.question);
  const cls = classifyMarketCategory(slug, question ?? null);
  const bestBid = asNumber(market.bestBid);
  const bestAsk = asNumber(market.bestAsk);
  const endDateRaw = market.endDate === undefined ? undefined : String(market.endDate);
  const endDate = endDateRaw ? new Date(endDateRaw) : undefined;
  return {
    slug,
    question,
    description: market.description === undefined ? undefined : String(market.description),
    // Our coarse class feeds the dispute-rate proxy (polyterm reads a free-text
    // category field; we have a real classifier, so use it).
    categoryForRisk: cls.coarse ?? cls.fine ?? undefined,
    endDate: endDate && !isNaN(endDate.getTime()) ? endDate : undefined,
    volume24hr: asNumber(market.volume24hr) ?? asNumber(market.volume24Hour),
    liquidity: asNumber(market.liquidityNum) ?? asNumber(market.liquidity),
    spread: bestBid !== undefined && bestAsk !== undefined ? Math.max(0, bestAsk - bestBid) : asNumber(market.spread),
  };
}

async function main(): Promise<number> {
  const universe = await fetchUniverse(PAGE);
  const ranked = [...universe]
    .sort((a, b) => (asNumber(b.volume24hr) ?? 0) - (asNumber(a.volume24hr) ?? 0))
    .slice(0, MAX);
  log(`[hygiene] universe=${universe.length} scoring=${ranked.length} holders=${WITH_HOLDERS ? "on" : "off"}${DRY ? " dry" : ""}`);

  const rows: Record<string, unknown>[] = [];
  for (const m of ranked) {
    const input = inputFrom(m);
    if (!input.slug) continue;
    const base = hygieneRow(input);
    let read: HoldersRead | undefined;
    if (!WITH_HOLDERS) read = { ok: false, error: "disabled (HYGIENE_HOLDERS=0)" };
    else if (m.conditionId) read = await fetchHolders(String(m.conditionId));

    // Per outcome, because the question "can a few wallets move this outcome" is asked per outcome:
    // one side of a complementary market is routinely held almost entirely by ONE structural address
    // (measured 2026-11-11: 6 of 8 sampled markets had the same proxy_wallet as #1 holder of their
    // outcome-1 side, at 44%-99.7% of supply) while the side the crowd trades is spread over >1,000
    // wallets. A single market-level "worst outcome" number hides that; the row carries both.
    const byOutcome = read?.ok
      ? read.outcomes.map((o) => ({
          outcomeIndex: o.outcomeIndex,
          ...holderConcentration(o.holders, { supplyShares: o.supplyShares, supplyComplete: o.complete }),
        }))
      : [];
    // Worst case = most concentrated top-5 share, tie-broken on top-1 (the outcome a few wallets
    // could move most). Ties are common at the 100%-single-holder end, hence the tie-break.
    const worst = [...byOutcome].sort((a, b) => b.top5Share - a.top5Share || b.top1Share - a.top1Share)[0];
    const truncated = read?.ok ? read.truncated : false;
    const assessed = Boolean(worst?.assessed);
    rows.push({
      ...base,
      concentration: worst ?? holderConcentration([]),
      concentrationByOutcome: byOutcome,
      conditionId: m.conditionId ? String(m.conditionId) : undefined,
      volume24hr: input.volume24hr,
      liquidity: input.liquidity,
      spread: input.spread,
      holderOutcomeIndex: worst?.outcomeIndex,
      holdersBasis: {
        endpoint: "v2/holders",
        conditionId: m.conditionId ? String(m.conditionId) : undefined,
        pages: read?.ok ? read.pages : 0,
        outcomes: byOutcome.length,
        supplyComplete: assessed ? (worst?.supplyComplete ?? false) : false,
        error: read && !read.ok ? read.error : undefined,
      },
      // Two sources on one row: market metadata is Gamma, the holder list is the
      // lagged Data API. Both are labelled so neither is read as the live tape.
      provenance: { gamma: gammaProvenance(), holders: read?.ok ? read.provenance : null },
      qualityFlags: [
        ...base.qualityFlags,
        ...(assessed ? [] : ["holder_concentration_unavailable"]),
        ...(truncated ? ["holder_supply_truncated"] : []),
      ],
    });
  }

  if (!DRY) appendFileSync(OUT, rows.map((r) => JSON.stringify(r)).join("\n") + "\n");

  const bands = new Map<string, number>();
  const grades = new Map<string, number>();
  let assessed = 0;
  for (const r of rows) {
    const wash = r.wash as { band: string; assessed: boolean };
    const risk = r.risk as { grade: string };
    bands.set(wash.band, (bands.get(wash.band) ?? 0) + 1);
    grades.set(risk.grade, (grades.get(risk.grade) ?? 0) + 1);
    if (wash.assessed) assessed += 1;
  }
  log(`[hygiene] rows=${rows.length} wash_assessed=${assessed} bands=${JSON.stringify(Object.fromEntries(bands))}`);
  log(`[hygiene] grades=${JSON.stringify(Object.fromEntries(grades))}`);
  // A row whose holder read failed is NOT a zero-concentration market: count the two apart so an
  // endpoint outage cannot read as "everything is clean".
  const holderRows = rows.filter((r) => {
    const c = r.concentration as { assessed: boolean };
    return c.assessed;
  });
  const holderTruncated = rows.filter((r) => (r.qualityFlags as string[]).includes("holder_supply_truncated"));
  log(
    `[hygiene] holders=${WITH_HOLDERS ? "on" : "off"} assessed=${holderRows.length}/${rows.length}` +
      ` truncated=${holderTruncated.length}` +
      (holderRows.length < rows.length
        ? ` unavailable=${rows.length - holderRows.length} (see holdersBasis.error per row)`
        : "")
  );
  for (const r of rows.slice(0, 10)) {
    const wash = r.wash as { score: number; band: string };
    const risk = r.risk as { score: number; grade: string };
    const conc = r.concentration as { top1Share: number; top5Share: number; holderCount: number; topHolder?: { wallet?: string } };
    log(
      `[hygiene]   ${String(r.slug).slice(0, 44).padEnd(44)} wash=${String(wash.score).padStart(3)} (${wash.band}) ` +
        `risk=${String(risk.score).padStart(3)} (${risk.grade}) ` +
        `top1=${(conc.top1Share * 100).toFixed(1)}% top5=${(conc.top5Share * 100).toFixed(1)}% n=${conc.holderCount}` +
        (conc.topHolder?.wallet ? ` big=${conc.topHolder.wallet.slice(0, 10)}` : "")
    );
  }
  log(`[hygiene] ${DRY ? "dry run — nothing written" : `appended ${rows.length} rows -> ${OUT}`} (advisory only, never a gate input)`);
  return 0;
}

main()
  .then((code) => process.exit(code))
  .catch((e) => {
    logError(`[hygiene] fatal: ${e instanceof Error ? e.message : e}`);
    process.exit(1);
  });
