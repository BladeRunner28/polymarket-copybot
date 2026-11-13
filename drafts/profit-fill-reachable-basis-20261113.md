# LANE A PROPOSAL — book the reachable basis, stop crediting legs the market never came to

http://localhost:3013/drafts/profit-fill-reachable-basis-20261113

**Status: PROPOSAL ONLY. Nothing applied.** No `apply-v*.ts` run, no `prisma/dev.db` write, no
`fillStatus` stamped, no RuleSet row, no merge to main. Every number below is read-only and was
re-derived today, not copied from the card.

**Instruments**

| file | role | state |
|---|---|---|
| `scripts/profit-fill-tape.py` | the tape adjudicator — venue minute tape (`clob.polymarket.com/prices-history`), keyless, retroactive; 6/6 self-tests | committed 2026-11-13 (501180d) |
| `scripts/reachable-basis-preflight.py` | **new with this doc** — prices the three surfaces a verdict could be applied to, audits the negative claim, and dry-runs the write over every row | read-only, committed with this file |

```
python3 scripts/profit-fill-tape.py --since=2026-09-01     # measurement (writes nothing)
python3 scripts/reachable-basis-preflight.py --since=2026-09-01   # this doc's tables (writes nothing)
```

Cost basis throughout: `simulatedPositionSize` = **dollars at risk**, deduped to the first leg per
`bot|wallet|market|outcome`, price = the price we booked (INVERTED legs repriced to the wallet's
fill), CIs market-clustered (2,000 draws). Population: **2,274 finished non-demo legs, $32,065,
opened 2026-09-01..11-13** (1,568 C-200 / 706 STANDARD).

---

## 0. What is being asked, in three lines

1. **P1 — report the reachable basis (recommended, 2h).** Five surfaces print the reachable figure
   beside the booked one. No ledger write, no cap move, revert is one env var.
2. **P2 — restate the ledger (recommended after P1, 3h).** Stamp the verdict on 287 C-200 rows and
   sweep 231 rows the flip already stamped `unfilled`, re-book `realizedPnl`: **+$5,670.95 →
   −$209.57**. This also moves `BotBankroll.realizedPnl` to the same figure and the equity-linked
   exposure cap **$3,840.16 → $1,000.00**. P2b is the separate one-line decision it forces: reseed
   the drawdown peak.
3. **P3 — the dispatch rule — NOT yet.** The review's rec #2 has an **inverted sign** (it would
   suppress the lane's best cells) and the measured losing cell is 106/121 legs from *before* the
   2026-11-09 price-side fix (post-fix: 15 legs, CI spans zero). Ship the shadow counter, pre-register
   150 legs, do not gate live entry on it.

---

## 1. Reproduction — today, not yesterday

`profit-fill-tape.py --since=2026-09-01` re-ran today; every headline figure on the card reproduces
to the cent:

| figure | card | today |
|---|---|---|
| legs / notional adjudicated | 2,274 / $32,065 | **2,274 / $32,065** |
| C-200 booked | +$5,922.5 (+29.6%) | **+$5,922.54 (+29.6%), CI [+5.2,+56.1]** |
| C-200 24h-never class | 236 legs / $3,321 / +$5,709.8 | **236 / $3,321 / +$5,709.84 (+171.9%)** |
| C-200 restated (void all 24h-never) | +1.1% | **+$212.70 (+1.1%), CI [−14.8,+19.7]** |
| STANDARD booked → restated | +3.4% → +2.5% | **+$411.61 → +$306.02 (+2.5%)** |
| ledger hole (NULL + no 60m touch) | 562 rows / +$5,765.4 | **562 / $6,556 / +$5,765.4** |
| resolver agreement | 80.6% | **80.6% (408 stamped legs)** |

**Two audits of the negative claim**, run for this doc and both clean:

- **Horizon adequacy:** 0 of the 739 untouched-at-60m legs have an incomplete 24h window. Every
  "never in 24h" verdict is a full 24 hours of tape, not "not yet".
- **Post-settlement contamination:** 0 of the 495 legs that touch inside 24h touch *after* they
  settled. That matters because the horizon is real: median entry→settle is **0.9 days** and **10.9%**
  of finished legs settle *inside* 24h, so a lost market printing 0 at resolution could have
  registered as a touch — booking a loss we never took. It does not: in every one of the 495, the
  first touch (if any) precedes settlement. The negative class therefore contains no leg that was
  touched only by its own resolution print.

