/**
 * standard-fill-stamp — the STANDARD lane's FILL BOOTH (card `t_7560e0d0`).
 *
 * MEASUREMENT ONLY. Reads the booked legs, stamps each one with the entry that was
 * actually ATTAINABLE in the evidence we hold, and prints the DISTRIBUTION of
 * (attainable − decision price) in cents per decision-lag bucket. Writes no DB row,
 * no RuleSet, no booked figure; nothing in the trade path imports it.
 *
 * THE QUESTION (from the profit-recs 2026-10-29 #1 pricing): STANDARD books
 * `entryPrice = currentPrice` with p(fill) = 1 and no fill model at all. If a cent
 * were attainable, it is worth +$1,439.33 on 90 days' settled notional — 62% of the
 * lane's realised profit. The card's pre-registered rule: ship a booking change
 * only once stamps exist on >= 300 legs, and the claim is REFUTED if the stamp lands
 * within ±0.3c of the mid on >= 300 legs. This script is what decides that.
 *
 * EVIDENCE, IN PRECEDENCE ORDER, COVERAGE REPORTED SEPARATELY FOR EACH
 *  S1 BOOK  data/l2/<assetId>.jsonl — our own top-25 ladder at 5s cadence. For each
 *           lag bucket the attainable price is the LOWEST best-ask in the window, and
 *           the mid beside it is the attaining snapshot's own (bid+ask)/2.
 *  S2 TAPE  venue prints, data-api `/v2/trades?condition=…&taker_only=false`, cached
 *           under data/c200-tape/. A print is a trade that HAPPENED, not a quote we
 *           could have hit, and it carries no mid — so it can extend coverage and
 *           supply a price-vs-decision reading, and it can never feed the ±0.3c-of-mid
 *           test. Fetched only for legs the book could not stamp (precedence), and only
 *           up to `--tape-max` markets, because this is a bounded run, not a crawler.
 *
 * THE READING THAT MUST TRAVEL (see src/lib/standard-fill-stamp.ts): a best ask at or
 * below a price is REACHABILITY — no queue position, no size — and a min-ask over a
 * window is an optimistic bound with hindsight. The 0-10s row is the no-patience,
 * no-hindsight read; report that one when quoting a taker cost.
 *
 * Usage
 *   npx tsx scripts/standard-fill-stamp.ts                     # book arm + a capped tape arm
 *   npx tsx scripts/standard-fill-stamp.ts --json              # quiet, artifact only
 *   npx tsx scripts/standard-fill-stamp.ts --book-only         # no network at all
 *   npx tsx scripts/standard-fill-stamp.ts --md drafts/x.md    # also write a dashboard draft
 * Flags: --db <path> --l2-dir <dir> --asset-map <path> --tape-cache <dir> --tape-max <n>
 *        --since-ms <ms> --horizon-ms <ms> --out <jsonl>
 *
 * The DB (prisma/dev.db) is 12 GB: every read here goes through the `sqlite3
 * -readonly` CLI. It is never copied, opened for write, or scanned without a WHERE.
 */
import { execFile, execFileSync } from "child_process";
import fs from "fs";
import path from "path";
import { promisify } from "util";
import {
  STAMP_LAG_BUCKETS,
  WIDEST_BUCKET,
  type StampLeg,
  type StampObservation,
  type StampSummary,
  type RefutationVerdict,
  evaluateRefutation,
  reachability,
  renderStamp,
  summariseStamps,
} from "../src/lib/standard-fill-stamp";

const execFileAsync = promisify(execFile);

const ROOT = path.resolve(__dirname, "..");
const HORIZON_MS = STAMP_LAG_BUCKETS[STAMP_LAG_BUCKETS.length - 1].maxMs;
/** How far BEFORE the decision a quote may sit and still describe the decision price. */
const PRE_QUOTE_GRACE_MS = 60_000;
/** A market's two outcome tokens closer than this to the decision price are ambiguous. */
const TOKEN_AMBIGUITY_USD = 0.02;
/**
 * How far the tape's own last pre-decision print may sit from the booked price before a
 * PROXIMITY token pick is refused. Above this the "nearest" token is plausibly the market's
 * OTHER outcome and the stamp would be identification error, not a measurement.
 */
const TAPE_TOKEN_PROXIMITY_USD = 0.05;

interface Args {
  db: string;
  l2Dir: string;
  assetMap: string;
  tapeCache: string;
  tapeMax: number;
  sinceMs: number | null;
  horizonMs: number;
  out: string;
  md: string | null;
  json: boolean;
  bookOnly: boolean;
}

