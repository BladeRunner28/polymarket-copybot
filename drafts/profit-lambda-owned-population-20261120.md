# λ̂ on the owned population — the cheap band's sizing input, refitted on the legs we own

**Card** `profit-lambda-owned-population` · approvals id `apr-profit-lambda-owned-population` · lane A ·
**PROPOSAL ONLY — nothing applied.** `data/premium-calibration.json` is untouched (mtime 2026-11-15),
no `apply-vNN` ran, `prisma/dev.db` not written.
**Instrument** `scripts/profit-lambda-owned-population.py` (read-only, `mode=ro`, selftested).
**Read** `data/lambda-owned-population-read-20261120.txt` (the full run this document quotes).

---

## 1. Key insight

The card's mechanism is wrong, its arithmetic is right in direction, and its fix cannot work through
the lever it names.

1. **The live λ̂ is NOT fitted on wallet prints.** `scripts/calibrate-premium.py :: finished_trades()`
   reads `PaperTrade WHERE botId='BANKROLL_200' AND status IN ('resolved','closed')` — our own booked
   rows — and labels each `1 if realizedPnl > 0`. Reproduced here within 0.032 in every band and
   exactly in two of five (§3). The real defects are different: **the population is every settled leg
   (owned or not), the price is the detection mid, and the label is a PnL sign, not the market outcome.**
2. **Refitted on the outcome label, the cheap band's λ̂ is −0.28 / −0.30, not −0.53.** At a 13.5c ask
   that is q ≈ **20.4%**, not the 28.4% the table asserts. On the arm the card names — tape-owned legs,
   venue winner as the label — λ̂ = **−0.277 on 35 legs** (hit 17.1%, Wilson [8%,33%]); on the whole
   labelled book, **−0.299 on 268 legs** (hit 17.5%, Wilson [13.5%,22.5%], clustered CI
   **[−0.482, −0.070]** — which **excludes the live −0.531**).
3. **…and it moves no money.** At `availableBankroll = $6,721.88` the $100 per-position cap binds for
   *any* λ̂ ≤ −0.112 at 13.5c. Every candidate value (−0.53, −0.30, −0.28) still books **$100**. The
   book's cheap clips are *not* two-valued — 32 × $100, 42 × $20, 3 × $50 and six odd clips
   ($17.37 ×4, $17.99, $9.97) (§6) — but under today's knobs every cheap-band Kelly clip saturates the
   $100 cap, and the $20 clips belong to the short-TTR/standard lane, which never reads λ̂. λ̂ decides
   whether a leg is Kelly-admitted at all, never how much it is for: **the clip is a
   `kellyMaxSizeUsd`/cap problem; λ̂ is a correctness problem.** Fixing λ̂ is worth $0 today and becomes
   worth money only when cash falls below ~$2,490 or the cap moves.

## 2. What the card claimed vs what I measured

| card claim | measured | verdict |
|---|---|---|
| λ̂ = −0.5308 is "fitted on wallet prints" | fitted on `PaperTrade` C-200 settled rows, `realizedPnl>0`; reproduced −0.4993 (n=348) today | **wrong mechanism** — it is our book, not the wallets |
| owned population hit 13.0% (7/54), 95% UB 24.9%, "below 28%" | 13.0% reproduces **only** as a *reconstructed-exit $ sign* (7/54). Venue-outcome label: **17.1% (6/35)**, Wilson [8.1%, 32.7%] — brackets 28% | **label-basis error** — a PnL sign was compared to a probability |
| owned λ̂ ≥ −0.20 ⇒ "over-betting by ~3x", re-derive size | owned λ̂ = **−0.277** (rule misses by 0.077); at 13.5c that is q 20.4% vs 28.4% (**1.39x** on q, **2.14x** on the Kelly fraction), not 3x | rule not met; overstatement real but smaller |
| the refit is what stops the $100 clip | the cap binds at any λ̂ ≤ −0.112; the $100-cap cohort is 32 of 83 cheap legs, 74.6% of the cell's notional, and it is sized by the cap, not by λ̂ (§6) | **the refit cannot shrink the clip** |

