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

import { type JevRequest, JEV_LOCAL_MODEL_DEFAULT, JEV_LOCAL_URL_DEFAULT } from "./shadow-jev";

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
