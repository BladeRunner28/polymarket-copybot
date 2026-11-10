# Price-side inversion — the ledger books the YES quote on 90 legs that hold the other token

**Lane A proposal · 2026-11-09 · nothing applied.** Roadmap card `price-side-inversion`
(measured today; the card's 11-08 numbers are re-derived below and have drifted by 3 legs / $627).

| | |
|---|---|
| Status | **hypothesis CONFIRMED at the mechanism** — the card's own refutation test was run and did not fire |
| Class | 90 legs · $2,476 notional · **+$5,641.69 booked = 59.7% of the book's +$9,443.76** |
| Corrected book | +$3,834.05 (reprice only) → **+$3,852.99** (+12.7%) with the live gates re-run |
| C-200 7-day ladder gate | +$2,674.85 booked → **−$186.65** corrected; the class is 108% of the gate sum |
| Ask | **approve the source fix in §5** (or reject it). No RuleSet, band, clip or drift-gate change is proposed. |
| Reproduce | `python3 scripts/profit-price-side.py` + `python3 scripts/price-side-read-source.py --legs 32` |

---

## 1. What is wrong — one positional read, four gates

The adapter turns the venue's `outcomePrices` array into two named fields by POSITION:

`src/lib/adapters/polymarket.ts:695` — `yesPrice = num(prices[0]); noPrice = num(prices[1]);`

Every consumer then picks between them with a two-label test:

`scripts/monitor-trades.ts:171` · `scripts/score-trades.ts:460`

```ts
const p = t.outcome === "NO" ? m.noPrice : m.yesPrice;
```

`src/lib/scoring/trade.ts:453` — `currentPrice: m.yesPrice ?? walletEntryPrice`
`scripts/update-pnl.ts:220` and `src/lib/exit-recovery.ts:175` carry the same selector for exits.

On a **Yes/No** market those two labels name the two tokens, so position and label coincide and
nothing is wrong. On a **label-named** market (`Under`/`Over`, `Canadiens`, `Jiri Lehecka`,
`Texas Tech`) the test falls through to the else-branch for every outcome that is not the literal
string `"NO"` — so **every leg holding the second-listed token is priced off the first-listed
token**, i.e. booked at `1 − true price`. The measured consequence:

- 90 of the 735 label-named regime legs are inverted (12.2%); **0 of the 1,396 Yes/No legs are**.
- 624 label-named legs are booked correctly — they are the ones holding index 0; the remaining 21
  label-named legs land in the "neither" bucket (stale mid-moves).
- Tape check (§3): recorded token is **outcome_index 1 on 31 of 31** graded inverted legs, and
  **outcome_index 0 on all 12** control legs.
- Because `currentPrice` is the same number, one wrong read is the operand of the high-entry caps,
  the `0.4-0.6` band skip, the `×3.5` long-shot size factor and the band map. The class is not
  merely *booked* at a long-shot price — it was *admitted and sized* as one.

`MarketSnapshot` writes `yesPrice`/`noPrice` at detection (`monitor-trades.ts:179`), so the
snapshot cannot be used to detect this after the fact; it records the same two slots.

## 2. Measured basis (all figures re-derived today from `prisma/dev.db`, read-only)

Population: finished legs with `ruleSetVersion >= 49`, `realizedPnl NOT NULL`, `simulatedPositionSize > 0`
= **2,131 legs, $30,384 notional, +$9,443.76 (+31.1%)**.

| class | n | notional | booked PnL | ROI | % of book PnL | hit% | avg booked px | avg wallet px |
|---|---|---|---|---|---|---|---|---|
| **INVERTED** | 90 | $2,476 | **+$5,641.69** | +227.8% | **59.7%** | 60.0% | 0.245 | 0.747 |
| consistent | 2,006 | $27,348 | +$3,996.53 | +14.6% | 42.3% | 40.8% | 0.437 | 0.446 |
| neither | 35 | $560 | −$194.46 | −34.7% | −2.1% | 51.4% | 0.425 | 0.535 |

4.2% of legs and 8.1% of notional carry 59.7% of the PnL. Window: first leg opened **2026-10-26**,
last 2026-11-08 (26 Oct, 64 Nov), **8 wallets, top two carry 69 of 90** (0x885ffdf3 36, 0xf5a3504a 33).

**The mirror.** Booked entry and `detectedPrice` both sit at the wallet's fill mirrored about 0.50,
against a control class where they sit *at* the wallet:

| | `|booked − (1−wallet)|` | `|detected − (1−wallet)|` | `|booked − wallet|` |
|---|---|---|---|
| INVERTED (n=90) | med **0.007**, p90 **0.020** | med **0.005** | med 0.462 |
| consistent (n=2,006) | med 0.295, p90 0.715 | med 0.297 | med 0.011 |

A complement to half a cent on two independently stored fields is arithmetic, not price movement.

**The market, not just the wallet, is on the other side.** `MarketSnapshot` at the trade minute,
top-40 inverted legs by |PnL|: booked price = the YES quote on **40 of 40** (median distance
**0.000**), while the wallet's fill = the NO quote to within **0.005**.

**The hit-rate test (model-free).** Buying at price `p` breaks even at a `p` hit rate. The class
hits **60.0%** at an average booked price of **0.245** — a **+35.5pp "edge"** — and is **−14.7pp
below** the price the wallets actually paid. In the top wallet-price quintile (w 0.86–0.94) it hits
61.1% at a booked price of 0.104.

**What the class is worth at the price the wallets paid.** Repricing every resolved inverted leg at
`walletEntryPrice`: the class books **+$31.98 (+1.3%)** instead of +$5,641.69. The book:

| basis | whole book | C-200 | STANDARD |
|---|---|---|---|
| booked | +$9,443.76 (+31.1%) | +$8,976.86 (+49.0%) | +$466.90 (+3.9%) |
| repriced (upper bound) | +$3,834.05 (+12.6%) | +$4,995.18 (+27.3%) | **−$1,161.14 (−9.6%)** |
| **fixed path** (live gates re-run) | **+$3,852.99 (+12.7%)** | **+$5,023.56 (+27.4%)** | **−$1,170.57 (−9.7%)** |

Bands (deduped, 1,967 legs; repriced rows stay in their **booked** band, so the cheap band's figure
is conservative):

| band | n | booked ROI | repriced ROI |
|---|---|---|---|
| 0.0–0.2 | 315 | +86.4% | **+43.9%** |
| 0.2–0.4 | 514 | +19.1% | **+8.2%** |
| 0.4–0.6 | 672 | −7.4% | −7.4% |
| 0.6–0.8 | 445 | −0.1% | −0.1% |
| 0.8–1.0 | 21 | −4.5% | −4.5% |

Concentration: ex-top-1 +$7,930.43 → +$2,320.72; **ex-top-5 +$4,683.18 (+15.7%) → +$476.10 (+1.6%)**;
ex-top-10 +$1,871.92 (+6.4%) → **−$733.65 (−2.5%)**.

## 3. The refutation test — run, and it did not fire

The card pre-registered: *a tape check of ≥20 legs (`/v2/trades`, `condition_id` + per-token
`outcome`/`outcome_index`) showing the booked price is what those tokens traded at would make the
wallet price the wrong one and move the fix to a different file.*

Method: for the 32 largest-|PnL| inverted legs (deduped by market+outcome), pull the venue's own
print tape for the condition and, at the trade minute, take the median print on the **recorded
outcome's token** and on its **sibling**. Cursor-paged back to the trade minute (the tape is
cursor-only and newest-first; a single 500-row page covers only ~1.8 h on a busy market).

