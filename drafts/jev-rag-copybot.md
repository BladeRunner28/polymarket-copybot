# Jev + RAG for CopyBot — where each one actually pays

**Status: APPROVED 2026-10-06 and executed in stages.** Option B (the shadow-lane instrument) is
shipped and verified; Options A/C/D are carded with pre-registered gates; nothing is wired into a
live decision path and the lane is default-off. See §9 for what actually landed.

*Question asked 2026-10-06: "How can we make use of Jev and RAG to improve copybot?"*

---

## 1. Verdict up front

1. **Jev is not a new subsystem — it is one more evidence source**, and CopyBot already owns the
   aggregation layer it belongs in: `src/lib/forecasting/` (Bayesian log-odds aggregation with
   evidence tiers, cluster-correlation correction, the market price as prior, and a
   `pAware = sigmoid(logit(pNeutral) + 0.1·logit(pMarket))` firewall). Jev's calibrated probability
   becomes an `EvidenceItem` with a `typeCap`, never a decision authority.
2. **The bar is not copyScore, it is the price.** Our own measurements say so: at leg grain the
   stored wallet scores are coin flips (AUC 0.43–0.50) while the entry-price baseline is 0.653
   (C-200) / 0.758 (STANDARD). The ML-1 card has already pre-registered exactly this bar —
   *beat the price-only baseline on net-of-fee PnL*. Any Jev/RAG evaluation that reports against
   copyScore is measuring the wrong thing.
3. **The cheapest useful step is a write-only Jev shadow lane (Option B, ~1 day), and the highest
   expected value is retrieval over our own 77k-label corpus (Option A, model-free).** RAG does not
   need Jev to be valuable; Jev without RAG will mostly re-price the market (see §4).

## 2. What Jev actually is

**Primary source:** TypeSafe AI (Diogo Almeida, founder), *"Introducing System One Models & Jev"*,
type-safe vendor blog, 2026‑09‑15 — `typesafe.ai/blog/introducing-system-one-models-and-jev`.
Reached through OpenRouter's **Decisions API** as `typesafe/jev-1.13` (listing live 2026‑09‑18,
secondary source). Interface in the vendor's own words: **"unstructured state in, typed
probabilistic decisions out"** — a frontier-intelligence function call. You send a typed state plus
typed questions; you get calibrated probabilities and confidence scores, or a discrete decision.
**No strings, no tool loop, no retrieval** — which is why the evidence it reasons over has to be
assembled *for* it. That is the RAG slot, and it is structural, not a workaround.

Mechanism, from the vendor: a new architecture, a **parallel sampler** (all outputs in one query,
not token-by-token), and a training method they call **Reinforcement Learning for Calibrated
Decisions (RLCD)**. Their stated optimand is *epistemic*: "higher confidence means higher accuracy",
plus consistency across similar inputs. Published latency **70–500 ms**, pricing **$0.042 / MTok
input, output free**. Schema matching is guaranteed by construction, so in their framing the model
**cannot produce a type error** — they put 0% on the hallucination/type-error plots.

They position the product exactly where CopyBot would use it: *"AI-Powered Workflows / smart
if-statements — structured outputs slot into ordinary software as fuzzy decision rules: classify,
route, score, extract, or branch where hand-written logic is too brittle. The surrounding code
constrains their freedom."* That is the RuleSet-decides-and-signals-advise split we already have,
arrived at independently.

Vendor-stated caveats that constrain any use of it here:

- The headline **"193.6x faster / 444.6x cheaper"** comes from *their own* workflow evals, where the
  reference answer is the **average of the smartest external models** (biases toward OpenAI/Anthropic
  — they say it likely understates them), the workflows were authored by their model-capabilities
  team (bias possible), and the tasks are outside Jev's training distribution. **No performance
  number from that page transfers to our market class.**
- Those evals were **run from the vendor's West Coast laptops** — the 70–500 ms figure is
  region-dependent. Measure it from this box before putting a call in any loop.
- **Cardinality up to 255 options per question**; higher cardinality is handled as a two-stage
  score-then-choose, which costs latency. Per-leg binary/no questions are unaffected.
- **Still early access, working off a waitlist** (2026‑09‑15) → provisioning is gated, not just an
  API key to paste.
- The FAQ answers to *"Where does our training data come from?"* and *"How does Jev perform against
  public benchmarks?"* are collapsed client-side and are **not in the served DOM** (checked; they
  mount on click). Not retrieved, not load-bearing for this design.
