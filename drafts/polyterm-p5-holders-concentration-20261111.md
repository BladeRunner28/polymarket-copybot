# Polyterm P5 — `/holders` concentration metric: the instrument was DEAD, and the number it would have produced was not a supply share

**Card:** `polyterm-p5-holders-concentration` (roadmap) · kanban `t_803cc632` · audit §P5
(`drafts/polyterm-audit-2026-09-28.md:183`) · lane **B** (instrument repair: nothing here changes
what the bot decides or how much it risks) · run 2026-11-11.

**One line:** the `/holders` read that P5 shipped on 2026-09-28 has been returning **HTTP 410 Gone**
since the Data API v1 retirement — every row it produced after that carried a zeroed concentration
block and the flag `holder_concentration_unavailable` — and the statistic itself divided by the
holders it happened to fetch rather than by the outcome's supply. Both are fixed and verified
against the live venue; the metric now lands in `data/market-hygiene.jsonl` for **25/25** markets on
the scorer's universe and **40/40** markets on our own book, with no nulls and a supply identity
check that closes to **0.0%**.

---

## 1. What was broken

### 1a. The endpoint was retired (the metric was a null, silently)

`scripts/shadow-market-hygiene.ts::fetchHolders` called

```
https://data-api.polymarket.com/holders?market=<conditionId>&limit=100
```

Measured today, any path without a `/v2` prefix on the Data API answers:

```
410 {"error":"Data API v1 has been retired","migration":"https://data-api.polymarket.com/v2/",
     "docs":"https://docs.polymarket.com/api-reference/data-api/overview"}
```

The call sat inside a `try/catch` that logged and returned `null`, so the failure was invisible in
the row: the concentration block came out zeroed and the only trace was a quality flag. The 8 rows
written on 2026-09-28 do carry real holder data (`holderCount: 50 … assessed: true`), so the break
sits somewhere between then and now — the retirement, not the port, is what killed it.

v2 is a different route **and** different params **and** different field names:

| | v1 (dead) | v2 (live) |
|---|---|---|
| route | `GET /holders` | `GET /v2/holders` |
| market filter | `?market=<conditionId>` | `?conditionId=` (aliases `condition`/`condition_id`); **`market` is rejected**: `"'market' is not a query param on this API: filter by condition id with 'condition'"` |
| envelope | bare array of `{token, holders}` | `{data: [{token_id, holders}], pagination {limit, offset, has_more, next_cursor}}` |
| holder fields | `proxyWallet`, `outcomeIndex` | `proxy_wallet`, `outcome_index` |
| paging | none | **cursor-only**; `has_more` + `next_cursor` |

### 1b. The denominator was the fetched page, not the outcome's supply

`holderConcentration()` divided every top-N share by the sum of the amounts **it was handed**. With
the old `limit=100`, the number labelled `top1Share` was a share of *the top 100 holders we happened
to list*, not of the outcome's supply. Measured on 8 of our markets (`probe_bias.py`, 2026-11-11),
the top-100 list covered **96.6%–100.0%** of the true supply (mean 99.5%) — so the error is small on
concentrated markets and grows exactly where the market is diffuse, i.e. where the metric would be
interesting.

### 1c. One market-level number hid a per-outcome asymmetry

`fetchHolders` returned "the worst-case outcome" but selected it by **largest total supply** — and
in a complementary market both outcomes have *identical* supply, so the choice was arbitrary (first
entry wins). Measured on the 25 markets of today's run, the two sides of the same market differ in
top-5 share by a **median of 25.3 percentage points** (min 2.3, max 65.3).

---

## 2. What shipped

