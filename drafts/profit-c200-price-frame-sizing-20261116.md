# C-200 sized on the sibling token's price — the writer, the size that survived the repair, and why the card's own fix is already shipped

**Lane A · PROPOSAL ONLY · 2026-11-16**
Board card: kanban `t_9753ec80` · approval `apr-profit-c200-price-frame-sizing` (approved 2026-11-16T22:06Z)
Parent finding: `drafts/profit-c200-clip-cap-25-20261116.md` §4 · predecessor frame work: `drafts/c200-complement-frame-repair-20261112.md` (t_1f579e82)
Instrument: `scripts/profit-c200-frame-census.ts` (read-only, committed with this document)

> **Nothing has been applied.** `prisma/dev.db` was opened read-only for every measurement
> (`sqlite3 -readonly "file:…?mode=ro"`); no `apply-vNN.ts` was run, no RuleSet touched (still **v73**),
> no row written, no code path changed, nothing merged. The apply/decide step is §7 and it is yours.

---

## Verdict

**The card's finding is real, its diagnosis is half wrong, and the change it authorises has already
been shipped — by a commit that predates the card by 8 days.** The honest close is verification plus
two consequences the card did not have, not a price-source change.

1. **The `0.865` on those rows is not a booking — it is the 2026-11-11 ledger repair's post image.**
   The card's open question ("which writer puts the correct 0.865 on the row") is answered: the repair
   `d974287`, from a pre-image of **0.13332**. The sidecar never wrote 0.865 — on Polymarket it books
   `intent.price − maker_credit` and nothing else (`rust-sidecar/src/main.rs:128,159-174`).

2. **So the size was coherent when it was taken and became incoherent when the price moved.** One
   positional price read fed Kelly, the λ̂ band, the long-shot rails, the dispatched intent *and* the
   booked entry. Kelly sized a **13.3¢ longshot** at $100 and the book recorded a 13.3¢ longshot at
   $100 — internally consistent, and wrong about the market. Five weeks later the repair re-priced the
   entry to the favourite price and left `simulatedPositionSize` where the longshot decision put it.
   That is the defect this card can actually own: **a repaired price with an unrepaired size.**

3. **Forward, the class is closed.** `fbf9073` (2026-11-09 09:15) moved all four Node writers onto
   `priceForOutcome()`; Kelly at `score-trades.ts:927` is handed `currentPrice`, which is that same
   label-priced number (`:524-525`), and so is the λ̂ band at `:925`. Measured on the regime:
   **0 of 113** post-fix intents mirror the wallet's print, **0 of 113** post-fix C-200 legs book above
   0.80, and the booked-entry complement class is **0** across the window. Re-pointing the price source
   again would be a no-op.

4. **What is worth acting on is downstream of the size, not the price.** On the 13 clips the frame
   carried **+$3,013.97 of booked PnL that the repair removed (−$2,927.48 of them, 76% of the class)** —
   and they are *winners* inside the `$100` tier (+$86.49) while that tier's loss sits entirely on the
   29 never-repaired legs (−$677.89). Any size-tier or clip-cap cohort read that spans pre-2026-11-09
   legs is mixing two decisions.

5. **Eight of the 13 carry a fill verdict decided on a level ~$0.73 away from the market** — every one
   of them stamped `unfilled` because the resolver tested `intentPrice` (0.06-0.195) while the wallet's
   own print for the same instant was 0.83-0.94. Those are **undecided, not settled**. That is a write
   (it restates bookings) and belongs to the fill-verdict lane, not to this card.

**Recommendation: (A) close this card as already-shipped and hand the 8 verdicts to the fill lane.**
Nothing else in the option set buys anything measurable today (§7).

---

## 1. What the card asked, and the four candidates it named

The card's `decision_rule` had three steps. Step 1 was identify the writer of the booked level
(candidates: sidecar depth guard · fill adjudicator · entry re-price · backfill). Step 2 was re-point
the scorer's price for Kelly, the premium band, the long-shot floor and the drift/spread gates at the
token the outcome label names, moving "the four call sites" in one change. Step 3 was boundary-test
named-outcome and UNDER legs plus a first-token control.

