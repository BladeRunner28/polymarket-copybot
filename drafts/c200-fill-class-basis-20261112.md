# C-200 fill-class basis — Lane A PROPOSAL (nothing applied)

http://localhost:3013/drafts/c200-fill-class-basis-20261112

**Status: PROPOSAL ONLY.** No RuleSet row, no `apply-v*.ts` run, no `prisma/dev.db` write, no merge.
Every number below is read-only and reproducible from the two commands in §1. The apply step is the
operator's, after he reads this — §9 carries the exact commands and the one-line revert.

Card: `profit-fill-class-basis` (roadmap, Scheduled) · approvals id `apr-profit-fill-class-basis` ·
lane A · proposed 2026-11-12 by the profit review (`drafts/profit-recs-20261112.md`).

---

## 0. The decision, in one paragraph

The fill-aware booking flip (2026-10-28) split every C-200 leg into **filled** (proven a position),
**unfilled** (proven not one — already books $0) and **unresolved** (no evidence either way — books at
p(fill)=1, the optimistic number). The lane's headline, its ladder and every published C-200 figure
sum all three. Split apart on today's book, **the only class anyone can prove is −$94.64 all-time and
−$515.50 post-flip (−46.7%, clustered CI [−70.9, −14.4])**, while the class nobody can adjudicate
carries **+$4,897.92 of the +$5,631.94 the lane reports**. The proposal: **the ladder advance gate and
the C-200 record line read the proven-fill class, and the report prints the unresolved credit beside it
as a labelled, unverified arm** — so a rung is never cleared on profit that may not exist. It moves
**no advance today** (all three credit arms fail rung 1 by more than $1,900) and **no risk parameter at
all**: the ledger, the exposure cap and the drawdown gate are untouched (§4 prices what touching them
would cost, and it is why they are out of scope).

---

## 1. Reproduction — what I re-ran

```
python3 scripts/profit-fill-cohort.py          # the card's instrument (exists, committed, 4/4 self-tests)
python3 scripts/c200-ladder-fill-basis.py      # NEW: the ladder read split by class (§2-§3)
```

Both are read-only (`sqlite3 …?mode=ro`); neither writes a row. The new instrument is in the working
tree at `scripts/c200-ladder-fill-basis.py` and is **not committed** — this session is proposal-only on
a repo that a nightly `git add -A` sweeps, so the commit belongs in the same change as the patch if the
operator takes it.

**The card's figures reproduce, with one day of drift** (more legs finished between the card's 07:57
read and mine):

| figure (deduped, cost = `simulatedPositionSize`) | card 07:57 | this read | verdict |
|---|---|---|---|
| post-flip C-200 legs / notional / PnL | 271 / $6,888 / −$49.70 | **272 / $6,988 / −$65.90** | drift, same sign |
| FILLED | 60 / $1,103 / **−$515.50 (−46.7%, CI −70.9..−14.4)** | **identical** | reproduces exactly |
| UNRESOLVED | 79 / $2,604 / +$465.90 (+17.9%) | **80 / $2,704 / +$449.60 (+16.6%, CI −28.9..+75.4)** | drift |
| filled − unresolved | −64.6pp CI [−132.1, −8.0] | **−63.3pp CI [−128.4, −6.9]** | reproduces, CI still excludes 0 |
| naturally resolved only | 225 legs +$467.10; filled 51 −$401.70; unresolved 62 +$868.80 | **identical** | reproduces exactly |
| filled, ex-top-1/3/5 | −52.5 / −61.4 / −69.6% | **identical** | reproduces exactly |
| filled by clip ≤$10 / $10–20 / >$40 | −15.2 / −28.5 / −90.4% | **identical** | reproduces exactly |
| the mirror (no-fill at own intent) | unfilled −2.3% (−12.3% at +2c) | **unfilled −$50.30 (−2.3%), filled −48.2%** | reproduces |
| self-test | 4/4 | **4/4 PASS** | — |

So: the filled class is unchanged and the drift is entirely new unresolved legs. Nothing in the card
needed correcting.

---

## 2. The measurement the card did not have: the ladder read, split

`query_bankroll.js` sums `PaperTrade.realizedPnl` for BANKROLL_200 over 14 local days and judges an
advance on the trailing **7 SETTLED** days (GOAL POLICY v2: sum ≥ target × 7; rung 1 = **$1,750**).
Nothing in that path knows about `fillStatus`. Split three ways on the same rows the report reads
(raw rows, `closedAt ?? resolvedAt`, window 2026-10-30..11-12, 264 rows):

