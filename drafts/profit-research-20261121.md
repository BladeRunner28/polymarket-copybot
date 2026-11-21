# Profit research 2026-11-21 — item 2's gate finally computed, and it turns on one cent

http://localhost:3013/drafts/profit-research-20261121

**Instruments (committed with this doc):** `scripts/profit-path-research.py` (the standing read),
**`scripts/profit-question-fill-read.py` (new, this doc)** — it joins the STANDARD fill booth's
1,028-leg union stamp to settled PnL and splits by **vertical × reachability**, so item 2's decision
rule is computed on the class item 2 names instead of on the lane-wide pool. Read-only, no DB write.

**Basis for every figure:** cost = `simulatedPositionSize` (**dollars at risk**, not notional);
PnL = `realizedPnl` where `status IN ('closed','resolved')` (TR-15 OR), `isDemo=0`; dedupe = first
leg per (botId, wallet, market, outcome); clock = entry vintage, never settlement date; CI =
market-clustered bootstrap, 2,000 draws. Reachability = the stamp's **minimum ask across its lag
buckets ≤ the booked price** — an UPPER bound on fill (no queue position, no size), not a fill.

---

## Finding 1 — item 2's rule was never computed on its own population, and it cannot be applied as written

Item 2's decision rule: *"if ≥60% of the question-market legs tape out as filled at non-negative ROI,
the profit is real; otherwise it is written off permanently."* Measured today on the only slice that
carries a book stamp **and** a settled PnL:

| STANDARD question class | legs | at risk | PnL | ROI | ex-top-3 | clustered CI |
|---|---:|---:|---:|---:|---:|---|
| all evaluable | 89 | $1,570 | +$287 | **+18.3%** | **−$276** | [−32.3, +78.4] |
| REACHABLE at booked | 32 | $553 | +$413 | +74.7% | −$76 | [−21.5, +212.2] |
| NOT reachable | 57 | $1,017 | −$127 | −12.4% | −$417 | [−56.2, +54.4] |

- **Reachability rate: 36.0% at the booked price (32/89) → item 2's ≥60% gate FAILS.**
- **At one cent of slack: 80.9% (72/89) → the same gate PASSES.** Same legs, same tape, one cent.
- The whole cell's +$287 is **three legs** (ex-top-3 −$276), and its CI spans zero.

So the rule that would settle the book's largest number returns whichever answer the operator
chooses. That is not a measurement; it is an unparameterised test. The distribution says why:
median attainable-minus-booked on the question class is **+0.5c**, and **23 of 89 legs (26%) sit
exactly one cent above the booked price** — the booked price is a 3–4 decimal quote against a
1c-tick book, so a zero-tolerance test measures tick rounding as much as fills.

**Coverage of the target:** the map covers **396 of 1,028** STANDARD legs opened since the L2 corpus
(38.5%), and **89 of 543** STANDARD question legs (16%) carry a book at dispatch. Book-wide, 372
question legs are mapped and carry **+$3,087**, but the lane that owns item 2 can only see a sixth
of its own class. The rule as written assumes complete adjudication. It has 16%.

## Finding 2 — same vertical, two lanes, opposite signs

The question class is the one place the two lanes disagree outright:

- **C-200, fill-confirmed:** 53 legs, $1,519 at risk, **−$757 (−49.8%)**, CI [−73.7, −15.6].
- **STANDARD, reachability-tested:** 89 legs, $1,570 at risk, **+$287 (+18.3%)**, CI spans zero,
  three legs carry it.

Neither can be promoted to a class result. What they jointly say is that "question markets make
money" is a statement about *which lane and which measurement*, not about the market type — the
C-200 cell is provably negative and the STANDARD cell is three legs.

## Finding 3 — the union refutation has already FIRED; yesterday's "NOT EVALUABLE" was the wrong population

The daily artifact carries two refutations. The **tick** one reads on its own snapshot (n=151 of the
required 300) and prints NOT EVALUABLE. The **union** one reads every stamped leg in the file:

- n = 396 (gate 300 met), **fired**: mean (attainable − mid) = **+0.26c**, inside the ±0.3c band →
  *"there is no cent to harvest and a booking change has no improvement to sell."*
- The ask arm on the same legs: attainable sits **+1.04c ABOVE** the booked price, with only
  **10.1%** at-or-better and 35.4% worse by ≥1c.

Yesterday's ledger entry recorded the tick's "NOT EVALUABLE". That was my mis-read, corrected here:
the booking-basis question is answered, and the answer is that the **booked entry is systematically
better than what the book offered** — which is the arithmetic signature the whole brief is about.

## Measurement refresh — and why today's −17.5% is not an improvement

| filled class | legs | at risk | PnL | ROI | clustered CI |
|---|---:|---:|---:|---:|---|
| all filled | 288 | $4,427 | **−$775** | **−17.5%** | [−50.8, +23.7] |
| ex-$100-clip | 267 | $2,327 | −$165 | −7.1% | [−31.5, +20.5] |
| $100 clip | 21 | $2,100 | **−$610** | **−29.0%** | — (win 9.5% vs 14.2% break-even) |

The aggregate moved **−21.8% → −17.5%** since yesterday. That is **five newly-settled legs totalling
+$176.16 on $63.23 of risk** — one of them a +$110 win on a $20 clip. A single leg moves this
aggregate 2.5pp. Nothing here is a trend, and the ex-$100 figure (−7.1%) is still indistinguishable
from zero.

- Vertical (filled): question −49.8% (n=53), esports −56.9% (n=67, CI excludes zero),
  sports +115.3% but **ex-top-3 −21.7%** (n=107).
