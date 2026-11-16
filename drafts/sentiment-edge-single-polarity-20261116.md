# The sentiment edge is one constant polarity per category — Lane A proposal

**Status: PROPOSAL ONLY. Nothing applied.** No RuleSet row written, no `prisma/dev.db` write, no
`apply-vNN` run, no edit to the live scoring path (`src/lib/forecasting/sentiment.ts` and
`scripts/score-trades.ts` are untouched). Card: `sentiment-edge-single-polarity` (approval
`apr-sentiment-edge-single-polarity`, 2026-11-16).

Served at `http://localhost:3013/drafts/sentiment-edge-single-polarity-20261116`.
Instrument: `scripts/sentiment-edge-dryrun.ts` (read-only; `--self-test` 14/14, `--json` →
`data/sentiment-edge-dryrun.json`). Every number below is re-runnable from it.

---

## 0. Recommendation, in four sentences

Apply **option A** at `aggregateSentimentForCategory`: read the evidence through `signedEvidence()`
(one row per distinct disclosure, minus any source whose polarity is a single value inside the
category being scored). Today that silences the sentiment layer in the only two categories that emit
an edge at all (Macro/Politics +12.38pp, Tech/AI +16.30pp), which is the intended effect: a set with
one polarity is a category prior, not evidence, and cannot distinguish one leg from another. Measured
reach on the book: 431 of 637 edged decisions go silent, 91 copies, 47 copies change score band
(40.9 % — reproduces the card's own figure), 16 admissions lost / 54 gained, and **−$141.15 on a
$1,363.83 v73 counterfactual of STANDARD-curve size** (−10.3 %, over 115 copies spanning 3 months).
No threshold, size, lane or gate moves.

**One thing the operator must know before deciding:** the card's own refutation condition (d) has
fired — the local-model shadow finds 11 polarity values on the same congress items the live feed
scores as one. That makes the upstream keyword table in `~/political-research-bot` the root cause.
It does not make the aggregator's behaviour correct, and the two fixes are not alternatives (§6).

---

## 1. The defect, mechanically

`src/lib/forecasting/sentiment.ts:108-127` — `aggregateSentimentForCategory` selects **every**
opinionated `RegulatorySignal` row in `[asOf-7d, asOf]` for the category, maps each to an evidence
item (`cluster = source`), and returns `aggregateEvidenceItems(items, yesPrice)`.

The `congress_gov_api` poller assigns polarity from a **keyword table keyed on category**, so within
a category every one of its rows carries the same number. Measured now (7d, opinionated only):

| category | rows | distinct disclosures | polarity values | modal | modal share |
|---|---|---|---|---|---|
| Macro/Politics | 119 | 35 | **1** | +0.50 | 100.0 % |
| Tech/AI | 6 | 1 | **1** | +0.80 | 100.0 % |

Two consequences that the card, and the earlier audit, read slightly wrong:

1. **Dedupe is not the fix.** The aggregation already cluster-corrects re-emission
   (`rho=0.6`: `effectiveCount(119) = 1.66`, `effectiveCount(35) = 1.64`), so reading the same set
   deduped moves the delta by **0.16 pp** (+12.38 → +12.22). The *exclusion* of the constant source
   is what removes the edge; the dedupe half of option A is cosmetic. Keep it — it is one call, and
   it is what makes the constancy test run at disclosure level rather than row level — but do not
   sell the change on the dedupe.
2. **The edge is a uniform tilt, not a per-leg signal.** Every leg in Macro/Politics receives the
   same sign and (before the clamp) the same number of copyScore points. It cannot express a
   direction *between* markets, which is the only thing a calibrated edge is for. The v34 clamp at
   `regulatoryScoreCap 79` is the system's own admission that a positive boost was never validated:
   boosted scores are pushed into the 70-79 sizing band rather than the ≥80 band.

**Reach of the tilt, and where it vanishes.** The delta is a logit blend, so the copyScore effect is
largest near p = 0.50 and disappears at the tails. Same set, same window:

| prior (yes price) | delta |
|---|---|
| 0.50 | +12.38 pp |
| 0.045 | +0.94 pp |
| 0.015 | +0.13 pp |
| 0.001 | −0.02 pp |

That is why the layer has mattered on mid-priced politics markets and not on the extreme-priced
vote-count markets.

**What it can and cannot do downstream** (`src/lib/scoring/trade.ts:234-327`, `356-412`):

- **Admission** — only reachable through the long-shot band's relaxed floor (`longshotMinCopyScore 70`
  vs global `minCopyScore 80`). A +12.4 boost from a 68 lands at 80.4 → clamped to 79 → still
  admitted on the long-shot floor; a leg at 57.6 lands at 70.0 and crosses the long-shot floor.
