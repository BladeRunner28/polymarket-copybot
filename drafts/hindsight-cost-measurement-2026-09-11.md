# Hindsight memory — cost measurement (2026-09-11)

**Question:** does persistent memory (Hindsight cloud) save token costs vs the built-in MEMORY.md/USER.md store?
**Method:** historical measurement from Hermes's own session accounting (`state.db`: `sessions`, `session_model_usage`) + the live Hindsight bank via the read-only client API. **Nothing was enabled or changed.**
**Verdict: cost is a non-argument — both options cost fractions of a cent per 1,000 turns. Decide Hindsight on capability (cap relief + entity recall), not on token savings.**

## 1. Rate model — verified against their real invoice

From `agent/usage_pricing.py` (snapshot `deepseek-pricing-2026-07`), for `deepseek-v4-flash`:
input **$0.14/Mtok** · output **$0.28/Mtok** · cache-read **$0.0028/Mtok** (50× cheaper than input).

Cross-check against recorded accounting (70 DeepSeek sessions, 3,762 API calls, 8,790 messages):

| | tokens | $ |
|---|---|---|
| input (uncached) | 6.9 M | 0.971 |
| output | 4.3 M | 1.199 |
| cache reads | 648.6 M | 1.816 |
| **total (modelled)** | | **$3.9859** |
| **total (recorded)** | | **$3.9860** ✓ |

Model matches the real bill to 4 decimals → the per-turn cost math below is trustworthy.
**Actual spend: ~$0.00106 per API call.** The entire memory question is being decided inside a rounding error.

## 2. What memory costs per turn

| Injected into every turn | tokens | $/turn | $/1,000 turns |
|---|---|---|---|
| Built-in block (MEMORY.md + USER.md), cached | 907 | $0.00000254 | **$0.0025** |
| Built-in block, if uncached | 907 | $0.00012698 | $0.127 |
| Hindsight recall at its 4,096-token cap (varies → never cacheable) | 4,096 | $0.00057344 | **$0.573** |

So Hindsight's recall injection is ~226× the cached built-in block and ~4.5× the uncached one — **in absolute terms $0.57 per 1,000 turns.** Even run hot, Hindsight adds well under a cent per 1,000 turns. Neither option can move the bill.

**The one scenario that would matter:** if recall injection ever landed *inside* the cached system-prompt prefix, a varying prompt would invalidate cache and re-bill the 648 M cache-read tokens at input rates: **+$0.0237/call = $89 total = 22.3× the current bill.** Hermes's cache-safety design is meant to prevent this (turn content, not system prompt) — but it is the only memory-related line item with real money in it, and worth confirming before any auto-recall configuration change.

## 3. What actually drives the bill (so the real levers are visible)

| | share of spend |
|---|---|
| cache reads (648 M tok) | 46% |
| output tokens (4.3 M) | 30% |
| uncached input (6.9 M) | 24% |

Levers with real money: shorter outputs, better cache reuse, fewer API calls. Not memory.

## 4. Why a historical ON/OFF A/B is impossible (honest limitation)

- Hindsight was active **Jul 15 → Aug 21**; that entire window ran on **Gemini**, whose rows carry `estimated_cost_usd = 0.000` (models absent from the pricing table → unpriced).
- **DeepSeek only starts Aug 28** — after Hindsight was switched off.
- Therefore: **no same-model before/after exists.** Any ON/OFF comparison is confounded by the model switch (different pricing, different caching behaviour).
- Additionally, the cloud service's own extraction/synthesis LLM calls are **off-ledger** — billed by Vectorize, invisible to Hermes accounting. The true total cost of Hindsight cannot be measured from local data.
- A valid A/B requires a bounded same-model test (50–100 turns with it on vs off) — that is an *implementation*, so it needs approval.

## 5. What's in the bank (the benefit side)

Measured through the read-only client API:

- **878 memories**, 148,936 chars ≈ **37,234 tokens** (41× the built-in block) — dates Jul 14 → Aug 17.
- Composition: **76% raw `world`/`experience` facts (667)**, 24% consolidated `observations` (211).
- **Only 4 distinct sessions covered** — a narrow harvest, not months of coverage.
- Overlap test vs the live built-in notes: **3 / 878** show >60% token overlap → content is genuinely *additive*, but it is largely raw session narration, which `session_search` (local FTS5, free) already covers.
- Unique-value sample: operational specifics the capped built-in store cannot hold — dashboard at `192.168.1.10:3013`, paper position sizing change ($0.25–$20 on Jul 20), L2-skew skip rule (< −0.40), entity-graph links.
- Data-quality note: at least one memory is in German (mixed-language extraction), and the bank stopped mid-August — ~3.5 weeks of sessions (Aug 17 → now) are absent.

## 6. Security finding

The Hindsight API key, along with other `.env` values, appears in **plaintext in a stored tool-output row inside `~/.hermes/state.db`** (from an earlier session that read `.env`). Hermes redacts secrets in *display*, but the transcript store holds the raw text. Recommendation: rotate the Hindsight key before sharing transcripts/dumps anywhere, and treat `state.db` as sensitive.

## 7. Conclusion

1. **"Persistent memory saves token cost" is true only in the sense of avoided re-derivation** — not in dollars. At their rates, memory is ~$0.003/1,000 turns (built-in, cached) vs ~$0.57/1,000 turns (Hindsight, worst case). Both are rounding errors against $0.00106/call.
2. **The built-in store is the cheaper artefact, but its cap (2,200 / 1,375 chars, currently 99% / 98% full) is the real cost** — it forces curation and eviction of facts.
3. **Hindsight's case rests on capability, not cost:** ~37 K tokens of additive knowledge that cannot fit in the capped prompt, plus entity/observation consolidation.
4. **Open unknown:** the *benefit* side (reduced re-derivation, fewer recovery tool calls) has not been measured. Only a bounded same-model A/B can produce it, which is an implementation decision.

**Options:** (a) bounded same-model A/B, 50–100 turns, on vs off — real benefit number, requires enabling; (b) adopt on capability grounds with the cheap config (`memory_mode: tools`, `recall_budget: low`, `recall_max_tokens: 1024`, `retain_every_n_turns: 5+`) ≈ $0.14/1,000 turns; (c) stay off and keep curating the built-in 2.2 KB by hand.