Step 2 was executed on **2026-11-09** by `fbf9073`, and the four call sites it names are exactly the
four that commit touched (`score-trades` booking, `update-pnl` mark, `monitor-trades` detection price,
`exit-recovery` early-exit value) — with a 104-line test (`tests/outcome-price.test.ts`).

| the card's candidate writer | measured | verdict |
|---|---|---|
| sidecar depth guard | depth guard fires **only** for `venue == Kalshi` / `PredictIt`; Polymarket legs fall through to `executed_price = intent.price` (`main.rs:128-153`) | **not it** |
| entry re-price | `paper.ts:204-236` posts `price: params.entryPrice` and stamps `recordFillIntent({intentPrice: params.entryPrice})` — the same number, no re-price | **not it** |
| fill adjudicator | writes `fillStatus`, never `entryPrice` | **not it** |
| backfill / ledger repair | `d974287` (2026-11-11): 233 rows, **`entryPrice = the sibling-complement / venue-corroborated price`** | **this one** |

The ledger's own pre-image is the proof, per leg:

```
paperTradeId cmw0disuf… pre.entryPrice 0.13332 → post.entryPrice 0.865   (intent 0.135, cheap-band credit 0.00168)
```

`0.135 − 0.00168 = 0.13332` — the pre-image is the intent minus the **0.10-0.20 band's** measured maker
credit, i.e. the sidecar booked what it was handed. The repair then supplied the favourite price. There
is no third writer.

---

## 2. The 13 clips, both frames, with the repair's own pre-image

`npx tsx scripts/profit-c200-frame-census.ts` (population: `BANKROLL_200`, `isDemo=0`,
`journal.ruleSetVersion ≥ 68`, size ≥ $99, membership from the repair ledger — not from the current
columns, which no longer show the class).

```
slug                           outcome          sized@   paid@  wallet    jdλ̂  kelly@sized  kelly@paid
atp-norrie-medvede-2026-10-29  DANIIL MEDVEDEV   0.173   0.825   0.820   -0.74  $100   SKIP q=0.699 ≤ 0.825
atp-altmaie-lehecka-2026-10-29 JIRI LEHECKA      0.153   0.845   0.840   -0.74  $100   SKIP q=0.727 ≤ 0.845
ucl-gal-stu-2026-11-03-spread- VFB STUTTGART     0.133   0.865   0.860   -0.68  $100   SKIP q=0.755 ≤ 0.865
ucl-mnu-rom-2026-11-03-total-5 UNDER             0.113   0.885   0.880   -0.68  $100   SKIP q=0.785 ≤ 0.885
nba-tor-den-2026-11-04-spread- NUGGETS           0.193   0.805   0.780   -0.68  $100   SKIP q=0.672 ≤ 0.805
ucl-aek1-rma-2026-11-04-team-t UNDER             0.059   0.940   0.940   -0.68  $100   SKIP q=0.873 ≤ 0.940
nba-mil-bos-2026-11-04-spread- CELTICS           0.123   0.875   0.870   -0.68  $100   SKIP q=0.770 ≤ 0.875
nba-tor-mil-2026-11-06-spread- BUCKS             0.103   0.900   0.890   -0.68  $100   SKIP q=0.808 ≤ 0.900
cfb-ucla-minnst-2026-11-07-1h- UNDER             0.153   0.845   0.830   -0.68  $100   SKIP q=0.727 ≤ 0.845
atp-ruud-alcaraz-2026-11-07    CARLOS ALCARAZ    0.173   0.805   0.820   -0.68  $100   SKIP q=0.672 ≤ 0.805
nhl-chi-car-2026-11-07-spread- HURRICANES        0.084   0.895   0.900   -0.68  $100   SKIP q=0.800 ≤ 0.895
lal-mad-bar-2026-11-08-spread- FC BARCELONA      0.133   0.865   0.860   -0.68  $100   SKIP q=0.755 ≤ 0.865
cbb-clvst-bowlgr-2026-11-09    BOWLING GREEN F   0.113   0.885   0.880   -0.68  $100   SKIP q=0.785 ≤ 0.885
```

