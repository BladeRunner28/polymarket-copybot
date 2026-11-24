/**
 * Venue shadow book: C-200 as booked (Polymarket) vs the same trades booked at
 * KALSHI's own top-of-book. Forward-only.
 *
 * WHY FORWARD-ONLY: Kalshi order books are not archived, so a quote fetched today
 * for a trade opened last week is NOT the entry that trade would have got. Rows
 * whose first sighting is more than `--max-quote-age-hours` after `openedAt` are
 * recorded as stale with no Kalshi entry and are excluded from the books.
 *
 * WHY THIS IS NOT data/kalshi-shadow.jsonl:
 *   - kalshi-shadow.py = ATTRIBUTION of the existing book at Polymarket prices
 *     ("which rule would have routed this?"), fully historical.
 *   - this ledger    = VENUE COMPARISON at each venue's own price ("what would the
 *     same trade have paid on Kalshi?"), forward-only, real quotes.
 *
 * MATCH VERIFICATION (added after a live false positive): the sidecar resolves a
 * Polymarket question to a Kalshi event by token overlap, `overlap / min(tokens)`,
 * bar 0.55. On 2026-09-13 that matched "Will Bursaspor win on 2026-09-13?" to
 * KXANYDEMWINTEXAS-26NOV03 (a Texas election market, 99.9¢) at score 0.67 by
 * sharing only {win, 2026} — a fabricated ~28¢ "venue edge". So every quote is now
 * verified against the matched event TITLE before it can enter a book, and the
 * raw ticker/title/score is stored for audit. Verification prefers false negatives
 * (dropping real matches on abbreviated titles) over fabricated prices.
 *
 * Usage:  npx tsx scripts/kalshi-venue-shadow.ts [--dry-run] [--max-quote-age-hours N]
 * Writes: data/kalshi-venue-shadow.jsonl (+ .summary.json). No DB writes.
 */

import { prisma } from "../src/lib/db";
import * as fs from "fs";
import * as path from "path";
import { execFileSync } from "child_process";
import {
  normaliseKalshiResult, venueSideWon, venueGross, summariseBasis,
  venueWonFromPair, pairKey, type PairJudgement,
} from "../src/lib/kalshi-venue-settlement";

const LEDGER = path.join(process.cwd(), "data", "kalshi-venue-shadow.jsonl");
const SUMMARY = path.join(process.cwd(), "data", "kalshi-venue-shadow-summary.json");
const SIDECAR = process.env.SIDECAR_QUOTE_URL ?? "http://127.0.0.1:3014/quote";
const KALSHI_FEE_RATE = 0.07; // Kalshi schedule; flagged as needing live confirmation (fee audit)
const DEFAULT_MAX_QUOTE_AGE_H = 6;
const BOT = "BANKROLL_200";
/** Deterministic contract-equivalence arm (card kalshi-lane-ontology-not-coverage, option (a),
 *  approved 2026-11-23). Observation only: it writes its own fields and its own summary block;
 *  it never feeds pmPnl / kalshiPnl / delta, and nothing in decisions or sizing reads it. */
const DET_RESOLVER = path.join(process.cwd(), "scripts", "kalshi-contract-equivalence.py");
const DET_ENABLED = process.env.KALSHI_DET_ARM !== "0";
/** Rows resolved per run: the resolver walks event markets per candidate, so a bound keeps a
 *  cron tick short; the ledger drains newest-first over successive runs. */
const DET_BATCH = Number(process.env.KALSHI_DET_BATCH ?? 60);

/** Venue-settlement pass (card kalshi-venue-shadow-pnl-exit-sign-basis): settled ledger rows whose
 *  ticker has not been read yet, per run. One keyless GET per distinct ticker. */
const VENUE_SETTLE_BATCH = Number(process.env.KALSHI_VENUE_SETTLE_BATCH ?? 80);
const KALSHI_API = "https://api.elections.kalshi.com/trade-api/v2";

/** A match must clear this raw sidecar score to be trusted at all. */
const MIN_MATCH_SCORE = 0.75;
/** Words that carry no identity — sharing one of these proves nothing. */
const GENERIC = new Set([
  "the", "will", "win", "wins", "lose", "loses", "beat", "beats", "game", "games", "match", "matches",
  "yes", "no", "above", "below", "over", "under", "between", "price", "close", "closes", "market",
  "rate", "rates", "point", "points", "total", "score", "final", "today", "tomorrow", "week", "month",
  "year", "day", "vs", "first", "last", "next", "more", "less", "than", "highest", "lowest",
]);

function words(s: string): string[] {
  return (s ?? "")
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter((w) => w.length >= 3 && !GENERIC.has(w) && !/^\d+$/.test(w));
}

