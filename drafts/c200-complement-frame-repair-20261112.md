# Complement-frame C-200 intent links — re-framed, re-priced, and the frame that is still in the ledger

**Lane A · PROPOSAL ONLY · 2026-11-12**
Board card: kanban `t_1f579e82` · parent `t_bb9577ae` (`drafts/c200-intent-link-repair-20261112`)
Population: the **18 pairs** `scripts/c200-link-missing.ts` refuses — $776.89 notional, **+$101.13** booked.

> **Nothing has been applied.** `prisma/dev.db` was opened read-only for every measurement below, no
> `scripts/apply-vNN.ts` was run, no RuleSet written (still **v72**), `data/c200-drawdown.json` untouched,
> nothing linked, nothing re-stamped, nothing restated. The apply path is §7 and it is yours.

---

## Verdict

**The frame in the title is real, the cause is not what the card assumes, and the first-pass estimate is
overstated by exactly the column the card warned about.**

1. **The intent is on the complement, and the entry is not.** These 18 legs read `entry ≈ 1 − intent`
   *because the 2026-11-11 price-side ledger repair moved their `entryPrice` onto the token frame and left
   `FillIntent.intentPrice` behind* (`data/repair-manifests/ledger-price-side-applied-20261111T123934.jsonl`,
   233 rows / 51 C-200). The wallet's own print — the one datum that is on neither of our frames — agrees with
   the **entry** (0.730 vs 0.735) and with **1 − intent** (0.735), so the intent is the wrong one. Re-framing
   the operand is therefore correct: `level = levelFor(1 − intent, "live")`.

2. **Root cause is already fixed in code, and that is measured, not assumed.** The intent inherited the
   pre-2026-11-09 positional read (`outcome === "NO" ? noPrice : yesPrice`) through
   `score-trades → paper.ts::recordFillIntent(intentPrice: params.entryPrice)`. Commit **`fbf9073`**
   (2026-11-09 15:15:16Z) replaced that read with `priceForOutcome(market, outcome)` in **all four** write
   paths (`monitor-trades.ts:177`, `score-trades.ts:480`, `update-pnl.ts`, `exit-recovery.ts`) and shipped a 104-line
   test. **Measured: 0 of the 91 intents dispatched at/after that commit sit on the complement frame.** The
   forward path is closed; what is missing is a **guard**, because the refusal lives only inside the link
   tool — the resolver will happily read whatever intent it finds.

