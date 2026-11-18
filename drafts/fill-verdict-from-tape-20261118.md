# LANE A PROPOSAL — make the venue tape the fill verdict

**The card is right about the defect and wrong about two of its three parameters — and it points at a
surface the change cannot reach.** Measured today on the population a dashboard actually sums (2,708
finished rows), the book goes from **+$1,564.1 (+5.0%) to −$2,547.4 (−7.1%)** once a leg books only if
the venue's price ever came to our level. The card's literal rule (1h, strict touch, resolver's negative
wins) reads **−$10.9%** — harsher than the evidence supports, because the paper ledger has no cancel and
because the series is a *midpoint*, not prints. I recommend the 24h / half-spread / tape-first rule and
price all four combos so the operator can pick a different one by number.

**Lane A constraint.** This is a proposal. Nothing has been applied: no `apply-vNN.ts`, no
`prisma/dev.db` write, no RuleSet read or write, DB opened `mode=ro` throughout, no merge of a rule
change. The two new instruments and the write-up are committed so every figure below is re-runnable.

Everything quoted comes from three committed read-only instruments, run today against
`prisma/dev.db` (`mode=ro`) and `clob.polymarket.com/prices-history` (keyless, cached under
`data/fill-tape-cache/`, gitignored):

```bash
python3 scripts/fill-verdict-from-tape-dryrun.py            # 2,339 deduped legs — the measurement convention
python3 scripts/fill-verdict-from-tape-dryrun.py --rows     # 2,708 rows — what a shipped surface sums
python3 scripts/fill-verdict-from-tape-dryrun.py --rows --min-rule 68   # 463 rows — the live regime
python3 scripts/profit-filled-decomp.py --min-rule 0        # the class decomposition (S1–S14)
python3 scripts/profit-filled-decomp.py                     # regime v68+
python3 scripts/profit-fill-tape.py --since=2026-09-01 --only=8   # the 24h horizon, two tolerances
```

---

## 0. What is being asked, in three lines