/** Question-vs-matched-title check. Returns a reason string, or null when OK. */
function verifyMatch(question: string, matchedTitle: string, score: number): string | null {
  if (!matchedTitle) return "no_matched_title";
  if (!(score >= MIN_MATCH_SCORE)) return `low_match_score_${score.toFixed(2)}`;
  const q = words(question);
  const t = new Set(words(matchedTitle));
  const shared = q.filter((w) => t.has(w));
  // A distinctive token (>=5 chars, non-generic) must be shared, otherwise the
  // match rests entirely on generic/numeric tokens.
  if (!shared.some((w) => w.length >= 5)) return `no_distinctive_overlap (shared: ${shared.join(",") || "none"})`;
  return null;
}

/** Same keyword map as scripts/build-decision-dataset.py / src/lib/scoring/price-edge.ts */
function pmFeeRate(text: string): number {
  const t = (text ?? "").toLowerCase();
  const crypto = ["btc", "bitcoin", "eth", "ethereum", "solana", "crypto", "token", "airdrop", "fdv", "market cap"];
  const polfin = ["election", "president", "senate", "congress", "nominee", "parliament", "prime minister", "fed",
    "rate cut", "inflation", "cpi", "gdp", "recession", "tariff", "stock", "nasdaq", "s&p", "earnings",
    "shutdown", "impeach", "poll", "vote", "governor", "mayor"];
  if (crypto.some((w) => t.includes(w))) return 0.07;
  if (polfin.some((w) => t.includes(w))) return 0.04;
  return 0.05;
}

/** Per-share taker fee, same functional form on both venues: shares * rate * p * (1-p). */
function feeUsd(size: number, price: number, rate: number): number {
  return size * rate * (1 - price);
}

type Row = {
  tradeId: string; decisionId: string; marketId: string; question: string; outcome: string; side: string;
  openedAt: string; openedMs: number; status: string;
  pmEntry: number; size: number; pmFeeRate: number;
  kalshiResolved: boolean; kalshiEntry: number | null; kalshiError: string | null;
  kalshiTicker: string | null; kalshiTitle: string | null; kalshiScore: number | null;
  verified: boolean; verifyReason: string | null;
  kalshiQuoteAtMs: number | null; stale: boolean; attempts: number;
  firstSeenAtMs: number; lastCheckedAtMs: number;
  won: boolean | null; pmPnl: number | null; kalshiPnl: number | null; delta: number | null;
  /** deterministic contract-equivalence arm — its own fields, never mixed into kalshiPnl */
  detVerdict?: string; detTicker?: string; detTitle?: string; detEntry?: number | null;
  detOurSideIsYes?: boolean | null; detEvent?: string; detAtMs?: number; detNote?: string;
  detRules?: string;
  /** SETTLEMENT BASIS, added 2026-11-24. `won` above is OUR EXIT SIGN and stays the historical
   *  record; it is NOT settlement. These fields are what the venue itself says, and the PnL arm
   *  built on them is a separate field — no old number was restated. */
  venueResult?: "yes" | "no" | null; venueStatus?: string | null; venueTicker?: string | null;
  venueAtMs?: number; venueWon?: boolean | null; venuePnl?: number | null; venueDelta?: number | null;
  venueSource?: "kalshi_side" | "pm_token" | null;
};

type DetOut = {
  marketId: string; verdict: string; ticker: string | null; kalshiTitle: string | null;
  yesBid: number | null; yesAsk: number | null; lastPrice?: number | null;
  price: number | null; ourSideIsYes: boolean | null; event?: string; note?: string;
  rulesPrimary?: string; tickerStatus?: string;
};

/** Resolve a batch of OUR trades to contract-equivalent Kalshi markets via the shipped
 *  deterministic parser (alias table + slug identity + strike gates). One subprocess per run,
 *  never per trade. Returns an empty map on any failure — this arm is additive, and a broken
 *  resolver must not stop the fuzzy arm from recording its rows. */
function resolveDeterministic(rows: Row[]): Map<string, DetOut> {
  const out = new Map<string, DetOut>();
  if (!DET_ENABLED || !rows.length || !fs.existsSync(DET_RESOLVER)) return out;
  const tmpIn = path.join(process.cwd(), "data", "cache", `det-arm-req-${process.pid}.json`);
  const tmpOut = tmpIn.replace("-req-", "-out-");
  try {
    fs.mkdirSync(path.dirname(tmpIn), { recursive: true });
    fs.writeFileSync(tmpIn, JSON.stringify(rows.map((r) => ({
      marketId: r.marketId ?? "", question: r.question, dayMs: r.openedMs, outcome: r.outcome,
    }))));
    execFileSync("python3", [DET_RESOLVER, "--resolve", tmpIn, "--resolve-out", tmpOut],
      { timeout: 240_000, stdio: ["ignore", "ignore", "inherit"] });
    const parsed = JSON.parse(fs.readFileSync(tmpOut, "utf-8")) as DetOut[];
    for (const d of parsed) out.set(d.marketId, d);
  } catch (e) {
    console.error(`det arm skipped: ${(e as Error).message}`);
  } finally {
    for (const p of [tmpIn, tmpOut]) { try { fs.unlinkSync(p); } catch { /* ignore */ } }
  }
  return out;
}

