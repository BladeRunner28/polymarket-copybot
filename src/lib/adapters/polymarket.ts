/**
 * Live Polymarket adapter using public, keyless APIs:
 *  - Leaderboard:   https://data-api.polymarket.com/v1/leaderboard
 *  - User activity: https://data-api.polymarket.com/activity
 *  - Markets:       https://gamma-api.polymarket.com/markets
 *
 * READ ONLY. This adapter only performs HTTP GET requests. It cannot place
 * orders, sign anything, or move funds. If an API fails, it throws an
 * AdapterError with the real status/message — no fake data, ever.
 */

import {
  AdapterError,
  DataAdapter,
  LeaderboardEntry,
  MarketState,
  WalletActivityTrade,
} from "../types";

const DATA_API = "https://data-api.polymarket.com";
const GAMMA_API = "https://gamma-api.polymarket.com";

const DELAY_MS = Number(process.env.API_DELAY_MS ?? 250);

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

async function getJson(url: string): Promise<unknown> {
  // Retry transient failures with exponential backoff (1s/2s/4s) before
  // surfacing: Cloudflare 429s, 5xx (data-api overnight instability),
  // network errors, and truncated-body JSON parse failures.
  for (let attempt = 0; ; attempt++) {
    const retryable = attempt < 3;
    let res: Response;
    try {
      res = await fetch(url, {
        method: "GET",
        headers: { accept: "application/json", "user-agent": "copybot-research/0.1 (paper-trading-only)" },
        signal: AbortSignal.timeout(15000),
      });
    } catch (e) {
      if (retryable) {
        await sleep(1000 * 2 ** attempt);
        continue;
      }
      throw new AdapterError(url, null, e instanceof Error ? e.message : String(e));
    }
    if ((res.status === 429 || res.status >= 500) && retryable) {
      await sleep(1000 * 2 ** attempt);
      continue;
    }
    if (!res.ok) {
      const body = await res.text().catch(() => "");
      throw new AdapterError(url, res.status, body.slice(0, 300) || res.statusText);
    }
    try {
      return await res.json();
    } catch (e) {
      if (retryable) {
        await sleep(1000 * 2 ** attempt);
        continue;
      }
      throw new AdapterError(url, res.status, `invalid JSON: ${e instanceof Error ? e.message : e}`);
    }
  }
}

function num(v: unknown): number | undefined {
  if (v === null || v === undefined || v === "") return undefined;
  const n = Number(v);
  return Number.isFinite(n) ? n : undefined;
}

export class PolymarketAdapter implements DataAdapter {
  readonly source = "polymarket";
  readonly isDemo = false;
  /** Process-lifetime cache of slugs that 404'd (dead/renamed markets). */
  private static notFound = new Set<string>();

  async fetchLeaderboard(limit: number): Promise<LeaderboardEntry[]> {
    // data-api leaderboard caps page size at 50 per request; offset paginates.
    const out: LeaderboardEntry[] = [];
    const pageSize = 50;
    for (let offset = 0; offset < limit; offset += pageSize) {
      const take = Math.min(pageSize, limit - offset);
      const url = `${DATA_API}/v1/leaderboard?timePeriod=month&orderBy=PNL&limit=${take}&offset=${offset}`;
      const data = (await getJson(url)) as Array<Record<string, unknown>>;
      if (!Array.isArray(data)) {
        throw new AdapterError(url, null, `unexpected leaderboard shape: ${typeof data}`);
      }
      if (data.length === 0) break;
      for (let i = 0; i < data.length; i++) {
        const row = data[i];
        const address = String(row.proxyWallet ?? row.address ?? row.wallet ?? "");
        if (!address) continue;
        out.push({
          address: address.toLowerCase(),
          label: (row.userName as string) || (row.name as string) || undefined,
          rank: num(row.rank) ?? offset + i + 1,
          pnl: num(row.pnl) ?? num(row.amount),
          volume: num(row.vol) ?? num(row.volume),
          raw: row,
        });
      }
      if (data.length < take) break;
      await sleep(DELAY_MS);
    }
    return out;
  }

