/**
 * Data API v1 <-> v2 DUAL READ — the migration gate.
 *
 * Runs the SAME adapter calls twice, flipping DATA_API_VERSION between them, and
 * diffs what the bot would actually see: wallet sets, ranks, realized-PnL sums,
 * row counts, and per-row values of every field scoring consumes.
 *
 * WHY: v1 is retired 2026-10-24. The parity probe (2026-10-17) proved the VALUES are
 * identical on 5 rows; this proves the ADAPTER returns them identically across a
 * real wallet sample. The default stays v1 until this passes.
 *
 * Run: API_DELAY_MS=0 npx tsx scripts/data-api-v2-dual-read.ts --wallets 6 --top 60
 */
import { writeFileSync } from "node:fs";
import { PolymarketAdapter } from "../src/lib/adapters/polymarket";

type Ver = "v1" | "v2";

function arg(name: string, dflt: number): number {
  const i = process.argv.indexOf(`--${name}`);
  if (i === -1) return dflt;
  const n = Number(process.argv[i + 1]);
  return Number.isFinite(n) ? n : dflt;
}

function setVer(v: Ver) {
  process.env.DATA_API_VERSION = v;
}

const round = (n: number | undefined) => (n === undefined ? undefined : Math.round(n * 1e6) / 1e6);

/** Numeric tolerance for float formatting differences only (v1 `10` vs v2 `10.0`). */
function close(a: number | undefined, b: number | undefined): boolean {
  if (a === undefined && b === undefined) return true;
  if (a === undefined || b === undefined) return false;
  return Math.abs(a - b) <= 1e-6;
}

function pct(a: number, b: number): string {
  if (b === 0) return a === 0 ? "n/a" : "n/a (v1 empty)";
  return `${(((a - b) / b) * 100).toFixed(2)}%`;
}

