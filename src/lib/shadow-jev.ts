/**
 * Jev shadow lane (Option B of `drafts/jev-rag-copybot.md`, user-approved 2026-10-06).
 *
 * WRITE-ONLY INSTRUMENT. Nothing here gates a copy, changes a size, or touches a RuleSet.
 * The lane logs, per copy-eligible leg, (a) the typed state we would send to Jev and
 * (b) Jev's calibrated probability when a call is configured, then marks the leg to
 * settlement and compares TWO predictors on the same rows:
 *
 *   arm A: the PRICE baseline  — the market's own implied probability (entry price)
 *   arm B: Jev                 — its stated probability
 *
 * The pre-registered bar (below) is deliberately NOT "beat copyScore": at leg grain the
 * stored wallet scores are coin flips (AUC 0.43-0.50) while the price baseline is 0.653
 * (C-200) / 0.758 (STANDARD), and the ML-1 card already fixed this bar as "beat the
 * price-only baseline on net-of-fee PnL". A Jev arm that beats copyScore and loses to the
 * price has measured nothing.
 *
 * Why the lane exists at all: `typesafe/jev-1.13` (TypeSafe "System One", via OpenRouter's
 * Decisions API) returns a calibrated probability for a typed state — the one type
 * CopyBot's deterministic points score cannot produce. It cannot browse, so the evidence
 * it reasons over has to be assembled for it: that is the RAG slot (Option A), and this
 * file is the instrument that will price whether the assembly is worth anything.
 *
 * DEFAULT OFF: JEV_SHADOW=1 plus a provider key (OPENROUTER_API_KEY / JEV_API_KEY) are required
 * before a single call is made. The ENDPOINT is no longer a guess: the Decisions API route was
 * unverified when this lane was built, and on 2026-10-06 OpenRouter published it in its own API
 * reference (POST /api/alpha/decisions), so it is now a documented default rather than something
 * invented in code — JEV_ENDPOINT survives as an override (proxy, mock, a different route).
 * Until the key exists the marker collects states only (they are free and they are the real
 * population).
 *
 * WIRE CONTRACT (verified 2026-10-06 against OpenRouter's `POST /api/alpha/decisions` reference,
 * schemas DecisionsRequest / DecisionsNoulQuestion / DecisionsChoiceQuestion / DecisionsNoulAnswer
 * / DecisionsChoiceAnswer). Request: { model, state: string|object|array, questions: an OBJECT
 * keyed by question name } where each question is { type: "noul", instructions } (criteria
 * optional) or { type: "choice", instructions, criteria: { option: criterion, ... } } (criteria
 * REQUIRED). Response: { model, answers: { name: { type: "noul", noul: 0.96 } |
 * { type: "choice", choice: "copy", probabilities?, confidence? } }, usage: { input_tokens,
 * output_tokens, cost? } }. The first cut of this file emitted `questions` as an ARRAY with
 * `kind`/`question` field names and read only `.probability` — that payload would have 400'd
 * every call and parsed as null. buildJevRequest() is the single place that shape is produced.
 */

import * as fs from "fs";
import { join } from "path";

export const JEV_SHADOW_FILE = join(__dirname, "..", "..", "data", "jev-shadow.jsonl");
export const JEV_SHADOW_SUMMARY_FILE = join(__dirname, "..", "..", "data", "jev-shadow-summary.json");

/** Pinned model id; override only to A/B a new revision, and keep the id on every row. */
export const JEV_MODEL_DEFAULT = "typesafe/jev-1.13";

/**
 * The Decisions API route, VERIFIED 2026-10-06 against OpenRouter's public API reference
 * (`POST /api/alpha/decisions`, model `typesafe/jev-1.13` or the `~typesafe/jev-latest` alias;
 * the System One mirror for the official TypeSafe SDKs is `POST /api/v1/systemone`). Pricing
 * $0.042 / 1M input tokens, output free, 32k context. No waitlist and no separate TypeSafe
 * account as of that date — an ordinary OpenRouter key is the only credential.
 */
export const JEV_ENDPOINT_DEFAULT = "https://openrouter.ai/api/alpha/decisions";

