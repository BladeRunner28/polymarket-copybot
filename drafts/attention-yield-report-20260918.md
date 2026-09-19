# Stage 0 + 1 results — attention→price lead test: **gate K1 FAILS**

**Date:** 2026-09-18 · **Scope:** Stage 0 (plumbing) shipped, Stage 1 (matcher + yield) run · **Outcome:** do not
proceed to Stage 2 · **Design:** `drafts/attention-lead-test-design-20260918.md` · **Predecessor:**
`drafts/trendradar-audit.md`

---

## 1. Stage 0 — shipped and verified

| change | file | verification |
|---|---|---|
| store `processed_at` / `updated_at` (ISO ts) + typed `entities` (name/type/wiki) | `political-research-bot/src/gdelt_shadow.py` | live `--dry-run` shows both fields landing (`"processed_at": "2026-09-18T16:55:39Z"`); `py_compile` clean |
| log the `assetId → marketId` map | `polymarket-copybot/scripts/record-l2.ts` (`data/l2-asset-map.jsonl`) | `npx tsc --noEmit` exit 0; takes effect on next recorder restart |

Stage 0 was worth doing regardless of the test outcome: the news feed is now a timestamped event stream
(previously day-granularity only), and the L2 corpus is now self-describing (the DB carries **no** token ids —
`ObservedTrade.rawTradeJson` is `{}` for all 283,154 rows, so every L2 analysis would otherwise re-resolve each
file through Gamma at ~300 ms).

Also established for later use: CLOB `prices-history` is keyless but **403s without a browser User-Agent**, and
its resolution is 60-second bars for the trailing 1h/6h/24h, 10-minute bars back 31 days.

## 2. Stage 1 — the yield ladder (the gate number)

`scripts/attention-match.py` over 1,702 news rows / 10 collection-days and a 24,259-question market universe
(38.8% auto-generated temperature ladders and similar noise families excluded first):

| rule applied | stories surviving |
|---|---|
| ≥1 token shared with any market (ceiling) | 1,509 / 1,702 |
| ≥1 candidate carries the story's entity | 1,509 |
| **entity matches ≤3 markets (ambiguity cap)** | **86** |
| + shipped second-token rule, live window, TTR ≥ 24h, price in (0.02, 0.98) | **4** |

**Yield = 0.4 events/day against a gate of ≥15/day. FAIL.**
Even the most generous entity-anchored variant (ambiguity cap only, no second-token rule) yields ≤ 8.6/day —
still under the gate.

### Why: the overlap is real but it is on generic vocabulary, not on propositions

- 94% of candidate stories (1,423 / 1,509) die at the ambiguity cap. Top offenders: **Donald Trump (74 stories),
  Federal Reserve (43), OpenAI (36), EU (16), United States (15), Anthropic (15), UN (12), Scott Bessent (11),
  Binance (10), ChatGPT (10), Bitcoin (10)** — the entities our six standing queries surface are *themes*, and a
  theme entity matches hundreds of live markets at once.
- The market side is dominated by generic vocabulary: `win` appears in **7,087** questions, `election` 3,275,
  `score` 2,297, `september` 1,942, `party` 1,309, `house` 1,300.
- The two vocabularies intersect on common nouns, not on the *specific proposition* that defines a market.
  A wire story about "the crypto industry" mentions Bitcoin; it does not entail any single Bitcoin market.

### Precision audit — 0/4 (gate: ≥85%) on the events the matcher did produce

| story | matched market | why it is wrong |
|---|---|---|
| "Election signs allowed in city Friday" (Hsinchu) | "Will Ann Kao win the next Hsinchu City Mayor election?" | matched on the *common noun* `election` + `city` |
| Ontario Catholic school board trustee election (Cornwall) | "Will Sasha Austin win the 2026 Hamilton, Ontario mayoral election?" | right province, wrong city |
| Frank Benedetto by-election in Reggio | "Will Francesco Toscano win the next Reggio di Calabria by-election?" | right city, different candidate |
| UK tax changes / oil & gas projects | "Will ACA premium tax credits not be extended and will the Republican Party win the House…" | matched on `party` + `tax` |

The similarity-based fallback (title↔question overlap ≥ 0.20 with the cap) raises yield to 3.7/day but produces
the same class of garbage — "FDA Approves New Covid Shots" → "Elliot Anderson: 1+ shots"; "Infarmed stops
distribution of Salofalk" → "Spread: Portugal U20 (−2.5)". Buying yield with precision is precisely what the
design forbade, which is why the gate is joint (yield **and** precision).

### Two flaws in my own matcher, stated for the record

1. The entity fallback admits **common nouns** ("Election", "Friday", "Party") as entities; the API returned empty
   `entity_refs` for ~half the stories, so the fallback fired often. A typed-entity-only rule would remove all
   four false positives.
2. The ambiguity cap was applied to candidates that *survived* the second-token rule, not to the entity's full
   candidate set — too permissive. Applying it at entity level is what the ladder reports (86 stories).

Neither flaw changes the verdict: the ceiling is 8.6/day at best, and the survivors are common-noun overlaps.
The **mechanism**, not the matcher, is the finding: theme-shaped news does not map to proposition-shaped markets.

## 3. What the failure actually teaches (the useful half)

The direction of the mapping is inverted from the design's assumption. What works — and it is the pattern this
repo already uses elsewhere — is **market → news**, not news → market:

1. Take the live market universe (39,076 questions, 24,259 after noise families).
2. For each market, extract the *specific* proposition entities (candidate, person, team, city, bill) — the
   tennis-matcher doctrine: name + date, both-sides-must-agree, ambiguity → return None rather than guess.
3. Query the news APIs **for those entities** (GDELT Cloud `q=<entity>`; and this is where TrendRadar's
   per-entity rank/persistence time series would actually earn its place).
4. Then the measurable claim is not "a story predicts a market" but **"does coverage intensity on a market's own
   proposition lead its price?"** — a lead/correlation test with a known, high-precision map by construction.

That reframing also explains why the earlier audit's "salience router" framing was half right: the router has to
start from the *market list*, because that is the only side whose subjects are propositions.

## 4. Honest costs and what survives

- Stage 0: kept (timestamps, asset map, the UA + resolution facts). Cheap and reusable by any future news study.
- Stage 1: ~2 hours, produced a decisive negative on the *forward* direction and a concrete alternative.
- Stage 2 (event study): **not run** — its precondition (≥15 events/day at ≥85% precision) failed on both arms.
  Running it on 4 false positives would have produced a confident answer to the wrong question.
- Stage 3 (TrendRadar / A2 wiring): unchanged, still post-Oct-8, and now with a *better* justification for
  TrendRadar's rank/persistence feature — it belongs to the market→news direction, not this one.

## 5. Verdict

K1 failed: the news universe and the market universe intersect on themes, not on propositions. Forward
news→market matching is not a viable salience router at any acceptable precision. The recommended next step, if
the salience idea is to continue at all, is the **inverted design** (market → news), which is a different
experiment with a different gate — and it starts with a matcher over the market list, not over the news feed.
