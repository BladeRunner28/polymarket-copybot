# Kalshi × Polymarket — does an equivalent CONTRACT settle the same way?

**Card:** `kalshi-pair-settlement-rule-check` · **Run:** 2026-11-23 20:00 CST (read 2026-11-24T02:05Z) · **Lane B (read-only)**
**Instrument:** `python3 scripts/kalshi-pair-settlement-read.py` (`npm run kalshi:pair-settlement`, `--self-test` 25/25)
**Artifact:** `data/kalshi-pair-settlement.json`

## The answer

**PASS — 37 of 37 settled pairs agree.** The card's pre-registered gate (≥19 of the first 20)
scores 20 with **0 disagreements**. No pair settled differently on the two venues, so the
ontology-complete set really is a pair set and not just a name match.

The test is not a tautology. Every row's agreement is checked against **two independent venue
records**, and the population is deliberately two-sided:

- our side is the Kalshi **YES** side on 19 pairs and the **NO** side on 18;
- Kalshi returned `no` on 24 and `yes` on 13;
- Polymarket's winner flag was `true` on 17 and `false` on 20.

A systematic side error would have produced roughly half the rows disagreeing. It produced zero.

## Basis (travels with every number)

| field | value |
|---|---|
| population | every `detVerdict == EQUIV` leg in `data/kalshi-venue-shadow.jsonl`: **37 legs, 36 distinct markets/tickers** |
| level | one ledger leg (`marketId｜outcome｜detTicker`), deduped |
| clock | `openedAt` 2026-11-16 → 2026-11-23; 6 game-days, largest slate 18 pairs |
| class mix | 20 SPREAD · 9 TOTAL · 8 MONEYLINE |
| Kalshi truth | `GET /trade-api/v2/markets/<detTicker>` → `result` (36/36 `finalized`, 0 void) |
| PM truth | `clob.polymarket.com/markets/<conditionId>` → `tokens[].winner` (keyless, conditionId joined from `ObservedTrade`) |

Concentration: max **2 legs on one market** (UFC Cannonier/Aliskerov, one per fighter), 18 of 36
on 2026-11-21 — a slate, not a single game.

## Two defects found while building the read (both fixed, both pinned)

**1. `side_yes` answered YES for every spread trade.** It read our side off the question's
spread id tail (`spread_index`), which is *the market's own* spread team — identical to the
Kalshi contract subject on every verified pair by construction. So 12 spread pairs plus 1
moneyline were stamped `detOurSideIsYes = true` while we actually held the **opponent**.
Measured: **13 of 37** stored side flags wrong. Had the audit trusted that column, 13 rows
would have been reported as settlement disagreements that do not exist.

The rule now takes the index of **our own outcome**, in whichever vocabulary it is written
(slug code / Kalshi city / venue label), and abstains when it cannot place the side. A
self-test arm keeps the retired rule present and asserts it returns YES on the fixture the
live rule calls NO.

**2. The ledger's `won` is an exit sign, not a settlement.** `won = realizedPnl > 0`. On this
population **12 of 37 legs** read differently from Polymarket's settlement (all 12: booked a
loss, settled a win — early exits). The audit therefore prices both venues' own settlement
and never reads `won`. This is not a new discovery, but it is the reason the card was
unreadable as written: "read `detRules` once 20 priced pairs settle" had no settlement column
to read.

## Reality checks that could have killed it

- **Rules drift:** `rules_primary` is byte-identical between our decision-time stamp and the
  venue's current text on **37 of 37** pairs, so the agreement is not "the rules changed and
  both venues happened to move".
- **Void / fair-price rows:** none. 36/36 Kalshi markets are `finalized` with a definite
  `result`, and every PM market is closed with an explicit winner flag. No row was excluded.
- **PM token join:** every outcome label resolved to a token by exact name (case-insensitive);
  zero needed the fuzzy bridge, so the agreement does not rest on a nickname heuristic.

## What this does and does not license

It satisfies the one precondition the card set: *"Do not size anything against the
cross-venue lane before this passes."* It does **not** authorise sizing, and nothing about
rules, size, thresholds or gates was changed. Sizing the cross-venue lane is a separate Lane A
decision with its own proposal.

## Re-open condition

Re-run when the ledger accumulates another 20 settled pairs, or immediately on any settlement
dispute (postponement, overtime, stat correction). The read is one command and idempotent.

## Rollback

`git revert` of this commit. It adds one read-only script, one artifact and one draft, edits
`side_yes` in `kalshi-contract-equivalence.py` (plus 6 self-test arms), and adds one npm
script. No RuleSet version, no sizing input, no live decision path.
