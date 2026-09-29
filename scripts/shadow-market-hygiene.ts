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
 *   HYGIENE_HOLDER_LIMIT  holders per request (default 100)
 *   HYGIENE_PAGE          Gamma page size for the universe pull (default 100)
 *
 * MODES
 *   (default)   score the top-N active markets, append JSONL
 *   --dry       print the summary, write nothing
 */

import { appendFileSync } from "fs";
import { join } from "path";
import { classifyMarketCategory } from "../src/lib/market-category";
import { hygieneRow, type HolderRow, type HygieneMarketInput } from "../src/lib/market-hygiene";
import { gammaProvenance, laggedDataApiProvenance } from "../src/lib/provenance";
import { VENUE, asNumber, parseJsonArray, venueGetJson } from "../src/lib/venue-read";
import { log, logError } from "../src/lib/redact";

const OUT = join(__dirname, "..", "data", "market-hygiene.jsonl");
const MAX = Number(process.env.HYGIENE_MAX_MARKETS ?? 25);
const PAGE = Number(process.env.HYGIENE_PAGE ?? 100);
const WITH_HOLDERS = String(process.env.HYGIENE_HOLDERS ?? "1") !== "0";
const HOLDER_LIMIT = Number(process.env.HYGIENE_HOLDER_LIMIT ?? 100);
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

/**
 * Holders for one market, from the LAGGED Data API. Returns the worst-case
 * (most concentrated) outcome's holders, because the question "can a few
 * wallets move this outcome" is asked per outcome.
 */
async function fetchHolders(conditionId: string): Promise<{ holders: HolderRow[]; outcome: number; provenance: unknown } | null> {
  try {
    const data = await venueGetJson(`${VENUE.dataApi}/holders?market=${encodeURIComponent(conditionId)}&limit=${HOLDER_LIMIT}`);
    if (!Array.isArray(data) || data.length === 0) return null;
    let best: { holders: HolderRow[]; outcome: number } | null = null;
    let bestAmount = -1;
    for (const entry of data as Record<string, unknown>[]) {
      const rows = Array.isArray(entry.holders) ? (entry.holders as Record<string, unknown>[]) : [];
      const mapped: HolderRow[] = rows.map((h) => ({
        proxyWallet: h.proxyWallet ? String(h.proxyWallet) : undefined,
        amount: asNumber(h.amount),
        outcomeIndex: asNumber(h.outcomeIndex),
      }));
      const total = mapped.reduce((a, h) => a + (h.amount ?? 0), 0);
      if (total > bestAmount) {
        bestAmount = total;
        best = { holders: mapped, outcome: asNumber(entry.token) ?? mapped[0]?.outcomeIndex ?? 0 };
      }
    }
    return best ? { ...best, provenance: laggedDataApiProvenance(["holders_endpoint"]) } : null;
  } catch (e) {
    logError(`[hygiene] holders failed for ${conditionId}: ${e instanceof Error ? e.message : e}`);
    return null;
  }
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
    let holders: HolderRow[] = [];
    let holderProvenance: unknown;
    let outcomeIndex: number | undefined;
    if (WITH_HOLDERS && m.conditionId) {
      const res = await fetchHolders(String(m.conditionId));
      if (res) {
        holders = res.holders;
        holderProvenance = res.provenance;
        outcomeIndex = res.outcome;
      }
    }
    rows.push({
      ...hygieneRow(input, holders),
      conditionId: m.conditionId ? String(m.conditionId) : undefined,
      volume24hr: input.volume24hr,
      liquidity: input.liquidity,
      spread: input.spread,
      holderOutcomeIndex: outcomeIndex,
      // Two sources on one row: market metadata is Gamma, the holder list is the
      // lagged Data API. Both are labelled so neither is read as the live tape.
      provenance: { gamma: gammaProvenance(), holders: holderProvenance ?? null },
      qualityFlags: [
        "heuristic_market_hygiene",
        "advisory_only",
        "not_a_gate_input",
        ...(holders.length === 0 ? ["holder_concentration_unavailable"] : []),
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
  for (const r of rows.slice(0, 10)) {
    const wash = r.wash as { score: number; band: string };
    const risk = r.risk as { score: number; grade: string };
    const conc = r.concentration as { top1Share: number; holderCount: number };
    log(
      `[hygiene]   ${String(r.slug).slice(0, 44).padEnd(44)} wash=${String(wash.score).padStart(3)} (${wash.band}) ` +
        `risk=${String(risk.score).padStart(3)} (${risk.grade}) top1=${(conc.top1Share * 100).toFixed(1)}% n=${conc.holderCount}`
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