function parseArgs(argv: string[]): Args {
  const val = (flag: string, dflt: string): string => {
    const i = argv.indexOf(flag);
    return i >= 0 && argv[i + 1] ? argv[i + 1] : dflt;
  };
  const num = (flag: string, dflt: number): number => {
    const i = argv.indexOf(flag);
    if (i < 0 || !argv[i + 1]) return dflt;
    const n = Number(argv[i + 1]);
    return Number.isFinite(n) ? n : dflt;
  };
  return {
    db: path.resolve(val("--db", path.join(ROOT, "prisma", "dev.db"))),
    l2Dir: path.resolve(val("--l2-dir", path.join(ROOT, "data", "l2"))),
    assetMap: path.resolve(val("--asset-map", path.join(ROOT, "data", "l2-asset-map.jsonl"))),
    tapeCache: path.resolve(val("--tape-cache", path.join(ROOT, "data", "c200-tape"))),
    tapeMax: num("--tape-max", 120),
    sinceMs: argv.includes("--since-ms") ? num("--since-ms", 0) : null,
    horizonMs: num("--horizon-ms", HORIZON_MS),
    out: path.resolve(val("--out", path.join(ROOT, "data", "standard-fill-stamp.jsonl"))),
    md: argv.includes("--md") ? path.resolve(val("--md", "")) : null,
    json: argv.includes("--json"),
    bookOnly: argv.includes("--book-only"),
  };
}

// --------------------------------------------------------------------- read-only DB
interface DbLeg {
  id: string;
  marketId: string;
  outcome: string;
  decisionPrice: number;
  sizeUsd: number;
  openedAt: number;
  status: string;
}

function sqliteJson<T>(db: string, sql: string): T[] {
  // -readonly + a file: URI: the 12 GB live DB is never opened for write and never copied.
  const out = execFileSync("sqlite3", ["-readonly", `file:${db}?mode=ro`, "-json", sql], {
    encoding: "utf8",
    maxBuffer: 512 * 1024 * 1024,
  });
  const t = out.trim();
  return t ? (JSON.parse(t) as T[]) : [];
}

function loadLegs(args: Args): DbLeg[] {
  const where = [`botId='STANDARD'`, `isDemo=0`];
  if (args.sinceMs !== null) where.push(`openedAt >= ${Math.floor(args.sinceMs)}`);
  const rows = sqliteJson<DbLeg>(
    args.db,
    `SELECT id, marketId, outcome, entryPrice AS decisionPrice, simulatedPositionSize AS sizeUsd,
            openedAt, status
     FROM PaperTrade WHERE ${where.join(" AND ")} ORDER BY openedAt`
  );
  return rows.map((r) => ({ ...r, decisionPrice: Number(r.decisionPrice), sizeUsd: Number(r.sizeUsd), openedAt: Number(r.openedAt) }));
}

function conditionMap(db: string, marketIds: string[]): Map<string, string> {
  const m = new Map<string, string>();
  const CHUNK = 400;
  for (let i = 0; i < marketIds.length; i += CHUNK) {
    const ids = marketIds.slice(i, i + CHUNK).map((x) => `'${x.replace(/'/g, "''")}'`).join(",");
    const rows = sqliteJson<{ marketId: string; conditionId: string }>(
      db,
      `SELECT DISTINCT marketId, conditionId FROM ObservedTrade
       WHERE conditionId IS NOT NULL AND marketId IN (${ids})`
    );
    for (const r of rows) m.set(r.marketId, r.conditionId);
  }
  return m;
}

// --------------------------------------------------------------------- asset map
function readAssetMap(file: string): Map<string, string[]> {
  const m = new Map<string, string[]>();
  if (!fs.existsSync(file)) return m;
  for (const line of fs.readFileSync(file, "utf8").split("\n")) {
    const t = line.trim();
    if (!t) continue;
    try {
      const o = JSON.parse(t) as { marketId?: string; assetIds?: string[] };
      if (o.marketId && Array.isArray(o.assetIds)) m.set(o.marketId, o.assetIds);
    } catch {
      /* a torn line is not a mapping */
    }
  }
  return m;
}

/**
 * Earliest snapshot timestamp in the corpus — the era its coverage can speak to. Read from
 * EVERY file (not a sample) so the population boundary is the same on every run: a sampled
 * minimum moves by minutes between runs and silently shifts the leg population.
 */
function corpusEpochMs(l2Dir: string): number | null {
  if (!fs.existsSync(l2Dir)) return null;
  const names = fs.readdirSync(l2Dir).filter((n) => n.endsWith(".jsonl"));
  if (names.length === 0) return null;
  let epoch: number | null = null;
  const buf = Buffer.alloc(512);
  for (const name of names) {
    const p = path.join(l2Dir, name);
    let head: string;
    try {
      const fd = fs.openSync(p, "r");
      const n = fs.readSync(fd, buf, 0, buf.length, 0);
      fs.closeSync(fd);
      head = buf.subarray(0, n).toString("utf8").split("\n")[0];
    } catch {
      continue;
    }
    try {
      const o = JSON.parse(head) as { ts?: number };
      if (typeof o.ts === "number" && (epoch === null || o.ts < epoch)) epoch = o.ts;
    } catch {
      /* skip */
    }
  }
  return epoch;
}

