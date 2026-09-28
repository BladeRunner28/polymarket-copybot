/**
 * shadow:forward-read — the pre-registered shadow read, applied uniformly.
 *
 * WHY (phil audit Trial A, drafts/phil-audit-2026-09-28.md §Shadow-trial):
 * we already mark several shadow feeds to settlement, but each has its own
 * bespoke summary. phil's repo is the counter-example that motivates one
 * convention: their sealed forward test returned -0.0730 with 145% of the P&L in
 * a single bet, and only their pre-registered criteria (min bets, cw_return > 0,
 * single-bet dominance cap) caught it. This script runs those criteria — plus a
 * market-clustered CI and a per-ruleSetVersion era sign check — over the shadow
 * lanes we already have.
 *
 * WHAT THIS IS NOT:
 *  - not a gate: it changes no rule, size, threshold or published number;
 *  - not the Oct 8 read: the pre-registered window closes 2026-10-08, and a run
 *    before then is a HARNESS SMOKE TEST. Rows are tagged `mode: "smoke"` unless
 *    `--preregistered` is passed, so a smoke number can never be quoted later as
 *    the pre-registered result.
 *
 * ENTRY CONVENTION (must match the lane summaries or the numbers are not
 * comparable): entry = the candidate's `currentPrice` (the price the scorer would
 * have copied at), stake = the row's recorded `stakeUsd`, return per $ staked =
 * (settledValue - entry) / entry. Entries below the approved dust floor (0.10,
 * tuning #29 rec 1) are EXCLUDED and the excluded count is reported — a $0.0005
 * entry that settles at 1.0 returns 2000x and is not executable at any size.
 *
 * ENV
 *   SHADOW_READ_DUST       dust floor (default 0.10)
 *   SHADOW_READ_MIN_ERA    lowest ruleSetVersion treated as OUR regime (default 49)
 *
 * MODES
 *   (default)        print the read
 *   --write          also append the result rows to data/shadow-forward-read.jsonl
 *   --preregistered  tag the written rows as the pre-registered read (Oct 8+ only)
 */

import { appendFileSync, readFileSync } from "fs";
import { join } from "path";
import { prisma } from "../src/lib/db";
import { evaluateShadowRead, type ShadowReadRow, type ShadowReadResult } from "../src/lib/shadow-read";
import { log, logError } from "../src/lib/redact";

const OUT = join(__dirname, "..", "data", "shadow-forward-read.jsonl");
const DUST = Number(process.env.SHADOW_READ_DUST ?? 0.10);
const MIN_ERA = Number(process.env.SHADOW_READ_MIN_ERA ?? 49);
const WRITE = process.argv.includes("--write");
const PREREGISTERED = process.argv.includes("--preregistered");

/** Shadow lanes that already pair candidate rows with resolve rows. */
const LANES = [
  { name: "late_drift_gate", file: "drift-shadow.jsonl", stakeField: "stakeUsd" },
  { name: "min_confidence_gate", file: "lowconf-shadow.jsonl", stakeField: "stakeUsd" },
] as const;

type Row = Record<string, unknown>;

function readJsonl(file: string): Row[] {
  try {
    return readFileSync(join(__dirname, "..", "data", file), "utf8")
      .split("\n")
      .filter((l) => l.trim().length > 0)
      .map((l) => JSON.parse(l) as Row);
  } catch {
    return [];
  }
}

/**
 * Which ruleSetVersion was live when each candidate was decided. Derived from
 * RuleSet.createdAt intervals, and only for versions >= MIN_ERA: before the v49
 * convention the regime label would be meaningful but not comparable, so those
 * rows are labelled unknown rather than silently pooled with the current era.
 */
async function eraLookup(): Promise<{ at: (ms: number) => string | null; versions: number[] }> {
  const rows = await prisma.ruleSet.findMany({
    select: { version: true, createdAt: true },
    orderBy: { createdAt: "asc" },
  });
  const bounds = rows.map((r) => ({ version: r.version, from: r.createdAt.getTime() }));
  return {
    versions: bounds.map((b) => b.version),
    at: (ms: number) => {
      let hit: number | null = null;
      for (const b of bounds) {
        if (b.from <= ms) hit = b.version;
        else break;
      }
      if (hit === null || hit < MIN_ERA) return null;
      return `v${hit}`;
    },
  };
}

