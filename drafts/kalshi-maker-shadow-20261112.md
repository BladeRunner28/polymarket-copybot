# Kalshi maker arm — the fill simulation the profile could not do, and why it closes

Card `t_1344932a` · `kalshi-maker-read-prereg` (option A, second half) · **Lane A — PROPOSAL ONLY**
Read 2026-11-12 · instrument `scripts/kalshi-maker-shadow-sim.py` · artifact `data/kalshi-maker-shadow-sim.json`
Dashboard: http://localhost:3013/drafts/kalshi-maker-shadow-20261112

**Nothing applied.** No RuleSet row, no `apply-v*.ts`, no `prisma/dev.db` write, no cron, no merge to
main, no Kalshi key exists on this box. The only things added to the tree are one untracked script,
one untracked artifact, one untracked settlement cache, and this document.

---

## Key insight

The 2026-11-11 read answered *"if we had been resting at level p, what did the fills at p pay?"* — a
per-price profile in which every qualifying print is credited once, at its own price, with **no
queue, no lifetime, and no unfilled remainder**. It could not lose a fill for arriving late, and it
could not charge the maker anything for the fills a resting order must take but would rather not.

Simulating the card's own rule from section (a) — rest a NO bid at `(1-p) − $0.01`, 100 contracts,
60 s lifetime, filled by a **later** print at our price, maker fee $0, marked to the venue's `result`
— over 613.3 captured hours:

- **The queue and the tick do not eat the edge.** Resting exactly at the trigger print's price
  returns **+1.601c** per contract against the profile's **+1.667c**. The read's own pessimistic
  "−1c for a tick of price improvement" haircut is not what the tape says: waiting at the print
  price costs **0.07c**, and resting a cent *cheaper* (`(1-p) − $0.01`, the card's literal formula)
  earns **more**, **+1.825c**.
- **The fill set eats the edge.** A resting order cannot decline a print that crosses it. Adding
  the fills a real book must take — prints that gap through our price, which the pre-registered
  exact-match rule excludes by construction — takes KXBTCD from **+1.825c to +0.508c** (CI
  `[-0.833, +1.904]`, no distinguishable edge), and KXETH15M to **−1.936c**
  (`[-3.698, -0.233]`, significantly negative).
- **The card's breadth clause fails independently**: only **51.2%** of KXBTCD's filled tickers are
  positive against a pre-registered bar of **60%**, and the shortfall is structural, not noise
  (52.0% at ≥20 legs per ticker).
- **One cell survives the realistic model**, and it is a different trade: buying NO at **0.90–1.00**
  returns **+1.517c `[+0.648,+2.323]`** (44,540 legs, 4,655 tickers) — the favourite-longshot bias,
  not the mid-band maker arm this card was testing.

**Verdict: 0 of 3 families graduate on the card's own rule, and no family has an edge on the fill set
a maker can actually get. Recommendation: CLOSE the lane, record the bracket, raise nothing else on
this card — the one surviving band belongs to a new pre-registered card (§7).** No forward shadow
job. Detail in §1–§9.

---

## 1. What was built

One offline instrument, read-only over the tape, writing only its own artifact:

| file | role |
|---|---|
| `scripts/kalshi-maker-shadow-sim.py` | streams every `prints-*.jsonl.gz`, runs five arms per family, ticker-clustered bootstrap (families, bands), self-test |
| `data/kalshi-maker-shadow-sim.json` | the artifact: every number below, with its pre-registration block |
| `data/kalshi-maker-shadow-settlements.json` | own settlement cache (240,389 tickers), a copy of the read's plus today's fetch — kept separate so this run cannot race `kalshi-maker-read.py`'s writer |

It does not import the read's fill logic. It re-uses only `bootstrap_ci`, `tape_hours`,
`credit_frac` and the settlement fetcher, so the statistics cannot drift between the two.

### The five arms (constants fixed before the run, in the file's docstring)

| arm | fill rule | status |
|---|---|---|
| `R_print` | every opposing print credits a fill at its own implied price — the read's profile | validation control |
| `B_print` | rest at the trigger print's own implied NO price, 60 s, filled by a **later** print there | control |
| `A_at` | **the card's (a)**: rest NO at `(1-p)−0.01`, 60 s, filled only by a later print **exactly** at our price | **pre-registered** |
| `A_one` | same orders, but a print that gaps **through** our price takes the single best-priced level it crossed | **central realistic estimate** |
| `A_sweep` | same orders, but a gap print takes **every** level it crossed | aggressive sensitivity |

Card constants kept verbatim: 100 contracts, 60 s lifetime, maker fee $0, `min(1, our_size/print_size)`
credit, mark = the venue's `result`, cluster bootstrap over **ticker** blocks (2,000 draws, seed
20261112). Nothing in the table above was chosen after seeing PnL.