/** Minimum resolved legs before the bar is even readable. */
export const JEV_MIN_RESOLVED_LEGS = 50;

/**
 * PRE-REGISTERED 2026-10-06, before any Jev call was made (no key exists yet, so this is
 * genuinely blind). Promote nothing unless ALL hold, out-of-sample, on resolved legs:
 *   1. Brier(jevP) < Brier(entryPrice) on the same rows,
 *   2. AUC(jevP) > AUC(entryPrice),
 *   3. the counterfactual gate (skip legs with jevP below threshold) improves net-of-fee
 *      PnL per leg against copying everything, AND
 *   4. it also beats the existing copyScore arm on the same rows.
 * A veto count is not a cost: the report must show the PnL of the vetoed set, not how many
 * legs were vetoed.
 */
export const JEV_PREREGISTRATION =
  "PRE-REGISTERED 2026-10-06: bar = n>=" + JEV_MIN_RESOLVED_LEGS +
  " resolved legs AND Brier(jev) < Brier(entryPrice) AND AUC(jev) > AUC(entryPrice) AND " +
  "net-of-fee counterfactual PnL/leg at the gate beats copy-all AND beats copyScore. " +
  "No promotion of any kind before all four hold.";

/**
 * The three Jev primitives are noul (yes/no probability), choice (one of N) and score (an
 * ordered scale). This lane only uses the first two: a score needs a legend whose levels we
 * cannot calibrate yet, and calibration is the entire reason the lane exists.
 */
export type JevQuestionKind = "noul" | "choice";

export interface JevQuestion {
  key: string;
  kind: JevQuestionKind;
  /** Goes on the wire as `instructions` — same word, so there is no rename to get wrong. */
  instructions: string;
  /** kind=choice: option → that option's own criterion. REQUIRED on the wire for choice. */
  criteria?: Record<string, string>;
  /** kind=noul: what true and false mean here; the wire schema requires BOTH keys if sent. */
  noulCriteria?: { true: string; false: string };
}

/** The wire question object, exactly as the Decisions API reference defines it. */
export interface JevWireQuestion {
  type: JevQuestionKind;
  instructions: string;
  criteria?: Record<string, string>;
}

export interface JevRequest {
  model: string;
  state: Record<string, unknown>;
  /** An OBJECT keyed by question name — never an array. */
  questions: Record<string, JevWireQuestion>;
}

export interface JevLeg {
  /** Identity + row keys, mirroring the other shadow feeds. */
  decisionJournalId?: string | null;
  marketId: string;
  outcome: string;
  side: string;
  walletAddress: string;
  /** Prices in probability space, as the scorer saw them. */
  entryPrice: number;
  /** The lane's BOOKED entry when a copy actually opened (C-200 books mid − 2¢ via the
   * sidecar). Kept beside the detection mid so no read compares the two fill models. */
  bookedEntryPrice?: number | null;
  detectedPrice?: number | null;
  walletEntryPrice?: number | null;
  spread?: number | null;
  liquidity?: number | null;
  ttrHours?: number | null;
  copyScore: number;
  confidence: number;
  /** The live decision ("paper_copy" | "watchlist" | "skip"). */
  liveDecision: string;
  lane?: string | null;
  marketQuestion?: string | null;
  marketCategory?: string | null;
  /** Ruleset in force when the leg was scored — the regime split needs it. */
  ruleSetVersion?: number | null;
}

/** The typed state handed to Jev: everything it may reason over, nothing it cannot. */
export function buildJevState(leg: JevLeg): Record<string, unknown> {
  const drift =
    leg.walletEntryPrice === undefined || leg.walletEntryPrice === null
      ? null
      : Math.abs(leg.entryPrice - leg.walletEntryPrice);
  return {
    market: {
      id: leg.marketId,
      question: leg.marketQuestion ?? null,
      category: leg.marketCategory ?? null,
      outcome_token: leg.outcome,
      implied_probability: leg.entryPrice,
      spread: leg.spread ?? null,
      liquidity_usd: leg.liquidity ?? null,
      hours_to_resolution: leg.ttrHours ?? null,
    },
    signal: {
      side: leg.side,
      copied_wallet: leg.walletAddress,
      wallet_fill_price: leg.walletEntryPrice ?? null,
      detection_mid: leg.detectedPrice ?? null,
      price_drift: drift,
      copybot_decision: leg.liveDecision,
      copybot_copy_score: leg.copyScore,
      copybot_confidence: leg.confidence,
      lane: leg.lane ?? null,
    },
    rule_set_version: leg.ruleSetVersion ?? null,
  };
}