- **Reported failure modes** (ecosystem sources, **not** vendor-stated and **not** reproduced by
  us): probabilities collapse toward the base rate — less than half the spread of the order book —
  and multi-outcome scores need not sum coherently. Our slug space contains real multi-outcome
  events (`unl-nor-prt-…-nor` vs `-prt`), so the second one lands on us; binary parity markets are
  milder. Treat both as hypotheses our shadow lane is there to test.
- **Provenance caveat (transfer review).** The published Jev trading demos are 5-minute BTC
  up/down rounds — a different market class from ours (hours-to-days, mid-anchored maker entries,
  sports/politics). **The architecture transfers; the reported results do not.**

Cost is a non-issue at our volume: ~1,650 copy-eligible fills/day at ~1k tokens each ≈ a few cents
per day; the post-funnel copy count is 26/day, i.e. effectively free.

## 3. The hole each one fills, and the trap both must avoid

**Where the pipeline is thin today:** the decision path is a deterministic points score
(`src/lib/scoring/trade.ts`, copyScore 0–100 with additive adjustments) gated by the RuleSet, and
the sentiment lane feeds the *dashboard* — the scorer-side regulatory multiplier was never wired
(`forecasting/` is live for the dashboard, not for the trade decision; GDELT shadow is JSONL-only).
So there is a real, unused slot for an aggregated, calibrated, evidence-based probability — and a
second, separate slot for retrieval.

**The trap:** a signal can beat copyScore and still be worthless, because copyScore itself does not
separate outcomes at leg grain. The ML-1a probe already measured this from the other side: 77k
counterfactual labels, and the **skipped signals are ~fair-priced**. So:

| Arbiter | Verdict on it |
|---|---|
| copyScore | coin flip at leg grain (AUC 0.43–0.50) — not an arbiter |
| price-only baseline | 0.653 (C-200) / 0.758 (STANDARD) — **the** bar |
| our resolved corpus | the only source of a counterfactual worth trusting |

## 4. Where RAG pays (ranked by value per unit of work)

1. **Retrieval over our own resolved corpus → bucket base rates.** 77k counterfactual labels +
   `DecisionJournal` + resolved `PaperTrade` + `MarketSnapshot`, indexed by (wallet archetype ×
   price band × category × drift bucket × liquidity bucket). Model-free, no vendor, no key, and it
   answers the question the RuleSet actually asks: *"in this bucket, what happened the last N
   times?"* This is the piece that can move the ladder, and it is measurable today.
2. **Evidence-brief assembly for `forecasting/`.** Retrieve dated, sourced items (news, regulatory
   rows, market metadata) as `EvidenceItem`s with cluster keys — the existing correlation correction
   (`mEff = m / (1 + (m−1)·ρ)`) already discounts same-source redundancy, which is precisely the
   failure mode of naive news retrieval. This is also the only way Jev becomes useful: give it the
   retrieved brief, since it cannot browse.
3. **Ops retrieval** (skill references, `drafts/`, tuning reviews, roadmap cards): answers *"what did
   we already settle?"* so the daily reviewer stops re-litigating shipped work. No trading impact,
   immediate time saving, no new dependency.
4. **Resolution-rule retrieval, alert-only:** has a published fact already satisfied a market's
   written resolution criteria while the price hasn't moved (the `polymarket-jev` pattern). Ships
   alert-only, no wallet/order path. Note the source's own caveat: in that scanner the apparent edge
   was mostly the gap between a base rate and the market's price.

## 5. Option set

**A — RAG-first, Jev as a feature (recommended).** Corpus index → bucket base rates (1) and an
evidence brief (2); Jev enters as an `EvidenceItem` (typeCap C, own cluster) writing a write-only
shadow lane. Effort M · risk low (nothing gates execution) · bar: beat price-only out-of-sample,
net of fees.

**B — Jev shadow lane only (cheapest first step, ~1 day).** Clone the `shadow-longshot.ts` /
`shadow-lowconf.ts` pattern, log per-leg `{decisionId, marketId, side, price, ttr, spread, jevP,
jevAction}` to `data/jev-shadow.jsonl`, join to outcomes as they resolve. Effort S · risk none
(write-only) · bar: AUC + Brier vs the price baseline on ≥50 resolved legs. Do this first if you
want Jev's numbers before building any retrieval.