  /**
   * Wallet activity for PROFILING. Raw /activity is useless for scoring
   * hyperactive wallets (500-trade pages cover minutes, resolved markets never
   * appear), so we build the picture from the positions APIs instead:
   *   - /closed-positions  -> resolved trades with realized PnL
   *   - /positions         -> open (unresolved) exposure
   * Then enrich liquidity/spread for a sample of markets via gamma.
   */
  async fetchWalletActivity(address: string, days: number): Promise<WalletActivityTrade[]> {
    // Short windows (trade monitoring) still use the raw activity feed.
    if (days <= 2) return this.fetchRecentTrades(address, days);

    const out: WalletActivityTrade[] = [];

    // Fetch BOTH tails of closed positions (best and worst realized PnL).
    // Taking only the top-100 winners would fake a ~100% win rate.
    const closedRows: Record<string, unknown>[] = [];
    const seenAssets = new Set<string>();
    for (const dir of ["DESC", "ASC"] as const) {
      const closedUrl = `${DATA_API}/closed-positions?user=${address}&limit=50&sortBy=REALIZEDPNL&sortDirection=${dir}`;
      const page = (await getJson(closedUrl)) as Array<Record<string, unknown>>;
      if (!Array.isArray(page)) {
        throw new AdapterError(closedUrl, null, `unexpected closed-positions shape`);
      }
      for (const row of page) {
        const key = String(row.asset ?? row.conditionId ?? Math.random());
        if (seenAssets.has(key)) continue;
        seenAssets.add(key);
        closedRows.push(row);
      }
      await sleep(DELAY_MS);
    }
    for (const row of closedRows) {
      const avgPrice = num(row.avgPrice);
      const totalBought = num(row.totalBought);
      const realizedPnl = num(row.realizedPnl);
      if (avgPrice === undefined || totalBought === undefined || realizedPnl === undefined) continue;
      const sizeUsd = totalBought * avgPrice;
      if (sizeUsd <= 0) continue;
      out.push({
        marketId: String(row.slug ?? row.conditionId ?? ""),
        conditionId: row.conditionId ? String(row.conditionId) : undefined,
        marketQuestion: String(row.title ?? "(unknown market)"),
        marketCategory: row.eventSlug ? String(row.eventSlug).split("-")[0] : undefined,
        outcome: String(row.outcome ?? "YES").toUpperCase(),
        side: "BUY",
        price: avgPrice,
        size: sizeUsd,
        timestamp: new Date(), // positions API has no timestamps; scoring doesn't use them
        resolved: true,
        won: (num(row.curPrice) ?? 0) > 0.5 || realizedPnl > 0,
        pnl: realizedPnl,
        raw: row,
      });
    }

    await sleep(DELAY_MS);
    const openUrl = `${DATA_API}/positions?user=${address}&limit=100&sortBy=CURRENT&sortDirection=DESC`;
    const open = (await getJson(openUrl)) as Array<Record<string, unknown>>;
    if (Array.isArray(open)) {
      for (const row of open) {
        const avgPrice = num(row.avgPrice);
        const initialValue = num(row.initialValue);
        if (avgPrice === undefined || initialValue === undefined || initialValue <= 0) continue;
        out.push({
          marketId: String(row.slug ?? row.conditionId ?? ""),
          conditionId: row.conditionId ? String(row.conditionId) : undefined,
          marketQuestion: String(row.title ?? "(unknown market)"),
          marketCategory: row.eventSlug ? String(row.eventSlug).split("-")[0] : undefined,
          outcome: String(row.outcome ?? "YES").toUpperCase(),
          side: "BUY",
          price: avgPrice,
          size: initialValue,
          timestamp: new Date(),
          resolved: false,
          raw: row,
        });
      }
    }

    await this.enrichWithMarketState(out);
    return out;
  }

  /** Raw recent trades from the activity feed — used for new-trade monitoring. */
  private async fetchRecentTrades(address: string, days: number): Promise<WalletActivityTrade[]> {
    const since = Math.floor(Date.now() / 1000) - days * 86400;
    const out: WalletActivityTrade[] = [];
    const pageSize = 500;
    let offset = 0;
    for (let page = 0; page < 4; page++) {
      const url = `${DATA_API}/activity?user=${address}&type=TRADE&limit=${pageSize}&offset=${offset}&start=${since}`;
      const data = (await getJson(url)) as Array<Record<string, unknown>>;
      if (!Array.isArray(data)) {
        throw new AdapterError(url, null, `unexpected activity shape: ${typeof data}`);
      }
      for (const row of data) {
        const ts = num(row.timestamp);
        if (!ts || ts < since) continue;
        const price = num(row.price);
        const usdc = num(row.usdcSize) ?? num(row.size);
        if (price === undefined || usdc === undefined) continue;
        out.push({
          marketId: String(row.slug ?? row.market ?? row.conditionId ?? ""),
          conditionId: row.conditionId ? String(row.conditionId) : undefined,
          marketQuestion: String(row.title ?? row.question ?? "(unknown market)"),
          marketCategory: row.eventSlug ? String(row.eventSlug).split("-")[0] : undefined,
          outcome: String(row.outcome ?? "YES").toUpperCase(),
          side: String(row.side ?? "BUY").toUpperCase() === "SELL" ? "SELL" : "BUY",
          price,
          size: usdc,
          timestamp: new Date(ts * 1000),
          raw: row,
        });
      }
      if (data.length < pageSize) break;
      offset += pageSize;
      await sleep(DELAY_MS);
    }
    return out;
  }