| file | change |
|---|---|
| `src/lib/holders-read.ts` **(new)** | `readOutcomeHolders(conditionId, {limit, maxPages, fetchJson})` — v2 route, walks `next_cursor` to exhaustion, returns **per outcome**: holders, enumerated `supplyShares`, `complete`. Fails loudly on an unexpected envelope, reports an empty list as `ok: false` (a null, never a zero). The `fetchJson` injection point exists so the walk is unit-tested, not just eyeballed. |
| `src/lib/market-hygiene.ts` | `holderConcentration(holders, {supplyShares, supplyComplete})` — divides by the **supply**; never by less than it can see (a stale supply below the listed sum cannot inflate concentration); adds `supplyShares`, `listedShares`, `supplyComplete` and `topHolder {wallet, share}` to the profile. |
| `scripts/shadow-market-hygiene.ts` | reads v2, writes per-outcome profiles (`concentrationByOutcome`), `.concentration` = the **most concentrated side** (top-5, tie-broken on top-1), `holdersBasis` (endpoint, pages, supplyComplete, error), and the flags `holder_concentration_unavailable` / `holder_supply_truncated`. `HYGIENE_HOLDERS=0` still disables the read and now records *why* (`disabled (HYGIENE_HOLDERS=0)`), instead of a zero that reads as "clean". |
| `scripts/holders-concentration-read.ts` **(new)** | the reproducible read over the JSONL: usability, per-outcome asymmetry, Spearman vs the hygiene scores, and the structural-holder tally. Refuses to print a pre-registered verdict it cannot take. |
| `scripts/holders-coverage-our-markets.ts` **(new)** | gate (a) applied to **our** universe: slug → conditionId → holder read for the markets our book actually holds, with the complementary-outcome supply identity check. |
| `tests/holders-read.test.ts` **(new)**, `tests/market-hygiene.test.ts` | 5 pagination tests (cursor followed, cap → truncated, bad envelope → loud failure, empty → unavailable, outcomes kept apart) and 3 metric tests (supply denominator, stale-supply guard, top holder named). |

---

## 3. Results (measured, this run)

### 3a. Gate (a) — is the read usable on the markets we trade?

`npx tsx scripts/holders-coverage-our-markets.ts --markets 40` (our book: 40 markets by leg count,
open or closed in the last 7d):

```
slug -> conditionId resolved : 40/40
concentration assessed       : 40/40
empty holder lists (NULL)    : 0
endpoint errors              : 0
truncated walks (upper bound): 0
holders per market: median 125 max 1373
top5 share (worst outcome): median 94.9% range 52.6%-100.0%
supply identity check (complementary outcomes must match): 40 markets, max gap 0.0%
```

`npx tsx scripts/shadow-market-hygiene.ts` (the scorer's own universe, top-25 by 24h volume) wrote
25 rows: `assessed=25/25 truncated=0`, holder counts median 176 max 4,129, outcome supply
65.9k–6.4M shares.

**Verdict on (a): the endpoint is usable — not a null.** No empty lists and no errors on either
universe. The null case is now *recorded* anyway (flag + `holdersBasis.error`), so an outage cannot
be mistaken for a clean market.

### 3b. Gate (b) — does concentration carry information independent of the hygiene score?

Descriptive only, one run, 25 markets (`scripts/holders-concentration-read.ts`):

| arm | Spearman | n |
|---|---|---|
| top5(worst side) vs risk score | **−0.287** | 25 |
| top5(worst side) vs wash score | **−0.237** | 16 wash-assessed rows |
| top5(worst side) vs volume24hr | −0.227 | 25 |
| top5(spread side) vs risk score | **−0.367** | 25 |

No CI, no era split, n=25 — this is a *signal that concentration is not independent* (weakly
negative against both hygiene axes and against volume), not a validated finding in either direction.

**A defect in this read, caught before it shipped:** the first version correlated the wash arm over
all 25 rows, counting the 9 rows whose wash profile is **unassessed** (a missing input) as a zero
score. That flipped the reading from −0.237 to −0.626 — the same "missing is not an observed zero"
trap the P3 card repaired in the risk score. The published number excludes unassessed rows and
prints its own n.

### 3c. The finding that matters more than the correlation: it is ONE address

```
distinct #1 holders: 16 across 25 rows
  0xa5ef39c3d3e10d0b270233af41cac69796b12966  #1 in 9 row(s)  median share 96.1%
  0xc9bfc7986767173b4f1c3fc9b2c6b255fc7381c0  #1 in 2 row(s)  median share 46.3%
rows whose #1 holder alone holds >=50% of that outcome's supply: 11/25
```

The same proxy wallet is the largest holder of one side of **9 of 25** unrelated markets at a median
**96.1%** of that outcome's supply, and holds **0%** of the other side (verified on 8 markets: it
appears on outcome 1 only, at 44%–99.7%). That is structural inventory — a mint/sell-the-other-side
position, not conviction. So a raw top-N share mostly measures *where the minted inventory sits*, and
any read of this metric has to name the address and report concentration with it stripped.

