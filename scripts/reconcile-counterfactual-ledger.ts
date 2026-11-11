/**
 * TABLE-VS-LEDGER DIFF for the counterfactual-ledger port
 * (roadmap card phil-counterfactual-ledger-primitive, gate (b)).
 *
 * WHAT IT PROVES: the four declined-gate lanes now write through ONE append-only
 * primitive and read through ONE summary function. The evidence is a
 * field-for-field comparison against a GOLDEN capture taken from the PRE-PORT lane
 * implementations on one frozen decision window
 * (data/counterfactual-ledger-golden.json, captured 2026-11-11 by
 * scripts/capture-counterfactual-golden.ts, which stays in the tree so the gate can
 * be re-taken for any future lane).
 *
 * Window rule (identical on both sides): every candidate DECIDED at/before the
 * frozen cutoff, plus the resolve set STORED IN THE GOLDEN (replayed, not re-read from
 * the live feed — the marker keeps appending resolves, so re-reading would make the gate
 * move on the next settle). The script re-derives a digest of the candidate window; if
 * that moved, the diff says so instead of pretending the numbers are comparable.
 *
 * Any disagreement between the golden field and the ported field is a PORT BUG,
 * not a finding: neither side is allowed to have a better opinion about fill,
 * stake, dedupe, dust or rounding.
 *
 * It also runs the PRE-REGISTERED read (src/lib/shadow-read.ts, phil audit Trial A)
 * over every lane through the same adapter, which is gate (c): one read, four
 * lanes, no per-lane read code.
 *
 * Run: npx tsx scripts/reconcile-counterfactual-ledger.ts [--quiet]
 * Exit code 1 on any field disagreement.
 */

import * as crypto from "crypto";
import * as fs from "fs";
import { join } from "path";
import { toShadowReadRows, type LedgerReadOptions } from "../src/lib/counterfactual-ledger";
import { readDriftRows, summarizeDrift, DRIFT_SHADOW_FILE } from "../src/lib/shadow-drift";
import { readLowConfRows, summarizeLowConf, LOWCONF_SHADOW_FILE } from "../src/lib/shadow-lowconf";
import {
  readWalletCapRows,
  summarizeWalletCap,
  WALLET_CAP_SHADOW_FILE,
  COUNTERFACTUAL_RECONCILE_FILE,
} from "../src/lib/shadow-wallet-cap";
import { readShadowRows, summarizeShadow, SHADOW_FILE } from "../src/lib/shadow-longshot";
import { evaluateShadowRead } from "../src/lib/shadow-read";
import { readWalletCapArming } from "../src/lib/wallet-cap-arming";

const GOLDEN_FILE = join(__dirname, "..", "data", "counterfactual-ledger-golden.json");
const REPORT_FILE = COUNTERFACTUAL_RECONCILE_FILE;

interface GoldenLane {
  lane: string;
  file: string;
  summary: Record<string, unknown>;
  rowsDigest: string;
  rowsSelected: number;
  /** The resolve set as it stood at capture — replayed, not re-read from the live feed. */
  resolves: Array<[string, string, number]>;
  /** Wall clock the pre-port summaries read the trailing-7d boundary against. */
  readClockMs: number;
}

interface Golden {
  capturedAt: string;
  windowCutoff: string;
  lanes: Record<string, GoldenLane>;
}

interface LaneDef {
  id: keyof Golden["lanes"];
  file: string;
  read: () => Array<Record<string, unknown>>;
  summarize: (
    rows: Array<Record<string, unknown>>,
    opts?: { now?: number }
  ) => Record<string, unknown>;
  /** Read options the lane's OWN summary uses — restated here so the pre-registered read prices the same population. */
  readOptions: LedgerReadOptions;
}