function loadLedger(): Map<string, Row> {
  const m = new Map<string, Row>();
  if (!fs.existsSync(LEDGER)) return m;
  for (const line of fs.readFileSync(LEDGER, "utf-8").split("\n")) {
    if (!line.trim()) continue;
    try {
      const r = JSON.parse(line) as Row;
      if (!r.tradeId) continue;
      // Migration: rows quoted before the match-verification guard existed carry a
      // price but no provenance. They were never verified, so they must not price a
      // book — flag them rather than silently trusting or silently dropping them.
      if (r.kalshiResolved && r.verified === undefined) {
        r.verified = false;
        r.verifyReason = "pre_guard_quote (no match provenance stored)";
      }
      m.set(r.tradeId, r);
    } catch { /* skip malformed line, never lose the rest */ }
  }
  return m;
}

type QuoteOut =
  | { ok: true; price: number; ticker: string; title: string; score: number }
  | { ok: false; error: string };

async function quoteKalshi(question: string, marketId: string, side: string): Promise<QuoteOut> {
  try {
    const res = await fetch(SIDECAR, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ market_id: marketId, market_question: question, side }),
      signal: AbortSignal.timeout(20_000),
    });
    if (res.status === 404) return { ok: false, error: "sidecar_route_missing" };
    if (!res.ok) return { ok: false, error: `sidecar_http_${res.status}` };
    const b = (await res.json()) as {
      ok?: boolean; price?: number; ticker?: string; matched_title?: string; match_score?: number; error?: string;
    };
    if (b.ok && typeof b.price === "number") {
      return { ok: true, price: b.price, ticker: b.ticker ?? "", title: b.matched_title ?? "", score: b.match_score ?? 0 };
    }
    return { ok: false, error: b.error ?? "no_price" };
  } catch (e) {
    return { ok: false, error: `sidecar_unreachable: ${(e as Error).message}` };
  }
}


/** The venue's own settlement: GET /markets/<ticker> -> result (yes|no) once finalized. Keyless.
 *  Returns null on failure (never a verdict), so a dead route cannot invent a settlement. */
async function fetchKalshiSettlement(
  ticker: string,
): Promise<{ result: "yes" | "no" | null; status: string | null } | null> {
  if (!ticker) return null;
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const res = await fetch(`${KALSHI_API}/markets/${encodeURIComponent(ticker)}`, {
        headers: { "user-agent": "medusa-copybot/1.0", accept: "application/json" },
        signal: AbortSignal.timeout(20_000),
      });
      if (res.ok) {
        const b = (await res.json()) as { market?: { result?: unknown; status?: unknown } };
        return {
          result: normaliseKalshiResult(b.market?.result),
          status: typeof b.market?.status === "string" ? b.market.status : null,
        };
      }
    } catch { /* retry once, then give up */ }
  }
  return null;
}

/** One line, both bases named, for stdout and --dry-run — so a settlement read can never be
 *  mistaken for the exit-sign book (card kalshi-venue-shadow-pnl-exit-sign-basis). */
function settlementBasisLine(sb: {
  known: number; population: number; agree: number; disagree: number;
  exitLossVenueWin: number; exitWinVenueLoss: number;
  matchedPriced: { n: number; exitPnl: number; venuePnl: number };
}): string {
  return `settlement basis (det arm; level=leg): ${sb.known} knowable of ${sb.population} settled legs, `
    + `${sb.agree} agree / ${sb.disagree} disagree with the exit sign (${sb.exitLossVenueWin} booked a loss that`
    + ` settled a win, ${sb.exitWinVenueLoss} booked a win that settled a loss); matched priced n=`
    + `${sb.matchedPriced.n} exit $${sb.matchedPriced.exitPnl} vs venue $${sb.matchedPriced.venuePnl}`;
}

/** The pair-settlement audit's per-pair adjudication (side + both venues' own settlement).
 *  Read-only input: this ledger consumes it, it never writes it. Missing file = no adjudication,
 *  and every settlement figure stays null rather than falling back to a second opinion. */
