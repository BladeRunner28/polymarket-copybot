# Fee booking in the ledger — REFUTED on its own 30-day rung clause (0 of 30 days). Withdraw; keep the fee as a print.

http://localhost:3013/drafts/fee-booking-net-ledger-20261102

**Card:** `fee-booking-net-ledger` (Backlog, Lane A, proposed 2026-11-02 by `drafts/profit-recs-20261102.md`).
**This run:** measurement only. No prisma write, no RuleSet read or write, no rule, size, gate, booking or
threshold changed, nothing merged to main. One new read-only instrument: `scripts/fee-ladder-reread.py`
(`immutable=1`, sqlite3 read-only, imports the fee law from `scripts/profit-fee-net.py` so the two cannot drift).

The fee is real, large, and unbooked — that part of the card is confirmed exactly. What the card was never
allowed to assume is that booking it would change the ladder's mind. It does not, on the window the card
pre-registered, and the card said in advance what to do about that. This memo does it.

---

## 1. Verdict, against the card's own pre-registration

The card's decision rule, pre-registered in the review it came from and repeated verbatim on the card:

> **DECISION RULE:** adopt when the modelled fee is **≥10% of booked PnL** **AND** a 30-day net re-read
> flips the rung verdict on **≥1 day**. **REFUTATION:** if venue-truth pricing puts the finished book's fee
> below **$600** … or a 30-day net re-read **never flips a rung day**, withdraw and keep the fee as a
> one-line EOD print.