## 3. The live table reproduced (so the premise is checked, not assumed)

`./venv-calib/bin/python scripts/profit-lambda-owned-population.py` — A1 arm, byte-identical query
and label to `calibrate-premium.py`:

| band | n | win% (PnL>0) | λ̂ today | λ̂ live (2026-11-15) | delta |
|---|---:|---:|---:|---:|---:|
| 0.00–0.20 | 348 | 22.4% | −0.4993 | −0.5308 | +0.032 |
| 0.20–0.40 | 667 | 31.5% | −0.0319 | −0.0632 | +0.031 |
| 0.40–0.60 | 1,002 | 47.0% | +0.0594 | +0.0594 | 0.000 |
| 0.60–0.80 | 599 | 55.9% | +0.3502 | +0.3392 | +0.011 |
| 0.80–1.01 | 171 | 78.4% | +0.4128 | +0.4128 | 0.000 |

Two bands reproduce exactly; the other three moved by ≤0.032 in five days of new settlements. **This is
our book.** (Label sources validated: `OutcomeReview.finalOutcome` on 1,498 legs, venue archive on 1,831,
**agreement 1,282/1,282 = 100%** where both speak.)

## 4. Four arms on the same bands — the label, not the population, is the big term

C-200, deduped, `isDemo=0`, settled; ownership = venue minute tape touch within 3600s (`filled_tape`).

| band | A1 book × PnL>0 | A2 book × outcome | A3 **owned × outcome** | A4 owned × PnL>0 |
|---|---|---|---|---|
| 0.00–0.20 | n=348 · 22.4% · **−0.499** | n=268 · 17.5% · **−0.299** | n=35 · 17.1% · **−0.277** | n=54 · 5.6% · +0.374 |
| 0.20–0.40 | n=667 · 31.5% · −0.032 | n=471 · 35.2% · −0.128 | n=54 · 24.1% · **+0.180** | n=69 · 18.8% · +0.361 |
| 0.40–0.60 | n=1,002 · 47.0% · +0.059 | n=725 · 49.8% · −0.009 | n=2 · — | n=2 · — |
| 0.60–0.80 | n=599 · 55.9% · +0.350 | n=487 · 70.0% · −0.031 | n=51 · 62.7% · **+0.148** | n=71 · 39.4% · +0.763 |
| 0.80–1.01 | n=171 · 78.4% · +0.413 | n=96 · 87.5% · +0.023 | n=2 · — | n=15 · — |

Read: **A1 → A2 is the label fix (−0.499 → −0.299, +0.20); A2 → A3 is the population fix
(−0.299 → −0.277, +0.02).** The population the card suspected is a small term. The label it did not
name is the large one. Note also that on OWNED legs the two upper bands read **positive** (0.20–0.40
+0.180, 0.60–0.80 +0.148) — i.e. "overpriced, do not buy" — while the book-wide arm reads −0.031 for
0.60–0.80 and would re-admit that band (§7).

## 5. Same 54 owned cheap legs, three labels — which one is the card's 13.0%?

| label | rate | note |
|---|---|---|
| booked PnL sign (`realizedPnl>0`) | **3/54 = 5.6%** | 18 legs are booked at ZERO PnL by the unfilled-stamp convention — understates |
| reconstructed exit sign (`pnl_at`, `te.exit_of`) | **7/54 = 13.0%** | **this is the card's number** (S9 tier table's "hit" column) |
| venue winning label | **6/35 = 17.1%**, Wilson [8.1%, 32.7%] | the probability target; 19 owned legs have no resolved market |

The card compared a **$ sign at a reconstructed exit** to q ≈ 28% and concluded the probability input
was too high. The right comparison is row 3, and it does not reject 28% at n=35. It is the book-wide
arm (n=268) that rejects the live λ̂.

