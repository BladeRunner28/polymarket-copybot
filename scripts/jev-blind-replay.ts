/**
 * shadow:jev-blind — the BLIND arm's replay (card `jev-arm-blind-question`, approved 2026-10-10).
 *
 * WHY THIS EXISTS: the leading arm's first read tied the price (AUC 0.4420 vs 0.4374) while
 * reproducing it EXACTLY on 77.6% of legs, because the state handed the model `implied_probability`
 * and then asked it to re-derive that price. The fix is a different question shape, not a different
 * model: this replay re-asks each leg with the price WITHHELD (see `blindState` /
 * `buildBlindMessages`) and asks ONE question — does this token resolve as the winner.
 *
 * The states are already on disk (`data/jev-shadow.jsonl` carries the state that was sent), so this
 * is a pure replay: no DB reads, no collection, no writes to the lane's own files, and it cannot
 * touch a live lane. Output goes to its OWN file (`data/jev-blind.jsonl`) so the two arms never mix:
 *
 *   npx tsx scripts/jev-blind-replay.ts --dry-run     # print the blind prompt + assert no price
 *   npx tsx scripts/jev-blind-replay.ts               # replay the whole stored corpus (resumable)
 *
 * Resumable by construction: legs already present in the output file are skipped, and rows are
 * flushed every JEV_BLIND_FLUSH, so a kill mid-run costs at most that many calls.
 */

import * as fs from "fs";
import { join } from "path";
import {
  JEV_LOCAL_MODEL_DEFAULT,
  JEV_LOCAL_URL_DEFAULT,
  buildBlindMessages,
  callLocalChat,
  parseBlindReply,
} from "../src/lib/jev-local";
import { JEV_SHADOW_FILE, readJevRows, type JevShadowRow } from "../src/lib/shadow-jev";

const OUT_FILE = process.env.JEV_BLIND_FILE ?? join(__dirname, "..", "data", "jev-blind.jsonl");
const LIMIT = Number(process.env.JEV_BLIND_LIMIT ?? 4000);
const FLUSH = Number(process.env.JEV_BLIND_FLUSH ?? 100);
const TIMEOUT_MS = Number(process.env.JEV_TIMEOUT_MS ?? 8000);
const URL = process.env.JEV_LOCAL_URL ?? JEV_LOCAL_URL_DEFAULT;
const MODEL = process.env.JEV_BLIND_MODEL ?? process.env.JEV_MODEL ?? JEV_LOCAL_MODEL_DEFAULT;
const DRY = process.argv.includes("--dry-run");

interface BlindRow {
  ts: string;
  key: string;
  marketId: string;
  outcome: string;
  /** The DETECTION MID, stored for scoring only — it is never part of the prompt. */
  price: number;
  marketCategory: string | null;
  /** Also prompt-visible, kept for post-hoc bucketing (e.g. "is the answer constant near expiry?"). */
  ttrHours: number | null;
  model: string;
  jevBlindProbability: number | null;
  jevBlindConfidence: number | null;
  latencyMs: number;
  inputTokens: number | null;
  error: string | null;
}

const legKey = (r: JevShadowRow): string =>
  `${r.decisionJournalId ?? ""}|${r.marketId}|${r.outcome}`;

function readBlindKeys(): Set<string> {
  if (!fs.existsSync(OUT_FILE)) return new Set();
  const keys = new Set<string>();
  for (const line of fs.readFileSync(OUT_FILE, "utf8").split("\n")) {
    if (!line.trim()) continue;
    try {
      const r = JSON.parse(line) as BlindRow;
      // Only a row that CARRIES a probability counts as done: a failed call must be retried.
      if (r.jevBlindProbability !== null && r.jevBlindProbability !== undefined) keys.add(r.key);
    } catch {
      /* a torn last line is not a key */
    }
  }
  return keys;
}