// --------------------------------------------------------------------- S1: our book
interface Snap {
  ts: number;
  ask: number;
  bid: number;
}

/** One bounded pass over one asset file: quotes in [t0 − grace, t0 + horizon]. */
function readSnaps(file: string, t0: number, horizonMs: number): Snap[] {
  let text: string;
  try {
    text = fs.readFileSync(file, "utf8");
  } catch {
    return [];
  }
  const out: Snap[] = [];
  const lo = t0 - PRE_QUOTE_GRACE_MS;
  const hi = t0 + horizonMs;
  for (const line of text.split("\n")) {
    if (!line) continue;
    let o: { ts?: number; asks?: Array<[string, number]>; bids?: Array<[string, number]>; ev?: string };
    try {
      o = JSON.parse(line) as typeof o;
    } catch {
      continue;
    }
    if (o.ev || typeof o.ts !== "number" || !o.asks || !o.bids || o.asks.length === 0 || o.bids.length === 0) continue;
    if (o.ts < lo) continue;
    if (o.ts > hi) break; // append-only file: timestamps are monotone
    out.push({ ts: o.ts, ask: Number(o.asks[0][0]), bid: Number(o.bids[0][0]) });
  }
  return out;
}

interface BookStamp {
  evidence: NonNullable<StampLeg["book"]>;
  /** Mid at the quote nearest the decision — used to choose the outcome token. */
  basisMid: number;
  assetId: string;
}

function stampBook(l2Dir: string, assets: string[], decisionPrice: number, t0: number, horizonMs: number): BookStamp | null {
  const perAsset: Array<{ asset: string; snaps: Snap[]; post: Snap[]; basis: Snap | null }> = [];
  for (const a of assets) {
    const file = path.join(l2Dir, `${a}.jsonl`);
    if (!fs.existsSync(file)) continue;
    const snaps = readSnaps(file, t0, horizonMs);
    if (snaps.length === 0) continue;
    const post = snaps.filter((s) => s.ts >= t0);
    if (post.length === 0) continue;
    const pre = snaps.filter((s) => s.ts <= t0);
    const basis = pre.length ? pre[pre.length - 1] : post[0];
    perAsset.push({ asset: a, snaps, post, basis });
  }
  if (perAsset.length === 0) return null;
  // Our outcome's token: the one whose quote near the decision is closest to the booked
  // price. The two tokens are near-complements, so a |Δmid| under 2c is a coin flip and
  // is flagged rather than hidden (see TOKEN_AMBIGUITY_USD).
  const scored = perAsset
    .map((x) => ({ ...x, dist: x.basis ? Math.abs((x.basis.ask + x.basis.bid) / 2 - decisionPrice) : Infinity }))
    .sort((x, y) => x.dist - y.dist);
  const chosen = scored[0];
  const runnerUp = scored[1];
  const ambiguous = runnerUp !== undefined && Math.abs(runnerUp.dist - chosen.dist) < TOKEN_AMBIGUITY_USD && chosen.dist > 0;
  const first = chosen.post[0];
  const byBucket: Record<string, StampObservation | null> = {};
  for (const b of STAMP_LAG_BUCKETS) {
    const win = chosen.post.filter((s) => s.ts <= t0 + Math.min(b.maxMs, horizonMs));
    if (win.length === 0) {
      byBucket[b.label] = null;
      continue;
    }
    let best = win[0];
    for (const s of win) if (s.ask < best.ask) best = s;
    byBucket[b.label] = { price: best.ask, mid: (best.ask + best.bid) / 2 };
  }
  return {
    assetId: chosen.asset,
    basisMid: chosen.basis ? (chosen.basis.ask + chosen.basis.bid) / 2 : first.ask,
    evidence: {
      coverLagMs: first.ts - t0,
      tokenAmbiguous: ambiguous,
      firstAsk: first.ask,
      firstBid: first.bid,
      byBucket,
    },
  };
}

// --------------------------------------------------------------------- S2: venue prints
interface TapeRow {
  token_id?: string;
  price: number | string;
  size?: number | string;
  timestamp: number;
}

const V2_TO_V1: Record<string, string> = {
  token_id: "asset",
  condition_id: "conditionId",
  transaction_hash: "transactionHash",
  proxy_wallet: "proxyWallet",
};

