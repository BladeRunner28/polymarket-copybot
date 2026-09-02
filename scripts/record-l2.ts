/**
 * record:l2 — long-running L2 order-book recorder (v40, Homerun-audit item).
 *
 * Subscribes to Polymarket's CLOB WebSocket for the ACTIVE market universe
 * (open paper trades + recently observed trades), snapshots the top-25 book
 * every 5s per asset, and appends trades as they print. Output: append-only
 * JSONL at data/l2/<assetId>.jsonl — the raw material for a future Cox-PH
 * fill-probability model and realistic backtests (homerun fill_simulator
 * concept; AGPL read-only reference).
 *
 *   book line:   {"ts": 1754…, "bids": [["0.55","12.3"], …], "asks": […]}
 *   trade line:  {"ts": 1754…, "t": {"price": "0.55", "size": "123", "side": "1"}}
 *
 * Universe refreshes every 10 min (gamma-api, cached clobTokenIds, throttled).
 * Supervised by the cron watchdog copybot-l2-watchdog.sh (pgrep + nohup).
 */

import { appendFileSync, mkdirSync } from "fs";
import { join } from "path";
import { prisma } from "../src/lib/db";

const WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market";
const GAMMA = "https://gamma-api.polymarket.com/markets"; // NOTE: no trailing slash — /markets?slug= 404s with one
const L2_DIR = join(__dirname, "..", "data", "l2");
const SNAPSHOT_MS = 5_000;
const UNIVERSE_REFRESH_MS = 10 * 60_000;
const MAX_MARKETS = 25;
const TOP_N = 25;

mkdirSync(L2_DIR, { recursive: true });

interface BookState {
  bids: Map<string, number>; // price -> size
  asks: Map<string, number>;
}

const books = new Map<string, BookState>(); // assetId -> book
const tokenCache = new Map<string, string[]>(); // marketId -> [yes, no] asset ids
let ws: WebSocket | null = null;
let lastSnapshot = 0;
let lastMsgAt = 0;
let msgCount = 0;
let reconnectDelay = 2000;

function append(assetId: string, line: unknown) {
  try {
    appendFileSync(join(L2_DIR, `${assetId}.jsonl`), JSON.stringify(line) + "\n");
  } catch (e) {
    console.error(`[l2] append failed ${assetId}: ${e instanceof Error ? e.message : e}`);
  }
}

function snapshot(now: number) {
  for (const [assetId, book] of books) {
    const bids = [...book.bids.entries()]
      .sort((a, b) => parseFloat(b[0]) - parseFloat(a[0]))
      .slice(0, TOP_N);
    const asks = [...book.asks.entries()]
      .sort((a, b) => parseFloat(a[0]) - parseFloat(b[0]))
      .slice(0, TOP_N);
    append(assetId, { ts: now, bids, asks });
  }
}

function applySnapshot(assetId: string, bids: Array<{ price: string; size: string }>, asks: Array<{ price: string; size: string }>) {
  const book: BookState = { bids: new Map(), asks: new Map() };
  for (const b of bids ?? []) book.bids.set(b.price, parseFloat(b.size));
  for (const a of asks ?? []) book.asks.set(a.price, parseFloat(a.size));
  books.set(assetId, book);
}

function applyPriceChanges(changes: Array<{ asset_id: string; price: string; size: string; side?: string }>) {
  for (const c of changes) {
    const s = parseFloat(c.size);
    const side = (c.side ?? "").toUpperCase();
    const map = side === "BUY" ? "bids" : side === "SELL" ? "asks" : null;
    if (!map) continue;
    let book = books.get(c.asset_id);
    if (!book) {
      book = { bids: new Map(), asks: new Map() };
      books.set(c.asset_id, book);
    }
    if (s <= 0) book[map].delete(c.price);
    else book[map].set(c.price, s);
  }
}

/** Gamma returns clobTokenIds as a comma-string, a JSON-array-string, or an
 *  array — normalize all three. (split(',') on the JSON-array-string form
 *  yields ids with quotes/brackets, which the CLOB WS silently rejects.) */
function parseTokenIds(raw: unknown): string[] {
  if (!raw) return [];
  if (Array.isArray(raw)) return raw.filter((x): x is string => typeof x === "string" && x.length > 0);
  const s = String(raw).trim();
  if (s.startsWith("[")) {
    try {
      const arr = JSON.parse(s);
      return Array.isArray(arr) ? arr.filter((x): x is string => typeof x === "string" && x.length > 0) : [];
    } catch {
      return [];
    }
  }
  return s.split(",").map((x) => x.trim()).filter(Boolean);
}

async function gammaTokenIds(marketId: string): Promise<string[] | null> {
  const cached = tokenCache.get(marketId);
  if (cached) return cached;
  try {
    // marketId is a slug in the copybot DB — Gamma's /markets?slug= form.
    const res = await fetch(`${GAMMA}?slug=${encodeURIComponent(marketId)}`, {
      signal: AbortSignal.timeout(10_000),
    });
    if (!res.ok) return null;
    const j = (await res.json()) as Array<{ clobTokenIds?: unknown }>;
    const ids = parseTokenIds(j?.[0]?.clobTokenIds);
    if (ids.length > 0) tokenCache.set(marketId, ids);
    await new Promise((r) => setTimeout(r, 300)); // gamma rate-limit courtesy
    return ids.length > 0 ? ids : null;
  } catch {
    return null;
  }
}

