# C-200 taker arm: CLOSED — book-walk taker-fill replay on 477 booked BUY legs

**Card:** `polythought-go-taker-fill` (approved 2026-11-09) · **Type:** Lane B measurement, read-only
· **Instrument:** `scripts/c200-bookwalk-taker.py` · **Artifact:** `data/c200-bookwalk-taker.jsonl`
· Served at `/drafts/polythought-go-taker-fill-20261109`

---

## Verdict

**The pre-registered rule FAILS.**

> VWAP premium <= 2c on >= 50% of joined legs with n >= 150 => open a maker-vs-taker comparison;
> ELSE close the taker arm permanently and record the null.

**47.8% → corrected to 49.1% of 477 joined legs price a taker fill at ≤2c over our booked maker entry**
(bar ≥ 50%, n = 477 ≥ 150). Per the rule as written: **the taker arm is closed and the null recorded.**
No rule, size, gate or booked figure moved — this is a measurement and a recorded decision, not a code change.

| what is compared | n | median premium | share ≤ 2c |
|---|---|---|---|
| taker VWAP vs the **booked maker entry** (the registered basis) | 477 | **+2.37c** | **49.1%** — FAIL |
| taker VWAP vs the **venue mid** at dispatch (pure crossing cost) | 477 | +0.50c | 86.4% |
| taker VWAP vs **intent − 2c** (retired flat convention, HISTORY) | 477 | +2.50c | 13.4% |

Two honest qualifications, both stated before anyone acts on the null:

1. **The miss is 0.9pp on n = 477** (binomial SE ≈ 2.3pp), so on price alone the verdict is
   *"not supported"*, not *"proven expensive"*. The rule as written has no confidence margin, so it
   fires; but a permanent close on 0.9pp would be a coin-flip.
2. **The fee makes the null decisive.** Adding the venue's documented taker fee
   (`rate · p · (1−p)`, per-market category rate from `ObservedTrade.marketCategoryClass`) drops the
   population to **27.0% ≤ 2c**, and the measured-credit era — the only arm that describes the lane
   today — to **45.6%**. Taking does not clear 2c once the trade is actually charged for.

---

## Correction trail — why the first pass read 47.8% / 433

The first run (2026-11-09 10:15, run records 1–2 in the artifact) reported 47.8% on 433 clean legs.
Both figures were mechanically wrong:

- **The defect.** `l2_window()` mapped timestamp → byte offset by linear interpolation between a
  file's first and last `ts`. These files are append-only but written in **bursts** (a market is
  subscribed for hours, then silent for days), so the interpolation lands outside the dispatch window.
  Measured: **43 of the 50 legs reported as `no_snapshot_in_window` had 14–24 two-sided snapshots
  inside `[t0−30s, t0+90s]`**.
- **The fix.** Binary-search the byte offset of the first line with `ts >= t0−30s` (the `ts` field is
  monotone: 0 non-monotonic files across the 50 checked), then stream to `t0+90s`. A second label
  repair: a book with asks but no bids can price a taker BUY but cannot pass the identity check, so it
  is now reported as `one_sided_book` (2 legs) instead of being called "no snapshot".
- **The effect.** 461 → **505 joined**, 433 → **477 clean**, 47.8% → **49.1%**. The 44 recovered legs
  are not a random sample — they are exactly the markets whose token files have bursty write
  patterns — which is why the corrected share moved by 1.3pp and the population by 10%.

The artifact is append-only and every run record now carries `"l2_seek": "binary_search_ts_v2"`. Only
v2 records are quoted in this write-up; the v1 records are kept as history, not as evidence.

---

## Method

- **Population.** `FillIntent` (botId = BANKROLL_200, side = BUY) **JOIN** `PaperTrade` — 515 booked
  legs, 2026-09-26 → 2026-11-09. 717 BUY intents exist; 202 never produced a `PaperTrade` row (gated
  or unfilled), so they have no "assumed fill" for a premium to be measured against.
