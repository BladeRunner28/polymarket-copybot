/**
 * Local-model adapter for the Jev shadow lane.
 *
 * WHY THIS EXISTS: the lane's wire contract (`buildJevRequest` -> OpenRouter's Decisions route) asks
 * three typed questions — two `noul` probabilities and one `choice` — and reads the answers back out
 * of an `answers` container. A local Ollama model speaks none of that: it takes messages and returns
 * text. This module is the translation, and only the translation:
 *
 *   request (the SAME body the vendor route would receive) -> chat messages,
 *   chat text -> the `{answers: {...}}` container `parseJevDecision()` already accepts.
 *
 * Single-sourcing matters here: the prompt is rendered FROM `buildJevRequest()`, so a local arm
 * answers exactly the propositions the vendor arm would be asked. If the questions change, both arms
 * move together and neither can drift into measuring a different question.
 *
 * MEASURED on Odin (RTX 5070 12GB, qwen3.5:9b, 2026-10-10), one real leg:
 *   think omitted  -> 8.3 s, 400 tokens, content EMPTY (the reasoning budget ate the answer)
 *   think: false   -> 1.1 s, 44 tokens, all three keys, valid JSON
 * so the caller must send `think: false` (top-level on /api/chat — the skill's documented knob; it is
 * silently ignored on /v1). Reasoning models otherwise fail as "unparsed payload shape", not as an
 * obvious error, which is exactly the trap this note exists to stop.
 */

import {
  type JevRequest,
  JEV_LOCAL_MODEL_DEFAULT,
  JEV_LOCAL_URL_DEFAULT,
  parseJevDecision,
} from "./shadow-jev";

export { JEV_LOCAL_MODEL_DEFAULT, JEV_LOCAL_URL_DEFAULT };

export interface LocalMessages {
  system: string;
  user: string;
}

/** The reply contract, stated to the model. Kept explicit because JSON mode only guarantees syntax. */
const SCHEMA_LINE =
  '{"outcome_wins":{"probability":<0-1>,"confidence":<0-1>},' +
  '"beats_entry":{"probability":<0-1>,"confidence":<0-1>},' +
  '"action":{"choice":"copy"|"watch"|"skip","confidence":<0-1>}}';

export function buildLocalMessages(req: JevRequest): LocalMessages {
  const system = [
    "You are a calibrated forecasting assistant scoring a trading decision.",
    "Answer with ONE JSON object and nothing else — no prose, no markdown, no code fences.",
    "Shape:",
    SCHEMA_LINE,
    "`probability` is your belief the proposition is TRUE, 0..1. Give your honest belief: a well",
    "calibrated 0.6 should be right about 60% of the time. Use the same three keys verbatim.",
  ].join("\n");

  const lines: string[] = [];
  lines.push("STATE");
  lines.push(JSON.stringify(req.state, null, 1));
  lines.push("");
  lines.push("QUESTIONS (answer every one)");
  for (const [key, q] of Object.entries(req.questions)) {
    lines.push(`- ${key} (${q.type}): ${q.instructions}`);
    if (q.criteria) {
      for (const [label, text] of Object.entries(q.criteria)) lines.push(`    ${label}: ${text}`);
    }
  }
  lines.push("");
  lines.push("Return the single JSON object now.");
  return { system, user: lines.join("\n") };
}

/**
 * Pull the first balanced JSON object out of a model reply.
 *
 * Local models wrap JSON in code fences, prepend "Here is the answer:", or emit the object after a
 * sentence of reasoning. None of that should read as a lane failure, so the extraction is tolerant —
 * but it never guesses: no balanced object means null, and the row records the failure.
 */