## 6. What each λ̂ actually buys — and why the refit is worth $0 today

Live knobs (RuleSet v73): `kellyFraction 0.5`, `kellyMaxBankrollPct 0.10`, `kellyMaxSizeUsd 100`,
`kellyMinEdgePct 0.02`, `c200LongshotBandFactor 3.5` (floor `max(kelly, legacyEquiv)`),
`premiumOverlayEnabled 0` (the overlay is OFF, so λ̂ reaches the Kelly path only),
`BotBankroll.cashBalance = $6,721.88`.

| paid price | cap binds for any λ̂ ≤ | q @ live −0.531 | q @ owned −0.277 | clip live | clip owned |
|---|---:|---:|---:|---:|---:|
| 0.050 | −0.228 | 0.133 | 0.086 | $100 | $100 |
| 0.104 | −0.136 | 0.233 | 0.163 | $100 | $100 |
| 0.135 | −0.112 | 0.284 | 0.204 | $100 | $100 |
| 0.190 | −0.086 | 0.364 | 0.274 | $100 | $100 |

`size = min(fraction·f*·avail, 10%·avail, $100)`. At $6,722 of available bankroll the last term wins
everywhere. **The λ̂ only starts mattering when cash falls below ~$1,164 (live) / ~$2,490 (owned
value, 13.5c ask)** — at which point the corrected table books ~40% less than the live one instead of
both being clipped at the ceiling.

And the clip structure inside the cell — a partition of all 83 regime legs, with every row checked to
sum to the cell's own $4,287.44 / −$616.86 (read A5b; this is the partition, not a filtered view):

| cohort | legs | intent $ | share | booked PnL | legs w/ `premium λ̂` tag |
|---|---:|---:|---:|---:|---:|
| at the $100 per-position cap | 32 | 3,200.00 | **74.6%** | **−$977.89** | 27 |
| $50 (sized under an earlier cap vintage) | 3 | 150.00 | 3.5% | +$203.63 | 3 |
| under $50 — $20 ×42, $17.37 ×4, $17.99, $9.97 | 48 | 937.44 | 21.9% | +$157.40 | 0 |
| **total** | **83** | **4,287.44** | 100% | **−$616.86** | 30 |

The top two rows are the card's ≥$50 tier: **35 legs, $3,350.00, 78.1% of the cell's notional,
−$774.26 booked**. The card prices that tier at −32.1% EV/int = −$1,075; that gap is a basis
difference, not a different leg set — the card's EV/int is measured on `trueP` dollars at risk, the
column above is booked `realizedPnl`.

Read: the $100 cohort carries the loss (74.6% of notional, −$977.89, against a cell total of
−$616.86) and every leg in it sits exactly at the cap (27 of the 32 carry the `premium λ̂=−0.68`
journal tag; five untagged STANDARD-dota2 legs were dispatched at the same size). A λ̂ change resizes
none of them: at $6,722 of cash the cap binds for any λ̂ ≤ −0.112, so −0.531 and −0.277 both book
$100. The $20 clips belong to the short-TTR/standard lane, which never reads λ̂; the three $50 legs are
tagged Kelly but sit below the cap, where the value of λ̂ at today's bankroll is not what set them.

(An earlier revision of this section quoted 36 legs / $3,368 / −$792 for a "λ̂-sized" cohort. No
definition yields it — it is the ≥$50 tier's 35 legs plus the single $17.99 untagged STANDARD leg
($3,367.99, −$792.25), and it reconciles with neither the cell's total nor the card's tier. Superseded
by the partition above.)

**The clip cap is the dollar lever (already approved as the $25 cap on this band); the λ̂ refit is an
input correction that only binds once the cap or the bankroll moves.**

## 7. Blast radius if the whole table were swapped (why the proposal is scoped to one band)

Band median booked price, live knobs, live table → outcome-convention table:

| band | med price | live λ̂ | q | clip | → A2 λ̂ | q | clip | read |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 0.00–0.20 | 0.105 | −0.531 | 0.235 | $100 | −0.299 | 0.170 | $100 | no change |
| 0.20–0.40 | 0.310 | −0.063 | 0.333 | $20 | −0.128 | 0.357 | $20 | no change (book arm) |
| 0.40–0.60 | 0.491 | +0.059 | 0.468 | $0 | −0.009 | 0.495 | $0 | no change |
| 0.60–0.80 | 0.685 | +0.339 | 0.557 | $0 | −0.031 | 0.696 | **$100** | **BAND RE-ADMITTED** |
| 0.80–1.01 | 0.880 | +0.413 | 0.777 | $0 | +0.023 | 0.875 | $0 | no change |

The book-wide arm would **re-admit 0.60–0.80 at full $100 clips**. The owned arm does not: on owned
legs that band reads **+0.148 (n=51) → still no edge → still skipped**. That is the strongest argument
for the card's own instinct — use the owned population, not the book — and it is why the swap is
proposed for one band only. Separately, the owned arm says **0.20–0.40 = +0.180 (n=54, hit 24.1% vs a
0.31 median price)**, i.e. that band should skip; that is a zero-flow change to a different cell and
needs its own decision, so it is **reported here, not proposed**.

Stability: the cheap band's outcome-basis λ̂ reads **−0.356** (first half, median decision 2026-09-11)
and **−0.241** (second half, median 2026-10-22) — same sign, drifting toward zero, no level flip.
Price basis check: booked entry −0.299 vs paid price (`trueP`) −0.299 on the same 268 legs — the
complement-frame repricing does not touch this band's sample.

---

## 8. Proposal

### P1 (recommended) — replace the **0.00–0.20** λ̂ with the owned × venue-outcome value, from the refit path, not by hand

- **Change:** `scripts/calibrate-premium.py` gains `--population owned --label outcome --price paid
  --scope-band 0.00-0.20` (owned = `filled_tape` from the fill-tape cache, label = venue winner through
  the `didOutcomeWin` guard, price = booked/paid entry). Run once; it writes
  `data/premium-calibration.json` with **one field changed**:
  `bands[0].lambda: −0.5308 → −0.2773` (and `n: 336 → 35`). The other four bands keep their live values
  and are reported, not replaced.
- **Before / after, every figure that moves:**

  | figure | before | after |
  |---|---|---|
  | `bands[0].lambda` | −0.5308 | **−0.2773** |
  | `bands[0].n` | 336 (book × PnL) | **35** (owned × outcome) |
  | q at a 13.5c ask | 0.284 | **0.204** |
  | q at the band's median paid price 0.105 | 0.235 | **0.163** |
  | clip at 13.5c, cash $6,722 | $100 | **$100 (unchanged)** |
  | cash level below which size starts to fall | $1,164 | **$2,490** |
  | journal tag `premium λ̂=…` | "info edge (underpriced)" | **unchanged** (threshold ≤ −0.15) |
  | sizes today | — | **$0 difference** |

- **Why ship a change worth $0 today:** it is the input every later sizing decision multiplies, it stops
  the table asserting 10pp of probability the population cannot support, and it makes the *next* refit
  (2026-12-01) inherit a defensible convention. It also cannot re-inflate: the same run reports the
  number rather than hand-typing it.
- **Cost** 2h · **Risk** low (one numeric field in one file; no band changes flow) ·
  **Revert** `git checkout HEAD~1 -- data/premium-calibration.json && git checkout HEAD~1 -- scripts/calibrate-premium.py`
  (or set `bands[0].lambda` back to −0.5308 and `n` to 336).
- **Decision rule (pre-registered):** keep the new value while a trailing owned-cheap sample of ≥35
  labelled legs reads a hit rate whose Wilson interval contains the implied q, and while the
  outcome-basis λ̂ stays ≤ −0.15 (i.e. the band keeps an edge). Re-read at each biweekly refit.
