# Ops record lookup — "has this been done already?" as a one-command retrieval

**Card:** `jev-ops-retrieval` (approved 2026-10-06, never built) · **Lane B** ·
**Read:** 2026-11-22T02:04Z · **Instrument:** `scripts/ops-record-lookup.py` (`npm run ops:record`)

## Key insight

The record already exists and already contains the numbers. `data/roadmap.json` carries
308 cards whose notes hold the population, the clock, the level and the reproduce
command; `drafts/` holds 502 more documents. The recurring failure is not a missing
measurement — it is that nobody queries the record before designing the next one.
Two duplicate-work incidents on this repo came from exactly that skip (a duplicate
pre-registration, and a claim shipped as open that had already been fixed).

Grep is the incumbent habit and it is the wrong tool for the question. A reviewer
asking *"was the apostrophe strip in v2 breaking outcome joins?"* does not know that
the card is called `data-api-v2-outcome-normalisation`, so literal AND-matching over
2 MB of prose misses. Measured on a fixed 16-query eval set drawn from real
incidents, ranked retrieval beats grep by a wide margin — and, importantly, a
"better" retrieval scheme (passages) measured **worse**, which is why it is reported
rather than shipped as the default.

## Measured (16 queries, every expected answer a real card on this board)

Corpus: 309 cards + 503 drafts = 812 docs (the first read was 810; this change adds one card and this draft). Level = one query → one expected card id.
Ranker = BM25 (k1 1.2, b 0.75, title 3x).

| arm | recall@1 | recall@3 | recall@5 | MRR |
|---|---|---|---|---|
| **A bm25-doc (pre-registered)** | 0.500 | **0.875** | 0.938 | 0.690 |
| A1 bm25-hybrid (key field 2.5x) | **0.625** | 0.750 | 0.875 | 0.714 |
| A2 bm25-passage (350-char) | 0.250 | 0.625 | 0.625 | 0.448 |
| B bm25-title (mutation control) | 0.562 | 0.750 | 0.750 | 0.634 |
| C literal-AND (`grep -l` habit) | 0.125 | 0.188 | 0.188 | 0.156 |

Pre-registered gate (declared in the script before the first run): A recall@3 ≥ 0.875
**and** A beats C on ≥ 2 queries **and** A > B strictly → **PASS** (0.875, 13 of 16,
0.875 > 0.750).

## Reality checks

- **Rank-1 is not better than titles alone** (0.500 vs 0.562). The note index pays off
  at rank 3, which is what a reviewer reads; the instrument is not claiming better
  first-hit precision than a filename.
- **Passage-level retrieval loses by 4 queries** on this corpus. Short passages make
  rare words look rarer (IDF over passages), so a 40-token footnote outranks the card
  that actually answers the question. Kept as a measured arm so it is not re-proposed.
- **The eval is card-targeted by construction**, so no card prior was added to the
  ranker: a "cards before drafts" boost would be self-fulfilling here. `--kind card`
  filters the corpus instead, and the filter is a user choice, not a ranking claim.
- **Two queries are not in the top 3, and only one is a true miss:** `insidercat-source-audit`
  is rank 5, `discord-eod-truncation` is **rank 236** (its query says "payload limit" where
  the note says "1,990 chars"). That is the real limit of a lexical index — a semantic
  matcher would be a new substrate, which is Lane A.
- **A demo query still misses:** *"did we already measure the slug cap"* returns
  `tr38-rec3-scorer-dead-slug-cache` at rank 1, not `slug-cap-token-granularity`
  (which repeats "cap" and "slug" in a 4 KB note). Reported, not tuned away: tuning on
  the same 16 queries is how a retrieval number stops meaning anything.

## Verdict

Ships as a read-only tool. It answers, with paths and status columns, and it prints
`!awaiting-approval` on any card carrying that tag — so the two things that actually
go wrong (re-deriving a Done measurement, or shipping a proposal that is already
queued for a yes) are visible in the output rather than in the next audit.

- Reproduce: `python3 scripts/ops-record-lookup.py --eval --json` (writes `data/ops-record-lookup.json`)
- Ask: `python3 scripts/ops-record-lookup.py --query "..." --kind card --k 5`
- Self-test: 9/9 arms (`--self-test`), incl. a refusal arm for an eval file naming a
  card that does not exist.

**Not wired into the reviewer crons.** That is the next step and it touches cron
prompts, not code; the tool has to be shown to a reviewer before it can save anyone
time.

## Found in passing (carded, not fixed)

`data/roadmap.json` has no schema enforcement on `note`: `tr39-print-type-ingest-guard`
stores it as a JSON **array** (1 of 308 cards), and the first version of this
instrument crashed on it. Any reader doing string work on `.note` breaks; the writer
(`scripts/roadmap-add-card.py`) only checks that the key is present. Carded as
`roadmap-note-schema-defect`.
