# ML feed REC 3 — the news corpora cannot supply a single as-of text for our book; take the shape, refuse the rows

Roadmap card `ml-feed-news-corpus-structure` (Lane A, approved 2026-11-12T16:45:06Z via
`apr-ml-feed-news-corpus-structure`). Answers the card's one open question — **the NC carve-out** — and
reports that a larger problem sits underneath it.

**NOTHING APPLIED.** No `scripts/apply-vNN.ts`, no write to `prisma/dev.db`, nothing merged to main, no
RuleSet, size, gate or published figure changed. Every DB read is `file:…?mode=ro` + `PRAGMA query_only=1`.

Instruments (read-only, in the working tree, **not committed** — the apply step commits them with the change):

```
scripts/news-corpus-coverage.py                  # NEW: this whole doc's numbers, one run
data/news-corpus-coverage-20261112.json          # NEW: its output, quoted throughout
```

The ~48 MB of downloaded parquet is a **transient cache outside the repo** (re-fetched on a cold run, 2 min):
it is not kept in the working tree, so the nightly backup has nothing to sweep and nothing un-recoverable is
dropped.

---

## 1. Verdict

**The NC question is the small one and the answer is EXCLUDE.** `window_a` (1,141 texts, CC BY-NC-SA 4.0)
cannot be part of a lane that risks real money — not the texts, not a feature table built from them, not a
model fine-tuned on them. That is a licence fact, not a judgement call.

**The large one is that the two CC BY 4.0 corpora together yield 59 news-bearing markets out of our 8,442
in the one span where they could possibly meet.** `dnakhla` contributes **0** rows inside our decision
window (its corpus ends 2026-03-22; ours starts 2026-07-14). SuperAGI's permissive Polymarket window
(15 Jul – 9 Aug 2026) intersects **245** of our markets and carries news on **59** of them — **0.7% of the
span book, 0.12% of all 49,205 markets in the export.** The card's decision rule ("era-split AUC beats
price-only 0.6704 by ≥0.01 out-of-sample") is therefore **not runnable on this data**, at any bar: n=59 is
not a population, and the card's own era split would halve it again before any AUC is computed.

**Recommendation: adopt the SHAPE into our own recorder and refuse the rows.** The transferable asset is the
four-part storage shape — checksum of the exact UTF-8 text, a capture timestamp distinct from the
publication date, an explicit no-news sentinel, and a **per-file** licence manifest. Our export has none of
it (52 columns, zero text or join columns) while the join key is one step away (`ObservedTrade.conditionId`,
6,533,437 rows / 24 nulls / present from 2026-07-13, one day before the export begins).

Three judgement calls, each one line and each overridable (the number that changes is on the line):

| # | call I made | instead of | what changes if you override |
|---|---|---|---|
| 1 | **EXCLUDE** `window_a` everywhere, recorded as excluded | quarantine it for eval-only use (O2) | 1,141 NC texts could answer "does a BY-trained event-type model transfer to PolyBench text?" — a question Window B already answers under CC BY 4.0, at the cost of NC bytes on a commercial host |
| 2 | ingest **nothing** as data; take the schema only | pre-train on `dnakhla` (143,142 headlines) | adds a US-news topic model (49 clusters, 13 outlets) to a book whose slug prefixes are 68% question words — no decided row is predicted differently, so the number that changes is 0 |
| 3 | **re-scope** the card's AUC test behind a recorder gate | keep the rule as written | the rule stays permanently untestable: 59 usable markets today, 0.4% of decisions carry any text-derived feature (315/80,209) |

## 2. The licence, resolved at the primary source

Read 2026-11-12 off the dataset API, the READMEs and each `LICENSE` file — not off the card summary.

| file | rows | licence | evidence | may feed a money lane? |
|---|---|---|---|---|
| `SuperAGI/llm-vs-prediction-markets-news` → `texts.parquet` | 5,317 | CC BY 4.0 | root `LICENSE` = "Attribution 4.0 International"; README: "CC BY 4.0 … except `window_a/`" | **yes**, with attribution |
| … → `window_a/texts.parquet` | 1,141 | **CC BY-NC-SA 4.0** | `window_a/LICENSE` = "Attribution-NonCommercial-ShareAlike 4.0 International" | **no** |
| `SuperAGI/llm-vs-prediction-markets` → `benchmark/window_a/*` | 2,997 moments | **CC BY-NC-SA 4.0** | same README carve-out; own `LICENSE` in that folder | **no** |
| … → `benchmark/window_b/*` | 3,619 moments | CC BY 4.0 | README | yes |
| `dnakhla/us-news-headlines-enriched` | 143,142 | CC BY 4.0 | single `license: cc-by-4.0` tag and card field | yes |

