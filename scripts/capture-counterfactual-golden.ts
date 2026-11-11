/**
 * GOLDEN CAPTURE for the counterfactual-ledger port.
 *
 * Runs the PRE-PORT lane summaries over one frozen decision window and writes
 * data/counterfactual-ledger-golden.json, which scripts/reconcile-counterfactual-ledger.ts
 * then diffs field-for-field against the ported implementations reading the same files.
 * Kept in the tree (not deleted after the run) so the gate is auditable: re-capturing is
 * how a future port of a fifth lane proves itself.
 *
 * Window rule (identical on both sides): every row that is not a candidate, plus every
 * candidate whose `ts` is at/before the cutoff. The cutoff is FROZEN here and stored in
 * the golden, so later appends to the feeds cannot move the comparison.
 *
 * Run from a tree that still has the PRE-PORT lane modules (overwriting the golden from a
 * ported tree would compare the port against itself and prove nothing):
 *   npx tsx scripts/capture-counterfactual-golden.ts [--cutoff <iso>]
 */

import * as crypto from "crypto";
import * as fs from "fs";
import { join } from "path";
import { readDriftRows, summarizeDrift, DRIFT_SHADOW_FILE } from "../src/lib/shadow-drift";
import { readLowConfRows, summarizeLowConf, LOWCONF_SHADOW_FILE } from "../src/lib/shadow-lowconf";
import {
  readWalletCapRows,
  summarizeWalletCap,
  WALLET_CAP_SHADOW_FILE,
} from "../src/lib/shadow-wallet-cap";
import { readShadowRows, summarizeShadow, SHADOW_FILE } from "../src/lib/shadow-longshot";

const GOLDEN_FILE = join(__dirname, "..", "data", "counterfactual-ledger-golden.json");

const LANES = [
  { id: "drift", lane: "late_drift_gate", file: DRIFT_SHADOW_FILE, read: readDriftRows, summarize: summarizeDrift },
  { id: "lowconf", lane: "min_confidence_gate", file: LOWCONF_SHADOW_FILE, read: readLowConfRows, summarize: summarizeLowConf },
  { id: "walletCap", lane: "per_wallet_cap", file: WALLET_CAP_SHADOW_FILE, read: readWalletCapRows, summarize: summarizeWalletCap },
  { id: "longshot", lane: "longshot_shadow_ladder", file: SHADOW_FILE, read: readShadowRows, summarize: summarizeShadow },
] as const;

/**
 * The frozen window is (candidates decided at/before the cutoff) + (the resolve rows
 * known at capture time, stored in the golden). Candidates never change retroactively
 * — the feeds are append-only and the cutoff is fixed — but the resolution marker keeps
 * appending, so the resolve set has to be frozen WITH the golden. Re-deriving it from
 * the live file instead would make the gate fail on the next settle, which is how a
 * probe becomes unfalsifiable/unreproducible.
 */
function windowRows(rows: Array<Record<string, unknown>>, cutoff: string) {
  return rows.filter((r) => r.type === "candidate" && String(r.ts) <= cutoff);
}

function digest(rows: Array<Record<string, unknown>>): string {
  const h = crypto.createHash("sha256");
  for (const r of rows) h.update(JSON.stringify(r) + "\n");
  return h.digest("hex");
}

function arg(name: string): string | undefined {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] : undefined;
}

const cutoff = arg("--cutoff") ?? new Date().toISOString();
const out: Record<string, unknown> = {
  capturedAt: new Date().toISOString(),
  windowCutoff: cutoff,
  codeState: "pre-port (this tree has no src/lib/counterfactual-ledger.ts)",
  windowRule: "candidates with ts <= windowCutoff, plus the resolve set stored here",
  lanes: {},
};

for (const def of LANES) {
  const all = def.read();
  const candidates = windowRows(all, cutoff);
  const resolves = all
    .filter((r) => r.type === "resolve")
    .map((r) => [String(r.marketId), String(r.outcome), Number(r.value)]);
  // Pre-port summaries need the resolve rows too, in feed order after the candidates.
  const rows = [
    ...candidates,
    ...resolves.map(([marketId, outcome, value]) => ({ type: "resolve", marketId, outcome, value })),
  ];
  const summary = def.summarize(rows as never) as unknown as Record<string, unknown>;
  (out.lanes as Record<string, unknown>)[def.id] = {
    lane: def.lane,
    file: def.file.replace(/^.*\.worktrees\/[^/]+\//, ""),
    rowsSelected: candidates.length,
    resolvesSelected: resolves.length,
    rowsDigest: digest(candidates),
    resolves,
    summary,
  };
  console.log(
    `${def.id}: ${candidates.length} candidates <= ${cutoff} + ${resolves.length} resolves, ` +
      `digest ${digest(candidates).slice(0, 16)}, ` +
      `candidates=${(summary as Record<string, unknown>).candidates} marked=${(summary as Record<string, unknown>).marked}`
  );
}

fs.writeFileSync(GOLDEN_FILE, JSON.stringify(out, null, 2));
console.log(`\ngolden written: ${GOLDEN_FILE}`);
