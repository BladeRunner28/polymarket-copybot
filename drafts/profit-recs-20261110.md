# Profit review 2026-11-10 — the fix landed on the parser, not on the ledger

http://localhost:3013/drafts/profit-recs-20261110

Instrument: `scripts/profit-postfix-integrity.py` (read-only, self-tests pass, committed with this file).
Basis everywhere: **cost = `simulatedPositionSize` = DOLLARS at risk**, deduped to the first leg per
bot|wallet|market|outcome **within status class**, CIs are market-clustered bootstraps (2,000 draws),
and the price is **the price of the token actually bought**: the wallet's own fill on a leg whose
booked price is its complement, otherwise the booked entry. Bands are assigned by that price, so a
repriced leg moves to the band it was really bought in — the read `profit-price-side.py` §6 explicitly
declines to give.

Two basis errors I made and fixed before quoting anything (recorded because they are the kind that
would have made this review unfalsifiable):

- I first credited every "consistent" leg with the **wallet's** fill when it was 1–6c better. On the
  `/p` arithmetic a 0.14 fill against a 0.20 book is +43% on the same exit, and it inflated the cheap
  band by 40x. Fixed: only an inverted leg is repriced.
- I first deduped across all statuses, so an **open** first leg shadowed a **finished** later leg with
  the same key. Fixed: dedupe within class (that is the 2,063 → 2,002 leg difference).

---

## 0. What the fix fixed, and what it did not

`fbf9073` (2026-11-09 09:15 CST) repaired the **write path**. Verified today:

- **53 legs opened since the fix, 0 carrying the complement**, 25 settled. The acceptance clause
  ("INVERTED n = 0 on the next 150 settled legs") is 25/150 in and holding.
- **0 of 130 open legs are affected.** My working hypothesis coming in — a right mark divided by a
  wrong entry, inflating `unrealizedPnl` hourly — is **false**. Every inverted leg is finished. There
  is no live mark/entry mismatch to unwind.

The **ledger** was not repaired:

- **137 finished legs still book the sibling token's price**: $2,954 notional, **booked +$5,599 →
  true −$36**. They hold **45% of the book's booked profit**.
- Book: **+$12,524 booked (+18.9%) → +$6,889 true (+10.4%)** — a $5,635 (1.8x) overstatement that
  Dashboard, DailyReport, `PnlSnapshot` and `capital-data` all still reproduce.
- **The 7-day C-200 ladder gate, the dashboard's own basis:** booked **+$2,474 = PASS on rung 1**
  ($1,750); true **−$377 = fail**. The ladder is one rung from an advance on a week that lost money.

Correction to yesterday's card, load-bearing enough to record: **the class is not a 2026-10-26
regression.** By provenance join it opens **26 legs in July, 21 in August, 26 in October, then 64 in
the first nine days of November.** What is new is the RATE. "First opened 2026-10-26" was a property
of the `ruleSetVersion >= 49` filter, not of the defect.

---

## 1. The map, re-banded by the price actually paid

All-time, 5,759 finished legs, $66,319 notional:

| band | n | notional | ROI (true) | CI95 | tol |
|---|---|---|---|---|---|
| 0.0–0.2 | 527 | $12,491 | **+50.9%** | [+8.3, +102.2] | **+8.3pp** |
| 0.2–0.4 | 927 | $10,943 | **+13.1%** | [+0.8, +26.0] | **+5.0pp** |
| 0.4–0.6 | 1,930 | $18,121 | −5.6% | [−11.7, +0.5] | −2.9 |
| 0.6–0.8 | 1,195 | $12,119 | +2.0% | [−2.8, +6.5] | −4.1 |
| 0.8–1.0 | 1,180 | $12,646 | −0.9% | [−3.9, +1.4] | −8.2 |

`tol` = realised hit% − average price paid = **the entry slippage in percentage points the band can
absorb before it is loss-making.** Every fee and every fill assumption has to live inside that number.

- **Two cells are CI-positive, not one:** the cheap band (+50.9%) and 0.2–0.4 (+13.1%). Together they
  are 35% of notional and 113% of the book's true profit ($6,355 + $1,432 of $6,889).
- The 0.4–0.6 block is still the largest notional block (27%) at −5.6%, but its CI touches zero and
  **the live ruleset barely trades it (2 legs in the current regime)** — it is history, not a live leak.
- **Ex-top-10 all-time +0.6%**; 90d ex-top-10 −0.1%. The profit is still 10 legs.