function buildRows(
  laneRows: Row[],
  stakeField: string,
  eraAt: (ms: number) => string | null
): { rows: ShadowReadRow[]; candidates: number; resolved: number; dustExcluded: number; unlabeledEra: number } {
  const resolves = new Map<string, number>();
  for (const r of laneRows) {
    if (String(r.type) === "resolve") resolves.set(`${r.marketId}|${r.outcome}`, Number(r.value));
  }
  const rows: ShadowReadRow[] = [];
  let resolved = 0;
  let dustExcluded = 0;
  let unlabeledEra = 0;
  for (const c of laneRows) {
    if (String(c.type) !== "candidate") continue;
    const v = resolves.get(`${c.marketId}|${c.outcome}`);
    if (v === undefined) continue;
    resolved++;
    const entry = Number(c.currentPrice);
    const stake = Number(c[stakeField] ?? 10);
    if (!Number.isFinite(entry) || entry < DUST || !Number.isFinite(stake) || stake <= 0) {
      dustExcluded++;
      continue;
    }
    const decidedAt = Date.parse(String(c.ts));
    const era = Number.isFinite(decidedAt) ? eraAt(decidedAt) : null;
    if (era === null) unlabeledEra++;
    rows.push({
      key: `${c.marketId}|${c.outcome}|${c.wallet ?? ""}|${c.ts}`,
      cluster: String(c.marketId),
      ret: (v - entry) / entry,
      stake,
      won: v > 0,
      decidedAt: Number.isFinite(decidedAt) ? decidedAt : 0,
      era,
    });
  }
  return { rows, candidates: laneRows.filter((r) => String(r.type) === "candidate").length, resolved, dustExcluded, unlabeledEra };
}

function pct(x: number): string {
  return `${(x * 100).toFixed(2)}%`;
}

function printRead(lane: string, built: ReturnType<typeof buildRows>, result: ShadowReadResult): void {
  const b = (v: boolean | null) => (v === null ? "n/a" : v ? "PASS" : "FAIL");
  log(
    `\n[forward-read] ${lane} — decision=${result.decision.toUpperCase()} ` +
      `(settled=${built.resolved}, dust_excluded=${built.dustExcluded}, era_unlabeled=${built.unlabeledEra})`
  );
  log(
    `  bets=${result.bets} markets=${result.clusters} stake=$${result.stakeUsd.toFixed(0)} winRate=${pct(result.winRate)} ` +
      `roi=${pct(result.roi)} se=${pct(result.weightedSe)} cw_return=${pct(result.cwReturn)}`
  );
  log(
    `  (a) cw_return>0 ${b(result.criterionA)} | (b) top bet ${pct(result.largestWinnerShare)} of positive PnL ${b(result.criterionB)} ` +
      `| (c) CI [${pct(result.ciLow)}, ${pct(result.ciHigh)}] ${b(result.criterionC)} | (d) era sign ${b(result.criterionD)}`
  );
  if (result.eras) log(`  eras: ${result.eras.map((e) => `${e.era} n=${e.bets} roi=${pct(e.roi)}`).join(" · ")}`);
  for (const r of result.reasons) log(`  ! ${r}`);
}

async function main(): Promise<number> {
  const era = await eraLookup();
  log(
    `[forward-read] mode=${PREREGISTERED ? "PRE-REGISTERED" : "SMOKE"}${
      PREREGISTERED ? "" : " (harness smoke test — the pre-registered window closes 2026-10-08)"
    } dust_floor=${DUST} min_era=v${MIN_ERA} ruleset_versions=${era.versions.length}`
  );

  const out: Row[] = [];
  for (const lane of LANES) {
    const laneRows = readJsonl(lane.file);
    if (laneRows.length === 0) {
      log(`\n[forward-read] ${lane.name} — no rows in data/${lane.file} (nothing to read)`);
      continue;
    }
    const built = buildRows(laneRows, lane.stakeField, era.at);
    const result = evaluateShadowRead(built.rows);
    printRead(lane.name, built, result);
    out.push({
      readAt: new Date().toISOString(),
      mode: PREREGISTERED ? "preregistered" : "smoke",
      lane: lane.name,
      sourceFile: `data/${lane.file}`,
      entryConvention: "candidate.currentPrice; stake=row stakeUsd; ret=(settledValue-entry)/entry",
      dustFloor: DUST,
      candidates: built.candidates,
      settled: built.resolved,
      dustExcluded: built.dustExcluded,
      eraUnlabeled: built.unlabeledEra,
      result,
      note: "harness read — no rule, size, gate or published number is changed by this",
    });
  }

  if (out.length === 0) {
    log("[forward-read] nothing read");
    return 0;
  }
  if (WRITE) {
    appendFileSync(OUT, out.map((r) => JSON.stringify(r)).join("\n") + "\n");
    log(`\n[forward-read] appended ${out.length} row(s) -> ${OUT}`);
  } else {
    log("\n[forward-read] print-only (pass --write to record the read)");
  }
  return 0;
}

main()
  .then(async (code) => {
    await prisma.$disconnect();
    process.exit(code);
  })
  .catch(async (e) => {
    logError(`[forward-read] fatal: ${e instanceof Error ? e.message : e}`);
    await prisma.$disconnect();
    process.exit(1);
  });
