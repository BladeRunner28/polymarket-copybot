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

const LEDGER = path.join(process.cwd(), "data", "kalshi-venue-shadow.jsonl");
const SUMMARY = path.join(process.cwd(), "data", "kalshi-venue-shadow-summary.json");
const SIDECAR = process.env.SIDECAR_QUOTE_URL ?? "http://127.0.0.1:3014/quote";
const KALSHI_FEE_RATE = 0.07; // Kalshi schedule; flagged as needing live confirmation (fee audit)
const DEFAULT_MAX_QUOTE_AGE_H = 6;
const BOT = "BANKROLL_200";

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
  tradeId: string; decisionId: string; question: string; outcome: string; side: string;
  openedAt: string; openedMs: number; status: string;
  pmEntry: number; size: number; pmFeeRate: number;
  kalshiResolved: boolean; kalshiEntry: number | null; kalshiError: string | null;
  kalshiTicker: string | null; kalshiTitle: string | null; kalshiScore: number | null;
  verified: boolean; verifyReason: string | null;
  kalshiQuoteAtMs: number | null; stale: boolean; attempts: number;
  firstSeenAtMs: number; lastCheckedAtMs: number;
  won: boolean | null; pmPnl: number | null; kalshiPnl: number | null; delta: number | null;
};

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
        tradeId: t.id, decisionId: t.decisionJournalId, question, outcome: t.outcome, side: t.side,
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
      "win/loss is derived from realizedPnl sign; partial exits and early closes make both legs approximate.",
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
  console.log(`wrote data/kalshi-venue-shadow.jsonl + summary`);
}

main().catch((e) => { console.error(e); process.exit(1); }).finally(() => prisma.$disconnect());
