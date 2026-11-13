# ML feed REC 2 — record bookmaker consensus odds forward

**Date:** 2026-11-12 · **Lane:** A (proposal only — nothing applied, nothing merged, `prisma/dev.db` read-only)
**Card:** `ml-feed-bookmaker-odds-recording` (approvals `apr-ml-feed-bookmaker-odds-recording`, approved 2026-11-12T16:45Z)
**Instruments:** `scripts/bookmaker-gap-corpus-audit.py` → `data/bookmaker-gap-corpus-audit.json` (new, committed with this doc); `scripts/bookmaker-odds-record.py` (built 2026-10-29, sample-validated); `scripts/odds-gaps.py` (the live collector).

> **Verdict.** Do **not** buy a vendor tier now. Record forward at $0 on a repaired free path — the key we
> already hold — and let the card's own pre-registered test run once. The corpus we already own cannot
> answer that test, and it fails in three separate ways that all had to be measured before any vendor
> question was worth asking. The clock starts on day 1 whether we pay or not, so paying today buys
> coverage, not time — and coverage is the one axis where the vendor's marginal value is measurable
> (~23% of our sport flow) and unproven at its price.

---

## 1. The decision, stated as the card wrote it

The card's rule, kept verbatim:

> Record 60 days of pre-match consensus implied probability for markets existing on **both** venues.
> Adopt only if the consensus-vs-Polymarket gap predicts settlement direction at **≥55%** on
> **≥200 paired observations**.
> **Refuted if** ≤52%, or paired markets number under 100 (then drop the lane rather than extend it).

What that rule needs, which nobody has yet established:

1. a corpus of pre-match book quotes that are de-vigged and on the **same side** as the Polymarket price;
2. a pairing between the two venues that actually fires on the sports we trade;
3. settlement labels read from the venue, not inferred from prices.

Point 1 and 2 both fail today. Section 4 measures it; section 5 is the repair.

---

## 2. What the vendor actually sells (verified at the primary source)

Read live 2026-11-12 from the HF API and the vendor's own bundled files (`data/cache/oddsrelay-sample/`),
not from the Reddit post the card quotes.

| Claim | Verified value | Source |
|---|---|---|
| Licence | `cc-by-4.0`, 10K–100K rows, `oddsrelay/uk-bookmaker-prices-sample`, last modified 2026-10-14 | HF `/api/datasets?search=oddsrelay` |
| Sample size | 20,374 raw prices, **15,820 matched**, 186 events, 66 books | `summary.md`, `bookmakers.csv` |
| Venue types | **Bookmakers only — 0 of 66 are exchanges** | `bookmakers.csv` grep |
| History / closing | none. "No history or closing prices, in the sample or in the feed. Pre-match only." | vendor statement, card |
| Snapshot instant | 2026-10-11T20:16:34Z, one instant, starts inside 24h | `summary.md` |

**Two corrections to the card's own framing.**

- The card says the feed carries "Betfair/Smarkets/Matchbook/BETDAQ **lays**". The vendor's own
  `summary.md` says: *"Venues: bookmakers only. Every exchange, and every venue under the Betfair name, is
  left out."* The sample contains **zero** exchange keys. Whether the paid feed differs is **unverified** —
  do not price a lay/back arb capability that the vendor's own data does not show.