**This is the honest answer to the card's original question.** The metric is real, the endpoint
works, the supply denominator is right — but the top-N number is dominated by one structural holder,
so its value as a "can a few wallets move this outcome" signal is unproven and the *default* reading
of it is misleading.

### 3d. Gate (c) — the pre-registered read: NOT TAKEN, and not takeable from this file

It requires `Spearman(concentration, per-$1 realized return)` with the sign checked inside each
`ruleSetVersion` era on ≥150 settled legs per arm, joining a holder snapshot at/before **each leg's
decision instant**. `market-hygiene.jsonl` is a spot snapshot of the top-25 markets at one instant
with no leg join — it can only support a **forward** read once a snapshot series exists and legs
accumulate in those markets. The read script prints that refusal rather than a number.

---

## 4. Verification evidence

- `npx tsc -p tsconfig.json --noEmit` → clean.
- `npx vitest run tests/holders-read.test.ts tests/market-hygiene.test.ts` → **24 passed**. The
  pagination walk is tested against a fake transport (cursor followed, page cap → `truncated`, bad
  envelope → loud failure, empty → unavailable, outcomes kept apart), which is the part a live smoke
  run cannot pin down.
- Live dry run, holders ON: `assessed=3/3 truncated=0` with plausible shares and the top holder
  printed per row.
- Live dry run, `HYGIENE_HOLDERS=0`: `holders=off assessed=0/2 … unavailable=2`, each row carrying
  `disabled (HYGIENE_HOLDERS=0)` — the disable switch works and does not invent a zero.
- Live write run → 25 rows appended to `data/market-hygiene.jsonl`; read back through
  `scripts/holders-concentration-read.ts` (the aggregation script, not the writer's own log).
- Supply identity (a market's two outcomes must carry equal share supply) closes to **0.0%** across
  40 markets on a complete walk — the check that proves the enumeration is whole. At the old
  `limit=100` it read 96.6%–100% (i.e. it was measuring a page).

## 5. Before / after, per figure

| figure | before (v1 route) | after (v2, supply denominator) |
|---|---|---|
| endpoint answer | `410 Gone` → `null` → zeroed block | `200`, `{data, pagination}` |
| concentration rows assessed | 0/25 (post-retirement) | **25/25** scored, **40/40** of our book |
| denominator | sum of fetched page (≤100 holders) | enumerated outcome supply, `supplyComplete: true` |
| unlisted share of supply | up to 3.4% | **0.0%** on complete walks |
| outcomes per row | 1 (arbitrary side) | both, with the worst side promoted |
| null vs zero | a failure looked like a clean market | flag **+** `holdersBasis.error` reason |
| pre-registered read | not taken | **still not taken** (needs a leg-level join) |

## 6. Flags (each one line, overridable)

- **Snapshot cadence: NOT wired to cron.** Nothing reads this live and the card did not ask for a
  cadence, so `shadow:hygiene` still runs by hand. The forward read (gate c) needs a series — wire it
  to a daily job if you want that read to become possible: `npm run shadow:hygiene`, no side effects
  beyond appending one JSONL row per market.
- **Page cap = 20 pages × 500 holders.** A market with >~5,000 holders per side is flagged
  `holder_supply_truncated` and its share is an upper bound. Raise `HYGIENE_HOLDER_MAX_PAGES` if a
  market that big matters; the row already says when it fired.
- **Structural holder: not excluded, only named.** `topHolder.wallet` is on every row so a read can
  strip it. I did **not** add an exclusion (it would be a rule, and which addresses are structural is
  exactly what the read has to establish).
- **Revert:** `git revert <this commit>` restores the v1 call (which is dead) and the subset
  denominator — i.e. reverting re-breaks the instrument; there is no config switch to go back to v1
  on purpose. `HYGIENE_HOLDERS=0` is the live switch that turns the whole read off.

## 7. Provenance of every number here

| number | source |
|---|---|
| `410` body, v2 route/param/field table | `probe_holders2.py` / `probe_holders3.py` (scratch, 2026-11-11) — raw responses kept |
| limit semantics, 328/276 holders at limit=500 | `probe_holders4.py` |
| 96.6%–100% supply coverage at limit=100 | `probe_bias.py` (8 markets) |
| 40/40 coverage, 0.0% supply gap | `scripts/holders-coverage-our-markets.ts` |
| 25/25 assessed, correlations, structural-holder tally | `scripts/holders-concentration-read.ts` over `data/market-hygiene.jsonl` (2026-11-11 rows) |