const LANES: LaneDef[] = [
  {
    id: "drift",
    file: DRIFT_SHADOW_FILE,
    read: readDriftRows,
    summarize: summarizeDrift as unknown as (rows: Array<Record<string, unknown>>) => Record<string, unknown>,
    readOptions: { stakeField: "stakeUsd", defaultStakeUsd: 10 },
  },
  {
    id: "lowconf",
    file: LOWCONF_SHADOW_FILE,
    read: readLowConfRows,
    summarize: summarizeLowConf as unknown as (rows: Array<Record<string, unknown>>) => Record<string, unknown>,
    readOptions: { stakeField: "stakeUsd", defaultStakeUsd: 10 },
  },
  {
    id: "walletCap",
    file: WALLET_CAP_SHADOW_FILE,
    read: readWalletCapRows,
    summarize: summarizeWalletCap as unknown as (rows: Array<Record<string, unknown>>) => Record<string, unknown>,
    readOptions: { stakeField: "sizeUsd", defaultStakeUsd: 0 },
  },
  {
    id: "longshot",
    file: SHADOW_FILE,
    read: readShadowRows,
    summarize: summarizeShadow as unknown as (rows: Array<Record<string, unknown>>) => Record<string, unknown>,
    readOptions: { stakeField: "stakeUsd", defaultStakeUsd: 20, betFilter: (r) => r.wouldAdmit === true },
  },
];

/** Frozen window: candidates at/before the cutoff, plus the golden's resolve set. */
function windowRows(rows: Array<Record<string, unknown>>, cutoff: string): Array<Record<string, unknown>> {
  return rows.filter((r) => r.type === "candidate" && String(r.ts) <= cutoff);
}

function resolveRows(resolves: Array<[string, string, number]>): Array<Record<string, unknown>> {
  return resolves.map(([marketId, outcome, value]) => ({ type: "resolve", marketId, outcome, value }));
}

function digest(rows: Array<Record<string, unknown>>): string {
  const h = crypto.createHash("sha256");
  for (const r of rows) h.update(JSON.stringify(r) + "\n");
  return h.digest("hex");
}

/** Flatten a summary to `path -> primitive`, so two shapes can be diffed key by key. */
function flatten(value: unknown, prefix = ""): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    out[prefix] = value;
    return out;
  }
  for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
    const path = prefix ? `${prefix}.${k}` : k;
    if (path === "generatedAt") continue;
    Object.assign(out, flatten(v, path));
  }
  return out;
}

function sameValue(a: unknown, b: unknown): boolean {
  if (typeof a === "number" && typeof b === "number") {
    if (Number.isNaN(a) && Number.isNaN(b)) return true;
    return Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(a), Math.abs(b));
  }
  if (a === null || b === null) return a === b;
  return a === b;
}

interface LaneReconcile {
  lane: string;
  laneId: string;
  file: string;
  window: { cutoff: string; rows: number; digest: string; digestMatches: boolean };
  /** Rows the lane's own feed holds on disk (0 = the file was never written). */
  feedRows: number;
  compared: number;
  mismatches: Array<{ path: string; golden: unknown; ported: unknown }>;
  /** Fields the port ADDS (e.g. the ex-dust read the confidence lane never had). */
  additive: string[];
  /** `empty` = the feed holds no rows, so the diff below attests the empty path only. */
  status: "match" | "mismatch" | "window_moved" | "empty";
  /**
   * Present on an EMPTY lane: the exact reason it is empty. `contradiction` is
   * the falsifiable part — an empty feed while the gated rail fired (or is
   * already breached) means the writer is broken, and the gate exits 1.
   */
  armCheck?: Record<string, unknown>;
  /** The ported summary itself, so the report is auditable without re-running the read. */
  portedSummary: Record<string, unknown>;
  preRegisteredRead: Record<string, unknown>;
}