- The feed's field vocabulary, sport keys and board shape are **The Odds API's own**
  (`baseball_mlb`, `ice_hockey_nhl`, `basketball_nba_preseason`, `tennis_atp_shanghai`, "`bookmaker_key`
  — the same one the API uses"). The marginal purchase is therefore a wider **sport-key set plus name
  matching**, not a new information source. That matters in section 6, because we already key the
  underlying provider.

---

## 3. Coverage fit — measured against our book, not against the post

| Measure | Value | Basis |
|---|---|---|
| Traded markets, all-time | 4,091 | `data/bookmaker-overlap.json` (2026-10-29) |
| Of which sport | 890 (21.8%), **100% in families the feed lists** | same |
| Traded markets, last 60d | 1,433, of which sport 534 (37.3%) | `PaperTrade.openedAt` |
| Largest sport families, last 60d | nba 117, nhl 76, dota 74, mlb 67, ufc 51, epl 42, ucl 39, atp 20 | same |

The card's "coverage mismatch" premise is **wrong as stated**: our sport markets are exactly the families
the feed lists. The real mismatch is narrower and is about *sport keys*, not sports — see section 5.2.
Horse racing and darts are in the sample and have no Polymarket listing, which costs nothing (we would
simply never pair them).

---

## 4. Reality check — the corpus we already own cannot answer the card's test

`data/odds-gaps.jsonl` is the free bookmaker-vs-Polymarket corpus we have been collecting since September
against the key already in `.env`. It is the obvious place to answer the question for free. It cannot.

### 4.1 Three defects, measured

| Defect | Measurement | Why it kills the read |
|---|---|---|
| Wrong bookmaker market | **313 of 567 rows (55.2%)** pair a totals / first-5-innings Polymarket market against a moneyline `h2h` price | The "gap" compares two different bets |
| Sides inverted | median \|book − pm\| = **0.226**, median \|book − (1−pm)\| = **0.034**; 235/254 rows (92.5%) closer flipped | The stored columns are opposite sides of the same bet |
| No de-vig, one side only | `de_vigged: false`; only the `home_team` price is stored | A vigged probability is biased low by ~half the margin (soccer 8.7%, MLB 7.0%) |

The mapping is not a guess. Against **venue** settlement (gamma `/events?slug=`, closed + `uma = resolved` +
`outcomePrices` 1/0; 86 of 101 moneyline markets labelled), each column lands on exactly one side:

| Arm (n = 86 markets) | Direction hit | Brier |
|---|---|---|
| `pmProb` vs first-named side won | 61.6% | 0.2286 |
| `pmProb` vs second-named side won | 38.4% | 0.3444 |
| `bookImplied` vs second-named side won | **67.4%** | **0.1973** |
| `bookImplied` vs first-named side won | 32.6% | 0.4276 |

`pmProb` prices the **first-named** team; `bookImplied` prices the **second-named** team. The two venues
agree on the favourite 81/86 (94.2%) of the time once that is corrected — i.e. **the stored "gap" is a sign
convention, not a disagreement between venues.** Any edge read off the file as stored is an artefact, in
either direction.

### 4.2 The card's statistic, side-corrected, on the pre-match subset

| Arm (pre-match first observation, n = 45 markets) | Direction hit | Brier |
|---|---|---|
| Polymarket (`pmProb`, as stored) | 55.6% (25/45) | 0.2533 |
| Bookmaker (`1 − bookImplied`, same side) | **57.8% (26/45)** | **0.2480** |

Read this as **unresolved, not passed**: 45 markets is far under the card's 100-market floor and 200-obs
requirement, and a 0.005 Brier edge on n=45 is inside noise. Note the direction: on the *full* pool
(including in-play rows, which are look-ahead) the book's Brier advantage is 0.031; restricted to
pre-match it collapses to 0.005. **The apparent edge lives almost entirely in in-play quotes** — which is
precisely why the card's pre-match gate is load-bearing and why no in-play row may enter the test.

Also note the bias direction: `bookImplied` is **vigged**, so Brier(book) is pessimistic by roughly half the
margin. The 0.2480 figure is a lower bound; a de-vigged connector would score slightly better. That makes
the forward design's de-vig requirement a measurement requirement, not a nicety.

### 4.3 The collector is also dead, silently

`copybot-odds-gaps` runs every 360 min, `last_status: ok`, and has written **nothing since 2026-10-28**
because its sport is hardcoded to `baseball_mlb` and the MLB season ended. Probed live 2026-11-12:

| Probe | Result |
|---|---|
| `odds-gaps.py --sport baseball_mlb` | `Events: 0` → "Logged 0", exit 0 |
| `odds-gaps.py --sport basketball_nba` | `Events: 8`, **0 paired**, 0 logged |
| `icehockey_nhl` / `soccer_epl` | 13 / 20 events, **0 paired each** |
| `mma_mixed_martial_arts` | 65 events, 2 paired |

Root cause of the zero pairing, found by reading the venue's own naming: Polymarket titles team markets by
**nickname only** — `Cavaliers vs. Knicks` — while `odds-gaps.py` requires *every token* of
`Cleveland Cavaliers` to appear in the question. `"cleveland"` is never there, so **the collector cannot
pair a single team-sport market**. It has been "ok" for weeks while recording nothing, and it would have
recorded nothing even in season.

**This is the decisive fact for the vendor question:** the pipeline that has to run for 60 days does not
work today, and no amount of vendor money fixes it. It is a matcher defect, not a coverage defect.

---

## 5. What to build instead (specification — not applied)

### 5.1 Recorder requirements

One append-only row per `(pm_market, side, as_of)` — never a single `gap` scalar, which is what made the
side inversion invisible for two months:

| Column group | Fields | Why |
|---|---|---|
| Identity | `as_of`, `source`, `region`, `event_id`, `sport_key`, `competition`, `commence_time`, `pm_market_id`, `side`, `pair_method` | Every row must be re-derivable and auditable |
| Book side | `book_fair_p`, `n_books`, `p10`, `p90`, `dispersion`, `devig_method` | Consensus **de-vigged**, median across books, dispersion kept |
| Venue side | `pm_side_label`, `pm_price` | The label is stored so the sign can never drift again |
| Timing | `lag_hours = commence_time − as_of`, `prematch` (bool) | The card's gate is data, not a later guess |

Plus a **reject ledger** (`data/bookmaker-consensus-rejects.jsonl`) with reason codes —
`pm_market_not_found`, `ambiguous_nickname`, `date_mismatch`, `book_no_price`, `not_prematch` — so pairing
yield is a measured number instead of silence. This is the failure mode the current collector has.

### 5.2 Pairing: by slug, not by question text

Polymarket's slug encodes both teams and the date (`nba-cle-nyk-2026-11-11`). Pair on
`(sport team abbreviations, commence date)` and use the question only to *confirm*, with a nickname
fallback (last token) and an explicit ambiguity rejection. Never require a city token the venue does not print.

### 5.3 Sport roster from the plan, not from a default

Live `/v4/sports/` probe (0 credits) returned 80 keys, `x-requests-remaining: 500`. In-window availability
today, matching our families: **NBA, NHL, NFL/NCAAF, ~30 soccer competitions, MMA/boxing, cricket, handball,
golf** — but **no baseball** (off-season), **no esports keys**, **no darts, no horse racing**, and tennis is
`tennis_wta_finals` only.

| Family (trailing 60d) | Free key | OddsRelay sample |
|---|---|---|
| nba 117, nhl 76, mlb 67 (off-season now) | yes / yes / out | yes |
| epl 42, ucl 39, uel 7 | yes | yes |
| ufc 51 | yes (`mma`) | **no key in sample** |
| dota 74, val 11, lol 5, cs2 3 | **no** | yes (esports) |
| atp 20, wta 8 | **wta_finals only** | yes |

So the free path covers roughly **60–70% of our in-window sport flow**, and the vendor's genuine marginal
coverage is esports + ATP ≈ **23%** of it.

### 5.4 Quota math (this is the binding constraint on cadence)

Measured from the live headers: `/odds` with `regions=eu,uk,us` costs **3 credits per call** (500 → 494
after two calls, then −3 each). The free tier is **500 credits/month**.

- `regions=uk` only (all we want — UK books, same region the vendor's sample uses) → **1 credit per call**.
- 4 sport keys × 3 calls/day = 12 calls/day = **360/month** — fits with margin.
- 4 sport keys every 6h = 24/day = **720/month** — exceeds the quota, silently degrading to 429s.
  The current 6-hourly schedule would break the month within two weeks of going multi-sport.

### 5.5 Estimated yield

Trailing 60d: 101 MLB moneyline markets reduced to **45 with a pre-match first observation** (44.6%). Forward
window (Nov 12 – Jan 11) covers NBA/NHL/NFL/soccer/MMA ≈ 341 family-markets, no MLB, no esports → estimate
**~150 paired pre-match markets in 60 days**, clearing the card's 100-market floor with margin. This is an
estimate, labelled as one; the recorder's own reject ledger is what settles it.

---

## 6. The vendor question, answered

**Do not buy now.** Five reasons, in order of weight:

1. **It does not buy time.** No history and no closing prices exist in the feed, so the 60-day corpus starts
   the day the recorder runs — identical for a free or paid source.
2. **It does not fix the thing that is broken.** The failure is the matcher (0/41 team-sport events paired
   today), not missing books. A paid feed behind the same matcher records zero.
3. **The marginal coverage is ~23%** (esports + ATP), and esports is the family where pairing is least proven.
4. **The "exchange/lay" advantage in the card is not in the vendor's own data** (0 of 66 books are exchanges).
5. **Price unknown** for a signal that, on the only corpus we have, is indistinguishable from the venue it
   would compete with (Δ +2.2pp, n=45).

**Pre-registered reopen condition** (so this is a decision, not a deferral): reopen the purchase **only if**
the repaired free run reaches day 60 with **fewer than 100 paired markets** *and* the reject ledger shows the
losses are `pm_market_not_found` / sport-key absences concentrated in **esports or ATP** — i.e. coverage,
not matching. Any other failure mode is ours to fix, not to buy.

---

## 7. Option set (recommendation first)

| # | Option | Cost | What changes |
|---|---|---|---|
| **A** | **Repair the free recorder, schedule it, run the card's 60-day test** | **$0** (+360 of 500 monthly credits) | New script + cron shim + prereg row; no rule, no sizing, no DB write |
| B | Buy an OddsRelay tier now | unknown | Adds esports/ATP coverage; adds a paid dependency before any signal is shown |
| C | Drop the idea | $0 | Removes the card; loses the one genuinely orthogonal external probability we can measure |

**Recommend A.** C is the honest fallback if A's pre-registered test fails — that is what the refutation
condition is for.

### Overrides I made, each overridable in one line

1. **Esports is out of scope for the free run.** Changes what we measure: coverage ≈390 of 534 rather than
   ≈483 family-markets. Revert by buying option B, or by adding a non-Odds-API source for esports only.
2. **Cadence is 3 calls/day per key at `regions=uk`, not 6-hourly.** Changes the credit burn: 360/month vs
   720/month (which breaks the quota). Revert by editing one line in the cron shim — and expect 429s.
3. **Settlement labels come from gamma `events?slug=`, not the archived CLOB route.** The CLOB
   `/markets/<conditionId>` route returns **403** from this host (probed); gamma returns 200 with
   `closed`/`uma`/`outcomePrices`. If gamma ever stops serving resolved slugs, the test fails to n=0 rather
   than silently scoring a price proxy — that failure is loud by design.

---

## 8. Operator commands (apply step — not run here)

Nothing below has been executed. Each line is idempotent and reversible in one step.

```bash
# 1. Re-read the measurement this proposal rests on (read-only, ~10s once labels are cached)
cd ~/polymarket-copybot && python3 scripts/bookmaker-gap-corpus-audit.py

# 2. GO — build the repaired recorder (writes data/bookmaker-consensus.jsonl + rejects ledger; no DB)
#    [script to be written on approval — section 5.1 is its spec]
#    python3 scripts/bookmaker-consensus-forward.py --dry-run     # pairing yield, writes nothing
#    python3 scripts/bookmaker-consensus-forward.py               # first real rows

# 3. GO — schedule it (3 calls/day/key, regions=uk, 1 credit/call)
#    cronjob: script scripts/cron-scripts/copybot-bookmaker-consensus.sh, interval 480m,
#             no_agent=true, deliver=local, failure_deliver=origin

# 4. REVERT everything
#    disable the cron job; the new files are append-only data, deleted with rm
#    data/bookmaker-consensus.jsonl data/bookmaker-consensus-rejects.jsonl
```

---

## 9. Verification log (what was actually probed, 2026-11-12)

| Probe | Result |
|---|---|
| HF `api/datasets?search=oddsrelay` | 200; `cc-by-4.0`; 10K–100K rows; lastModified 2026-10-14 |
| `bookmakers.csv` | 66 books, **0** exchange keys |
| `gamma /events?slug=mlb-ari-kc-2026-09-08` | 200, 101,591 B, `closed=true`, `uma=resolved`, prices `["1","0"]` |
| `clob /markets/<conditionId>` | **403** (709 B) — not used, documented |
| `api.the-odds-api.com/v4/sports/` | 200, 80 keys, 500 credits remaining, 0 used |
| `odds-gaps.py --sport baseball_mlb` | `Events: 0` (off-season) → the 6-hourly cron's silent no-op |
| `odds-gaps.py --sport basketball_nba` | 8 events → **0 paired** |
| pairing-yield probe (nba/nhl/epl/mma) | 0/8, 0/13, 0/20, 2/65 paired |
| `bookmaker-gap-corpus-audit.py` | 86/101 moneyline markets labelled from venue settlement |

Adjacent defect found while probing, **not** this card and not fixed: the weekly `ML data-feed scout` cron
is failing every run with `HTTP 402: Insufficient Balance` (last run 2026-11-09) — it is silently producing
nothing, which is why this card's own research lane has been quiet.

---

## 10. What I did not do

- No `apply-vNN.ts` run. RuleSet still **v72**.
- No write to `prisma/dev.db` — every query opened `mode=ro`.
- Nothing merged to `main`; no cron job created or edited; no vendor contacted or paid.
- The card note references `drafts/ml-feed-bookmaker-odds-recording-20261029.md`, which **does not exist** in
  the repo — the note's 55.0%/50.8%/Brier-0.2479 figures were never committed with a script, and they do not
  reproduce on the corrected basis above. **This document supersedes that note.**

**Reproduce:** `python3 scripts/bookmaker-gap-corpus-audit.py` →
`data/bookmaker-gap-corpus-audit.json` (labels cached in `data/cache/bookmaker-gap-labels.json`).