3. **The card's estimate reproduces exactly and is book-window-only.** `14 of 18 unreachable, $78.25 on
   $508.90` ✓. Recomputing the tape at the re-framed level (the card's own step 2) turns **4 of those 14
   positive** — the 5-second L2 sampler missed a transient ask that the public tape recorded —
   so the honest frame-B verdict is **10 of 18 unreachable, $39.63 on $354.91**. A naive link+restate over
   the whole 219 would take **$101.13** out of the book; the correct figure is **$39.63**, a **$61.50**
   over-correction (2.6× on this bucket).

4. **The 18 are the small half of the class.** **32** instrument-era intents carry the complement frame when
   tested against the wallet's print. **19 are already linked and stamped `unfilled` — every one of them on
   the wrong token — and 9 of those 19 read REACHABLE when re-framed.** Two of the 9 sit inside
   `t_bb9577ae`'s 376-leg restate population, so the restate tool's own re-verify (which reads the same
   intent) would **agree with the wrong stamp and zero 2 real positions** (+$3.16).

**Recommendation — (c) both, composed as one release with the parent's repair:** restate the **10** legs at
the re-framed operand (−$39.63) · **exclude** the 2 frame-artifact legs from the parent's 376 and **re-stamp
the 9** · ship the **frame guard** (§6) instead of a "write-path fix", because there is nothing left to fix
in the write path. Net effect on the release: **384 legs, −$2,336.25**, DD **12.4%** open on the rebased peak.

---

## 1. Corrections to the card's own framing

| the card says | measured | why it matters |
|---|---|---|
| "`entry ≈ 1 − intent` … linking them would hand the resolver a level a dollar away" | true, and the reason is that the **entry was repaired** on 2026-11-11 and the intent was not | the re-frame is not a re-interpretation of history, it restores the token the lane meant to buy |
| "the level the lane was actually handed is `(1 − intent)`" | true **for the resolver operand**; the lane was handed `0.265` to the sidecar (wrong token), and the sidecar booked it 0.3¢ under that | the booked level was restated by the 11-11 repair, so `entry` and `1 − intent` now agree, and `levelFor(1 − intent)` is the level the release must test |
| "the artifact's tape column is INVALID at that frame" | true — `level 0.245`, computed at `intent − 0.02` on the booked frame | it was recomputed here (§2), and it **changes the answer** |
| "14 of 18 read unreachable, $78.25 on $508.90" | reproduces **exactly** | it is the book-window arm only; the tape arm moves 4 legs and $38.62 |
| "why does `FillIntent.intentPrice` land on the complement frame … it affects future legs as well" | it did; `fbf9073` closed it on 2026-11-09, and **0 of 91** post-fix intents carry it | so the second half of the card is a **guard**, not a fix |

## 2. The re-framed measurement (book **and** recomputed tape)

Three operands, because the difference between them is what the decision turns on:

| frame | level tested | what it represents |
|---|---|---|
| **A** | `levelFor(intent, "live")` = 0.260 | what a naive link hands the resolver — the **other token's** price |
| **B** | `levelFor(1 − intent, "live")` = 0.731 | the level the lane was handed, restored to the leg's own token |
| **C** | `entryPrice` = 0.735 | the booked level itself (post-repair, no maker credit) — a strictness check |

Two evidence arms. `book.minAsk` is level-independent, so the book arm is exactly what the resolver would
read. The tape arm was **recomputed** from the cached public tape (`data/c200-tape/<conditionId>.json`,
18/18 covered, fetched 2026-11-12 19:38–19:43 UTC) at **each frame's own level**, on the leg's own token
(the artifact's token was resolved by **outcome label** on all 18 — no proximity guess). Precedence is
**positive-first**: our sampler reads the best ask every ~5 s, so a book negative means "no ask at or below
the level in the instants sampled", while a tape print at or below it is a trade that happened there. A tape
positive therefore overrides a book negative; a tape negative never overrides a book positive.

```
frame  meaning                                        unfilled   notional      PnL   filled  unres
A  level = intent (a naive link)        [book]              18     $776.89   $101.13       0     0
B  level = 1 − intent (re-framed)       [book]              14     $508.90    $78.25       4     0   ← the card's estimate
B  level = 1 − intent (re-framed)       [book + tape]       10     $354.91    $39.63       8     0   ← the honest verdict
C  level = entryPrice (strict)          [book]              13     $503.93    $76.51       5     0
C  level = entryPrice (strict)          [book + tape]        9     $349.95    $37.89       9     0
```

Per-leg operands (all 18, in dispatch order; `bk` = `minAsk ≤ level`, `tp` = a post-dispatch print ≤ level):

| # | dispatched | market | outcome | intent | entry | lvlA | lvlB | minAsk | bkA | bkB | tpA | tpB | p60 | PnL |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 10-28 | atp-bertola-shapova | DENIS SHAPOVALOV | 0.265 | 0.735 | 0.260 | 0.731 | 0.740 | n | n | n | **Y** | 10 | +6.49 |
| 2 | 10-29 | atp-fery-musetti | LORENZO MUSETTI | 0.275 | 0.725 | 0.270 | 0.721 | 0.730 | n | n | n | n | 6 | −17.99 |
| 3 | 10-29 | atp-norrie-medvede | DANIIL MEDVEDEV | 0.175 | 0.825 | 0.173 | 0.821 | 0.810 | n | **Y** | ? | ? | 0 | +21.21 |
| 4 | 10-29 | atp-altmaie-lehecka | JIRI LEHECKA | 0.155 | 0.845 | 0.153 | 0.841 | 0.850 | n | n | n | **Y** | 19 | +18.34 |
| 5 | 10-30 | arg-cas-ros-total-3 | UNDER | 0.275 | 0.725 | 0.270 | 0.721 | 0.730 | n | n | ? | ? | 0 | +6.83 |
| 6 | 11-02 | atp-tabilo-jodar | RAFAEL JODAR | 0.215 | 0.785 | 0.210 | 0.781 | 0.790 | n | n | n | **Y** | 12 | +4.93 |
| 7 | 11-03 | ucl-mnu-rom-total-5 | UNDER | 0.115 | 0.885 | 0.113 | 0.881 | 0.890 | n | n | ? | ? | 0 | +12.99 |
| 8 | 11-03 | ucl-fcb-ast-first-h | UNDER | 0.315 | 0.685 | 0.310 | 0.681 | 0.690 | n | n | n | n | 1 | +8.28 |
| 9 | 11-03 | cfb-buf-miaoh-1h-mo | MIAMI (OH) | 0.330 | 0.670 | 0.325 | 0.666 | 0.680 | n | n | n | **Y** | 4 | +8.86 |
| 10 | 11-04 | nba-atl-was-total-2 | UNDER | 0.085 | 0.915 | 0.084 | 0.911 | 0.930 | n | n | ? | ? | 0 | +4.64 |
| 11 | 11-04 | cfb-ballst-umass-sp | UMASS | 0.265 | 0.735 | 0.260 | 0.731 | 0.740 | n | n | ? | ? | 0 | +6.49 |
| 12 | 11-05 | cfb-gast-applst | APPALACHIAN ST | 0.315 | 0.685 | 0.310 | 0.681 | 0.680 | n | **Y** | n | Y | 6 | −17.99 |
| 13 | 11-05 | col-ata-kai-first-h | UNDER | 0.260 | 0.740 | 0.255 | 0.736 | 0.740 | n | **Y** | ? | ? | 0 | +1.74 |
| 14 | 11-06 | wta-hontama-linette | MAGDA LINETTE | 0.315 | 0.685 | 0.310 | 0.681 | 0.690 | n | n | ? | ? | 0 | +8.28 |
| 15 | 11-06 | cfb-wvir-txtech | TEXAS TECH | 0.135 | 0.865 | 0.133 | 0.861 | 0.860 | n | **Y** | n | Y | 6 | +4.05 |
| 16 | 11-07 | cfb-ucla-minnst-1h | UNDER | 0.155 | 0.845 | 0.153 | 0.841 | 0.860 | n | n | ? | ? | 0 | +18.34 |
| 17 | 11-08 | lal-mad-bar-spread | FC BARCELONA | 0.135 | 0.865 | 0.133 | 0.861 | 0.850 | n | **Y** | n | Y | 3 | +15.61 |
| 18 | 11-09 | nba-mem-tor-spread | RAPTORS | 0.325 | 0.675 | 0.320 | 0.671 | 0.690 | n | n | ? | ? | 0 | −9.97 |

`?` = the tape has no post-dispatch print on that token (sparse market) — uninformative, never a negative.
`p60` = prints on the leg's own token within 60 min of dispatch.

**Why four legs move, and the spot-check that proves it** (leg 1, `DENIS SHAPOVALOV`): the L2 sampler's
lowest ask in the hour was **0.740**, and the tape shows two **0.730** prints on the same token
(t+2627 s × 37.04 and t+3492 s × 7.41, `outcome: "Denis Shapovalov"`). At the re-framed level 0.7313 that is
reachable — a resting bid at 0.7313 is better than a print at 0.730. Book-only calls it unreachable because
a transient ask between two 5-second samples is invisible. Reproduce the prints yourself:
`npx tsx scripts/c200-link-missing-spotcheck.ts --complement`.

**Quality of the negatives** (a negative the ledger acts on has to be earned):

| check | measured |
|---|---|
| window covers the decision moment | dispatch → coverage **median 0.3 min** (max 0.5); coverage **median 127 min** (min 120); **fragile 0 of 18** |
| legs without book coverage | **0** |
| gap `minAsk − levelB` on the unreachable set | median **+1.3%**, min **+0.5%**, max +2.8% |
| basis tally at frame B | book-window **14**, tape-positive **4**, unresolved **0** |
| marginal set (unreachable at the credited level, reachable at the booked entry) | **1 leg, $1.74** — a stricter test would *add* $1.74, it cannot rescue the bucket |
| tape provenance | cached public tape, 18/18 covered, fetched 2026-11-12 19:38–19:43 UTC |
| artifact tape column | **not quoted**: `level 0.245`, computed at `intent − 0.02` on the booked frame |

**Caveat that must travel:** a best ask at or below the level is **reachability**, not a fill (no queue
position, no size). The 8 legs that read reachable keep `p(fill)=1`; the bucket as a whole stays an upper
bound, just a smaller one.

## 3. Why the intent landed on the complement (root cause, with the exact insert points)

```
scripts/monitor-trades.ts:170,177     detectedPrice = t.price; then priceForOutcome(m, t.outcome)   ← post-fbf9073
scripts/score-trades.ts:454,480       currentPrice = t.detectedPrice; then priceForOutcome(...)     ← post-fbf9073
        pre-fix read                  outcome === "NO" ? m.noPrice : m.yesPrice  →  every NAMED outcome
                                      (team / player / UNDER) priced at the FIRST token = the complement