| verdict | n |
|---|---|
| booked price = SIBLING token's price (≤0.02) | **29** |
| inconclusive (market moved between the print and the trade minute) | 2 |
| no tape available at the minute | 1 |
| **booked price = RECORDED token's price (the kill condition)** | **0** |

Agreement over the 31 graded legs, `|median − booked|`: **sibling med 0.005, p90 0.017, ≤0.02 on
29**; recorded token **med 0.505, p90 0.760, ≤0.02 on 0**. Tolerance-free form: booked is nearer
the sibling on 25 legs, nearer the recorded token on **0**.

**Differential control (the part that makes the test mean something).** The same procedure on 12
**consistent** label-named legs — legs the ledger got right — returns **7 LEDGER=OWN, 5
inconclusive, 0 LEDGER=SIBLING**, and every one of them holds outcome_index 0, while all 31 graded
inverted legs hold index 1. The instrument can return "own" (it does so on the control arm and on a
synthetic tape in the self-tests), so "0 of 32" is a measurement, not a constant.

**Conclusion.** The wallet price is not the wrong one; the ledger's read is. The fix belongs in the
price read, not in the wallet matching, and the card's kill condition is empty.

## 4. What the fix changes besides the PnL figure — it changes ADMISSION

On the true price the class is not a long-shot at all: booked bands are 0.0–0.2 (34 legs) and
0.2–0.4 (56), but the true prices are **0.6–0.8 (57), 0.8–1.0 (32), 0.4–0.6 (1)**. So the same
repair that fixes the booking re-runs four gates on a completely different number:

- **C-200 high-entry cap 0.80** refuses **15 of 43** C-200 legs.
- **STANDARD high-entry cap 0.85** refuses **9 of 47** STANDARD legs.
- **0.4–0.6 band skip** (both lanes live) refuses 1 more C-200 leg.
- **×3.5 long-shot size factor** no longer fires on a 0.75 favourite.

**25 of 90 legs (28%) would never be copied.** Their booked PnL is +$4,043.68 on $1,395 of
notional. This is a flow cost, and it is the reason the corrected +$3,852.99 is not a straight
subtraction: refusing legs removes winners *and* losers. By lane the class books **C-200
+$4,093.94** (43 legs) and **STANDARD +$1,673.08** (47 legs), plus 4 early exits at −$125.33.

**The ladder.** C-200, 7 local calendar days (2026-11-03 … 2026-11-09, 140 legs): booked
**+$2,674.85** → fixed path **−$186.65**. The class alone is 26 legs / +$2,888.85 = **108% of the
gate sum**. The $250/day rung clears on the booked figure and clears nothing on the corrected one.

## 5. The proposed change (not applied — this is the ask)

1. Add one helper next to the existing label machinery — the adapter already parses
   `outcomeLabels` + `outcomePrices` and returns both (`polymarket.ts:681-742`), and
   `normalizeOutcomeLabel()` already exists in `src/lib/resolution.ts`:

   ```ts
   /** Price of the token this outcome actually names. Falls back to the
    *  positional yes/no pair ONLY when the venue gave us no labels. */
   export function priceForOutcome(m: MarketState, outcome: string): number | undefined {
     const want = normalizeOutcomeLabel(outcome);
     if (m.outcomeLabels?.length && m.outcomePrices?.length === m.outcomeLabels.length) {
       const i = m.outcomeLabels.findIndex((l) => normalizeOutcomeLabel(l) === want);
       if (i >= 0) return m.outcomePrices[i];
     }
     return outcome === "NO" ? m.noPrice : m.yesPrice;
   }
   ```

2. Replace the four selection sites with it: `monitor-trades.ts:171` (detectedPrice),
   `score-trades.ts:460` (currentPrice → caps/skip/band/clip), `trade.ts:453`,
   `update-pnl.ts:220` + `exit-recovery.ts:175` (exit pricing).
3. **No RuleSet change, no band-map change, no drift-gate change, no clip change.** The gates
   behave correctly; they were fed a bad operand. `f61fdbe` (drift gate → directional,
   user-approved) is the commit that stopped accidentally blocking this class — recorded as the
   explaining history, **not** as a thing to revert.
4. Tests: a synthetic market `outcomes=["Over","Under"], outcomePrices=[0.13,0.87]` with a trade on
   `"Under"` must price **0.87**, and a Yes/No market must be unchanged; plus one test asserting the
   label path wins when both labels exist.

Out of scope by the card's own note: the fill-aware booking card (legs that were never positions).
The two compound and must not be added together.

## 6. Acceptance bar and REFUTATION of the fix

