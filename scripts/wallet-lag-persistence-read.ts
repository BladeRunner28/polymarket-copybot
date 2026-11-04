/**
 * wallet-lag-persistence-read — READ-ONLY. Does a wallet edge survive a DELAYED copy?
 * (roadmap card wallet-lag-persistence-ranker, Lane B measurement. Decision rule is
 * written below BEFORE the first run and is not edited after seeing results.)
 *
 * QUESTION. Every score we rank wallets with is measured on the wallet OWN fill price:
 * ROI, consistency, copyability, win rate. None of them answers the only question that
 * matters when our fill is late, gated or re-priced: does the edge survive the wait?
 * This read prices each tracked wallet copy at 0 / +10m / +30m / +1h from OUR OWN TAPE
 * and asks whether the survival pattern outranks the scores we rank with today.
 *
 * PRICE AT LAG. The tape is every ObservedTrade row we recorded on that (market, token)
 * pair, at any wallet status, demo off (the rows are what OUR recorder saw, not the
 * venue full tape). Lag 0 is the wallet own fill price, which is what our copy pays by
 * construction. Lag L takes the last print at or before t+L, or a print up to 5m after
 * it, and refuses anything more than 20m stale (src/lib/lag-persistence.ts). A leg with
 * no admissible print is EXCLUDED at that lag and counted, never priced from an old one.
 *
 * SETTLEMENT is VENUE TRUTH: CLOB /markets/{conditionId} -> the token whose winner flag
 * is true, matched by NAME against the outcome the wallet bought (identity-normalised).
 * A leg whose stored outcome matches no token on the market is excluded and counted; it
 * is never guessed. Cache: data/lag-persistence-cache.json (one entry per conditionId).
 *
 * MONEY is RETURN ON COST: payout / price - 1. Not edge per share, because edge per
 * share flatters expensive favourites and makes a longshot-heavy wallet look harmless.
 * GROSS of fees, and said so: no single fee law covers this population.
 *
 * BASIS, printed per table: population = ObservedTrade BUY legs, observationOnly=false,
 * isDemo=0, wallet status=track AS OF THIS RUN, conditionId present; clock = the tape and
 * the wallet table as read now (wallet rows are as-of-print snapshots, not as-of-leg);
 * level = leg, wallet-clustered for wallet scores and market-clustered for population
 * means (legs on one market share one settlement, so a row-level CI is too narrow).
 *
 * PRE-REGISTERED DECISION RULE (for the FINDING only — nothing here changes a decision):
 * Rankers are scored on a TIME SPLIT: wallets scored on legs before the cut (>= 10 legs
 * at that lag), evaluated on legs after it. Label = the leg still returns > 0 at +1h.
 *   CLEARS iff AUC(persistence@1h) >= 0.60 with a wallet-clustered CI excluding 0.5, AND
 *          the PAIRED delta against the best stored score has CI lower bound > 0, AND
 *          the two best wallets carry < 50 percent of the positive delta.
 *   REFUTED iff the AUC CI includes 0.5, or any stored score still beats it.
 *   Else INSUFFICIENT. A CLEARED read is still Lane A: adoption needs approval.
 *
 *   npx tsx scripts/wallet-lag-persistence-read.ts
 *   npx tsx scripts/wallet-lag-persistence-read.ts --clob-limit=4000 --workers=6
 *
 * Output: data/wallet-lag-persistence.json. No DB writes, no rule/sizing change.
 */
import { prisma } from "../src/lib/db";
import { auc, clusteredBootstrap, clusteredBootstrapDelta } from "../src/lib/metrics";
import { normalizeOutcomeLabel } from "../src/lib/resolution";
import {
  copyReturnPerDollar,
  LagCell,
  LAGS_MS,
  meanRetAtLag,
  persistenceDelta,
  priceAtLag,
  sortPrints,
  summariseCells,
  TapePrint,
} from "../src/lib/lag-persistence";
import * as fs from "fs";
import { join } from "path";

const ROOT = join(__dirname, "..");
const OUT = join(ROOT, "data", "wallet-lag-persistence.json");
const CACHE = join(ROOT, "data", "lag-persistence-cache.json");
const CLOB = "https://clob.polymarket.com/markets/";
const LAG_1H = 3_600_000;
const argNum = (name: string, dflt: number) => {
  const hit = process.argv.find((a) => a.startsWith(`--${name}=`));
  return hit ? Number(hit.split("=")[1]) : dflt;
};
const CLOB_LIMIT = argNum("clob-limit", 20000);
const WORKERS = argNum("workers", 6);
const MIN_WALLET_LEGS = argNum("min-legs", 10);

type LegRow = {
  id: string;
  walletAddress: string;
  marketId: string;
  outcome: string;
  conditionId: string;
  walletEntryPrice: number | null;
  detectedPrice: number | null;
  ts: number;
};

