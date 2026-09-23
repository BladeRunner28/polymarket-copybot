/**
 * verify:wallet-depth — proof harness for the wallet-depth-field-clamp card
 * (approved 2026-09-23).
 *
 * The claim to verify is narrow:
 *   1. the scan write path now stores an UNCLAMPED depth (values above the old
 *      100 / 200 sampling ceilings exist in the DB), and
 *   2. the depth walk cannot move a published score.
 *
 * (2) is checked CAUSALLY (--causal-check): for each snapshot wallet, fetch the
 * scoring sample ONCE, score it, run the depth walk, score the SAME sample again
 * and deep-compare it. The walk is the only thing added between the two
 * scorings, so any delta is attributable to it. A before/after comparison across
 * two production scans cannot answer this question — the live book changes
 * between scans, so scores drift on their own (that drift is measured and
 * reported separately, as context, never as proof).
 *
 * Usage:
 *   npx tsx scripts/verify-wallet-depth.ts --causal-check
 *   npx tsx scripts/verify-wallet-depth.ts --snapshot
 *   npm run scan:wallets
 *   npx tsx scripts/verify-wallet-depth.ts --compare
 *
 * Read-only apart from its own artifacts (data/wallet-depth-verify-*.json).
 */

import { prisma } from "../src/lib/db";
import { getAdapter } from "../src/lib/adapters";
import { getActiveRules } from "../src/lib/rules";
import { scoreWallet } from "../src/lib/scoring/wallet";
import * as fs from "fs";
import { join } from "path";

const ROOT = join(__dirname, "..");
const SNAP = join(ROOT, "data", "wallet-depth-verify-before.json");
const REPORT = join(ROOT, "data", "wallet-depth-verification.json");
const SCAN_LIMIT = Number(process.env.WALLET_SCAN_LIMIT ?? 25);

type Row = {
  address: string;
  status: string;
  globalScore: number;
  roi30d: number;
  copyabilityScore: number;
  consistencyScore: number;
  tradeCount30d: number;
  resolvedTradeCount30d: number;
  depthCensored: boolean;
  depthMeasuredAt: string | null;
};

/** Exactly the scanner's selection: least-recently-scanned first. */
async function scanTargets(): Promise<Row[]> {
  const ws = await prisma.walletProfile.findMany({
    where: { isDemo: false },
    orderBy: [{ lastScannedAt: { sort: "asc", nulls: "first" } }, { sourceRank: "asc" }],
    take: SCAN_LIMIT,
  });
  return ws.map(toRow);
}

/** The snapshotted addresses, read back by identity — NOT re-derived from the
 *  scanner's ordering, which moves them to the back of the queue once scanned. */
async function rowsForAddresses(addresses: string[]): Promise<Row[]> {
  const ws = await prisma.walletProfile.findMany({ where: { address: { in: addresses } } });
  return ws.map(toRow);
}

function toRow(w: {
  address: string;
  status: string;
  globalScore: number;
  roi30d: number;
  copyabilityScore: number;
  consistencyScore: number;
  tradeCount30d: number;
  resolvedTradeCount30d: number;
  depthCensored: boolean;
  depthMeasuredAt: Date | null;
}): Row {
  return {
    address: w.address,
    status: w.status,
    globalScore: w.globalScore,
    roi30d: w.roi30d,
    copyabilityScore: w.copyabilityScore,
    consistencyScore: w.consistencyScore,
    tradeCount30d: w.tradeCount30d,
    resolvedTradeCount30d: w.resolvedTradeCount30d,
    depthCensored: w.depthCensored ?? false,
    depthMeasuredAt: w.depthMeasuredAt ? w.depthMeasuredAt.toISOString() : null,
  };
}

const SCORE_FIELDS = ["globalScore", "roi30d", "copyabilityScore", "consistencyScore"] as const;

function pct(part: number, whole: number) {
  return whole ? `${((100 * part) / whole).toFixed(1)}%` : "n/a";
}

