import { describe, it, expect } from "vitest";
import {
  JEV_ENDPOINT_DEFAULT,
  JEV_MIN_RESOLVED_LEGS,
  JEV_PREREGISTRATION,
  auc,
  brier,
  buildCandidateRow,
  buildJevQuestions,
  buildJevRequest,
  buildJevState,
  jevCallConfig,
  logLoss,
  parseJevDecision,
  summarizeJev,
  takerFeePerShare,
  type JevLeg,
  type JevShadowRow,
} from "../src/lib/shadow-jev";

/**
 * The Jev shadow lane is write-only instrumentation (Option B, approved 2026-10-06), so what
 * these tests must prove is NOT "the model is good" — it is that the INSTRUMENT cannot lie:
 * the state is the real population, a payload we do not recognise yields no number (never a
 * guess), and the pre-registered comparison is computed on the same rows for both arms with
 * the price arm intact even where the model arm is missing.
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

function row(over: Partial<JevShadowRow>): JevShadowRow {
  return { ts: new Date().toISOString(), type: "candidate", ...over } as JevShadowRow;
}

describe("state + questions", () => {
  it("hands Jev the market-implied probability and the copy context, with nulls intact", () => {
    const s = buildJevState(leg) as any;
    expect(s.market.implied_probability).toBe(0.62);
    expect(s.market.id).toBe("m1");
    expect(s.signal.price_drift).toBeCloseTo(0.03, 10);
    expect(s.signal.copybot_decision).toBe("paper_copy");
    expect(s.signal.copybot_copy_score).toBe(71.5);
    expect(s.rule_set_version).toBe(60);

    const bare = buildJevState({ ...leg, walletEntryPrice: null, spread: undefined, liquidity: undefined });
    const bs = bare as any;
    expect(bs.signal.price_drift).toBeNull();
    expect(bs.market.spread).toBeNull();
    expect(bs.market.liquidity_usd).toBeNull();
  });

  it("asks small binary questions (cardinality stays far below the documented 255 ceiling)", () => {
    const qs = buildJevQuestions(leg);
    expect(qs.map((q) => q.key)).toEqual(["outcome_wins", "beats_entry", "action"]);
    expect(qs[0].kind).toBe("noul");
    expect(qs[0].instructions).toContain("YES");
    expect(qs[1].instructions).toContain("0.62");
    expect(Object.keys(qs[2].criteria ?? {})).toEqual(["copy", "watch", "skip"]);
    expect(qs.length).toBeLessThanOrEqual(255);
  });
});

/**
 * The wire contract, asserted against the schema OpenRouter publishes for
 * `POST /api/alpha/decisions` (verified 2026-10-06). The first cut of this lane sent
 * `questions` as an array with `kind`/`question` fields and read only `.probability`, which
 * would have 400'd every call and stored a null model arm forever. These tests exist so that
 * cannot come back: the request shape and the response shape are both pinned here.
 */