/** Public trade tape, keyless, newest-first, cursor-paged. Cached by conditionId. */
async function fetchTape(conditionId: string, cacheDir: string, maxPages = 4): Promise<TapeRow[]> {
  fs.mkdirSync(cacheDir, { recursive: true });
  const cache = path.join(cacheDir, `${conditionId}.json`);
  if (fs.existsSync(cache)) {
    try {
      return JSON.parse(fs.readFileSync(cache, "utf8")) as TapeRow[];
    } catch {
      /* a torn cache is refetched */
    }
  }
  const rows: TapeRow[] = [];
  let cursor: string | null = null;
  for (let page = 0; page < maxPages; page++) {
    const url =
      `https://data-api.polymarket.com/v2/trades?condition=${encodeURIComponent(conditionId)}` +
      `&limit=500&taker_only=false` +
      (cursor ? `&cursor=${encodeURIComponent(cursor)}` : "");
    let payload: { data?: TapeRow[]; pagination?: { next_cursor?: string } } = {};
    try {
      const { stdout } = await execFileAsync("curl", ["-s", "--max-time", "30", url], {
        maxBuffer: 64 * 1024 * 1024,
      });
      payload = stdout.trim() ? (JSON.parse(stdout) as typeof payload) : {};
    } catch {
      break;
    }
    const chunk = payload.data ?? [];
    for (const r of chunk) {
      const o = r as unknown as Record<string, unknown>;
      for (const [k2, k1] of Object.entries(V2_TO_V1)) if (o[k1] === undefined && o[k2] !== undefined) o[k1] = o[k2];
      rows.push(r);
    }
    cursor = payload.pagination?.next_cursor ?? null;
    if (!cursor || chunk.length === 0) break;
  }
  if (rows.length) {
    try {
      fs.writeFileSync(cache, JSON.stringify(rows));
    } catch {
      /* cache is an optimisation only */
    }
  }
  return rows;
}

function stampTape(
  tape: TapeRow[],
  assetIds: string[],
  decisionPrice: number,
  t0: number,
  horizonMs: number
): {
  tape: StampLeg["tape"];
  resolvedBy: "map" | "proximity" | null;
  rowsForMarket: number;
  rowsInWindow: number;
  tokenGapUsd: number | null;
} {
  const ours = new Set(assetIds);
  const all = tape
    .map((r) => {
      const tok = (r as unknown as { asset?: string }).asset;
      return { token: tok, price: Number(r.price), ts: Number(r.timestamp) };
    })
    .filter((r) => r.token !== undefined && Number.isFinite(r.price) && Number.isFinite(r.ts))
    .map((r) => ({ token: r.token as string, price: r.price, ts: r.ts * 1000 }))
    // The venue tape is NEWEST-FIRST. Every "latest print before the decision" below assumes
    // ascending order — without this sort the pick reads the market's OLDEST print and lands
    // on the wrong outcome token (observed: +57.5c stamps that were pure identification error).
    .sort((a, b) => a.ts - b.ts);
  if (all.length === 0) return { tape: null, resolvedBy: null, rowsForMarket: 0, rowsInWindow: 0, tokenGapUsd: null };
  // Precedence: our own asset map when it knows this market (the token is then known, not
  // guessed). Only when the map has no entry do we fall back to the tape itself — the
  // house's own `pick_token` technique: of the market's tokens, ours is the one whose last
  // print BEFORE the decision is closest to the price we booked.
  const byMap = assetIds.length > 0;
  const rows = byMap ? all.filter((r) => ours.has(r.token)) : all;
  if (rows.length === 0) return { tape: null, resolvedBy: null, rowsForMarket: all.length, rowsInWindow: 0, tokenGapUsd: null };
  const inWindow = rows.filter((r) => r.ts >= t0 && r.ts <= t0 + horizonMs);
  let token: string | null = null;
  let bestD = Infinity;
  for (const tok of new Set(rows.map((r) => r.token))) {
    const pre = rows.filter((r) => r.token === tok && r.ts <= t0);
    if (pre.length === 0) continue;
    const d = Math.abs(pre[pre.length - 1].price - decisionPrice);
    if (d < bestD) {
      bestD = d;
      token = tok;
    }
  }
  if (token === null) {
    return { tape: null, resolvedBy: null, rowsForMarket: all.length, rowsInWindow: inWindow.length, tokenGapUsd: null };
  }
  // A proximity pick is only trusted when the token's own last pre-decision print is
  // CLOSE to the price we booked. Without this floor the pick can land on the market's
  // OTHER token (whose prints sit tens of cents away) and manufacture a delta that is
  // pure identification error — observed at +58c on the first run.
  if (!byMap && bestD > TAPE_TOKEN_PROXIMITY_USD) {
    return { tape: null, resolvedBy: null, rowsForMarket: all.length, rowsInWindow: inWindow.length, tokenGapUsd: bestD };
  }
  const post = rows.filter((r) => r.token === token && r.ts >= t0 && r.ts <= t0 + horizonMs);
  if (post.length === 0) {
    return { tape: null, resolvedBy: null, rowsForMarket: all.length, rowsInWindow: inWindow.length, tokenGapUsd: bestD };
  }
  const byBucket: Record<string, StampObservation | null> = {};
  for (const b of STAMP_LAG_BUCKETS) {
    const win = post.filter((r) => r.ts <= t0 + Math.min(b.maxMs, horizonMs));
    if (win.length === 0) {
      byBucket[b.label] = null;
      continue;
    }
    const min = win.reduce((a, r) => (r.price < a ? r.price : a), Infinity);
    byBucket[b.label] = { price: min, mid: null };
  }
  return {
    tape: { prints: post.length, byBucket },
    resolvedBy: byMap ? "map" : "proximity",
    rowsForMarket: all.length,
    rowsInWindow: inWindow.length,
    tokenGapUsd: bestD,
  };
}

