import { describe, it, expect } from "vitest";
import {
  buildJevRequest,
  buildJevQuestions,
  jevCallConfig,
  parseJevDecision,
  JEV_LOCAL_MODEL_DEFAULT,
  JEV_LOCAL_URL_DEFAULT,
  type JevLeg,
} from "../src/lib/shadow-jev";
import { buildLocalMessages, extractJsonObject, normalizeAnswer, parseLocalReply } from "../src/lib/jev-local";

/**
 * The LOCAL arm (JEV_PROVIDER=local) puts an Ollama model behind the SAME three questions the
 * vendor route asks. What these tests must prove is not "the local model is good" — it is that the
 * adapter cannot quietly change the experiment:
 *
 *   1. the prompt is rendered FROM buildJevRequest(), so a local answer is an answer to the same
 *      propositions (no second, drifting question set),
 *   2. a reply we cannot read yields NO number (never a guess), and
 *   3. the local provider needs no credential but is still gated by JEV_SHADOW.
 */

const leg: JevLeg = {
  decisionJournalId: "dj1",
  marketId: "m1",
  outcome: "YES",
  side: "BUY",
  walletAddress: "0xabc",
  entryPrice: 0.62,
  detectedPrice: 0.62,
  walletEntryPrice: 0.65,
  spread: 0.02,
  liquidity: 5000,
  ttrHours: 30,
  copyScore: 71.5,
  confidence: 0.55,
  liveDecision: "paper_copy",
  lane: "BANKROLL_200",
  marketQuestion: "Will X happen?",
  marketCategory: "politics",
  ruleSetVersion: 60,
};

describe("buildLocalMessages — the same questions as the vendor route, rendered to chat", () => {
  it("carries every question's instructions and criteria verbatim", () => {
    const req = buildJevRequest(leg, "qwen3.5:9b");
    const { system, user } = buildLocalMessages(req);
    for (const q of buildJevQuestions(leg)) {
      expect(user).toContain(q.instructions);
      const criteria = q.kind === "noul" ? q.noulCriteria : q.criteria;
      for (const text of Object.values(criteria ?? {})) expect(user).toContain(text);
    }
    // the state is handed over as JSON, keyed the same way the vendor body keys it
    expect(user).toContain(JSON.stringify(req.state, null, 1));
    expect(system).toContain("outcome_wins");
    expect(system).toContain("beats_entry");
    expect(system).toContain("action");
  });

  it("asks for one JSON object and nothing else (a chat model needs the shape stated)", () => {
    const { system } = buildLocalMessages(buildJevRequest(leg));
    expect(system).toMatch(/ONE JSON object/);
    expect(system).toMatch(/probability[\s\S]*confidence/);
  });
});

describe("parseLocalReply — tolerant extraction, never an invented number", () => {
  it("reads the documented shape, keyed exactly as the vendor container is", () => {
    const a = parseLocalReply(
      JSON.stringify({
        outcome_wins: { probability: 0.71, confidence: 0.6 },
        beats_entry: { probability: 0.58, confidence: 0.5 },
        action: { choice: "copy", confidence: 0.8 },
      })
    );
    expect(a).not.toBeNull();
    const d = parseJevDecision({ answers: a, usage: { input_tokens: 10, output_tokens: 20, cost: 0 } });
    expect(d.probability).toBeCloseTo(0.71, 10);
    expect(d.beatsEntryProbability).toBeCloseTo(0.58, 10);
    expect(d.action).toBe("copy");
    expect(d.confidence).toBeCloseTo(0.8, 10);
    expect(d.usage?.costUsd).toBe(0);
  });

  it("survives fences and a sentence of prose in front of the object", () => {
    const fenced = '```json\n{"outcome_wins":{"noul":0.4},"action":{"choice":"skip"}}\n```';
    expect(parseLocalReply(fenced)?.outcome_wins).toEqual({ noul: 0.4 });
    const prose = 'Sure — here is my answer:\n{"outcome_wins":{"probability":0.2},"action":"watch"}';
    const a = parseLocalReply(prose);
    expect(parseJevDecision({ answers: a }).action).toBe("watch");
    expect(parseJevDecision({ answers: a }).probability).toBeCloseTo(0.2, 10);
  });

  it("accepts a wrapper container and percentages, which local models emit", () => {
    const a = parseLocalReply('{"answers":{"outcome_wins":{"probability":62},"action":{"choice":"copy"}}}');
    const d = parseJevDecision({ answers: a });
    expect(d.probability).toBeCloseTo(0.62, 10);
    expect(d.action).toBe("copy");
  });

  it("returns null for anything unreadable, so the row records a failure and not a number", () => {
    expect(parseLocalReply("")).toBeNull();
    expect(parseLocalReply("I cannot answer that.")).toBeNull();
    expect(parseLocalReply('{"outcome_wins":')).toBeNull(); // truncated mid-object
    expect(parseLocalReply("[1,2,3]")).toBeNull();
    // a parsed object with none of the three keys is still nothing
    expect(parseLocalReply('{"reasoning":"hmm","notes":"later"}')).toBeNull();
  });

  it("keeps an out-of-range value visible as a boundary rather than dropping the answer", () => {
    expect(parseJevDecision({ answers: parseLocalReply('{"outcome_wins":{"probability":150}}') }).probability).toBe(1);
    expect(parseJevDecision({ answers: parseLocalReply('{"outcome_wins":{"probability":-3}}') }).probability).toBe(0);
  });
});