Four corrections to how the card describes this, each of which changes the gate:

1. **The carve-out is two files in two repositories, not one file.** The card names
   `llm-vs-prediction-markets-news/window_a/`; the *main* dataset's `benchmark/window_a/` is NC too. The two
   datasets are separate HF repos with separate sha — a checker that inspects only the news repo passes half
   the contaminated surface.
2. **Both cards' `license` field is an ARRAY holding both licences.** A pass/fail check on the card header
   cannot express "CC BY 4.0 except one subdirectory" — it resolves to *mixed*, which is neither yes nor no.
   The gate has to be **per file**, which is exactly what the news README does in prose and what a manifest
   should do in data.
3. **ShareAlike is the harder half, not NonCommercial.** NC alone would leave "research/eval" open. SA means
   any adaptation must itself be released NC-SA, so a model, embedding or feature table derived from
   `window_a` cannot be dropped into a proprietary commercial lane *even if the evaluation was internal*.
   The conservative read — the one I recommend — is that nothing derived from those 1,141 texts ever touches
   the lane, and the safe alternative already exists: Window B is the same pipeline, same venue, same
   three-article blocks, under CC BY 4.0.
4. **Relicensing is not on the table.** `window_a` derives from PolyBench (Cheng, Liu & Long,
   arXiv:2604.14199, cited in the main dataset's credits), so the rights are upstream third-party. Asking
   SuperAGI for a commercial licence buys a negotiation for 1,141 texts that supply **zero** of our
   decisions.

The card also says the texts are "keyed by SHA-256 with article URL, site and capture time". Measured: the
texts file has **five** columns — `sha256, kind, text, words, redacted` — and none of them is a URL or a
timestamp. The URL / site / Common Crawl capture time live on the *main* dataset (`benchmark/window_b/
news_articles.parquet`, 2,489 rows / 1,538 distinct URLs), joined by `text_sha256`. The shape is real, but it
takes both datasets to demonstrate it.

## 3. What the corpora actually hold

| | measured |
|---|---|
| SuperAGI `texts.parquet` | 5,317 rows = 3,477 `article_text` (median 361 words) + 1,840 `row_news_text` composite blocks (median 994 words); 5,317 distinct sha256; 73 rows `redacted=1` |
| Window B (Polymarket, BY) | 3,619 market-moments, 3,619 distinct markets, 15 Jul – 9 Aug 2026; news on **1,010 (27.9%)**; article counts 0:2,609 · 1:209 · 2:123 · 3:678; 950 ladder markets (26.3%) |
| Window B capture times | 2026-07-01T21:37Z → 2026-08-09T17:27Z — *before* each forecast moment, i.e. genuinely as-of |
| `dnakhla` | 143,142 headlines, 13 outlets, 2015-01-01 → **2026-03-22**; 118,113 "current" era; 37,252 rows (26.0%) have no parseable `datetime`; `collected_at` is one bulk snapshot (2026-03-20 → 03-22), so the only usable clock is the published date |

Their own headline limit — stated in the README, confirmed here — is that **seven in ten rows have no news
at all**, even with a name-match + reranker-≥0.3 pipeline over Common Crawl. That is the cost of the
mapping, and it is not a defect in their data.

**One trap worth more than the rest of this section:** 2,609 of the 3,619 Window B rows carry
`news_text_sha256 = e3b0c442…b855`, the SHA-256 of the **empty string**, with `words = 0`. A checksum join
therefore reports "news found" on **100%** of rows; the real figure is 27.9%. Every reader of a
checksum-keyed corpus needs a non-empty guard, and ours must ship with one.

## 4. Coverage against our book — the number that decides REC 3

| join | measured |
|---|---|
| our conditions in Window B's span (2026-07-15 → 08-10) | 8,442 distinct `conditionId` over 88,415 observed trades |
| …that appear in Window B's 3,619 markets | **245 (2.90%)** |
| …of those 245, carrying news | **59 — 0.70% of the span book, 0.12% of the export's 49,205 markets** |
| `dnakhla` rows inside our decision window | **0** (their corpus ends 2026-03-22, five months before 2026-07-14) |
| decisions carrying the only text-derived feature we have (`has_sentiment`) | **315 of 80,209 (0.4%)** — 315 of 12,822 rows in the sentiment export |

Basis, stated so nobody re-derives it wrong: our side is `ObservedTrade.conditionId` (the identifier in
`decisions.parquet` is a market *slug* — `cs2-ts7-mouz-2026-08-02-game1` — and the parquet carries no
condition column at all, which is why the card's premise cannot be tested off the parquet alone); their side
is `market_moments.venue_market_id`; both keys are the 0x-prefixed 64-hex condition id.

So the honest statement is not "the corpus is small". It is: **the corpus is a different population.** Window
B samples ~139 markets/day from the volume head with a two-sided book and spread ≤0.10, while our book is
827 decisions/day over 49,205 markets, 68% of whose slug prefixes are question words
(`will` 28,687 · `highest` 23,101 · `lowest` 2,766 · then `lol`, `cs2`, `mlb`, `atp`, `dota2`). A 2.9%
intersection is what that sampling difference predicts, and no amount of downloading widens it.

## 5. Our side of the shape — what is missing and what is one join away

| | measured |
|---|---|
| `data/ml/decisions.parquet` | 80,209 × 52; date range 2026-07-14 → 2026-10-19; 49,205 markets; 4,863 acted rows |
| text / URL / checksum / capture / question / condition columns | **none** (regex over all 52 names) |
| `ObservedTrade.conditionId` | 6,533,437 rows, **24 null**, non-null from 2026-07-13 20:13 — covers the whole export |
| `RegulatorySignal` (our only as-of news supply) | 2,810 rows, 2026-08-16 → 2026-11-12, **political only**: congress 1,455 · govinfo 1,164 · quiver 190 · reddit 1 — ~32/day, nothing for sports/esports |
| category labels | `category_class` non-null on 5,344/80,209 (6.7%) and 587/4,863 acted (12.1%) — a no-backfill migration artifact, derivable from `marketId` + question per the schema comment |
| slug prefixes as an event type | 372 distinct, top 20 cover 87.0% — but 54,568 rows (68.0%) start with a question word, so the prefix is an event *family* (`highest`, `will`), not a news event type |

Which means the missing piece is not storage capacity and not the licence. It is that **no news text is
captured at decision time anywhere in the pipeline**, and the join key needed to attach one is already
present and complete.

## 6. Why the card's decision rule is not runnable today

Three walls, in the order they bind:

1. **No text to train or score on.** The export has no news column, and the corpora supply 59 markets (see
   §4). The card's rule assumes a split population; there isn't one.
2. **The BY file carries no labels.** `texts.parquet` is `sha256, kind, text, words, redacted` — "train a
   headline→event-type classifier on the CC BY 4.0 split only" needs event types from somewhere else. Our
   own metadata gives 6.7% coverage today; `dnakhla` gives 49 `topic_label` clusters whose distribution
   (`trump_shutdown_bill`, `2016_election_campaign`, NYT-heavy US general news) is not the distribution of a
   book that is mostly sports, esports and numeric thresholds. A model trained on those topics classifies
   *US news*, not *our markets*.
3. **The mapping upstream of it was killed on measurement.** `market-to-news-lead-test` (Done, 2026-11-08)
   failed its pre-registered Stage A gate at **80.0% entity-map precision against an 85% bar** (16/20 mapped
   markets, fresh sample), and Stage B was never run. Coverage was *not* the blocker there — 386 of 485
   mapped markets carried ≥5 items/7d (median 52). **Our news supply is findable; our market→entity map is
   imprecise.** No corpus fixes that, and REC 3 measures the wrong organ if it is read as a way around it.

## 7. The option set

| | what | effort | risk | why not / why |
|---|---|---|---|---|
| **O1 (recommended)** | **EXCLUDE + RECORD.** `window_a` refused by a per-file licence manifest, recorded as `EXCLUDED` with its reason; neither corpus ingested as lane data; the four-part shape adopted into a news-as-of recorder on our own export | ~2–3 h | none — write-only instrument, no decision path | — |
| **O2** | O1 **+ a quarantined eval-only copy** of `window_a` (gitignored, `data/ml/quarantine/`) to ask whether a BY-trained event-type model transfers to PolyBench text | +1 h | NC bytes on a commercial host; SA contamination by accident; the manifest exists to prevent exactly this | Window B answers the same question under CC BY 4.0 |
| **O3** | **No adoption.** Drop the SuperAGI family as licence-ambiguous (~10 MB, two repos, mixed cards), keep `dnakhla` as a pre-train corpus | ~1 h | none | loses the only thing that transfers — capture-timestamp + sentinel + per-file manifest |
| **O4** | **Relicence** `window_a` | days | correspondence with no leverage | rights are PolyBench's, upstream third-party, for 1,141 texts that supply 0 decisions |

## 8. If O1 is approved — the apply path

Five operator commands; nothing here is Lane A (no rule, size, gate or published number moves), so on
approval this is a Lane B build:

```bash
# 1. the gate's input: per-file licence manifest, with window_a recorded as refused
#    (see the JSON in §8.1) — nothing reads it until step 4's check lands
$EDITOR data/news-corpus-licences.json

# 2. the recorder: writes the text-as-of stamp for every decision whose sentiment features exist
.venv-ml/bin/python scripts/news-asof-record.py --date $(date -u +%F)   # → data/news-asof/<date>.jsonl

# 3. export columns (write-only, NULL-retro): news_block_sha256, news_capture_ts,
#    news_article_count, news_source  — added to export-sentiment-features.ts and
#    export-training-data.ts, defaults NULL so every historical row reads "not captured"

# 4. the leak-free invariant, which is the whole point — ships with the recorder as
#    scripts/news-asof-verify.py and must return 0 rows:
#    every non-null capture_ts <= the row's decided_at  (text known before the decision, not after)

# 5. commit script + manifest + doc together (the nightly backup sweeps anything left uncommitted)
```

### 8.1 The manifest that makes the exclusion a fact rather than a habit

```json
{
  "generated": "2026-11-12",
  "rule": "a file may become a lane dependency only if its OWN licence file permits commercial use",
  "files": [
    {"dataset": "SuperAGI/llm-vs-prediction-markets-news", "path": "texts.parquet",
     "licence": "cc-by-4.0", "verdict": "PERMITTED", "role": "shape reference + attributed excerpts"},
    {"dataset": "SuperAGI/llm-vs-prediction-markets-news", "path": "window_a/texts.parquet",
     "licence": "cc-by-nc-sa-4.0", "verdict": "EXCLUDED",
     "reason": "NonCommercial + ShareAlike; a money lane is commercial use and any adaptation must ship NC-SA"},
    {"dataset": "SuperAGI/llm-vs-prediction-markets", "path": "benchmark/window_a/",
     "licence": "cc-by-nc-sa-4.0", "verdict": "EXCLUDED", "reason": "same carve-out, second repository"},
    {"dataset": "SuperAGI/llm-vs-prediction-markets", "path": "benchmark/window_b/",
     "licence": "cc-by-4.0", "verdict": "PERMITTED", "role": "as-of exemplar; only 59 of our markets"},
    {"dataset": "dnakhla/us-news-headlines-enriched", "path": "data/",
     "licence": "cc-by-4.0", "verdict": "PERMITTED", "role": "pre-train only; corpus ends 2026-03-22"}
  ]
}
```

## 9. Re-scoped decision rule (pre-registered here, so the next session cannot drift)

The card's rule is replaced by a gate **and** the rule it was trying to express. Both are falsifiable.

**Gate (must be met before any AUC is quoted):** the news-as-of recorder has accumulated
**≥300 decisions with a non-null `news_block_sha256`**, of which **≥100** sit in markets whose entity map
passes the Stage-A repair (≥85% precision on a fresh ≥40-market sample). Until then the answer to "do news
features help" is **UNMEASURED**, not negative.

**Test (only after the gate):** an event-type feature derived from as-of text must beat the **era-matched
price-only comparator (0.6704 held-out)** by **≥0.01 AUC** out-of-sample on a time-ordered split, with the
market-clustered 95% CI on money excluding zero.

**REFUTED IF:** Δ ≤ 0, or the lift vanishes when the model is retrained on a later era (regime-fitting — the
same decay that took price from 0.7592 to 0.6704), or the gate has not been met by **2027-02-01**, in which
case the card closes as unmeasurable and the recorder keeps running at zero cost.

## 10. What would change this answer

- **A CC BY 4.0 corpus that covers our actual book** (sports/esports fixtures and numeric-threshold markets,
  keyed by condition id or by a resolvable entity) would re-open the classifier question directly. Neither
  candidate is that corpus, and `dnakhla`'s own limit — 0 rows after 2026-03-22 — cannot be fixed by
  downloading it more carefully.
- **A Stage-A map repair** reaching ≥85% strict precision on a fresh sample changes wall 3 only; it still
  needs the recorder to exist, which is why O1 ships regardless of it.
- **A commercial relicence of PolyBench** (upstream, not SuperAGI) would make O2 legitimate. It would still
  buy 1,141 texts and 2,997 market-moments from Feb 2026 — outside our decision window, so it would still
  not score a single one of our decisions.

## 11. Reproduce / rollback

```bash
.venv-ml/bin/python scripts/news-corpus-coverage.py            # ~2 min first run (50 MB fetch), then seconds
# → data/news-corpus-coverage-20261112.json  (every table above)
```

Downloads only the CC BY 4.0 files; `window_a` is deliberately never fetched (`window_a_fetched: false` is
written into the artefact as the check). Rollback of this doc's work: delete `scripts/news-corpus-coverage.py`
and `data/news-corpus-coverage-20261112.json` — nothing else reads them, no DB row was written, no rule
changed. (The parquet cache lives outside the repo and expires on its own.)

Deliverable served at `http://localhost:3013/drafts/news-corpus-asof-20261112`.