async function main() {
  const golden = JSON.parse(fs.readFileSync(GOLDEN_FILE, "utf-8")) as Golden;
  const cutoff = golden.windowCutoff;

  const results: LaneReconcile[] = [];
  let failures = 0;
  let armContradictions = 0;

  for (const def of LANES) {
    const g = golden.lanes[def.id];
    if (!g) throw new Error(`golden capture is missing lane "${def.id}"`);
    const feed = def.read();
    const candidates = windowRows(feed, cutoff);
    const rows = [...candidates, ...resolveRows(g.resolves)];
    const rowsDigest = digest(candidates);
    const digestMatches = rowsDigest === g.rowsDigest;
    const goldenFlat = flatten(g.summary);
    // Price the trailing-7d cohort at the instant the golden was captured, otherwise the
    // 7-day boundary moves between capture and diff and the cohort fields "mismatch".
    const ported = def.summarize(rows, { now: g.readClockMs });
    const portedFlat = flatten(ported);

    const mismatches: Array<{ path: string; golden: unknown; ported: unknown }> = [];
    for (const [path, want] of Object.entries(goldenFlat)) {
      if (!(path in portedFlat)) {
        mismatches.push({ path, golden: want, ported: "<missing>" });
        continue;
      }
      if (!sameValue(want, portedFlat[path])) {
        mismatches.push({ path, golden: want, ported: portedFlat[path] });
      }
    }
    const additive = Object.keys(portedFlat).filter((p) => !(p in goldenFlat));

    // Gate (c): the pre-registered read, applied to this lane through the ONE adapter.
    const readRows = toShadowReadRows(rows, def.readOptions);
    const read = evaluateShadowRead(readRows);

    // A lane with NOTHING in the frozen window cannot attest anything: the golden's
    // own fields are all zeros, so a field-for-field match is a property of the empty
    // path, not evidence the lane works. Score it EMPTY and say why (card t_bfb9e54c:
    // a 10/10 match on an empty feed looked like evidence for 53 days). Keyed on the
    // WINDOW, not the feed, so the day the lane starts writing still reports honestly.
    const status: LaneReconcile["status"] =
      candidates.length === 0
        ? "empty"
        : !digestMatches
          ? "window_moved"
          : mismatches.length === 0
            ? "match"
            : "mismatch";
    if (mismatches.length > 0) failures++;

    let armCheck: Record<string, unknown> | undefined;
    if (status === "empty") {
      const armRead = await readWalletCapArming({ feedRows: feed.length });
      if (armRead.ok) {
        const a = armRead.arming;
        armCheck = {
          state: a.state,
          enabled: a.enabled,
          walletCapUsd: Math.round(a.walletCapUsd * 100) / 100,
          basis: a.basis,
          blocksInWindow: a.blocksInWindow,
          windowDays: a.windowDays,
          feedRows: a.feedRows,
          breached: a.breached,
          tightest: a.tightest
            ? {
                walletAddress: a.tightest.walletAddress,
                notionalUsd: Math.round(a.tightest.notionalUsd * 100) / 100,
                ceilingUsd: Math.round(a.tightest.ceilingUsd * 100) / 100,
                headroomUsd: Math.round(a.tightest.headroomUsd * 100) / 100,
                ratio: Math.round(a.tightest.ratio * 10000) / 10000,
              }
            : null,
          contradiction: a.contradiction,
          note: a.note,
          capBasis: armRead.capBasis,
        };
        if (a.contradiction) armContradictions++;
      } else {
        armCheck = { unavailable: armRead.error };
      }
    }

    results.push({
      lane: g.lane,
      laneId: def.id,
      file: def.file.replace(/^.*\.worktrees\/[^/]+\//, ""),
      window: { cutoff, rows: candidates.length, digest: rowsDigest.slice(0, 16), digestMatches },
      feedRows: feed.length,
      compared: Object.keys(goldenFlat).length,
      mismatches,
      additive,
      status,
      armCheck,
      portedSummary: ported,
      preRegisteredRead: {
        bets: read.bets,
        clusters: read.clusters,
        roi: Math.round(read.roi * 10000) / 10000,
        cwReturn: Math.round(read.cwReturn * 10000) / 10000,
        ci: [Math.round(read.ciLow * 10000) / 10000, Math.round(read.ciHigh * 10000) / 10000],
        eraCheck: read.criterionD,
        decision: read.decision,
        note: read.reasons[0],
      },
    });
  }

  const report = {
    generatedAt: new Date().toISOString(),
    goldenCapturedAt: golden.capturedAt,
    windowCutoff: cutoff,
    lanes: results,
    summary: {
      lanesCompared: results.length,
      lanesMatching: results.filter((r) => r.status === "match").length,
      lanesEmpty: results.filter((r) => r.status === "empty").map((r) => r.laneId),
      armContradictions,
      mismatches: results.reduce((n, r) => n + r.mismatches.length, 0),
      verdict:
        failures > 0 || armContradictions > 0
          ? failures > 0
            ? "FAIL — port bug"
            : "FAIL — an EMPTY lane's gate is firing, so its writer is broken (feed silent while blocks exist)"
          : results.some((r) => r.status === "empty")
            ? "PASS — every POPULATED lane reproduces its golden; empty lane(s) reported as EMPTY, not as matches"
            : "PASS — port reproduces every golden field",
    },
  };
  fs.writeFileSync(REPORT_FILE, JSON.stringify(report, null, 2));

  for (const r of results) {
    const emptyNote =
      r.status === "empty"
        ? `\n  VACUOUS — ${
            r.feedRows === 0
              ? "the feed holds 0 rows"
              : `the window holds 0 rows of the feed's ${r.feedRows}`
          }, so the ${r.compared}-field match below attests the EMPTY path only, not the lane`
        : "";
    console.log(
      `\n[${r.status.toUpperCase()}] ${r.lane} (${r.laneId}) window<=${cutoff} rows=${r.window.rows} ` +
        `digest=${r.window.digest}${r.window.digestMatches ? "" : " (MOVED since capture)"}${emptyNote}`
    );
    console.log(`  compared ${r.compared} golden fields, ${r.mismatches.length} mismatch(es)`);
    if (r.armCheck) {
      const a = r.armCheck as Record<string, unknown>;
      if (a.unavailable) {
        const why = String(a.unavailable).replace(/\s+/g, " ").trim();
        console.log(`  arm check: UNAVAILABLE — ${why.length > 240 ? `${why.slice(0, 240)}…` : why}`);
      } else {
        console.log(
          `  arm check: state=${String(a.state)} ceiling=$${Number(a.walletCapUsd).toFixed(2)} ` +
            `(basis ${String(a.basis)}) blocks/${String(a.windowDays)}d=${String(a.blocksInWindow)} ` +
            `breached=${(a.breached as string[]).length} contradiction=${String(a.contradiction)}`
        );
        console.log(`    ${String(a.note)}`);
        console.log(`    cap: ${String(a.capBasis)}`);
      }
    }
    for (const m of r.mismatches.slice(0, 10)) {
      console.log(`    ${m.path}: golden=${JSON.stringify(m.golden)} ported=${JSON.stringify(m.ported)}`);
    }
    if (r.additive.length) console.log(`  additive (not in golden): ${r.additive.join(", ")}`);
    const p = r.preRegisteredRead as Record<string, unknown>;
    console.log(
      `  pre-registered read: bets=${p.bets} clusters=${p.clusters} roi=${p.roi} cw_return=${p.cwReturn} ` +
        `ci=${JSON.stringify(p.ci)} era=${p.eraCheck === null ? "UNVERIFIABLE" : String(p.eraCheck)} -> ${p.decision}`
    );
  }

  console.log(
    `\n${report.summary.verdict}\n  ${report.summary.lanesMatching}/${report.summary.lanesCompared} lanes match` +
      `${report.summary.lanesEmpty.length ? `, ${report.summary.lanesEmpty.length} EMPTY (${report.summary.lanesEmpty.join(", ")})` : ""}` +
      `, ${report.summary.mismatches} field mismatch(es), ${report.summary.armContradictions} arm contradiction(s). ` +
      `Report: ${REPORT_FILE}`
  );
  process.exit(failures === 0 && armContradictions === 0 ? 0 : 1);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
