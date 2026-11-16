# The congress sentiment scorer is a per-category keyword default — fix it upstream (Lane A proposal)

**Status: PROPOSAL ONLY. Nothing applied.** No `apply-vNN` run, no `prisma/dev.db` write, no RuleSet
row, no edit to `~/political-research-bot/src/congress_api.py`, no cron change, no merge to main.
Card: `sentiment-keyword-table-constant` (approval `apr-sentiment-keyword-table-constant`, 2026-11-16).
Measured 2026-11-16T22:15Z.

Served at `http://localhost:3013/drafts/sentiment-keyword-table-constant-20261116`.
Instrument: `scripts/congress-polarity-dryrun.py` (read-only; `--self-test` 19/19; opens `dev.db`
with `immutable=1`; `--json` writes `data/congress-polarity-dryrun.json`). Every figure below is
re-runnable from it.

---

## 0. Recommendation, in five sentences

Apply **option A**: rewrite `analyze_bill_title()` into a scorer that (1) polls the *current* Congress
instead of the retired 118th, (2) routes on the API's own controlled `policyArea` instead of title
substrings, (3) assigns polarity from the bill's **latest action class** instead of its category, and
(4) emits a row only when an item survives every gate, recording the rest — with the gate that dropped
it — in a local ledger so the corpus documents what was polled and why it was neutral. On the same
rows the book has already received, that scorer keeps **0 of 1,540**; on the current Congress it keeps
**~22 opinionated items per 1,000 bills polled** (~5–8/week across five buckets). It changes no
RuleSet, no sizing path and no published figure; its only downstream effect is that the
`congress_gov_api` cluster stops contributing an edge, which is the same cohort the companion card
`sentiment-edge-single-polarity` priced at −$141.15 of clip on a $1,363.83 v73 counterfactual.

**The one thing the operator must know before approving: this fix does NOT give the sentiment edge a
direction — and that is now measured, not argued.** The card's title assumes "fix the table upstream
and the edge has a direction again". It does not. Every gate I could construct leaves a population
that is **98–100 % positive** (+59 / −1 opinionated-by-action items in a 1,000-bill sample), because a
bill that dies *quietly* is the base-rate class (`referred to committee`, 85 % of rows) and therefore
carries no news, while `passed`/`became law` is by definition one-sided. The fix converts a keyword
constant (+0.50) into an action constant (+0.30…+0.90). §5 shows why no table can do better, and what
would.

---

## 1. Three defects, not one

The card names one ("polarity comes from a keyword table keyed on category"). Measurement finds
three, and the polarity one is the least consequential — because the other two decide *which* rows
ever reach it.

| # | defect | where | measured consequence |
|---|---|---|---|
| **D1** | **the population is a retired Congress** — `bill/118`, `limit=5`, `sort=updateDate+desc` | `congress_api.py:37` | median **action age at ingest = 902 days** (p90 1,258); **0 of 1,540** stored rows had an action inside 30 days *at the time they were ingested*; live, the 118th yields **0** viable items in 1,000 polled |
| **D2** | **polarity is a function of the category, not the item** | `congress_api.py:17-32` | modal value **+0.50 = 84.4 %** of all rows; every category holds one value (Crypto −0.90 ×124, Healthcare +0.70 ×51, Tech/AI +0.80 ×8, Defense +0.85 ×7) |
| **D3** | **routing is raw substring matching with a catch-all default** | `congress_api.py:21-32` | `'sec'` matches **Secretary / Security / Section** → 124 rows land in Crypto; `'ai '` matches **"Vichai "** → Tech/AI; `return "Macro/Politics", 0.5` swallows **84.4 %** of everything |

D1 is why the feed could never carry a direction even if D2 were fixed: *the bills it reads cannot
move.* The 118th Congress ended in January 2025. Across the 1,000 118th-Congress bills polled in
§2.5 the **newest action is 692 days old (≈2024-12)**, and the five bills the bot actually reads each
run last acted between 2023 and 2024-04-11. `sort=updateDate desc` keeps returning the same
commemorative resolutions because `updateDate` moves on metadata edits, not on legislative action:

```
2026-11-16 21:50:53 | Macro/Politics | +0.50 | "Recognizing the significance of Chicano/Chicana Heritage Month"
2026-11-16 21:50:52 | Macro/Politics | +0.50 | "Expressing support for ... national Chuck Brown Day"
2026-11-16 21:50:50 | Macro/Politics | +0.50 | "Honoring the legacy of the Harlem Renaissance"
```

299 distinct bills produced 1,540 rows: **5.15× re-emission** of items whose latest action is a
committee referral from 2023.

---

## 2. Evidence

**Basis for every line:** population = `RegulatorySignal` rows with `source='congress_gov_api'`
(1,540 all-time; the layer reads no demo rows); live population = congress.gov v3
`/bill/{congress}?limit=250&offset=…&sort=updateDate+desc`, 4 pages = 1,000 bills; clocks are UTC;
"fresh" = `latestAction.actionDate` within the gate window of the row's own `processedAt`.

### 2.1 What the feed has emitted

| category | rows | distinct polarity | modal | modal share | span |
|---|---|---|---|---|---|
| Macro/Politics | 1,302 | 2 | +0.50 | 99.8 % | 08-16 → 11-16 |
| Crypto | 124 | 1 | −0.90 | 100 % | 08-28 → 11-05 |
| Healthcare | 51 | 1 | +0.70 | 100 % | 09-04 → 11-03 |
| Finance | 48 | 2 | −0.70 | 93.8 % | 08-16 → 10-27 |
| Tech/AI | 8 | 1 | +0.80 | 100 % | 10-30 → 11-12 |
| Defense/Geopolitics | 7 | 1 | +0.85 | 100 % | 10-05 → 10-27 |

7-day window (the aggregator's): **125 opinionated rows — 119 Macro/Politics at +0.50, 6 Tech/AI at
+0.80.** One value per category, every row, for the entire life of the feed. This reproduces the
companion card's table exactly; nothing here is new, and nothing in it is a polarity *signal*.

### 2.2 The population cannot move (D1)

| action class (all 1,540 stored rows) | rows | share |
|---|---|---|
| `not_advanced` (referred to committee / read twice / held at desk) | 1,312 | 85.2 % |
| `other` | 90 | 5.8 % |
| `reported` (ordered reported / placed on calendar) | 67 | 4.4 % |
| `passed_chamber` | 57 | 3.7 % |
| `procedural` | 12 | 0.8 % |
| `became_law` | 2 | 0.1 % |
| `blocked` (failed / rejected / vetoed) | **0** | 0 % |

**Median action age at ingest: 902 days. p90: 1,258. Rows with an action inside 30 days at ingest: 0.**
Not one row the book has ever received was a fresh legislative event. The sentiment layer has been
pricing a two-year-old committee referral as +0.50 Macro/Politics news, five times over.

### 2.3 Routing is substring matching (D3)

Recomputing the legacy table against the stored titles:

| legacy category | → corrected category | rows |
|---|---|---|
| Macro/Politics | unrouted (no market bucket) | 1,231 |
| Crypto | unrouted | 111 |
| Macro/Politics | Energy/Climate | 32 |
| Crypto | Tech/AI | 10 |
| Macro/Politics | Defense/Geopolitics | 8 |
| Finance | unrouted | 6 |
| Crypto | Finance | 2 |

The Crypto bucket is the clearest casualty: `'sec'` fires on "**Sec**retary of Agriculture",
"Homeland **Sec**urity", "Social **Sec**urity Service to Victims of Identity Theft Act". Of its 124
rows, **111 route nowhere** under a word-boundary table, 10 route to Tech/AI, 2 to Finance — **one**
stays Crypto. All 124 carried **−0.90** into a bucket of crypto markets. Overall **1,402 of 1,540
rows (91.0 %)** would change category or fall out entirely under a correct table, which is the
measure of how much of the corpus was filed by substring accident.

### 2.4 Replay of the proposed scorer on the same rows

`routed` = rows a bucket was assigned to (overlaps the drop columns); the drop columns are disjoint
and sum to 1,540.

| routing vocabulary | routed | non-binding | ceremonial | unrouted | stale | **kept** |
|---|---|---|---|---|---|---|
| reader only (`research-categories.ts`) | 190 (12.3 %) | 191 | 10 | 1,180 | 159 | **0** |
| reader + policy-subject map | 460 (29.9 %) | 191 | 10 | 912 | 427 | **0** |

**Zero of 1,540.** Under any routing vocabulary, every historical congress row is stale, ceremonial,
non-binding or unrouted — and 85 % of them are a committee referral besides. The book's entire congress
sentiment input was structurally incapable of being information, which is consistent with the
companion card's finding that the direction it asserted did not predict (66 legs pushed toward:
29.7 % hit / −$0.08 per share; 53 pushed against: 31.0 % / +$0.05).