type WalletRow = {
  address: string;
  globalScore: number;
  roi30d: number;
  consistencyScore: number;
  copyabilityScore: number;
  winRate30d: number;
};

type WinnerInfo = { state: string; winner?: string | null; tokens?: string[] };

const iso = (ms: number) => new Date(ms).toISOString().replace(".000Z", "Z");
const pct = (v: number) => `${(100 * v).toFixed(2)}%`;
const money = (v: number) => `${v >= 0 ? "+" : ""}${v.toFixed(4)}`;

async function loadLegs(): Promise<LegRow[]> {
  const rows = await prisma.$queryRawUnsafe<Array<Record<string, unknown>>>(
    "SELECT o.id, o.walletAddress, o.marketId, o.outcome, o.conditionId, " +
      "o.walletEntryPrice, o.detectedPrice, o.timestamp " +
      "FROM ObservedTrade o JOIN WalletProfile w ON w.address = o.walletAddress " +
      "WHERE w.status = ? AND o.side = ? AND o.isDemo = 0 AND o.observationOnly = 0 " +
      "AND o.conditionId IS NOT NULL AND length(o.conditionId) > 0",
    "track",
    "BUY"
  );
  return rows.map((r) => ({
    id: String(r.id),
    walletAddress: String(r.walletAddress),
    marketId: String(r.marketId),
    outcome: String(r.outcome),
    conditionId: String(r.conditionId),
    walletEntryPrice: r.walletEntryPrice === null ? null : Number(r.walletEntryPrice),
    detectedPrice: r.detectedPrice === null ? null : Number(r.detectedPrice),
    ts: Number(r.timestamp),
  }));
}

async function loadWallets(): Promise<Map<string, WalletRow>> {
  const rows = await prisma.$queryRawUnsafe<Array<Record<string, unknown>>>(
    "SELECT address, globalScore, roi30d, consistencyScore, copyabilityScore, winRate30d " +
      "FROM WalletProfile WHERE status = ?",
    "track"
  );
  const out = new Map<string, WalletRow>();
  for (const r of rows) {
    out.set(String(r.address), {
      address: String(r.address),
      globalScore: Number(r.globalScore),
      roi30d: Number(r.roi30d),
      consistencyScore: Number(r.consistencyScore),
      copyabilityScore: Number(r.copyabilityScore),
      winRate30d: Number(r.winRate30d),
    });
  }
  return out;
}

/** The print tape, per (marketId, token identity) — every row we recorded, demo off. */
async function loadTape(markets: string[]): Promise<Map<string, TapePrint[]>> {
  const by = new Map<string, TapePrint[]>();
  const CHUNK = 400;
  for (let i = 0; i < markets.length; i += CHUNK) {
    const batch = markets.slice(i, i + CHUNK);
    const ph = batch.map(() => "?").join(",");
    const rows = await prisma.$queryRawUnsafe<Array<Record<string, unknown>>>(
      `SELECT marketId, outcome, timestamp, walletEntryPrice, detectedPrice FROM ObservedTrade`
      + ` WHERE isDemo = 0 AND marketId IN (${ph})`,
      ...batch
    );
    for (const r of rows) {
      const price = r.walletEntryPrice === null ? Number(r.detectedPrice) : Number(r.walletEntryPrice);
      if (!Number.isFinite(price)) continue;
      const key = `${String(r.marketId)}|${normalizeOutcomeLabel(String(r.outcome))}`;
      const list = by.get(key) ?? [];
      list.push({ ts: Number(r.timestamp), price });
      by.set(key, list);
    }
    process.stdout.write(`\r  tape: ${Math.min(i + CHUNK, markets.length)}/${markets.length} markets`);
  }
  process.stdout.write("\n");
  for (const [k, v] of by) by.set(k, sortPrints(v));
  return by;
}

function loadCache(): Record<string, WinnerInfo> {
  try {
    return JSON.parse(fs.readFileSync(CACHE, "utf8")) as Record<string, WinnerInfo>;
  } catch {
    return {};
  }
}

/**
 * Venue truth, never a proxy: the token whose winner flag is true, plus the token NAMES
 * so a label that matches no token can be excluded rather than scored as a loss.
 * "not_closed_yet" is re-fetched on the next run (a market can still settle); resolved
 * and closed-without-winner entries are cached, because neither can change.
 */
