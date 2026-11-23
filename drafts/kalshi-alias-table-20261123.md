# Kalshi cross-venue lane: the alias table is built, wired, and measured

**Card:** `kalshi-lane-ontology-not-coverage` — option **(a)**[^1] approved 2026-11-23T13:22Z via the
approvals inbox (`apr-kalshi-lane-ontology-not-coverage`). **Nothing here changes what the bot
decides, how much it risks, or any live number.**

[^1]: The card's lettered option set is (a)–(e); the approved one is **(a)**: *fund the alias half
only — a code→city table per league + wire the shipped parser into the shadow lane, no execution,
no sizing, no capital.*

---

## 1. What shipped

| artefact | what it is |
|---|---|
| `scripts/kalshi-team-aliases.py` (new) | derives the code→name table **from the venue**, and `--check` refuses a table where two distinct clubs share an alias |
| `data/kalshi-team-aliases.json` (new) | 167 Polymarket slug codes → the names Kalshi actually renders, across NBA / NFL / NHL / MLB / EPL |
| `scripts/kalshi-contract-equivalence.py` (extended) | alias layer + slug-side attribution + **closed-event pool** + `--as-of`, `--no-alias`, `--pool`, `--resolve`; self-test 39 arms |
| `scripts/kalshi-venue-shadow.ts` (extended) | the shadow lane now books a **deterministic arm** alongside the fuzzy one (own fields, own summary block) |
| `data/kalshi-contract-equivalence.json` | regenerated at the current clock |

### Why the table is derived, not typed

The card's proposal says "a code→city table per league (~30 rows each)". Typing 167 rows from memory
is unverifiable, so the table is a **transcription of the venue**: every Kalshi event carries its own
codes in `sub_title` (`"BOS vs GSW (Nov 22)"`) beside the title it renders (`"Boston vs Golden
State"`). `--derive` walks 90 days of settled events plus the open book per league, aligns the two
fields, and writes the name the venue used most often for each code. Only the *code map* is authored
(`gs`/`gsw`→`GSW`, `mac`→`MCI`, `che`→`CFC`, …).

```
nba   37 codes,  37 forms,  30 distinct names
nfl   35 codes,  71 forms,  65 distinct names
nhl   38 codes,  38 forms,  32 distinct names
mlb   34 codes,  36 forms,  32 distinct names
epl   23 codes,  24 forms,  21 distinct names
alias check: PASS (0 collision(s))
```

### The one property that matters: an alias must discriminate

`--check` fails the build if two **distinct venue codes** resolve to the same string inside a league.
That is what keeps `lal`/`lac` (`Los Angeles L` / `Los Angeles C`), `nyg`/`nyj`
(`New York G` / `New York J`), `nyr`/`nyi` and Manchester City/United apart — the exact collapses a
shared-token matcher makes. The derivation also **drops** any form the venue uses for more than one
club: NFL renders both New York franchises as plain `"New York"` in some events, so that form is
excluded by rule (1 ambiguous form dropped), not by luck.

---

## 2. Measurement

Same population as the 2026-11-21 read (C-200 acted, `isDemo=0`, `openedAt` 2026-11-14..21, level =
market, stake = Σ `simulatedPositionSize`, 115 markets / $1,961.68) and the **same pinned clock**
(`--as-of 2026-11-21T15:13Z`), so every arm below is the same book.

| arm | event pool | pairs | stake of the book |
|---|---|---|---|
| **A** as committed 2026-11-21 (pre-change code) | open index snapshot | 12 | $177.41 — **9.0%** |
| **B** new code, alias table OFF (`--no-alias`) | open index snapshot | 13 | $187.33 — **9.6%** |
| **C** new code + alias table | open index snapshot | 15 | $297.25 — **15.2%** |
| **D** new code + alias table | open index **+ closed events in the window** (61,499 events, cursor EXHAUSTED) | 33 | $516.91 — **26.4%** |
| **E** fresh 7d read, current clock 2026-11-23T13:46Z | open (50,491 closed, cursor EXHAUSTED) | 44 | $650.44 of $2,619.84 — **24.8%** |

**The alias table's own lift is C − B = +5.6pp** (and +6.2pp against the committed 9.0%), measured on
a pool that is identical between the two arms. Every other column moves for a different, named reason:
B over A is the slug-side attribution (a moneyline whose contract names the city no longer needs the
nickname to match), D over C is the closed-event pool, and E is simply the current book.

`spread side cross-check: agree=10, undetermined=14, disagree=0` — the `home`/`away` encoding in our
market ids agrees with the team named in our own spread question in every case where both are
determinable, which is what licenses reading the side off the id.

### What is still naming-blocked, and why that is now honest

The remaining `NO_EVENT_MATCH` stake is **college** (`cfb`/`cbb`/`cwbb`) and the smaller soccer
leagues, whose slug codes are contractions (`vtech`, `washst`, `bih`) rather than the venue's own
codes. In the fresh read that is 42 markets / $510.87 (19.5% of the book), of which $451.25 is
`naming-unverified` and $59.62 `sport-unmapped` (`unl`/`fr2`/`afcq` — Nations League matches are
found by the text path, so they are resolved; the rest are genuinely unmapped families).