### 2.5 What a fixed feed actually yields (live, 1,000 bills)

| Congress | routing | kept at 7 d | 30 d | 90 d | 365 d |
|---|---|---|---|---|---|
| **118 (what the bot polls)** | reader | 0 | 0 | 0 | 0 |
| **118** | reader+subject | 0 | 0 | 0 | 0 |
| 119 (current) | reader | 0 | 1 | 2 | 5 |
| 119 | reader+subject | 2 | 5 | 6 | 12 |

Congress 118 yields **nothing at any window up to a year**. That is D1 stated as a number: the
polarity table could be perfect and this feed would still emit zero information.

Congress 119, routed on the API's own **`policyArea`** (a controlled 32-value vocabulary, fetched from
`/bill/{congress}/{type}/{number}`) with candidates = *binding instrument ∧ action ≤30 d ∧
opinionated action class*, and the obvious subject→bucket mapping (including *Public Lands and Natural
Resources → Energy/Climate*):

```
1,000 bills → 22 candidates → 20 routed, 2 unrouted
   Energy/Climate      10  (+10)     ← Public Lands: Route 66 Trail, Fort Ontario, Carson City land, Churchill Museum
   Macro/Politics       6  (+6)
   Finance              2  (+2)
   Healthcare           1  (+1)
   Defense/Geopolitics  1  (+1)
   sign split: +20 / −0
```

Two things fall out of that table, and they are the whole proposal:

1. **Every routed item is positive.** In the wider 1,000-bill sample, items that are opinionated *by
   action* split **+59 / −1** (congress 118: +43 / −1). The negative class — a bill failing — is
   1 in 1,000; a bill that simply dies is `not_advanced`, which is the base rate and therefore not
   news. The population is one-class by construction.
2. **`policyArea` routes accurately and still lands in the wrong bucket.** Ten of twenty routed items
   are public-lands, historic-trail and museum bills filed under *Public Lands and Natural Resources*,
   which the subject map sends to Energy/Climate. They have no relationship to any energy or climate
   market. Keyword routing was wrong for a different reason (`'sec'` → Crypto); controlled-vocabulary
   routing is *right about the bill* and still wrong about the market, because there is no
   category-level join between legislative subject matter and Polymarket questions. **That is why §3
   leaves this one area unmapped** — routing it correctly is precisely what makes the tilt meaningless.

Rate: **22 candidates, all with action ages of 4–18 days** → roughly **5–8 opinionated events per
week across ~5 buckets** — about **one item per bucket per week**, at ±0.30…±0.90. The aggregator's
`mEff` for a single-item cluster is 1 and its `consistency` is 1.0 by definition, so a lone
park-designation bill would arrive at *full strength* with no scepticism attached (§5.3).

---

## 3. The exact change

One file, `~/political-research-bot/src/congress_api.py`. Read-only dry run in
`polymarket-copybot/scripts/congress-polarity-dryrun.py --live` prices the same pure functions.