describe("documented Decisions API contract", () => {
  it("sends questions as an OBJECT keyed by name, never the old array of kind/question", () => {
    const body = buildJevRequest(leg);
    expect(Array.isArray(body.questions)).toBe(false);
    expect(Object.keys(body.questions).sort()).toEqual(["action", "beats_entry", "outcome_wins"]);
    expect(body.model).toBe("typesafe/jev-1.13");
    expect(typeof body.state).toBe("object");

    for (const [key, q] of Object.entries(body.questions)) {
      // required by DecisionsNoulQuestion/DecisionsChoiceQuestion
      expect(["noul", "choice"]).toContain(q.type);
      expect(typeof q.instructions).toBe("string");
      expect(q.instructions.length).toBeGreaterThan(0);
      // the old, wrong field names must not survive anywhere in the payload
      expect(q).not.toHaveProperty("kind");
      expect(q).not.toHaveProperty("question");
      expect(q).not.toHaveProperty("options");
      expect(key.length).toBeGreaterThan(0);
    }

    // noul criteria, when sent, must carry BOTH true and false
    const noul = body.questions.outcome_wins;
    expect(Object.keys(noul.criteria ?? {}).sort()).toEqual(["false", "true"]);
    // choice criteria is REQUIRED by the schema and maps option → criterion
    expect(Object.keys(body.questions.action.criteria ?? {})).toEqual(["copy", "watch", "skip"]);
    expect(JSON.parse(JSON.stringify(body))).toEqual(body);
  });

  it("reads the documented response: noul, choice, per-answer confidence and usage", () => {
    const payload = {
      id: "gen-dec-1789738314-X5e5eKGQdvR9rblyX250",
      model: "typesafe/jev-1.13-20260917",
      provider: "TypeSafe",
      answers: {
        outcome_wins: { type: "noul", noul: 0.96 },
        beats_entry: { type: "noul", noul: 0.31 },
        action: { type: "choice", choice: "copy", confidence: 0.75, probabilities: { copy: 0.84, skip: 0.16 } },
      },
      usage: { input_tokens: 476, output_tokens: 70, cost: 0.000019992 },
    };
    const d = parseJevDecision(payload);
    expect(d.probability).toBe(0.96);
    expect(d.beatsEntryProbability).toBe(0.31);
    expect(d.action).toBe("copy");
    expect(d.confidence).toBe(0.75);
    expect(d.usage).toEqual({ inputTokens: 476, outputTokens: 70, costUsd: 0.000019992 });
  });

  it("carries the model's own cost onto the row, and null when the call never happened", () => {
    const d = parseJevDecision({
      answers: { outcome_wins: { type: "noul", noul: 0.5 } },
      usage: { input_tokens: 300, output_tokens: 20, cost: 0.0000126 },
    });
    const withModel = buildCandidateRow(leg, d, { model: "typesafe/jev-1.13", latencyMs: 210 });
    expect(withModel.jevCostUsd).toBe(0.0000126);
    expect(withModel.jevInputTokens).toBe(300);
    const statesOnly = buildCandidateRow(leg, null, { model: "typesafe/jev-1.13", latencyMs: null });
    expect(statesOnly.jevCostUsd).toBeNull();
    expect(statesOnly.jevInputTokens).toBeNull();
  });
});

describe("parseJevDecision — an unrecognised payload must never become a number", () => {
  it("reads the nested answers form", () => {
    const d = parseJevDecision({
      answers: { outcome_wins: { probability: 0.71 }, beats_entry: { probability: 0.4 }, action: { choice: "copy" } },
      confidence: 0.8,
    });
    expect(d.probability).toBe(0.71);
    expect(d.beatsEntryProbability).toBe(0.4);
    expect(d.action).toBe("copy");
    expect(d.confidence).toBe(0.8);
  });

  it("reads the flat form and the array form", () => {
    expect(parseJevDecision({ outcome_wins: 0.3, action: "skip" }).probability).toBe(0.3);
    expect(
      parseJevDecision({ answers: { questions: [{ key: "outcome_wins", probability: 0.9 }] } }).probability
    ).toBe(0.9);
  });

  it("clamps to probability space instead of storing an out-of-range value", () => {
    expect(parseJevDecision({ outcome_wins: 1.4 }).probability).toBe(1);
    expect(parseJevDecision({ outcome_wins: -0.2 }).probability).toBe(0);
  });

  it("returns all-null for garbage, which is what keeps a bad shape off the summary", () => {
    for (const junk of [null, undefined, 42, "nope", [], { unrelated: true }]) {
      const d = parseJevDecision(junk);
      expect(d.probability).toBeNull();
      expect(d.action).toBeNull();
    }
    expect(parseJevDecision({ outcome_wins: "not-a-number" }).probability).toBeNull();
  });
});