- **Sizing** — the score bands are 70-79 (sweet spot) and ≥80 (top). At v73 both pay **$18.00**, so
  only a base↔sweet transition moves dollars.
- **C-200 size** — none. Kelly sizing (`scripts/score-trades.ts:920-935`) bypasses the copyScore band
  map entirely (λ̂/price/bankroll). For C-200 this change is an **admission** question only; no dollar
  figure is claimed for that lane. The $ column in §4 is the STANDARD curve.

---

## 2. Evidence, measured 2026-11-16

**Basis for every line:** population = `RegulatorySignal` rows (all sources; the layer reads no demo
rows) / `DecisionJournal` (`isDemo=0`); level = one signal row, one distinct disclosure, or one
decision as labelled; clock = `processedAt` / `createdAt` UTC; window 7d to 2026-11-16T16:58Z;
RuleSet **v73** (`sentimentEvidenceEnabled 1`, `sentimentScale 100`, `sentimentMinSignals 1`,
`regulatoryScoreCap 79`).

### 2.1 Supply (7d, opinionated rows only)

| source | rows | disclosures | re-emit | polarities | modal | last emit |
|---|---|---|---|---|---|---|
| congress_gov_api | 125 | 36 | 3.5× | 2 (across all categories) | +0.50 95.2 % | 2026-11-16T15:49Z |
| govinfo_fr_notice | 94 | 8 | 11.8× | 1 | 0.00 100 % | 2026-11-16T15:49Z |
| quiver_congress_trade | 0 | 0 | — | — | — | 2026-09-06T22:46Z (dead 71d) |

`govinfo` has never contributed: 100 % of its rows are 0.00, i.e. it never enters the opinionated
set. `quiver_congress_trade` is the only source the book has ever had with real polarity variance
(all-time: 190 rows / 25 disclosures / 4 values) and it has been dead since 2026-09-06 with no alert
(separate card `research-source-silent-death`). So **the live sentiment layer has exactly one
functioning source, and that source is a per-category constant.**

### 2.2 The arms (prior 0.50; delta = YES-frame posterior − prior)

| category | LIVE | DEDUPED | **A** | **B** | A+B |
|---|---|---|---|---|---|
| Macro/Politics | 119 · +12.38 pp | 35 · +12.22 pp | none | none | none |
| Tech/AI | 6 · +16.30 pp | 1 · +11.11 pp | none | none | none |
| the other 5 categories | none | none | none | none | none |

Both options are behaviourally **identical today**: the per-category set holds one distinct polarity,
so A drops the only source and B's variance gate fails. The tie breaks on what happens when a varying
source returns (§3).

### 2.3 Is the layer live right now? No — because of flow, not a defect

Last decision carrying an edge: `DecisionJournal` 2026-11-14T12:50Z. Last `[SENTIMENT]` log line:
2026-11-14T08:39Z. There have been **zero decisions in any research category since 2026-11-14** —
the copied flow moved to sports/novelty markets (`Spread: Jaguars (-10.5)` ×147, `Will Spain win on
2026-11-15?` ×94, …). Checked rather than assumed: a silent path here would have been a defect, and
it is not one.

In the 2026-11-13 → 11-16 window the layer made **100 evaluations, 88 Macro/Politics and 12 Tech/AI,
46 of them above the 0.005 noise floor**, median +3.33 pp, max +16.38 pp. All 46 are positive
(upward) boosts. Those are the decisions that stop receiving one under option A.

### 2.4 The attribution is one row deep

`DecisionJournal.sentimentDelta` (added 2026-11-14) is populated on **0 of 1,616** post-change rows —
not a defect, simply because no research-category decision has been scored since it landed. So the
replay below parses the edge out of `reasonsJson` prose, and the *first* thing to read after this
change ships is whether that column starts filling.

---

## 3. The exact change

**Shipped as part of this proposal, with no callers and therefore no behaviour change:**
`signedEvidence()` in `src/lib/research-source-supply.ts` (+5 tests in
`tests/research-source-supply.test.ts`, 21/21 green). It is the function the apply step calls, so the
dry run prices the same code the live path would run instead of a second implementation.

