# The near-certainty gate is not reading a broken mid — it is reading the **other token's price**

Card: `t_4d29ae55` (Lane A — proposal, nothing shipped) · read 2026-10-29 ·
instrument `scripts/nearcert-mark-guard-read.py` → `data/nearcert-mark-guard-read.json`
(parent: `nearcertainty-tail-shadow`, t_53dd2edd)

## Verdict

The card asked whether the detection mid needs a tick-floor / one-sided-book guard before the
gates read it. **It does not — the defect one level down is bigger and has nothing to do with
the tick floor.** The gate's operand is the price of the *sibling token* on every label-named
market, on 30.6% of all scored decisions, and the 0.000 marks are that bug — not a failed read.

Three facts decide it (all measured, not inferred):

1. **The 521 sub-0.001 marks in the sub-0.05 cohort are all exactly `0.000000`, and every one
   of them is on a market that had already closed before the decision was stamped.** 521/521.
   Not one is a live market read as zero.
2. **On those rows the mark is either a correct settled price or the sibling token's settled
   price, and which one is decided by the token's POSITION in the market, not by anything
   about the read.** Strict test (decisions stamped after `closedTime`, so the venue's
   `outcomePrices` are frozen 0/1 and the true price of our token is known exactly):

   | token we traded | decisions | mark = OUR settled price | mark = SIBLING's |
   |---|---|---|---|
   | first-listed (`outcomes[0]`) | 371 | **371** | 0 |
   | YES/NO market | 172 | **172** | 0 |
   | second-listed (`outcomes[1]`) | 359 | **0** | **359** |

   902 decisions, zero exceptions. A failed read cannot be 100% correlated with token position;
   a positional label bug is *exactly* that.
3. **The cause is three lines of shipped code.** `adapters/polymarket.ts:695-696` exposes
   `yesPrice = outcomePrices[0]`, `noPrice = outcomePrices[1]`, and every caller picks
   `outcome === "NO" ? noPrice : yesPrice` (`monitor-trades.ts:171`, `score-trades.ts:446`,
   `update-pnl.ts:220`, `exit-recovery.ts:175`). Any label that is not literally `NO` —
   a team, a player, `UNDER`, `Spread: Burkina Faso (-1.5)` — is priced with the
   **first-listed** token. On a binary market the two prices are complements, so the booked
   entry error is exactly `1 - 2·p_true`: nil at 0.50, ~0.8 at 0.90, ~0.94 at 0.03.

Row-level proof (the card's own examples): `fif-arg-bur-2026-10-03-spread-away-1pt5`, trade on
`ARGENTINA` filled at 0.96–0.97, gate price stored as `0.034` / `0.041` / `0.028` — the Burkina
Faso leg. `atp-bu-djokovi-2026-10-01`, trade on `NOVAK DJOKOVIC` at 0.77, `detectedPrice` 0.225.
The sums are 0.994–1.001, i.e. the two tokens' prices, not one market's movement.

## What the card got right, and the three numbers I have to correct

Right: the marks are real, they are 36–39% of the cohort, they arrive in same-second batches,
and the copied wallet's own fill in the same market is 0.37–0.97 (`wallet fill ≥ 0.05` on
**520 of the 521** rows).

Corrected:

| parent's figure | what it is | correct figure |
|---|---|---|
| 567 rows (39.3%) below the tick floor | that count is on `ObservedTrade.detectedPrice` — the *detection-time* field, which falls back to the wallet's own fill when the monitor's fetch fails | the **gate's own operand** (parsed from the journal) is below the floor on **521 rows (36.1%)**, and all 521 are exactly `0.000000` |
| "479 read exactly 0.000000 … a failed monitor read" | the field is not empty; on a closed market it is the settled price of the token whose slot the caller chose | 319 of the 521 are the **correct** settled price (that token lost); **202 are the sibling's** (that token won) |
| "68% of quotable marks sit ≥5¢ under the wallet's own entry" | a consequence of the same bug plus staleness: error = 1 − 2p | of the 232 cohort rows on a second-listed token, **209 match the sibling token's settled price**; the rest cannot be separated per row |

The parent's `genuine sub-5¢ arm` (wallet also paid < 0.05, 0/16 settled) is defined by the
**wallet's fill**, not by the mark, so it survives this correction — those markets really were
cheap, and they really lost. The `ALL quotable` arm (+$174.68 / $10) is the one built out of
sibling prices, and it was already labelled a measurement defect.

## The defect is not in the tail

The tail is just where it is visible. Position of every scored decision in the window:

| token position | decisions | share | priced correctly today? |
|---|---|---|---|
| YES/NO market | 15,504 | 42.3% | yes |
| first-listed label | 9,833 | 26.8% | yes |
| **second-listed label** | **11,194** | **30.6%** | **no — the sibling's price** |
| no labels resolvable (slug 404 / parlay) | 98 | 0.3% | n/a |

Consequences already in the data:

* **Drift: 10,061 of 21,896 drift rejections (45.9%) ran on a flipped sign.** The gate is
  `adverseDrift = max(0, currentPrice − walletEntry)` (Lane A, 2026-10-26), so on a second-listed
  token a real chase reads as a discount (admitted) and a real discount reads as a chase
  (rejected). This is the single largest behavioural effect of the bug and it is invisible from
  any per-gate report.
* **Book: 65 legs (of 585 admitted decisions in 30d) sit on second-listed tokens**; their
  realized PnL is +$1,290.89 and **6 of the 59 closed/resolved ones disagree with the venue's
  own outcome** — all six are `BANKROLL_200`, five of them `closed` (early exit), which is the
  `update-pnl.ts:220` / `exit-recovery.ts:175` path marking at the complement.
* **Band/sizing:** the same `currentPrice` feeds λ̂ band selection, the band-size rails, the
  high-entry caps and `thesisScore`, so those 11,194 decisions were also banded on the
  complement (the sizing error equals the entry error, `1 − 2p`).

## The card's three options, priced

| option | rows touched / 30d | admissions changed | verdict |
|---|---|---|---|
| **(a) tick-floor guard → "no data"** | 521 relabelled | **0** | rejects as a fix: it calls all 521 "no data", but 319 of them are a *correct* settled price (that token lost) and 202 are a sibling price — the guard cannot tell them apart, and the cause stays |
| **(b) re-fetch before scoring** | 521 | **0** | **provably inert**: all 521 markets were already closed at decision time, the venue's prices are frozen 0/1, and the re-fetch runs the same three lines → the same slot. Costs one extra call per candidate for nothing |
| **(c) leave alone** | — | **0** | **defensible for this clause and only this clause**: the clause is symmetric, so a sub-0.05 mark on a second token is a ≥0.95 market read upside-down and the same clause rejects it from the other end — all **232/232** cohort rows on second tokens stay rejected after repricing. But the operand is still wrong for a third of the book, and drift/sizing/exits read it |
| **(d) label-matched price** (recommended) | 11,194 re-priced | **0 through the near-certainty clause**; drift-sign changes on 10,061 | the only option that reaches the cause; see below |

**So the honest answer to the card's question is: the gate is firing on the right *verdict* for
the wrong *number*, and no guard on the mid fixes it.** The near-certainty clause rejects these
candidates either way — the reason it prints (`price 0.000 near certainty`) is simply false.

## Recommendation — option D, shadow first

Fix the operand, don't guard it: match the trade's own label to the payload's label array.
`normalizeOutcomeLabel()` already exists (`src/lib/resolution.ts:20`) and is already used by the
adapter for resolution; `MarketState` already carries `outcomeLabels` / `outcomePrices`
(`types.ts:79-81`). One helper, four call sites, today's positional slot kept as the fallback
when a payload carries no labels (that is also the revert).

Lane discipline: this changes what the bot decides on 30.6% of decisions, so it ships in two
steps, and step 1 is Lane B:

1. **NOW (shadow, no decision change):** log `priceToday` and `priceLabelMatched` on every
   scored decision, plus the same pair on the exit-marking path. Nothing reads the new field.
2. **Then (Lane A, on the shadow's evidence):** flip the four call sites.

Before/after if step 2 is approved:

| figure | today | after |
|---|---|---|
| decisions priced on the sibling token | 11,194 / 36,629 (30.6%) | 0 |
| near-certainty rejections | 1,983 | 1,983 (invariant — proven) |
| recorded sub-0.05 near-certainty cohort | 1,443 | 1,211 (232 move to the rich side, where they belong) |
| drift rejections whose sign is inverted | 10,061 / 21,896 | 0 |
| book legs entered on a complement price | 65 | 0 going forward |

**Pre-registered gate for step 2** (fixed now, not re-tunable at the read):

* *Hypothesis:* the label-matched price equals the venue's settled price on the token we traded.
* *Measurement:* the shadow's two figures on every decision stamped after its market's
  `closedTime`, 7 days.
* *Decision rule:* flip when the label-matched figure agrees with the venue's settled price on
  ≥99% of post-close decisions over the 7-day window **and** the repriced 30d drift population
  is not worse than today's at the measured fill.
* *Refutation:* if label matching fails on >1% of post-close decisions (punctuation drift,
  re-worded labels), do not flip — add a label normalizer at intake instead. If the repriced
  drift population loses money where today's rejects, keep the bug and card the drift rule.

Until step 2 is approved, nothing in the trade path changes and the near-certainty clause keeps
producing the right verdicts with a false number in the reason string.

## Instrument

`scripts/nearcert-mark-guard-read.py` — read-only on `prisma/dev.db`, one artifact
(`data/nearcert-mark-guard-read.json`) plus a label cache (`data/nearcert-market-meta.json`,
4,004 markets, 0 fetch errors). It fetches gamma `/markets/slug/<slug>` per market to get
`outcomes` / `outcomePrices` / `closedTime`, classifies every decision by token position, and
scores each mark against the venue's own settled prices. Only decisions stamped after
`closedTime` are used for the consistency test.

Run: `python3 scripts/nearcert-mark-guard-read.py --days 30` (≈6 min cold, instant warm).

Nothing was committed and nothing in the trade path was touched.
