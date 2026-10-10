# GDELT lane: moved to the keyless 15-minute bulk feed

*Instrument `src/gdelt_bulk.py` v0.2.0 · backfilled 2026-10-02 22:00Z → 2026-10-10 09:00Z · 2026-10-10*

## Verdict

The GDELT lane appends again, keyless, from GDELT's own 15-minute export files — proven with real rows, not
a probe. Everything below was measured on the real feed today.

- **The Cloud DOC API is out from this host**: 5/5 calls returned HTTP 429 at ≥8 s pacing (probed at swap
  time). The endpoint answers, but the server's actual rate policy is not the advertised 1 req / 5 s.
- **The bulk route works with no key and no plan**: `data.gdeltproject.org/gdeltv2/lastupdate.txt` answers
  200, and one `.export.CSV.zip` is ~57 KB / ~900 events fetched in <0.1 s with `DATEADDED` equal to the
  file's own stamp — genuinely fresh, not a cached re-issue.
- **Corpus now**: 717 stamps / 746,116 events / **220,163 matched rows** in 9 daily gzipped files
  (2026-10-02 → 2026-10-10), zero duplicate `item_id`s, ~24.5k rows and ~1.9 MB per day.
- **Cron wiring is unexercised**: the research-bot job last ran 01:42 CDT (pre-swap); the first end-to-end
  run under the wrapper is 07:42 CDT.

## What the collector does

- Walks the published `:00/:15/:30/:45` stamps forward from a cursor in `data/gdelt-bulk-cursor.json`,
  stopping on the first 404 so a gap is never silently skipped.
- Matches the only text the event table carries — the source URL slug plus actor names and action geo —
  against per-category term lists. **The event table has no article title** (`title_derived` is the URL
  slug) and no themes/entities.
- Appends one gzip member per file to `data/gdelt-bulk/YYYYMMDD.jsonl.gz` and commits the cursor per file,
  so a crash re-does at most one file.
- Cloud path bails on the FIRST plan-403 instead of burning 6 categories × 4 attempts × 10 s (~4 min) and
  writing 966 identical log lines per run.

## Backfill

`--since 2026-10-02T22:00 --max-files 900` closed the 403 gap the source swap created. The 10-02 file is
partial (the legacy DOC feed's last write was 10-02 16:51 CDT); 10-03 → 10-09 are complete 96-stamp days.

| day | rows | Macro | Finance | Health | Energy | Tech | Crypto |
|---|---|---|---|---|---|---|---|
| 10-02 (partial, 8 stamps) | 1,739 | 61% | 10% | 14% | 9% | 5% | 1% |
| 10-03 | 19,289 | 66% | 8% | 12% | 9% | 5% | 0% |
| 10-04 | 19,424 | 68% | 8% | 9% | 10% | 4% | 1% |
| 10-05 | 32,346 | 65% | 9% | 10% | 10% | 5% | 1% |
| 10-06 | 35,421 | 64% | 8% | 12% | 9% | 6% | 0% |
| 10-07 | 34,563 | 62% | 9% | 12% | 10% | 7% | 0% |
| 10-08 | 34,200 | 65% | 9% | 13% | 7% | 6% | 1% |
| 10-09 | 33,333 | 69% | 7% | 11% | 7% | 6% | 0% |
| 10-10 (to 09:00Z, 37 stamps) | 9,848 | 72% | 7% | 10% | 7% | 4% | 0% |
| **total** | **220,163** | 65.5% | 8.2% | 11.5% | 8.7% | 5.6% | 0.5% |

## Storage and durability

- The bulk feed is **gitignored** (`.gitignore:58`) because the nightly git backup has a 95 MB guard and
  this grows ~1.9 MB/day; the legacy `data/gdelt-shadow.jsonl` keeps the small Cloud/DOC shape (3,421 rows,
  last written 10-02). **A future reader must UNION the two.**
- The research bot is **not a git repo at all**, so the collector and the feed existed only on the internal
  disk. `run_research_bot.sh` now mirrors `data/gdelt-bulk/` (plus the cursor) to
  `/Volumes/Storage/gdelt-bulk/` on every run — plain `rsync`, because the current day's file grows between
  runs, and an unmounted volume prints a warning instead of failing the run.
- Verified: 220,163 rows on both sides, 18 MB on Storage.

## The term retune, measured (and why it is not just a longer list)

The retune was approved as "extend the Crypto/Tech term lists". Measured, that is not where recall was
lost — **the matcher was**.

**Full-corpus attribution** (717 stamps, original lists + 30 candidate terms, plain substring matching):
+33,328 rows (+15%), but the top contributors were embeds, not topics — `ether` matched "to**gether**"
(4,782), `amd` matched "M**amd**ani" (2,627), `defi` matched "**defi**nitive" (1,524), `hack` matched
"s**hack**" (998), `ripple` matched "c**ripple**s", `cpi` matched "N**CPI**", and `nft`/`xrp`/`ecb` matched
CAMEO actor codes (`XRPBTSD2V44O3CSHD3SMVT24GM`).

**One-day A/B/C run** (2026-10-08, all 96 stamps, three variants on the same files):

| variant | rows | Crypto | Finance | Energy | Health | Tech/AI | Macro |
|---|---|---|---|---|---|---|---|
| A: old lists + substring (what the corpus held) | 34,785 | 173 | 4,259 | 1,949 | 4,238 | 1,626 | 22,540 |
| B: old lists + whole-token matcher | 30,660 | 157 | 2,767 | 1,701 | 3,841 | 1,173 | 21,021 |
| C: shipped (new lists + whole-token) | 34,200 | 229 | 3,057 | 2,309 | 4,326 | 2,094 | 22,185 |

- The matcher alone removes 4,125 rows/day of embeds and **domain-name** matches — `rappler`→"apple" (80),
  `economictimes`→"economic" (915), `bankingnews`→"bank" (396), `administered`→"minister" (43),
  `turmoil`→"oil" (37). Those are articles tagged by the *publisher's hostname*, not by their content.
- The expansion then adds 3,540 rows back on genuinely topical tokens: Crypto **+32%**, Tech/AI **+29%**,
  Energy/Climate **+18%**, Healthcare +2%.
- **The one real trade: Finance −28%**, almost entirely the two topic-agnostic domain tags above
  (915 + 396 of the 1,202). Net across all categories: **−585 rows/day (−1.7%)**.
- The matcher is now whole-token with an inflection suffix set (`es|ed|ing|s`) so `election` still hits
  "elections" and `bank` still hits "banks"/"banking"; the *derivational* losses (protesters, diplomatic,
  congressional, presidential, healthcare, banking, cryptocurrency, cybersecurity, chipmaker, oilfield) were
  found by measuring which words dropped out and are now explicit terms. 17 unit cases: 9 measured false
  positives rejected, 8 targeted slugs still matched.
- The 8-day corpus was rebuilt under v0.2.0 so the whole history is homogeneous (rows carry `version`).

## Still open

- **The atlas is not re-pointed.** `phase-gdelt-atlas` stays frozen on the 403-ing page fetches; its only
  working source is the same bulk route, and it needs its own story/geo mapping.
- **The event table is not a drop-in for a downstream matcher.** It carries CAMEO codes, Goldstein, AvgTone,
  mention counts and a source URL — no themes, no entities, no title. If the A2 wiring needs themes/entities,
  the **GKG** files (~2.9 MB/file, article-level) are the upgrade, and only the matching step changes.
- No consumer reads the feed yet (shadow-only, no webhook, not in `RegulatorySignal`).