- `sized@` = the repair's pre-image (the level Kelly actually banded); `paid@` = its post-image (the
  favourite the wallet bought, `|paid − wallet| ≤ 0.02` on all 13 — the wallet print is the only datum
  on neither of our frames, and it sits with `paid@`, never with `sized@`).
- `jdλ̂` is the λ̂ the journal recorded: **−0.68 / −0.74 on all 13**, i.e. the 0.0-0.2 band's premium,
  not the 0.8-1.01 band's **+0.2906** (the refit live at the time, `93a8b23`).
- `kelly@sized` funds **13/13 at $100** (the hard cap); `kelly@paid` returns **SKIP(no edge) on 13/13**.
  The verdict is robust to the calibration vintage: at today's λ̂ (+0.4128) **0/13** are funded, and at
  the 2026-11-01 λ̂ that the scorer actually read (+0.2906) **0/13** are funded. The sign of λ̂ in the
  0.8-1.01 band is what decides it, and it has been positive at every refit on record.
- Booked PnL on these 13: **+$3,013.97 before the repair, +$86.49 after.**

Full class (`d974287` preimage, 233 rows): C-200 **50 rows, +$3,965.37 → +$121.48 (δ −$3,843.89)**;
STANDARD 183 rows, δ −$1,499.04. Against the lane's pre-repair booked **+$8,913.40 → +$5,069.51**, the
frame carried **43.1% of C-200's entire booked profit**, and the 13 clips are **76%** of that
(−$2,927.48 of −$3,843.89).

---

## 3. The correction to the causal story — and why it matters

The card says the scorer "sized the sibling token while the book holds the token the outcome label
names". The second half is only true **after 2026-11-11**. Before the repair the book held the *same*
wrong price the scorer used:

| | before 2026-11-11 | after the repair |
|---|---|---|
| price Kelly banded | 0.133 (sibling) | 0.133 (unchanged — the journal is immutable) |
| price the book recorded | 0.13332 (sibling − credit) | **0.865** (favourite, wallet-corroborated) |
| `simulatedPositionSize` | $100 (longshot decision) | $100 (unchanged) |
| `FillIntent.intentPrice` | 0.135 | 0.135 (never moved) |

So this is not "a favourite sized at $100 by mistake". It is **one wrong price feeding four consumers,
then a repair that moved only one of them.** That distinction decides the remedy: re-pointing the price
source cannot fix a row whose price has already been corrected — the size and the verdicts are what
lag.

It also means the card's own sentence "the correct clip on it is $0" is a counterfactual about the
*favourite*, and it is the right counterfactual (13/13 SKIP) — but it prices the leg as if the model
had refused a bet it never evaluated, not as a size that should now be restated. Restating a settled
size changes book composition and every tier figure built on it; that is not on offer here.

---

## 4. Is the class still live? No — three independent checks

| check | population | result |
|---|---|---|
| intent mirrors the wallet's print (`|intent−(1−wallet)| ≤ 0.012` **and** `|intent−wallet| ≥ 0.05`) | post-`fbf9073`, regime, `FillIntent`-linked | **0 of 113** (111 agree within 6¢, 67 named-label legs exercised) |
| same test, pre-fix | 184 linked legs | 18 mirror (151 agree, 97 named) |
| booked-entry complement class (`|entry−wallet| ≥ 0.10` and `|entry−(1−wallet)| ≤ 0.06`) | whole regime | **0** — the repair's own claim, re-verified on today's DB |
| C-200 legs booked ≥ 0.80 post-fix | regime, `openedAt > fbf9073` | **0 legs.** Bands: 0.00-0.20 30 legs/$1,497/+$233.87 · 0.20-0.40 48/$615/+$10.12 · 0.40-0.60 1/$5/$0 · 0.60-0.80 34/$322/−$26.06 · **0.80-1.00 0** |

The last row is the structural point: post-fix the lane cannot reach the defect through this door,
because Kelly refuses the favourite band and the long-shot rails never see the leg.

