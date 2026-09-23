# `ObservedTrade.marketCategory` is a slug token, not a category — real category added at ingest

**Card** `observed-trade-category-field` (approved 2026-09-23) · **status** data fix applied + verified; the
scoring swap is now a separate, measured proposal · **date** 2026-09-23

## The defect, counted

`marketCategory` is `eventSlug.split("-")[0]`. Live census over all **335,443** observed rows / **863** tokens:

- **40.3%** of a stratified 2,599-row sample carries a **question/function word** as its token
  (`highest` 73,089 · `which` 10,142 · `next` 4,971 · `lowest` 4,754 · `where` 4,591 · `how` 3,736 · …).
- Token **`highest` alone wraps 14,879 distinct marketIds** — it is a bucket, not a category.
- `WalletProfile.bestCategory` — the column the wallet features call "strongest category" — reads
  `fifwc` 452, `lol` 294, `atp` 197, `mlb` 187 … and **`will` 101, `world` 97, `us` 83, `what` 74**.
- `src/lib/insider.ts:88` already documents it ("NOT a research category — the API payload fills it with
  garbage") and works around it by re-deriving the category from question text.

**Spot check on the one consumer that accidentally works:** the v45 blacklist entries `lol` / `cs2` / `nfl` are
genuinely the leagues (`LoL: Team Secret vs Karmine Corp`, `Counter-Strike: NIP vs K27`, `Panthers vs.
Cardinals`) — that is why the defect never surfaced. It is also why the token must stay: the blacklist and the
per-slug cap are defined on league-scale granularity on purpose.

## Readers enumerated (all of them)

| reader | wants | verdict |
|---|---|---|
| `src/lib/scoring/wallet.ts:112` → `bestCategory`, `categoryStrengthsJson` | a real category | **defective** — slug-token statistics |
| `scripts/score-trades.ts:717` v45 per-bot blacklist | league/token granularity | correct **because** tokens are league names |
| `scripts/score-trades.ts:266, 725-741` v45 per-slug cap (15) | league-level exposure cap | token-based by design — but see the finding below |
| `scripts/score-trades.ts:264, 447, 645` `researchCategoryFor(question, token)` | research category | question-led, token only as a hint |
| `src/lib/insider.ts:127` | research category | already re-derives from question text |
| `scripts/monitor-trades.ts` | write path | **fixed here** |

## What shipped

- **`src/lib/market-category.ts`** — a faithful TS port of the classifier that was validated against the
  vendor's own category map at **r = +0.548 over 353 wallets**: slug-token rules first (exact where the question
  is free-form), then question rules; returns `coarse` (`sports`, `esports`, `weather`, `politics`, …) and `fine`
  (`football-ucl`, `esports-lol`, `weather-temp`, …).
- **Adapter write path** (`polymarket.ts`, all 3 sites) — every `WalletActivityTrade` now carries
  `marketCategoryClass` + `marketCategoryFine` **beside** the unchanged token.
- **`schema.prisma` + dev.db** — `ObservedTrade.marketCategoryClass` / `marketCategoryFine` (ALTER ADD COLUMN,
  prisma drift diff empty); `monitor-trades.ts` persists them.

## Verification

**Parity is proven, not assumed** — `scripts/verify-market-category.py` labels a stratified 2,599-row sample with
the Python reference; `scripts/verify-market-category.ts` diffs the TS port against it row-by-row:
**`PARITY: PASS — 0 mismatches`**.

Class coverage over that sample: `weather 26.6% · other 23.1% · sports 17.6% · esports 10.4% · politics 10.4% ·
crypto 5.0% · tech 3.9% · econ 1.7% · culture 1.5%`; 101 of 251 distinct tokens classify to `other` only, and
6 tokens span more than two real categories — i.e. **tokens are not categories, measured**.

## What deliberately did NOT change

Wallet scoring still reads the token, so **no published score moved**. Swapping `categoryFitScore` onto the class
is a *scoring* change (it feeds the copy score → admission), and it now has evidence attached: the token-based
category fit measures **AUC 0.497 (C-200) / 0.525 (STANDARD)** against leg outcome — a coin flip
(see `drafts/wallet-selection-score-information-20260923.md`). Because the class now exists at ingest, a
class-based category fit is *buildable and measurable from the next scan*; it needs its own pre-registered gate.

## Side finding worth its own card: the 15-per-slug cap counts TOKENS

Last 7 days, journal-tagged `v45 market-slug cap` blocks: **1,002 — every one of them on token `highest`**, all at
"would be 16/15". The cap the v45 work intended as *league-level* exposure control is being consumed by a bucket
that spans 14,879 marketIds (weather + anything else whose event slug starts with `highest`), so a single
saturated token starves unrelated markets. Carded, not changed: it is an admission-behaviour change and the
Kelly window is frozen until Oct 8.