export function extractJsonObject(text: string): unknown | null {
  if (!text) return null;
  const cleaned = text.replace(/```(?:json)?/gi, "").trim();
  try {
    return JSON.parse(cleaned);
  } catch {
    /* fall through to the balanced scan */
  }
  const start = cleaned.indexOf("{");
  if (start < 0) return null;
  let depth = 0;
  let inStr = false;
  let esc = false;
  for (let i = start; i < cleaned.length; i++) {
    const ch = cleaned[i];
    if (inStr) {
      if (esc) esc = false;
      else if (ch === "\\") esc = true;
      else if (ch === '"') inStr = false;
      continue;
    }
    if (ch === '"') inStr = true;
    else if (ch === "{") depth++;
    else if (ch === "}") {
      depth--;
      if (depth === 0) {
        try {
          return JSON.parse(cleaned.slice(start, i + 1));
        } catch {
          return null;
        }
      }
    }
  }
  return null;
}

/** Probability spellings a local model may use for a bare number or a keyed object. */
const PROB_KEYS = ["probability", "noul", "p", "value", "score", "prob"];

/**
 * Normalize one answer into the shape `readProb`/`readChoice` already read.
 *
 * A model that answers 62 for 62% is common enough to handle: a number in (1, 100] is divided by 100
 * (a genuine 1.0 stays 1.0). Anything else out of range is clamped, never dropped — an unusable
 * answer shows up as a boundary value the report can see, not as a silent null.
 */
export function normalizeAnswer(raw: unknown): unknown {
  if (typeof raw === "number") return { probability: scaleProb(raw) };
  if (typeof raw === "string") {
    const t = raw.trim();
    if (t === "") return null;
    const asNum = Number(t);
    if (Number.isFinite(asNum) && /^-?[0-9.]+$/.test(t)) return { probability: scaleProb(asNum) };
    return { choice: t.toLowerCase() };
  }
  if (raw && typeof raw === "object" && !Array.isArray(raw)) {
    const o = { ...(raw as Record<string, unknown>) };
    for (const k of PROB_KEYS) {
      if (typeof o[k] === "number") {
        o[k] = scaleProb(o[k] as number);
        return o;
      }
    }
    return o;
  }
  return null;
}

function scaleProb(n: number): number {
  const v = n > 1 && n <= 100 ? n / 100 : n;
  if (!Number.isFinite(v)) return 0;
  return Math.min(1, Math.max(0, v));
}

/**
 * The container `parseJevDecision()` expects, or null when the reply carried no usable object.
 * Keys the model omitted stay omitted — the parser treats an absent key as null, which is honest.
 */
export function parseLocalReply(text: string): Record<string, unknown> | null {
  const obj = extractJsonObject(text);
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return null;
  const src = obj as Record<string, unknown>;
  // tolerate a wrapper: {"answers": {...}} / {"result": {...}} / {"decisions": {...}}
  let answers: Record<string, unknown> = src;
  for (const k of ["answers", "decisions", "result", "output", "decision"]) {
    const v = src[k];
    if (v && typeof v === "object" && !Array.isArray(v)) {
      answers = v as Record<string, unknown>;
      break;
    }
  }
  const out: Record<string, unknown> = {};
  for (const key of ["outcome_wins", "beats_entry", "action"]) {
    if (answers[key] !== undefined) {
      const n = normalizeAnswer(answers[key]);
      if (n !== null) out[key] = n;
    }
  }
  return Object.keys(out).length ? out : null;
}

/* ---------------------------------------------------------------------------------------------
 * THE BLIND ARM (card `jev-arm-blind-question`)
 *
 * The first read of the leading arm failed for a structural reason, not a model reason: the state
 * handed the model `implied_probability` (and two more price-level fields) and then asked it to
 * re-derive that same price — 77.6% of its answers came back as an EXACT echo of the detection mid.
 * The blind arm removes the price from the prompt entirely and asks ONE question — does this token
 * resolve as the winner — so the answer is the model's own belief, with the price used only
 * AFTERWARDS, for scoring.
 *
 * It reuses the stored states, so the whole test is a replay: no new collection, no DB work, and it
 * cannot touch a live lane.
 * ------------------------------------------------------------------------------------------- */

/**
 * Every field in the vendor state that carries the market price or a near-substitute for it.
 *
 * `implied_probability` is the price itself; `detection_mid` IS the entry price on these legs
 * (collectLegs sets entryPrice = detectedPrice when the mid is usable); `wallet_fill_price` is the
 * copied wallet's fill, within a few cents; `price_drift` is |entry - wallet fill|, which pins the
 * price to within the drift. Leaving any one of them in would re-open the leading question.
 */
export const BLIND_STRIPPED_FIELDS = [
  "implied_probability",
  "detection_mid",
  "wallet_fill_price",
  "price_drift",
] as const;

/** The state with every price-level field REMOVED (not nulled: a null invites a guess). */
export function blindState(state: Record<string, unknown>): Record<string, unknown> {
  const strip = (o: unknown): unknown => {
    if (Array.isArray(o)) return o.map(strip);
    if (!o || typeof o !== "object") return o;
    const src = o as Record<string, unknown>;
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(src)) {
      if ((BLIND_STRIPPED_FIELDS as readonly string[]).includes(k)) continue;
      out[k] = strip(v);
    }
    return out;
  };
  return strip(state) as Record<string, unknown>;
}

const BLIND_SCHEMA_LINE = '{"outcome_wins":{"probability":<0-1>,"confidence":<0-1>}}';

/**
 * The blind prompt: one question, no price anywhere in it.
 *
 * The system line states the withholding explicitly rather than silently omitting the field — a
 * model that notices a missing key tends to invent one, and an invented price is worse than none.
 */
export function buildBlindMessages(state: Record<string, unknown>, outcome: string): LocalMessages {
  const system = [
    "You are a calibrated forecasting assistant. You are given a market and one outcome token.",
    "You are NOT told the market price or anyone's fill price — that is deliberate. Estimate the",
    "probability from the market's own description, its category and its time to resolution. Do not",
    "invent or infer a price; if the information is thin, say so with a probability near 0.5.",
    "Answer with ONE JSON object and nothing else — no prose, no markdown, no code fences.",
    "Shape:",
    BLIND_SCHEMA_LINE,
    "`probability` is your belief that the outcome token is the one the market resolves to, 0..1.",
    "Use the key `outcome_wins` verbatim.",
  ].join("\n");

  const lines: string[] = [];
  lines.push("STATE (no price fields are provided)");
  lines.push(JSON.stringify(blindState(state), null, 1));
  lines.push("");
  lines.push("QUESTION");
  lines.push(
    `Does the token "${outcome}" resolve as the winning outcome of this market? ` +
      `"${outcome}" is the answer only if it is the outcome the market resolves to; if the market ` +
      "voids or resolves elsewhere, it is not."
  );
  lines.push("");
  lines.push("Return the single JSON object now.");
  return { system, user: lines.join("\n") };
}

/** The blind reply's own parser: one probability, or null — never a guess. */
export function parseBlindReply(text: string): { probability: number; confidence: number | null } | null {
  const answers = parseLocalReply(text);
  if (!answers) return null;
  const d = parseJevDecision({ answers });
  if (d.probability === null) return null;
  return { probability: d.probability, confidence: d.confidence };
}

export interface LocalChatResult {
  content: string;
  thinking: string | null;
  latencyMs: number;
  promptTokens: number | null;
  evalTokens: number | null;
  error: string | null;
  raw: unknown;
}

/**
 * ONE Ollama chat call (`/api/chat`, JSON mode, thinking OFF by default).
 *
 * Extracted so the lane and the blind replay share a single HTTP path — the measurement is only as
 * trustworthy as the call being identical between the two arms. `json: false` is for callers that
 * want the raw text (nothing in the lane does today, but a model that ignores JSON mode should be
 * observable rather than silently fatal).
 */
export async function callLocalChat(opts: {
  url: string;
  model: string;
  messages: LocalMessages;
  /** top-level `think`; default FALSE — measured: thinking on burns the budget and returns nothing. */
  think?: boolean;
  timeoutMs?: number;
  numPredict?: number;
  keepAlive?: string;
  json?: boolean;
  fetchImpl?: typeof fetch;
}): Promise<LocalChatResult> {
  const {
    url,
    model,
    messages,
    think = false,
    timeoutMs = 8000,
    numPredict = 400,
    keepAlive = "5m",
    json = true,
    fetchImpl = fetch,
  } = opts;
  const body = {
    model,
    stream: false,
    ...(json ? { format: "json" } : {}),
    think,
    keep_alive: keepAlive,
    options: { temperature: 0, num_predict: numPredict },
    messages: [
      { role: "system", content: messages.system },
      { role: "user", content: messages.user },
    ],
  };
  const t0 = Date.now();
  try {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), timeoutMs);
    const res = await fetchImpl(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: ctl.signal,
    });
    clearTimeout(timer);
    const latencyMs = Date.now() - t0;
    const text = await res.text();
    let raw: unknown = null;
    try {
      raw = JSON.parse(text);
    } catch {
      raw = { unparsed: text.slice(0, 2000) };
    }
    const d = raw as {
      message?: { content?: string; thinking?: string };
      prompt_eval_count?: number;
      eval_count?: number;
    };
    return {
      content: d?.message?.content ?? "",
      thinking: d?.message?.thinking ?? null,
      latencyMs,
      promptTokens: d?.prompt_eval_count ?? null,
      evalTokens: d?.eval_count ?? null,
      error: res.ok ? null : `HTTP ${res.status}`,
      raw,
    };
  } catch (e) {
    return {
      content: "",
      thinking: null,
      latencyMs: Date.now() - t0,
      promptTokens: null,
      evalTokens: null,
      error: e instanceof Error ? `${e.name}: ${e.message}` : String(e),
      raw: null,
    };
  }
}
