# Market→news lead test — STAGE A result: KILLED at the gate

**Verdict: STAGE A FAILS.** The pre-registered bar is entity-map precision ≥85%; the repaired extractor
scores **80.0%** strict (16/20) on a fresh, non-overlapping 50-market sample. The card's own kill rule —
*"precision <85% → stop"* — fires, so **Stage B (the lead test itself) is not run**. Nothing about price
was measured, and nothing in the bot changed.

## Basis (population / clock / level)

- **Population**: live Polymarket markets, `active=true & closed=false`, ordered by 24h volume desc, first
  2,000 (gamma), fetched **2026-11-08T02:06:10Z**. That is the volume head of the board, not the whole board.
- **Level**: one market question = one entity map. Precision is scored per market (a map is PRECISE only if
  *every* extracted entity is the proposition's subject).
- **Audit 2 sample**: offset 20, stride 40 over that order → 50 markets, **20 mapped / 20 ambiguous /
  10 no-candidate**. Non-overlapping with audit 1.
- **Coverage clock**: 7 complete days, **2026-11-01T00:00Z → 2026-11-08T00:00Z**, per-entity news items from the
  Google News RSS index (keyless, quoted query).

## The two gates

| Gate | Bar | Measured | Result |
|---|---|---|---|
| Map precision (audit 2, post-repair) | ≥85% | **80.0%** (16/20; Wilson 58.4–91.9%) | **FAIL** |
| Map precision, "primary subject recovered" reading | ≥85% | 85.0% (17/20), 0 margin | ON the bar, not over |
| Map precision (audit 1, pre-repair, DEVELOPMENT set) | — | 65.2% (15/23) | used to induce the repairs |
| Coverage reach: mapped markets with ≥5 items/7d | ≥20 | **386** of 485 fully-queried markets | pass (moot) |

Coverage, so nobody re-asks: of 836 mapped markets, the top-400 entities by market support fully cover **485**
markets; of those, **386 (79.6%) carry ≥5 news items in the 7 days**, median 52 items, 8.7% at zero, and
**244/485 carry a saturated entity** (the RSS index caps at ~100 items per query, so those counts are a lower
bound). Bulk is not the problem. The map is.

## Why it fails — two structural classes, not sample noise

1. **Place name standing in for a team** (`Spread: Hawai'i (-7.5)` → `Hawai'i`; the news flow is the state, not
   the Rainbow Warriors). Same shape as `Alaska Senate` for a race.
2. **Theme entity with the actor dropped** (`Trump declassifies new UFO files` → `UFO` alone, because `Trump` is
   an ordinary dictionary word and doctrine refuses ordinary words). The query then retrieves UFO news that has
   nothing to do with the proposition.

Plus the two that were repaired and stayed fixed: bare plural nicknames (`Islanders`, `Eagles` — singular is a
dictionary word) and malformed spans (`Rock' Johnson`, `Gen.G Make`, `Stephen Smith` after a dropped initial).

Neither surviving class is fixable with the current doctrine. Both need a **gazetteer** (teams/orgs → canonical
entity) or a **type test** (is this span a person/org/place, and is it the grammatical subject?), i.e. the
extractor must know something about the world, not just about capital letters.

## Extraction yield (the part that is useful whatever happens next)

Of 2,000 live markets: **836 mapped (41.8%)**, 721 refused as theme-level by the ambiguity cap (36.1%),
443 with no specific named entity at all (22.2%). The ambiguity cap is doing heavy work — `bitcoin` alone
resolves 81 live markets, `elon musk` 58, `us` 46.

## Declared substitutions (instrument, not strategy)

- The card named **GDELT Cloud per-entity queries**. That API has answered HTTP 403 on every call since
  2026-10-02 (dead plan). Substituted: **Google News RSS** per entity (keyless, carries `pubDate`).
- The keyless **GDELT 2.0 event export** was tested first and **rejected for this purpose**: its `Actor1Name` /
  `Actor2Name` fields carry countries and generic roles (POLICE 2,479, PRESIDENT 2,009, GOVERNMENT 2,002 in one
  day) and **zero person names** — `TRUMP`, `NETANYAHU`, `PUTIN` all absent. It cannot resolve a proposition
  entity, so it cannot answer Stage A.

## What would change this answer

A team/org gazetteer (Keybase/Wikidata-style alias table) plus a person-vs-place type test, then a **fresh**
audit on a new sample (offset 40). If that reaches ≥85% strict with n≥40 mapped markets, Stage A re-opens and
Stage B becomes fair. Until then the lane is not worth a day of measurement.

## Instrument / rollback

- `scripts/market-news-lead-stage-a.py` — `--self-test` (19/19, includes negative controls that prove the
  doctrine can REFUSE), `--sample`, `--labels`, `--coverage`.
- Artifacts: `data/market-news-lead-stage-a.json`, `.sample.jsonl`, `.sample2.jsonl`, `.labels1.json`,
  `.labels2.json`, `.coverage.jsonl`.
- Rollback: delete those six files and the script; nothing else reads them.
