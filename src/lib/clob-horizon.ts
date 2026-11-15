/**
 * Horizon prices for a decision, read from the venue's own fill tape.
 *
 * WHY THIS EXISTS (card `data2-per-decision-provenance`)
 * ----------------------------------------------------
 * OutcomeReview.priceAfter1h/6h/24h shipped in the schema and were then written by
 * NOTHING and read by NOTHING: 11,774 review rows on 2026-11-14, 0 populated, so the
 * label was binary and nothing downstream could learn timing.
 *
 * BASIS
 * -----
 * CLOB `/markets/<conditionId>` resolves the token the decision HELD (by label, not
 * by position — a named outcome like "Stephen Thompson" has no YES/NO), then
 * `/prices-history` returns that token's own prints for
 * [decidedAt, decidedAt+24h] at 1-minute fidelity. `decision-provenance.ts` owns
 * the rule for turning prints into a horizon price, so writer and probe agree.
 *
 * NOT usable as the basis: our own MarketSnapshot table — measured 2026-11-14 on
 * 400 decisions (14d), a snapshot within +/-20 min of +1h exists for 21.0%, of +6h
 * for 5.5%, of +24h for 0.0%. The snapshot writer bursts and never revisits.
 *
 * Keyless and read-only. Every failure returns null / an empty tape; nothing here
 * guesses a price, and no caller writes a value it did not measure.
 */
import { normalizeOutcomeLabel } from "./resolution";
import { horizonReads, parsePricesHistory, type HorizonRead, type PricePoint } from "./decision-provenance";

const CLOB_API = "https://clob.polymarket.com";
const UA = "copybot-research/0.1 (paper-trading-only)";

export type ClobMarket = {
  closed?: boolean;
  tokens?: Array<{ outcome?: string; token_id?: string; winner?: boolean }>;
};

const marketCache = new Map<string, ClobMarket | null>();
const historyCache = new Map<string, PricePoint[]>();

export async function clobMarketByConditionId(conditionId: string): Promise<ClobMarket | null> {
  const hit = marketCache.get(conditionId);
  if (hit !== undefined) return hit;
  let out: ClobMarket | null = null;
  try {
    const res = await fetch(`${CLOB_API}/markets/${encodeURIComponent(conditionId)}`, {
      headers: { accept: "application/json", "user-agent": UA },
      signal: AbortSignal.timeout(15000),
    });
    out = res.ok ? ((await res.json()) as ClobMarket) : null;
  } catch {
    out = null;
  }
  marketCache.set(conditionId, out);
  return out;
}

/** The token id of the label this decision held, or null when the payload cannot say. */
export function tokenIdForLabel(market: ClobMarket | null, outcomeLabel: string | null | undefined): string | null {
  const want = normalizeOutcomeLabel(outcomeLabel);
  if (!want || !market?.tokens) return null;
  for (const t of market.tokens) {
    if (!t?.token_id) continue;
    if (normalizeOutcomeLabel(t.outcome) === want) return t.token_id;
  }
  return null;
}

export async function tokenTape(tokenId: string, decisionMs: number): Promise<PricePoint[]> {
  const startTs = Math.floor(decisionMs / 1000);
  const key = `${tokenId}:${startTs}`;
  const hit = historyCache.get(key);
  if (hit) return hit;
  let points: PricePoint[] = [];
  try {
    const res = await fetch(
      `${CLOB_API}/prices-history?market=${encodeURIComponent(tokenId)}&startTs=${startTs}&endTs=${startTs + 24 * 3600}&fidelity=1`,
      { headers: { accept: "application/json", "user-agent": UA }, signal: AbortSignal.timeout(20000) }
    );
    points = res.ok ? parsePricesHistory(await res.json()) : [];
  } catch {
    points = [];
  }
  historyCache.set(key, points);
  return points;
}

export type HorizonSet = Record<"1h" | "6h" | "24h", HorizonRead>;

/**
 * The three horizon prices for one decision, or null when the token cannot be
 * identified at all (no conditionId, or a label the venue's token list does not
 * carry). A null is never written as 0 — the caller stores SQL NULL.
 */
export async function horizonPricesFor(
  conditionId: string | null | undefined,
  outcomeLabel: string | null | undefined,
  decisionMs: number
): Promise<HorizonSet | null> {
  if (!conditionId) return null;
  const market = await clobMarketByConditionId(conditionId);
  const tokenId = tokenIdForLabel(market, outcomeLabel);
  if (!tokenId) return null;
  return horizonReads(await tokenTape(tokenId, decisionMs), decisionMs);
}
