/**
 * record:l2 — long-running L2 order-book recorder (v40, Homerun-audit item).
 *
 * Subscribes to Polymarket's CLOB WebSocket for the ACTIVE market universe, snapshots the top-25 book
 * every 5s per asset, and (for markets inside a C-200 dispatch window) appends the raw quote-event
 * stream. Output: append-only JSONL at data/l2/<assetId>.jsonl — the raw material for a future Cox-PH
 * fill-probability model and realistic backtests (homerun fill_simulator concept; AGPL read-only
 * reference).
 *
 *   book line:   {"ts": 1754…, "bids": [["0.55","12.3"], …], "asks": […]}
 *   event line:  {"ts": 1754…, "pc": {"price":"0.55","side":"BUY","size":"12.3","bestBid":"0.54",
 *                                     "bestAsk":"0.56"}}   -> data/l2-events/<assetId>.jsonl
 *   ltp line:    {"ts": 1754…, "ev": "ltp", "price": "0.55"}  (venue's last_trade_price, CHANGES only —
 *                a coarse traded-price marker, NOT a fill tape: see below)
 *
 * THERE IS NO TRADE STREAM on the market channel (verified 2026-09-26 by shape-probing the live feed:
 * it sends only `book` and `price_change`; an earlier version of this script waited for an
 * `{event:"trade"}` message that never arrives, which is why the corpus held zero print lines in
 * 36,042 files). Prints must come from the public trade tape (data-api, see
 * scripts/c200-printthrough.py) or an on-chain OrderFilled ingest. Do not re-add a print branch here
 * on the assumption the venue sends fills.
 *
 * Three coverage mechanisms, in order of what they guarantee:
 *   1. candidate universe — top MAX_MARKETS markets by copy-candidate observed-trade recency,
 *      refreshed every 10 min (unchanged).
 *   2. PINNED markets (v62, A2) — the market of any fresh C-200 fill intent is pinned immediately
 *      (polled every PIN_POLL_MS over a short dispatch lookback) and held for PIN_TTL_MS, so coverage
 *      starts ≤ ~20s after a dispatch instead of 2.7-8.6 min and spans the measurement window. This is
 *      what makes the 5-minute print-through horizon measurable at all.
 *   3. quote-event stream — for PINNED markets only, every raw price_change (carrying best_bid and
 *      best_ask) is appended, so a level touch between 5s snapshots is still observable.
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
const L2_EVENTS = join(__dirname, "..", "data", "l2-events");
// assetId -> marketId map. The L2 corpus is one file per CLOB asset id, and the DB does NOT
// carry token ids (ObservedTrade.rawTradeJson is empty for all 283k rows), so without this map
// every analysis has to re-resolve each file through Gamma (~300ms each). Append-only, one line
// per market, written when the token list is first resolved. Takes effect on the next recorder
// restart (the watchdog only restarts on death, so the running process keeps the old code).
const ASSET_MAP = join(__dirname, "..", "data", "l2-asset-map.jsonl");
const SNAPSHOT_MS = 5_000;
const UNIVERSE_REFRESH_MS = 10 * 60_000;
const MAX_MARKETS = 25;
const TOP_N = 25;
// Pinning (A2): how often to look for fresh dispatches, how far back a dispatch still counts, and how
// long a pinned market stays subscribed. Env overrides exist so the mechanism can be proven against
// historical dispatches without waiting for a live one.
const PIN_POLL_MS = Number(process.env.L2_PIN_POLL_MS ?? 20_000);
const PIN_LOOKBACK_MS = Number(process.env.L2_PIN_LOOKBACK_MS ?? 10 * 60_000);
const PIN_TTL_MS = Number(process.env.L2_PIN_TTL_MS ?? 2 * 3_600_000);

mkdirSync(L2_DIR, { recursive: true });
mkdirSync(L2_EVENTS, { recursive: true });

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

/** Record which market a L2 asset file belongs to (see ASSET_MAP note above). */
function appendAssetMap(marketId: string, assetIds: string[]) {
  try {
    appendFileSync(ASSET_MAP, JSON.stringify({ ts: Date.now(), marketId, assetIds }) + "\n");
  } catch (e) {
    console.error(`[l2] asset-map append failed ${marketId}: ${e instanceof Error ? e.message : e}`);
  }
}