### The live regime breaks the cheap band — and that is the finding

Opened since 2026-10-26 (325 legs, $7,188), the whole book is **−11.9%** and the split is not even:

| cell | n | notional | ROI | CI95 |
|---|---|---|---|---|
| **0.0–0.2** | 65 | $2,763 (38% of live) | **−33.2%** | [−57.7, **−0.2**] |
| 0.2–0.4 | 113 | $1,386 | +11.2% | [−16.8, +41.0] |
| 0.6–0.8 | 108 | $1,325 | −7.8% | [−21.3, +5.2] |
| 0.8–1.0 | 37 | $1,707 | +0.5% | [−14.0, +11.6] |

**The band that is the book's entire engine is the band that is currently losing money, and it excludes
zero on the negative side.** Hit rate 7.7% against a 12.1% break-even. The bot is putting 38% of live
notional into the one cell whose forward sign has flipped.

This is the single most important number in today's review, and it does not settle anything on its own:
n=65, SE ≈ ±11pp on the hit rate, and the regime is 15 days old. What it does do is kill the plan the
all-time table invites — "the cheap band pays, fund it" — because that plan is priced on the era that
ended on 2026-10-26.

---

## 2. The obvious lever inverts with the window, so I withdrew it

Coming in, the clean trade looked like lane capital efficiency. All-time:

- **BANKROLL_200: +25.5%, 1.6d hold, $0.1657 per capital-day**
- **STANDARD: +3.1%, 13.2d hold, $0.0027 per capital-day** — a **61x** gap, on 67% of notional.

That writes "cap STANDARD, fund C-200". **It is fitted to the wrong window.** Since 2026-10-26:

- **BANKROLL_200: −16.2% on 217 legs, −$0.2474 per capital-day**
- **STANDARD: +6.7% on 108 legs, +$0.0997 per capital-day**

The lane the ladder is built on is the loser in the live regime; the lane with 61x worse all-time
efficiency is the survivor. Both are 0.6–0.7d holds there, so it is not a turnover artefact.
**No lane-mix cap is proposable today** — the lever's sign flips between the two windows, and I will
not pick the window that suits a proposal.

---

## 3. Wallets: the two "stars" were the defect

- `0x885ffdf3` — booked **+109.5%** (264 legs) → true **+10.2%**; 39 inverted legs.
- `0xf5a3504ad3` — booked **+123.8%** (55 legs) → true **−18.2%**; 30 of 55 legs inverted.
- The six wallets carrying ≥5 inverted legs hold **51% of booked profit and 12% of true profit**; every
  one of their per-wallet CIs spans zero.
- **27 of the 53 wallets with ≥20 finished legs are true-ROI positive: 51%.** A screen of 53 producing
  a coin flip has found nothing. Consistent with the standing wallet null — no wallet action, and no
  new wallet machinery, follows from today's data.

---

## 4. Prior numbers that do not reconcile (recorded, not resolved in my favour)

- **7d true gate:** −$377 here vs −$671 in `profit-price-side` §7. Different population (163 vs 143
  legs — mine spans all rule versions, that one filters `rv>=49`) and a different window edge. **Both
  fail rung 1**; the verdict is robust, the figure is not. Quote the script you ran.
- **Book totals vs yesterday:** +$12,524/+$6,889 here vs +$9,264/+$3,623 there. Population difference,
  not disagreement: mine includes pre-`rv49` legs. On the shared `rv>=49` population my booked figure
  is $10,550 vs its $9,264 — that residual is the dedupe rule (I dedupe within status class, it dedupes
  over a population already filtered to `realizedPnl IS NOT NULL`). Same direction, same verdict.
- **Cheap band in the live era:** `profit-velocity` §AM.7 has CI [−12.1, +231.0] on 38 legs; I get
  −33.2% [−57.7, −0.2] on 65 legs post-10-26. Different window AND different banding (booked vs true).
  The true banding is the one to quote; do not reuse the older number.
- The 5-band up-weight arm ("+$5,067 all-time, the only CI-positive sizing change") was priced with 36
  fake cheap-band legs inside the cheap band. On the true basis those legs are 0.8–0.9 favourites and
  the cheap band is *more* cleanly positive, so the arm's premise survives the correction; its blocker
  was never PnL, it was the clamp (at $18 against a $20 cap, 2.0x and 1.5x are the same trade).
  **No new proposal from this; the prior closure stands.**

---

# Recommendations