async function activeMarketIds(): Promise<string[]> {
  // Only markets with observed trade activity in the last 2h — live by
  // definition. Open paper positions include stale/resolved markets whose
  // tokens are dead on the CLOB WS (gamma returns them, the WS returns []).
  const recent = await prisma.observedTrade.findMany({
    where: { timestamp: { gte: new Date(Date.now() - 2 * 3_600_000) } },
    select: { marketId: true },
    distinct: ["marketId"],
    orderBy: { timestamp: "desc" },
    take: MAX_MARKETS,
  });
  return recent.map((m) => m.marketId);
}

// --- Connection management ---
// The CLOB server accepts exactly ONE subscription per connection (a second
// subscribe returns "INVALID OPERATION"), and rejects a whole batch if any
// asset id is stale. So: one connection per market, subscribed once with that
// market's tokens. Stale markets get an empty snapshot (harmless) and can't
// poison anything else. Reconnects are scheduled per market with backoff.

const connections = new Map<string, WebSocket>(); // marketId -> ws
const retryAt = new Map<string, number>(); // marketId -> retry-after epoch ms
let universe = new Map<string, string[]>(); // marketId -> asset ids

function openConnection(marketId: string, assetIds: string[]) {
  if (connections.has(marketId)) return;
  const sock = new WebSocket(WS_URL);
  connections.set(marketId, sock);
  sock.onopen = () => {
    sock.send(JSON.stringify({ assets_ids: assetIds, type: "market" }));
    // Keepalive: server can go silent on idle connections (PING -> PONG).
    const ping = setInterval(() => {
      if (sock.readyState === WebSocket.OPEN) sock.send("PING");
    }, 10_000);
    sock.addEventListener("close", () => clearInterval(ping), { once: true });
  };
  sock.onmessage = (ev) => {
    try {
      lastMsgAt = Date.now();
      const raw = String(ev.data);
      if (raw === "PONG") return; // keepalive reply, not a data message
      const msg = JSON.parse(raw);
      // Full book snapshot: array of {asset_id, bids:[{price,size}], asks:[...]}
      if (Array.isArray(msg)) {
        for (const m of msg) {
          if (m?.asset_id) applySnapshot(m.asset_id, m.bids ?? [], m.asks ?? []);
        }
        return;
      }
      if (Array.isArray(msg?.price_changes)) {
        applyPriceChanges(msg.price_changes);
        return;
      }
      if (msg.event === "trade" && Array.isArray(msg.trades)) {
        for (const t of msg.trades) {
          append(msg.asset_id, { ts: Date.now(), t: { price: t.price, size: t.size, side: t.side } });
        }
      }
    } catch (e) {
      console.error(`[l2] message error: ${e instanceof Error ? e.message : e}`);
    }
  };
  sock.onclose = () => {
    connections.delete(marketId);
    const delay = 30_000;
    retryAt.set(marketId, Date.now() + delay);
    console.warn(`[l2] closed ${marketId} — retry in ${delay / 1000}s`);
    setTimeout(() => reconcileConnections(), delay + 1000);
  };
  sock.onerror = () => {
    /* onclose always follows */
  };
}

function reconcileConnections() {
  const now = Date.now();
  for (const [marketId, sock] of connections) {
    if (!universe.has(marketId)) {
      sock.close();
      connections.delete(marketId);
    }
  }
  for (const [marketId, assetIds] of universe) {
    if ((retryAt.get(marketId) ?? 0) > now) continue;
    openConnection(marketId, assetIds);
  }
}

async function refreshUniverse() {
  const marketIds = await activeMarketIds();
  const next = new Map<string, string[]>();
  for (const m of marketIds) {
    const ids = await gammaTokenIds(m);
    if (ids && ids.length > 0) next.set(m, ids);
  }
  universe = next;
  // Prune books for assets we no longer track.
  const live = new Set([...next.values()].flat());
  for (const assetId of [...books.keys()]) if (!live.has(assetId)) books.delete(assetId);
  console.log(`[l2] universe: ${next.size} markets, ${[...next.values()].flat().length} assets`);
  reconcileConnections();
  return next;
}

async function main() {
  console.log(`[l2] recorder starting (${new Date().toISOString()}) — dir ${L2_DIR}`);
  const initial = await refreshUniverse();
  if (initial.size === 0) {
    console.warn("[l2] empty universe on start; will retry in 10m");
  }

  setInterval(() => {
    const now = Date.now();
    if (now - lastSnapshot >= SNAPSHOT_MS) {
      lastSnapshot = now;
      snapshot(now);
    }
  }, 1000);

  setInterval(() => {
    void refreshUniverse();
  }, UNIVERSE_REFRESH_MS);

  // Diagnostic heartbeat (keep: cheap, proves data is flowing).
  setInterval(() => {
    const age = lastMsgAt ? Math.round((Date.now() - lastMsgAt) / 1000) : -1;
    const open = [...connections.values()].filter((s) => s.readyState === WebSocket.OPEN).length;
    console.log(`[l2] heartbeat conns=${connections.size} open=${open} books=${books.size} lastMsg=${age}s ago`);
  }, 15_000);

  const shutdown = () => {
    console.log("[l2] shutting down");
    for (const sock of connections.values()) sock.close();
    connections.clear();
    prisma.$disconnect();
    process.exit(0);
  };
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
}

main().catch((e) => {
  console.error("[l2] fatal:", e);
  process.exit(1);
});