// --------------------------------------------------------------------- run
async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!fs.existsSync(args.db)) {
    console.error(`[standard-fill-stamp] no database at ${args.db} — pass --db <path to prisma/dev.db>`);
    process.exit(1);
  }
  const epoch = corpusEpochMs(args.l2Dir);
  const sinceMs = args.sinceMs ?? epoch;
  const legs = loadLegs({ ...args, sinceMs });
  const all = loadLegs({ ...args, sinceMs: null });
  const amap = readAssetMap(args.assetMap);

  const stamped: StampLeg[] = [];
  let bookFiles = 0;
  let bookStamped = 0;
  for (const leg of legs) {
    const assets = amap.get(leg.marketId) ?? [];
    if (assets.some((a) => fs.existsSync(path.join(args.l2Dir, `${a}.jsonl`)))) bookFiles++;
    const b = stampBook(args.l2Dir, assets, leg.decisionPrice, leg.openedAt, args.horizonMs);
    if (b) bookStamped++;
    stamped.push({
      id: leg.id,
      decisionPrice: leg.decisionPrice,
      sizeUsd: leg.sizeUsd,
      book: b ? b.evidence : null,
      tape: null,
    });
  }

  // S2, precedence: only legs the book could not stamp, and only for a bounded number of
  // markets. Coverage of the tape is reported whatever it turns out to be.
  let tapeMarketsAttempted = 0;
  let tapeMarketsWithPrints = 0;
  let tapeMarketsInWindow = 0;
  let tapeStamped = 0;
  let tapeByMap = 0;
  let tapeByProximity = 0;
  let tapeTokenRejected = 0;
  if (!args.bookOnly) {
    const uncovered = legs.filter((l, i) => stamped[i].book === null);
    const byMarket = new Map<string, DbLeg[]>();
    for (const l of uncovered) {
      const arr = byMarket.get(l.marketId) ?? [];
      arr.push(l);
      byMarket.set(l.marketId, arr);
    }
    const markets = [...byMarket.keys()].slice(0, args.tapeMax);
    const cid = conditionMap(args.db, markets);
    const CONCURRENCY = 6;
    for (let i = 0; i < markets.length; i += CONCURRENCY) {
      const slice = markets.slice(i, i + CONCURRENCY);
      const fetched = await Promise.all(
        slice.map(async (m) => {
          const c = cid.get(m);
          if (!c) return { m, rows: [] as TapeRow[] };
          return { m, rows: await fetchTape(c, args.tapeCache) };
        })
      );
      for (const { m, rows } of fetched) {
        tapeMarketsAttempted++;
        if (rows.length > 0) tapeMarketsWithPrints++;
        const assetIds = amap.get(m) ?? [];
        let sawWindow = false;
        for (const leg of byMarket.get(m) ?? []) {
          const idx = stamped.findIndex((s) => s.id === leg.id);
          if (idx < 0) continue;
          const r = stampTape(rows, assetIds, leg.decisionPrice, leg.openedAt, args.horizonMs);
          if (r.rowsInWindow > 0) sawWindow = true;
          if (r.resolvedBy === "map") tapeByMap++;
          if (r.resolvedBy === "proximity") tapeByProximity++;
          if (r.resolvedBy === null && r.tokenGapUsd !== null && r.tokenGapUsd > TAPE_TOKEN_PROXIMITY_USD) {
            tapeTokenRejected++;
          }
          if (r.tape) {
            stamped[idx] = { ...stamped[idx], tape: r.tape };
            tapeStamped++;
          }
        }
        if (sawWindow) tapeMarketsInWindow++;
      }
    }
  }

  const bookSummary = summariseStamps(stamped, "book");
  const tapeSummary = summariseStamps(stamped, "tape");
  const bookRef = evaluateRefutation(bookSummary);
  const tapeRef = evaluateRefutation(tapeSummary);
  const reach = reachability(stamped);

  const coverage = {
    standardLegsAll: all.length,
    standardLegsInScope: legs.length,
    scopeSinceMs: sinceMs,
    l2CorpusEpochMs: epoch,
    l2CorpusPresent: fs.existsSync(args.l2Dir),
    marketsMissingAssetMap: legs.filter((l) => (amap.get(l.marketId) ?? []).length === 0).length,
    bookFilePresent: bookFiles,
    bookStamped,
    tapeMarketsAttempted,
    tapeMarketsWithPrints,
    tapeMarketsInWindow,
    tapeStamped,
    tapeByMap,
    tapeByProximity,
    tapeTokenRejected,
  };

  const artifact = {
    ranAt: new Date().toISOString(),
    basis: {
      population: "STANDARD PaperTrade rows, isDemo=0, opened at/after the L2 corpus epoch",
      decisionPrice: "PaperTrade.entryPrice (the quote STANDARD read at scoring time and booked)",
      deltaCents: "attainable - decisionPrice, in cents; POSITIVE = worse than booked",
      attainment: "lowest best-ask (book) / lowest print (tape) inside the lag window — REACHABILITY, not a fill",
      refutation: `fires only when n >= ${bookRef.gate} legs carry a mid AND |mean (attainable - mid)| <= ${bookRef.bandC}c`,
    },
    coverage,
    book: bookSummary,
    tape: tapeSummary,
    refutation: { book: bookRef, tape: tapeRef },
    reachabilityModeNone: reach,
    legs: stamped.map((s) => ({
      id: s.id,
      decisionPrice: s.decisionPrice,
      sizeUsd: s.sizeUsd,
      book: s.book
        ? {
            coverLagMs: s.book.coverLagMs,
            tokenAmbiguous: s.book.tokenAmbiguous,
            firstAsk: s.book.firstAsk,
            firstBid: s.book.firstBid,
            byBucket: s.book.byBucket,
          }
        : null,
      tape: s.tape ? { prints: s.tape.prints, byBucket: s.tape.byBucket } : null,
    })),
  };

  fs.mkdirSync(path.dirname(args.out), { recursive: true });
  fs.appendFileSync(args.out, JSON.stringify(artifact) + "\n");

  const lines: string[] = [];
  const pct = (x: number | null) => (x === null ? "n/a" : `${(100 * x).toFixed(0)}%`);
  const fmtC = (x: number | null) => (x === null || !Number.isFinite(x) ? "n/a" : `${x >= 0 ? "+" : ""}${x.toFixed(2)}c`);
  lines.push(
    `[standard-fill-stamp] population: ${coverage.standardLegsInScope} STANDARD legs opened on/after ` +
      `${sinceMs === null ? "(no epoch)" : new Date(sinceMs).toISOString()} of ${coverage.standardLegsAll} ever` +
      ` · L2 corpus ${coverage.l2CorpusPresent ? "present" : "ABSENT"}`
  );
  lines.push(
    `[standard-fill-stamp] book arm: ${coverage.bookStamped}/${coverage.standardLegsInScope} legs stamped` +
      ` (${pct(coverage.standardLegsInScope ? coverage.bookStamped / coverage.standardLegsInScope : null)})` +
      ` · ${bookFiles} legs had an L2 file at all` +
      (coverage.marketsMissingAssetMap ? ` · ${coverage.marketsMissingAssetMap} legs with no asset-map entry` : "")
  );
  lines.push(
    `[standard-fill-stamp] tape arm: ${coverage.tapeMarketsAttempted} markets fetched` +
      ` (${coverage.tapeMarketsWithPrints} returned prints, ${coverage.tapeMarketsInWindow} had a print INSIDE the dispatch window)` +
      ` → ${coverage.tapeStamped} legs stamped (token by asset map ${coverage.tapeByMap}, by tape proximity ${coverage.tapeByProximity}, ` +
      `refused as untellable ${coverage.tapeTokenRejected})` +
      (args.bookOnly ? " · SKIPPED (--book-only)" : ` · capped at --tape-max ${args.tapeMax}`)
  );
  lines.push("");
  for (const l of renderStamp(bookSummary)) lines.push(l);
  lines.push(
    `[standard-fill-stamp] resolver (mode=none, level = booked price): reachable ${reach.reachable}/${reach.attempted}` +
      ` = ${pct(reach.rate)} · unresolved ${reach.unresolved} (excluded, never counted as 'no fill')`
  );
  lines.push(
    `[standard-fill-stamp] REFUTATION (book, ±${bookRef.bandC}c of the mid, gate ${bookRef.gate}): ${bookRef.reason}`
  );
  if (bookRef.n > 0 && !bookRef.gateMet) {
    const spanDays = (Date.now() - (sinceMs ?? epoch ?? Date.now())) / 86_400_000;
    const perDay = spanDays > 0 ? bookSummary.total.n / spanDays : 0;
    const needed = bookRef.gate - bookRef.n;
    lines.push(
      `[standard-fill-stamp] gate arithmetic: ${bookRef.n} stamped legs over ${spanDays.toFixed(1)} days ` +
        `= ${perDay.toFixed(2)}/day → **${needed} more** legs, ~${perDay > 0 ? Math.ceil(needed / perDay) : "n/a"} days ` +
        `at the recorded coverage rate (book coverage is ${pct(bookSummary.coverage.rate)} of in-scope legs)`
    );
    const medianInsideBand = bookRef.medianMidC !== null && Math.abs(bookRef.medianMidC) <= bookRef.bandC;
    lines.push(
      `[standard-fill-stamp] direction at n=${bookRef.n} (NOT a verdict): mean ${fmtC(bookRef.meanMidC)} / median ` +
        `${fmtC(bookRef.medianMidC)} vs the contemporaneous mid, ` +
        `${medianInsideBand ? "inside" : "outside"} the ±${bookRef.bandC}c band — ` +
        (medianInsideBand
          ? "the booked price IS the mid and the attainable ask sits a spread ABOVE it, so the evidence points TOWARD refutation of the 1c-improvement claim"
          : "the attainable price sits away from the mid, so the evidence points AWAY from refutation")
    );
  }
  if (tapeSummary.coverage.covered > 0) {
    lines.push("");
    for (const l of renderStamp(tapeSummary)) lines.push(l);
    lines.push(`[standard-fill-stamp] REFUTATION (tape): ${tapeRef.reason}`);
  }
  lines.push("");
  lines.push(
    "[standard-fill-stamp] CAVEAT: attainable = REACHABILITY (a seller at/below the price), no queue position, no size; " +
      "min-ask over a window is optimistic by construction. Measurement only — no rule, size, gate or booked figure moved."
  );

  if (!args.json) for (const l of lines) console.log(l);
  else console.log(JSON.stringify({ coverage, book: bookSummary, tape: tapeSummary, refutation: artifact.refutation, reach }, null, 2));

  if (args.md) {
    const md = renderMarkdown({ coverage, bookSummary, tapeSummary, bookRef, tapeRef, reach, lines });
    fs.mkdirSync(path.dirname(args.md), { recursive: true });
    fs.writeFileSync(args.md, md);
    if (!args.json) console.log(`[standard-fill-stamp] draft written to ${args.md}`);
  }
  if (!args.json) console.log(`[standard-fill-stamp] artifact appended to ${args.out}`);
}