**C — RAG-only, ops-facing.** Index skills/drafts/journal for me and the reviewer crons. Effort S ·
no trading impact · no edge gain. Worth doing regardless, but it is not an improvement to CopyBot.

**D — Resolution-lag alert lane.** Rule-text retrieval + Jev, alert-only, separate from the copy
lanes. Effort M · risk low · value unproven (see §4.4).

**Not proposed:** Jev in the live decision or sizing path before a shadow measurement clears the
price-only bar. That is a rule/sizing change and would be an override-class ask — and it is the
exact shortcut the ecosystem's own write-ups warn against.

## 6. Measurement plan if A or B are approved

- **Instrument:** write-only shadow lane (`data/jev-shadow.jsonl` + a summary JSON), behind a
  default-off flag, following the existing `LOCAL_SENTIMENT_MODEL` / `*-shadow.jsonl` precedent.
- **Population:** every copy-eligible leg scored (not just the 26 that get copied), so the sample is
  ~1,650/day and reaches n≥50 resolved legs in days, not a month.
- **Report:** AUC and Brier for "good leg" (the ML-1 label), calibration curve, and a counterfactual
  PnL replay at current sizing vs. (a) price-only and (b) copyScore. Same population, same window,
  one page — a pair printed off two windows is how an edge becomes unfalsifiable.
- **Pre-registered decision rule:** promote nothing unless it beats the price-only baseline
  out-of-sample, net of fees, and holds across both the pre/post-Aug-28 fill-model split.
- **Honesty constraint:** a veto count is not a cost. Measure the variance a signal would have
  removed, never the wins it would have blocked.

## 7. Gates and open questions

- **No OpenRouter credential exists in this repo** (`grep -rn OPENROUTER .env src scripts` → 0 hits),
  and Jev was in **early access off a waitlist** as of 2026‑09‑15, so step one is a provisioning
  decision, not a code change. It is also a single-vendor, single-endpoint dependency: the design
  ships with an off switch and a fallback (the existing local qwen3.5 shadow lane is the natural
  control arm).
- **Measure the latency from this box before designing around it.** The vendor's 70–500 ms is
  West-Coast-laptop-sourced; a 330 ms median is a different design constraint than 120 ms if the
  call sits anywhere near the copy decision.
- The sentiment/scorer wiring remains unwired by design; this proposal does **not** touch it.
- Measurement-window discipline: a shadow lane is measurement-only and needs no freeze override.
- Ecosystem sources (OpenRouter listing, laikalabs guide, `jevymarket`, `polymarket-jev`) are
  external claims; §2 separates what the vendor states from what third parties assert.

## 8. Sources

**Primary**
- TypeSafe AI — *Introducing System One Models & Jev* (2026‑09‑15): System One class, RLCD, parallel
  sampler, typed outputs with guaranteed schema matching, calibration claim, $0.042/MTok in + free
  out, 70–500 ms, smart-if-statement positioning, 255-option cardinality, early-access waitlist, and
  the vendor's own bias disclosures on its workflow evals.
- `src/lib/forecasting/index.ts` — our log-odds aggregation, evidence tiers, cluster correlation
  (`mEff = m/(1+(m−1)·ρ)`), price prior and the `0.1·logit(pMarket)` firewall.
- `src/lib/scoring/trade.ts` — copyScore construction (the points score Jev must beat *the price*,
  not this).
- `scripts/analyze-score-separation.ts`, `scripts/export-training-data.ts`, ML-1 / ML-1a / ML-1b
  cards in `data/roadmap.json`, `references/local-llm-sentiment-shadow.md` (the shadow-lane
  precedent).

**Secondary (external claims, marked as such throughout)**
- OpenRouter model listing `typesafe/jev-1.13` — Decisions API, pricing, context window, 2026‑09‑18.
- laikalabs.ai — "How to Use Jev AI for Trading on Polymarket": pipeline shape, base-rate collapse,
  multi-outcome incoherence, the mandatory research step.
- `github.com/markusbug/jevymarket` — scan → research → state → Jev → evaluate → execute → log.
- `github.com/swang666/polymarket-jev` — resolution-lag scanner, alert-only.

## 9. What was approved and what actually landed (2026‑10‑06)

Approval: **all four options**, plus the two tuning-review closures. Executed the same day.