/**
 * The typed questions. Kept deliberately small and binary: the vendor documents a
 * 255-option cardinality ceiling and a two-stage fallback above it, and per-leg
 * binary questions are the case that costs nothing extra.
 */
export function buildJevQuestions(leg: JevLeg): JevQuestion[] {
  const outcome = leg.outcome;
  return [
    {
      key: "outcome_wins",
      kind: "noul",
      instructions:
        `Does the token "${outcome}" resolve as the winning outcome of this market? ` +
        "Answer yes if it does, no if it does not, at the given hours_to_resolution.",
      noulCriteria: {
        true: `"${outcome}" is the outcome the market resolves to.`,
        false: `"${outcome}" is not the outcome the market resolves to, or the market voids.`,
      },
    },
    {
      key: "beats_entry",
      kind: "noul",
      instructions:
        `Buying "${outcome}" at implied_probability ${leg.entryPrice} pays out 1 if it wins and ` +
        "0 if it loses. Is that purchase profitable after fees?",
      noulCriteria: {
        true: `The win probability is high enough that buying at ${leg.entryPrice} is +EV after fees.`,
        false: `The win probability is too low for buying at ${leg.entryPrice} to clear fees.`,
      },
    },
    {
      key: "action",
      kind: "choice",
      instructions: "Should this leg be copied, watched, or skipped?",
      criteria: {
        copy: "The evidence supports opening this position now.",
        watch: "The evidence is mixed; it does not support opening now and does not forbid it.",
        skip: "The evidence argues against opening this position.",
      },
    },
  ];
}

/**
 * THE wire body. One place, built only from the documented Decisions API shape — this is what
 * callJev posts. Anything that needs to change about the questions (a wording, a new primitive)
 * changes here and nowhere else, and tests/shadow-jev.test.ts asserts the response contract
 * against the vendor's own example payload.
 */
export function buildJevRequest(leg: JevLeg, model: string = JEV_MODEL_DEFAULT): JevRequest {
  const questions: Record<string, JevWireQuestion> = {};
  for (const q of buildJevQuestions(leg)) {
    const criteria = q.kind === "noul" ? q.noulCriteria : q.criteria;
    questions[q.key] = { type: q.kind, instructions: q.instructions, ...(criteria ? { criteria } : {}) };
  }
  return { model, state: buildJevState(leg), questions };
}

export interface JevDecision {
  /** Probability for `outcome_wins`, 0..1. */
  probability: number | null;
  /** Same for `beats_entry` when present. */
  beatsEntryProbability: number | null;
  /** Model-stated confidence, 0..1, when present. */
  confidence: number | null;
  action: string | null;
  /** The response's own usage block, stored so the lane's cost is measured, not assumed. */
  usage?: JevUsage | null;
}

/** Token counts and the billed cost from the Decisions response (`usage`). */
export interface JevUsage {
  inputTokens: number | null;
  outputTokens: number | null;
  costUsd: number | null;
}

function num(v: unknown): number | null {
  const n = typeof v === "string" ? Number(v) : v;
  if (typeof n !== "number" || !Number.isFinite(n)) return null;
  return n;
}

function clamp01(n: number | null): number | null {
  if (n === null) return null;
  if (n < 0) return 0;
  if (n > 1) return 1;
  return n;
}

/**
 * Parse a Decisions-API response defensively. The vendor's type-safety guarantee covers ITS
 * schema, not our mapper — so a payload we do not recognise returns null and the raw body is
 * stored on the row instead of an invented number.
 *
 * The documented shapes are read FIRST: noul answers carry `{ type: "noul", noul: 0.96 }` and
 * choice answers `{ type: "choice", choice: "copy", probabilities?, confidence? }`. The older
 * `.probability` / bare-string / array forms stay supported because rows written before
 * provisioning may be replayed, and tolerance costs nothing — an unrecognised value is still
 * null, never a guess.
 */
