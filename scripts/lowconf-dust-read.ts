/**
 * lowconf-dust-read — price the minConfidence shadow lane WITHOUT its dust.
 * Read-only. Evidence for the `lowconf-shadow-dust-floor` card (queue item 10).
 *
 * WHY: `summarizeLowConf`'s dust-inclusive headline is dominated by sub-cent entries
 * that are unexecutable at any size on this venue (a $10 ticket at 0.0005 shares pays
 * 20,000x if it wins). The 2026-08-19 tuning read on the DRIFT lane hit the same
 * shape and got a floor (tuning #29 rec 1, DRIFT_DUST_MIN_ENTRY); the minConfidence
 * lane never did, so every read of it since has led with a number that answers
 * "what did lottery tickets pay", not "what would a refused copy have paid".
 *
 * BASIS (stated, never implied):
 *   population = every candidate row in data/lowconf-shadow.jsonl written by
 *                scripts/score-trades.ts when the CONFIDENCE gate refused a copy,
 *                restricted to rows whose market|outcome has a resolve row;
 *   level      = three, always printed together — TICKETS (one per poll row),
 *                COPIES (earliest poll per marketId|outcome|wallet) and BETS
 *                (earliest poll per market);
 *   clock      = decision ts (candidate row), UTC; settlement = the resolve row's
 *                value (0/1) written by mark-shadow-longshot from the venue's own
 *                winning label, never a PnL sign;
 *   price      = currentPrice on the candidate row, the price the copy would have
 *                paid; stake = $10 fixed (the feed's own convention, which booked
 *                nothing, so a constant clip is the only comparable one).
 *
 * Cross-check: the BETS total is recomputed here from the raw jsonl with an
 * independent implementation of the earliest-wins rule and MUST equal
 * `summarizeLowConf().basis.wouldHavePnlOneBetPerMarket` — the script exits 1 if
 * the two bases diverge, so a printed figure cannot drift from the summary JSON.
 *
 *   npx tsx scripts/lowconf-dust-read.ts
 *   LOWCONF_DUST_MIN_ENTRY=0.05 npx tsx scripts/lowconf-dust-read.ts
 */

import { readLowConfRows, summarizeLowConf, LOWCONF_DUST_MIN_ENTRY, LOWCONF_BANNED_TAIL_MAX } from "../src/lib/shadow-lowconf";

const usd = (n: number) => (n < 0 ? "-$" : "$") + Math.abs(n).toFixed(2);
const pct = (n: number) => (n * 100).toFixed(1) + "%";

interface LedgerRow {
  marketId: string;
  pnl: number;
  entry: number;
}

/** Independent re-implementation of the earliest-poll-per-market rule (see cross-check above). */
function marketLedger(rows: Array<Record<string, unknown>>): LedgerRow[] {
  const resolves = new Map<string, number>();
  for (const r of rows) if (r.type === "resolve") resolves.set(`${r.marketId}|${r.outcome}`, Number(r.value));
  const first = new Map<string, { t: number; pnl: number; entry: number }>();
  for (const c of rows) {
    if (c.type !== "candidate") continue;
    const v = resolves.get(`${c.marketId}|${c.outcome}`);
    if (v === undefined) continue;
    const entry = Number(c.currentPrice);
    const stake = Number(c.stakeUsd ?? 10);
    const pnl = entry > 0 ? ((v - entry) / entry) * stake : 0;
    const at = Date.parse(String(c.ts));
    const t = Number.isFinite(at) ? at : Number.POSITIVE_INFINITY;
    const key = String(c.marketId);
    const prev = first.get(key);
    if (prev === undefined || t < prev.t) first.set(key, { t, pnl, entry });
  }
  return [...first.entries()].map(([marketId, r]) => ({ marketId, pnl: r.pnl, entry: r.entry }));
}

function quantile(sorted: number[], q: number): number {
  if (sorted.length === 0) return 0;
  const i = Math.min(sorted.length - 1, Math.max(0, Math.round((sorted.length - 1) * q)));
  return sorted[i];
}

const rows = readLowConfRows();
if (rows.length === 0) {
  console.error("lowconf-dust-read: data/lowconf-shadow.jsonl is empty or unreadable — refusing to print a clean-looking zero.");
  process.exit(1);
}
const s = summarizeLowConf(rows);
const ledger = marketLedger(rows);
const d = s.dust;

const xcheckRaw = Math.round(ledger.reduce((a, r) => a + r.pnl, 0) * 100) / 100;
const xcheckExDust =
  Math.round(ledger.filter((r) => r.entry >= LOWCONF_DUST_MIN_ENTRY).reduce((a, r) => a + r.pnl, 0) * 100) / 100;
if (xcheckRaw !== s.basis.wouldHavePnlOneBetPerMarket || xcheckExDust !== d.wouldHavePnlOneBetPerMarket) {
  console.error(
    `lowconf-dust-read: BASIS DIVERGENCE — independent ledger dust-inclusive ${usd(xcheckRaw)} / ex-dust ${usd(
      xcheckExDust
    )} vs summary ${usd(s.basis.wouldHavePnlOneBetPerMarket)} / ${usd(
      d.wouldHavePnlOneBetPerMarket
    )} on ${ledger.length} markets. Refusing to print either as a read.`
  );
  process.exit(1);
}

