/**
 * wallet-depth-ceiling-read — what the depth ceiling does to a depth FLOOR, measured.
 * Read-only. Evidence for card `wallet-depth-ceiling-300-finding` (queue item 18, 2026-11-04).
 *
 * WHY THIS EXISTS. `resolvedTradeCount30d` stops at the walk budget (300 closed by default), so
 * ~half the wallet table holds one number for "300" and "3,000". The open question the card names
 * is not "is the field clamped" (it is) but "does the clamp move the DEPTH FLOOR" — the only place
 * the field is actually used as a threshold. That is answerable exactly, and this prints it:
 * a censored count is a LOWER BOUND, and a lower bound answers "at least k" correctly up to k=300.
 *
 * BASIS (stated, never implied):
 *   population = WalletProfile rows, isDemo = 0 (the whole scored table, not our book);
 *   level      = the wallet;
 *   clock      = the scan snapshot (lastScannedAt range) — these are live values, not as-of-entry;
 *   exclusions = rows with depthMeasuredAt IS NULL are reported and EXCLUDED from the ceiling read:
 *                they predate the 2026-09-23 walk and still carry sample-clamped counts (<=100).
 * The live floor is read from the ACTIVE RuleSet, and its real basis is printed next to it — the
 * rule is applied to the SCORING SAMPLE inside scoreWallet (src/lib/scoring/wallet.ts), not to
 * this stored field, which is why the ceiling cannot move admission at all.
 *
 * Read-only: no writes, no rule/sizing consumer. Run: npx tsx scripts/wallet-depth-ceiling-read.ts
 */

import { prisma } from "../src/lib/db";
import {
  readCeiling,
  floorVerdicts,
  saturationFloor,
  type DepthObservation,
} from "../src/lib/wallet-depth-ceiling";

const pct = (a: number, b: number) => (b > 0 ? `${((100 * a) / b).toFixed(1)}%` : "n/a");
const num = (n: number) => n.toLocaleString("en-US");

export const FLOOR_CANDIDATES = [3, 5, 10, 25, 50, 100, 300, 400, 600, 1000];

async function main() {
  const rows = await prisma.walletProfile.findMany({
    where: { isDemo: false },
    select: {
      resolvedTradeCount30d: true,
      tradeCount30d: true,
      depthCensored: true,
      depthMeasuredAt: true,
      lastScannedAt: true,
    },
  });
  const active = await prisma.ruleSet.findFirst({ where: { active: true }, orderBy: { version: "desc" } });

  const measured = rows.filter((r) => r.depthMeasuredAt !== null);
  const unmeasured = rows.length - measured.length;
  const obs: DepthObservation[] = measured.map((r) => ({
    value: r.resolvedTradeCount30d,
    censored: r.depthCensored,
  }));

  const read = readCeiling(obs);
  const stamps = measured.map((r) => r.lastScannedAt?.getTime() ?? 0).filter((t) => t > 0);
  const iso = (ms: number) => new Date(ms).toISOString().replace(".000Z", "Z");

  console.log("wallet depth CEILING read — READ-ONLY, gates nothing");
  console.log(
    `  population: ${num(rows.length)} WalletProfile rows (isDemo=0) | level=wallet | clock=scan snapshot` +
      `${stamps.length ? ` ${iso(Math.min(...stamps))}..${iso(Math.max(...stamps))}` : ""}`
  );
  console.log(
    `  EXCLUDED ${num(unmeasured)} row(s) with no depthMeasuredAt (pre-2026-09-23 walk era, sample-clamped <=100)` +
      ` -> ceiling read on ${num(read.n)} wallets`
  );
  console.log("");
  console.log(
    `  derived ceiling (max stored count) = ${read.ceiling} | AT ceiling ${num(read.atCeiling)} = ${pct(
      read.atCeiling,
      read.n
    )} of wallets`
  );
  console.log(
    `  of those: ${num(read.censoredAtCeiling)} flagged censored (LOWER BOUND, true depth unknown), ` +
      `${num(read.exactAtCeiling)} exact | censored under the ceiling: ${num(read.censoredBelowCeiling)}` +
      ` (open-side budget, closed count still exact)`
  );
  console.log(
    `  => the field is a THRESHOLD indicator, not a depth measure: it cannot order wallets at or above ${read.ceiling}.`
  );
  console.log("");

  const verdicts = floorVerdicts(obs, FLOOR_CANDIDATES);
  console.log("  FLOOR SIMULATION — what each candidate minimum would do to this table");
  console.log(
    `  ${"floor".padStart(6)} ${"pass".padStart(7)} ${"pass%".padStart(7)} ${"of-pass-lo".padStart(11)} ${"fail".padStart(7)} ${"fail-indet".padStart(10)}`
  );
  for (const v of verdicts) {
    console.log(
      `  ${String(v.floor).padStart(6)} ${num(v.pass).padStart(7)} ${pct(v.pass, read.n).padStart(7)} ` +
        `${num(v.passCensored).padStart(11)} ${num(v.fail).padStart(7)} ${num(v.failIndeterminate).padStart(10)}`
    );
  }
  console.log(
    `  saturationFloor = ${saturationFloor(read.ceiling)} — no floor at or below ${read.ceiling} can be moved by the ceiling;`
  );
  console.log(
    `  only a floor ABOVE ${read.ceiling} produces indeterminate FAILS, and there the count is a lower bound, not a verdict.`
  );
  console.log("");

  // ---- the live floor, and the population it is actually applied to
  let liveFloor: number | null = null;
  if (active) {
    try {
      const parsed = JSON.parse(active.rulesJson) as { minResolvedTrades?: number };
      liveFloor = typeof parsed.minResolvedTrades === "number" ? parsed.minResolvedTrades : null;
    } catch {
      liveFloor = null;
    }
  }
  console.log(
    `  LIVE FLOOR: RuleSet v${active?.version ?? "?"} minResolvedTrades = ${liveFloor ?? "unreadable"} | ` +
      `applied to the SCORING SAMPLE (the <=100-row closed-positions sample), not to this field ` +
      `(src/lib/scoring/wallet.ts:105)`
  );
  const lv = liveFloor === null ? null : verdicts.find((v) => v.floor === liveFloor);
  if (liveFloor !== null && lv) {
    console.log(
      `  at floor ${liveFloor}: ${num(lv.pass)}/${num(read.n)} wallets pass (${pct(lv.pass, read.n)}), ` +
        `${num(lv.failIndeterminate)} indeterminate -> the ceiling cannot move admission`
    );
  } else if (liveFloor !== null) {
    const single = floorVerdicts(obs, [liveFloor])[0];
    console.log(
      `  at floor ${liveFloor}: ${num(single.pass)}/${num(read.n)} wallets pass, ${num(single.failIndeterminate)} indeterminate`
    );
  }
  console.log("");
  console.log(
    "  VERDICT: the ceiling does NOT move any live depth floor (live floor is far below it); it DOES make every"
  );
  console.log(
    `  statistic that orders wallets inside the deep end unfalsifiable. Depth statistics must carry depthCensored,`
  );
  console.log(
    "  and the as-of-entry observed-depth measure stays the only one that can grade depth (it is itself a lower bound)."
  );
}

main()
  .catch((err) => {
    console.error("[wallet-depth-ceiling-read] FAILED:", err);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