- **Book.** `data/l2/<tokenId>.jsonl` (top-25 ladder, 5 s cadence). The snapshot used is the one
  **nearest** the dispatch inside `[-30 s, +90 s]`; median signed lag **+12.8 s** (p10 +3.1, p90 +21.0)
  — the recorder's pin lag, so a taker fill is priced against the book a few seconds *after* the
  intent. Every row carries its lag; arm D re-cuts at |lag| ≤ 15 s.
- **Fill.** `shares = simulatedPositionSize / entryPrice` — the lane risks **dollars**, so a fixed clip
  buys fewer shares at a worse price. Asks are walked ascending until the clip is filled. **Depth never
  bound**: 477/477 legs filled completely inside the top-25 ladder, so book-walk VWAP = best ask here,
  and the ladder matters only through the spread.
- **Premium.** `vwap_ask − booked entryPrice`, in cents — the number the rule is written on. Also
  reported vs `intentPrice` (the detection mid we were handed) and vs `intent − 0.02` (retired
  convention, labelled HISTORY).
- **Era classification is by the credit actually booked**, not the calendar: the sidecar books
  `entry = max(0.01, intent − credit)`, the credit was a flat 2c until 2026-10-09 and the measured
  per-band share since 2026-10-10 (max 0.458c), so `intent − entry ≥ 1.99c` uniquely identifies the
  retired flat-2c convention. (10 of 2026-10-10's legs still carry 2c; a calendar cut would misclassify
  them.)
- **Token identity — the trap that decides this measurement.** A market has two outcome tokens and the
  sibling's book sits at ~`1 − our price`, so opening the wrong file manufactures a ~+50c "premium".
  Tokens are resolved from the venue's own labels (`CLOB /markets/<conditionId> → tokens[].outcome`,
  cached in `data/c200-token-map.jsonl`), and every leg is sanity-checked by mid proximity; a leg whose
  book sits closer to `1 − intent` than to `intent` is flagged `wrong_side` and **excluded from the
  headline, never averaged in**. The venue-label pick agrees with the pre-existing tape-label pick in
  `data/c200-printthrough.jsonl` on **505 of 505** joined legs (that tape labels every booked intent),
  so the token map is not a second guess at identity — it is the same identity by an independent route.
- **Fee.** The registered metric is price only. A fee arm is reported beside it because a
  maker-vs-taker decision that ignores the taker fee is incomplete: `fee/share = rate · p · (1−p)` with
  the documented per-category rate (`crypto 0.07 · sports 0.05 · politics/finance/tech 0.04 ·
  economics/culture/weather/other 0.05 · geopolitics 0`), carried per leg by
  `ObservedTrade.marketCategoryClass` (100% coverage on these legs: 448 at 0.05, 28 at 0.04, 1 at 0.07).

---

## 1. Population and coverage

| item | value |
|---|---|
| booked C-200 BUY legs (PaperTrade join) | 515 |
| joined to an L2 book at dispatch | 505 |
| wrong-side legs excluded | 28 |
| depth-short legs excluded | 0 |
| clean analysable | 477 |
| skipped: no snapshot anywhere in the window | 7 |
| skipped: one-sided book (asks only, no bids) | 2 |
| skipped: label-miss (no venue label matches the traded outcome) | 1 |

The 9 legs with no usable two-sided book are all in the flat-2c era (7 no snapshot, 2 one-sided), so
coverage does **not** favour the measured-credit arm. The one `label-miss` is a token-identity gap, not
a coverage gap.

## 2. Premium of a taker fill (cents, vs the booked maker entry)

| stat | value |
|---|---|
| mean | +2.11c |
| median | +2.37c |
| p10 | +0.56c |
| p25 | +0.96c |
| p75 | +2.87c |
| p90 | +4.00c |
| share ≤ 2c | **49.1%** |
| share ≤ 1c | 38.0% |
| share ≤ 0 | 7.3% |
| usd-weighted mean | +2.24c |
| share ≤ 2c, usd-weighted | 60.1% |

The rule is **leg-count**, not dollar-weighted. The usd-weighted 60.1% is reported for completeness and
does **not** satisfy the bar — reading it as a pass is the most available way to get this wrong.

## 3. Decomposition — what the premium is made of