describe("jevCallConfig — default off, and the endpoint is the one the vendor documents", () => {
  it("is off by default, and points at the documented route without being asked", () => {
    const c = jevCallConfig({});
    expect(c.canCall).toBe(false);
    expect(c.reason).toContain("default off");
    // The route is verified (OpenRouter API reference), so it is a default rather than a gap.
    expect(c.endpoint).toBe(JEV_ENDPOINT_DEFAULT);
    expect(JEV_ENDPOINT_DEFAULT).toBe("https://openrouter.ai/api/alpha/decisions");
  });

  it("still refuses to call without a key, even with the flag on", () => {
    const c = jevCallConfig({ JEV_SHADOW: "1" });
    expect(c.canCall).toBe(false);
    expect(c.reason).toContain("OPENROUTER_API_KEY");
    // JEV_SHADOW alone can never produce a call, key or no key: the flag is the master switch.
    expect(jevCallConfig({ JEV_SHADOW: "1", OPENROUTER_API_KEY: "k" }).canCall).toBe(true);
    expect(jevCallConfig({ OPENROUTER_API_KEY: "k" }).canCall).toBe(false);
  });

  it("lets JEV_ENDPOINT override (proxy, mock, a different route) and keeps the model id", () => {
    expect(jevCallConfig({ JEV_SHADOW: "1", JEV_ENDPOINT: "https://example.invalid/d" }).canCall).toBe(false);
    const c = jevCallConfig({
      JEV_SHADOW: "1",
      JEV_ENDPOINT: "https://example.invalid/d",
      OPENROUTER_API_KEY: "k",
      JEV_MODEL: "typesafe/jev-1.13",
    });
    expect(c.canCall).toBe(true);
    expect(c.endpoint).toBe("https://example.invalid/d");
    expect(c.model).toBe("typesafe/jev-1.13");
  });
});

describe("metrics math", () => {
  it("AUC is exact on a separable case and handles ties/single-class", () => {
    // every positive scores below every negative -> AUC 0
    expect(auc([0.5, 0.6, 0.4, 0.7], [1, 0, 1, 0])).toBe(0);
    // every positive above every negative -> AUC 1
    expect(auc([0.6, 0.4, 0.5, 0.4], [1, 0, 1, 0])).toBe(1);
    // all tied -> 0.5
    expect(auc([0.5, 0.5, 0.5, 0.5], [1, 0, 1, 0])).toBeCloseTo(0.5, 10);
    expect(auc([0.5, 0.4], [1, 1])).toBeNull();
    expect(auc([], [])).toBeNull();
  });

  it("Brier and log-loss are the standard forms", () => {
    expect(brier([1, 0], [1, 0])).toBe(0);
    expect(brier([0.5, 0.5], [1, 0])).toBeCloseTo(0.25, 10);
    expect(logLoss([0.5, 0.5], [1, 0])).toBeCloseTo(Math.log(2), 10);
    // never -Infinity on a confident miss
    expect(logLoss([0, 1], [1, 0])).toBeGreaterThan(0);
  });

  it("taker fee is 0.10 x min(p, 1-p)", () => {
    expect(takerFeePerShare(0.5)).toBeCloseTo(0.05, 10);
    expect(takerFeePerShare(0.9)).toBeCloseTo(0.01, 10);
  });
});