const exDust = ledger.filter((r) => r.entry >= LOWCONF_DUST_MIN_ENTRY);
const bannedTail = ledger.filter((r) => r.entry > 0 && r.entry < LOWCONF_BANNED_TAIL_MAX);
const sorted = [...exDust].sort((a, b) => a.pnl - b.pnl);
const pnls = sorted.map((r) => r.pnl);
const sortedDesc = [...exDust].sort((a, b) => b.pnl - a.pnl);
const totalExDust = exDust.reduce((a, r) => a + r.pnl, 0);
const top10 = sortedDesc.slice(0, 10).reduce((a, r) => a + r.pnl, 0);
const trim = 0.05;
const cut = Math.floor(sorted.length * trim);
const trimmed = sorted.slice(cut, sorted.length - cut);
const trimmedMean = trimmed.length ? trimmed.reduce((a, r) => a + r.pnl, 0) / trimmed.length : 0;
const wins = exDust.filter((r) => r.pnl > 0).length;

console.log("lowconf-dust-read — minConfidence reject counterfactual, dust-floored");
console.log(
  `population: ${s.candidates} candidate rows -> ${s.marked} settled-ticket rows, ${s.basis.signals} copy signals, ` +
    `${s.basis.markets} markets; clock ${s.firstCandidateAt} .. ${s.lastCandidateAt} (candidate ts, UTC); stake $${s.stakeUsd}/ticket`
);
console.log(`floor: entry >= $${LOWCONF_DUST_MIN_ENTRY} (drift-feed convention)  |  banned tail (v67, <$${LOWCONF_BANNED_TAIL_MAX}) reported separately`);
console.log("");
console.log("TICKETS (one per poll row — the ticket stream, NOT the book)");
console.log(`  marked rows           ${s.marked}`);
console.log(`  dust-inclusive total  ${usd(s.wouldHavePnl)}   ${s.avgPnlPerTrade === null ? "—" : usd(s.avgPnlPerTrade) + "/row"}`);
console.log(`  rows below floor      ${d.rowsExcluded}  carrying ${usd(d.rowPnlExcluded)}`);
console.log(`  ex-dust total         ${usd(d.wouldHavePnl)}   ${d.avgPnlPerTrade === null ? "—" : usd(d.avgPnlPerTrade) + "/row"} on ${s.marked - d.rowsExcluded} rows`);
console.log("");
console.log("COPIES (earliest poll per market|outcome|wallet — what a refused copy returns)");
console.log(`  signals               ${s.basis.signals} (${d.signalsExcluded} below floor)`);
console.log(`  dust-inclusive        ${usd(s.basis.wouldHavePnlPerSignal)}`);
console.log(`  ex-dust               ${usd(d.wouldHavePnlPerSignal)}`);
console.log("");
console.log("BETS (earliest poll per market — one ticket per market)");
console.log(`  markets               ${s.basis.markets} -> ${exDust.length} ex-dust (${d.marketsExcluded} below floor)`);
console.log(`  dust-inclusive        ${usd(s.basis.wouldHavePnlOneBetPerMarket)}`);
console.log(`  ex-dust total         ${usd(totalExDust)}`);
console.log(`  ex-dust, ex-top-10    ${usd(totalExDust - top10)}`);
console.log(`  mean / median / trimmed(5%) per market: ${usd(totalExDust / exDust.length)} / ${usd(quantile(pnls, 0.5))} / ${usd(trimmedMean)}`);
console.log(`  win rate (pnl>0)      ${pct(exDust.length ? wins / exDust.length : 0)} of ${exDust.length}`);
console.log(`  deciles (p10..p90)    ${[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9].map((q) => usd(quantile(pnls, q))).join(" ")}`);
console.log(
  `  top market            ${sortedDesc[0]?.marketId ?? "—"} ${sortedDesc[0] ? usd(sortedDesc[0].pnl) : ""}` +
    (totalExDust !== 0 && sortedDesc[0] ? ` = ${pct(sortedDesc[0].pnl / totalExDust)} of the ex-dust total` : "")
);
console.log(`  banned tail           ${bannedTail.length} markets, ${usd(bannedTail.reduce((a, r) => a + r.pnl, 0))}`);
console.log("");
console.log(
  `READ: the dust-inclusive headline (${usd(s.wouldHavePnl)} row-level) is not a PnL claim about the gate — ` +
    `${usd(d.rowPnlExcluded)} of it sits on ${d.rowsExcluded} rows priced below $${LOWCONF_DUST_MIN_ENTRY} that no size could have bought. ` +
    `The bet-basis ex-dust figure is ${usd(totalExDust)} across ${exDust.length} markets, ${usd(totalExDust - top10)} without the ten largest.`
);