**Shipped and verified — Option B, the shadow-lane instrument**
- `src/lib/shadow-jev.ts` — state builder, typed questions, defensive parser, rank AUC / Brier /
  log-loss, the pre-registered verdict, the fee model.
- `scripts/mark-shadow-jev.ts` — collector (DB → state rows), marker (resolution), backfill.
- `tests/shadow-jev.test.ts` — **20 tests pass**; `npx tsc --noEmit` clean.
- Run for real: 200 scored legs collected from the 24 h window, 9 resolutions marked on the first
  pass, 83 of 200 already resolved, summary written to `data/jev-shadow-summary.json`.
- First harness read (**plumbing check, not a finding**): price arm AUC 0.111, Brier 0.3407,
  log-loss 0.9279; copyScore AUC 0.927 on the same rows. That pair is **not** comparable to the
  documented leg-grain baselines (wallet scores 0.43–0.50, entry-price 0.653/0.758) — this
  population is every decision in one day (mixed `skip`/`paper_copy`), it is a non-random
  newest-200 slice of ~1,653 eligible/day, and n=83. Read it again only at n ≥ 50 **with** a model
  arm.
- Four design decisions worth keeping: the price arm is the **detection mid** (not the C-200
  `mid − 2¢` booked entry, which is stored separately so no read credits the model with the fill
  model); the lane is **default-off with no default endpoint** (the Decisions API route is
  unverified, so it must be configured rather than guessed, and an unparsed payload stores the raw
  response with a null probability); stored states can be **replayed** to backfill the model arm;
  legs are **deduped** by id so a re-append cannot double-count.

**Carded with pre-registered gates (not started):** `jev-rag-corpus-index` (A, the corpus index +
evidence brief), `jev-ops-retrieval` (C), `jev-resolution-lag-alert` (D, alert-only, no wallet
path). Board: http://localhost:3013/roadmap — 151 cards, 151 unique ids, all four visible.

**Tuning-review closures (verified by me, not taken from the review's adjective)**
- `tr38-rec3-scorer-dead-slug-cache` → **Done**: 0 `Market fetch failed` across 1,088 runs
  09‑28→10‑06 (bar ≤ 60; last nonzero day 09‑27 = 115), 0 single-slug repeats, header parity
  1,044 + 44 = 1,088 runs with 0 FAILED, and the 404-cache line on 1,032/1,032 scored runs after
  03:00 on the deploy morning (the 12 misses are 01:36–02:53 of the deploy day itself).
- `tr34-rec1-observe-rotation` → **Done with one clause RETIRED**: bar 1 met (656 distinct
  observation wallets/24 h vs a bar of ≥150 and a pre-v62 baseline of 68); the
  `≤ 20,000 rows/24 h` clause is **mis-specified** — measured 109,834, because the row count scales
  with the very coverage the fix was for (rows per wallet/day actually FELL 248 → 167 while
  distinct wallets rose 68 → 656). The invariants that hold: per-cycle cap still exactly 40, and
  duplicate observation rows 301/95,485 = 0.32%. Two new facts for the next reviewer: a bare
  `grep -c 429` on the monitor log is a **false-positive machine** (the rotation's own line says
  `≈ 429 min` — 111 phantom hits), so match `HTTP 429|Too Many Requests` (0 since the v62
  cutover); and the honest cost of the fix is stored volume ≈ 110 k rows/day, which is part of the
  reported +0.091 GB/day DB growth, with the 40-wallet cap as the only lever.
- Both cards keep their original `gate` text; the closure lives in `dates` + `note`. The reviewer
  cron's standing inputs for both were updated **in place** (not appended) so the prompt cannot
  assert "shipped" and "closed" at once. Re-runnable verifier: `python3
  scripts/verify-observe-and-deadslug-gates.py` (exits non-zero on any failing bar).

**Still blocked, and what unblocks it**
1. `JEV_SHADOW` needs an **openrouter key + the Decisions API endpoint** (the vendor was in
   early access off a waitlist as of 2026‑09‑15), then `JEV_ENDPOINT`, then a first live call.
   Until then the lane collects states, which is not wasted work — they are replayable.
2. **Measure latency from this box** before the call sits near a decision (the vendor's 70–500 ms
   is West-Coast-laptop sourced).
3. Nothing here is promotion-eligible yet: the bar in §6 is unchanged and unread.