1. **A1 (recommended, reversible in one env var):** the read path decides whether a leg was a position
   from the venue's own tape — `filled = resolver stamp OR the midpoint reached our booked level within
   24h at half a cent` — and a leg with no evidence of a fill books zero. Six read surfaces, printed
   two-basis for one week before the credit line moves alone.
2. **A3 (same decision):** withdraw card `ladder-credit-confirmed-filled`. Its own refutation fired on
   2026-11-17 and today's re-read makes it worse: the class it would credit is **−$943.4 on 107 legs
   (−35.1%)** in the live regime.
3. **Not asked for now (A2):** restating the stored ledger. It is what reaches `netWorth` and the
   exposure cap, and it is a different, one-way decision — `BotBankroll.realizedPnl` is a **posted
   ledger**, not a read-path aggregate, so A1 cannot reach it. Priced in §5, not recommended today.

---

## 1. The defect, restated with today's numbers

`src/lib/paper.ts:47` is the whole booking rule:

```ts
export function bookedPnl(leg: { fillStatus?: string | null }, pnl: number): number {
  if (!fillAwareBookingEnabled()) return pnl;
  if (leg.fillStatus === "unfilled") return 0;   // <-- the only negative ever enforced
  return pnl;                                    // NULL books at p(fill) = 1
}
```

Three structural holes, all measured:

| hole | size (today) |
|---|---|
| `NULL` books at p(fill)=1 | 1,523 legs / $20,932 in the Sept+ population, **+$4,327.3** of stored PnL |
| the resolver's `unfilled` is a **false negative on 30.0%** of decidable legs | 101 of 337 decidable legs trade through our level after dispatch (live regime: 83 of 97 = **85.6%**) |
| rows stamped `unfilled` still carry stored PnL (stamped after settlement) | 535 legs, **+$2,297.1** |

The resolver's *positive* stamp is trustworthy — 234 of 238 decidable resolver-filled legs agree with
the tape (**98.3%**; live regime 107/107 = 100%). So the defect is one-sided: **the negative is the
untrustworthy half**, and nothing downstream re-tests it.

**The class the resolver never stamped is not untested — it is 63.3% touched and its profit is in the
37% that never came to us:**

| class (deduped, Sept+) | legs | cost | stored PnL | ROI |
|---|---|---|---|---|
| resolver `filled` | 281 | $4,334 | **−$937.1** | −21.6% |
| `NULL` & midpoint touched ≤1h | 862 | $13,516 | +$212.5 | +1.6% |
| `NULL` & never touched ≤1h | 500 | $5,638 | **+$4,458.0** | +79.1% |
| rows stamped `unfilled` | 535 | $8,280 | +$2,269.5 | — |

The two positive classes are exactly the two with no evidence of a fill.

---

## 2. What the tape is — and why that changes the rule, not the direction

`clob.polymarket.com/prices-history` returns a **minute MIDPOINT series**, not executed prints:
on 1c-spread books 89.8% of 16,675 sampled points sit exactly at the half-cent (`profit-fill-tape` §1b;
card `profit-tape-is-midpoints`, Lane B, repaired 2026-11-18). So:

> **"touch" means our resting bid became the best bid** — a seller arriving would have hit us. Weaker
> than a trade print, stronger than nothing, and *one-directional*: a midpoint that never came to us is
> an upper bound on "never filled", never a proof.

Two consequences the card does not carry:

1. **A strict touch (`L+0.001`) can only fire when the market moved BELOW us.** If our bid *is* the
   best bid on a 1c book, the midpoint sits at `L+0.005` and never prints at `L`. The instrument's
   `near_miss` band (`L+0.001 … L+0.010`) is therefore where the real question lives: **42.0% of the
   402 near-miss legs sit at exactly the half-cent**, the signature of a bid that was at the best bid.
2. **The paper ledger has no cancel.** The sidecar (`rust-sidecar/src/main.rs`) has no TTL, expiry or
   cancel path — grepped, none. A bid that fills at hour 7 is still a position in this model, so a 1h
   window throws away real exposure. Measured: of the legs untouched in the first hour, **841 (or 644 at
   the half-spread tolerance) touch later inside 24h** — $9,050 / $6,327 of real notional.

---

## 3. The rule grid — one rule at a time, same population

All four columns are measured on the same rows by the same classifier; only the rule changes.
`resolver-first` = the resolver's `unfilled` outvotes a tape touch (the card's implicit choice).
`tape-first` = a tape touch outvotes the stamp.

### 3a. Every finished ROW opened ≥ 2026-09-01 — what a surface sums (2,708 rows, $39,874, 77.9d)

| rule | rows | cost | PnL | ROI | cluster CI |
|---|---|---|---|---|---|
| stored ledger, all rows | 2,708 | $39,874 | +$3,861.1 | +9.7% | — |
| **published today** (positions only) | 2,169 | $31,530 | **+$1,564.1** | **+5.0%** | [−14.5,+26.6] |
| 1h · L+0.001 · resolver-first *(the card, literally)* | 1,404 | $22,407 | −$2,437.6 | −10.9% | [−27.2,+6.7] |
| 1h · L+0.001 · tape-first | 1,507 | $25,229 | −$2,444.7 | −9.7% | [−24.6,+7.0] |
| 1h · L+0.005 · resolver-first | 1,468 | $23,176 | −$2,408.2 | −10.4% | [−26.5,+6.0] |
| 1h · L+0.005 · tape-first | 1,755 | $28,776 | −$2,417.3 | −8.4% | [−22.3,+5.4] |
| 24h · L+0.001 · resolver-first | 1,928 | $28,227 | −$2,471.0 | −8.8% | [−25.2,+9.9] |
| 24h · L+0.001 · tape-first | 2,371 | $35,144 | −$2,885.3 | −8.2% | [−22.2,+7.4] |
| 24h · L+0.005 · resolver-first | 1,955 | $28,721 | −$2,307.8 | −8.0% | [−24.3,+10.1] |
| **24h · L+0.005 · tape-first** *(recommended)* | **2,424** | **$36,004** | **−$2,547.4** | **−7.1%** | **[−21.2,+7.6]** |

### 3b. The measurement convention (deduped first leg per bot|wallet|market|outcome, 2,339 legs, $33,547)

| basis | legs | cost | PnL | ROI | $/day |
|---|---|---|---|---|---|
| stored ledger | 2,339 | $33,547 | +$5,659.7 | +16.9% | +$72.6 |
| published today (positions only) | 1,804 | $25,267 | +$3,390.2 | +13.4% | +$43.5 |
| card literal (1h · 0.001 · resolver-first) | 1,143 | $17,851 | −$724.6 | −4.1% | −$9.3 |
| **recommended (24h · 0.005 · tape-first)** | **2,084** | **$30,129** | **−$408.3** | **−1.4%** | **−$5.2** |

Both populations agree on the sign and disagree on the size by ~6pp, because dedupe drops accumulated
duplicates that are disproportionately winners. **The shipped surface will show the row numbers
(§3a); quote the deduped ones only as the measurement convention.** The bracket is −1.4% … −7.1%,
against a published +5.0% / +16.9%.

### 3c. What the recommended rule voids (rows)

| | rows | cost | PnL | ROI | CI |
|---|---|---|---|---|---|
| voided: resolver `filled` | 0 | $0 | $0 | — | — |
| voided: resolver `unfilled` | 70 | $1,061 | +$2,536.6 | +239.1% | [+87.1,+398.5] |
| voided: resolver `NULL` | 214 | $2,809 | +$3,871.9 | +137.8% | [+52.1,+274.5] |
| **TOTAL voided** | **284** | **$3,870** | **+$6,408.5** | **+165.6%** | **[+87.9,+271.8]** |

Concentration inside the voided class: ex-top-1 +$4,895.2, ex-top-5 +$2,850.7, ex-top-10 +$1,645.4;
**202 of 284 rows positive (71%)**. Half a coin flip of winners carrying a handful of longshots is
exactly what a portfolio booked at p(fill)=1 looks like — five rows carry $3,557.8 of the $6,408.5.

The arithmetic closes to the cent, which is the strongest single check in this document:

```
stored  +$3,861.1   −   voided +$6,408.5   =   −$2,547.4        (rule book, §3a)
```

Read against today's *published* figure the same move decomposes as

```
published +$1,564.1  −  NULL rows never touched $3,871.9  −  stamped-'unfilled' rows the tape also
never touched $239.5  =  −$2,547.4
```

The remaining **469 stamped-`unfilled` rows come back into the book at a net −$239.5** — they are the
resolver's false-negative class, and booking them makes the number slightly *worse*, not better. That
is the one place this change moves against its own headline, and it is reported rather than netted
away.

### 3d. The live regime (v68+): this is a historical problem, and say so

| | rows | cost | PnL | ROI |
|---|---|---|---|---|
| stored ledger | 463 | $10,024 | −$140.8 | −1.4% |
| published today | 259 | $5,110 | −$511.7 | −10.0% |
| **recommended rule** | 446 | $9,606 | −$406.9 | −4.2% |
| voided | 17 | $419 | +$266.0 | +63.6% |

**Only 17 rows / $419 / +$266 are voided in the live regime.** The $6.4k phantom is Sept–October
vintage. Approving this does not change what the bot decides or how much it risks tomorrow; it stops
the *lifetime and ladder* figures claiming profit that was never exposure. That is the honest scope,
and it is also why A1 is cheap and safe.

---

## 4. Where the change lands — and the surface the card gets wrong

| # | surface | file | what it reads today |
|---|---|---|---|
| 1 | booking (write path) | `src/lib/paper.ts:47`, call sites `:360` mark / `:381` settle / `:493` close | `bookedPnl()` — the only verdict consumer |
| 2 | the ladder / rung | `query_bankroll.js:113-160` (14d `realizedPnl` series), gate at `:143-160` | raw `realizedPnl`, **no verdict at all** |
| 3 | EOD report | `src/lib/report.ts:744,754` (`stdRealized`, `cmpRealized`), `:800` day stack | raw `realizedPnl` |
| 4 | Overview + Analytics | `src/app/page.tsx:108-141`, `src/app/analytics/page.tsx:103-161` | raw `realizedPnl` |
| 5 | day-PnL / daily-loss breaker | `src/lib/day-pnl.ts` (`realized`, TR-15 rows) | raw `realizedPnl` |
| 6 | the stamper | `scripts/c200-fill-resolve.ts` → `src/lib/c200-fill-resolution.ts`; STANDARD booth `src/lib/standard-fill-stamp.ts` (measurement-only) | the evidence the stamps come from |

**Correction to the card:** its decision rule says the tape-never-traded class books zero "and the
C-200 bankroll row that sets netWorth". It cannot. `BotBankroll.realizedPnl` is incremented **at settle
time** (`src/lib/paper.ts:386-390, 510-514`) and equals the row sum to the cent today
(+$5,117.89), so it is a posted ledger, not a read-path aggregate. A verdict helper can change what
the reports *say*; only a restatement changes what the ledger *holds*. Those are §5's two arms.

### Design for A1 — one helper, one artifact, six readers

```ts
// src/lib/fill-verdict.ts  (new, ~40 lines)
export type FillVerdict = { v: "reached" | "never" | "no_tape"; minp: number | null;
                            touchTs: number | null; model: string };