async function fetchWinnerOnce(cid: string): Promise<WinnerInfo> {
  try {
    const res = await fetch(`${CLOB}${cid}`, {
      headers: { accept: "application/json", "user-agent": "copybot-research/0.1 (paper-trading-only)" },
      signal: AbortSignal.timeout(20000),
    });
    if (!res.ok) return { state: `http_${res.status}` };
    const m = (await res.json()) as { closed?: boolean; tokens?: Array<{ outcome?: string; winner?: boolean }> };
    const toks = m.tokens ?? [];
    const names = toks.map((t) => String(t.outcome ?? ""));
    const win = toks.find((t) => t.winner === true);
    if (win && win.outcome) return { state: "resolved", winner: String(win.outcome), tokens: names };
    return { state: m.closed === false ? "not_closed_yet" : "closed_without_winner", tokens: names };
  } catch (e) {
    const name = e instanceof Error ? e.name : "error";
    return { state: `fetch_${name}` };
  }
}

/** 429 and transport blips are RETRIED, never cached: a rate-limited read is not a verdict. */
const RETRYABLE = new Set([
  "http_429", "http_502", "http_503", "http_504", "http_500",
  "fetch_error", "fetch_TimeoutError", "fetch_AbortError", "fetch_DOMException",
]);

async function fetchWinner(cid: string): Promise<WinnerInfo> {
  let last: WinnerInfo = { state: "fetch_error" };
  for (let attempt = 0; attempt < 5; attempt++) {
    last = await fetchWinnerOnce(cid);
    if (!RETRYABLE.has(last.state)) return last;
    await new Promise((r) => setTimeout(r, 400 * 2 ** attempt));
  }
  return last;
}

/**
 * Only stable states are cached: resolved and closed-without-winner cannot change,
 * while not_closed_yet must be re-asked and a 429 must never be remembered as an answer.
 */
async function resolveAll(cids: string[]): Promise<Record<string, WinnerInfo>> {
  const cache = loadCache();
  const stable = (s: string | undefined) => s === "resolved" || s === "closed_without_winner";
  const pending = cids.filter((c) => !cache[c] || !stable(cache[c].state));
  console.log(`  settlement: ${cids.length} markets, ${cids.length - pending.length} cached, fetching ${pending.length} at ${WORKERS} workers`);
  let done = 0;
  let failures = 0;
  const run = async (list: string[]) => {
    let cursor = 0;
    const worker = async () => {
      for (;;) {
        const i = cursor++;
        if (i >= list.length) return;
        const cid = list[i];
        const info = await fetchWinner(cid);
        if (stable(info.state)) {
          cache[cid] = info;
        } else {
          failures += 1;
          if (!cache[cid]) cache[cid] = info;
        }
        done += 1;
        if (done % 250 === 0) process.stdout.write(`\r  settlement: ${done}/${list.length}`);
      }
    };
    await Promise.all(Array.from({ length: Math.max(1, WORKERS) }, () => worker()));
  };
  await run(pending);
  process.stdout.write(`\r  settlement: ${done}/${pending.length}\\n`);
  if (failures > 0) console.log(`  settlement: ${failures} markets did not reach a stable state this run (retried inside the fetch)`);
  try {
    fs.writeFileSync(CACHE, JSON.stringify(cache));
  } catch (e) {
    console.log(`  !! cache write failed: ${String(e)}`);
  }
  return cache;
}


type LegResult = {
  wallet: string;
  marketId: string;
  ts: number;
  payout: number;
  entryPrice: number;
  rets: Map<number, number | null>;
  bases: Map<number, string>;
};

function mean(xs: readonly number[]): number {
  return xs.reduce((a, b) => a + b, 0) / xs.length;
}

function median(xs: readonly number[]): number {
  const s = xs.slice().sort((a, b) => a - b);
  const n = s.length;
  return n % 2 === 1 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2;
}

/** Hanley-McNeil AUC standard error at A = 0.5, the same helper the wallet-score read uses. */
function aucHalfMde(nPos: number, nNeg: number): number {
  if (nPos <= 0 || nNeg <= 0) return Number.NaN;
  return 1.96 * Math.sqrt((nPos + nNeg + 1) / (12 * nPos * nNeg));
}