```python
# 1) current Congress, not the retired one (D1)
CONGRESS = int(os.environ.get("CONGRESS_NUMBER", "119"))     # 119th convenes 2025-01
PAGE = int(os.environ.get("CONGRESS_PAGE_LIMIT", "250"))     # API max; bot used 5
FRESH_DAYS = int(os.environ.get("CONGRESS_FRESH_DAYS", "30"))

URL = f"https://api.congress.gov/v3/bill/{CONGRESS}?limit={PAGE}&sort=updateDate+desc"

# 2) polarity from the LATEST ACTION, not the category (D2)
ACTION_CLASSES = [
    ("became_law",     ("became public law", "signed by president"),                +0.9, 0.95),
    ("passed_chamber", ("passed senate", "passed house", "agreed to in the house",
                        "agreed to in the senate", "concurred in"),                 +0.5, 0.85),
    ("reported",       ("ordered to be reported", "reported by the committee",
                        "placed on the union calendar"),                            +0.3, 0.70),
    ("blocked",        ("failed", "rejected", "vetoed", "motion to table",
                        "cloture not invoked"),                                     -0.7, 0.85),
    ("not_advanced",   ("referred to", "read twice", "held at the desk",
                        "received in the senate"),                                   0.0, 0.70),
    ("procedural",     ("cloture", "motion to proceed", "quorum"),                   0.0, 0.60),
]

# 3) route on the API's controlled vocabulary, not title substrings (D3)
POLICY_AREA_BUCKET = {
    "Health": "Healthcare",
    "Finance and Financial Sector": "Finance", "Taxation": "Finance",
    "Economics and Public Finance": "Finance", "Foreign Trade and International Finance": "Finance",
    "Energy": "Energy/Climate", "Environmental Protection": "Energy/Climate",
    "Water Resources Development": "Energy/Climate",
    "Armed Forces and National Security": "Defense/Geopolitics",
    "International Affairs": "Defense/Geopolitics", "Immigration": "Defense/Geopolitics",
    "Science, Technology, Communications": "Tech/AI",
    "Government Operations and Politics": "Macro/Politics", "Congress": "Macro/Politics",
    "Civil Rights and Liberties, Minority Issues": "Macro/Politics",
    "Crime and Law Enforcement": "Macro/Politics", "Education": "Macro/Politics",
    "Labor and Employment": "Macro/Politics", "Social Welfare": "Macro/Politics",
    "Housing and Community Development": "Macro/Politics", "Emergency Management": "Macro/Politics",
    "Agriculture and Food": "Macro/Politics", "Transportation and Public Works": "Macro/Politics",
    "Commerce": "Macro/Politics", "Law": "Macro/Politics", "Native Americans": "Macro/Politics",
    # deliberately unmapped (no market bucket): Animals; Arts, Culture, Religion;
    # Sports and Recreation; Public Lands and Natural Resources  ← see §5.2
}
```

Pipeline per run:

1. **One list call** (`limit=250`). Free filters on `latestAction` — binding instrument
   (`HR|S|HJRES|SJRES`; `HRES|SRES|HCONRES|SCONRES` are opinions with no legal effect), action age
   ≤ `FRESH_DAYS`, action class opinionated. That leaves ~5–6 candidates per 250 bills.
2. **One detail call per candidate** → `policyArea` → bucket, else drop. ~6 extra requests per run
   against a 5,000/hour allowance.
3. **Emit one row per action event**, keyed on `(congress, type, number, actionDate)` in a small
   JSON ledger (`data/congress-emitted.json`). This is what stops the 5.15× re-emission: a bill that
   has not moved re-polls as a duplicate and emits nothing.