src/lib/paper.ts:205-220              POST /execute  { price: params.entryPrice }
src/lib/paper.ts:225-233              recordFillIntent({ ..., intentPrice: params.entryPrice })   ← inherits the frame
src/lib/fill-intent.ts:188            validation = finite & > 0 — NO frame check
rust-sidecar/src/main.rs:166-170      entry = intent − maker_credit  (so the BOOK was on the wrong token too)
src/lib/paper.ts:296-315              webhook writes PaperTrade.entryPrice = that number
src/lib/c200-fill-resolution.ts       resolveFill(): level = levelFor(intentPrice, mode) — NO frame awareness
scripts/c200-fill-resolve.ts:112      builds ResolutionLeg from the ARTIFACT's intentPrice
```

So the defect is one positional price read, inherited by two write sites and one booking path. Two later
events changed the picture:

- **2026-11-09, `fbf9073`** — `src/lib/outcome-price.ts::priceForOutcome()` replaces the positional read in
  `monitor-trades.ts`, `score-trades.ts`, `update-pnl.ts` and `exit-recovery.ts`, with
  `tests/outcome-price.test.ts` (104 lines). This is the same fix that moved the **entry**, and it is why the
  entry and the intent now disagree.
- **2026-11-11 18:39 UTC (12:39 CDT), `ledger-price-side-applied-20261111T123934`** — 233 legs (51 of them C-200) had
  `entryPrice` / `exitPrice` / `realizedPnl` restated onto the venue token price. That is what turns the
  historical frame error into the visible signature `entry ≈ 1 − intent`.

**Measured on the whole instrument era (802 intents, every one with a leg):**

| test | count | note |
|---|---|---|
| `entry ≈ 1 − intent` (the link tool's refusal test) | **18** | all keyed-unlinked; the card's population |
| `intent ≈ 1 − walletPrint` and not `≈ walletPrint` (frame test, independent of the entry) | **32** | 19 linked/stamped, 13 unlinked |
| — of those 32, dispatched at/after `fbf9073` | **0** of 91 | forward path closed |
| intents >5¢ away from the wallet print that are **not** a mirror | 22 | mid-vs-print divergence, a different (known) effect — do not fold it in |

## 4. The stamped population: 9 verdicts decided on the wrong token

A resolver stamp is a claim too. Every complement-frame leg was re-read at the re-framed level:

| | legs | realised PnL | notional |
|---|---|---|---|
| complement-frame intents in the era | 32 | — | — |
| — already linked, stamped `unfilled` | **19** | — | — |
| — of those, **REACHABLE when re-framed** | **9** | **+$3.16** | $309.92 |
| — of those 9, inside `t_bb9577ae`'s restate population (stamped-unfilled *and* still booking) | **2** | **+$3.16** | — |

The two that matter for the release:

| leg | market | intent | booked level | re-framed level | minAsk | re-framed verdict | PnL |
|---|---|---|---|---|---|---|---|
| `cmvpt59yy00021um2qgbujgb5` | atp-wawrink-lehecka-2026-10-27 | 0.175 | 0.173 | **0.821** | 0.830 | reachable (tape) | **+$21.15** |
| `cmvpztqy700081um23oeugqlg` | wta-joint-cirstea-2026-10-26 | 0.305 | 0.300 | **0.691** | 0.340 | reachable | **−$17.99** |

Both were stamped `unfilled` by a level ~$0.60 below the book that was actually in front of the leg. The
restate tool specified in `t_bb9577ae` §9 re-verifies "against the current artifact" — but it reads the same
complement-frame intent, so its re-verify **agrees** and zeroes them. **The gate is frame-blind; this is the
one change to that proposal's spec this card proposes.**

The other 7 flip to reachable with `PnL $0.00` — they move no money, but they are part of the same verdict
ledger (they are the difference between "65.2% of the instrument era was unreachable" and the truth), and
they are the population a later fill-rate read would quote.

## 5. What moves — every figure, before and after

Restating the bucket is `paper.ts`-class surgery: legs + bankroll + cash in one transaction, priced against
§6 of the parent proposal (**its peak-interaction table applies unchanged**).

**Frame B + tape (recommended scope: 10 legs, −$39.63)**

| surface | today | after |
|---|---|---|
| `PaperTrade.realizedPnl` (10 settled legs) | +$39.63 | **$0.00** |
| open legs in the bucket | 0 | 0 (nothing to mark) |
| `BotBankroll.realizedPnl` | $5,638.38 | **$5,598.75** |
| `BotBankroll.cashBalance` | $7,120.66 | **$7,081.03** |
| realised net worth (`principal 1,900 + realized`) | $7,538.38 | **$7,498.75** |
| equity-linked exposure cap (`1000 + 50%·(NW−1900)`) | $3,819.19 | **$3,799.38** |
| drawdown vs the **stored** watermark $11,068.58 | 31.9% TRIPPED | **32.3% TRIPPED** |
| drawdown in the **same release as the parent repair** (peak rebased on the corrected ledger, 384 legs) | — | **12.4% open** |
| ladder, trailing 7 settled days | +$190.03 | **+$171.64** (9.8% of the $250/day rung; 4 bucket legs, $18.39; rung unchanged) |
| `PnlSnapshot` marks on those legs | untouched | untouched — report-only surface, as in the parent |

**Frame B book-only (14 legs, −$78.25)** — priced for completeness, not recommended: `BotBankroll.realizedPnl`
$5,560.13 · cash $7,042.41 · NW $7,460.13 · DD 32.6% (stored) / **13.0%** in the release · release total
**$2,374.87 over 388 legs**.

**Release composition (why the leg count is not 376 + 10):**

```
parent's 376-leg class                −$2,299.78
  minus the 2 frame-artifact legs        +$3.16   (excluded from the zeroing; re-stamped instead)
  plus this bucket (frame B+tape)       −$39.63
  = 384 legs                           −$2,336.25     NW $5,202.13 · DD 12.4% open