async function census(label: string) {
  const all = await prisma.walletProfile.findMany({
    where: { isDemo: false },
    select: {
      resolvedTradeCount30d: true,
      tradeCount30d: true,
      depthCensored: true,
      depthMeasuredAt: true,
    },
  });
  const n = all.length;
  const gt = (f: (r: (typeof all)[number]) => number, v: number) => all.filter((r) => f(r) > v).length;
  const measured = all.filter((r) => r.depthMeasuredAt !== null).length;
  console.log(
    `\n${label}: ${n} live wallets | resolved>100: ${gt((r) => r.resolvedTradeCount30d, 100)} (${pct(
      gt((r) => r.resolvedTradeCount30d, 100),
      n
    )}) | resolved==100: ${all.filter((r) => r.resolvedTradeCount30d === 100).length} (${pct(
      all.filter((r) => r.resolvedTradeCount30d === 100).length,
      n
    )}) | total>200: ${gt((r) => r.tradeCount30d, 200)} (${pct(gt((r) => r.tradeCount30d, 200), n)}) | total==200: ${
      all.filter((r) => r.tradeCount30d === 200).length
    } | depth measured: ${measured} (${pct(measured, n)}) | still censored: ${all.filter((r) => r.depthCensored).length}`
  );
  return { n, measured };
}

/**
 * CAUSAL CHECK — the only experiment that isolates the change under test.
 * Fetch the sample once, score it, run the depth walk, score again, and compare
 * both the scores and the sample itself (a walk that mutated the array would be
 * the one way to move a score from here).
 */
async function causalCheck(): Promise<boolean> {
  const adapter = getAdapter();
  const { rules } = await getActiveRules();
  const targets = JSON.parse(fs.readFileSync(SNAP, "utf-8")).rows.map((r: Row) => r.address);
  console.log(`\nCAUSAL CHECK — ${targets.length} wallet(s): sample frozen, depth walk inserted between two scorings`);
  let failures = 0;
  let walked = 0;
  for (const address of targets) {
    const trades = await adapter.fetchWalletActivity(address, 30);
    const before = scoreWallet(trades, rules);
    const beforeJson = JSON.stringify(trades);
    const depth = await adapter.fetchWalletDepth(address, {
      closed: before.resolvedTradeCount30d,
      open: Math.max(0, before.tradeCount30d - before.resolvedTradeCount30d),
    });
    const after = scoreWallet(trades, rules);
    const sampleChanged = JSON.stringify(trades) !== beforeJson;
    const deltas = SCORE_FIELDS.filter((f) => before[f] !== after[f]);
    if (depth.requests > 0) walked++;
    if (deltas.length > 0 || sampleChanged) {
      failures++;
      console.log(
        `  MISMATCH ${address}: deltas [${deltas.join(",")}] sampleMutated=${sampleChanged} depth requests=${depth.requests}`
      );
    }
  }
  const report = {
    generatedAt: new Date().toISOString(),
    wallets: targets.length,
    walletsWalked: walked,
    causalDeltaCount: failures,
    passed: failures === 0,
  };
  fs.writeFileSync(join(ROOT, "data", "wallet-depth-causal-check.json"), JSON.stringify(report, null, 2));
  console.log(
    `CAUSAL DELTA: ${failures === 0 ? "0 on all wallets — PASS" : `${failures} wallet(s) FAILED`} ` +
      `(${walked}/${targets.length} actually took the depth walk)`
  );
  return failures === 0;
}