describe("summarizeJev — both arms on the same rows, price arm survives a missing model arm", () => {
  const rows: JevShadowRow[] = [
    row({ marketId: "m1", outcome: "YES", entryPrice: 0.5, copyScore: 80, jevProbability: 0.6 }),
    row({ marketId: "m2", outcome: "YES", entryPrice: 0.6, copyScore: 80, jevProbability: 0.2 }),
    row({ marketId: "m3", outcome: "YES", entryPrice: 0.4, copyScore: 70, jevProbability: 0.7 }),
    row({ marketId: "m4", outcome: "YES", entryPrice: 0.7, copyScore: 90, jevProbability: 0.3 }),
    // no model arm yet — must still count for the PRICE arm
    row({ marketId: "m5", outcome: "YES", entryPrice: 0.55, copyScore: 60, jevProbability: null }),
    { ts: new Date().toISOString(), type: "resolve", marketId: "m1", outcome: "YES", value: 1 } as JevShadowRow,
    { ts: new Date().toISOString(), type: "resolve", marketId: "m2", outcome: "YES", value: 0 } as JevShadowRow,
    { ts: new Date().toISOString(), type: "resolve", marketId: "m3", outcome: "YES", value: 1 } as JevShadowRow,
    { ts: new Date().toISOString(), type: "resolve", marketId: "m4", outcome: "YES", value: 0 } as JevShadowRow,
    { ts: new Date().toISOString(), type: "resolve", marketId: "m5", outcome: "YES", value: 1 } as JevShadowRow,
  ];

  const s = summarizeJev(rows, 0.55);

  it("labels a leg good only when winning at a profitable price", () => {
    expect(s.resolved).toBe(5);
    expect(s.priceOnly.n).toBe(5);
    expect(s.jev.n).toBe(4);
    expect(s.resolvedWithModel).toBe(4);
  });

  it("computes both arms and shows the incumbent score is not the arbiter", () => {
    expect(s.priceOnly.brier).not.toBeNull();
    expect(s.jev.brier).not.toBeNull();
    expect(s.copyScore.n).toBe(5);
    expect(s.copyScore.auc).not.toBeNull();
  });

  it("splits the gate into kept vs vetoed and reports the vetoed PnL (never just a count)", () => {
    expect(s.gate.threshold).toBe(0.55);
    expect(s.gate.keptN).toBe(2); // jev 0.6, 0.7
    expect(s.gate.vetoedN).toBe(2); // jev 0.2, 0.3
    expect(s.gate.vetoedMeanPnlPerStakeNetOfFee).not.toBeNull();
    expect(s.gate.copyAllMeanPnlPerStakeNetOfFee).not.toBeNull();
  });

  it("refuses to render a verdict below the pre-registered sample", () => {
    expect(s.barReadable).toBe(false);
    expect(s.beatsPriceOnly).toBeNull();
    expect(s.preregistration).toBe(JEV_PREREGISTRATION);
    expect(JEV_MIN_RESOLVED_LEGS).toBe(50);
  });

  it("dedupes a backfilled leg instead of counting it twice in every arm", () => {
    const key = { marketId: "dup1", outcome: "YES" };
    const dupes: JevShadowRow[] = [
      row({ ...key, entryPrice: 0.5, copyScore: 70, jevProbability: null }),
      row({ ...key, entryPrice: 0.5, copyScore: 70, jevProbability: 0.8 }), // backfilled re-append
      { ts: new Date().toISOString(), type: "resolve", marketId: "dup1", outcome: "YES", value: 1 } as JevShadowRow,
    ];
    const s = summarizeJev(dupes, 0.55);
    expect(s.candidates).toBe(1);
    expect(s.priceOnly.n).toBe(1);
    expect(s.jev.n).toBe(1);
    expect(s.jev.brier).toBeCloseTo((0.8 - 1) ** 2, 10);
  });

  it("renders a verdict on a large sample, both directions", () => {
    const build = (informative: boolean) => {
      const out: JevShadowRow[] = [];
      for (let i = 0; i < 60; i++) {
        const v = i % 2; // alternate win/loss
        const price = 0.5;
        const jev = informative ? (v === 1 ? 0.75 : 0.25) : v === 1 ? 0.25 : 0.75;
        out.push(row({ marketId: `mm${i}`, outcome: "YES", entryPrice: price, copyScore: 50, jevProbability: jev }));
        out.push({ ts: new Date().toISOString(), type: "resolve", marketId: `mm${i}`, outcome: "YES", value: v } as JevShadowRow);
      }
      return summarizeJev(out, 0.55);
    };
    const good = build(true);
    expect(good.barReadable).toBe(true);
    expect(good.beatsPriceOnly).toBe(true);
    const bad = build(false);
    expect(bad.beatsPriceOnly).toBe(false);
  });
});

describe("row shape", () => {
  it("carries the price arm, the booked entry, the model arm and the raw state", () => {
    const r = buildCandidateRow(leg, { probability: 0.66, beatsEntryProbability: 0.5, confidence: 0.7, action: "copy" }, {
      model: "typesafe/jev-1.13",
      latencyMs: 210,
      raw: { answers: {} },
    });
    expect(r.type).toBe("candidate");
    expect(r.entryPrice).toBe(0.62);
    expect(r.jevProbability).toBe(0.66);
    expect(r.jevAction).toBe("copy");
    expect(r.jevLatencyMs).toBe(210);
    expect((r.state as any).market.implied_probability).toBe(0.62);
  });

  it("stores a failure as an error with a null probability — no invented number", () => {
    const r = buildCandidateRow(leg, null, { model: "typesafe/jev-1.13", latencyMs: 8000, error: "TimeoutError: aborted" });
    expect(r.jevProbability).toBeNull();
    expect(r.jevError).toContain("aborted");
  });
});