### Population

18,015,141 qualifying prints, 735 files, **613.3 captured hours / 2,624 coverage rows** (≈82% duty)
over 2026-10-12T21:49Z → 2026-11-12T17:02Z. Universe: the three families that promoted in the read
(`KXBTCD` primary, `KXBTC15M`, `KXETH15M`); the gate is applied **per family, no pooling**.

### Validation before any number was believed

- **Self-test 23/23** — including the card's own measured error (a print *below* the resting price is
  not a fill), expiry either side of the deadline, no stacking of orders at one level, and that a
  consumed order cannot refill.
- **The instrument reproduces the published read to the cent.** `R_print` on KXBTCD NO returns
  **+1.667c `[+0.559,+2.736]`**; the 2026-11-11 artifact published **+1.667c `[+0.486,+2.745]`** on
  the same 591 h. Two independent calculations, same answer.
- **17 sampled legs re-derived from the raw tape by a separate script** (no shared code): 17/17
  trigger print, fill print, first-qualifying-print and lifetime all confirmed.
- **Two real bugs were found and fixed during this work, which is why the numbers above are worth
  anything:**
  1. `datetime.fromisoformat` rejects 5-digit fractional seconds, and **9.9% of KXBTCD prints carry a
     fraction it cannot parse** (5-digit is ~9.0pp of that) — the first version silently dropped them.
     Parse failures are now counted and printed (`unparseable_print_rows: 0`).
  2. Stripping `Z` before parsing made every timestamp naive, so all times were read as local
     (a uniform 5 h shift). Harmless for the EV, fatal for any join or hour-file lookup.
  Both are now covered by self-test checks.

---

## 2. Result — KXBTCD, the primary family

| arm | legs | EV/contract | 95% CI (ticker-clustered) | tickers | % positive |
|---|---|---|---|---|---|
| `R_print` (read profile) | 1,039,454 | **+1.667c** | `[+0.559,+2.736]` | 12,994 | 55.7% |
| `B_print` (rest at print price) | 638,858 | **+1.601c** | `[+0.436,+2.767]` | 10,584 | 52.4% |
| `A_at` (**card (a)**, exact-price) | 231,742 | **+1.825c** | `[+0.554,+3.090]` | 8,843 | **51.2%** |
| `A_one` (one crossed level) | 417,669 | **+0.508c** | `[-0.833,+1.904]` | 9,040 | 50.9% |
| `A_sweep` (all crossed levels) | 269,491 | **−1.087c** | `[-2.703,+0.599]` | 7,243 | 49.9% |

`A_at` is a small-edge but broad, sign-stable slice, not one market's story: top-10 tickers are 24.6%
of its PnL, the ex-top-10 EV is **+1.388c**, the 5%-trimmed ticker EV is **+1.374c**, and the sign
holds across the window's halves (**+1.157c** then **+2.516c**, split 2026-10-28T07:34Z).

*A_sweep has fewer legs than A_one because a sweep arm consumes its resting levels earlier and never
rebuilds them inside the same 60 s; leg counts across arms are not nested. That is why §4's central
marginal is computed from the one-level model, where the added legs are exactly the gap fills.*

### The other two families (same arms)

| family | `A_at` (pre-registered) | `A_one` (realistic) | `A_sweep` |
|---|---|---|---|
| KXBTC15M | +1.298c `[-0.421,+2.945]` | +0.687c `[-1.003,+2.376]` | −0.874c `[-2.871,+1.047]` |
| KXETH15M | +0.810c `[-1.014,+2.691]` | **−1.936c `[-3.698,−0.233]`** | −3.159c `[-4.939,−1.397]` |

Neither secondary family clears zero even on the flattering exact-price rule; on the realistic rule
KXETH15M is significantly **negative**.

---