4. **Emit a row only when the item survives every gate** (i.e. it is opinionated). Non-news items —
   `not_advanced`, `procedural`, ceremonial, non-binding, unrouted, stale — are recorded in the
   ledger with the gate that dropped them and in the run log, **not** in `RegulatorySignal`. Writing a
   `0.0` row per polled item would be inert for the aggregator (`|score| >= 0.3` never enters `n`,
   exactly as `govinfo_fr_notice`'s 93 zero rows/week are inert) but it would put ~780 rows/week into
   the table against today's 125, for no reader. Flag 5 reverses this if you want DB-level audit.
5. `local_sentiment.score_and_log()` stays exactly where it is: the shadow needs the same item text,
   and it must keep never blocking the live signal.

---

## 4. What moves, what does not

| figure | before | after | note |
|---|---|---|---|
| congress rows / 7 d | 125, all opinionated | **5–8 opinionated**, 0 neutral in the DB | the only live-feed figure that moves |
| Macro/Politics edge | +12.38 pp | none | the congress cluster is the whole set |
| Tech/AI edge | +16.30 pp | none | |
| opinionated congress rows, all-time | 1,540 | 0 survive the fix | §2.4 |
| Crypto buckets receiving −0.90 | 124 rows | 0 | misroutes removed |
| `[SENTIMENT]` evaluations on politics flow | ~37/day | ≲1/day | the feed no longer supplies a per-category constant to every leg |
| RuleSet | v73 | **v73 unchanged** | no new field, no `apply-vNN` |
| C-200 Kelly size | — | **unchanged** | that path never read the edge |
| dashboard / EOD / ladder | — | **unchanged** | nothing published reads the edge |
| ML sentiment columns | per-category constant | null for those categories | exporter's existing `nullAgg` path |
| API cost per run | 1 request | ~7 requests, +~1 s | 5,000/h allowance |

**The downstream effect is the companion card's option A cohort**, and its priced diff applies almost
unchanged: 431 of 637 edged decisions silenced, 91 copies, 47 copies changing band (40.9 %),
−$141.15 on a $1,363.83 v73 counterfactual of STANDARD-curve size. "Almost" because the fixed feed is
not quite silent: ~1 item per bucket per week can now emit a small edge (where today the whole bucket
sits at a constant), so a category could show a lone +0.30 instead of +12.4 pp. That residual is
exactly what flag 6 (`minSignals >= 3`) exists to suppress. **Order does not matter** — apply either
card or both; if both land, the aggregator guard becomes inert on congress and stays armed for the
next constant source.

---

## 5. The refutation: this does not create a direction (measured)

This section exists because the card's premise is wrong and the operator should see the arithmetic
before he approves the work, not after.

### 5.1 A one-class population cannot be two-sided

| sample | items opinionated **by action** | positive | negative |
|---|---|---|---|
| congress 118, 1,000 bills | 44 | 43 | 1 |
| congress 119, 1,000 bills | 60 | 59 | 1 |

The negative class is *a bill that failed* — 0.1 % of everything Congress does. The class that
actually describes a dead bill is `not_advanced` (85.2 %): referred to committee, read twice, held at
the desk. There is no defensible polarity for "nothing happened", so it must be 0.0 — and once it is
0.0, the surviving population is the 0.1 %–4 % that advanced, all positive.

Choosing a different sign convention does not escape this. Treating `referred to committee` as
**bearish** (what the local-model shadow does: −0.1/−0.2 on 80.2 % of items) simply re-creates the
defect with a negative constant. **The two conventions are mirror images of the same one-class
population, and a mirror is not a direction:**

| cohort | as measured (keyword +0.50) | after a global sign flip |
|---|---|---|
| pushed **toward** the leg | 66 legs · 29.7 % hit · **−$0.08**/share | 53 legs · 31.0 % hit · **+$0.05**/share, CI [−0.07, +0.20] |
| pushed **against** the leg | 53 legs · 31.0 % hit · **+$0.05**/share | 66 legs · 29.7 % hit · **−$0.08**/share |

The flipped read **looks like a winning sentiment layer** (+$0.05/share on the cohorts it favours) and
is nothing of the sort: it is the same two cohorts relabelled, with the same interval straddling zero.
Anyone who re-runs the companion card's sign test after this fix and reports "the direction predicts
now" will be reading the mirror.

### 5.2 The join is the defect, not the table

`policyArea` is a *correct* description of the bill and still routes ten of twenty candidates into
Energy/Climate from public-lands and museum bills. That is not a table bug to be fixed with a better
table — it is the structure: the writer classifies a **bill**, the reader classifies a **market**
(`src/lib/research-categories.ts`), and the two are joined on a seven-word bucket name that means
different things on each side. A category prior can therefore only ever say *"this week's legislative
mix skews positive in bucket X"*, which is not a claim about any particular market. The aggregator
then multiplies that claim by `mEff` and applies it to every leg in the bucket.

### 5.3 Fewer items makes it *worse*, not safer

After the fix the congress cluster carries ~1 item per bucket per week. In `aggregateEvidenceItems`
the per-cluster update is `l += mEff * trimmedMean(logLRs)` and `consistency` is *the share of the
batch sharing this signal's sign* — which for a one-item batch is **1.0 by construction**. So a single
park-designation bill at +0.90 arrives with maximum consistency, no corroboration penalty and nothing
to trim. A sparse feed does not attenuate the tilt; it launders it.

**This raises the value of a flag the companion card left optional:** its `minSignals: 3` (flag 3,
default 1). With a sparse, one-sign feed, `minSignals >= 3` stops being housekeeping and becomes the
only thing standing between one bill and a sizing band. If both cards are approved, set it.

### 5.4 What the shadow arm actually demonstrates

`data/sentiment-ab.jsonl`, 1,490 congress items, 1,240 scored: **52 opinionated (4.2 % of scored),
+40 / −12**, and the reasons are procedural — *"Vote passed with significant margin"*, *"Referred to
committee indicates bill is not advancing"*. The local model reproduces the same one-sidedness because
**the rubric is one-sided, not the implementation**: `local_sentiment.py`'s system prompt tells it "a
bill advancing toward passage is bullish for its subject". That instruction is the constant. Wiring
the model in live — the obvious next move — would import the same defect with a lower threshold
(3.5 % of all items clear 0.3, and the threshold is the layer's own).

### 5.5 The falsifier I am pre-registering against myself

If, over the first **200 opinionated congress rows** emitted after the fix, **≥ 2 distinct polarity
values appear inside any single category**, then the one-class claim above is wrong and the feed does
carry a direction worth pricing. Report it and reopen the direction question with that population.
Conversely: if the 200 rows are ≥ 95 % one sign inside every category, this proposal's §5 stands and
the direction question belongs to §6, not to this table.

---

## 6. What would actually give the edge a direction

Two mechanisms exist in this system's own design; neither is this fix.

1. **A genuinely two-sided source — congressional trade disclosures (buy vs sell).**
   `quiver_congress_trade` is the only source the book has ever had with real polarity variance
   (190 rows / 25 disclosures / 4 values) and it has been dead since 2026-09-06, with no alert
   (card `research-source-silent-death`). Buy = +, sell = −, *per ticker*, is a sign that is intrinsic
   to the item rather than assigned by a table. Its weakness is the one we already measured: it is a
   source about *specific companies*, and Polymarket has few single-ticker markets — so it wants the
   market-anchored path too.
2. **A market-anchored join — the only route to a per-leg direction.**
   Instead of a bucket, emit `(bill, marketId)` when a bill's subject matches a *specific* market's
   question (e.g. "Will the CLARITY Act pass by 2026-12-31?"), and let the reader require the match.
   That is a different pipeline: `research-signal` would carry a market hint, the reader would have to
   accept one, and it needs entity resolution and a hit-rate instrument before it is worth a dollar.
   It is also the only version of this idea whose information content is non-trivial: the market
   already prices *the bill's prospects*, so the tradable content is the **event timing** — a bill
   advancing is news the market may not have repriced — which is exactly what a 6-hour poll with an
   action ledger can timestamp.
3. **What I would not do:** wire the local model into the live feed. 3.5 % of items clear the 0.3
   threshold, its rubric is one-sided by construction (§5.4), and a small model is not a reproducible
   judge — that harness has already recorded a 95 %→0 % flag-rate swing on reworded input.

Recommendation on scope: **A now; the anchored path carded, not built**, with the bar in §5.5 and a
hit-rate instrument as its first deliverable.

---

## 7. Verifying it enforces (after the operator applies it)

An edit that leaves the file changed proves nothing — and the failure mode here is silence, which is
*also* what a dead cron looks like. Four checks:

1. **Unit:** `python3 scripts/congress-polarity-dryrun.py --self-test` → 19/19, including "word
   boundary keeps 'Secretary' out of Crypto", "referred-to-committee is NOT news", "HJRES kept",
   "ceremonial that passed is still dropped".
2. **Through the feed, not through my instrument:** hand-run the job's own wrapper
   (`bash ~/political-research-bot/run_research_bot.sh`) and read its lines. The new script logs one
   line per polled candidate with its gate result (`KEPT <cat> <pol>` / `DROP <gate>`), so the run
   itself proves the gates fire. Zero `KEPT` lines on a run whose ledger says candidates existed =
   the scorer rejects everything; every line reading `KEPT` with a title-derived category = the old
   table is still live.
3. **Both sides, in the right places:** liveness is proved by the *ledger and the log*, not the DB —
   `data/congress-emitted.json` growing with `candidates_polled`, and a run log line per polled
   candidate. Suppression is proved in the DB: `SELECT COUNT(*) FROM RegulatorySignal WHERE
   source='congress_gov_api' AND processedAt > <apply ms> AND ABS(sentimentScore) >= 0.3` ≪ 125/7 d.
   **Do not read an empty table as "the fix works"** — this feed's failure mode is silence, and a
   stopped cron looks identical from the DB.
4. **Downstream, not by silence:** `DecisionJournal.sentimentDelta` and `reasonsJson LIKE '%Sentiment
   evidence edge%'` on the next politics-flow window. If a congress edge still appears, the
   aggregator is reading rows the feed no longer writes — check the window before concluding.

---

## 8. Rollback

`git revert <apply sha>` in `~/political-research-bot` — one commit, one file, no schema, no RuleSet,
no data rewritten. The ledger `data/congress-emitted.json` is regenerable (delete it and the feed
re-emits once, which the 0.3 filter absorbs). `data/congress-polarity-dryrun.json` is regenerable by
re-running the instrument. Env knobs (`CONGRESS_NUMBER`, `CONGRESS_FRESH_DAYS`, `CONGRESS_PAGE_LIMIT`)
let the operator narrow the gate without a code change; setting `CONGRESS_FRESH_DAYS=0` restores a
silent feed immediately, which is the fail-safe direction.

---

## 9. Flags for the operator (each one is a line you can veto)

| # | decision | recommended | what it changes | how to override |
|---|---|---|---|---|
| 0 | **Apply at all**, given §5 says it buys no direction | **YES** — it removes a measured non-predictive input and stops the misroutes | silences the congress cluster in Macro/Politics + Tech/AI (same cohort the companion card priced at −$141 of clip) | say "minimal" for option B, or "aggregator only" to skip this and rely on the other card |
| 1 | Congress number | **119**, read from env | the whole point of D1; a hardcoded number re-breaks on 2027-01-03 | `CONGRESS_NUMBER=…` |
| 2 | Freshness window | **30 d** (yield: 5 per 1,000 bills) | 7 d → 2, 90 d → 6, 365 d → 12; all-positive at every setting | `CONGRESS_FRESH_DAYS` |
| 3 | Routing key | **`policyArea`**, with *Public Lands and Natural Resources* deliberately unmapped | keeps park/museum bills out of Energy/Climate; loses ~½ of the yield | add the area to `POLICY_AREA_BUCKET` |
| 4 | Polarity table | action classes as in §3 | the values are judgement calls: `reported` +0.30 is the weakest and the most frequent | edit `ACTION_CLASSES`; it is one list |
| 5 | Where the audit trail lives | **ledger + run log** (`data/congress-emitted.json`) | writing a `0.0` row per polled item instead would add ~780 rows/week to `RegulatorySignal` against 125 today; inert for the aggregator, but with no reader | `CONGRESS_EMIT_NEUTRAL=1` |
| 6 | `minSignals` at the aggregator | **3**, if the companion card also lands | a one-item batch otherwise carries `consistency = 1.0` (§5.3) | it is that card's flag 3 |
| 7 | Option B alternative | **not** recommended | zero-out only (`sentimentScore = 0.0` always): 3 lines, same aggregator effect today, but accumulates no valid corpus and leaves D1's API waste running | say "minimal" |

---

## 10. Appendix — reproduce

```bash
cd ~/polymarket-copybot
python3 scripts/congress-polarity-dryrun.py --self-test                  # 19/19
python3 scripts/congress-polarity-dryrun.py --stored                     # §2.1–2.4
python3 scripts/congress-polarity-dryrun.py --live --pages 4 --limit 250 # §2.5, 118 vs 119
python3 scripts/congress-polarity-dryrun.py --live --pages 4 --cat-mode reader+subject
python3 scripts/congress-polarity-dryrun.py --all --json                 # writes data/congress-polarity-dryrun.json

# the freshness × routing sensitivity table (§2.5) is the same instrument with FRESH_DAYS swept:
#   python3 - <<'PY' … dry.FRESH_DAYS = fd; proposed_row(...) …
# the policyArea routing table (§2.5) additionally fetches /bill/{congress}/{type}/{number} per
#   candidate — ~22 detail calls for the numbers quoted.
```

The instrument opens `prisma/dev.db` with `immutable=1` (read-only, no lock contention with the
10-minute scorer), makes only GET requests to congress.gov, and writes nothing except the optional
JSON artifact under `data/`.