export function parseJevDecision(payload: unknown): JevDecision {
  const empty: JevDecision = {
    probability: null,
    beatsEntryProbability: null,
    confidence: null,
    action: null,
    usage: null,
  };
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return empty;
  const root = payload as Record<string, unknown>;

  // The documented container is `answers`; the rest is tolerance for a wrapper change.
  let answers: Record<string, unknown> = root;
  for (const k of ["answers", "decisions", "result", "output", "decision"]) {
    const v = root[k];
    if (v && typeof v === "object" && !Array.isArray(v)) {
      answers = v as Record<string, unknown>;
      break;
    }
  }
  const pick = (key: string): unknown => {
    const direct = answers[key] ?? root[key];
    if (direct !== undefined) return direct;
    // array form: [{key, noul|probability|value|answer}]
    const arr = (answers.questions ?? root.answers) as unknown;
    if (Array.isArray(arr)) {
      for (const item of arr) {
        if (item && typeof item === "object") {
          const o = item as Record<string, unknown>;
          if (o.key === key || o.name === key || o.id === key)
            return o.noul ?? o.probability ?? o.value ?? o.answer;
        }
      }
    }
    return undefined;
  };
  /** The answer object for a key, or null when the key is absent. */
  const answerOf = (key: string): Record<string, unknown> | null => {
    const raw = pick(key);
    return raw && typeof raw === "object" && !Array.isArray(raw) ? (raw as Record<string, unknown>) : null;
  };

  // noul: documented key first, then the older spellings, then a bare number.
  const readProb = (key: string): number | null => {
    const raw = pick(key);
    if (raw === null || raw === undefined) return null;
    if (raw && typeof raw === "object") {
      const o = raw as Record<string, unknown>;
      return clamp01(num(o.noul ?? o.probability ?? o.p ?? o.value ?? o.score));
    }
    return clamp01(num(raw));
  };

  // choice: documented key first, then the older spellings.
  const readChoice = (key: string): string | null => {
    const raw = pick(key);
    if (typeof raw === "string") return raw;
    if (raw && typeof raw === "object") {
      const o = raw as Record<string, unknown>;
      const c = o.choice ?? o.value ?? o.label ?? o.answer;
      return typeof c === "string" ? c : null;
    }
    return null;
  };

  // Confidence is per-answer in the documented shape (choice carries it; noul does not).
  const confRaw = answerOf("action")?.confidence ?? answerOf("outcome_wins")?.confidence ?? root.confidence;
  const confidence = clamp01(
    confRaw && typeof confRaw === "object"
      ? num((confRaw as Record<string, unknown>).confidence ?? (confRaw as Record<string, unknown>).value)
      : num(confRaw)
  );

  // usage: { input_tokens, output_tokens, cost? } — the lane's real cost per call.
  const u = root.usage && typeof root.usage === "object" ? (root.usage as Record<string, unknown>) : null;
  const usage = u
    ? {
        inputTokens: num(u.input_tokens ?? u.inputTokens),
        outputTokens: num(u.output_tokens ?? u.outputTokens),
        costUsd: num(u.cost ?? u.costUsd),
      }
    : null;

  return {
    probability: readProb("outcome_wins"),
    beatsEntryProbability: readProb("beats_entry"),
    confidence,
    action: readChoice("action"),
    usage,
  };
}

/**
 * Is the lane allowed to make outbound calls? Default OFF. The endpoint now falls back to the
 * route OpenRouter documents (JEV_ENDPOINT_DEFAULT) instead of refusing, because that route is
 * verified rather than guessed; JEV_ENDPOINT only needs setting to point somewhere else. The
 * flag and the key are still both required, so nothing here can call out on its own.
 */