**The apply step (one commit, ~12 lines in `src/lib/forecasting/sentiment.ts`):**

```ts
// 1) import
import { signedEvidence } from "../research-source-supply";

// 2) option (default = the new basis; "rows" exists only for before/after instruments)
export interface SentimentAggregationOpts {
  windowDays?: number;
  minSignals?: number;
  opinionatedThreshold?: number;
  asOf?: Date;
  /**
   * Evidence basis. "deduped-signed" (default) = one row per distinct disclosure,
   * minus any source whose polarity is a single value within this category; a
   * non-empty result is guaranteed >= 2 distinct polarities, so minSignals is
   * subsumed. "rows" = the pre-2026-11-16 basis, for instruments only.
   */
  evidenceBasis?: "deduped-signed" | "rows";
}

// 3) the function body
   const rows = await prisma.regulatorySignal.findMany({
     where: { /* unchanged */ },
     orderBy: { processedAt: "asc" },
-    select: { source: true, sentimentScore: true, confidence: true, processedAt: true },
+    select: { source: true, sentimentScore: true, confidence: true, processedAt: true, rawPayload: true },
   });

   if (rows.length < minSignals) return null;

-  const items = buildEvidenceItems(rows, asOf);
-  return aggregateEvidenceItems(items, yesPrice);
+  const evidence = (opts.evidenceBasis ?? "deduped-signed") === "rows" ? rows : signedEvidence(rows);
+  if (evidence.length === 0) return null;   // a constant set emits NO edge, not a zero one
+  return aggregateEvidenceItems(buildEvidenceItems(evidence, asOf), yesPrice);
```

**Call sites — all three move together:**

| call site | effect |
|---|---|
| `scripts/score-trades.ts:561` (the live gate) | the edge becomes null in both constant categories → no `[SENTIMENT]` line, no `sentimentDelta`, no copyScore change |
| `scripts/export-sentiment-features.ts:104-105` (ML feature columns) | `agg` null → the code's existing `nullAgg` path; the ML sentiment columns go from a per-category constant to **null** for those categories. That is the honest value, but the ML lane should then *drop* the column rather than keep an all-null one |
| `scripts/sentiment-edge-read.ts:83` (before/after instrument) | prints the new basis; pass `{ evidenceBasis: "rows" }` to price the old one |