function renderMarkdown(x: {
  coverage: Record<string, unknown>;
  bookSummary: StampSummary;
  tapeSummary: StampSummary;
  bookRef: RefutationVerdict;
  tapeRef: RefutationVerdict;
  reach: { attempted: number; unresolved: number; reachable: number; rate: number | null };
  lines: string[];
}): string {
  const { coverage, bookSummary, bookRef, tapeSummary, tapeRef, reach } = x;
  const t = bookSummary.total;
  const fmt = (n: number | null, suffix = "") => (n === null || !Number.isFinite(n) ? "n/a" : `${n >= 0 ? "+" : ""}${n.toFixed(2)}${suffix}`);
  const gate = bookRef.gateMet ? "MET" : "NOT MET";
  const gateSince = Number(coverage.scopeSinceMs ?? 0);
  const gateSpanDays = gateSince > 0 ? (Date.now() - gateSince) / 86_400_000 : 0;
  const gatePerDay = gateSpanDays > 0 ? bookSummary.total.n / gateSpanDays : 0;
  const gateNeed = Math.max(0, bookRef.gate - bookRef.n);
  const gateLine = bookRef.gateMet
    ? "- **Gate arithmetic:** met — the rule can be evaluated on this read."
    : `- **Gate arithmetic:** ${gateNeed} more stamped legs. At the measured rate (${bookSummary.total.n} stamped over ` +
      `${gateSpanDays.toFixed(1)} days = ${gatePerDay.toFixed(2)}/day) that is ~${gatePerDay > 0 ? Math.ceil(gateNeed / gatePerDay) : "n/a"} days ` +
      `of ordinary running — but the binding constraint is L2 COVERAGE, not time: ` +
      `${bookSummary.coverage.rate === null ? "n/a" : (100 * bookSummary.coverage.rate).toFixed(0)}% of in-scope STANDARD legs ` +
      `have a covered book window at all, because the recorder pins C-200 dispatches and STANDARD dispatches are not pinned.`;
  return [
    "# STANDARD fill booth — first read (card t_7560e0d0)",
    "",
    `Generated ${new Date().toISOString()} by \`scripts/standard-fill-stamp.ts\`. **Measurement only** — nothing in`,
    "the trade path reads this, and no rule, size, gate or booked figure was changed.",
    "",
    "## The question",
    "",
    "STANDARD books `entryPrice = currentPrice` with p(fill) = 1 and no fill model at all. Profit-recs 2026-10-29 #1",
    "priced a 1c better entry at **+$1,439.33** on 90 days' settled notional (5.0% of notional against a 90d realised",
    "+8.1%): one cent is 62% of the lane's 90-day profit. This is the measurement that decides whether that cent exists.",
    "",
    "## Headline",
    "",
    `- **Book arm, widest window (${t.bucket}):** n = **${t.n}** legs, mean ` +
      `**${fmt(t.meanC, "c")}** vs the booked price, median **${fmt(t.medianC, "c")}**, 10th–90th percentile ` +
      `[${fmt(t.p10C)}, ${fmt(t.p90C)}]. The entry was attainable at the booked price or better on ` +
      `**${t.shareAtOrBetter === null ? "n/a" : (100 * t.shareAtOrBetter).toFixed(0)}%** of legs and a cent or more WORSE on ` +
      `**${t.shareWorseBy1c === null ? "n/a" : (100 * t.shareWorseBy1c).toFixed(0)}%**.`,
    `- **Versus the mid** (what the refutation is worded against): mean **${fmt(t.meanMidC, "c")}**, median ` +
      `**${fmt(t.medianMidC, "c")}**, within ±0.3c on ${t.shareMidWithinBand === null ? "n/a" : (100 * t.shareMidWithinBand).toFixed(0)}% of ` +
      `${t.midN} legs.`,
    `- **No waiting, no hindsight (first snapshot after the decision, n = ${bookSummary.first.n}):** mean ` +
      `**${fmt(bookSummary.first.meanC, "c")}**, median **${fmt(bookSummary.first.medianC, "c")}**, a cent or more worse on ` +
      `**${bookSummary.first.shareWorseBy1c === null ? "n/a" : (100 * bookSummary.first.shareWorseBy1c).toFixed(0)}%**. ` +
      `This is the taker's number; every wider bucket buys its lower mean with hindsight.`,
    `- **The pre-registered gate is ${gate}:** ${bookRef.n} legs against the required ${bookRef.gate}.`,
    gateLine,
    `- **Verdict:** ${bookRef.reason}`,
    "",
    "## How to read the two arms (they do NOT agree, and must not be pooled)",
    "",
    `The book arm asks *what ask could I have lifted*: at the first snapshot after the decision the best ask sat ` +
      `**${bookSummary.first.medianC !== null && bookSummary.first.medianC > 0 ? "above" : "at or below"}** the booked price ` +
      `(median ${fmt(bookSummary.first.medianC, "c")}, a cent or more worse on ` +
      `${bookSummary.first.shareWorseBy1c === null ? "n/a" : (100 * bookSummary.first.shareWorseBy1c).toFixed(0)}% of legs). ` +
      `A taker pays the spread, and the wider buckets approach parity only by taking the window's best price with hindsight.`,
    "",
    `The tape arm asks *did anything trade at or below the booked price*: ` +
      `${tapeSummary.total.n === 0 ? "no leg was stamped, so it says nothing" : `${tapeSummary.total.shareAtOrBetter === null ? "n/a" : (100 * tapeSummary.total.shareAtOrBetter).toFixed(0)}% of legs show a print at or below it inside an hour, median ${fmt(tapeSummary.total.medianC, "c")}, p10 ${fmt(tapeSummary.total.p10C, "c")}`} — ` +
      `but a min-print over an hour is the most optimistic statistic available, and its left tail is markets repricing ` +
      `(a print at 0.001 is not an entry a copier could size). The tape says the level existed somewhere in the hour; ` +
      `the book says you could not have lifted it at the decision. Only the book arm carries a mid, so only the book ` +
      `arm can answer the ±0.3c test.`,
    "",
    "## Distribution by decision-lag bucket (book arm)",
    "",
    "```",
    ...renderStamp(bookSummary),
    "```",
    "",
    "## Second source: venue prints (tape arm)",
    "",
    "Prints are trades that HAPPENED, not quotes we could have lifted, and they carry no mid — so this arm can extend",
    "coverage and read price-vs-decision, and can never feed the ±0.3c-of-mid test.",
    "",
    "```",
    ...(tapeSummary.coverage.covered > 0 ? renderStamp(tapeSummary) : ["[standard-fill-stamp] tape: no leg stamped"]),
    `[standard-fill-stamp] REFUTATION (tape): ${tapeRef.reason}`,
    "```",
    "",
    "## Coverage, per source (never assumed complete)",
    "",
    "```",
    JSON.stringify(coverage, null, 2),
    "```",
    "",
    "## Shared resolver, mode `none` (level = the booked price)",
    "",
    `Reachable **${reach.reachable}/${reach.attempted}** = ${reach.rate === null ? "n/a" : (100 * reach.rate).toFixed(0)}%`,
    `· unresolved ${reach.unresolved} (excluded from the rate, never counted as "did not fill").`,
    "",
    "## What this read does NOT establish",
    "",
    "- The card's gate (**≥300 legs**) is **not met by the book arm**, and the tape arm cannot substitute: it has no mid,",
    "  so the ±0.3c-of-mid test has no population to fire on. Nothing is refuted and nothing is confirmed.",
    "- Attainment is reachability: a best ask at/below a price is a seller willing there, ignoring queue position and",
    "  size. Min-ask over a window is an optimistic bound with hindsight; the 0-10s row is the no-patience read.",
    "- Our L2 recorder covers the market universe plus C-200 pins. STANDARD dispatches are not pinned, so book coverage",
    "  is incidental — that is why the book arm's n is what it is, and it is the binding constraint on the gate.",
    "",
    "## Reproduce",
    "",
    "```",
    "npx tsx scripts/standard-fill-stamp.ts --book-only     # offline, book arm only",
    "npx tsx scripts/standard-fill-stamp.ts                 # + bounded tape arm",
    "```",
    "",
    "Artifact: `data/standard-fill-stamp.jsonl` (append-only, one snapshot per run).",
    "",
  ].join("\n");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