/** Quote-event tape, PINNED markets only (see header). One file per asset, same ts convention. */
function appendEvent(assetId: string, line: unknown) {
  try {
    appendFileSync(join(L2_EVENTS, `${assetId}.jsonl`), JSON.stringify(line) + "\n");
  } catch (e) {
    console.error(`[l2] event append failed ${assetId}: ${e instanceof Error ? e.message : e}`);
  }
}

// --- Pinned markets (A2): confidence that we were recording when a C-200 copy happened ------------
// marketId -> {assetIds, expiresAt}. Kept OUTSIDE the candidate universe so a 10-min refresh can
// neither drop a market mid-measurement nor be the reason coverage starts late.
const pinned = new Map<string, { assetIds: string[]; expiresAt: number }>();
const lastLtp = new Map<string, string>(); // assetId -> last stored last_trade_price
let lastPinPollAt = 0;
let pinCount = 0; // cumulative pins this process lifetime (observability for the poll path)

/** Pin every market with a C-200 fill intent dispatched in the lookback window. Never throws: a DB
 *  failure downgrades to "no new pins this tick", which is exactly the pre-v62 behaviour. */
async function pollDispatches(): Promise<number> {
  let added = 0;
  lastPinPollAt = Date.now();
  try {
    const since = new Date(Date.now() - PIN_LOOKBACK_MS);
    const rows = await prisma.fillIntent.findMany({
      where: { dispatchedAt: { gte: since } },
      select: { marketId: true, dispatchedAt: true },
      distinct: ["marketId"],
      orderBy: { dispatchedAt: "desc" },
    });
    for (const r of rows) {
      const expiresAt = new Date(r.dispatchedAt).getTime() + PIN_TTL_MS;
      if (expiresAt <= Date.now()) continue;                 // its measurement window is over
      const existing = pinned.get(r.marketId);
      if (existing && existing.expiresAt >= expiresAt) continue;
      const assetIds = await gammaTokenIds(r.marketId);
      if (!assetIds || assetIds.length === 0) {
        console.warn(`[l2] pin deferred (no tokens yet) ${r.marketId}`);
        continue;
      }
      pinned.set(r.marketId, { assetIds, expiresAt });
      added += 1;
      pinCount += 1;
      console.log(`[l2] pinned ${r.marketId} until ${new Date(expiresAt).toISOString()} (C-200 dispatch)`);
    }
  } catch (e) {
    console.error(`[l2] dispatch poll failed (kept existing pins): ${e instanceof Error ? e.message : e}`);
  }
  if (added > 0) void rebuildUniverse();
  return added;
}