## 3. By price band — and the one cell that survives

`A_at` and `A_one`, KXBTCD, by the price we paid for NO, with ticker-clustered CIs (bands hold ≥3,300
tickers each):

| NO price band | legs | `A_at` EV (exact) | `A_one` EV (realistic) |
|---|---|---|---|
| 0.00–0.10 (deep tail) | 35,440 / 49,480 | +0.699c `[-0.181,+1.644]` | +0.260c `[-0.603,+1.207]` |
| 0.10–0.25 | 31,616 / 61,092 | +0.741c `[-1.130,+2.575]` | −0.851c `[-2.426,+0.806]` |
| 0.25–0.50 | 46,496 / 99,322 | +1.189c `[-1.134,+3.598]` | −0.671c `[-2.751,+1.527]` |
| 0.50–0.75 | 48,061 / 99,530 | +3.284c `[+1.116,+5.402]` | +1.619c `[-0.513,+3.762]` |
| 0.75–0.90 | 36,201 / 62,643 | +2.485c `[+0.781,+4.138]` | +1.342c `[-0.380,+3.056]` |
| 0.90–1.00 (buy NO dear) | 33,363 / 44,540 | +2.030c `[+1.269,+2.803]` | **+1.517c `[+0.648,+2.323]`** |

Read it twice, because the two columns disagree about *where* the money is:

- With the exact-price rule, three bands clear zero — the mid band (NO 0.50–0.75, i.e. YES 0.25–0.50)
  is the best of them at **+3.284c**.
- With the realistic fill set, the mid band no longer clears zero (`[-0.513,+3.762]` on 99,530 legs)
  and **the only surviving cell is buying NO at 0.90–1.00** at **+1.517c `[+0.648,+2.323]`**.

That surviving cell is **not this card's question and not a maker-lane result**. Buying NO at 0.95
pays +5c when NO wins and loses 95c when it does not, so +1.517c/contract means the market priced NO
at 0.95 while it resolved NO ~96.5% of the time: the favourite-longshot bias, and the exact mirror of
the read's already-banked negative ("YES below 0.02 realised 0.0000, n=3,211"). It is a tail-risk
profile — small wins, rare large losses — that needs its own pre-registration, its own drawdown
accounting and its own refutation. **Do not read it as a reason to keep the maker lane open, and do
not size anything off it.**

Fill latency (trigger → fill, median 5.24 s) does **not** show the toxic-fast-fill signature:
0–2 s fills pay **+2.704c**, 30–60 s fills **+1.248c**. Fast fills here are continuation, and they
are the *good* ones — the adverse selection sits in the gap-throughs, not in the speed.

---

## 4. The crux — the pre-registered fill rule selects a fill set nobody can have

The card fixed "a fill requires a print **AT** the resting price with the taker opposing us" — and
it is right that a print *below* your bid is not a fill. But a print **above** your bid *is*: a
taker buying YES at 0.45 takes every resting NO-bid/YES-offer level it crosses, including ours at
an implied 0.41. The exact-price rule drops those fills by construction.

They are not free:

- Adding **one** crossed level per gap print adds **185,927 legs** at **−1.114c/contract** and takes
  KXBTCD from +1.825c to **+0.508c** (CI includes zero).
- Adding **every** crossed level adds 37,749 legs at a marginal **−17.5c/contract** and takes it to
  **−1.087c**.
- KXETH15M is already **−1.936c `[-3.698,−0.233]`** under the conservative one-level model.

The two models bracket the truth — the tape cannot say how deep a sweep went, because the book is
unobservable on a keyless feed and the print floor hides the sub-100-lot liquidity between levels.
But **every** point in the bracket except the exact-price corner is ≤ +0.51c with a CI that includes
zero. The exact-price corner is the one place a maker cannot choose to stand.

---

## 5. The breadth clause fails too, and structurally

The card's graduate rule: **≥2,000 filled legs** AND **EV>0 with a 95% ticker-clustered CI excluding
zero** AND **≥60% of filled tickers positive.**

`A_at` clears the first two (+1.825c, CI `[+0.554,+3.090]`, 231,742 legs) and fails the third at
**51.2%**. That is not a small-sample accident:

- 52.7% at ≥5 legs per ticker; **52.0% at ≥20 legs per ticker** (3,465 tickers) — more legs per
  ticker does not move it, because a ~12-leg ticker at ~$0.50 exposure has a per-ticker standard
  error near **±14c** while the edge is **+1.8c**. The per-ticker sign is a coin flip by
  construction; only an edge of roughly 4c+ would clear 60%.
- The read's own best arm got 55.7% and its report named that as the reason the headline is not read
  as an edge. This instrument agrees.

**I am not proposing to amend the clause.** Changing a pre-registered bar after seeing the result is
the exact lookahead this repo has already paid for. The clause is a filter on edge *magnitude*, the
arm's edge is 1.8c, and the filter says no. That is a legitimate answer to the question the card
asked.

---

## 6. What the card should conclude

Per the card's clause (c), applied family by family:

| family | ≥2,000 legs | EV>0 | CI excludes 0 | ≥60% tickers + | verdict |
|---|---|---|---|---|---|
| KXBTCD | ✓ | ✓ | ✓ | ✗ (51.2%) | **CLOSE** |
| KXBTC15M | ✓ | ✓ | ✗ | ✗ (51.5%) | **CLOSE** |
| KXETH15M | ✓ | ✓ | ✗ | ✗ (51.4%) | **CLOSE** |

And on the realistic fill set (`A_one`) no family has a CI excluding zero above zero. Both roads end
in the same place: **the maker lane closes.**

This is the expected outcome the card itself named ("that is the expected outcome, since our moat is
wallet-copy + measurement, not microstructure"). The value delivered is the bracket, plus one
surviving band handed to a new card.

What is *not* refuted, and should not be lost: **the read's profile is not a queue illusion.** A
maker resting at the last print's price keeps 96% of the profile's EV (+1.601c vs +1.667c). If a
book-aware capture ever shows the gap-through fills are rarer than the conservative model assumes,
that sentence is what reopens the question — see §10.

---

## 7. (a) EXACT CHANGE PROPOSED — close, record, and one new pre-registered card

**Lane A: nothing in this proposal is applied by me.** Every step is yours:

1. Move roadmap card `kalshi-maker-read-prereg` to **Done** with the negative recorded: the
   three-arm bracket, the breadth failure at 51.2% (KXBTCD), and the realistic family arm at
   +0.508c `[-0.833,+1.904]`.
2. **Do not** create the maker shadow job, its ledger or its cron entry. No forward data is owed:
   the arm fails a pre-registered clause on 231,742 legs of existing tape, and the realistic variant
   has no family-level edge to confirm.
3. Raise **one** new card for the surviving cell, pre-registered, nothing sized off this read. Paste
   body:

   > Deep-favourite NO on KXBTCD (NO 0.90–1.00 / YES 0.00–0.10): rest a 100-ct NO bid one tick
   > inside the last print for 60 s, filled when a later print reaches our price, marked to the
   > venue result. Retro read 2026-11-12 (`drafts/kalshi-maker-shadow-20261112.md`): +1.517c/ct,
   > 95% ticker-clustered CI [+0.648,+2.323], 44,540 legs on 4,655 tickers, under the **realistic**
   > fill model (a print that crosses our price fills us). GATE (fixed now, before forward data):
   > graduate only if forward tape gives ≥2,000 legs, EV>0 with a 95% ticker-clustered CI excluding
   > zero, AND the arm's max drawdown stays inside 4× its mean per-leg EV (this is a favourite bet:
   > +5c when right, −95c when wrong). REFUTED IF forward EV ≤ 0, or if the pooled win rate falls
   > under the 95% break-even implied by the price paid. No size change anywhere until then.
4. Leave the instrument and artifact in place as the record.
5. Keep the LIP line out of this card's PnL — see limit L5. No Kalshi key exists, so nothing here can
   execute regardless.

**If you would rather run the maker forward arm anyway** (defensible only as an out-of-sample check of
the *profile*), the minimum honest spec is: the 14-minute tape window is already running; score the
same five arms weekly with `python3 scripts/kalshi-maker-shadow-sim.py --quiet`; graduate bar
unchanged; nothing added to the trading book. My recommendation is **not** to run it — the only
clause it could still move is breadth, and §5 shows breadth is a function of edge size, not of time.

---

## 8. (c) Decision rule — unchanged, quoted