```
S2. THE ADVANCE GATE, EACH BASIS (settled 7d SUM >= target x 7)
  basis                                             settled 7d   need   rung     T+0 7d  legs
  A. as the report reads it (filled + unresolved)      -203.47   1750   Phase 1   +55.10   160   fail (-12%)
  B. unresolved credited at ZERO                       -286.42   1750   Phase 1  -358.70   160   fail (-16%)
  C. proven fills only                                 -286.42   1750   Phase 1  -358.70   160   fail (-16%)
     window 2026-11-03 .. 2026-11-09
```

Read it as three facts:

1. **The gate fails on every basis, by more than $1,900.** The basis change authorises no advance
   today and would not have authorised one at any point in the post-flip era (best T+0 window: +$55.10).
   This is a basis change, not a promotion.
2. **The unresolved class is worth $82.95 in the settled window and $413.80 in the T+0 window** — the
   gap between what the lane reports and what it can prove. Small now; the reason it matters is not its
   size today but that it is the *only* sign-carrier (below).
3. **The dashboard's own ladder reads the T+0 window** (`src/app/page.tsx:317-338`), so today the
   dashboard prints a $55.10 gate sum while the 18:00 report prints −$203.47 on the settled window.
   That divergence is pre-existing and documented in both files; it is a second reason the three copies
   must be changed in one commit.

Deduped cross-check on the same window (the published surfaces are raw; this only proves the duplicates
are not carrying the delta): booked −$203.47 / filled-only −$286.42, identical to the raw read.

### 2.1 The three credit arms, so the choice can be read as material-or-not

```
observed fill share among STAMPED post-flip legs: 31.0% by leg, 25.7% by notional
  settled window 2026-11-03..11-09:  (i) fills-only -286.42  (ii) EV -265.11  (iii) booked -203.47   need $1,750
  post-flip all-time (raw rows):     (i) fills-only -505.94  (ii) EV -390.46  (iii) booked  -56.36
```

- **(i) fills-only** — unresolved treated as never filled. The lower bound.
- **(ii) EV** — unresolved credited at the observed notional fill share (25.7%). An **estimate**, not a
  measurement, so it is printed for scale and **never used as a gate basis**.
- **(iii) booked** — today's number; the upper bound.

The choice is worth **$83** on the settled window and **$450** post-flip all-time **today** — but it is
not cosmetic over the lane's history (§2.2), and it is not a performance lever at all: it is a
**truthfulness** lever on the one number that decides whether this lane graduates.

### 2.2 It is not cosmetic: the booked arm has already cleared a rung; the provable one never has

Rolling 7-day windows over the whole C-200 history (107 windows, by close day, 2026-07-23..11-12):

```
    booked     best window 2026-09-16..2026-09-22  +2,661.00   windows clearing $1,750: 8
    fills-only best window 2026-10-13..2026-10-19    +525.28   windows clearing $1,750: 0
  stamp coverage pre-flip  378 of 2542 rows (14.9%)   post-flip 197 of 277 rows (71.1%)
```

**Read this with its caveat, because it is the strongest number in the file and the easiest to misread.**
The eight clearing windows are all pre-flip, where only **14.9%** of rows carry a fill verdict — so the
fills-only arm there is a *coverage-limited lower bound*, not proof the lane never earned $1,750. What it
does prove is that the basis is decisive: on the basis the ladder reads today, this lane has cleared the
cheapest rung eight times; on the basis of what anyone can verify about the positions it held, never
once — and the post-flip era, where coverage is 71.1%, is the era the gate will be judged in.

---

## 3. Why the gate takes the strictest arm

Because the class it would otherwise credit is not merely noisy — it is **undecidable forever, and it
is the only thing holding the lane's sign up.**

- **Coverage:** 575 of 2,819 finished C-200 rows carry a fill verdict (**20.4%**); 2,244 are unresolved.
- **Recoverability:** the resolver reads a rolling print-through artifact (802 intents, all stamped).
  A dry run of `scripts/c200-fill-resolve.ts` (dry by default) reports `resolution coverage 0.0% of 1`;
  2,247 legs are invisible to it and the venue's book history is not queryable after the fact. There is
  no backlog to work off.
- **All-time split of the published number** (raw rows — the population the overview card, the EOD and
  the analytics page sum):

| class | rows | booked PnL |
|---|---|---|
| filled | 192 | **−$94.64** |
| unfilled | 383 | +$828.66 *(the pre-flip phantom the flip removed)* |
| unresolved | 2,244 | **+$4,897.92** |
| **total** | **2,819** | **+$5,631.94** |