async function main() {
  const adapter = new PolymarketAdapter();
  const topN = arg("top", 60);
  const nWallets = arg("wallets", 6);
  const failures: string[] = [];

  // ---------- 1. leaderboard ----------
  setVer("v1");
  const lb1 = await adapter.fetchLeaderboard(topN);
  setVer("v2");
  const lb2 = await adapter.fetchLeaderboard(topN);

  const set1 = new Set(lb1.map((e) => e.address));
  const set2 = new Set(lb2.map((e) => e.address));
  const only1 = [...set1].filter((a) => !set2.has(a));
  const only2 = [...set2].filter((a) => !set1.has(a));
  const pnl1 = lb1.reduce((s, e) => s + (e.pnl ?? 0), 0);
  const pnl2 = lb2.reduce((s, e) => s + (e.pnl ?? 0), 0);
  const rankMismatch = lb1.filter((e, i) => lb2[i] && lb2[i].rank !== e.rank).length;

  console.log("=== LEADERBOARD ===");
  console.log(`  v1 rows ${lb1.length} | v2 rows ${lb2.length}`);
  console.log(`  wallet sets: only-v1 ${only1.length}, only-v2 ${only2.length}`);
  console.log(`  pnl sum: v1 ${round(pnl1)} | v2 ${round(pnl2)} | delta ${round(pnl2 - pnl1)}`);
  console.log(`  rank mismatches at same index: ${rankMismatch}`);
  if (only1.length || only2.length) failures.push(`leaderboard wallet set differs (${only1.length}/${only2.length})`);
  if (!close(round(pnl1), round(pnl2))) failures.push(`leaderboard pnl sum differs`);
  if (lb1.length !== lb2.length) failures.push(`leaderboard row count differs`);

  // ---------- 2. wallet profiling reads ----------
  const sample = [...set2].slice(0, nWallets);
  console.log(`\n=== WALLET PROFILING (${sample.length} wallets, 30d) ===`);
  const perWallet: Record<string, unknown>[] = [];

  for (const address of sample) {
    try {
      setVer("v1");
      const a1 = await adapter.fetchWalletActivity(address, 30);
      setVer("v2");
      const a2 = await adapter.fetchWalletActivity(address, 30);

      const sum = (xs: typeof a1, f: (x: (typeof a1)[number]) => number | undefined) =>
        xs.reduce((s, x) => s + (f(x) ?? 0), 0);
      const pnlA = sum(a1, (x) => x.pnl);
      const pnlB = sum(a2, (x) => x.pnl);
      const szA = sum(a1, (x) => x.size);
      const szB = sum(a2, (x) => x.size);

      // Identity is the POSITION (condition + outcome + side), never its price:
      // v1 and v2 aggregate the same position to slightly different averages, so
      // folding price into the key would report drift as a missing row.
      // v2 STRIPS PUNCTUATION from outcome names: v1 "Anyone's Legend" arrives as
      // v2 "Anyones Legend". Anything keyed on (wallet, market, outcome) therefore
      // breaks across the cutover -- recorded as a migration hazard, and normalised
      // here so verification does not report one row twice.
      const norm = (s: unknown) => String(s ?? "").toUpperCase().replace(/[^A-Z0-9]/g, "");
      const key = (x: (typeof a1)[number]) => `${x.conditionId ?? x.marketId}|${norm(x.outcome)}|${x.side}`;
      // v2 can return the SAME position twice: the closed record plus a residual
      // OPEN dust row. Dedupe before matching, or those duplicates look like
      // missing rows on the other side (measured: 21 on 0x111f73e9).
      const dedupe = (xs: typeof a1) => {
        const m = new Map<string, (typeof a1)[number]>();
        for (const x of xs) if (!m.has(key(x))) m.set(key(x), x);
        return m;
      };
      const m1 = dedupe(a1);
      const m2 = dedupe(a2);
      const dupV1 = a1.length - m1.size;
      const dupV2 = a2.length - m2.size;
      const match = [...m1.keys()].filter((k) => m2.has(k)).length;
      // A v2-only row with no pnl and a sub-dollar basis is the residue of a
      // position v2 keeps OPEN after v1 has closed it (measured: 0.0893 and 0.1108
      // shares on 0x7c37b52e). Economically nil, but it must be COUNTED, not
      // silently matched away.
      let dustRows = 0;
      for (const k of [...m2.keys()].filter((kk) => !m1.has(kk))) {
        const r = m2.get(k)!;
        if (r.pnl === undefined && (r.size ?? 0) < 1.0) dustRows++;
      }

      // Measured 2026-10-19: v1 vs v2 disagree on ~1% of profiling rows at the
      // 4th decimal of price (2/200 on one wallet: avg 0.3231 vs 0.3227, pnl
      // 40076.71 vs 40082.03 = 0.013%). Repeated reads are bit-stable within a
      // version, so this is a venue-side aggregation difference, not churn or a
      // defect on our side. Tolerance is therefore RELATIVE and recorded, not
      // assumed away -- max deviations land in the JSON.
      const relOk = (a: number | undefined, b: number | undefined, tol = 1e-3) => {
        if (a === undefined && b === undefined) return true;
        if (a === undefined || b === undefined) return false;
        const scale = Math.max(Math.abs(a), Math.abs(b), 1);
        return Math.abs(a - b) / scale <= tol;
      };
      let valueDiffs = 0;
      let maxPnlDev = 0;
      let maxPriceDev = 0;
      let outcomeRewritten = 0;
      for (const [k, x1] of m1) {
        const x2 = m2.get(k);
        if (!x2) continue;
        if (String(x1.outcome) !== String(x2.outcome)) outcomeRewritten++;
        const pnlDev = x1.pnl !== undefined && x2.pnl !== undefined ? Math.abs(x1.pnl - x2.pnl) : 0;
        const pxDev = x1.price !== undefined && x2.price !== undefined ? Math.abs(x1.price - x2.price) : 0;
        maxPnlDev = Math.max(maxPnlDev, pnlDev);
        maxPriceDev = Math.max(maxPriceDev, pxDev);
        const bad =
          !relOk(round(x1.pnl), round(x2.pnl)) ||
          !relOk(round(x1.size), round(x2.size)) ||
          pxDev > 0.005 ||
          x1.won !== x2.won;
        if (bad) valueDiffs++;
      }

      const row = {
        address,
        rowsV1: a1.length,
        rowsV2: a2.length,
        matched: match,
        unmatchedV1: a1.length - match,
        unmatchedV2: a2.length - match,
        pnlV1: round(pnlA),
        pnlV2: round(pnlB),
        pnlDelta: round(pnlB - pnlA),
        sizeV1: round(szA),
        sizeV2: round(szB),
        valueDiffs,
        maxPnlDev,
        maxPriceDev,
        dustRows,
        dupV1,
        dupV2,
        outcomeRewritten,
        unmatchedV2NonDust: a2.length - match - dustRows,
      };
      perWallet.push(row);
      console.log(
        `  ${address.slice(0, 10)}… rows ${a1.length}/${a2.length} matched ${match} ` +
          `pnl ${round(pnlA)}/${round(pnlB)} (Δ ${round(pnlB - pnlA)}) valueDiffs ${valueDiffs} ` +
          `dust ${dustRows} dupV1/V2 ${dupV1}/${dupV2} outcomeRewritten ${outcomeRewritten}`
      );

      // Compare DEDUPED position counts; the raw row counts legitimately differ
      // because v2 emits a second dust row for some positions.
      if (Math.abs(m2.size - m1.size) > dustRows) {
        failures.push(`${address}: ${m1.size} v1 positions vs ${m2.size} v2 (${dustRows} dust explain the delta)`);
      }
      const realUnmatched = m1.size - match;
      if (realUnmatched > 0) failures.push(`${address}: ${realUnmatched} v1 positions have no v2 counterpart`);
      if (!relOk(pnlA, pnlB, 1e-3)) {
        failures.push(`${address}: realized pnl sum differs beyond 0.1% (${round(pnlA)} vs ${round(pnlB)})`);
      }
      if (valueDiffs > 0) failures.push(`${address}: ${valueDiffs} matched rows differ in value`);
      if (outcomeRewritten > 0) {
        console.log(`     note: ${outcomeRewritten} outcome string(s) rewritten by v2 (punctuation stripped)`);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      console.log(`  ${address.slice(0, 10)}… ERROR ${msg.slice(0, 140)}`);
      failures.push(`${address}: ${msg.slice(0, 80)}`);
    }
  }

  // ---------- 3. depth walker (cursor completeness) ----------
  console.log(`\n=== DEPTH WALK (cursor completeness) ===`);
  const depth: Record<string, unknown>[] = [];
  for (const address of sample.slice(0, 3)) {
    try {
      // measureDepth only walks when the scoring SAMPLE is AT ITS CEILING
      // (sampleClosedCap/sampleOpenCap = 100). Passing 0 makes it a null test
      // that returns 0/0 without a single request -- which is how this check
      // first came back "clean" while proving nothing.
      setVer("v1");
      const d1 = await adapter.fetchWalletDepth(address, { closed: 100, open: 100 });
      setVer("v2");
      const d2 = await adapter.fetchWalletDepth(address, { closed: 100, open: 100 });
      const row = { address, v1: d1, v2: d2 };
      depth.push(row);
      console.log(
        `  ${address.slice(0, 10)}… closed ${d1.closedCount}/${d2.closedCount} ` +
          `open ${d1.openCount}/${d2.openCount} censored ${d1.censored}/${d2.censored} ` +
          `requests ${d1.requests}/${d2.requests}`
      );
      if (d1.requests === 0 || d2.requests === 0) failures.push(`${address}: depth walk made no requests (null test)`);
      // v2 counts dust residues as open, so a small positive delta in openCount is
      // expected; a LARGE one would mean the cursor walk lost pages.
      const openDelta = d2.openCount - d1.openCount;
      if (d1.closedCount !== d2.closedCount) {
        failures.push(`${address}: closed depth ${d1.closedCount} != ${d2.closedCount}`);
      }
      if (openDelta < 0 || openDelta > 5) {
        failures.push(`${address}: open depth ${d1.openCount} -> ${d2.openCount} (dust cannot explain ${openDelta})`);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      console.log(`  ${address.slice(0, 10)}… ERROR ${msg.slice(0, 140)}`);
      failures.push(`${address}: depth ${msg.slice(0, 80)}`);
    }
  }

  // ---------- verdict ----------
  const out = {
    probe: "data-api-v2-dual-read",
    at: new Date().toISOString(),
    leaderboard: { rowsV1: lb1.length, rowsV2: lb2.length, onlyV1: only1, onlyV2: only2, pnlV1: round(pnl1), pnlV2: round(pnl2), rankMismatch },
    wallets: perWallet,
    depth,
    failures,
    verdict: failures.length === 0 ? "PASS" : "FAIL",
  };
  writeFileSync("data/data-api-v2-dual-read.json", JSON.stringify(out, null, 1));
  console.log(`\n=== VERDICT: ${out.verdict} ===`);
  for (const f of failures.slice(0, 20)) console.log(`  ✗ ${f}`);
  console.log(`  wrote data/data-api-v2-dual-read.json`);
  process.exit(failures.length === 0 ? 0 : 1);
}

main().catch((e) => {
  console.error(e);
  process.exit(2);
});