| clause | pre-registered test | measured | result |
| --- | --- | --- | --- |
| 1 | modelled fee ≥ 10% of booked PnL | **27.13%** bet-level ($1,183 on $4,361 booked), **19.93%** leg-level ($3,038 on $15,241); venue-truth bases $3,038 / $3,537 / $4,996, all ≫ $600 | **MET** |
| 2 | 30-day net re-read flips the rung verdict on ≥1 day | **0 of 30 days** — leg basis (the gate's own population), **0 of 30** bet basis, **0 of 30** on the per-day variant | **FAILED** |

**Both clauses were required. Clause 2 fails, so the card's own refutation fires: withdraw the ledger
booking and keep the fee as a one-line print.** No ledger change is proposed. The operator decision left
open is whether to accept the withdrawal or amend the rule (options in §7) — not whether to book.

---

## 2. The measurement that settles it

Gate definition taken from the code that actually advances the ladder
(`src/app/page.tsx` `C200_PHASES` / `GOAL POLICY v2`): rungs **250 / 500 / 1,000 / 2,000 / 5,000 $/day**,
advance test = **trailing 7-day SETTLED SUM ≥ rung × 7**, settled = `status in (closed, resolved)` on
`BANKROLL_200`, day bucket = **local calendar day** of `(closedAt ?? resolvedAt)` (the page's `c200DayKey`).
For every complete day in the window the script recomputes that verdict twice — GROSS on booked
`realizedPnl`, NET on `realizedPnl − enter-fee` — and a **flip** is a day whose rung index falls.

Leg basis, all 30 complete local days 2026-10-03 … 2026-11-01 (the gate sums rows, so this is the
authoritative column; bet basis gives the same verdicts and is printed by the script):

| window end | legs | gross 7d | fee 7d | net 7d | rung G | rung N | flip |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-10-03 | 175 | 2,223.20 | 63.97 | 2,159.23 | 1 | 1 | — |
| 2026-10-04 | 162 | 2,167.33 | 53.63 | 2,113.70 | 1 | 1 | — |
| 2026-10-05 | 176 | 985.52 | 41.34 | 944.18 | 0 | 0 | — |
| 2026-10-06 | 183 | 1,663.10 | 44.44 | 1,618.66 | 0 | 0 | — |
| 2026-10-07 | 192 | 1,540.52 | 51.73 | 1,488.79 | 0 | 0 | — |
| 2026-10-08 | 201 | 1,507.36 | 53.95 | 1,453.41 | 0 | 0 | — |
| 2026-10-09 | 213 | 1,708.78 | 60.07 | 1,648.71 | 0 | 0 | — |
| 2026-10-10 | 181 | 1,453.70 | 57.56 | 1,396.14 | 0 | 0 | — |
| 2026-10-11 | 172 | 1,444.37 | 59.48 | 1,384.89 | 0 | 0 | — |
| 2026-10-12 | 156 | 763.36 | 54.89 | 708.47 | 0 | 0 | — |
| 2026-10-13 | 132 | 177.82 | 48.78 | 129.04 | 0 | 0 | — |
| 2026-10-14 | 138 | 324.09 | 46.64 | 277.45 | 0 | 0 | — |
| 2026-10-15 | 117 | 159.99 | 43.65 | 116.34 | 0 | 0 | — |
| 2026-10-16 | 98 | −121.86 | 35.26 | −157.12 | 0 | 0 | — |
| 2026-10-17 | 81 | −222.88 | 39.98 | −262.86 | 0 | 0 | — |
| 2026-10-18 | 83 | 305.35 | 44.13 | 261.22 | 0 | 0 | — |
| 2026-10-19 | 74 | 391.81 | 41.01 | 350.80 | 0 | 0 | — |
| 2026-10-20 | 75 | 244.83 | 46.06 | 198.77 | 0 | 0 | — |
| 2026-10-21 | 56 | 139.18 | 41.78 | 97.40 | 0 | 0 | — |
| 2026-10-22 | 53 | 305.57 | 39.49 | 266.08 | 0 | 0 | — |
| 2026-10-23 | 53 | 333.95 | 40.62 | 293.33 | 0 | 0 | — |
| 2026-10-24 | 38 | 343.46 | 26.21 | 317.25 | 0 | 0 | — |
| 2026-10-25 | 40 | −217.51 | 22.99 | −240.50 | 0 | 0 | — |
| 2026-10-26 | 52 | −467.34 | 35.24 | −502.58 | 0 | 0 | — |
| 2026-10-27 | 48 | −407.47 | 33.61 | −441.08 | 0 | 0 | — |
| 2026-10-28 | 49 | −452.33 | 37.13 | −489.46 | 0 | 0 | — |
| 2026-10-29 | 51 | 415.10 | 52.76 | 362.34 | 0 | 0 | — |
| 2026-10-30 | 51 | 466.39 | 52.83 | 413.56 | 0 | 0 | — |
| 2026-10-31 | 53 | 597.46 | 50.92 | 546.54 | 0 | 0 | — |
| 2026-11-01 | 47 | 551.63 | 54.71 | 496.92 | 0 | 0 | — |

**0 flips. Two of the 30 days reached a rung at all (2026-10-03, 2026-10-04), and the fee did not take
rung 1 back from either.** The best window cleared the $1,750 rung-1 gate by **$473.20 gross** and still
cleared it by **$409.23 net**; the next blocker ($500/day, $3,500 over the window) was **$1,276.80** away
gross and **$1,340.77** away net. The fee would have to be **7.4× larger** (≈$473 instead of $63.97) to pull
that week back to rung 0.

For a flip to happen at all, the trailing 7-day **gross** sum has to land inside the fee's own width
($23–$64 per window here) above a rung boundary. Over the 30-day window the closest approach was
**$473** — seven times the fee. That is the whole mechanism, and it is arithmetic, not luck.

30-day totals (leg basis): gross **$2,287.01**, fee **$199.58**, net **$2,087.43** — the fee is **8.73%**
of booked PnL on this window, i.e. the *other* clause's 10% bar is not even met on the recent month.

---

## 3. The one day in 90 where it does bite — and why it is not enough

I ran the same re-read over 90 days (2026-08-04 … 2026-11-01) to see whether the 30-day answer was a
window artefact. It is not an artefact, but it is a near miss, and the operator should see it:

| window end | basis | gross 7d | fee 7d | net 7d | rung G → N | flip |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-09-21 | leg | 1,798.78 | 107.93 | 1,676.75 | 1 → 0 | **YES** (net short by $73.25) |
| 2026-09-21 | bet | 1,751.27 | 107.93 | 1,643.34 | 1 → 0 | **YES** (gross clears by $1.27, net short by $106.66) |

**That single day is 100% of the value the booking would have had on the ladder in 90 days: it retracts
the Phase-1 week the ladder actually cleared on 2026-09-21.** Two reasons it does not rescue the card:

1. It is **outside the pre-registered 30-day window**, and the pre-registration exists precisely so the
   window cannot be picked after the answer is known. Re-windowing to 90 days to reach a pass is the
   failure mode the rule was written to prevent.
2. It predates **GOAL POLICY v2 (2026-10-12)**, which is what made the trailing-sum gate exist at all. The
   v1 rule in force at the time required "7 consecutive days each ≥ target", and the page's own note
   records that test as structurally unsatisfiable for this book (median settled day $0.15; best
   consecutive run ever 2 days at either level). So the flip is a v2 back-fit onto a week that the rule in
   force then would not have called an advance week.

The per-day variant ("did that day alone earn the rung", the only other reading of "rung day") is **0 of
30 and 0 of 90** — the fee never straddles a daily rung target either. So there is no reading of the
clause that produces a pass in the pre-registered window.

---

## 4. What the fee does bite — all of it re-verified this run, none of it withdrawn

Reproduced from `python3 scripts/profit-fee-net.py` (identical to the review's numbers, so the
disagreement is not in the measurement):

| basis | bets | notional | gross | fee | net (one fee) | $/1k-capital-day gross → net |
| --- | --- | --- | --- | --- | --- | --- |
| all finished, bet-level | 4,890 | $52,494 | +8.31% | 2.25% | **+6.05%** | 8.52 → **6.21** (−27.1%) |
| STANDARD | 3,591 | $43,463 | +4.16% | 2.03% | +2.13% | 3.63 → **1.86** (−48.8%) |
| BANKROLL_200 | 1,299 | $9,031 | +28.28% | 3.35% | +24.93% | 186.91 → 164.77 |
| all finished, leg-level | 12,429 | $135,467 | +11.25% | 2.24% | +9.01% | 11.95 → 9.57 |

- **The closed (mark-exit) half of the book flips sign on the entry fee alone:** 3,216 bets / $32,966
  (63% of bet-level notional) go **+1.86% → −0.21%**.
- **BANKROLL_200's 0.4–0.6 band flips sign per capital-day:** 10.56 → **−3.92** $/1k-capital-day.
- **Capital requirement for the rungs rises 37.2%:** $500/day needs $80,541 deployed, not $58,693.
- Fee law/rate not in question: `data/fee-sign-flip-report.json` prices the venue's own schedule at
  **$4,996.97 vs $5,024.02** proxy on 12,710 legs (99.68% coverage, 2 sign flips).

Those are **rate-level and scoreboard-level facts**. They are not rung-verdict facts, and this card's
adoption test was written on the rung. The review said it plainly in its own "contradictions" section —
*"the fee does not flip any rung arithmetic in direction, and the ladder was already 88× short"* — so the
refutation was foreordained by the card's own analysis. Recording that rather than quietly re-scoping.

---

## 5. What a ledger booking would actually cost, and what it would silently rewrite

This is why the refutation matters beyond procedure — the change is not a print:

- **Schema:** `PaperTrade` has no fee column (`prisma/schema.prisma:177-217`). A migration on a **12.6 GB**
  live `dev.db` plus a backfill over **12,429 finished legs** (fee is computable from `entryPrice`,
  `simulatedPositionSize` and the slug-keyword rate, so no venue data is needed — but the write is
  retroactive and irreversible in practice).
- **The booking basis is itself an open question:** one fee **$3,038**, two fees at implied exit
  **$3,537**, exit=entry **$4,996** on the *identical* legs. That is card `fee-exit-basis-instruments`
  (Lane B, unfixed). Booking now freezes one of three numbers that differ by 64%.
- **Retroactive rewrite of every history the operator reads:** `realizedPnl` feeds the cumulative PnL
  series, win rate, `PnlSnapshot`, the EOD report and the ladder history. Every past number moves; none of
  today's decisions change.
- **It would not fix the decision loop either.** The card's WHY says the decision loop is fee-blind, but a
  ledger column does not feed a gate — `price-edge.ts` is `status: "shadow"` and wired to nothing, and this
  card does not wire it. Booking the ledger fixes the *scoreboard only*.

Against that: **0 days of ladder verdict in 30, 1 day in 90.** The cost/benefit is not close.

---

## 6. The refutation conditions (what would revive this card — and what already killed it)

**Killed by (fired, measured above):** a 30-day net re-read that never flips a rung day → **0 of 30** on
both population bases and on the per-day variant. The other refutation branch did **not** fire (venue-truth
fee $3,038–$4,996 ≫ the $600 floor), so the withdrawal rests on clause 2 alone — stated explicitly so no
one reads this as a venue-pricing problem.

**Revive if any of these becomes true, measured with the same script:**

1. **The book scales into a rung boundary.** The failure here is distance, not materiality: a flip needs
   the trailing 7-day gross sum within ~$25–$110 of `rung × 7`. At the ladder's opening rung that means
   trailing 7-day gross in **[$1,750, $1,750 + fee]** — the book will live there as soon as the C-200 lane
   is actually being advanced toward. Re-run `scripts/fee-ladder-reread.py --days 30`; **one flip day and
   clause 2 passes**, with no re-windowing required.
2. **The ladder gate changes basis** from a trailing sum to a per-capital-day *rate*. Every rate comparison
   in §4 already shows the fee moving the answer by 27–49%; the card would be trivially met on that gate.
3. **The fee rate is revised** materially upward (0.05 → 0.10 doubles the fee width and the whole §4 table).
4. **A decision path starts reading booked PnL net** — that is a different card and would need its own
   measurement; it is not this one.

---

## 7. What the operator is being asked to decide

Nothing is applied. The options, in the order I would take them:

- **(a) Accept the withdrawal (default, and my recommendation).** Leave `realizedPnl` gross, leave the
  ladder as it reads today, close the card on its own pre-registered refutation. Record the 27.1% haircut
  as a **scoreboard caveat** in the EOD line rather than a ledger change.
- **(b) The card's own fallback — "the fee as a one-line EOD print".** **Not implemented and not
  implemented by me:** `src/lib/report.ts` and `scripts/report-daily.ts` print **no** fee line today
  (verified by grep, 0 matches). Adding one is a report change and needs an explicit yes; it would print
  modelled fee and net-vs-gross for the day, from the same law, read-only.
- **(c) Amend the rule and book it anyway on scoreboard-honesty grounds.** Legitimate, but it is a
  *different* justification than the one pre-registered, and it should be argued as such — and it should
  wait for `fee-exit-basis-instruments` so the basis is settled first, and it should write a **new column**
  rather than mutating `realizedPnl`, so the existing book stays comparable.
- **(d) Nothing at all.** Defensible: on the last 30 days the fee is 8.73% of booked PnL and changes no
  verdict; the scoreboard caveat in the EOD covers it.

---

## 8. Reproduce (every number above)

```
python3 scripts/fee-ladder-reread.py --db prisma/dev.db --days 30   # 0 of 30 flips (this memo's clause 2)
python3 scripts/fee-ladder-reread.py --db prisma/dev.db --days 90   # 1 of 90: 2026-09-21
python3 -m py_compile scripts/fee-ladder-reread.py
python3 scripts/profit-fee-net.py                                   # §1/§4 tables, unchanged from the review
```

`fee-ladder-reread.py` opens the DB with `immutable=1`, writes nothing, imports the fee law from
`profit-fee-net.py`, and prints its own population, basis and window on every run. It prints **both**
population bases (leg = the gate's own rows, bet = first leg per wallet/market/outcome), the rung indices,
the flip flag, the distance to the nearest blocking rung, and a clearly-labelled per-day variant that is
**not** the advance gate. If a future run prints a flip, the card reopens on clause 2 with no argument.

### Provenance

| figure | source |
| --- | --- |
| 0 of 30 rung flips, leg and bet basis, per-day variant | `scripts/fee-ladder-reread.py --days 30` (this run) |
| 1 of 90: 2026-09-21 gross $1,798.78 → net $1,676.75 | `scripts/fee-ladder-reread.py --days 90` (this run) |
| gate definition (rungs, 7-day settled sum, local day key) | `src/app/page.tsx` `C200_PHASES`, `GOAL POLICY v2`, `c200DayKey` |
| gross/net ROI, fee %, $/1k-capital-day, closed-half sign flip, band sign flips | `scripts/profit-fee-net.py` §FN.1/§FN.2/§FN.5, unchanged |
| three fee bases $3,038 / $3,537 / $4,996 | `scripts/profit-fee-net.py` §FN.1 |
| venue truth $4,996.97 vs $5,024.02, 99.68% coverage, 2 sign flips | `data/fee-sign-flip-report.json` (2026-10-22) |
| fee law and category rates 0.05/0.04/0.07 | `src/lib/scoring/price-edge.ts` `takerFeePerShare`, `categoryFeeRate` |
| no fee column; no fee line in the EOD | `prisma/schema.prisma:177-217`; grep `fee` in `src/lib/report.ts`, `scripts/report-daily.ts` = 0 |
| $500/day capital $58,693 → $80,541 (+37.2%) | §FN.4 |

*One new read-only file this run (`scripts/fee-ladder-reread.py`); one draft; one roadmap tag. **No prisma
write, no RuleSet row read or written, no rule/size/gate/booking/threshold changed, nothing merged.** Lane
A — this file is a recommendation, not a change.*

---

## BASIS RESOLVED (2026-11-02, card `fee-exit-basis-instruments`)

The open question this draft flagged in §"the booking basis is itself an open question" is now settled,
and it moves the numbers in this document — **downward, in the direction that strengthens the withdrawal**.

Both fee instruments were charging an early exit at the leg's **entry** price
(`c200-fee-reprice-archive.py: ex_docs = entry_docs`; `fee-sign-flip-test.py: cur *= 2.0`). The fee law
`p*(1-p)` goes to zero at the payoff extremes, so the exit leg was overstated by ~4x on exactly the legs
this book leaves: 83.4% of closed legs (7,500 / 8,988) exit below 0.05 or above 0.80; only 13.4% leave
within 1c of entry, so `exit ≈ entry` was never a defensible basis.

| fee bill, same legs (level = leg, isDemo = 0, 13,889 legs / $140,623.37 notional) | withdrawn basis | at the leg's own exit | delta |
| --- | --- | --- | --- |
| docs model, two fees | $5,196.95 | **$3,735.56** (2.66% of notional) | −28.1% |
| published schedule, two fees | $5,233.57 | $3,764.97 | −28.1% |
| archive min-law, two fees | $15,841.89 | $11,191.35 | −29.4% |
| flip-test joined population (12,849 legs, $140,210.39, 99.7% coverage) | $5,186.78 current / $5,159.20 venue | **$3,725.38 / $3,698.53** | −28.1% |

The exit price is the one written on the row: `PaperTrade.currentPrice` on **8,988 / 8,988** closed legs,
identity `c = p*(1+pnl/size)` as fallback (used 0 times here), and the two bases disagree on exactly
**1** leg (0.1354). `'undetermined'` is now a printed category, never a silent fall back to the entry price.

**What this does not change:** clause 2 — the withdrawal's actual ground — is untouched. `$3,736` still
clears the $600 refutation floor by 6x, and `scripts/fee-ladder-reread.py` charges the **entry fee only**,
so its 0-of-30 rung flips and its $199.58 / 30d figure need no restatement. A smaller fee only widens the
margin by which the fee is too small to take rung 1 back.

Line 238 of the source table (`venue truth $4,996.97 vs $5,024.02 … 2026-10-22`) is now superseded by
`data/fee-sign-flip-report.json` regenerated 2026-11-02 on the corrected basis.