describe("normalizeAnswer — the spellings a chat model uses", () => {
  it("scales only the 1..100 range and never re-scales a 0..1 value", () => {
    expect(normalizeAnswer(0.9)).toEqual({ probability: 0.9 });
    expect(normalizeAnswer(1)).toEqual({ probability: 1 });
    expect(normalizeAnswer(90)).toEqual({ probability: 0.9 });
    expect(normalizeAnswer("0.35")).toEqual({ probability: 0.35 });
    expect(normalizeAnswer("copy")).toEqual({ choice: "copy" });
    expect(normalizeAnswer(null)).toBeNull();
  });

  it("scales a keyless probability but leaves confidence alone", () => {
    expect(normalizeAnswer({ probability: 62, confidence: 0.7 })).toEqual({ probability: 0.62, confidence: 0.7 });
  });

  it("extractJsonObject takes the first balanced object, not the last brace in the text", () => {
    const obj = extractJsonObject('note {"a":{"b":1}} trailing {"c":2}') as Record<string, unknown>;
    expect(obj).toEqual({ a: { b: 1 } });
  });
});

describe("jevCallConfig — the local provider needs no key, and is still default-off", () => {
  it("is inert without JEV_SHADOW=1 even though the local route has no credential to require", () => {
    const c = jevCallConfig({ JEV_PROVIDER: "local" });
    expect(c.canCall).toBe(false);
    expect(c.reason).toContain("default off");
    expect(c.provider).toBe("local");
  });

  it("calls with no API key at all, pointing at the LAN host and the measured model", () => {
    const c = jevCallConfig({ JEV_SHADOW: "1", JEV_PROVIDER: "local" });
    expect(c.canCall).toBe(true);
    expect(c.reason).toContain("local");
    expect(c.endpoint).toBe(JEV_LOCAL_URL_DEFAULT);
    expect(c.model).toBe(JEV_LOCAL_MODEL_DEFAULT);
    expect(c.provider).toBe("local");
  });

  it("honours overrides and defaults to the vendor provider when unset", () => {
    const c = jevCallConfig({
      JEV_SHADOW: "1",
      JEV_PROVIDER: "LOCAL",
      JEV_LOCAL_URL: "http://127.0.0.1:11434/api/chat",
      JEV_MODEL: "gemma4:12b-it-qat",
    });
    expect(c.provider).toBe("local");
    expect(c.endpoint).toBe("http://127.0.0.1:11434/api/chat");
    expect(c.model).toBe("gemma4:12b-it-qat");
    // no JEV_PROVIDER -> the vendor route, unchanged, key still required
    const v = jevCallConfig({ JEV_SHADOW: "1" });
    expect(v.provider).toBe("openrouter");
    expect(v.canCall).toBe(false);
  });
});