```

Identity, so the restatement cannot be half-applied: today `principal 1,900 + realized 5,638.38 − open
notional 417.72 = cash 7,120.66` ✓ (measured). The three fields move together or the book stops reconciling.

## 6. Decision: (a) restate, (b) fix the write path, or (c) both

**Recommendation: (c), with (b) reduced to a guard because the fix already shipped.**

| | what it does | verdict |
|---|---|---|
| (a) restate the bucket | zeroes 10 settled legs proven unreachable at the re-framed level | **yes**, −$39.63, inside the parent's release |
| (b) "fix the intent-price write path" | — | **already done** (`fbf9073`): 0/91 post-fix intents on the complement frame. Re-doing it would be a no-op |
| (b′) **guard** | make a wrong-frame intent unable to drive a verdict silently | **yes** — this is the real second half |
| (c) both | (a) + (b′) + the 2-leg exclusion | **recommended** |

**The guard, specified rather than shipped** (Lane A — it changes verdicts, so it gets a before/after):

1. `src/lib/c200-fill-resolution.ts`: add an optional `bookedEntry?: number | null` to `ResolutionLeg`; when
   present and `|bookedEntry − (1 − intent)| ≤ 0.012` **and** `|bookedEntry − intent| ≥ 0.05`, set
   `intent = 1 − intent` and return `reframed: true` on the verdict. Both call sites already hold the leg
   (`scripts/c200-fill-resolve.ts` needs `entryPrice` added to its `select`; `c200-link-missing-impact.ts`
   has it). Before/after is §2's table: frame B is the operand, frame A disappears.
2. `scripts/c200-fill-resolve.ts`: print the count of `reframed` verdicts in its BASIS line, so a silently
   reframed population is visible instead of inferred.
3. `src/lib/fill-intent.ts::recordFillIntent`: one `console.warn` when the intent disagrees with the leg's
   `entryPrice` by >5¢ on a leg whose market has named outcomes — the write-time tripwire that would have
   caught this in October, with no new write and no behaviour change.
4. `scripts/c200-fill-resolve.ts` stamp path: `reframed` legs are stamped from the re-framed operand, and the
   link tool writes `PaperTrade.intentPrice = 1 − intent` when it links a complement pair (the column is
   write-only shadow; `FillIntent.intentPrice` stays as the record of what was actually handed over).

**Pre-registered refutation.** This proposal is wrong if any of the following holds, and each is cheap:

- **the 4 tape positives are on the wrong token** → the bucket reverts to the book-only 14/$78.25. Falsified
  here: the artifact resolved the token by **outcome label** on all 18, and the deciding prints carry
  `outcome: "Denis Shapovalov"` on the token the wallet itself printed 0.730 on.
- **the entry, not the intent, is the wrong frame** → the wallet's own print would sit near the intent.
  Falsified: wallet prints sit at `1 − intent ± $0.02` on all 18 and at `entry ± $0.01`.
- **coverage began after the decision** → 0 fragile verdicts (max lag 0.5 min, min window 120 min).
- **the 2 exclusions are not in the parent's population** → they are `fillStatus='unfilled'` **and** carry
  non-zero `realizedPnl`, which is exactly the 247-class predicate (`STEP 3c` prints the same 247).
- **a stricter test would rescue the bucket** → it would *add* $1.74 (1 marginal leg), not remove money.

Stop and re-measure if, at apply time, any of the 10 re-verifies as reachable at the re-framed level, or if
`SUM(leg.realizedPnl) ≠ BotBankroll.realizedPnl` after the write.

## 7. The apply path (dry run only — Lane A, nothing run)

No tool exists that performs this, and it should not be handed over pre-wired:

```
# 0. re-measure (read-only; the parity guard fails loudly if the two tools disagree about the book)
DATABASE_URL="file:./dev.db" npx tsx scripts/c200-link-missing-impact.ts          # §2, §4, §5
DATABASE_URL="file:./dev.db" npx tsx scripts/c200-link-missing-spotcheck.ts --complement   # §2 operands + prints