const PAIR_AUDIT = path.join(process.cwd(), "data", "kalshi-pair-settlement.json");
type PairAuditRow = {
  marketId?: string; outcome?: string; kalshiTicker?: string;
  sideYes?: boolean | null; kalshiResult?: string | null; pmWinner?: boolean | null; verdict?: string;
};
function loadPairJudgements(): { map: Map<string, PairJudgement>; generatedAt: string | null; pairs: number } {
  const map = new Map<string, PairJudgement>();
  if (!fs.existsSync(PAIR_AUDIT)) return { map, generatedAt: null, pairs: 0 };
  try {
    const doc = JSON.parse(fs.readFileSync(PAIR_AUDIT, "utf-8")) as { generatedAt?: string; pairs?: PairAuditRow[] };
    for (const p of doc.pairs ?? []) {
      if (!p.marketId || !p.kalshiTicker) continue;
      map.set(pairKey(p.marketId, p.outcome ?? "", p.kalshiTicker), {
        sideYes: p.sideYes ?? null,
        kalshiResult: normaliseKalshiResult(p.kalshiResult),
        pmWinner: p.pmWinner ?? null,
      });
    }
    return { map, generatedAt: doc.generatedAt ?? null, pairs: map.size };
  } catch {
    return { map, generatedAt: null, pairs: 0 };
  }
}
async function main() {
  const dryRun = process.argv.includes("--dry-run");
  const ageIdx = process.argv.indexOf("--max-quote-age-hours");
  const maxAgeH = ageIdx >= 0 ? Number(process.argv[ageIdx + 1]) : DEFAULT_MAX_QUOTE_AGE_H;
  const maxAgeMs = maxAgeH * 3600_000;
  const now = Date.now();

  const ledger = loadLedger();

  const trades = await prisma.paperTrade.findMany({
    where: { botId: BOT, isDemo: false },
    select: {
      id: true, decisionJournalId: true, status: true, openedAt: true, closedAt: true, resolvedAt: true,
      entryPrice: true, simulatedPositionSize: true, realizedPnl: true, outcome: true, side: true, marketId: true,
      decision: { select: { observedTrade: { select: { marketQuestion: true } } } },
    },
    orderBy: { openedAt: "desc" },
    take: 400,
  });

  let added = 0, quoted = 0, failed = 0, stale = 0, unverified = 0, settled = 0;
  const reasonCounts = new Map<string, number>();
  const seenAtCutoff = Math.min(...[...ledger.values()].map((r) => r.firstSeenAtMs), now);

  for (const t of trades) {
    const openedMs = new Date(t.openedAt).getTime();
    const question = t.decision?.observedTrade?.marketQuestion ?? "";
    const existing = ledger.get(t.id);

    if (!existing) {
      const isStale = now - openedMs > maxAgeMs;
      const row: Row = {
        tradeId: t.id, decisionId: t.decisionJournalId, marketId: t.marketId, question, outcome: t.outcome, side: t.side,
        openedAt: new Date(t.openedAt).toISOString(), openedMs, status: t.status,
        pmEntry: t.entryPrice, size: t.simulatedPositionSize, pmFeeRate: pmFeeRate(question),
        kalshiResolved: false, kalshiEntry: null, kalshiError: null,
        kalshiTicker: null, kalshiTitle: null, kalshiScore: null,
        verified: false, verifyReason: null,
        kalshiQuoteAtMs: null, stale: isStale, attempts: 0, firstSeenAtMs: now, lastCheckedAtMs: now,
        won: null, pmPnl: null, kalshiPnl: null, delta: null,
      };
      if (openedMs >= seenAtCutoff - 86_400_000 && !isStale) {
        row.attempts = 1;
        const q = await quoteKalshi(question, t.marketId, t.side);
        row.kalshiQuoteAtMs = Date.now();
        if (q.ok) {
          row.kalshiResolved = true; row.kalshiEntry = q.price;
          row.kalshiTicker = q.ticker; row.kalshiTitle = q.title; row.kalshiScore = q.score;
          const reason = verifyMatch(question, q.title, q.score);
          row.verified = reason === null;
          row.verifyReason = reason;
          if (row.verified) quoted++;
          else {
            unverified++;
            const key = (reason ?? "unknown").split(" ")[0];
            reasonCounts.set(key, (reasonCounts.get(key) ?? 0) + 1);
          }
        } else {
          row.kalshiError = q.error;
          failed++;
          reasonCounts.set(q.error.split(":")[0], (reasonCounts.get(q.error.split(":")[0]) ?? 0) + 1);
        }
      } else if (isStale) {
        row.kalshiError = `stale_first_sighting (${((now - openedMs) / 3600_000).toFixed(1)}h > ${maxAgeH}h)`;
        stale++;
      } else {
        row.kalshiError = "before_window_start";
      }
      ledger.set(t.id, row);
      added++;
      continue;
    }

    existing.status = t.status;
    existing.lastCheckedAtMs = now;
    const done = t.status === "closed" || t.status === "resolved";
    if (done && t.realizedPnl != null) {
      const won = t.realizedPnl > 0;
      const pmFee = feeUsd(existing.size, existing.pmEntry, existing.pmFeeRate);
      const pmPnl = t.realizedPnl - pmFee;
      let kalshiPnl: number | null = null;
      // Unverified matches never price a book.
      if (existing.verified && existing.kalshiEntry != null && existing.kalshiEntry > 0) {
        const kFee = feeUsd(existing.size, existing.kalshiEntry, KALSHI_FEE_RATE);
        const gross = won ? existing.size * (1 / existing.kalshiEntry - 1) : -existing.size;
        kalshiPnl = gross - kFee;
      }
      existing.won = won; existing.pmPnl = pmPnl; existing.kalshiPnl = kalshiPnl;
      existing.delta = kalshiPnl == null ? null : kalshiPnl - pmPnl;
      settled++;
    }
  }

  // ---- deterministic contract-equivalence arm (observation only; never touches pmPnl/kalshiPnl)
  const marketById = new Map(trades.map((t) => [t.id, t.marketId]));
  for (const r of ledger.values()) if (!r.marketId) r.marketId = marketById.get(r.tradeId) ?? "";
  let detAttempted = 0;
  if (DET_ENABLED) {
    const todo = [...ledger.values()]
      .filter((r) => !r.stale && r.kalshiError !== "before_window_start"
        && r.detVerdict === undefined && r.marketId)
      .sort((a, b) => b.openedMs - a.openedMs)
      .slice(0, DET_BATCH);
    detAttempted = todo.length;
    const det = resolveDeterministic(todo);
    for (const r of todo) {
      const d = det.get(r.marketId);
      if (!d) continue;
      r.detVerdict = d.verdict;
      r.detAtMs = Date.now();
      if (d.verdict === "EQUIV") {
        r.detTicker = d.ticker ?? undefined;
        r.detTitle = d.kalshiTitle ?? undefined;
        r.detEvent = d.event;
        r.detOurSideIsYes = d.ourSideIsYes ?? null;
        r.detEntry = d.price ?? null;
        r.detRules = d.rulesPrimary;
        r.detNote = d.note;
      } else {
        r.detNote = d.note;
      }
    }
  }


  // ---- venue-settlement pass (card kalshi-venue-shadow-pnl-exit-sign-basis, 2026-11-24).
  // `won` above is the EXIT sign of OUR paper leg. This pass records what the VENUE says, and a
  // second set of figures derived from it, without overwriting the exit-sign ones.
  let venueChecked = 0, venueFailed = 0, venueStillOpen = 0;
  let pairAudit = loadPairJudgements();
  let venueSideFlagDisagreements = 0;
  {
    const settledRows = [...ledger.values()].filter((r) => r.pmPnl != null);
    // The population this basis is DEFINED on: a contract-equivalence pair — the only arm that
    // names the venue contract we hold. A fuzzy sidecar quote has a ticker but no resolved side, so
    // it can never produce a settlement read and keeps its exit-sign figures, unchanged.
    const basisRows = settledRows.filter((r) => r.detVerdict === "EQUIV" && !!r.detTicker);
    const todo = basisRows
      .filter((r) => r.venueResult == null) // undefined = never read; null = not yet finalized
      .sort((a, b) => b.openedMs - a.openedMs)
      .slice(0, VENUE_SETTLE_BATCH);
    if (process.env.KALSHI_VENUE_DEBUG) {
      console.error(`venue dbg: ledger=${ledger.size} settled=${settledRows.length} basisRows=${basisRows.length} todo=${todo.length}`);
    }
    for (const r of todo) {
      const ticker = r.detTicker as string;
      const got = await fetchKalshiSettlement(ticker);
      venueChecked++;
      if (!got) { venueFailed++; continue; }
      r.venueTicker = ticker;
      r.venueResult = got.result;
      r.venueStatus = got.status;
      r.venueAtMs = Date.now();
      // A market the venue has not finalized yet stays retryable: its empty result is not a verdict.
      if (got.result == null) venueStillOpen++;
    }
    // Derived every run from what is stored (idempotent). The SIDE question is not re-derived here:
    // it comes from the pair-settlement audit, because the ledger's own detOurSideIsYes disagrees
    // with our outcome's side on 13 of 41 determinable pairs — a second opinion would manufacture
    // settlement flips out of that defect.
    for (const r of settledRows) {
      const p = r.detTicker ? pairAudit.map.get(pairKey(r.marketId, r.outcome, r.detTicker)) : undefined;
      const v = venueWonFromPair(p);
      r.venueWon = v.won;
      r.venueSource = v.source;
      if (p && p.sideYes != null && r.detOurSideIsYes != null && p.sideYes !== r.detOurSideIsYes) {
        venueSideFlagDisagreements++;
      }
      // A venue-basis PnL needs the VENUE's own entry price (detEntry), never Polymarket's: pricing
      // a Kalshi contract at our PM fill is the same class of basis lie this card is repairing.
      const entry = r.detEntry ?? null;
      const gross = r.venueWon == null || entry == null ? null : venueGross(r.size, entry, r.venueWon);
      r.venuePnl = gross == null || entry == null ? null : gross - feeUsd(r.size, entry, KALSHI_FEE_RATE);
      r.venueDelta = r.venuePnl == null || r.pmPnl == null ? null : r.venuePnl - r.pmPnl;
    }
  }
  const rows = [...ledger.values()].sort((a, b) => a.openedMs - b.openedMs);
  const inWindow = rows.filter((r) => !r.stale && r.kalshiError !== "before_window_start");
  const verified = inWindow.filter((r) => r.verified);
  // Every quoted row lands in exactly one bucket: verified, or counted as rejected.
  const unverifiedRows = inWindow.filter((r) => r.kalshiResolved && !r.verified);
  for (const r of unverifiedRows) {
    const key = (r.verifyReason ?? "unknown").split(" ")[0];
    reasonCounts.set(key, (reasonCounts.get(key) ?? 0) + 1);
  }
  const bookRows = verified.filter((r) => r.pmPnl != null);
  const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);
  const pmPnl = sum(bookRows.map((r) => r.pmPnl ?? 0));
  const kPnl = sum(bookRows.map((r) => r.kalshiPnl ?? 0));
  const staked = sum(bookRows.map((r) => r.size));

  const byDay = new Map<string, { pm: number; kalshi: number }>();
  for (const r of bookRows) {
    const d = r.openedAt.slice(0, 10);
    const e = byDay.get(d) ?? { pm: 0, kalshi: 0 };
    e.pm += r.pmPnl ?? 0; e.kalshi += r.kalshiPnl ?? 0;
    byDay.set(d, e);
  }
  const dates = [...byDay.keys()].sort();
  const cum = (pick: (v: { pm: number; kalshi: number }) => number) => {
    let acc = 0;
    return dates.map((d) => (acc += pick(byDay.get(d)!)));
  };
  const r2 = (v: number) => Math.round(v * 100) / 100;

  const summary = {
    asOf: new Date().toISOString(),
    kind: "forward-venue-shadow",
    windowStart: new Date(Math.min(...rows.map((r) => r.firstSeenAtMs))).toISOString(),
    note: "Forward-only venue comparison: each C-200 copy booked at Polymarket's actual entry and at Kalshi's "
      + "own top-of-book, same size, each venue's own taker fee. Not a backfill — Kalshi order books are not archived.",
    caveats: [
      "Kalshi's public orderbook exposes the TOP LEVEL only — no depth, no market impact, no fill probability.",
      "Kalshi fee modelled at 0.07 (published schedule; the fee audit flags it as needing live confirmation).",
      "Every quote is verified against the matched Kalshi event TITLE; unverified matches are counted and excluded, "
        + "never priced. Expect false negatives (abbreviated titles) — dropping a real match is cheaper than "
        + "fabricating a venue edge.",
      "win/loss in the kalshi book comes from realizedPnl's SIGN (our exit), NOT from settlement: an early "
      + "close books a loss on a contract that settled a win. For any settlement question read "
      + "settlementBasis and deterministic.book.venuePnl (the venue's own result on our adjudicated "
      + "side); the exit-sign figures are kept unchanged as the historical record.",
      `rows first seen more than ${maxAgeH}h after open are excluded as stale (a late quote is not an entry).`,
      "no real Kalshi orders were placed and none will be — paper only.",
    ],
    coverage: {
      copiesSeen: rows.length, inWindow: inWindow.length, withKalshiQuote: verified.length,
      crossListRate: inWindow.length ? Math.round((verified.length / inWindow.length) * 1000) / 1000 : 0,
      staleSkips: rows.filter((r) => r.stale).length,
      quoteFailures: inWindow.filter((r) => !r.kalshiResolved).length,
      // Recomputed from the ledger (not the run counter) so the buckets always sum:
      // verified + unverified + no-quote === inWindow.
      unverifiedMatches: unverifiedRows.length,
      rejectionReasons: Object.fromEntries(reasonCounts),
    },
    books: {
      pm: { n: bookRows.length, pnl: r2(pmPnl), staked: r2(staked), roiPct: staked ? r2((pmPnl / staked) * 100) : 0 },
      kalshi: { n: bookRows.filter((r) => r.kalshiPnl != null).length, pnl: r2(kPnl), staked: r2(staked),
                roiPct: staked ? r2((kPnl / staked) * 100) : 0 },
      delta: { pnl: r2(kPnl - pmPnl), perTrade: bookRows.length ? r2((kPnl - pmPnl) / bookRows.length) : 0 },
    },
    series: { dates, pmCum: cum((v) => v.pm).map(r2), kalshiCum: cum((v) => v.kalshi).map(r2) },
    /** Contract-equivalence arm: deterministic pairs (slug identity + derived team aliases +
     *  class + strike), priced on OUR side. Separate from the fuzzy arm above on purpose —
     *  its rows are NOT mixed into pm/kalshi/delta, so activating it moves no published
     *  number and deleting the block reverts to the pre-2026-11-23 read exactly. */
    deterministic: (() => {
      const det = [...ledger.values()].filter((r) => r.detVerdict !== undefined);
      const equiv = det.filter((r) => r.detVerdict === "EQUIV");
      const priced = equiv.filter((r) => r.detEntry != null);
      const settledDet = priced.filter((r) => r.pmPnl != null);
      const detPnl = sum(settledDet.map((r) => {
        const won = r.won === true; // EXIT SIGN, not settlement — see venuePnl beside it
        const gross = won ? r.size * (1 / (r.detEntry as number) - 1) : -r.size;
        return gross - feeUsd(r.size, r.detEntry as number, KALSHI_FEE_RATE);
      }));
      const venuePriced = settledDet.filter((r) => r.venuePnl != null);
      const venuePnlDet = sum(venuePriced.map((r) => r.venuePnl ?? 0));
      const venueStakedDet = sum(venuePriced.map((r) => r.size));
      const pmPnlDet = sum(settledDet.map((r) => r.pmPnl ?? 0));
      const stakedDet = sum(settledDet.map((r) => r.size));
      const verdicts: Record<string, number> = {};
      for (const r of det) verdicts[r.detVerdict as string] = (verdicts[r.detVerdict as string] ?? 0) + 1;
      return {
        enabled: DET_ENABLED, attempted: detAttempted, resolved: det.length,
        verdicts, equiv: equiv.length, priced: priced.length,
        coverage: det.length ? Math.round((equiv.length / det.length) * 1000) / 1000 : 0,
        fuzzyEquiv: det.filter((r) => r.detVerdict === "EQUIV" && r.verified).length,
        detOnlyEquiv: det.filter((r) => r.detVerdict === "EQUIV" && !r.verified).length,
        book: {
          n: settledDet.length, pmPnl: r2(pmPnlDet), detPnl: r2(detPnl), staked: r2(stakedDet),
          pmRoiPct: stakedDet ? r2((pmPnlDet / stakedDet) * 100) : 0,
          detRoiPct: stakedDet ? r2((detPnl / stakedDet) * 100) : 0,
          /** Same book, priced on the VENUE's result instead of our exit sign, with its own n: a leg
           *  with a settlement verdict but no entry price is knowable and not priceable. */
          detPnlBasis: "exit_sign", venuePnlBasis: "kalshi_market_result",
          venueN: venuePriced.length, venuePnl: r2(venuePnlDet), venueStaked: r2(venueStakedDet),
          venueRoiPct: venueStakedDet ? r2((venuePnlDet / venueStakedDet) * 100) : 0,
        },
        pairs: equiv.slice(-30).map((r) => ({
          question: r.question.slice(0, 80), detTicker: r.detTicker, detTitle: (r.detTitle ?? "").slice(0, 80),
          ourSideIsYes: r.detOurSideIsYes, detEntry: r.detEntry, pmEntry: r.pmEntry,
          fuzzyTicker: r.kalshiTicker, fuzzyVerified: r.verified, note: r.detNote,
        })),
      };
    })(),
    /** SETTLEMENT BASIS (card kalshi-venue-shadow-pnl-exit-sign-basis). Population = settled
     *  contract-equivalent legs; level = one ledger leg; clock = openedAt of those legs; truth = the
     *  venue's own settlement, adjudicated per pair by scripts/kalshi-pair-settlement-read.py.
     *  Additive: no exit-sign figure is restated, replaced or mixed in. */
    settlementBasis: (() => {
      const legs = [...ledger.values()].filter((r) => r.detVerdict === "EQUIV" && r.pmPnl != null);
      const s = summariseBasis(legs.map((r) => ({ exitWon: r.won, venueWon: r.venueWon })));
      const pricedLegs = legs.filter((r) => r.venuePnl != null && r.detEntry != null);
      let exitOnPriced = 0, venueOnPriced = 0;
      for (const r of pricedLegs) {
        const entry = r.detEntry as number;
        const g = venueGross(r.size, entry, r.won === true);
        if (g != null) exitOnPriced += g - feeUsd(r.size, entry, KALSHI_FEE_RATE);
        venueOnPriced += r.venuePnl ?? 0;
      }
      const opened = legs.map((r) => r.openedMs);
      return {
        ...s,
        populationNote: "detVerdict==EQUIV legs whose paper leg is settled; level = ledger leg",
        exitBasis: "realizedPnl sign of OUR paper leg (early exits and partial closes) — NOT settlement",
        venueBasis: "Kalshi /markets/<ticker> result on our side as adjudicated by the pair audit"
          + " (PM token winner only as the fallback)",
        clock: {
          openedAtFrom: opened.length ? new Date(Math.min(...opened)).toISOString() : null,
          openedAtTo: opened.length ? new Date(Math.max(...opened)).toISOString() : null,
          readAt: new Date().toISOString(),
        },
        quoterun: { attempted: venueChecked, failures: venueFailed, stillOpen: venueStillOpen },
        sideAdjudication: {
          source: "data/kalshi-pair-settlement.json",
          generatedAt: pairAudit.generatedAt,
          pairsInArtifact: pairAudit.pairs,
          legsAdjudicated: legs.filter((r) => r.venueSource != null).length,
          /** named, never consumed: the ledger's stored detOurSideIsYes against the adjudicated side,
           *  on this same population. It is the defective column (13 of 41 pairs, audit 2026-11-24). */
          storedSideFlagDisagreements: venueSideFlagDisagreements,
        },
        /** matched pair on the legs that have BOTH the venue's own entry price and a venue verdict */
        matchedPriced: {
          n: pricedLegs.length, exitPnl: r2(exitOnPriced), venuePnl: r2(venueOnPriced),
          delta: r2(venueOnPriced - exitOnPriced),
          basis: "same legs, same detEntry; exit-sign PnL vs venue-settlement PnL",
        },
        flips: legs.filter((r) => r.venueWon != null && r.won != null && r.won !== r.venueWon)
          .map((r) => ({
            question: r.question.slice(0, 80), detTicker: r.detTicker, venueResult: r.venueResult,
            venueSource: r.venueSource, exitWon: r.won, venueWon: r.venueWon,
            pmPnl: r2(r.pmPnl ?? 0), venuePnl: r.venuePnl == null ? null : r2(r.venuePnl),
          })),
      };
    })(),
    // accepted + rejected quotes, so the match audit is visible on the dashboard
    matchAudit: rows.filter((r) => r.kalshiResolved).slice(-40).map((r) => ({
      question: r.question.slice(0, 90), ticker: r.kalshiTicker, matchedTitle: (r.kalshiTitle ?? "").slice(0, 90),
      score: r.kalshiScore, kalshiEntry: r.kalshiEntry, pmEntry: r.pmEntry,
      verified: r.verified, reason: r.verifyReason,
    })),
    perTrade: bookRows.slice(-50).map((r) => ({
      tradeId: r.tradeId, question: r.question.slice(0, 90), pmEntry: r.pmEntry,
      kalshiEntry: r.kalshiEntry, pmPnl: r2(r.pmPnl ?? 0), kalshiPnl: r2(r.kalshiPnl ?? 0), delta: r2(r.delta ?? 0),
    })),
  };

  if (dryRun) {
    console.log(`[dry-run] added=${added} verified=${quoted} unverified=${unverified} failed=${failed} stale=${stale} settled=${settled}`);
    console.log(JSON.stringify(summary.coverage));
    console.log(`[dry-run] det arm: attempted=${summary.deterministic.attempted} resolved=${summary.deterministic.resolved} `
      + `verdicts=${JSON.stringify(summary.deterministic.verdicts)} priced=${summary.deterministic.priced}`);
    console.log(settlementBasisLine(summary.settlementBasis));
    return;
  }
  fs.writeFileSync(LEDGER, rows.map((r) => JSON.stringify(r)).join("\n") + "\n");
  fs.writeFileSync(SUMMARY, JSON.stringify(summary, null, 2));
  console.log(`venue shadow: copies=${rows.length} inWindow=${inWindow.length} verified=${verified.length} `
    + `unverified=${unverifiedRows.length} settled=${bookRows.length}`);
  console.log(`books: PM ${summary.books.pm.pnl >= 0 ? "+" : ""}$${summary.books.pm.pnl} | `
    + `Kalshi ${summary.books.kalshi.pnl >= 0 ? "+" : ""}$${summary.books.kalshi.pnl} | `
    + `delta ${summary.books.delta.pnl >= 0 ? "+" : ""}$${summary.books.delta.pnl}`);
  if (Object.keys(summary.coverage.rejectionReasons).length) {
    console.log(`quoting buckets: ${JSON.stringify(summary.coverage.rejectionReasons)}`);
  }
  const dsum = summary.deterministic;
  console.log(`det arm (contract equivalence): resolved=${dsum.resolved} equiv=${dsum.equiv} `
    + `priced=${dsum.priced} book n=${dsum.book.n} PM $${dsum.book.pmPnl} | DET $${dsum.book.detPnl}`);
  console.log(settlementBasisLine(summary.settlementBasis));
  console.log(`wrote data/kalshi-venue-shadow.jsonl + summary`);
}

main().catch((e) => { console.error(e); process.exit(1); }).finally(() => prisma.$disconnect());