The remaining sampling error is the 1-minute re-check of the negative class: **6 of 80 legs touch at
1-minute fidelity (7.5% reverse rate)** — haircut applied, the phantom is ≈226 legs / ≈$5,280, still
~89% of the lane's booked profit. The refutation bar was ≥20%.

## 2. The hole, in code

`src/lib/paper.ts:47` is the whole booking rule:

```ts
export function bookedPnl(leg: { fillStatus?: string | null }, pnl: number): number {
  if (!fillAwareBookingEnabled()) return pnl;
  if (leg.fillStatus === "unfilled") return 0;   // <-- only this
  return pnl;                                    // NULL books at p(fill) = 1
}
```

Three call sites use it (`paper.ts:360` mark, `:381` settle, `:493` close). A leg whose
`fillStatus` is `NULL` (`prisma/schema.prisma:215`) books exactly as if it had filled, and the
resolver only ever stamps rows it can *reach*: `src/lib/c200-fill-resolution.ts` needs
`FillIntent` evidence from a rolling window, so 562 rows carrying **+$5,765.4** were never stampable.
The venue tape settles what the artifact could not.

There is a **second, smaller hole in the same contract**: **247 C-200 rows are already stamped
`unfilled` and still carry +$828.66** (245 of them settled before the flip existed; **2 rows /
+$17.60 settled after it**). The stamp landed *after* the leg settled, so `bookedPnl()` never re-ran
on them. A restatement job must sweep these too or it will "fix" the phantom and leave $829 of the
same class on the books.

## 3. Which basis, exactly — six candidates priced

The word "reachable" hides a choice. Each row below is the same 1,568 C-200 legs, $20,012 at risk,
with only the void rule changed. `realizedPnl` is used as stored, so the flip's existing zeroing is
already inside every row.

| basis | void rule | PnL | ROI | CI95 |
|---|---|---|---|---|
| booked | nothing | +$5,922.54 | +29.6% | [+5.2,+56.1] |
| resolver-filled only | keep only `fillStatus='filled'` | −$63.36 | −0.3% | [−5.5,+6.4] |
| tape 60m, NULL only | void NULL + untouched **60m** | +$401.64 | +2.0% | [−10.2,+15.5] |
| card literal | void NULL + untouched **24h** | +$1,241.12 | +6.2% | [−10.6,+24.7] |
| **full contract (recommended)** | the card rule **+ zero every `unfilled` row** | **+$440.03** | **+2.2%** | **[−13.3,+20.3]** |
| void all 24h-never | void the 236 whatever their stamp | +$212.70 | +1.1% | [−14.8,+19.7] |

**Why the full contract and not the card's literal rule.** The card's rule leaves **+$828.66 on rows
the resolver itself proved unfilled** — the flip's own contract, unenforced. Adding that sweep is the
same decision, not a new one, and it is the only variant whose rule is one sentence: *a leg books
only if some evidence says its level was reachable* — the resolver's where the resolver has a stamp,
the venue tape where it does not.

**Why not the stronger version** (void all 236 including `filled`-stamped rows): it overrules the
resolver's *positive* evidence (a best-ask at or below our level in our own L2 window) with tape
*silence*, which is the weaker evidence. That is 3 legs / +$170.40 — the difference between +2.2%
and +1.1%. Cheap to take later if the operator prefers the lower number; it is not taken here because
a negative claim should not outvote a positive one at n=3.

Note both directions of conservatism are built in and they cut *against* the proposal:
`near_miss` legs (min price within 1c **above** our bid — not reachable) stay booked, and that class
is **−$182.80 on 340 legs**; the 105 complement-frame rows ($413.63, all time) are refused rather than
adjudicated.

## 4. What the write does — the dry run, over every row

The tables above are the review's deduped *measurement* population. A write touches **rows**, and the
phantom is not confined to the September-onward window, so the sweep was dry-run over **all 2,824**
finished C-200 rows (each row adjudicated at its own dispatch minute):

```
finished C-200 rows, all time              2,824      booked +$5,670.95   ← equals BotBankroll.realizedPnl
refused — no conditionId                       0
refused — complement-frame (sibling token)   105     $413.63   (not adjudicated: a verdict would guess)
STAMP   NULL + never-24h                  287 rows   $3,666.50   removes +$5,047.46
SWEEP   'unfilled' + PnL still booked     231 rows   $2,217.03   removes   +$833.06
KEEP    'filled'-stamped + never            1 row               leaves        $0.00
                                         ─────────────────────────────────────────────
                                         removed  +$5,880.52  →  after  −$209.57
```