**Three mirror counts exist and they are not in conflict** — quote the basis with any of them:
`fbf9073`'s own message says 87 regime legs *booked* at the complement (a different column, before the
repair); `drafts/c200-complement-frame-repair-20261112.md` says 32 instrument-era *intents* mirror over
802; this read says 18 of 184 linked legs inside the regime window with the ±0.012 test. Same class,
three windows, three tolerances.

---

## 5. What this does to the two downstream reads

**(a) The `$100`-tier clip-cap proposal is not caused by the frame — but its membership is 31%
frame-decided sizes.** Settled `$100` tier in the regime (42 legs today; 41 at the card's read — one
opened 2026-11-16 17:48, non-frame):

| group | legs | notional | booked PnL |
|---|---|---|---|
| frame-repaired (size decided at the sibling price) | 13 | $1,300 | **+$86.49** |
| never-repaired | 29 | $2,900 | **−$677.89** |
| total | 42 | $4,200 | −$591.40 |

The tier's loss is the never-repaired legs. The frame legs are the tier's **winners**. So capping the
tier would cap the winners as well and "fix" nothing — which independently confirms the clip-cap
card's own finding that a cap is a cost, not a repair. But any statement of the form *"the `$100` tier
is the only losing dollar tier"* must carry this split: a third of the tier's legs were sized by a
decision the model would not have taken at the price paid.

**(b) The band tables are clean; the size tables are not.** The repair moved `entryPrice`, so band
cohorts re-band correctly today. `simulatedPositionSize` was never touched, so on those 13 legs the
size is still the longshot decision. Band reads: safe. Size/tier/clip reads spanning pre-2026-11-09:
carry the split or exclude the 13.

---

## 6. The residual this card should hand on: 8 verdicts decided on the wrong token

Of the 13:

- **8 carry a `FillIntent` and are stamped `unfilled`** — every one of them because `resolveFill()`
  tested the intent level (0.06-0.195) against a market trading at 0.80-0.94. The resolver asked the
  right question about the wrong token. The wallet's own print at 0.83-0.94 in the same window shows
  the market *was* at our level, so "unreachable" is not established — these are **undecided**.
- **5 carry no intent** (3 stamped `filled`, 2 with no `fillStatus` at all) and none is zeroed, so all
  five book at p(fill)=1: **+$86.49 realised** on bets the model refuses at the price paid. That money
  is real only if the position was real, and nothing in the row proves that either.

Precedent and population: `drafts/c200-complement-frame-repair-20261112.md` measured **32** instrument-era
intents on the frame, **19 already linked and stamped `unfilled`**, **9 of which read REACHABLE when
re-framed** — and its recommendation (a frame guard in the resolver rather than a write-path fix) is
still unshipped. The 8 clips here are a subset of that class; re-adjudicating them is a **write**
(restating bookings), so it is Lane A and needs its own approval — I have not touched them.

---

## 7. Options — effort / measured cost / measured purchase