async function main() {
  const started = Date.now();
  const legs = await loadLegs();
  const markets = [...new Set(legs.map((l) => l.marketId))];
  const walletCount = new Set(legs.map((l) => l.walletAddress)).size;
  console.log("POPULATION: ObservedTrade side=BUY, observationOnly=false, isDemo=0, wallet status=track as of this run,");
  console.log(`            conditionId present. ${legs.length} legs / ${markets.length} markets / ${walletCount} wallets.`);
  console.log(`CLOCK: leg timestamps ${iso(Math.min(...legs.map((l) => l.ts)))} .. ${iso(Math.max(...legs.map((l) => l.ts)))}; read at ${iso(started)}.`);
  console.log("LEVEL: leg. Population means are market-clustered, wallet lines wallet-clustered. Money is RETURN ON COST, gross of fees.");

  const tape = await loadTape(markets);
  const walletTable = await loadWallets();
  const cids = [...new Set(legs.map((l) => l.conditionId))];
  const winners = await resolveAll(cids);

  const labelStates = new Map<string, number>();
  const bump = (k: string) => labelStates.set(k, (labelStates.get(k) ?? 0) + 1);
  const basisCounts = new Map<string, number>();
  const unpriced = new Map<number, number>();
  const results: LegResult[] = [];

  for (const leg of legs) {
    const info = winners[leg.conditionId];
    const st = info?.state ?? "uncached";
    if (st !== "resolved") {
      bump(st);
      continue;
    }
    const want = normalizeOutcomeLabel(leg.outcome);
    const names = (info.tokens ?? []).map((t) => normalizeOutcomeLabel(t)).filter((t) => t !== "");
    if (want === "" || !names.includes(want)) {
      bump("outcome_name_not_in_tokens");
      continue;
    }
    bump("resolved_labelled");
    const payout = normalizeOutcomeLabel(info.winner) === want ? 1 : 0;
    const entry = leg.walletEntryPrice ?? leg.detectedPrice;
    const rets = new Map<number, number | null>();
    const bases = new Map<number, string>();
    rets.set(0, entry === null ? null : copyReturnPerDollar(payout, entry));
    bases.set(0, "own_fill");
    const prints = tape.get(`${leg.marketId}|${want}`) ?? [];
    for (const lag of LAGS_MS) {
      if (lag === 0) continue;
      const p = priceAtLag(prints, leg.ts, lag);
      if (!p) {
        rets.set(lag, null);
        bases.set(lag, "no_admissible_print");
        unpriced.set(lag, (unpriced.get(lag) ?? 0) + 1);
        continue;
      }
      bases.set(lag, p.basis);
      basisCounts.set(p.basis, (basisCounts.get(p.basis) ?? 0) + 1);
      rets.set(lag, copyReturnPerDollar(payout, p.price));
    }
    results.push({ wallet: leg.walletAddress, marketId: leg.marketId, ts: leg.ts, payout, entryPrice: entry ?? 0, rets, bases });
  }

  console.log(`\\nLABELLING: ${JSON.stringify(Object.fromEntries(labelStates))}`);
  console.log(`PRINT BASIS (lag > 0): ${JSON.stringify(Object.fromEntries(basisCounts))}; no admissible print: ${JSON.stringify(Object.fromEntries(unpriced))}`);
  if (results.length === 0) await shutdown("no labelled legs", 1);
  const labelledShare = results.length / Math.max(1, legs.length);
  const coverageOk = labelledShare >= 0.9;
  if (!coverageOk) {
    console.log(`  !! COVERAGE FAIL: ${pct(labelledShare)} of legs carry a venue label (${results.length}/${legs.length}) - the subset is not a sample of the population, so the verdict is forced to INSUFFICIENT.`);
  }

  const marketCluster = (r: LegResult) => r.marketId;
  const walletCluster = (r: LegResult) => r.wallet;
  const retAt = (r: LegResult, lag: number) => r.rets.get(lag) as number;

  const tableRows: Array<Record<string, unknown>> = [];
  console.log("\\n=== POPULATION: counterfactual copy return per $1 staked, by lag ===");
  console.log("   lag     priced   excluded   meanRet      median    winRate   market-clustered 95% CI   ex-top-10-mkt");
  for (const lag of LAGS_MS) {
    const rows = results.filter((r) => r.rets.get(lag) !== null);
    const nExcluded = results.length - rows.length;
    if (rows.length === 0) {
      console.log(`  ${String(lag / 60000).padStart(4)}m  ${"0".padStart(7)}  ${String(nExcluded).padStart(9)}   (nothing priced)`);
      tableRows.push({ lagMs: lag, n: 0, excluded: nExcluded });
      continue;
    }
    const rets = rows.map((r) => retAt(r, lag));
    const ci = clusteredBootstrap(rows, marketCluster, (s) => mean(s.map((r) => retAt(r, lag))));
    const byMarket = new Map<string, number[]>();
    for (const r of rows) {
      const list = byMarket.get(r.marketId) ?? [];
      list.push(retAt(r, lag));
      byMarket.set(r.marketId, list);
    }
    const ordered = [...byMarket.values()].map((v) => mean(v)).sort((a, b) => b - a);
    const exTop = ordered.length > 10 ? mean(ordered.slice(10)) : null;
    console.log(`  ${String(lag / 60000).padStart(4)}m  ${String(rows.length).padStart(7)}  ${String(nExcluded).padStart(9)}   ${money(mean(rets)).padStart(9)}   ${money(median(rets)).padStart(9)}   ${pct(rets.filter((x) => x > 0).length / rets.length).padStart(7)}   [${money(ci.low)}, ${money(ci.high)}]   ${exTop === null ? "na" : money(exTop)}`);
    tableRows.push({
      lagMs: lag, n: rows.length, excluded: nExcluded,
      meanRet: Number(mean(rets).toFixed(6)), medianRet: Number(median(rets).toFixed(6)),
      winRate: Number((rets.filter((x) => x > 0).length / rets.length).toFixed(6)),
      ci95: [Number(ci.low.toFixed(6)), Number(ci.high.toFixed(6))],
      exTop10MarketsMeanRet: exTop === null ? null : Number(exTop.toFixed(6)),
      markets: byMarket.size,
    });
  }

  // MATCHED PANEL: one population priced at every lag, so the decay is not a change of sample.
  const panel = results.filter((r) => LAGS_MS.every((lag) => r.rets.get(lag) !== null));
  console.log(`\\n=== MATCHED PANEL (same legs at every lag): ${panel.length} legs, ${new Set(panel.map((r) => r.marketId)).size} markets, ${new Set(panel.map((r) => r.wallet)).size} wallets ===`);
  const panelRows: Array<Record<string, unknown>> = [];
  if (panel.length > 0) {
    for (const lag of LAGS_MS) {
      const rets = panel.map((r) => retAt(r, lag));
      const ci = clusteredBootstrap(panel, marketCluster, (s) => mean(s.map((r) => retAt(r, lag))));
      const at0 = mean(panel.map((r) => retAt(r, 0)));
      const drop = mean(rets) - at0;
      const byMarket = new Map<string, number[]>();
      for (const r of panel) {
        const list = byMarket.get(r.marketId) ?? [];
        list.push(retAt(r, lag));
        byMarket.set(r.marketId, list);
      }
      const ordered = [...byMarket.values()].map((v) => mean(v)).sort((a, b) => b - a);
      const exTop = ordered.length > 10 ? mean(ordered.slice(10)) : null;
      // The PAIRED difference is what the decay question actually asks, and it is far
      // better estimated than either level: same legs, same settlements, one price changed.
      const dci = clusteredBootstrap(panel, marketCluster, (s) => mean(s.map((r) => retAt(r, lag) - retAt(r, 0))));
      console.log(`  ${String(lag / 60000).padStart(4)}m  meanRet ${money(mean(rets))}  CI [${money(ci.low)}, ${money(ci.high)}]  vs 0-lag ${money(drop)} (paired CI [${money(dci.low)}, ${money(dci.high)}])  win ${pct(rets.filter((x) => x > 0).length / rets.length)}  ex-top-10-mkt ${exTop === null ? "na" : money(exTop)}`);
      panelRows.push({
        lagMs: lag, n: panel.length,
        meanRet: Number(mean(rets).toFixed(6)),
        ci95: [Number(ci.low.toFixed(6)), Number(ci.high.toFixed(6))],
        dropVsLag0: Number(drop.toFixed(6)),
        dropVsLag0Ci95: [Number(dci.low.toFixed(6)), Number(dci.high.toFixed(6))],
        winRate: Number((rets.filter((x) => x > 0).length / rets.length).toFixed(6)),
        exTop10MarketsMeanRet: exTop === null ? null : Number(exTop.toFixed(6)),
      });
    }
  }

  // WALLET CONCENTRATION: on this tape a population mean is dominated by a few wallets,
  // so the same move is ALSO printed with the largest contributor removed. A lag effect
  // that only exists with one wallet in the sample is not a lag effect.
  let walletSensitivity: Record<string, unknown> | null = null;
  const panelByWallet = new Map<string, LegResult[]>();
  for (const r of panel) {
    const list = panelByWallet.get(r.wallet) ?? [];
    list.push(r);
    panelByWallet.set(r.wallet, list);
  }
  if (panel.length > 0 && panelByWallet.size > 1) {
    const contrib = [...panelByWallet.entries()]
      .map(([wallet, list]) => ({
        wallet,
        n: list.length,
        mean0: mean(list.map((r) => retAt(r, 0))),
        mean1h: mean(list.map((r) => retAt(r, LAG_1H))),
      }))
      .sort((a, b) => Math.abs(b.n * (b.mean1h - b.mean0)) - Math.abs(a.n * (a.mean1h - a.mean0)));
    const top = contrib[0];
    const rest = panel.filter((r) => r.wallet !== top.wallet);
    const allMove = mean(panel.map((r) => retAt(r, LAG_1H))) - mean(panel.map((r) => retAt(r, 0)));
    const restMove = rest.length > 0 ? mean(rest.map((r) => retAt(r, LAG_1H))) - mean(rest.map((r) => retAt(r, 0))) : null;
    console.log(`  WALLET CONCENTRATION: largest 0->1h contributor is ${top.wallet.slice(0, 10)} (${top.n}/${panel.length} legs, ${pct(top.n / panel.length)}): mean@0 ${money(top.mean0)} -> @1h ${money(top.mean1h)}`);
    console.log(`                        full panel move ${money(allMove)}; without that wallet ${restMove === null ? "na" : money(restMove)}`);
    walletSensitivity = {
      topContributor: top.wallet,
      topContributorLegs: top.n,
      topContributorShareOfPanel: Number((top.n / panel.length).toFixed(4)),
      fullPanelMove0to1h: Number(allMove.toFixed(6)),
      moveWithoutTopContributor: restMove === null ? null : Number(restMove.toFixed(6)),
      walletsInPanel: panelByWallet.size,
    };
  }

  const flat: Array<{ wallet: string; lagMs: number; ret: number | null }> = [];
  for (const r of results) for (const lag of LAGS_MS) flat.push({ wallet: r.wallet, lagMs: lag, ret: r.rets.get(lag) ?? null });
  const cells = summariseCells(flat);
  const cellAt = (w: string, lag: number): LagCell | undefined => cells.get(w)?.get(lag);

  type WalletLine = { wallet: string; n: number; ret0: number; ret10: number | null; ret30: number | null; ret1h: number; delta1h: number | null; };
  const lines: WalletLine[] = [];
  for (const [wallet, byLag] of cells) {
    const c0 = byLag.get(0);
    const c1 = byLag.get(LAG_1H);
    if (!c0 || !c1) continue;
    if (c0.n < MIN_WALLET_LEGS) continue;
    lines.push({
      wallet,
      n: c0.n,
      ret0: c0.meanRet,
      ret10: cellAt(wallet, 600_000)?.meanRet ?? null,
      ret30: cellAt(wallet, 1_800_000)?.meanRet ?? null,
      ret1h: c1.meanRet,
      delta1h: persistenceDelta(cells, wallet, 0, LAG_1H),
    });
  }
  lines.sort((a, b) => b.ret1h - a.ret1h);
  console.log(`\\n=== PER WALLET, return per $1 staked (wallets with >= ${MIN_WALLET_LEGS} priced legs at lag 0) ===`);
  console.log("   wallet        n     0-lag    +10m    +30m     +1h   drop(0->1h)   survives@1h");
  for (const l of lines) {
    const f = (v: number | null) => (v === null ? "   na " : money(v).padStart(8));
    console.log(`  ${l.wallet.slice(0, 10)}  ${String(l.n).padStart(5)}  ${f(l.ret0)} ${f(l.ret10)} ${f(l.ret30)} ${f(l.ret1h)}   ${f(l.delta1h)}        ${l.ret1h > 0 ? "yes" : "NO"}`);
  }
  const survivors = lines.filter((l) => l.ret1h > 0).length;
  console.log(`  wallets still positive at +1h: ${survivors}/${lines.length}`);

  const positiveDeltas = lines.map((l) => l.delta1h).filter((d): d is number => d !== null && d < 0).map((d) => -d).sort((a, b) => b - a);
  const deltaSum = positiveDeltas.reduce((a, b) => a + b, 0);
  const top2Share = deltaSum > 0 ? (positiveDeltas[0] + (positiveDeltas[1] ?? 0)) / deltaSum : null;
  console.log(`  decay concentration: top-2 wallets carry ${top2Share === null ? "na" : pct(top2Share)} of the total 0->1h decay`);

  // --- HOLD-OUT RANKER COMPARISON ---------------------------------------------
  const priced = results.filter((r) => r.rets.get(LAG_1H) !== null).sort((a, b) => a.ts - b.ts);
  let comparison: Record<string, unknown> | null = null;
  if (priced.length >= 200) {
    const cut = priced[Math.floor(priced.length / 2)].ts;
    const scoreLegs = priced.filter((r) => r.ts < cut);
    const evalLegs = priced.filter((r) => r.ts >= cut);
    const scoreByWallet = new Map<string, LegResult[]>();
    for (const r of scoreLegs) {
      const list = scoreByWallet.get(r.wallet) ?? [];
      list.push(r);
      scoreByWallet.set(r.wallet, list);
    }
    const persist1h = new Map<string, number>();
    const persist0 = new Map<string, number>();
    for (const [w, list] of scoreByWallet) {
      const p1 = list.filter((r) => r.rets.get(LAG_1H) !== null);
      if (p1.length < MIN_WALLET_LEGS) continue;
      persist1h.set(w, mean(p1.map((r) => retAt(r, LAG_1H))));
      persist0.set(w, mean(p1.map((r) => retAt(r, 0))));
    }
    const evalRows = evalLegs.filter((r) => persist1h.has(r.wallet));
    const yWin = evalRows.map((r) => r.payout);
    const yProf = evalRows.map((r) => (retAt(r, LAG_1H) > 0 ? 1 : 0));
    const nPos = yWin.filter((y) => y === 1).length;
    type Ranker = { name: string; score: (r: LegResult) => number };
    const rankers: Ranker[] = [
      { name: "persistence@1h", score: (r) => persist1h.get(r.wallet) ?? Number.NaN },
      { name: "persistence@0", score: (r) => persist0.get(r.wallet) ?? Number.NaN },
      { name: "globalScore", score: (r) => walletTable.get(r.wallet)?.globalScore ?? Number.NaN },
      { name: "roi30d", score: (r) => walletTable.get(r.wallet)?.roi30d ?? Number.NaN },
      { name: "consistencyScore", score: (r) => walletTable.get(r.wallet)?.consistencyScore ?? Number.NaN },
      { name: "copyabilityScore", score: (r) => walletTable.get(r.wallet)?.copyabilityScore ?? Number.NaN },
      { name: "winRate30d", score: (r) => walletTable.get(r.wallet)?.winRate30d ?? Number.NaN },
      { name: "entryPrice", score: (r) => r.entryPrice },
    ];
    console.log(`\\n=== HOLD-OUT RANKER COMPARISON ===`);
    console.log(`  time split at ${iso(cut)}: scored on ${scoreLegs.length} legs, evaluated on ${evalRows.length} legs / ${new Set(evalRows.map((r) => r.wallet)).size} wallets / ${new Set(evalRows.map((r) => r.marketId)).size} markets`);
    console.log(`  label A = settled WIN (payout 1): ${nPos}/${evalRows.length} = ${pct(nPos / Math.max(1, evalRows.length))}; leg-level MDE at AUC 0.5 (optimistic, ignores clustering) ${aucHalfMde(nPos, evalRows.length - nPos).toFixed(3)}`);
    console.log("   ranker              AUC(win)  wallet-clustered CI     AUC(profitable@1h)");
    const ranked: Array<{ name: string; aucWin: number; lo: number; hi: number; aucProf: number }> = [];
    for (const rk of rankers) {
      const s = evalRows.map(rk.score);
      const ok = s.every((v) => Number.isFinite(v));
      if (!ok) {
        console.log(`  ${rk.name.padEnd(18)}  (a wallet on the eval side has no stored score - skipped)`);
        continue;
      }
      const aWin = auc(s, yWin);
      const ci = clusteredBootstrap(evalRows, walletCluster, (sample) => auc(sample.map(rk.score), sample.map((r) => r.payout)));
      const aProf = auc(s, yProf);
      console.log(`  ${rk.name.padEnd(18)}  ${aWin.toFixed(3)}     [${ci.low.toFixed(3)}, ${ci.high.toFixed(3)}]              ${aProf.toFixed(3)}`);
      ranked.push({ name: rk.name, aucWin: aWin, lo: ci.low, hi: ci.high, aucProf: aProf });
    }

    const persist = rankers[0];
    const persistAuc = ranked.find((r) => r.name === "persistence@1h");
    const storedNames = ["globalScore", "roi30d", "consistencyScore", "copyabilityScore", "winRate30d"];
    const storedRanked = ranked.filter((r) => storedNames.includes(r.name));
    const bestStored = storedRanked.length > 0 ? storedRanked.reduce((a, b) => (b.aucWin > a.aucWin ? b : a)) : null;
    const deltas: Array<Record<string, unknown>> = [];
    for (const rk of rankers.slice(1)) {
      const sA = evalRows.map(persist.score);
      const sB = evalRows.map(rk.score);
      if (!sB.every((v) => Number.isFinite(v))) continue;
      const d = clusteredBootstrapDelta(
        evalRows,
        walletCluster,
        (sample) => auc(sample.map(persist.score), sample.map((r) => r.payout)),
        (sample) => auc(sample.map(rk.score), sample.map((r) => r.payout))
      );
      console.log(`  paired delta AUC(persistence@1h - ${rk.name.padEnd(16)}) = ${d.point >= 0 ? "+" : ""}${d.point.toFixed(4)}  CI [${d.low.toFixed(4)}, ${d.high.toFixed(4)}]  P(persistence better) = ${(100 * d.pGreater).toFixed(1)}%`);
      deltas.push({ vs: rk.name, delta: Number(d.point.toFixed(4)), ci95: [Number(d.low.toFixed(4)), Number(d.high.toFixed(4))], pGreater: Number(d.pGreater.toFixed(4)) });
    }

    // --- PRE-REGISTERED VERDICT ---------------------------------------------
    const reasons: string[] = [];
    let verdict: string;
    const aucOk = persistAuc !== undefined && Number.isFinite(persistAuc.aucWin) && persistAuc.aucWin >= 0.6 && persistAuc.lo > 0.5;
    const bestDelta = deltas.find((d) => d.vs === (bestStored ? bestStored.name : ""));
    const beatsBest = bestStored === null ? null : Number(bestDelta ? (bestDelta.ci95 as number[])[0] : Number.NaN) > 0;
    const twoWalletOk = top2Share !== null && top2Share < 0.5;
    if (!aucOk) reasons.push(`persistence AUC(win) ${persistAuc ? persistAuc.aucWin.toFixed(3) : "na"} does not clear 0.60 with a CI above 0.5`);
    if (beatsBest !== true) reasons.push(`it does not beat the best stored score (${bestStored ? bestStored.name : "na"} ${bestStored ? bestStored.aucWin.toFixed(3) : "na"}) with a paired CI above zero`);
    if (!twoWalletOk) reasons.push(`the 0->1h decay is concentrated: top-2 wallets carry ${top2Share === null ? "na" : pct(top2Share)}`);
    const evalWallets = new Set(evalRows.map((r) => r.wallet)).size;
    if (!coverageOk) {
      verdict = "INSUFFICIENT";
      reasons.unshift(`coverage: only ${pct(labelledShare)} of legs carry a venue settlement label, so no population statement is safe`);
    } else if (aucOk && beatsBest === true && twoWalletOk && evalWallets >= 5) {
      verdict = "CLEARS";
    } else if (!aucOk || beatsBest === false) {
      verdict = "REFUTED";
    } else {
      verdict = "INSUFFICIENT";
    }
    if (evalWallets < 5) reasons.push(`only ${evalWallets} wallets on the evaluation side - a wallet-level AUC cannot be read from that`);
    console.log(`\\n  VERDICT: ${verdict}`);
    for (const r of reasons) console.log(`    - ${r}`);
    console.log("  NOTE: a CLEARED read is still Lane A. Adopting persistence as a ranker changes what the bot copies.");
    comparison = {
      cut: iso(cut), scoreLegs: scoreLegs.length, evalLegs: evalRows.length,
      evalWallets: new Set(evalRows.map((r) => r.wallet)).size,
      evalMarkets: new Set(evalRows.map((r) => r.marketId)).size,
      labelWinShare: Number((nPos / Math.max(1, evalRows.length)).toFixed(4)),
      legLevelMdeAuc: Number(aucHalfMde(nPos, evalRows.length - nPos).toFixed(4)),
      rankers: ranked.map((r) => ({ name: r.name, aucWin: Number(r.aucWin.toFixed(4)), ci95: [Number(r.lo.toFixed(4)), Number(r.hi.toFixed(4))], aucProfitableAt1h: Number(r.aucProf.toFixed(4)) })),
      pairedDeltas: deltas,
      top2WalletShareOfDecay: top2Share === null ? null : Number(top2Share.toFixed(4)),
      verdict, reasons,
    };
  } else {
    console.log(`\\n  HOLD-OUT COMPARISON SKIPPED: only ${priced.length} legs carry a +1h price (need 200).`);
  }

  const out = {
    builtAt: new Date(started).toISOString(),
    readOnly: true,
    basis: {
      population: "ObservedTrade side=BUY, observationOnly=false, isDemo=0, wallet status=track as of this run, conditionId present",
      clock: `leg timestamps ${iso(Math.min(...legs.map((l) => l.ts)))} .. ${iso(Math.max(...legs.map((l) => l.ts)))} (tape and wallet rows as read at run time)`,
      level: "leg; population means market-clustered, wallet lines wallet-clustered",
      money: "return on cost, payout/price - 1, GROSS of fees",
      settlement: "venue truth: CLOB /markets/{conditionId} -> token whose winner flag is true, matched by normalised outcome NAME",
    },
    legs: legs.length, markets: markets.length, wallets: walletCount,
    labelled: results.length,
    labelStates: Object.fromEntries(labelStates),
    printBasis: Object.fromEntries(basisCounts),
    unpricedByLag: Object.fromEntries(unpriced),
    populationByLag: tableRows,
    matchedPanel: { legs: panel.length, rows: panelRows, walletSensitivity },
    perWallet: lines.map((l) => ({
      wallet: l.wallet, n: l.n, ret0: Number(l.ret0.toFixed(4)),
      ret10: l.ret10 === null ? null : Number(l.ret10.toFixed(4)),
      ret30: l.ret30 === null ? null : Number(l.ret30.toFixed(4)),
      ret1h: Number(l.ret1h.toFixed(4)),
      drop0to1h: l.delta1h === null ? null : Number(l.delta1h.toFixed(4)),
      survives1h: l.ret1h > 0,
    })),
    walletsPositiveAt1h: survivors,
    comparison,
  };
  fs.writeFileSync(OUT, JSON.stringify(out, null, 2));
  console.log(`\\nwrote ${OUT} in ${((Date.now() - started) / 1000).toFixed(0)}s`);
}

async function shutdown(msg: string, code: number): Promise<never> {
  console.log(msg);
  await prisma.$disconnect();
  process.exit(code);
}

main()
  .then(async () => {
    await prisma.$disconnect();
  })
  .catch(async (e) => {
    console.error(e);
    await prisma.$disconnect();
    process.exit(1);
  });