- **Refutation:** (a) ≥150 owned cheap legs resolve and hit **≥28%** — the card's pre-registered bar,
  restored here (an earlier revision of this draft had lowered it to 100 without saying why) → the
  live −0.53 was right and the 13% reading was small-sample weather; (b) the corrected λ̂ reaches
  ≥ −0.11 while the $25 cap is in force, in which case the cheap band's legs stop being Kelly-admitted
  at all and the cap becomes moot; (c) any measured forward cohort where the −0.277 table sizes
  *worse* than −0.531 at equal cash.

### P2 — treat the clip as the dollar lever, not λ̂ (already approved as the $25 cap)
Nothing in this study changes the earlier card: 74.6% of the cell's notional sits at the $100 cap and
carries −$977.89 there because `kellyMaxSizeUsd` puts it there, not because of λ̂. With P1 shipped and
cash at $6.7k the cheap band still books $100. **The cap is what moves the money.**

### P3 — 0.20–0.40 (reported, needs its own card)
Owned × outcome reads **+0.180 (n=54, hit 24.1% vs 0.31 median price)** → the band is overpriced and
should skip; live λ̂ (−0.063) admits it at $20 and it returns −7.8% EV/int on 128 regime legs
(CI [−25.9, +11.4] — underpowered, which is why this is a card and not a line in P1).

### Not proposed
Swapping the whole table from the book-wide arm (re-admits 0.60–0.80 at $100 clips, §7); changing the
label basis for 0.40–0.60 and 0.80–1.01 (2 owned labelled legs each — no measurement exists); touching
`kellyMaxSizeUsd`, the rails, or the short-TTR lane's fixed size in this change.

---

## 9. What would settle it (and how long it takes)

The owned sample is label-limited, not leg-limited: 54 owned cheap legs, only **35 resolved enough to
carry a venue winner**. The owned cheap legs themselves are a **22-day window (2026-10-28 → 2026-11-19,
~17 owned/week)**, so the arm adds roughly **11 labelled legs a week**; the card's pre-registered bar
that ends the argument — **150 labelled owned cheap legs** (≥150 hitting ≥28% refutes P1) — is about
**11 weeks out, early February 2027**. At that width the λ̂ standard error falls from 0.254 to
0.254·√(35/150) ≈ **0.12**, and the reading either confirms −0.28 or restores −0.53. (The 115-day
median time-to-resolution is what makes this the binding constraint, not leg flow.)

Until then every reading of this band should state which of the four conventions it used — and no
review should compare a $ sign to a q again.

## 10. Reproduce

```bash
cd ~/polymarket-copybot
./venv-calib/bin/python scripts/profit-lambda-owned-population.py --selftest     # 8 checks, incl. a
                                                                                # synthetic λ recovery
                                                                                # and the clip partition
./venv-calib/bin/python scripts/profit-lambda-owned-population.py                # the full read
                                                                                # (§A5b is the clip
                                                                                #  partition §6 quotes)
python3 scripts/profit-marginal-cell.py                                          # S9 tier table (card's
                                                                                # 48/29/$937 and 35/25/$3,350)
```

Files: instrument `scripts/profit-lambda-owned-population.py`; read
`data/lambda-owned-population-read-20261120.txt`; live table unchanged
`data/premium-calibration.json` (2026-11-15).

## IF YOU WEREN'T HERE

The table was never fitted on wallet prints — it is fitted on our own rows, with a PnL sign as the
label, which is why it claims 28% at 13.5c where the outcome-labelled book says 20%. Refitting it
correctly moves λ̂ from −0.53 to −0.28 and moves **no dollars**, because the $100 cap binds for
any λ̂ below −0.11 at current cash. Ship the one-field correction (it is free and it is the input
the next sizing decision multiplies), keep the $25 cap as the clip fix, and leave 0.60–0.80 out of
the table change — the owned arm keeps it skipped while the book-wide arm would re-admit it at $100.