export function jevCallConfig(env: Record<string, string | undefined> = process.env): {
  canCall: boolean;
  reason: string;
  endpoint: string | null;
  model: string;
} {
  const model = env.JEV_MODEL ?? JEV_MODEL_DEFAULT;
  const endpoint = env.JEV_ENDPOINT ?? JEV_ENDPOINT_DEFAULT;
  if (env.JEV_SHADOW !== "1") return { canCall: false, reason: "JEV_SHADOW is not 1 (default off)", endpoint, model };
  const key = env.OPENROUTER_API_KEY ?? env.JEV_API_KEY;
  if (!key) return { canCall: false, reason: "no OPENROUTER_API_KEY/JEV_API_KEY", endpoint, model };
  return { canCall: true, reason: "enabled", endpoint, model };
}

export interface JevShadowRow extends Record<string, unknown> {
  ts: string;
  type: "candidate" | "resolve";
}

/** One candidate row: the state, the model arm (null until a key exists), the price arm. */
export function buildCandidateRow(
  leg: JevLeg,
  decision: JevDecision | null,
  meta: { model: string; latencyMs: number | null; error?: string | null; raw?: unknown } = { model: JEV_MODEL_DEFAULT, latencyMs: null }
): JevShadowRow {
  return {
    ts: new Date().toISOString(),
    type: "candidate",
    source: "jev_shadow",
    model: meta.model,
    decisionJournalId: leg.decisionJournalId ?? null,
    marketId: leg.marketId,
    outcome: leg.outcome,
    side: leg.side,
    wallet: leg.walletAddress,
    marketQuestion: leg.marketQuestion ?? null,
    marketCategory: leg.marketCategory ?? null,
    lane: leg.lane ?? null,
    ruleSetVersion: leg.ruleSetVersion ?? null,
    // ---- price arm (the bar) ----
    entryPrice: leg.entryPrice,
    bookedEntryPrice: leg.bookedEntryPrice ?? null,
    detectedPrice: leg.detectedPrice ?? null,
    walletEntryPrice: leg.walletEntryPrice ?? null,
    spread: leg.spread ?? null,
    liquidity: leg.liquidity ?? null,
    ttrHours: leg.ttrHours ?? null,
    copyScore: leg.copyScore,
    confidence: leg.confidence,
    liveDecision: leg.liveDecision,
    // ---- model arm ----
    jevProbability: decision?.probability ?? null,
    jevBeatsEntryProbability: decision?.beatsEntryProbability ?? null,
    jevConfidence: decision?.confidence ?? null,
    jevAction: decision?.action ?? null,
    jevLatencyMs: meta.latencyMs,
    jevError: meta.error ?? null,
    jevCostUsd: decision?.usage?.costUsd ?? null,
    jevInputTokens: decision?.usage?.inputTokens ?? null,
    jevRaw: meta.raw === undefined ? null : meta.raw,
    state: buildJevState(leg),
  };
}

/** Append rows; JSONL, same style as the other shadow feeds. */
export function appendJevRows(rows: JevShadowRow[], file = JEV_SHADOW_FILE): void {
  if (!rows.length) return;
  fs.appendFileSync(file, rows.map((r) => JSON.stringify(r)).join("\n") + "\n");
}

export function readJevRows(file = JEV_SHADOW_FILE): JevShadowRow[] {
  try {
    return fs
      .readFileSync(file, "utf-8")
      .split("\n")
      .filter((l) => l.trim().length > 0)
      .map((l) => JSON.parse(l) as JevShadowRow);
  } catch {
    return [];
  }
}

/**
 * Taker fee per share for the archive-era schedule (0.10 × min(p, 1−p)). The schedule has
 * changed several times since that era — RE-CONFIRM it at the read (see the ops skill's
 * archive-fee reference) before quoting a net figure as final.
 */
export function takerFeePerShare(price: number): number {
  return 0.1 * Math.min(price, 1 - price);
}