async function main() {
  if (process.argv.includes("--causal-check")) {
    const ok = await causalCheck();
    await census("CURRENT");
    if (!ok) process.exitCode = 1;
    return;
  }
  const mode = process.argv.includes("--compare") ? "compare" : "snapshot";
  const rows = await scanTargets();

  if (mode === "snapshot") {
    fs.writeFileSync(SNAP, JSON.stringify({ takenAt: new Date().toISOString(), limit: SCAN_LIMIT, rows }, null, 2));
    console.log(`Snapshot of the next ${rows.length} scan target(s) → ${SNAP}`);
    await census("BEFORE");
    return;
  }

  if (!fs.existsSync(SNAP)) throw new Error(`No snapshot at ${SNAP} — run --snapshot before the scan.`);
  const before = (JSON.parse(fs.readFileSync(SNAP, "utf-8")) as { takenAt: string; rows: Row[] }).rows;
  const after = await rowsForAddresses(before.map((b) => b.address));
  const byAddr = new Map(after.map((r) => [r.address, r]));
  const rowsNow = after;

  console.log(`\nComparing ${before.length} wallet(s) snapshotted ${JSON.parse(fs.readFileSync(SNAP, "utf-8")).takenAt}`);
  console.log("address                                      scored? closed_old→new      total_old→new     censored");
  const scoreDeltas: Array<{ address: string; field: string; before: number; after: number }> = [];
  const missing: string[] = [];
  const countMoves: Array<{ address: string; closedBefore: number; closedAfter: number; totalBefore: number; totalAfter: number }> = [];

  for (const b of before) {
    const a = byAddr.get(b.address);
    if (!a) {
      missing.push(b.address);
      continue;
    }
    for (const f of SCORE_FIELDS) {
      if (b[f] !== a[f]) scoreDeltas.push({ address: b.address, field: f, before: b[f], after: a[f] });
    }
    countMoves.push({
      address: b.address,
      closedBefore: b.resolvedTradeCount30d,
      closedAfter: a.resolvedTradeCount30d,
      totalBefore: b.tradeCount30d,
      totalAfter: a.tradeCount30d,
    });
    const moved = b.resolvedTradeCount30d !== a.resolvedTradeCount30d || b.tradeCount30d !== a.tradeCount30d;
    console.log(
      `${b.address}  ${a.depthMeasuredAt ? "yes  " : "NO   "} ${String(b.resolvedTradeCount30d).padStart(
        4
      )}→${String(a.resolvedTradeCount30d).padStart(4)}  ${String(b.tradeCount30d).padStart(4)}→${String(
        a.tradeCount30d
      ).padStart(4)}  ${a.depthCensored ? "censored" : "exact"}${moved ? "  *moved" : ""}`
    );
  }

  const deeper = countMoves.filter((m) => m.closedAfter > m.closedBefore || m.totalAfter > m.totalBefore);
  const aboveOldCeiling = rowsNow.filter((r) => r.resolvedTradeCount30d > 100 || r.tradeCount30d > 200);
  const c = await census("AFTER");

  const verdict = {
    // context only: two production scans minutes apart see a MOVED live book, so
    // these deltas are scan-to-scan drift, not the depth walk's doing. Score
    // neutrality is established by --causal-check, not by this comparison.
    scanToScanDrift: { walletsWithAnyScoreDelta: new Set(scoreDeltas.map((d) => d.address)).size, deltas: scoreDeltas },
    counts: {
      reScanned: rowsNow.length,
      recordedDeeper: deeper.length,
      aboveOldCeilingStored: aboveOldCeiling.length,
      moves: deeper,
    },
    census: c,
    generatedAt: new Date().toISOString(),
  };
  fs.writeFileSync(REPORT, JSON.stringify(verdict, null, 2));

  const worst = SCORE_FIELDS.map((f) => {
    const ds = scoreDeltas.filter((d) => d.field === f).map((d) => Math.abs(d.after - d.before));
    return `${f} max |Δ| ${ds.length ? Math.max(...ds).toFixed(3) : "0"} (n=${ds.length})`;
  }).join(" | ");
  console.log(`\nSCAN-TO-SCAN DRIFT (context, not the change under test): ${worst}`);
  console.log(`DEPTH: ${deeper.length}/${rowsNow.length} wallet(s) recorded deeper than the sample; ${aboveOldCeiling.length} now store a value above the old 100/200 ceiling`);
  console.log(`Report → ${REPORT}`);
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