Cross-checks that make this quotable: the row sum **is** `BotBankroll.realizedPnl` to the cent
(+$5,670.95), so the dry run starts from the ledger's own number; and the since-2026-09-01 bracket
(the measurement window, §3) reads +$5,712.22 → −$15.19 with +$5,727.41 removed. The delta between the
two brackets is the pre-September book: +$153.11 more phantom removed, −$41.27 lower booked
(dedupe/duplicate effects account for a further $455.22 on the measurement population).

**README-level consequence, the number the operator is really approving:** the ledger's C-200 profit
is not reduced, it is **deleted** — the lane ends at **−$209.57 lifetime** — and every downstream
figure that reads `BotBankroll.realizedPnl` moves with it:

| | today | after P2 |
|---|---|---|
| `BotBankroll.realizedPnl` (BANKROLL_200) | +$5,670.95 | **−$209.57** |
| net worth, principal + realized | $7,570.95 | $1,690.43 |
| effective exposure cap (`exposure-cap.ts:26`, base $1,000 + 50% above principal) | **$3,840.16** | **$1,000.00** |
| open notional $377.92 as a share of cap | 9.8% | **37.8%** |
| realized-basis drawdown (live: `data/c200-drawdown.json`, peak $11,069) | **31.6% — TRIPPED** | **84.7% — TRIPPED**, unless P2b reseeds the peak |

No halt: $377.92 of open notional against a $1,000 floor still clears. But the lane that has been
cycling **$540–1,170/day of notional (median $632) for the last week** goes from 10x headroom to
2.6x. That is why P1 and P2 are priced separately and why P2 needs its own yes.

`c200-drawdown.json`'s own rule says a peak reset "is a deliberate act — record note +
basisDeclaredAt with it". **P2b** is that act: after the restatement the recorded peak ($11,069) is a
high-water mark set by profit that never existed, so leaving it in place measures the lane against a
phantom. It must be recomputed from the recorded net-worth series in the same commit, not from the
restated `realizedPnl` sum (the peak embeds capital injections — all-time realized is $5,670.95 while
the peak reads $11,069).

## 5. The ladder: this changes nothing today, and that is a finding

Goal Policy v2 grades the **settled trailing-7-day sum** (local days, `query_bankroll.js`, window
2026-11-06..11-12):

| | booked | reachable |
|---|---|---|
| settled 7d sum | +$96.78 | **+$113.05** |
| cheapest rung ($250/day → needs $1,750) | fails | fails |

The restatement moves the ladder **up $16.27**, because the one day in the window with a never-class
leg (2026-11-12) happened to be a loser. No rung clears either way, so this proposal cannot be
accused of buying an advance — and, equally, it does not cost one. The phantom profit that matters
is **September–October vintage**, outside any live ladder window; it is inside the lifetime figure,
the exposure cap and the drawdown peak.

## 6. The three arms

### P1 — report the reachable basis (Lane A, 2h, recommended)

- **Hypothesis:** the lane's published record is 96% composed of legs whose price never came within
  1c of our bid in 24h, so its real record is the reachable cohort (≈ +2.2%), and printing that
  beside the booked number costs nothing and deletes nothing.
- **Measurement:** §3 table; §1 reproduction; the write path in §4 for what *would* change if the
  operator later takes P2.
- **Design:** one helper, `src/lib/reach-basis.ts`:

  ```ts
  /** Reachable-basis credit for one leg. `booked` reproduces today byte-for-byte. */
  export function reachCredit(v: {voided?: boolean} | undefined, pnl: number | null): number {
    return v?.voided ? 0 : (pnl ?? 0);
  }
  /** Default `reachable`; REACHABLE_BASIS=booked restores today exactly. */
  export function reachBasis(): "booked" | "reachable" { … }
  ```

  plus a verdict store (`FillTapeVerdict`: tradeId unique, tokenId, `minP60`, `minP24h`, verdict,
  touchLagS, checkedAt) written by a nightly job that re-adjudicates **finished legs whose window has
  closed**, and read by:

  | # | surface | change |
  |---|---|---|
  | 1 | `query_bankroll.js` (`findMany` ≈L113, gate ≈L143-160, print L323-340) | join the verdict map; compute the series twice; the **gate reads the reachable arm**; print both, labelled |
  | 2 | `src/app/page.tsx` (C-200 card L126, series L312/L372) | reachable sub-line beside the booked figure; the rung derives from the reachable sum |
  | 3 | `src/app/analytics/page.tsx` (C-200 series L103) | second line (booked dashed, reachable solid) |
  | 4 | `src/lib/report.ts` (EOD C-200 total L393, `cmpPayoff`) | both arms printed; payoff companions on the booked arm with the reachable one beside |
  | 5 | `~/.hermes/cron/jobs.json` — `copybot-c200-daily-report`, `copybot-tuning-review-daily` | the standing basis line gains one clause: *"the lane is judged on the reachable basis; the booked sum prints beside it and is never the basis"* (2 occurrences) |