- Coverage: C-200 **856/2,903 = 29.5%**; STANDARD **0/10,036 = 0.0%**, fifth day.
- Whole-book $100 tier: 87 legs / $8,649 / **+$2,917**, against −$610 on the 21 legs of it we can
  prove. The cap's target shows the same sign inversion as the book itself.

## Progress on the approved five (deltas only)

- **1. Maker-vs-taker shadow — 0 legs, day 4.** No artifact, no card; still unstarted.
- **2. STANDARD fill adjudication — stamp advanced, merge into `fillStatus` not done.**
  Union 1,028 legs, 396 book-stamped (38.5%), 352 settled-evaluable. DB coverage still 0.0%.
- **3. $100 clip cap — forward cohort unchanged at 4 legs of 40** ($400, −$400, 0 wins). This
  morning's review withdrew it as a second fix; I add the whole-book/filled sign inversion above.
- **4. ML re-point — no shipped change.** Daily job clean (5,954 export rows, 0 failed steps); the
  gate still scores outcome AUC against price-only. The re-point exists only as a card.
- **5. LIP — re-read, still CLOSE.** Live menu **10,070 programs, 0 above the $0.0131 gate**, max
  live ceiling 0.003529; measured net **+$0.0000921/contract-hour** (11.7x below the best measured
  ceiling). Unchanged.

## External (change detection only)

- **Kalshi changelog** advanced from Nov 19 to a **Nov 26 batch** (RFQ listener sessions, weather
  point-market time zones, `historical/fills` now takes 100 tickers, stricter `side` validation).
  **No fee, incentive or liquidity-economics change.** https://docs.kalshi.com/changelog.md (2026-11-21)
- **Polymarket changelog**: no entry after the Nov 20 fee repricing, which is now **effective**
  (23:59 UTC Nov 20). `src/lib/scoring/price-edge.ts:65` still returns 0.07/0.04, so from today any
  shadow read overcharges crypto 7x and non-election politics 4x. Unwired; Lane A proposal stands.
  https://docs.polymarket.com/changelog.md (2026-11-21)
- **arXiv q-fin.TR**: newest is 2026-11-19 (nothing since yesterday's read); no prediction-market
  paper newer than 2026-11-17. Nothing to import.
- **GitHub**: only same-day-created repos by pushed_at; no new tool that changes an available
  measurement. MIT-licensed `tickfoundry-python` is a data-vendor SDK — a purchase, not a lever.
- **Reddit: unsampled, third day** (`.rss` 404, `.json` 403, old.reddit 404). No forum claim used.

---

## Ranking

1. **Parameterise and finish item 2 before anyone applies its verdict.** Value: it decides whether
   the book's **+$6,200** question profit is capital or a write-off. Today it is 24% tested and the
   verdict flips on 1c. Nothing else in this book is worth that much per hour of work.
2. **The 24h tenor floor** (already approved; +$26.2/day on the two-lane read, this morning's
   instrument) — the only measured positive dollar figure on the table. It is waiting on its own
   n≥150 trigger, not on a decision.
3. **Maker conversion (item 1)** — largest unmeasured lever and the one the brief's central finding
   points at, but 0 legs shadowed in four days. Unquantified, so it cannot outrank 1 or 2.
4. **Clip cap — do not ship** (withdrawn this morning; my sign-inversion check agrees).
5. **LIP — closed.** 0 of 10,070 live programs clear the gate.

### R1 — Pre-register item 2's tolerance and complete its population (Lane A, proposal only)

- **Hypothesis:** the question class's profit is decidable only if the fill test has a stated price
  tolerance and covers the legs the claim sits on.
- **Before:** rule reads "≥60% tape out as filled" → measured 36.0% at booked, 80.9% at +1c →
  **verdict FAIL or PASS depending on an unstated parameter**; population 89 of 543 STANDARD
  post-corpus question legs (16%).
- **After:** *"≥60% of mapped question legs carry a min-ask ≤ the booked price (tol 0, the strict
  basis — reachability is already an upper bound, so slack may not be added to an upper bound), and
  the reachable cohort's ROI ≥ 0, on ≥300 settled legs."* Measured today: 36.0% → FAIL, on 89 legs.
- **Decision rule / refutation:** if the completed ≥300-leg population reaches ≥60% at tol 0 with
  reachable ROI ≥ 0, the profit is real and the ladder may credit it. If it stays below 60%, the
  class is written off — and that is a $6,200 accounting change, which is why it needs 300 legs,
  not 89.
- **Do not** write the class off today on 24% coverage. **Do not** pass it on the +1c arm.

### Lane B (fixed, verified, committed)

The fill-stamp artifact's `basis.population` said *"opened at/after the L2 corpus epoch"* while the
scheduled tick scopes to **2026-10-29** — 59 days later — so `standardLegsInScope: 154` read as the
post-corpus population (it is 1,028). A reader, and the ≥300-leg gate arithmetic, inherited the
wrong denominator. The string now names the actual anchor and says the in-scope count is not the
post-corpus population. A stale wrapper comment claiming a moving anchor was corrected in the same
commit. Boundary test: no rule, size or gate moved — a label that described the wrong population.

**Revert:** `git revert <sha>` (scripts/standard-fill-stamp.ts, scripts/cron-scripts/copybot-standard-fill-chain.sh).

---

*No published rule, size, gate or booked figure was changed. Lane A items are proposals pending
approval. DB read with `mode=ro`. No prisma write.*