> graduate only if it reaches ≥2,000 filled legs AND its fill-weighted EV is > 0 with a 95%
> ticker-clustered CI excluding zero AND ≥60% of filled tickers are positive. Otherwise the lane
> CLOSES.

## 9. (e) ROLLBACK

Nothing live, no capital, no rule, no RuleSet version to unwind. To erase every trace of this read:

```
rm scripts/kalshi-maker-shadow-sim.py data/kalshi-maker-shadow-sim.json \
   data/kalshi-maker-shadow-settlements.json drafts/kalshi-maker-shadow-20261112.md
```

All four are untracked additions from this run; no tracked file was modified by it (other sessions'
edits to `data/roadmap.json`, `data/approvals.json` and `scripts/profit-postfix-integrity.py` are
theirs, not mine).

## 10. (d) WHAT WOULD REFUTE THE CLOSE

Any one of these reopens the card, and each is cheap to state in advance:

1. **A book-aware capture shows gap-throughs are rare.** The gap-through fills are where the edge
   dies (−1.114c marginal, one level). If a depth-carrying capture of the mid band shows a resting
   order is filled by *touch* prints ≥90% of the time and by gap prints <5%, the realistic arm
   converges on the exact arm and the mid band's +3.284c stands. `scripts/kalshi-1c-queue-capture.py`
   is the working pattern; it needs a different price band, not different infrastructure.
2. **The exact-price arm's breadth reaching 60% on a genuinely sharpened population** — e.g. one
   market class where tickers carry 100+ legs each, so the per-ticker sign is not binomial noise.
3. **The mid band clearing zero under the realistic model on a fresh tape window** — it reads
   +1.619c `[-0.513,+3.762]` today, so the falsifier is a second 30-day window whose one-level CI for
   NO 0.50–0.75 excludes zero.
4. **The `R_print` reproduction breaking** — if a re-run stops reproducing the read's +1.667c to the
   cent, the instrument is wrong and every number here is void. That is the first thing to re-run.

## 11. Limits — these travel with every number above

- **L1 PRINT FLOOR.** The tape keeps only prints ≥100 contracts, so this is a large-print fill model.
  Most maker fills in practice are smaller and invisible here. Direction of bias unmeasured.
- **L2 NO BOOK.** No queue position, no partial fills, no cancels, no competing size at our level.
  The credit rule is the card's and the unfiltered fill count is printed beside it. **This is the
  limit that decides the answer**: §4's bracket is unobservable on this feed.
- **L3 DUTY CYCLE.** 613.3 h of ~744 h (≈82%). A hole can only *lose* fills, never create one, so
  the fill count is a lower bound — the EV is not, and it is not sorted in a known direction either.
- **L4 NO SIDE ONLY**, because the card's (a) names the NO side. This is not a two-sided spread
  capture; the read's YES mirror is a different arm and must not be swapped in.
- **L5 NOT THE LIP RESULT.** `lip-ledger.py` measured resting fills inside LIP reward programs
  (−1.23c mark-out). This is the general family/price profile, not a re-derivation of that, and the
  two must never be interchanged.
- **L6 PRICE PROFILE, NOT A CAPITAL PLAN.** 378 legs/hour at ~55 credited contracts each
  (~20,800 contracts/hour). There is no exposure cap, bankroll or sizing here; the EV/contract is the
  quantity, not the PnL column.
- **L7 SETTLEMENT SNAPSHOT.** 565 of 231,742 `A_at` legs (0.24%) are unsettled and are excluded, never
  marked. Cache is today's fetch.
- **L8 BAND CELLS ARE SMALLER THAN THE FAMILY.** Every band CI above is a 2,000-draw bootstrap on
  3,300–4,700 tickers with no multiple-testing correction across six bands × two arms; a single cell
  clearing zero at that width is a candidate, not a result.

## 12. Reproduce

```
python3 scripts/kalshi-maker-shadow-sim.py --self-test      # 23/23, exits 1 on RED
python3 scripts/kalshi-maker-shadow-sim.py --limit-print-files 5 --no-fetch   # smoke, ~2 s
python3 scripts/kalshi-maker-shadow-sim.py --quiet           # full read, ~5-6 min (band CIs cost a
                                                             # bootstrap each), writes the artifact
```

Cost of this read: **~3 h** (instrument + four full passes + verification). Cost of the decision it
proposes: **zero**.