`BotBankroll.realizedPnl` is **+$5,631.94 — the row sum to the cent** (gap −$0.00), so the ledger and the
published card agree, and both are 87% unresolved profit.

- **Both bounds are negative**, so the class decides *how negative*, never *whether*:

```
post-flip C-200: 277 finished rows, $7,070 intent notional
  booked (unresolved at p(fill)=1)        -56.36   = -0.80% of intent notional
  proven fills only (unresolved at 0)   -533.51   = -7.55% of intent notional  (-47.6% of the $1,121 at risk)
```

That is the sentence the gate has to be built on: **a lane whose whole honest range is negative must not
be allowed to clear a rung on the optimistic end of it.** The counter-risk — that fills are adversarially
selected, so a fills-only basis is biased *down* — is real and is exactly why the report prints the
booked arm beside the gate instead of deleting it (see the mirror: the intents we did **not** get would
have paid −2.3% at their own price, the ones we got paid −48.2%). Both classes lose; the fill decides
by how much.

---

## 4. What "zero exposure for sizing" must NOT mean — the second channel, priced

The card's wording ("treat unfilled + unresolved as zero exposure for sizing") has a second reading, and
it is dangerous. `score-trades.ts:119-121` builds netWorth as `principal + BotBankroll.realizedPnl +
Σ open unrealized`; the **realized-basis drawdown gate** (`rules.maxDrawdownPct = 0.2`, `ddBasis =
realized`) and the **equity-linked exposure cap** (`$1,000 + 50% × max(0, netWorth − principal)`) both
read it. Measured:

```
BotBankroll: principal $1,900.00  realizedPnl $5,631.94  cash $7,104.30, open unrealized $50.56
  netWorth today                    $7,582.50  -> cap $3,841   realized-basis DD 32.0%  (gate 20%)
  netWorth with unresolved removed  $2,684.58  -> cap $1,392   realized-basis DD 76.2%
  => cap difference $2,449; DD 32.0% -> 76.2%
```

Excluding the unresolved class **at the ledger** would cut the C-200 gross-exposure ceiling by 64% and
push a gate that is already firing (the scorer logs `drawdown gate [realized] … 32.0% > 20%`; 2,642
occurrences in `logs/cron/copybot-monitor-score.log`) to a level no peak rebase could recover. A
`drawdown gate` / `gross exposure cap` reason is a **portfolio gate** (`exposure-cap.ts:121`): it blocks
the whole observation, not one lane.

**Therefore: scope 2 is NOT part of this proposal.** The ledger, the cap and the drawdown gate stay
byte-identical. Only the read path changes. If the operator ever wants the ledger cleaned, that is a
separate card with the numbers above in it — and it needs the peak rebase (`c200-drawdown.json`
`realizedPeak $11,068.58`) settled first, or it freezes the lane outright.

---

## 5. The proposal

### P1 (recommended) — one shared helper, three surfaces, one gate

Add `src/lib/fill-basis.ts`:

```ts
export type FillBasis = "booked" | "filled";

/** Ladder/record credit for one leg. `booked` reproduces today's behaviour byte-for-byte. */
export function fillBasisCredit(
  leg: { fillStatus?: string | null }, pnl: number | null, basis: FillBasis
): number {
  if (basis !== "filled") return pnl ?? 0;
  return leg.fillStatus === "filled" ? (pnl ?? 0) : 0;
}

/** One knob, one place. Default `filled`; `C200_FILL_BASIS=booked` restores today exactly. */
export function ladderFillBasis(): FillBasis {
  return (process.env.C200_FILL_BASIS ?? "").trim().toLowerCase() === "booked" ? "booked" : "filled";
}
```

Then, in one commit:

| # | file | change |
|---|---|---|
| 1 | `query_bankroll.js` (`findMany` select ≈L113; gate ≈L143-160; print block L323-340) | add `fillStatus` to the select; compute the series twice; **the gate/advance reads `fillBasisCredit(...,"filled")`**; print both lines, the fills-only one labelled `THE ADVANCE BASIS` |
| 2 | `src/app/page.tsx` (`C200_PHASES` L297, gate L317-338, rows L309-325) | same select + helper; the **displayed rung** derives from the fills-only sum, the booked sum prints beside it |
| 3 | `src/app/analytics/page.tsx` (C-200 series L103, daily map L161) | add `fillStatus`; plot both series (filled-only as the solid line, booked as dashed) |
| 4 | `src/lib/report.ts` (C-200 total L361/L373-376; `cmpFinished`) | the EOD C-200 line prints `proven fills −$94.64` and `booked +$5,631.94 (87% unresolved)`, and the payoff companions are computed on the booked arm **with the fills-only arm beside them** (`payoffSummary` already takes rows — pass the filtered set) |
| 5 | `~/.hermes/cron/jobs.json` — `copybot-c200-daily-report`, `copybot-tuning-review-daily` | the standing advance-basis string gains one clause: *"the advance is judged on the proven-fill (fillStatus='filled') sum; the booked sum is printed beside it and is never the advance basis"* (2 occurrences today, measured by count — prompts not printed) |