---

## 3. Instrument defects found while executing this (all repaired, all armed)

1. **The event pool could not see a settled game.** `data/kalshi-event-index.json` is a snapshot of
   events that were OPEN when it was built, so a trailing 7d read asked "does a counterpart exist?"
   against a pool that had already deleted the counterparts. The `window_pool()` walk of
   `status=settled` events fixes it; the log now prints `cursor EXHAUSTED` or
   `TRUNCATED (raise --pool-pages)` because a truncated walk silently hides a slice of the window.
2. **One game under two titles looked ambiguous against itself.** `"Liverpool vs Manchester United:
   Total Goals"` and `"Liverpool FC vs Manchester United: Correct Score"` are the same fixture; the
   candidate key now uses the matchup's identity tokens (`matchup_key`), so a fixture is one
   candidate with all its families. Two rows moved from AMBIGUOUS to EQUIV after the fix.
3. **A club's city matched the OPPONENT.** `"RCD Espanyol de Barcelona"` matched a Kalshi side
   named `"Barcelona"` (a different club) at 100% of the candidate's tokens and fabricated a La Liga
   "equivalent" 2.4 days from our trade. `subject_match` now requires a one-token candidate to be
   our team's **head** token — and the text path's day window tightened from 10 days to 1.
4. **The venue's `*_dollars` fields are strings.** A float-only parser read a live book as "no
   quote"; `market_quote` now accepts `"0.2700"` and legacy cents.
5. **A settled market still quotes 0/1.** The resolver now refuses to emit a price unless the
   ticker is `active`/`open` and `0 < price < 1`, with the reason recorded (`not_tradeable:finalized`).
6. **A two-sided game lists one market per team, and both are "equivalent" to a moneyline.**
   Taking the first match booked the wrong side of our own trade; the resolver now prefers the
   market whose side IS ours (`side_yes`), and refuses to price when it cannot tell.

---

## 4. The shadow-lane wiring (observation only)

`scripts/kalshi-venue-shadow.ts` now runs the resolver once per tick over the newest 60 unresolved
rows (`KALSHI_DET_BATCH`, `KALSHI_DET_ARM=0` disables) and writes its own fields —
`detVerdict`, `detTicker`, `detTitle`, `detEntry`, `detOurSideIsYes`, `detRules`, `detNote` — plus a
`deterministic` block in `data/kalshi-venue-shadow-summary.json`. It **never** writes `pmPnl`,
`kalshiPnl` or `delta`, so every published venue-shadow number is untouched:

```
books (settled pairs only): PM $+29.27 (n=2) | Kalshi $+0.17 (n=2) | delta $-29.10   <- unchanged
det arm (contract equivalence): resolved=60 equiv=12 priced=1 | book n=0 PM $+0.00 vs DET $+0.00
  det verdicts: {"OTHER_CLASS": 18, "NO_EVENT_MATCH": 28, "EQUIV": 12, "AMBIGUOUS_EVENT": 2}
```

The resolver is the **same code** the measurement uses, so a pair the report counts is a pair the
lane can price; `detRules` stores the venue's `rules_primary` per pair, which is what the card's
settlement-rule refutation condition needs.

---

## 5. Decision rule

- **(c) fund condition:** *fresh read ≥10% of stake verified, **or** alias table lifts 9.0% by
  ≥3pp on the same window.* → **BOTH CLAUSES MET.** Alias lift **+5.6pp** (9.6% → 15.2%) on an
  identical pool; fresh 7d read at the current clock **24.8%** ($650.44 of $2,619.84, 44 pairs).
- **(d) refutation:** three consecutive weekly reads below 5%; the alias table moving the number by
  <1pp; or verified pairs failing a settlement-rule comparison on the first 20 that settle.
  The first two are **not** met (5.6pp ≫ 1pp). The third is now instrumented (`detRules`) but needs
  settled pairs that had a live quote — none yet; it is carded as `kalshi-pair-settlement-rule-check`
  and **no sizing decision may be taken on this lane before it passes**.
- **(e) rollback:** below.

---

## 6. Named next steps (not done here)

1. **College tables** (`cfb`, `cbb`, `cwbb`): the remaining naming bucket. Their slug codes are
   contractions of school names, so they need a school table derived the same way (`KXNCAAFGAME`
   `sub_title` carries the venue's own codes) plus a contraction rule. This is where most of the
   residual $291–440 sits.
2. **Settlement-rule comparison** on the first 20 pairs that settle with `detRules` captured: the
   venue's `rules_primary` vs our resolution. Card's own refutation clause; do it before any sizing
   question is asked.

---

## 7. Revert

```bash
git revert <this commit>          # alias table, resolver, shadow arm, card note
rm data/kalshi-team-aliases.json  # if you revert by hand instead
```
The lane returns to the 2026-11-21 state: 12 verified pairs / 9.0% of a 7d book, no shadow-lane
deterministic arm, and no new number on any dashboard.