  /**
   * The activity API has no resolution/PnL fields, so wallet scoring would see
   * every trade as unresolved. Enrich by fetching market state (resolution,
   * liquidity, spread) for the most-traded markets, one gamma call per market,
   * capped to keep API load sane.
   */
  private async enrichWithMarketState(trades: WalletActivityTrade[]): Promise<void> {
    const MAX_MARKETS = 15;
    const byMarket = new Map<string, WalletActivityTrade[]>();
    for (const t of trades) {
      if (!t.marketId) continue;
      const list = byMarket.get(t.marketId) ?? [];
      list.push(t);
      byMarket.set(t.marketId, list);
    }
    // Enrich a blend: markets from the OLDEST trades (most likely resolved —
    // needed for win-rate/ROI scoring) plus the highest-exposure markets.
    const entries = [...byMarket.entries()].map(([id, list]) => ({
      id,
      list,
      exposure: list.reduce((a, t) => a + t.size, 0),
      earliest: Math.min(...list.map((t) => t.timestamp.getTime())),
    }));
    const byAge = [...entries].sort((a, b) => a.earliest - b.earliest);
    const byExposure = [...entries].sort((a, b) => b.exposure - a.exposure);
    const chosen = new Map<string, (typeof entries)[number]>();
    for (const e of byAge.slice(0, Math.ceil(MAX_MARKETS * 0.6))) chosen.set(e.id, e);
    for (const e of byExposure) {
      if (chosen.size >= MAX_MARKETS) break;
      chosen.set(e.id, e);
    }
    const ranked = [...chosen.values()];

    for (const { id, list } of ranked) {
      let m: MarketState;
      try {
        m = await this.fetchMarket(id);
      } catch {
        continue; // enrichment is best-effort; scoring treats these as unresolved
      }
      for (const t of list) {
        t.liquidity = m.liquidity;
        t.spread = m.spread;
        // Only infer resolution for trades that don't already carry accurate
        // realized PnL (closed-positions data is authoritative).
        if (t.resolved === undefined && m.resolved && m.winningOutcome) {
          t.resolved = true;
          const effectiveOutcome = t.side === "SELL" ? (t.outcome === "YES" ? "NO" : "YES") : t.outcome;
          t.won = m.winningOutcome === effectiveOutcome;
          // Realized PnL approximation for a $size position at entry price.
          t.pnl = t.price > 0 ? (t.won ? t.size * ((1 - t.price) / t.price) : -t.size) : 0;
        }
      }
      await sleep(DELAY_MS);
    }
  }

  async fetchMarket(marketId: string): Promise<MarketState> {
    // Negative-cache: dead/expired slugs 404 forever — don't refetch each cycle.
    if (PolymarketAdapter.notFound.has(marketId)) {
      throw new AdapterError(marketId, 404, `market not found (cached): ${marketId}`);
    }
    const url = `${GAMMA_API}/markets?slug=${encodeURIComponent(marketId)}`;
    const data = (await getJson(url)) as Array<Record<string, unknown>>;
    if (!Array.isArray(data) || data.length === 0) {
      PolymarketAdapter.notFound.add(marketId);
      throw new AdapterError(url, 404, `market not found: ${marketId}`);
    }
    const m = data[0];
    let yesPrice: number | undefined;
    let noPrice: number | undefined;
    try {
      const prices = JSON.parse(String(m.outcomePrices ?? "[]")) as string[];
      yesPrice = num(prices[0]);
      noPrice = num(prices[1]);
    } catch {
      /* leave undefined */
    }
    const bestBid = num(m.bestBid);
    const bestAsk = num(m.bestAsk);
    const endDate = m.endDate ? new Date(String(m.endDate)) : undefined;
    const ttrHours =
      endDate && !isNaN(endDate.getTime())
        ? Math.max(0, (endDate.getTime() - Date.now()) / 3_600_000)
        : undefined;
    const resolved = m.closed === true || m.umaResolutionStatus === "resolved";
    let winningOutcome: string | undefined;
    if (resolved && yesPrice !== undefined) {
      winningOutcome = yesPrice > 0.5 ? "YES" : "NO";
    }
    return {
      marketId,
      conditionId: m.conditionId ? String(m.conditionId) : undefined,
      question: String(m.question ?? marketId),
      category: m.category ? String(m.category) : undefined,
      yesPrice,
      noPrice,
      bestBid,
      bestAsk,
      spread: bestBid !== undefined && bestAsk !== undefined ? Math.max(0, bestAsk - bestBid) : num(m.spread),
      liquidity: num(m.liquidityNum) ?? num(m.liquidity),
      volume: num(m.volumeNum) ?? num(m.volume),
      timeToResolutionHours: ttrHours,
      resolved,
      winningOutcome,
      raw: m,
    };
  }
}