/** Rank-based AUC (Mann-Whitney), average ranks on ties. Null when one class is empty. */
export function auc(scores: number[], labels: number[]): number | null {
  const n = scores.length;
  if (n !== labels.length || n === 0) return null;
  const pos = labels.filter((l) => l === 1).length;
  const neg = n - pos;
  if (pos === 0 || neg === 0) return null;
  const idx = scores.map((s, i) => [s, i] as const).sort((a, b) => a[0] - b[0]);
  const ranks = new Array<number>(n);
  let i = 0;
  while (i < n) {
    let j = i;
    while (j + 1 < n && idx[j + 1][0] === idx[i][0]) j++;
    const avg = (i + j) / 2 + 1; // 1-based average rank
    for (let k = i; k <= j; k++) ranks[idx[k][1]] = avg;
    i = j + 1;
  }
  let sumPosRanks = 0;
  for (let k = 0; k < n; k++) if (labels[k] === 1) sumPosRanks += ranks[k];
  return (sumPosRanks - (pos * (pos + 1)) / 2) / (pos * neg);
}

export function brier(probs: number[], labels: number[]): number | null {
  const n = probs.length;
  if (n === 0 || n !== labels.length) return null;
  let s = 0;
  for (let i = 0; i < n; i++) s += (probs[i] - labels[i]) ** 2;
  return s / n;
}

export function logLoss(probs: number[], labels: number[]): number | null {
  const n = probs.length;
  if (n === 0 || n !== labels.length) return null;
  const eps = 1e-6;
  let s = 0;
  for (let i = 0; i < n; i++) {
    const p = Math.min(1 - eps, Math.max(eps, probs[i]));
    s += -(labels[i] * Math.log(p) + (1 - labels[i]) * Math.log(1 - p));
  }
  return s / n;
}

interface ScoredLeg {
  label: number;
  jev: number | null;
  price: number;
  copyScore: number | null;
  entryPrice: number;
  pnlPerStake: number;
}

export interface JevShadowSummary {
  generatedAt: string;
  preregistration: string;
  candidates: number;
  /** Rows carrying a Jev probability. */
  withModel: number;
  /** Candidates with a settlement record. */
  resolved: number;
  resolvedWithModel: number;
  /** Arm A — the bar. */
  priceOnly: { n: number; auc: number | null; brier: number | null; logLoss: number | null; meanPnlPerStake: number | null; meanPnlPerStakeNetOfFee: number | null };
  /** Arm B — Jev. */
  jev: { n: number; auc: number | null; brier: number | null; logLoss: number | null; meanPnlPerStake: number | null; meanPnlPerStakeNetOfFee: number | null };
  /** Arm C — the incumbent score, only to show it is not the arbiter. */
  copyScore: { n: number; auc: number | null; brier: number | null };
  /** Counterfactual gate at a fixed jevP threshold: kept vs vetoed legs. */
  gate: {
    threshold: number;
    keptN: number;
    keptMeanPnlPerStakeNetOfFee: number | null;
    vetoedN: number;
    vetoedMeanPnlPerStakeNetOfFee: number | null;
    copyAllMeanPnlPerStakeNetOfFee: number | null;
    improves: boolean | null;
  };
  /** Pre-registered verdict; null until the sample reaches the minimum. */
  beatsPriceOnly: boolean | null;
  barReadable: boolean;
  feeModel: string;
}

/**
 * Join candidates to resolutions and compare the arms on the SAME rows. Labels:
 * a leg is "good" when the token won at a price where that is profitable (value >
 * entry), which is exactly the question the price arm predicts with `entryPrice`.
 */