**Accept (the card's bar):** `INVERTED n = 0` on the next **150 settled regime legs** after deploy,
measured by `scripts/profit-price-side.py` (its classifier is unchanged and independent of the fix).

Refuted if, over those 150 legs, **any** leg shows `|entryPrice − (1−walletEntryPrice)| < 0.06` **and**
`|entryPrice − walletEntryPrice| > 0.10`. If such a leg's outcome is `outcome_index 1` on a
label-named market, the read was not fixed at one of the five sites; if it is index 0, the model is
wrong somewhere else entirely and this proposal must be withdrawn, not patched.

Secondary (informational, not a bar): the label-named/Yes-No split should stay 0 inverted on both;
the tape control arm should keep returning LEDGER=OWN.

## 7. Reality checks / what this measurement does NOT establish

- **Repricing is an estimate.** The counterfactual entry is the copied wallet's own fill: no
  slippage, no fee, and strictly the *lower bound* of the correction on winners (the true price is
  always higher than the booked one, so the payoff only falls).
- **Early exits are not repriced.** 4 of the 90 legs closed early; their PnL was also computed
  against a wrong entry but is left at its booked value, so the fixed-path total is approximate in
  both directions. The 7-day gate figure is affected by the same rule.
- **The tape sample is the 32 largest legs**, not a random draw. Inverted legs are systematically
  large (that is why they rank top), so the tape evidence is biased toward exactly the legs that
  matter, and says less about the tail.
- **Wallet-print coverage is low on the tape** (3 of 31 graded legs show the copied wallet's own
  print on the recorded token) — the copied wallets route through aggregators. This does not weaken
  the test (it uses the token medians, not the wallet's print) but it means "we can see the wallet's
  fill on the tape" is not a usable check.
- **The drift-gate history is inherited, not re-measured.** That `|drift| > 0.004` blocked every one
  of these legs before `f61fdbe` is the 11-08 review's claim and is consistent with the class window
  starting on 2026-10-26; the fix does not depend on it.
- **The class is 2 wallets.** 69 of 90 legs come from two addresses, so a forward read of 150 legs
  may complete slowly if those wallets stop trading.
- **Population drift.** The card was written on 87 legs / +$8,817; three more legs settled since. All
  figures here are re-derived on 90 legs / +$9,443.76 today.

## 8. Overridable decisions (each is a one-line answer)

1. **Approve the source fix as specified in §5** — default: yes. Revert: one helper + five call
   sites; `git revert` of the single commit restores the positional read.
2. **History: forward-only or also re-book the 90 existing legs?** Default: **forward-only**.
   Rewriting `PaperTrade.entryPrice` on settled rows changes every published figure retroactively
   (book, bands, ladder, EOD history) and is a separate decision with its own before/after.
3. **Ladder: do not take the $500/day rung on this window** — default: hold. The 7-day sum that
   passes $250/day is 108% this class; it fails on the corrected basis. Re-check after the fix's 150
   settled legs.
4. **Instrumentation:** stamp the traded token's own price at detection (additive column on
   `MarketSnapshot`) so a future recurrence is visible without a tape crawl. Default: **not in this
   patch** (schema change, separate card).

## 9. Reproduce

```bash
cd ~/polymarket-copybot                      # read-only; both scripts open the DB with mode=ro
python3 scripts/profit-price-side.py                     # §1-§10: class, mirror, snapshot, hit rate, reprice, bands, ladder, ex-top-N
python3 .worktrees/t_2bdd07dc/scripts/price-side-read-source.py --legs 32
                                                          # §1 fingerprint, §2 the read in code, §3 tape + control arm, §4/§4b fixed path
python3 .worktrees/t_2bdd07dc/scripts/price-side-read-source.py --no-tape --self-test
                                                          # self-tests without network
```

`price-side-read-source.py` is new with this card and lives in the worktree for branch
`wt/price-side-inversion` (also attached to the board card); once merged it sits at
`scripts/price-side-read-source.py`. Its §2 asserts the four code patterns still match and prints
`SELF-TEST FAIL — the read in §2 has MOVED` if a fix lands, so the instrument cannot silently go
stale against the defect it describes.