Cost 1h. No RuleSet field is needed for P1: it is a read-path change, and the knob is an env var, so
the revert does not need a rules version.

### P2 (not recommended) — replace every published C-200 figure with the fills-only number

Priced so the operator can decline knowingly: the overview card, the analytics series and the EOD C-200
total would go **+$5,631.94 → −$94.64**, and the dashboard would then disagree with `BotBankroll`
(which reconciles to the cent against the row sum) and with `reconcile-bankroll`'s identity. Two numbers
under one heading, or a card that contradicts the ledger — the defect class this repo has spent months
removing. P1 gets the same information with no figure deleted.

### P4 (optional, independent) — the enforceable form of "no clip increase"

The card's second clause is *"no C-200 clip increase and no clip above its pre-flip average ($8–10)
until the filled cohort reaches 120 legs with a CI that includes zero"*. As prose it is unenforceable;
as a field it is 20 lines. Measured context: post-flip C-200 avg clip **$25.7** (pre-flip $8.7), and 4
filled legs are already >$40 at −90.4%, 0 wins.

- New RuleSet field `c200ClipCapUsd?: number` — **absent/undefined = no-op** (byte-identical, the
  repo's rule for every new field), set by a version only if approved.
- Apply it at the **final size** returned to the booking call, i.e. after `applyKellyBandRails`, not
  only inside `mapBankroll200Size`: that helper is reached from the booking path *and* from the
  `legacyEquivUsd` the rails compare against, so a cap applied at one site is handed straight back by
  the other. Pin a test on the **leg's final size**, not on the helper's return.
- Suggested value if taken: **$20** (the clip the pre-flip book actually traded, and the live
  `BOT_LIMITS` ceiling for the other lane) — one dollar figure to override, revert = delete the field.

I am **not** proposing this as part of P1 (it changes what the lane risks, so it deserves its own yes),
and I am not proposing $0: 61 filled legs is not enough to justify a lane-wide halt.

---

## 6. Every figure that moves

| surface | today | after P1 | note |
|---|---|---|---|
| 18:00 report — phase gate (settled 7d) | −$203.47 (fails $1,750) | **−$286.42 (fails)** | new labelled line, booked printed beside |
| 18:00 report — T+0 gate | +$55.10 | **−$358.70** | dashboard-only arm |
| dashboard rung / gate | $55.10 of $1,750 (3.1%) | **−$358.70 (0%)** | does not advance either way |
| EOD C-200 total | +$5,631.94 | **+$5,631.94 booked / −$94.64 proven fills** | both printed |
| overview C-200 realized card | +$5,631.94 | unchanged + new sub-line | P2 would have moved it |
| analytics C-200 series | booked | booked + fills-only | two lines |
| `BotBankroll.realizedPnl` | $5,631.94 | **$5,631.94** | unchanged by design (§4) |
| exposure cap | $3,841 | **$3,841** | unchanged by design (§4) |
| realized-basis drawdown | 32.0% | **32.0%** | unchanged by design (§4) |
| STANDARD (any figure) | — | **unchanged** | no STANDARD row carries a fill verdict (0 of 3,710), so the helper is the identity there |

---

## 7. Verification before it is believed

1. **Byte-identical revert test:** with `C200_FILL_BASIS=booked`, `node query_bankroll.js` must print
   numbers identical to today's run (diff the two outputs; the only allowed change is the new labelled
   line).
2. **Boundary/identity probes:** the helper returns `pnl` for `booked`; `0` for `unfilled` and `NULL`
   under `filled`; `pnl` for `filled` under `filled`. Assert `filled + unfilled + NULL` partitions the
   total under `booked` (the cohort instrument already self-tests this: 272 vs 272).