**Cost:** the select gains `rawPayload` (congress ≈ 507 B/row, govinfo ≈ 276 B/row; ~90 KB per call
at today's window). Negligible for the 10-minute scorer; the nightly ML export makes two calls per
decision and will get slower — acceptable for a one-off job, worth knowing.

### A vs B — why A, and why B is not a smaller A

- **B is inert once anything varies, and that is the case that matters.** B keeps every row and only
  asks whether the set holds ≥2 values. The moment one quiver disclosure returns with the opposite
  sign, the set holds 2 values, B emits an edge — and 119 of the 120 rows in it are still the
  constant, so the edge is still ~97 % the category prior plus one real observation. A drops the
  constant source and prices only what varies.
- **A implies B's property.** Every surviving source holds ≥2 distinct values, so a non-empty A set
  always holds ≥2 distinct values. There is no separate variance gate to write, keep in sync, or get
  wrong (pinned by a test).
- **They cost the same.** Identical output today, one call and one helper either way.

---

## 4. The diff — every figure that moves

Replay: all 637 non-demo decisions that carry an edge, each re-scored **at its own `asOf`**
(window `[createdAt-7d, createdAt]`), then run through the real band/admission/size arithmetic.

**Verification that the replay is faithful:** it reproduces the stored edge within 0.15 pp on
**533/637** decisions. The misses are the rows where the prior has to be approximated: none of the
637 carries `priceAtDecision` (the column landed 2026-11-15, after the last edge), so the replay takes
the detection mid from `ObservedTrade` while the scorer used the price it read at scoring time — and
on a NO-side leg the yes-frame prior is the complement, which the journal does not record. The size
function reproduces the stored `simulatedPositionSize` on **33/115** copies; that number is low on
purpose-built ground, because the 637 decisions span ~3 months of ruleset versions and the check
recomputes every size under **v73**. The `$` column is therefore a **v73 counterfactual applied to
the same rules on both sides** — the *delta* is the change's effect, the *level* is not the booked book.

| category | edge decisions | copies | set silenced | copies silenced | mean edge | copies changing band | size before | size after | Δ |
|---|---|---|---|---|---|---|---|---|---|
| Macro/Politics | 380 | 70 | 203 | 48 | +1.79 pp | 25 | $751.55 | $750.79 | −$0.76 |
| Finance | 84 | 26 | 84 | 26 | +8.56 pp | 16 | $349.76 | $219.88 | **−$129.88** |
| Crypto | 128 | 16 | 128 | 16 | −3.22 pp | 6 | $208.52 | $208.00 | −$0.52 |
| Tech/AI | 44 | 3 | 15 | 1 | +3.03 pp | 0 | $54.00 | $44.01 | −$9.99 |
| Defense/Geopolitics | 1 | 0 | 1 | 0 | +17.50 pp | 0 | — | — | — |
| **TOTAL** | **637** | **115** | **431** | **91** | | **47 (40.9 %)** | **$1,363.83** | **$1,222.68** | **−$141.15** |

Other figures that move:

| figure | before | after | note |
|---|---|---|---|
| Macro/Politics edge | +12.38 pp | none | at prior 0.50; today's only 2 live categories |
| Tech/AI edge | +16.30 pp | none | |
| `[SENTIMENT]` evaluations (3d) | 100 (46 > noise floor) | 0 | while the feed stays constant |
| copies changing **the clip that pays** | 28 of 115 | — | the other 19 band changes are sweet↔high, cosmetic at v73 ($18 = $18) |
| copies sizing **up** | 10 | — | removing a constant NEGATIVE polarity removes a uniform penalty: all 16 Crypto copies lost a set whose constant ran −0.90 from 2026-08-28 to 11-05, and 6 of them changed band |
| copies sizing **down** | 29 | — | |
| admissions lost / gained | 16 lost / 54 crossed | — | no score-independent hard skip; leg-level blocks (C-200 blacklist, slug cap) are not visible to this read |
| clamp-bounded rows | 240 of 637 | — | sat exactly on 79, so their pre-edge score is a lower bound; harmless for size at v73 |
| ML sentiment columns | per-category constant | null | exporter already handles a null agg |
| RuleSet | v73 | **v73 unchanged** | no new rule field, no `apply-vNN` |
| dashboard / EOD / ladder figures | — | **unchanged** | nothing published reads the edge; the overview page lists raw signals, not edges |

**Pre-registered decision rule (card `(c)`): "apply A if the SIGNED arm removes an edge in a category
where the clamp does not already neutralise it — ≥1 changed admission OR ≥10 % of that category's
copies changing sizing band."** Satisfied: 16 changed admissions, and 25/70 = 35.7 % (Macro/Politics)
and 16/26 = 61.5 % (Finance) of copies change band.

---

## 5. Does the removed edge carry information? (the card's refutation condition)

Two label arms printed on every line, per the harness rule: **MARKET** =
`didOutcomeWin(OutcomeReview.finalOutcome)`, **PNL** = `realizedPnl > 0`. Population = one leg;
price = `PaperTrade.entryPrice`.

**The direct test — the edge's own direction.** A constant cannot be tested *within* a category
(every leg gets the same number), but the **sign is per-leg**: the same constant pushes a YES leg
toward and a NO leg against. So split every leg whose set option A silences by the sign it received:

| cohort | legs (settled) | markets | mean price | MARKET hit | 95 % CI | edge/share | boot 95 % | PNL |
|---|---|---|---|---|---|---|---|---|
| **pushed toward the leg (+)** | 66 (62) | 33 | 0.272 | 11/37 = 29.7 % | [17, 46] | **−$0.08** | [−0.22, +0.05] | 23/62 |
| **pushed against the leg (−)** | 53 (48) | 33 | 0.262 | 9/29 = 31.0 % | [17, 49] | **+$0.05** | [−0.07, +0.20] | 14/48 |

The legs the edge **favoured** did *worse* than the legs it opposed (29.7 % vs 31.0 % hit; −$0.08 vs
+$0.05 per share). The point estimate is in the wrong direction and both intervals straddle zero.
That is the refutation that matters: not "the tilt lost money" but **"the direction the tilt asserted
did not predict"**.

Per category, for the same cohorts (categorical polarity in the last column is the all-time constant
measured from the feed):

| cohort | legs (settled) | markets | median date | mean price | MARKET hit | 95 % CI | edge/share | boot 95 % | PNL | constant |
|---|---|---|---|---|---|---|---|---|---|---|
| Macro/Politics | 60 (55) | 38 | 2026-10-02 | 0.306 | 8/31 = 25.8 % | [14, 43] | −$0.08 | [−0.19, +0.05] | 18/55 | +0.50 |
| Finance | 37 (35) | 11 | 2026-09-09 | 0.277 | 6/20 = 30.0 % | [15, 52] | −$0.15 | [−0.32, +0.05] | 13/35 | −0.70 |
| Crypto | 20 (18) | 13 | 2026-09-20 | 0.161 | 6/14 = 42.9 % | [21, 67] | **+$0.26** | [+0.06, +0.47] | 6/18 | −0.90 |
| Tech/AI | 2 (2) | 1 | 2026-09-12 | 0.042 | 0/1 | — | −$0.05 | — | 0/2 | +0.80 |
| Macro/Politics, edge *kept* | 23 (23) | 13 | 2026-09-09 | 0.415 | 14/22 = 63.6 % | [43, 80] | +$0.21 | [−0.03, +0.43] | 18/23 | — |

Three honest readings:

1. **Nothing here says the tilt was informative.** Four cells, no cell with the tilt's direction
   confirmed; the only interval that excludes zero (Crypto, +$0.26/share) is the one where the legs
   did better than price *despite* the constant, i.e. against the tilt.
2. **The "edge kept" row is not a control.** It is an earlier-era cohort (median 2026-09-09 vs
   2026-10-02) from when quiver was alive — a time split, not a treatment contrast. Do not read its
   63.6 % as "the edge works when it varies".
3. **It is unprovable at this sample, on purpose.** n = 29–37 market-resolved legs per cell, clustered
   on 11–38 markets, with leg-level intervals that are already anti-conservative. That is the
   argument, not a limitation of the analysis: this is an input to a live decision, and the system
   cannot measure whether it works.

### The shadow arm — and the pre-registered refutation, which has fired

`data/sentiment-ab.jsonl`, 2,783 scored items (shadow only, never a decision input):

| source | items | rule polarity values | local model values | opinionated **opposite** to the rule |
|---|---|---|---|---|
| congress_gov_api | 1,485 | 7 | **11** | **17** |
| govinfo_fr_notice | 1,167 | 1 | 1 | 0 |
| quiver_congress_trade | 130 | 4 | 6 | 0 |

Card `(d)`: *"If the live shadow arm (LOCAL_SENTIMENT_MODEL, data/sentiment-ab.jsonl) shows ≥2
directions on the same bills, then the polarity DOES exist upstream and the defect is the keyword
table in political-research-bot, not the reader — fix it there and leave this aggregator alone."*

**It is met as written.** I am not going to bury that: the card said don't touch the aggregator if
this showed up, and it showed up. What it changes, and what it does not:

- **It does change the root cause.** The keyword-table fallback in
  `~/political-research-bot/src/congress_api.py` is where the constant is manufactured (its modal
  value covers 84.4 % of all-time congress rows). That is a separate, real defect, and it needs its
  own card.
- **It does not make the aggregator correct.** The *live feed* still emits one value per category
  (`RegulatorySignal`, measured above). "The polarity exists upstream" is true of a shadow model's
  opinion about a bill; it is not true of what the aggregator reads. The aggregator's behaviour —
  pricing a one-value set as calibrated evidence worth up to +16 copyScore points — is unchanged by
  any upstream fix, and it is the amplifier that made a keyword default worth a sizing band.
- **The shadow cannot be the fix by itself.** 990 of 1,485 congress items sit at |0.10|–|0.20|, i.e.
  below the layer's own 0.3 opinionated threshold: wired in as-is it would contribute *nothing*. And
  this harness already recorded that a small local model is not a reproducible judge. So "fix the
  keyword table" is a project with a pre-registered validation bar, not a switch.
- **The two fixes are not alternatives.** A is the guard that makes "calibrated evidence" true
  regardless of what any feed does next (a new source that emits one value re-creates this defect
  silently); the keyword table is what would give the layer a *direction* worth pricing again.

Applying A therefore means: **the sentiment layer contributes nothing until a varying source
returns.** That is the real cost, and §4 says it is worth −$141 on a $1,364 counterfactual of the
cohort it touches, with no measured loss in outcome quality.

---

## 6. Verifying it enforces (after the operator applies it)

An `apply` that leaves the file changed proves nothing. Four checks, in order:

1. **Unit:** `npx vitest run tests/research-source-supply.test.ts` → 21 pass, including "a non-empty
   result always holds ≥2 distinct polarities" and "never merges two unparseable payloads to
   manufacture a constant".
2. **Boundary, through the live reader:** `npx tsx scripts/sentiment-edge-dryrun.ts` → the **A**
   column must read `none` for Macro/Politics and Tech/AI, and the **LIVE** column must equal A on
   every category (i.e. the default really is the new basis).
3. **Production evidence, not silence:** the *absence* of `[SENTIMENT]` lines is equally consistent
   with "no candidate" (today's state, §2.3) — so do not read it as proof. Proof is
   `npx tsx scripts/sentiment-edge-read.ts` printing `SINGLE POLARITY` with no edge, plus
   `SELECT COUNT(*) FROM DecisionJournal WHERE createdAt > <apply ms> AND reasonsJson LIKE '%Sentiment
   evidence edge%'` = 0 while the feed is constant, on the next window in which a research-category
   market is copied at all.
4. **Revert is one field:** an instrument can prove the legacy arm still works before and after the
   change — `aggregateSentimentForCategory(cat, p, { evidenceBasis: "rows" })` must reproduce
   +12.38 pp / +16.30 pp. If it does not, the option is not wired and the "revert is one field" claim
   is false.

---

## 7. Rollback

`git revert <apply sha>` — one commit, reader-side only. No schema change, no RuleSet version bump,
no data rewritten, no dashboard or report rebuilt. `data/sentiment-edge-dryrun.json` and
`data/research-source-supply.json` are regenerable by re-running their scripts. If the `evidenceBasis`
option survives the revert decision, flipping the default back to `"rows"` restores today's behaviour
without any code change.

---

## 8. What this does NOT do

- **Does not fix the keyword table** in `~/political-research-bot/src/congress_api.py`. Separate card;
  it is Lane A (it changes what the bot decides) and it needs a pre-registered bar, because the shadow
  that motivates it is sub-threshold and unvalidated.
- **Does not touch the legacy sentiment branch** (`scripts/score-trades.ts:568-585`, the
  `sentimentEvidenceEnabled === 0` path). That branch reads the *same* constant with
  `findFirst` and applies a flat **±25 / +10 / −20** copyScore boost — worse than the aggregator. It is
  dead today (v73 has the flag at 1) but it is one flag away from re-creating this defect at 2× the
  magnitude. Recommend gating it identically, or deleting it.
- **Does not re-open `quiver_congress_trade`.** It has been dead 71 days; card
  `research-source-silent-death` owns that, and it is the only source whose return would make this
  filter inert (in the good way).
- **Does not change the C-200 Kelly size path**, which never read the edge.

---

## 9. Flags for the operator (each one is a line you can veto)

| # | decision | recommended | what it costs / changes | how to override |
|---|---|---|---|---|
| 0 | **Apply A at all**, given the refutation fired | **YES** — the amplifier is the cheap half | silences the layer until a varying source returns; −$141 on the touched cohort's v73 counterfactual | say "upstream only" and I card the keyword-table fix alone |
| 1 | Default basis | `"deduped-signed"` | the live gate + ML features + instruments all move together; no caller can inherit the old defect | `evidenceBasis: "rows"` at any call site |
| 2 | Keep the `"rows"` door at all | **YES** | 4 lines; it is the only way an instrument can price before/after without reverting | drop the option, revert = full git revert |
| 3 | Minimum surviving disclosures | 1 (no extra gate) | a 2-disclosure varying set can emit a small edge — correct by the definition, thin by construction | add `minSignals: 3` in the live call; note default is 1, so this is a one-word change |
| 4 | Legacy branch (`sentimentEvidenceEnabled = 0`) | gate it identically, or delete it | closes a ±25-boost resurrection path | leave it and accept the risk |

---

## Appendix — reproduce

```bash
cd ~/polymarket-copybot
npx tsx scripts/sentiment-edge-dryrun.ts --self-test     # 14/14 filter checks
npx tsx scripts/sentiment-edge-dryrun.ts --json          # writes data/sentiment-edge-dryrun.json
npx tsx scripts/research-source-supply-read.ts --days 7  # the supply + arms + reach arms
npx vitest run tests/research-source-supply.test.ts      # 21 tests incl. signedEvidence
grep -c "\[SENTIMENT\]" logs/cron/copybot-monitor-score.log
```

The dry run is read-only: it opens `prisma/dev.db` for reads, writes one JSON artifact under `data/`,
and calls nothing that can open a trade.