async function main() {
  const rows = readJevRows(JEV_SHADOW_FILE);

  // One row per leg, preferring the row that carries the state (older rows predate it).
  const byKey = new Map<string, JevShadowRow>();
  for (const r of rows) {
    if (r.type !== "candidate") continue;
    const key = legKey(r);
    const prev = byKey.get(key);
    if (!prev || (r.state && !prev.state)) byKey.set(key, r);
  }
  const legs = [...byKey.values()].filter((r) => r.state && typeof r.state === "object");
  const withoutState = byKey.size - legs.length;

  const done = readBlindKeys();
  const todo = legs.filter((r) => !done.has(legKey(r))).slice(0, LIMIT);

  console.log(
    `jev-blind: ${byKey.size} legs on disk (${withoutState} without a stored state — not replayable), ` +
      `${done.size} already replayed, ${todo.length} to call. model=${MODEL} url=${URL}`
  );

  if (DRY) {
    const sample = todo[0] ?? legs[0];
    if (!sample) {
      console.log("jev-blind --dry-run: nothing to show.");
      return;
    }
    const price = Number(sample.entryPrice);
    const messages = buildBlindMessages(sample.state as Record<string, unknown>, String(sample.outcome));
    const blob = JSON.stringify(messages);
    // The one assertion this arm stands on: the price is nowhere in the prompt.
    const priceStrings = [String(price), price.toFixed(2), price.toFixed(3), String(price * 100)];
    const leaked = priceStrings.filter((p) => blob.includes(p));
    console.log(`--- blind prompt for ${sample.marketId} / ${sample.outcome} (price ${price}) ---`);
    console.log(messages.system);
    console.log("");
    console.log(messages.user);
    console.log("");
    console.log(
      leaked.length
        ? `PRICE-LEAK CHECK: FAILED — prompt contains ${JSON.stringify(leaked)}`
        : `PRICE-LEAK CHECK: clean — neither the stored price nor its cent/percent spellings appear in the prompt.`
    );
    return;
  }

  const batch: BlindRow[] = [];
  let ok = 0;
  let failed = 0;
  let doneCount = 0;
  const latencies: number[] = [];
  const flush = () => {
    if (!batch.length) return;
    fs.appendFileSync(OUT_FILE, batch.map((r) => JSON.stringify(r)).join("\n") + "\n");
    batch.length = 0;
  };

  for (const leg of todo) {
    const price = Number(leg.entryPrice);
    const messages = buildBlindMessages(leg.state as Record<string, unknown>, String(leg.outcome));
    const r = await callLocalChat({ url: URL, model: MODEL, messages, timeoutMs: TIMEOUT_MS });
    const parsed = r.error ? null : parseBlindReply(r.content);
    if (parsed) ok++;
    else failed++;
    latencies.push(r.latencyMs);
    batch.push({
      ts: new Date().toISOString(),
      key: legKey(leg),
      marketId: String(leg.marketId),
      outcome: String(leg.outcome),
      price,
      marketCategory: (leg.marketCategory as string) ?? null,
      ttrHours: (leg.ttrHours as number) ?? null,
      model: MODEL,
      jevBlindProbability: parsed ? parsed.probability : null,
      jevBlindConfidence: parsed ? parsed.confidence : null,
      latencyMs: r.latencyMs,
      inputTokens: r.promptTokens,
      error: r.error ?? (parsed ? null : r.content.trim() ? "unparsed payload shape" : "empty content"),
    });
    if (batch.length >= FLUSH) {
      flush();
      doneCount += FLUSH;
      const med = latencies.slice(-FLUSH).sort((a, b) => a - b)[Math.floor(FLUSH / 2)];
      console.log(
        `jev-blind: ${doneCount}/${todo.length} replayed, ${ok} answered, ${failed} failed, median ${med} ms/call`
      );
    }
  }
  flush();
  console.log(
    `jev-blind: done — ${ok}/${todo.length} answered, ${failed} failed. Wrote ${OUT_FILE}. ` +
      `Read it with: python3 scripts/jev-blind-read.py`
  );
}

main().catch((e) => {
  console.error("shadow:jev-blind FAILED:", e);
  process.exit(1);
});