Ranked by expected value. Nothing here is applied: everything that changes what the bot decides or how
much it risks is **Lane A — propose only.**

### 1. Repair the 137 rows so the ladder stops reading a number the fix disproved (Lane A, 1h)

- **Hypothesis:** the `entryPrice` on the 137 inverted legs is the sibling token's price, so re-pricing
  those rows at the venue's own label moves the book to +$6,889 and turns this week's rung-1 PASS into
  a fail. Falsifiable on 137 rows.
- **Measurement:** `scripts/profit-postfix-integrity.py` §A/§B. Per leg: set `entryPrice` to the token
  price at the trade minute (the same read `src/lib/outcome-price.ts` now performs), recompute
  `realizedPnl` on the payoff identity, rebuild `BotBankroll` + `PnlSnapshot`. 137 rows, $2,954
  notional, **0 open legs touched**.
- **Decision rule:** apply when re-deriving the entry from the venue label reproduces the wallet's fill
  within 0.02 on **≥95%** of the 137 legs (measured: median 0.007, p90 0.020 — already met) **and** the
  operator accepts a −$5,635 restatement of published PnL.
- **Refutation:** a tape check of ≥20 legs showing the **booked** price is what those tokens actually
  traded at. If that holds, the fix was wrong and the rows are right.
- **Expected effect on profit:** $0. It removes a false +$2,474 PASS from the one gate that converts PnL
  into a capital decision.
- **Cost:** 1h, plus whatever the operator wants for the retroactive EOD restatement.

### 2. Measure the cheap band's fill tolerance — both CI-positive cells live or die here (Lane B, 2h)

- **Hypothesis:** the two CI-positive cells are achievable at the price we pay; if the measured fill
  premium over the booked price is ≤3c, they are the only cells worth sizing into.
- **Measurement:** extend `scripts/c200-bookwalk-taker.py` to **STANDARD** 0.0–0.4 legs (the C-200 arm
  is closed on its own pre-registered metric and is not reopened): L2 book walk at dispatch, VWAP plus
  the documented per-market taker fee, against the booked entry. Deliverable: median/mean premium in
  cents and each cell's ROI recomputed at that fill against its own tolerance (**+8.3pp** cheap,
  **+5.0pp** on 0.2–0.4).
- **Decision rule:** size a cell only if, at the measured fill, its ROI stays CI>0 with median premium
  ≤3c. If median premium ≥8.3c, the cheap band's entire edge is priced away and no cheap-band action is
  ever justified.
- **Refutation:** median premium ≤3c **and** the fill-adjusted ROI's CI includes zero — then neither
  cell is real, the book has no proven edge anywhere, and the correct action is to shrink gross rather
  than reallocate it.
- **Expected effect on profit:** 0 today; it gates 113% of the book's true profit.
- **Cost:** 2h, read-only, artifact only.

### 3. No sizing change this week — the measurement is not there (Lane A: nothing to apply)

The honest answer for anything that changes allocation. Three independent reasons, each sufficient:

- The lane ranking **flips sign** between all-time and the live regime (§2), so any lane-mix proposal
  written today is a window artefact.
- The cheap band's forward record **reversed sign** in the current regime (§1) and the regime is 15
  days old at n=65 — too small to act on, too clean to ignore.
- Every pre-2026-11-09 leg is contaminated by a quantified booking defect (137 legs, 45% of booked
  profit) that no sizing shadow has been re-priced against.

**The measurement that unlocks one:** re-run this script when the post-fix cohort reaches **150 settled
legs** (~2 weeks at the current rate). Decision rule: size the cheap band when its post-fix CI excludes
zero on those 150; refutation: post-fix CI-negative at n≥150 → close the band rather than size it.

---

**IF YOU WEREN'T HERE:** repair the 137 rows and reprint the ladder gate on the true basis — and keep
the ladder held at v71 this week, because the PASS that would advance it is arithmetic that no longer
exists.

---

### Instrument repairs performed directly (Lane B, no approval needed)

- New read-only `scripts/profit-postfix-integrity.py`, 6 sections, self-tests pass (identity reproduces
  on 12,739/12,739 legs, synthetic reprice exact, classification partitions 13,158/13,158). No prisma
  write, no RuleSet read or write, nothing in a decision path.
- Card `ledger-price-side-repair` added (Scheduled, awaiting-approval) so the ask is on the board.
- Nothing else touched: no rule, threshold, size or gate moved; no `apply-v*.ts` run.
