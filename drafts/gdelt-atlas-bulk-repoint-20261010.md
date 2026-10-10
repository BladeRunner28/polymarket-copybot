# GDELT Atlas re-pointed at the keyless bulk route

**Applied 2026-10-10 ~14:32–19:38 UTC (user-approved in-thread).** Card: `phase-gdelt-atlas` → Done.
Commits: `cca8010` (dedupe, sibling item), this one. Live at **http://localhost:3013/atlas.html**.

## The problem

The atlas rebuild cron (`copybot-gdelt-atlas-rebuild`, `0 */6 * * *`, no_agent) had been reporting
`ok` while doing nothing since **2026-10-02**. Its source — GDELT Cloud `/api/v2/stories` — answers
`403 "API keys are not included in your current plan (free) outside an active evaluation"` from this
host. The wrapper treats "too few stories" as a *kept-snapshot* exit 0, so the failure was invisible:
the job fired every 6 hours and re-published a three-week-old snapshot of 148 stories.

## What changed

The atlas now reads the **same keyless corpus the GDELT shadow lane already consumes**
(`~/polymarket-copybot/data/gdelt-bulk/YYYYMMDD.jsonl.gz`, GDELT's published 15-minute event exports,
written by `political-research-bot/src/gdelt_bulk.py`).

- **New:** `~/gdelt-atlas/fetch_bulk_stories.py` — groups the event-level corpus into one record per
  article URL and emits build.py's story schema.
- **Patched:** `build.py` — source docstring, `salience` labelling (+ the source/formula note rendered
  under the map title), and it no longer embeds the per-country `stories` array the JS never reads.
- **Patched:** the rebuild wrapper (`scripts/gdelt-atlas-rebuild.sh`, canonical copy in the git-backed
  repo; `~/.hermes/scripts/copybot-gdelt-atlas-rebuild.sh` is now a shim — the atlas logic previously
  lived **only** on the internal disk, not in any backup).
- **Untouched:** `fetch_stories.py` (the Cloud fetcher) stays on disk, unused, as the reference for
  the schema and for the day the plan comes back.

## Before / after (measured)

| | before (frozen 10-02) | after |
|---|---|---|
| stories | 148 | **19,857** |
| countries covered | 44 | **141 / 177** |
| atlas.html | 344 KB | 569 KB |
| fetch runtime | — (403s) | 0.75 s for 3 daily files |
| feed items | 148 | 400 (top by salience) |

Event rows folded: **85,737 → 19,857 unique article URLs** over the last 3 daily files. Category mix:
Macro/Politics 12,637 · Healthcare 2,636 · Finance 1,791 · Tech/AI 1,416 · Energy/Climate 1,274 ·
Crypto 103. Top coverage: US 5,714 · India 2,516 · UK 830 · Nigeria 814 · Canada 636.

## Reality checks (what this is NOT)

- **`significance` is gone; `salience` is derived.** The Cloud's significance score is a paid metric.
  The replacement is `0.6 ×(articles/50) + 0.4 × |Goldstein|/10`, hand-weighted, range 0–1. It orders a
  viewer and nothing else — no decision path imports it. Both the map header and the tooltip say
  "derived salience" so a later reader cannot mistake it for a calibrated measurement.
- **The bulk feed is EVENT-level.** It carries CAMEO codes, Goldstein, AvgTone, mention counts and a
  source URL — no article title (titles are GDELT's URL-slug reconstruction) and no entity/theme
  fields. Real article titles and themes need the **GKG** files (~2.9 MB/file), which is a separate,
  larger change (it changes the collector's matching step, not the atlas).
- **Titles are slugs.** Cleaned of leading article ids (485 fixed) and opaque tracking paths that are
  not words (1,191 now fall back to the domain, e.g. `www.webradio.com`). They stay lowercase on
  purpose: title-casing mangles "us sanctions" and "us house" into "Us …".
- **Country is the LAST component of `action_geo`** ("Delhi, Delhi, India" → India) resolved through
  the map's own ISO3 alias table, falling back to `actor1/actor2_country`. 42 of 177 map countries have
  no coverage in a 3-day window (small states + Antarctica) — that is the window, not a bug.
- **The atlas is a viewer, not a feed.** `data/gdelt-shadow.jsonl` (3,421 rows, frozen 10-02) stays the
  small Cloud/DOC-shaped file; the bulk corpus is separate (`data/gdelt-bulk/`, gitignored, mirrored to
  /Volumes/Storage). A future reader must UNION the two.

## Verification

- Full path exercised through the **cron shim** (`bash ~/.hermes/scripts/copybot-gdelt-atlas-rebuild.sh`),
  not a hand-run: fetch → build → publish → summary, exit 0, summary line
  `400 feed / 19,857 stories | 141 countries | 568 KB`.
- Page rendered in headless Chrome against the live dashboard: header `19,857 / 141 / 10-10 19:38`,
  177 country paths with 141 carrying data, 400/400 feed rows, category chips summing within the cap,
  the derived-salience note visible under the map title, no error text or empty panels.
- `/atlas.html` served by the dashboard (200) after publication; `git`-backed copies of both scripts
  committed so the logic survives the internal disk.

## Still open (unchanged, not part of this)

- The **atlas has no durability beyond the repo copies** if `~/gdelt-atlas/` is lost (its geojson +
  build inputs are mirrored, the generated HTML is not — it is reproducible from the corpus).
- **A2 evidence wiring** (mapping news → research categories → evidence rows) remains post-window work
  on `phase-gdelt`, and it needs GKG themes/entities, not this event table.