- **Expected effect:** $0 paper. Removes **≈$5,483** of phantom from the measured window
  (+$5,922.54 → +$440.03) and takes every published lifetime figure to the same basis the ledger dry
  run reaches (−$209.57), without deleting a stored number.
- **Refutation:** if the verdict store's coverage falls below 95% of finished C-200 legs in any
  30-day window, or if a 1-minute re-check of the void class shows ≥20% touch, withdraw P1.
- **Revert:** `REACHABLE_BASIS=booked` (code default is the approved basis; the repo's convention,
  because nothing loads `.env` — see `fillAwareBookingEnabled`).

### P2 — restate the ledger (Lane A, 3h, recommended after P1)

- **Hypothesis:** the phantom is not a reporting problem, it is a booking problem: the exposure cap,
  the drawdown basis and `BotBankroll` all inherit `realizedPnl`, so the lane is risk-managed against
  profit it never earned.
- **Measurement:** §4 dry run — 287 stamps + 231 sweeps = **+$5,880.52** removed, cap $3,840 → $1,000,
  open notional 9.8% → 37.8% of cap.
- **Design:** one job (`scripts/tape-reach-rebook.ts`), idempotent, three phases, each printing its
  counts and refusing to run if a guard trips:
  1. adjudicate every finished C-200 leg whose window closed, **refusing** complement-frame rows and
     rows with no `conditionId` (105 + 0 all time);
  2. stamp `fillStatus='unfilled'` where NULL + never-24h, and re-book `realizedPnl = 0` on those and
     on `unfilled` rows that still carry PnL — writing a `RebookLedger` row per leg with the previous
     value;
  3. update `BotBankroll.realizedPnl` to the new row sum and print the cap before/after; the operator
     then runs `reconcile-bankroll --apply` (its identity is `principal + realized − open = cash`, so
     cash moves with it).
- **Refutation:** if ≥20% of the void class touches on a 1-minute re-check; or if the first 150
  forward C-200 legs opened after the restatement earn ≤ 0 while a matched booked-basis shadow holds
  positive → the void class was real exposure and the restatement is withdrawn.
- **Revert:** `RebookLedger` makes it exact — re-apply each stored previous value, reset
  `BotBankroll.realizedPnl`, re-run `reconcile-bankroll --apply`. No `git revert` needed, no history
  rewrite.
- **Do not bundle P1 and P2.** P1 is reversible in one env var and moves nothing but text; P2 deletes
  $5,881 of recorded profit and moves two risk rails. They fail differently.

### P2b — reseed the drawdown peak (Lane A, 30min, one-line decision)

Without it, P2 leaves the lane measured at **84.7% drawdown against an $11,069 peak** that the
restatement just proved never existed. With it, the peak is recomputed from the recorded net-worth
series and the note/basisDeclaredAt are stamped into `data/c200-drawdown.json` as that file requires.
This is not optional cleanup: it is the difference between a lane that is frozen forever and one whose
rail measures something real. Recommend: **reseed in the same commit as P2.**

### P3 — the dispatch rule: correction first, gate later

The review's rec #2 reads *"if the current market price is **above** our intended entry by ≥0.5c, do
not dispatch"*. **That is inverted.** The measured losing cell is the opposite one — our booked price
**at or above** the dispatch market:

| cell (d = booked price − market price at dispatch) | legs | $ | booked PnL | ROI | CI95 |
|---|---|---|---|---|---|
| d ≥ +0.5c (**the losing cell**) | 121 | $1,571 | **−$677.43** | −43.1% | **[−67.9,−7.9]** |
| d ≥ 0 (at or above) | 208 | $3,848 | −$516.87 | −13.4% | [−33.6,+9.2] |
| \|d\| < 0.5c | 357 | $7,165 | −$124.25 | −1.7% | [−20.3,+20.5] |
| d < 0 (deep bids) | 1,090 | $11,277 | +$6,724.22 | +59.6% | [+20.7,+103.5] |

Implemented as written, the rule would have suppressed the **1,090 deep-bid legs earning +$6,724**
and kept the −$677 cell. Two further facts stop it shipping today:

1. **It is mostly a pre-fix artifact.** 106 of the 121 legs opened before 2026-11-09 (the
   price-side-inversion fix): −$629.71, CI [−75.9,−8.8]. On/after 2026-11-09: **15 legs, −$47.72,
   CI [−75.2,+93.3]** — direction intact, significance gone.
2. **The live path cannot see the condition it names.** At dispatch `scripts/score-trades.ts` passes
   `entryPrice = currentPrice` (L454/L481/L1246) and the sidecar books `max(0.01, price − credit)`, so
   a fresh read makes d ≈ −credit by construction. The measured cell is legs where the detection price
   was stale or the market reverted within the minute — a **freshness** defect, not a price-level one.

So: **P3 is not a live gate today.** The honest form is a write-only shadow at the existing
`currentPrice` site (L1060 already does a per-leg price comparison for the high-entry cap, so the hook
costs ~20 lines), journaling `dispatch_gap_cents` on every C-200 leg, with the pre-registered bar:
**150 post-restatement legs in the d ≥ +0.5c cell with a market-clustered CI excluding zero and
non-negative PnL** → the rule is then proposed as a gate. That instrument is Lane B and does not need
an approval; the gate it would justify does.

## 7. What this proposal does NOT do

- No RuleSet field, no `apply-v*.ts`, no rule/threshold/size change, no ladder re-date, no clip change.
- **P2 is scoped to C-200.** STANDARD has no resolver stamps at all (0 of 706 legs in this window), so
  its reachable read is 8 never-legs / +$105.59 under the same rule — priced, and left for the
  `standard-fill-stamp` surface rather than bundled here. Applying a tape verdict to a lane the flip
  has never touched is a different decision with a different revert.
- No claim that the lane is bad — it claims the lane's **number** is: `+29.6% → +2.2%` on the same
  legs, same exits, same dollars at risk.
- Does not re-litigate: gate tuning (exhausted), the 168h exit read (closed at 107 settled legs), the
  pending clip cap (drawdown case stands), the ML lane, `profit-band-clip-rebalance`.
- The card `profit-fill-class-basis`'s −46.7% filled-class figure is **withdrawn** by the parent
  review (515 tape-filled legs read −7.7%, CI [−29.3,+17.6]); that correction stands and is not
  re-proposed here.

## 8. What could still be wrong

| risk | size | already checked |
|---|---|---|
| 1-minute sampling misses intra-minute troughs | 7.5% reverse rate on 80 legs | yes — refutation bar was ≥20% |
| post-resolution prints counted as touches | 0 legs | yes |
| incomplete 24h windows | 0 legs | yes |
| token map (team-name / over-under labels) | 2 legs by price proximity; label legs touch 50.6% | yes |
| complement-frame legs adjudicated on the wrong token | 105 rows refused, $413.63 (all time) | yes |
| `near_miss` (within 1c above bid) treated as booked | 340 legs, **−$182.80** — kept booked, i.e. conservative | yes |
| the ledger population ≠ the measurement population | reconciled, §4 | yes |

## 9. Overridable flags — one line each

1. **Basis = full contract** (+2.2% measured; −$209.57 on the ledger) instead of the card's literal
   NULL-only rule (+6.2% / +$1,241.12). *Why:* it enforces the flip's own contract on 231 rows
   carrying +$833. **Override to NULL-only** if you want the smallest possible write; the flags below
   are unaffected.
2. **P1 before P2** — read path first, ledger later. *Why:* P1 is reversible in one env var and moves
   no risk rail; P2 deletes $5,881 of recorded profit and drops the cap $3,840 → $1,000. **Override to
   both-at-once** if you'd rather see the honest number in the ledger today.
3. **P2b reseed = yes**, in the same commit. *Why:* without it the lane sits at 84.7% drawdown against
   a peak the same commit just disproved. **Override to leave the peak** if you want the gate to keep
   reading the pre-restatement high-water mark.
4. **P3 = shadow only, not a gate.** *Why:* the review's rule was sign-inverted and 106/121 of its
   legs predate the 2026-11-09 fix. **Override to gate now** (corrected sign: skip when
   `booked ≥ dispatch market + 0.5c`) — it would have removed −$677 here and, on this history, cost
   nothing; the reason not to is the 15-leg post-fix sample.

---

**IF YOU WEREN'T HERE:** C-200's `+29.6%` is `+2.2%` once you ask whether the market ever came to our
price; the ledger has $5,881 of it left to delete, the exposure cap believes $2,840 of it, and the
drawdown gate is already tripped against a peak built from it. P1 makes the report honest tonight; P2
makes the risk system honest, and costs a $1,000 cap plus a re-seeded peak to do it.