function expirePins(): number {
  const now = Date.now();
  let dropped = 0;
  for (const [marketId, p] of pinned) {
    if (p.expiresAt <= now) {
      pinned.delete(marketId);
      dropped += 1;
      console.log(`[l2] unpinned ${marketId} (measurement window ended)`);
    }
  }
  return dropped;
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
    if (ids.length > 0) {
      tokenCache.set(marketId, ids);
      appendAssetMap(marketId, ids);
    }
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
    // v61: keep the L2 watch list on copy-candidate markets; observation-only
    // rows would push real candidates out of the MAX_MARKETS subscription.
    where: { timestamp: { gte: new Date(Date.now() - 2 * 3_600_000) }, observationOnly: false },
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
let candidates = new Map<string, string[]>(); // marketId -> asset ids (the 10-min candidate refresh)

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
      // Object-form book message (event_type "book"): the venue re-sends the whole ladder on
      // subscribe and periodically after. The array form above does not cover it, so without this
      // branch the in-memory book drifts from the venue's on any missed price_change.
      if (msg.event_type === "book" && msg.asset_id) {
        applySnapshot(msg.asset_id, msg.bids ?? [], msg.asks ?? []);
        if (pinned.has(marketId) && msg.last_trade_price && lastLtp.get(msg.asset_id) !== String(msg.last_trade_price)) {
          lastLtp.set(msg.asset_id, String(msg.last_trade_price));
          appendEvent(msg.asset_id, { ts: Date.now(), ev: "ltp", price: msg.last_trade_price });
        }
        return;
      }
      if (Array.isArray(msg?.price_changes)) {
        applyPriceChanges(msg.price_changes);
        // Quote-event tape for PINNED markets only: a level touch between two 5s snapshots is
        // invisible in data/l2, and this is the window the C-200 measurement depends on.
        if (pinned.has(marketId)) {
          const ts = Date.now();
          for (const c of msg.price_changes) {
            if (!c?.asset_id) continue;
            appendEvent(c.asset_id, {
              ts,
              pc: { price: c.price, side: c.side, size: c.size, bestBid: c.best_bid, bestAsk: c.best_ask },
            });
          }
        }
        return;
      }
      // NOTE: no trade branch. The market channel has no fill stream (verified 2026-09-26): a
      // `{event:"trade"}` handler sat here for weeks and never fired once. Prints come from the public
      // trade tape — see scripts/c200-printthrough.py.
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
  candidates = next;
  return rebuildUniverse();
}

/** universe = candidate markets ∪ pinned dispatch markets. Rebuilt from both sources so a 10-min
 *  candidate refresh can never drop a market we are mid-measurement on. */
function rebuildUniverse(): Map<string, string[]> {
  expirePins();
  const merged = new Map<string, string[]>(candidates);
  for (const [marketId, p] of pinned) {
    if (p.assetIds.length > 0) merged.set(marketId, p.assetIds);
  }
  universe = merged;
  // Prune books for assets we no longer track.
  const live = new Set([...merged.values()].flat());
  for (const assetId of [...books.keys()]) if (!live.has(assetId)) books.delete(assetId);
  console.log(
    `[l2] universe: ${merged.size} markets, ${[...merged.values()].flat().length} assets ` +
      `(${candidates.size} candidates + ${pinned.size} pinned)`
  );
  reconcileConnections();
  return merged;
}

async function main() {
  console.log(`[l2] recorder starting (${new Date().toISOString()}) — dir ${L2_DIR}`);
  // Seed pins BEFORE the first universe build, so a restart mid-measurement keeps covering the
  // dispatch windows that are still open (PIN_TTL_MS decides which those are).
  await pollDispatches();
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

  // A2: the dispatch poll. Cheap (a few rows off an indexed table), never throws, and it is the only
  // reason coverage can start within ~20s of a C-200 copy instead of at the next 10-min refresh.
  setInterval(() => {
    void pollDispatches();
  }, PIN_POLL_MS);

  // Diagnostic heartbeat (keep: cheap, proves data is flowing). Also surfaces the A2 poll path:
  // `pinned`/`pins`/`lastPoll` make a silent poll loop and a stale one distinguishable.
  setInterval(() => {
    const age = lastMsgAt ? Math.round((Date.now() - lastMsgAt) / 1000) : -1;
    const open = [...connections.values()].filter((s) => s.readyState === WebSocket.OPEN).length;
    const pollAge = lastPinPollAt ? Math.round((Date.now() - lastPinPollAt) / 1000) : -1;
    console.log(
      `[l2] heartbeat conns=${connections.size} open=${open} books=${books.size} lastMsg=${age}s ago ` +
        `pinned=${pinned.size} pins=${pinCount} lastPoll=${pollAge}s ago`
    );
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