# 1. link the 18 with the RE-FRAMED price written to PaperTrade.intentPrice (NEW — not written yet)
#    refuses any leg whose frame signature is absent at apply time; dry run by default

# 2. re-stamp the 9 frame-artifact legs from the re-framed operand (NEW — the guard's first run does this;
#    they are already linked, so the resolver's next run picks them up once the guard ships)

# 3. restate the 10 at frame B+tape — the SAME script t_bb9577ae specifies (c200-link-restate.ts), with
#    the population extended by this bucket and the 2 exclusions subtracted from the 376

# 4. rebase the watermark once, on the corrected ledger  → 5,935.46 (unchanged by this bucket: the
#    2026-10-18 peak predates all 18 legs, so the bucket moves the numerator, not the peak)
```

**Revert:** the bucket restatement reverts by manifest row (per-row pre-image on `realizedPnl`, plus the
bankroll deltas), exactly as the parent's tool. The link step reverts by re-nulling
`FillIntent.paperTradeId`/`linkedAt` and `PaperTrade.intentPrice`; a re-stamp reverts by setting
`fillStatus`/`fillBasis` back to `NULL` on the 9 ids in §4.

## 8. What this does NOT fix

- **The 8 reachable legs keep `p(fill)=1`** — the bucket stays an upper bound. 4 of the 8 rest on a tape
  print, not a book window; a tape print is not queue position.
- **`FillIntent.intentPrice` stays wrong for the 32 historical rows.** It is write-only shadow and no PnL
  flows from it, but every future read of the intent column on those rows must apply the same frame test.
  Rewriting them is a separate, cheap Lane A migration (32 rows) that I have *not* proposed to bundle.
- **The mid-vs-print divergence** (22 intents >5¢ from the wallet print that are not mirror errors) is a
  different effect — adverse selection between detection and the wallet's fill — and is not touched here.
- **The duplicate-leg pair** (`atp-jacquet-machac-2026-11-02`, two legs on one key) is the known
  duplicate-accumulation class; it shows up here only because both legs are complement-frame.
- **Recurrence by a different route:** `recordFillIntent` still trusts its caller. The guard is a tripwire,
  not an invariant — a second positional read added anywhere would reproduce this class.
- **Historical `PnlSnapshot` marks** on the restated legs stay as they are (report surface), as in the parent.

## 9. Flags needing your word

1. **Restatement scope for this bucket** — (i) **10 legs, −$39.63** (tape-confirmed, recommended),
   (ii) 14 legs, −$78.25 (book-only; punishes 4 legs the tape proves reachable), (iii) none — ship only the
   guard and leave +$101.13 booking at `p(fill)=1`.
2. **The 2 exclusions** — ride in the parent's release (recommended; they are inside its 376) or a separate
   repair. They change the parent's total from −$2,299.78 to −$2,296.62.
3. **The guard's shape** — resolver-side frame normalisation (recommended: 1 module + 1 `select` + a BASIS
   line), or rewriting the 32 historical `intentPrice` rows, or both.

## 10. Reproduce

```bash
DATABASE_URL="file:./dev.db" npx tsx scripts/c200-link-missing-impact.ts                  # §2, §4, §5 (read-only)
DATABASE_URL="file:./dev.db" npx tsx scripts/c200-link-missing-spotcheck.ts --complement  # §2 operands + the prints
DATABASE_URL="file:./dev.db" npx tsx scripts/c200-link-missing.ts                         # the population + the refusal
git show --stat fbf9073                                                                   # the write-path fix
wc -l data/repair-manifests/ledger-price-side-applied-20261111T123934.jsonl               # the entry repair (233 rows)
```

The parity guard in `c200-link-missing-impact.ts` is intact: it still fails loudly if the 201-pair
population/sums drift from `c200-link-missing.ts` (measured today: 201 / $3,728.02 / $1,115.18 — exact).