/** Default `tape`; FILL_VERDICT=resolver restores today's behaviour byte-for-byte. */
export function fillVerdictMode(): "tape" | "resolver"
/** Does this leg book? No verdict -> today's rule (the resolver stamp decides, NULL books). */
export function booksLeg(leg: { fillStatus?: string | null }, v?: FillVerdict | null): boolean
```

- **Producer:** `scripts/fill-verdict-stamp.py`, nightly after the EOD, re-adjudicates finished legs
  whose window has elapsed (never re-adjudicates a decided leg — append/merge, the same shape as
  `scripts/standard-fill-stamp-merge.py`), and writes `data/fill-verdict.jsonl` keyed by `tradeId`
  with `{verdict, minp, touchTs, window, tau, model, checkedAt}`. **No schema migration, no prisma
  write** — the artifact pattern the STANDARD booth already uses.
- **Readers:** the six rows above join the artifact in memory. A leg with no verdict yet falls back to
  today's rule, so no leg changes basis before it is adjudicated, and coverage prints beside the
  number (a surface must say `verdict coverage 96.2% of finished legs`).
- **Refusals (hard, in the producer):** refuse rows where `entry ≈ 1 − intentPrice` (the
  complement-frame class, 105 C-200 rows in the 2026-11-13 read — the level is a dollar away from the
  stated outcome, so a verdict would guess) and rows with no `conditionId`. Refused rows keep today's
  behaviour and are counted in the coverage line.
- **The week:** every surface prints `booked / verdict / resolver-filled / never-touched` for seven
  days before any credit line moves alone, exactly as the card asks.

**Revert:** `FILL_VERDICT=resolver` — one env var, code default is the new basis (the repo's convention,
because nothing loads `.env`; see `fillAwareBookingEnabled`). The artifact is additive, so a
`git revert` of the readers also restores today exactly. Nothing is deleted either way.

**Effort: 3–4h** (helper + 6 readers + the stamp job + the two-basis week), not the card's 2h — the
artifact producer and the refusal rules are the extra hour.

---

## 5. The two arms, priced separately

### A1 — read path (recommended now)

| figure | today | after A1 (rows) |
|---|---|---|
| published book, all lanes Sept+ | +$1,564.1 (+5.0%) | **−$2,547.4 (−7.1%)** |
| C-200 book (Sept+ rows) | +$5,159.2 stored | **−$1,008.8** |
| STANDARD book (Sept+ rows) | −$1,298.0 stored | −$1,538.5 |
| ladder, settled T-3..T-9 window | +$441.9 (25.3% of the $1,750 bar) | **+$394.0 (22.5%)** |
| ladder, same window ex-top-1 | −$110.3 | −$158.2 |
| resolver-filled class (live regime) | −$943.4 (−35.1%) | unchanged |
| `BotBankroll.realizedPnl` | +$5,117.89 | **unchanged** |
| exposure cap | $3,559.15 | **unchanged** |
| open C-200 notional / cap | $37.89 = 1.06% | unchanged |

No rung is bought either way (both are a quarter of the bar), and the cap is untouched — so A1 is a
**measurement** change with no risk-rail movement. That is the reason to take it first.

### A2 — ledger restatement (not now; its own yes)

Priced only to the Sept+ slice, because the all-time version needs its own row-level dry run:

| | today | after A2 (Sept+ slice) |
|---|---|---|
| C-200 rows voided | — | 269 rows / $3,590 → **−$6,168.0** of stored PnL |
| `BotBankroll.realizedPnl` | +$5,117.89 | **−$1,050.1** |
| net worth (principal + realized + open MTM) | $7,018.30 | **$850.30** |
| exposure cap ($1,000 base + 50% above principal) | $3,559.15 | **$1,000.00** |
| open notional as a share of cap | 1.06% | **3.79%** |
| realized-basis drawdown vs the recorded peak ($11,458.63) | 38.8% | **92.6% — the 20% gate TRIPS** |

So A2 is not "a smaller number": it freezes the lane unless the peak is reseeded from the recorded
net-worth series in the same commit (the `P2b` step the 2026-11-13 proposal already specified —
`drafts/profit-fill-reachable-basis-20261113.md` §4), and it deletes profit that is currently inside
`cashBalance` ($6,979.99). The 2026-11-13 all-time dry run (+$5,880.52 removed → −$209.57 lifetime) was
a **different rule** and does not transfer; A2 needs its own row-level run before any yes.

### A3 — withdraw `ladder-credit-confirmed-filled` (same decision, zero cost)

Its refutation fired on 2026-11-17 and today's re-read fires it harder: the class it would credit is
the *adversarially selected fast-fill subclass*, −$937.1 on 281 legs (−21.6%) all-history, −$943.4 on
107 legs (−35.1%) live. Approving it would pin the rung to the worst-measured basis in the book.

---

## 6. Validation — why this tape is believable

| check | result |
|---|---|
| coverage | 2,339 / 2,339 legs adjudicated (**100%**); 0 legs without tape in any run |
| agreement on the class we already trust | 98.3% of decidable resolver-`filled` legs (234/238); 100% live regime |
| the touch test is not a t0 artifact (we paid the market price, so the tape is at our price at dispatch) | rates barely decay with a lag floor: filled 83.3→80.1%, unfilled 18.9→17.0%, NULL 56.6→51.8% at lag ≥900s |
| the 24h negative is not a sampling artifact | 1-minute re-check of the never class: 1.2% reverse rate at the half-spread tolerance, 3.8% at strict (80 sampled) |
| horizon | of legs untouched in the first hour, 644 (half-spread) / 841 (strict) touch inside 24h — a 1h rule would erase them |
| tolerance is not free | 42.0% of the 402 near-miss legs sit at exactly the half-cent; voiding them would bank $489.3 of artifact |
| the tape does not "invent" fills | a resolver-`filled` leg it calls never-touched is 4 legs, all-history |

---

## 7. Pre-registered refutation

**Withdraw A1 if any of these fires:**

1. A second source that is **not** the price tape (L2 book capture from `data/l2-*`, or venue trade
   prints at our bid) shows **≥60% of the voided class actually filled** at non-negative ROI on a
   forward 150-row sample. Then "never touched" is not "never filled" and the phantom is real profit.
2. A forward 150-row sample of the voided class, re-read at **1-minute** fidelity, touches at **≥60%**
   — that would mean the 5-minute series is stepping over our level often enough to make the negative
   meaningless.
3. Verdict-store coverage falls below **95% of finished rows in any 30-day window**, in which case the
   fallback silently becomes the rule and the change is unimplementable.

**Reopen A2 when:** A1 has printed two-basis for ≥7 days, the peak-reseed procedure has its own
approved one-liner, and the all-time row-level dry run is committed.

---

## 8. What could still be wrong

| risk | size | checked? |
|---|---|---|
| the series is a midpoint, not prints — "touch" is reachability, not a trade | whole model; direction preserved | yes — S1b, and the wording here says so |
| queue position and size are ignored: a midpoint at our bid means a seller *could* have hit us | lower bound on fill for every booked leg | yes — stated, and it is why the refutation names a non-tape source |
| 5-min sampling in the 24h arm | 1.2–3.8% reverse rate | yes — 1-minute re-check on 80 legs |
| complement-frame rows (`entry ≈ 1 − intent`) | 105 C-200 rows identified 2026-11-13, refused | yes — hard refusal in the producer |
| dedupe vs rows | 2,339 vs 2,708; −1.4% vs −7.1% | yes — both published |
| `near_miss` band (`L+0.001…L+0.010`) | 402 legs / $5,017 / −$489.3 | kept **booked** under 0.005, i.e. conservative (it lowers the book) |
| rows opened before the 2026-11-09 price-side repair | most of the voided class is Sept–Oct vintage | yes — the live regime is reported separately (§3d) |
| the ladder's own window is T-3..T-9, not "last 7d" | 149 legs, +$441.9 → +$394.0 | yes — S13b, computed on the rung's own clock |

---

## 9. Overridable flags — one line each

1. **Rule = 24h · L+0.005 · tape-first** (−7.1% rows / −1.4% deduped). *Why:* the ledger has no cancel
   and the series is a midpoint, so the card's 1h · 0.001 window voids real exposure. **Override to the
   card's literal rule** (−10.9% rows / −4.1% deduped) if you want the harshest defensible number.
2. **Window 24h, not 1h.** *Why:* 644 rows / $6,327 / +$597.9 of real positions fill only after the
   hour (841 / $9,050 / +$186.7 at strict). Override to 1h if you want "we only count fills inside the
   hour we were watching".
3. **Tolerance L+0.005, not L+0.001.** *Why:* 42.0% of the near-miss mass sits at exactly the
   half-cent — the signature of a bid that *was* the best bid. Override to strict (+$0.001) to count only
   prints at or below our level; it lifts the book by ~$30 and voids 402 more legs.
4. **The tape outvotes the resolver's negative.** *Why:* 30.0% decidable false-negative rate against
   98.3% agreement on the positive. Override to resolver-first and the book rises ~$240 (it books 400
   fewer rows) — cheaper, less honest.
5. **A1 now, A2 later.** *Why:* A1 moves text only and reverts with one env var; A2 deletes $6,168 of
   recorded profit, drops the cap $3,559 → $1,000 and trips the drawdown gate at 92.6% unless the peak
   is reseeded. **Override to both-at-once** only with the reseed in the same commit.
6. **A3 = withdraw `ladder-credit-confirmed-filled`.** *Why:* its own refutation fired; it would credit
   the −35.1% subclass. Override to keep it and the rung reads a basis the tape contradicts.

---

## 10. Provenance and artifacts

- Approval: `apr-fill-verdict-from-tape`, Lane A, approved 2026-11-18T17:03:44Z (proposal only).
- Roadmap card: `fill-verdict-from-tape`; the card's own 2026-11-18 basis correction (tape = midpoints)
  is carried into the wording of every figure here.
- Instruments (committed with this write-up, all read-only):
  `scripts/fill-verdict-from-tape-dryrun.py` (new, `--selftest` PASS: tolerance, policy, no-evidence
  fallback), `scripts/profit-filled-decomp.py` (S13b rung window, S14 tolerance sweep added),
  `scripts/profit-fill-tape.py` (§8 now sweeps the tolerance and splits the voided class by resolver
  stamp).
- Run artifacts: `data/fill-verdict-from-tape-dryrun-20261118.txt`,
  `data/fill-verdict-from-tape-dryrun-rows-20261118.txt`,
  `data/fill-verdict-from-tape-dryrun-rows-regime-20261118.txt`,
  `data/profit-filled-decomp-allhist-20261118.txt`, `data/profit-filled-decomp-regime-20261118.txt`,
  `data/fill-tape-horizon-20261118.txt`.
- Nothing applied: no prisma write, no RuleSet read/write, no `apply-v*`, no dispatch, gate, exit or
  clip touched, no rule merged.

---

**IF YOU WEREN'T HERE:** the book's +$1,564 is +$1,564 only because 284 rows the market never brought
to our price still book at p(fill)=1 — they carry +$6,408 of the +$6,409 of profit, 71% of them
winners, and five rows carry $3,558 of it. Ask the venue and the row book reads −$2,547 (−7.1%). It is
a read-path change (3–4h, one env var to undo), it buys no rung (22.5% of the bar either way), and it
touches no risk rail. The ledger restatement that *would* touch the cap is a separate, one-way
decision — priced here, not recommended today. And kill `ladder-credit-confirmed-filled` in the same
breath: the class it wants to credit is −35.1%.