export function summarizeJev(rows: JevShadowRow[], threshold = Number(process.env.JEV_GATE_THRESHOLD ?? 0.55)): JevShadowSummary {
  // Dedupe by leg: a row can be re-appended when the model arm is backfilled onto a
  // state-only row (or re-collected after a failed call). Prefer the row that carries a
  // model arm, else the newest — counting both would double-count the leg in every arm.
  const byKey = new Map<string, JevShadowRow>();
  for (const r of rows) {
    if (r.type !== "candidate") continue;
    const key = `${r.decisionJournalId ?? ""}|${r.marketId}|${r.outcome}`;
    const prev = byKey.get(key);
    if (!prev) {
      byKey.set(key, r);
      continue;
    }
    const prevHas = prev.jevProbability !== null && prev.jevProbability !== undefined;
    const curHas = r.jevProbability !== null && r.jevProbability !== undefined;
    if (curHas && !prevHas) byKey.set(key, r);
    else if (curHas === prevHas && String(r.ts) >= String(prev.ts)) byKey.set(key, r);
  }
  const candidates = [...byKey.values()];
  const resolves = new Map<string, number>();
  for (const r of rows) {
    if (r.type === "resolve") resolves.set(`${r.marketId}|${r.outcome}`, Number(r.value));
  }
  const scored: ScoredLeg[] = [];
  for (const c of candidates) {
    const v = resolves.get(`${c.marketId}|${c.outcome}`);
    if (v === undefined) continue;
    const entry = Number(c.entryPrice);
    if (!Number.isFinite(entry) || entry <= 0) continue;
    const won = v === 1;
    const pnlPerStake = won ? (1 - entry) / entry : -1;
    scored.push({
      label: v > entry ? 1 : 0,
      jev: c.jevProbability === null || c.jevProbability === undefined ? null : Number(c.jevProbability),
      price: entry,
      copyScore: c.copyScore === undefined ? null : Number(c.copyScore),
      entryPrice: entry,
      pnlPerStake,
    });
  }

  const mean = (xs: number[]): number | null => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);
  const netOf = (leg: ScoredLeg): number => {
    const fee = takerFeePerShare(leg.entryPrice);
    return leg.label === 1
      ? (1 - leg.entryPrice - fee) / leg.entryPrice
      : -1 - fee / leg.entryPrice;
  };
  const stats = (probs: number[], labels: number[]) => ({
    n: probs.length,
    auc: auc(probs, labels),
    brier: brier(probs, labels),
    logLoss: logLoss(probs, labels),
  });

  const all = scored;
  const withModel = scored.filter((s) => s.jev !== null);

  const priceOnly = {
    ...stats(all.map((s) => s.price), all.map((s) => s.label)),
    meanPnlPerStake: mean(all.map((s) => s.pnlPerStake)),
    meanPnlPerStakeNetOfFee: mean(all.map(netOf)),
  };
  const jev = {
    ...stats(withModel.map((s) => s.jev as number), withModel.map((s) => s.label)),
    meanPnlPerStake: mean(withModel.map((s) => s.pnlPerStake)),
    meanPnlPerStakeNetOfFee: mean(withModel.map(netOf)),
  };
  const withScore = scored.filter((s) => s.copyScore !== null);
  const copyScore = stats(withScore.map((s) => s.copyScore as number), withScore.map((s) => s.label));

  const kept = withModel.filter((s) => (s.jev as number) >= threshold);
  const vetoed = withModel.filter((s) => (s.jev as number) < threshold);
  const copyAllNet = mean(withModel.map(netOf));
  const keptNet = mean(kept.map(netOf));
  const vetoedNet = mean(vetoed.map(netOf));

  const barReadable = withModel.length >= JEV_MIN_RESOLVED_LEGS;
  const beatsPriceOnly =
    !barReadable || jev.brier === null || priceOnly.brier === null || jev.auc === null || priceOnly.auc === null
      ? null
      : jev.brier < priceOnly.brier && jev.auc > priceOnly.auc && keptNet !== null && copyAllNet !== null && keptNet > copyAllNet;

  return {
    generatedAt: new Date().toISOString(),
    preregistration: JEV_PREREGISTRATION,
    candidates: candidates.length,
    withModel: withModel.length,
    resolved: all.length,
    resolvedWithModel: withModel.length,
    priceOnly,
    jev,
    copyScore,
    gate: {
      threshold,
      keptN: kept.length,
      keptMeanPnlPerStakeNetOfFee: keptNet,
      vetoedN: vetoed.length,
      vetoedMeanPnlPerStakeNetOfFee: vetoedNet,
      copyAllMeanPnlPerStakeNetOfFee: copyAllNet,
      improves: keptNet === null || copyAllNet === null ? null : keptNet > copyAllNet,
    },
    beatsPriceOnly,
    barReadable,
    feeModel:
      "taker 0.10 x min(p,1-p) per share (archive era) — RE-CONFIRM the era's schedule at the read before quoting a net figure",
  };
}
