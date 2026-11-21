# Kalshi cross-venue lane: 0% is refuted — the gap is NAMING, not an LLM

**Read:** 2026-11-21T15:13Z · **Window:** 7d (2026-11-14 → 21) · **Population:** C-200 acted
markets (isDemo=0), level = market, stake = Σ simulatedPositionSize · **Instrument:**
`scripts/kalshi-contract-equivalence.py --days 7` (26 self-test arms, artifact
`data/kalshi-contract-equivalence.json`).

## The card's premise, re-tested

The 2026-09-18 read said *"verified cross-listings = 0 (0%), the binding constraint is
contract ontology, park the lane"*. That was measured on a September book (elections and
politics). Two months later the book is sports, and against a **complete** open-event
index (22,782 events, cursor exhausted, 2026-11-21T15:02Z) the answer is not zero.

## Result — 12 verified contract-equivalent pairs, 9.0% of stake

| class | markets | stake | share of book |
|---|---|---|---|
| MONEYLINE | 24 | $386.01 | 19.7% |
| SPREAD | 19 | $223.94 | 11.4% |
| TOTAL | 18 | $217.60 | 11.1% |
| OTHER (barriers, series maps, no-opponent) | 54 | $1,134.13 | 57.8% |

| verdict | markets | stake | share |
|---|---|---|---|
| **EQUIV** (event + class + strike verified) | **12** | **$177.41** | **9.0%** |
| DIFFERENT_CONTRACT (same game, no such strike) | 1 | $9.92 | 0.5% |
| NO_EVENT_MATCH — naming unverified | 37 | $521.36 | 26.6% |
| NO_EVENT_MATCH — sport unmapped | 11 | $118.86 | 6.1% |
| OTHER_CLASS | 54 | $1,134.13 | 57.8% |

Concentration is not carrying it: median pair $13.95, top pair 11.3% of the equivalent
stake, trim-5 mean $18.26. Every pair prints the exact Kalshi contract it matched, e.g.

- `Spread: LSU (-14.5)` → `KXNCAAFSPREAD-26NOV21LSUTENN` "LSU wins by over 14.5 points"
- `UCLA vs. Michigan: O/U 41.5` → `KXNCAAFTOTAL-26NOV21UCLAMICH` "Full Game: Over 41.5 points scored"
- `UFC Fight Night: Jared Cannonier vs. Ikram Aliskerov` → `KXUFCFIGHT-26NOV21CANALI` "Jared Cannonier wins"

## What actually blocks the lane

1. **Strike-level parsing is deterministic, not semantic.** ~40 lines of regex, validated
   by 26 self-test arms (line equality at half-point grids, side assignment, team totals
   vs game totals, quarters vs full game, corners vs goals). No LLM needed.
2. **Naming is the gap.** PM market ids are slugs (`cfb-lsu-tenn-2026-11-21-spread-away-14pt5`,
   `nba-nop-sas-2026-11-21`) — sport + two 3-letter codes + day. Kalshi titles use CITY
   names for pro leagues (`KXNBAGAME`: "Atlanta vs Boston"), so `nop`/`sas` cannot meet
   "New Orleans"/"San Antonio". That bucket is 37 markets / $521 and is an **instrument
   limit**, not a measured absence — it includes football/basketball games that a
   30-row-per-league code→city table would resolve.
3. **Sidecar depth is still wrong but now unreachable**: `MAX_EVENT_PAGES=25` × 200 =
   5,000 events = 21.9% of the inventory, at `MATCH_THRESHOLD 0.55`. Depth was already
   known to be a defect; with the ontology measured it is simply moot, because the correct
   join is (sport, day, team codes, strike) — not fuzzy title scoring.

## Decision asked of the operator (Lane A)

- **(a) change:** build the code→city alias table plus wire the existing parser into the
  shadow lane only (no execution, no sizing, no capital). Effort ≈ 1 day; the parser and
  the gates already exist.
- **(b) basis:** 12 verified pairs / 9.0% of a 7d book measured on 2026-11-21T15:13Z; 42.2%
  of the book is class-bearing; the naming bucket is $521 (26.6%) and unmeasured.
- **(c) decision rule:** fund if a fresh weekly read shows ≥10% of stake verified, or if the
  alias table lifts the current 9.0% by ≥3pp on the same 7d window.
- **(d) refutation:** three consecutive weekly reads below 5% verified stake, or the alias
  table moving the number by <1pp, means the lane is genuinely too thin — park it.
- **(e) rollback:** revert the matcher commit; the shadow lane returns to its current 0
  verified cross-listings and nothing in decisions or sizing depends on it.

## Instrument defects found and fixed while building this (Lane B)

1. A >=1-shared-token subject rule accepted "Georgia" ≈ "Georgia St." and "Kansas" ≈
   "Kansas St."; a State/St. qualifier must now agree on both sides.
2. One shared token accepted "New Mexico" ≈ "New York"; now shared tokens must cover ≥60%
   of the candidate's own tokens.
3. `MAX_EVENT_PAGES` was described as 8×200 in `kalshi-slug-matcher.py` while the sidecar
   had moved to 25×200 — the depth is now read from `adapters.rs` at run time.
4. A season-long market with no date in its ticker won every near-date comparison
   ("LSU Regular Season Wins", "Colorado presidential election winner?"); candidates now
   require a `vs` title and a dated ticker.
5. Quarter/half/team-total event families were being read as full-game contracts.
6. `O/U 11.5 Total Corners` and player props were parsed as game totals.
7. Splitting a title on `:` before ` vs ` made every prefixed title single-sided
   ("Fight Night: A vs B") and silently dropped 6 UFC pairs.
8. Grouping a game's event families collapsed their tickers, so the same game looked
   ambiguous against itself.