3. **Cross-surface agreement:** the 18:00 report's settled fills-only sum, the dashboard's settled
   equivalent and `python3 scripts/c200-ladder-fill-basis.py` must print the same three numbers on the
   same day (they read different windows today — settled vs T+0 — so compare like with like).
4. **No silent scope leak:** `grep -rn "C200_FILL_BASIS\|fillBasisCredit" src scripts` must return only
   the intended sites; `SELECT COUNT(*) FROM RuleSet` and every `BotBankroll` row must be unchanged
   before/after the deploy, and `npx tsc --noEmit && npx vitest run` clean.

## 8. Pre-registered decision rule and refutation

**Gate (this proposal):** the advance basis is the proven-fill sum. Rung 1 is cleared when the trailing
7 settled days of `fillStatus='filled'` PnL sum to ≥ $1,750. **Re-read date 2026-11-25** (§ below) or on
the first rung approach, whichever is first.

**The 120-leg bar:** 61 filled legs post-flip at **4.23/day** → 59 more → **~14 days (2026-11-25)**.
At that point print the filled cohort's ROI with its market-clustered CI; the lane's size restriction
(if P4 is taken) lifts only when that CI **includes zero**.

**Refutation (any one withdraws this proposal):**
- **(a) The class is recoverable and mostly filled.** If the venue's archived trade tape — or any
  surviving book capture — shows **≥70% of the unresolved post-flip legs printed at or below our bid**,
  they were real positions: the proven-fill cohort is a selected minority, the lane's record is the
  booked one, and P1 should be withdrawn (not merely re-tuned). Cost 2h; this is the only thing that can
  refute it, and it fails today because the artifact is a rolling window with 0.0% reach.
- **(b) The gate starts blocking a lane that is provably profitable.** If, over 120 forward filled legs,
  the fills-only settled sum is positive with a CI excluding zero **while** the booked sum is
  materially higher and the unresolved share is falling (i.e. the resolver is catching up), then the
  basis is measuring resolver coverage rather than the lane, and the gate should move to arm (ii).
- **(c) A published figure disagrees after the change** (§7.3 fails) — withdraw and fix the surface
  before anything is read off it.

**What the losing branch costs** (priced, so the choice is even): taking (i) over (iii) has cost **$83**
on the settled window and **$450** post-flip all-time. Over 90 days, if the lane traded exactly as it has
post-flip, the strict basis would under-report by ~$2.8k — against a $1,750 rung. It cannot promote a
lane that has not earned it: the booked basis fails the rung by $1,953.47 today and the strict basis by
$2,036.42, and over the whole history the two bases clear the cheapest rung 8 times and 0 times
respectively (§2.2).

## 9. Apply — operator commands (if he approves)

```bash
# 1. the helper + the five surfaces (one patch, one commit)
git checkout -b lane-a/c200-fill-class-basis
#    … apply §5 P1 …
npx tsc --noEmit && npx vitest run
C200_FILL_BASIS=booked node query_bankroll.js > /tmp/basis-booked.txt   # must match today
C200_FILL_BASIS=filled node query_bankroll.js > /tmp/basis-filled.txt   # the advance line moves
# 2. dashboard (build-time: the public/ bundle is what :3013 serves)
npm run build && launchctl kickstart -k gui/$(id -u)/com.xsnyde2.copybot-dashboard
# 3. the two reviewer prompts: one clause each, both in the same change (they re-litigate otherwise)
# 4. P4 only if separately approved: scripts/apply-v73.ts (new field, default absent), then
#    DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v73.ts
```

**Revert:** `C200_FILL_BASIS=booked` (env, one line, no rebuild) or `git revert <sha>`. Neither touches
the DB, so a revert cannot strand a row.

## 10. What I did not do

- Nothing applied: no `apply-v*.ts`, no `prisma/dev.db` write, no branch, no merge, no RuleSet row.
- No rule, gate, size or lane moved. The standalone-cap and DD numbers in §4 are measurements of a
  channel I am **recommending against** touching.
- `scripts/c200-ladder-fill-basis.py` is new and **uncommitted** in the working tree; commit it with the
  patch if P1 is taken (a number that cannot be re-run is a guess).
- I did not re-derive the STANDARD fill question (0 of 3,710 legs stamped — a separate 3-4h build) and
  I did not re-open the pending clip-cap card's drawdown argument, which stands on its own.
- Everything quoted is on the stated basis: `simulatedPositionSize` = dollars at risk, dedupe first leg
  per `bot|wallet|market|outcome`, market-clustered CIs (2,000 draws), and **raw rows where the
  published surface is raw** (§2, §3) with the deduped view printed beside it.
