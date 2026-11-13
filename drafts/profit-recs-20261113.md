# Profit review 2026-11-13 — 96% of the book's best lane never traded at our price

http://localhost:3013/drafts/profit-recs-20261113

**Instrument:** `scripts/profit-fill-tape.py` (new, read-only, self-tests **6/6**, committed with this
file). It imports `scripts/profit-postfix-integrity.py` for the leg loader and the CI so the basis is
identical to the rest of the review. Run:

```
python3 scripts/profit-fill-tape.py --since=2026-09-01
```

Cost basis everywhere: `simulatedPositionSize` = **dollars at risk**, deduped to the first leg per
`bot|wallet|market|outcome`, price = the price we booked (INVERTED legs repriced to the wallet's fill),
CIs market-clustered (2,000 draws). Population: **2,274 finished non-demo legs, $32,065 at risk,
opened 1 Sep – 13 Nov 2026**. Raw HTTP is cached under `data/fill-tape-cache/`; no prisma write, no
RuleSet read or write, no rule edit, no `fillStatus` stamped.

---

## 0. What is new today, in one line

Yesterday's brief said the fill question could never be adjudicated because the print-through artifact
is a rolling window. **That was wrong.** `clob.polymarket.com/prices-history` serves the venue's own
minute-level tape for any token, keyless, retroactively. Every one of the 2,274 legs got a verdict
(100% coverage), and the answer is not the one I was arguing for yesterday:

- **C-200 since 1 Sep: booked +$5,922 (+29.6%). 236 legs carrying +$5,710 — 96% of it — never
  printed within 1c of our bid in a full 24 hours.** Restated: **+1.1%**.
- **STANDARD: booked +3.4%, and it survives every check I can throw at it** — 90% fill rate,
  +3.4% at the dispatch price, +2.5% with only the never-class voided.
- The lane with the big number is 85% of post-flip notional and is the one whose number does not exist.

That is the trade I would make today: **stop buying C-200's discount and start charging STANDARD for
its fills.**

---

## 1. Can the tape speak, and can I trust it

Coverage is total — no `no_market`, no `no_tape`, 2 legs needed a price-proximity token map (both
resolved; §6a shows touch rate 50.6% on label-mapped vs 100% on 2 proximity legs, so the map is not
doing the talking).

| lane | legs | filled ≤60m | near miss | untouched ≤60m |
|---|---|---|---|---|
| BANKROLL_200 | 1,568 | 515 (33%) | 340 (22%) | 713 (45%) |
| STANDARD | 706 | 636 (90%) | 44 (6%) | 26 (4%) |

Sanity check against the only labels that exist — the 570 C-200 legs the resolver already stamped:

| | tape touch | tape no-touch |
|---|---|---|
| resolver `filled` | 155 | 3 |
| resolver `unfilled` | 76 | 174 |

(near-miss rows — 31 and 131 — are excluded from both columns.)

Two-sided agreement **80.6%**; 82.0% of resolver-`filled` legs touch, 19.9% of resolver-`unfilled` do.
The tape is measuring the same object. The horizon sweep (60s → 3600s, §1) shows agreement rising
monotonically, i.e. the 1-minute series misses brief dips and the tape's touch is a **lower** bound on
fill probability — every number below leans in the direction that is unfavourable to my own claim.

## 2. I ran yesterday's own refutation condition and it came within 2.5pp of refuting me

Yesterday's card says: *if ≥70% of the 79 unresolved post-flip C-200 legs printed at or below our bid,
they were real positions and the −46.7% proven-fill record is a selected minority — withdraw.*

- Unresolved legs now: **83, $2,734**. Tape adjudicates **83/83 (100%)**.
- **67.5% touched** within 60m. Below the 70% bar, so the condition is *not* met — but it is 67.5%,
  not the 0% I implicitly assumed when I called the class undecidable.
- The 56 that newly resolve as filled read **+$201.3 (+8.8%), CI [−39.7,+77.3]** — no evidence for the
  +17.9% I was arguing about, and no evidence against it either.

**And the load-bearing number from yesterday does not reproduce.** At 515 tape-filled C-200 legs since
1 Sep the lane reads **−7.7% (CI [−29.3,+17.6])**, not −46.7%. The −46.7% was a 60-leg sample, and I
quote it here only to retract it: the direction survives, the magnitude does not. Same for the claim
that the unresolved class is unmeasurable — the artifact is a rolling window, the venue's tape is not.

## 3. The class that actually decides the lane

I had the wrong object. It is not the 83 unresolved legs; it is the 713 legs the market never brought
to our price inside the hour — and, once I extended the horizon to 24 hours to give the "they filled
later" objection a fair hearing, the picture sharpens rather than blurs:

| fill lag (n=739 untouched ≤60m) | legs | share |
|---|---|---|
| 1–6h | 205 | 28% |
| 6–24h | 290 | 39% |
| **never within 24h** | **244** | **33%** |

The no-cancel paper model means a bid that fills at hour 7 is a real position, so only the 24h-never
class is voidable. It is small in count and enormous in PnL:

| lane | booked ROI | never-24h legs | never-24h $ | never-24h PnL | restated ROI | late-fill ROI |
|---|---|---|---|---|---|---|
| BANKROLL_200 | **+29.6%** | 236 | $3,321 | **+$5,709.8** | **+1.1%** | +24.2% |
| STANDARD | +3.4% | 8 | $150 | +$105.6 | **+2.5%** | +44.1% |

**236 legs — 15% of the lane's legs, 17% of its notional — carry 96% of its booked profit, on prices
the market never showed for a day.** The booked +88.4% ROI on the untouched class (CI [+33.6,+151.7],
the only CI-excluding-zero *positive* class in the book) is arithmetic, not a position: at 6–15c a 2c
discount is a 15–33% mark-up, and the lane books that mark-up on legs it never bought.

Negative claims need high-resolution evidence, so I re-checked the never-class at **1-minute fidelity**:
6 of 80 touch (7.5% reverse rate). Haircut accordingly, the phantom is ≈226 legs / ≈$5,280 — still
~89% of the lane's profit.

Where it survives in the ledger (§6d): **562 rows with `fillStatus IS NULL` and no tape touch inside
60m carry +$5,765.4 booked** — that is the live hole, because the flip only zeroes rows it explicitly
stamps `unfilled`. (A further 174 rows the resolver already stamped `unfilled` still carry +$1,063
booked, which the flip's contract says should be zero; the DB split is 194 pre-flip rows / +$796.56 —
era residue, booked before the flip existed — and **one post-flip row / +$27.57**, which I could not
explain in the time available. Reporting it as a loose end, not claiming it as a finding.)

## 4. The cost basis: half of C-200's edge is the price we wrote down

Every leg re-priced at the price the tape showed at dispatch (`p0` — the first price any taker could
have hit), same exit, same dollars at risk:

| lane | booked ROI | ROI @ dispatch price | CI95 @ p0 |
|---|---|---|---|
| BANKROLL_200 | +29.6% | **+15.0%** | [−4.0,+35.6] |
| STANDARD | +3.4% | **+3.4%** | [−8.2,+16.4] |

C-200 loses half its edge to the writing-down of the entry (median booked price −2.00c under the
dispatch market; 67% of its legs more than 1c under). STANDARD is basis-invariant (median 0.00c).
A number that changes by 15pp when you change what "entry price" means is not an edge; it is an
assumption.

## 5. Fillability — where the volume is vs where the fills are

| band | lane | legs | touch ≤60m | ROI booked | ROI touched | CI95 touched |
|---|---|---|---|---|---|---|
| 0.0–0.2 | C-200 | 251 | **37.1%** | +51.4% | **−17.5%** | [−59.2,+37.6] |
| 0.0–0.2 | STANDARD | 81 | **93.8%** | +45.6% | **+54.9%** | [−23.9,+151.3] |
| 0.4–0.6 | C-200 | 492 | 26.0% | +3.1% | −4.7% | [−21.6,+12.9] |
| 0.4–0.6 | STANDARD | 237 | 87.8% | −9.1% | −6.1% | [−21.8,+10.3] |
| 0.8–1.0 | C-200 | 32 | 62.5% | +7.7% | **+8.2%** | **[+3.7,+12.7]** |

Same band, same wallet universe: the cheap tail fills 94% of the time on STANDARD and earns +54.9% on
what it gets; it fills 37% of the time on C-200 and what it gets loses 17.5%. The single CI-positive
fill-restricted cell in the whole book is C-200 0.8–1.0 at **20 legs** — too few to act on, and I am
not going to build a favourite-band proposal on it.

## 6. Why C-200 fills a third as often — and why "pay up" is still not the fix

Measured against the market at dispatch, not the wallet's fill:

| lane | mean d | median d | share bidding >1c under | touch ≤60m |
|---|---|---|---|---|
| BANKROLL_200 | −1.46c | **−2.00c** | 67.3% | 33% |
| STANDARD | −0.13c | 0.00c | 9.8% | 90% |

Then the cell that decides what to do — filled legs only, ROI re-priced at `p0` so the discount cannot
flatter it:

| lane | d bucket | filled n | filled $ | ROI @ p0 | CI95 (booked) |
|---|---|---|---|---|---|
| C-200 | d ≤ −2c | 123 | $946 | −2.2% | [−37.9,+93.2] |
| C-200 | −2c < d ≤ −0.5c | 78 | $1,076 | **+17.4%** | [−56.6,+139.3] |
| C-200 | \|d\| < 0.5c | 193 | $4,822 | **−7.6%** | [−31.7,+24.2] |
| C-200 | d ≥ +0.5c | 121 | $1,571 | **−40.1%** | **[−67.9,−7.9]** |
| STANDARD | \|d\| < 0.5c | 474 | $7,941 | **+9.1%** | [−6.4,+27.2] |
| STANDARD | d ≥ +0.5c | 109 | $1,948 | −6.0% | [−28.5,+10.8] |

Two readings, and the second is the one that pays:

1. **Fill rate and edge trade off exactly as the payoff asymmetry predicts** — the deeper we bid, the
   less we fill and the better each fill is; the more aggressively we bid, the more we fill and the
   worse each fill is. C-200 sits at 33% fill / −7.6% on the bulk of its fills.
2. **The one cell that is both statistically significant and losing is entries where our booked price
   is at or above the dispatch market: 121 legs, −40.1%, CI [−67.9,−7.9], −$677.** Add the at-market
   cell and 314 of C-200's 515 fills — $6,393 of filled notional — run **≈ −$1,000** while its deep
   cells (201 fills, $2,022) run **+$166**. These are not pre-flip ghosts: 161 of those 314 fills are
   post-flip, $4,601 of the $6,393. When the wallet's fill is already above the market at our
   dispatch, the market keeps going — the wallet was early and we are copying the wrong side of it.

That is not gate tuning: the drift gate measures the move since the *wallet's* entry and its default
tolerance is 8c; this is the sign of the move at *our* dispatch and the lossless tolerance is 0.5c.
It is also not "pay up for fills" (measured dead yesterday: −2.3% at the wallet's own price) — it is
the opposite, **don't pay above the market you are copying into**.

---

## 7. What I am not re-litigating

- **Gate tuning** stays exhausted; nothing here proposes a gate change. §6 is an entry-price rule, and
  I say explicitly that it overlaps the drift gate's neighbourhood.
- **Exit alpha / 0.2–0.4 at 168h** stays closed at 107 settled legs (150-leg gate).
- **The pending clip cap** keeps its drawdown case and has already lost its edge case; nothing changes.
- **The Ladder read** was already measured on the card `profit-fill-class-basis`: all three credit arms
  fail and the basis change moves no advance today. I did not re-derive it and I am not re-proposing it.

---

# Recommendations

Ranked by expected value. Both that change what the bot risks or books are **Lane A — propose only,
nothing applied.**

### 1. Book and quote the lanes on the reachable basis (Lane A, 1h)

- **Hypothesis:** C-200's published +29.6% is 96% composed of legs whose price never came within 1c of
  our bid in 24 hours, so the lane's real record is its reachable cohort, which is ≈ +1%.
- **Measurement:** §3 of `scripts/profit-fill-tape.py` — 244 never-24h legs, $3,471, +$5,815.4 booked
  (236 of them C-200: $3,321, +$5,709.8). 60m restatement (§3): C-200 −4.2%. Ledger location (§6d):
  562 `NULL` rows carrying +$5,765.4. Validation §1: 80.6% agreement with the resolver's stamps.
- **Decision rule:** `bookedPnl` voids any leg whose token printed no price at or below our entry
  inside 24h (5-min fidelity), for legs with no resolver stamp; the ROI reader and the daily report
  quote the reachable-only figure; the ladder may not credit the voided class.
- **Refutation:** if a **1-minute-fidelity** re-check of the full 236 shows **≥20%** touch, the class is
  a sampling artifact and I withdraw. (Measured on a sample of 80: **7.5%**.)
- **Expected effect:** $0 paper today; it removes **≈$5,400** of phantom from the book's headline and
  from any 7-day window the ladder is scored on. At the 2027 anchor this is the difference between
  scaling a lane that earns 1% and believing it earns 30%.
- **Cost:** 1h (one filter in the ROI reader + the report line). No RuleSet touch.

### 2. C-200 stops dispatching into a market that has already undercut the wallet (Lane A, 2h)

- **Hypothesis:** C-200 entries whose booked price is at or above the dispatch market lose money and
  are 61% of the lane's fills, so suppressing them raises the lane's fill-restricted expectancy from
  −7.7% to positive.
- **Measurement:** §9 (b) — d ≥ +0.5c: 121 fills, $1,571, **−40.1%, CI [−67.9,−7.9]**; at-market:
  193 fills, $4,822, −7.6%. Together $6,393 of fills ≈ −$1,000, against +$166 on the $2,022 of deep
  fills. 161 of the 314 losing fills are post-flip.
- **Decision rule:** at dispatch, if the current market price is **above** our intended entry by
  ≥ 0.5c, do not dispatch (paper: record the intent, book zero). Keep the deep bids unchanged.
- **Refutation:** a forward **100-leg** cohort of C-200 entries at/above the dispatch price prints
  **non-negative** ROI → restore them. (Separately: if the currently-unpriced at-market cell is
  confirmed non-negative at 150 legs, narrow the rule to the ≥+0.5c cell only.)
- **Expected effect:** **≈ +$1,000 per 74 days** at current sizes (≈ −$1,000 → +$166 on the retained
  fills), and it removes the book's only CI-significant loss cell. This is the recommendation I would
  defend hardest.
- **Cost:** 2h (dispatch-time price check on the C-200 path + a shadow counter).

### 3. Give STANDARD's 0–0.2 band the notional, cap C-200 at its pre-flip clip (Lane A, 1h to amend)

- **Hypothesis:** the only cell in the book that is simultaneously fillable and positive is
  STANDARD's cheap tail (93.8% fill, +54.9% on what it gets), while the equivalent C-200 cell fills 37%
  and loses 17.5% — so the 85/15 notional split is inverted relative to the evidence.
- **Measurement:** §5 band table; §9 basis table (STANDARD basis-invariant at +3.4%, C-200 +29.6% →
  +15.0%).
- **Decision rule:** C-200 clip back to its pre-flip $8–10 average and no increase while its
  reachable-only record is non-positive; STANDARD's 0–0.2 clip may rise within the existing exposure
  cap. Nothing above $25 moves without a 200-leg reachable cohort.
- **Refutation:** C-200's reachable-only record beats STANDARD's by ≥5pp over a 200-leg cohort → the
  split is right as it stands and I withdraw.
- **Expected effect:** ≈ **+$280 per 74 days per $20k** of redirected notional at current prices —
  small in dollars, decisive in direction: it stops a 3x clip raise from being paid to the weak lane.
- **Cost:** 1h (card amendment); do not apply the clip change until §1's restatement is approved, or
  the sizing change will be measured against a phantom baseline.

---

**IF YOU WEREN'T HERE:** stop the ladder and the daily report from crediting C-200's 236 never-filled
legs — the book's best-looking lane is 85% of the notional and 96% of its profit is a price the market
never showed, while the small lane that fills 90% of the time is the only one whose number survives
being re-priced.

---

### Instrument repairs performed directly (Lane B, no approval needed)

- **New `scripts/profit-fill-tape.py`** — 100% fill coverage from the venue's own tape: coverage, a
  horizon sweep calibrated against the resolver's 570 stamped verdicts, the 60m and 24h class census,
  per-lane restatement, break-even entry slippage, fillability by band, dispatch-gap decomposition with
  CIs, ledger cross-tab, 1-minute re-check of the negative claim, and six self-tests (**6/6**:
  classifier boundaries, restatement identity, diff-CI antisymmetry under arm swap, `true_pnl` exit
  identity). Read-only; nothing stamped.
- **Corrected my own instrument from yesterday's report, twice, in public:** (a) the −46.7% filled-class
  figure does not reproduce at 515 legs (−7.7%, CI [−29.3,+17.6]); (b) "the unresolved class can never
  be adjudicated" was false — the CLOB price tape is queryable retroactively and gave 100% coverage.
  Both are stated in §2 rather than quietly dropped.
- **Caught before quoting:** a first pass labelled `bid −1c` as a *worse* fill when it is 1c cheaper;
  the sign is fixed and the label now names the adverse direction.
- Nothing else touched: no rule, threshold, gate, size or lane moved; no `apply-v*.ts` run; no RuleSet
  read or write.