| # | option | effort | cost | purchase |
|---|---|---|---|---|
| **A** | **Close this card as already-shipped.** Record the writer answer, the pre-image evidence and the two consequences (§5, §6) on the card. Add the frame split as a standing line on the clip-cap card so the tier read carries it. | 0 | $0 | Truthful card; no re-litigation; the tier read stops being mis-attributed |
| B | Hand the 8 `unfilled` verdicts (+ t_1f579e82's 19/9) to the fill lane as a re-adjudication card: test the tape at `1 − intent` (positive-first precedence), re-stamp, restate. | 2-3h | $800 notional in scope; booked PnL moves **unknown direction** (5 of the 13 filled and won, so the honest prior is *more* positions, not fewer) | Decided verdicts instead of a hole; converts 0 into ± on 8 legs |
| C | Lane B repair: a **log-only** mirror detector at dispatch (`|intent−(1−wallet)| ≤ 0.012 && |intent−wallet| ≥ 0.05` → one `[FRAME] MIRROR` line + a `risksJson` tag). No admission change. | 45m | $0 (write-only) | Converts a silent regression class into a greppable line; a regression today would be invisible for weeks |
| D | Re-point the price source again (the card's own step 2) | 3h | $0 | **Already shipped, 0 measured effect — refused** |
| E | Cap the clip instead of the frame | 1h | −$69 to −$76 of measured PnL (sibling card) | Turns a wrong-side bet into a smaller wrong-side bet — refused |

Recommendation: **A now**, **B as its own card** (it is the only one with a number attached), **C** if
you want the guard — it is Lane B by the boundary test (it changes nothing the bot decides), and I have
deliberately not shipped it inside this proposal card.

---

## 8. Pre-registered refutation (so this cannot be re-argued from prose)

The verdict above is **"the defect is closed forward and the card's action is already shipped."** It is
refuted — and the card's step 2 becomes live again as written — if any of these appears on a re-read:

1. **≥ 1** post-`fbf9073` C-200 leg whose `FillIntent.intentPrice` mirrors the wallet's print
   (`|intent−(1−wallet)| ≤ 0.012` and `|intent−wallet| ≥ 0.05`), or
2. **≥ 1** post-`fbf9073` C-200 leg booked ≥ 0.80, or
3. any post-`fbf9073` named-outcome leg whose journal records a λ̂ belonging to a different band than
   its booked price.

Any one of the three means a live price source is still mixed and this document's §4 is wrong.
Re-read command: `npx tsx scripts/profit-c200-frame-census.ts` — §5 self-checks print PASS/FAIL on
exactly these three conditions (plus two population guards), so a regression shows up as a FAIL, not as
a number someone has to remember.

---

## 9. Revert

Nothing was applied, so there is nothing to revert: no RuleSet version, no DB row, no schema, no code
path. The only committed artifacts are this document and one read-only script; both are removable with
`git rm drafts/profit-c200-price-frame-sizing-20261116.md scripts/profit-c200-frame-census.ts`. The
script opens no write handle — deleting it cannot leave state behind.

---

## 10. Reproduce every figure here

```bash
cd ~/polymarket-copybot
npx tsx scripts/profit-c200-frame-census.ts          # all sections + 5 self-checks
npx tsx scripts/profit-c200-frame-census.ts --cash 7400   # pin the bankroll the Kelly arm uses
npx tsx scripts/profit-c200-frame-census.ts --calib fa1b459  # 2026-10-15 refit instead of 2026-11-01
```

Basis carried by every number in this document: population `botId='BANKROLL_200'`, `isDemo=0`,
`journal.ruleSetVersion ≥ 68`, `openedAt ≥ 2026-10-27`, membership in the frame class from
`data/repair-manifests/ledger-price-side-applied-20261111T123934.jsonl` (**not** from today's columns,
which no longer contain the class), Kelly at the **active** RuleSet v73 parameters
(fraction 0.5, maxBankrollPct 0.1, maxSizeUsd $100, minBetUsd $2, minEdgePct 0.02), λ̂ from
`data/premium-calibration.json` (2026-11-15) and from `git show 93a8b23:data/premium-calibration.json`
(2026-11-01) for the vintage check, cost basis = `simulatedPositionSize` (dollars at risk, not shares).

---

## 11. Explicitly NOT done

- No `apply-vNN.ts`, no RuleSet write (still v73), no `prisma/dev.db` write, no merge to main.
- No price-source change — it exists (`fbf9073`) and re-applying it would be a no-op.
- No re-stamp of the 8 `unfilled` verdicts, no restatement of any size or PnL, no link repair.
- No change to the clip-cap card's arithmetic — only the frame split added beside it.
- No new production log line (option C is proposed, not shipped).

---

## Overridable flags (one line each, with the number that moves)

1. **Do not close this card; authorise B now** — the 8 verdicts are the only open number. Cost: $800
   notional in scope, booked PnL direction unknown (prior: *more* positions, since 5 of 13 filled and won).
   Revert: the re-stamp is a ledger write with its own preimage, reversible the same way `d974287` was.
2. **Ship C (log-only guard) as Lane B** — 45m, $0, no admission change; revert is deleting one
   `log()` + one `risksJson` push. Say the word and I ship it with a re-read of the post-fix count
   before/after.
3. **Keep the `$100` tier read unchanged** — then the clip-cap proposal's "$100 is the only losing
   tier" stands as written, and its 13-of-42 frame-decided sizes go unstated. Cost: a reviewer
   re-derives the tier later and finds the split by hand.