| basis compared with | n | median premium | share ≤ 2c |
|---|---|---|---|
| booked maker entry (live convention) | 477 | +2.37c | 49.1% |
| venue mid at dispatch (pure crossing cost) | 477 | +0.50c | 86.4% |
| intent − 2c (retired flat convention, HISTORY) | 477 | +2.50c | 13.4% |

The taker's cost over the **mid** is exactly the measured median half-spread (spread median 1.0c,
mean 1.68c). The rest of the premium over our fill is the **credit we book**, not a taker penalty:
in the measured era the median decomposes as 0.50c half-spread + 0.46c credit = 0.96c. That is why the
same book prices as "cheap" against the mid and "over the bar" against our fill.

## 4. By credit era — the decisive split

| era | n | median premium | mean | share ≤ 2c | rule |
|---|---|---|---|---|---|
| flat-2c (booked ≤ 2026-10-09) | 247 | +2.50c | +2.83c | 16.2% | FAIL |
| measured credit (2026-10-10 →) | 230 | +0.96c | +1.34c | **84.4%** | PASS |

On price alone the live convention passes comfortably; the blended population fails. This is the one
reading that argues against a permanent close — and the fee arm in §7 is what answers it: on the
measured-credit population the share falls to **45.6%** once the trade is charged for, because a 1c
price premium is consumed by a 1.5–1.7c fee at typical prices.

## 5. By price band (clean legs, all eras)

| band | n | median premium | mean | share ≤ 2c |
|---|---|---|---|---|
| 0.00–0.10 | 41 | +2.50c | +3.27c | 42% |
| 0.10–0.20 | 41 | +1.17c | +2.26c | 66% |
| 0.20–0.40 | 178 | +1.14c | +1.67c | 60% |
| 0.40–0.60 | 142 | +2.50c | +2.47c | 28% |
| 0.60–0.80 | 75 | +1.87c | +1.77c | 59% |

0.40–0.60 is where crossing is most expensive at the midpoint, and the sub-0.10 band next (a 2–3c
spread on a 5–10c token is 20–60% of the price). Both are the same finding as §3: the premium is
spread + credit, not a per-band taker penalty.

## 6. Sensitivity arms (one assumption changed at a time)

| arm | n | median | mean | share ≤ 2c |
|---|---|---|---|---|
| A primary (nearest snapshot, shares off entry) | 477 | +2.37c | +2.11c | 49.1% |
| B shares sized off `intentPrice` instead | 477 | +2.37c | +2.09c | 49.1% |
| C first snapshot at/after dispatch | 477 | +2.37c | +2.11c | 49.1% |
| D primary ∧ \|lag\| ≤ 15 s | 287 | +2.50c | +2.09c | 45.6% |

None of the mechanical choices moves the verdict; the era (and the fee) are the only variables that do.

## 7. With the taker fee added (fee/share = rate · p · (1−p))

| fee basis | n | median premium+fee | mean | share ≤ 2c |
|---|---|---|---|---|
| **per-market category rate** (448×0.05, 28×0.04, 1×0.07) | 477 | **+3.16c** | +3.13c | **27.0%** |
| flat 0.04 | 477 | +3.00c | +2.93c | 39.8% |
| flat 0.05 (default) | 477 | +3.18c | +3.14c | 26.6% |
| flat 0.07 (max) | 477 | +3.62c | +3.55c | 14.3% |

| era | n | per-market rate | flat 0.05 | flat 0.07 |
|---|---|---|---|---|
| flat-2c | 247 | 9.7% | 9.3% | 6.5% |
| measured credit | 230 | **45.6%** | 45.2% | 22.6% |

The fee is per-market and only applies where the venue enables it; `marketCategoryClass` carries no
fee-enabled flag, so this is the *documented-rate* upper bound rather than a per-market bill. Fee-free
markets (geopolitics rate 0) are the only subset where the zero-fee numbers apply — none of these 477
legs classifies as geopolitics, so the fee arm covers essentially the whole population.

## 8. Token identity control and the price-side inversion (side finding)

The sibling book is an **independent** check that the token file belongs to the outcome the leg holds:

| check | value |
|---|---|
| clean legs with a sibling book | 477 |
| clean legs whose sibling mid is >5c off `1 − our mid` | **0** |
| wrong-side legs / with a sibling book | 28 / 28 |
| wrong-side legs whose SIBLING mid is within 1c of our intent | 24 |
| wrong-side legs whose SIBLING mid is within 3c of our intent | 26 |
| joined legs also labelled by the print-through tape / agreeing | 505 / 505 |

So the clean population's token identity is airtight, and **26 of the 28 wrong-side legs have a book on
the *other* outcome sitting on our booked price** — the price-side inversion, measured from the venue's
own book rather than from the ledger's labels. 26 of the 28 are in the measured-credit era, i.e. the
inversion is current, not historical. Two examples:

- `atp-wawrink-lehecka-2026-10-27`, outcome **JIRI LEHECKA**, intent 0.175 → Lehecka trades 0.825;
  the sibling Wawrinka book is 0.175.
- `dota2-aur1-1win-2026-10-08-game2`, outcome **AURORA**, intent 0.385 → Aurora trades 0.610;
  the sibling 1win book is 0.390.

Two legs are **inconclusive**, not corroborating, and are named so the claim is not over-read:
`dota2-1win-pari-2026-10-09-game1` (intent 0.335, sibling 0.495 — both books sit near 0.5) and
`atp-michels-fils-2026-10-29` (intent 0.325, sibling 0.415 — a 9c gap, consistent with a market move).
These 28 legs are excluded from the premium statistics because their premium is meaningless, but they
are evidence for card `price-side-inversion`, not noise to throw away.

## 9. What this measurement does NOT say

- **It is a price, not a fill.** A taker always fills; the maker credit we book is a
  probability-weighted claim (measured reach 18–27% by band). The honest cross-arm comparison is
  `cost per filled unit × fill rate`, and this script measures only the first term. The close recorded
  here is a close of the *taker entry direction at this cost*, not a proof that the maker convention is
  sound.
- **Fee scope.** §7 is the documented category schedule, not a per-market bill; markets with
  `feesEnabled = false` would keep the §2 figures. None of these legs classifies as fee-free.
- **Snapshot lag.** The book is read a median +12.8 s after dispatch. Arm D (|lag| ≤ 15 s) is stable,
  but no snapshot equals the exact intent instant; 13.4% of legs even price *below* the mid at
  dispatch, which is market movement inside that lag, not a discount.
- **Top-25 ladder.** Depth beyond 25 levels is not recorded; with $1–13 clips this never bound
  (477/477 full), but a larger clip would need the deeper book.
- **10 legs unjoined** (7 no snapshot, 2 one-sided, 1 label-miss) are reported, not imputed.

## 10. Decision, and the one override flag

- **Executed (this card's rule):** taker arm **CLOSED**, null recorded — the roadmap card moves to
  Done carrying the verdict, and no code, rule, size or published figure changes.
- **Reopen path, if anyone wants it:** a *new* pre-registration on the measured-credit population with
  a **fee-inclusive** metric (`vwap_ask + fee − entry ≤ 2c`) and n ≥ 150. That is a different test from
  the one registered here and must be registered as such, not read as a reversal of this null.

**Override flag (one line, if you disagree with the close):** say **"re-register"** and I open the
fee-inclusive measured-era test as a new card. The number that would move: measured-era share at
per-market fee = **45.6%** (vs 84.4% price-only), n = 230.

## Reproduce

```bash
cd ~/polymarket-copybot
python3 scripts/c200-bookwalk-taker.py               # summary to stdout
python3 scripts/c200-bookwalk-taker.py --json        # machine-readable summary
python3 scripts/c200-bookwalk-taker.py --md <file>   # regenerate the tables above
python3 scripts/c200-bookwalk-taker.py --offline     # cached token map, no CLOB fetches
```

Artifact: `data/c200-bookwalk-taker.jsonl` — one run record carrying the summary **and every per-leg
row** (intent, booked entry, lag, spread, VWAP, premium vs each basis, fee rate, depth flag,
wrong-side flag, sibling mid). Token cache: `data/c200-token-map.jsonl` (venue labels; delete to
re-fetch from CLOB). Prior run records (no `l2_seek` field, or `l2_seek` absent) are the v1 seek and
are superseded.
