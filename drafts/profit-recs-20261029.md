# Profit review — 2026-10-29

http://localhost:3013/drafts/profit-recs-20261029

**Cost basis on every ROI below: `simulatedPositionSize` = dollars at risk, never shares.**
A BUY of `$n` at `p` is `n/p` shares; settlement at `s` realises `n*(s/p − 1)`, an exit at `c`
realises `n*(c/p − 1)`. A ROI line without that basis is not comparable to any other line here.

Every figure is computed by `scripts/profit-sellside.py` (§SS.1–SS.8, this commit), which imports
the settlement-truth reader (`truth_of`) from the committed `scripts/profit-velocity.py` rather
than re-implementing it. Reproduce:

```
DATA_MODE=live python3 scripts/profit-sellside.py          # first run fetches, caches data/sellside-flow.json
python3 scripts/profit-sellside.py --offline               # cache only, no wire
```

---

## The copy inherits the entry and none of the repricing

Three facts, measured today on data that has been in the repository all along and never read
this way.

**1. The wallets we copy are 2.5-hour traders.** `monitor-trades.ts:130` reads
`if (t.side !== "BUY") continue; // copy entries only, not exits`, so `ObservedTrade` holds
**4,660,889 BUY rows and 10 SELL rows**. Fetched directly from the data API for the 23 tracked
wallets that respond (6 × 500 prints each): **245 SELL prints against 6,557 BUY — 3.6% of prints
but 9.7% of notional ($1.01M of $10.4M)**. From those, **155 round trips** (§SS.2):

- median hold before the sell: **2.5 hours** (p10 0.3h, p90 11.6h), **94% inside 24h**
- sell price − buy price: **median +41.9pp**, mean +26.6pp, **72% sold higher**

**2. Our fills do not move.** For all 12,346 finished legs, the mark for our own outcome at
`openedAt + h` from the recorder's own `MarketSnapshot` (§SS.5, **12,254 legs covered at 2.5h =
99.3%**):

- **+2.5h: median +0.0pp, mean +0.0pp; rose ≥5pp 11%, fell ≥5pp 11%** — perfectly symmetric
- +24h (7,173 legs): median +0.2pp, mean +0.0pp; 19% / 18%
- +168h (1,038 legs): median +0.5pp, mean −1.1pp; 24% / 19%
- control, −24h → entry (877 legs): median +0.0pp, mean −2.9pp

**3. It does not move at any latency either.** Decision lag = `DecisionJournal.createdAt −
ObservedTrade.timestamp`, 12,826 legs: **median 20.2 min**, p10 3.5 min, p90 172.6 min. Settled
ROI by lag (§SS.7):

- **<5 min: +21.1%** (688 settled legs, $8,705)
- 5–15 min: +6.3% (1,125 / $14,079)
- 15–30 min: +30.8% (641 / $8,159)
- 30–60 min: +38.6% (232 / $3,045)
- 1–4h: **+60.4%** (519 / $6,177)
- >4h: +19.4% (156 / $1,627)
- and the +2.5h mark change is **+0.5 / +0.5 / 0.0 / −0.2 / 0.0 / 0.0pp** across those buckets

Being late is not what costs us money. **Being early is worth nothing.** Every bucket, from
three minutes to four hours, admits a cohort whose marks do not reprice.

### What that means, stated as an accounting identity rather than an opinion

The book's realised PnL splits cleanly by how a leg left (§SS.8):

- **settled: 3,361 legs, $41,792 notional → +$10,455 (+25.0%)**
- **early-closed: 8,985 legs, $92,149 notional → +$3,477 (+3.8%)**

And the early-closed half is *not* the v66 population — it is 6,503 dead-slug 404 expiries whose
marks are calibrated to ±5c (2026-10-28, independent). The exits that hurt are the ones taken at
a **live** mark on an **unsettled** market, which is exactly what a calendar rail does. Pricing
that on today's population (§SS.5, settled subsets only):

- exit at the **+2.5h** mark instead of holding: **−$10,169.65** (hold +$10,555.71 vs exit
  +$386.06 on $41,671), market-clustered 95% CI [−25,995, +1,139] over **1,371 markets**
- exit at **+24h**: **−$7,681.84** (hold +$7,150.40 vs exit −$531.44 on $30,822), CI
  [−23,318, +1,784] over 788 markets
- exit at **+168h**: **+$1,049.80** (hold −$855.37 vs exit +$194.43 on $3,780), CI [−912, +3,018]
  over 68 markets

The 168h line is the only one that favours exiting and it is an artefact of coverage, not of
horizon: coverage falls 12,254 → 7,173 → **1,038** legs, so that subset is the *recent* cohort,
and hold is −22.6% there because the recent cohort is −22.6% (STANDARD 30d: −2.9%), not because
168 hours is special. It is reported so nobody quotes it as support for a rail.

---

## The three doors this closes — including one I opened yesterday

**Copy the exit. Dead.** I expected this to be the finding and it is not: the wallets sell at
+41.9pp because the price moves *for them*; our fills' marks do not move at all (§SS.5), so
there is no exit price to capture. §SS.3 confirms the pairing is nearly empty rather than
merely unprofitable — of 12,346 settled legs, **4** had a later same-wallet sell inside the
fetch window (the API's window reaches hours-to-days back; our legs are weeks old). Alpha
+$30.92 on $54.97 over 3 markets. That is not a result, it is a missing denominator, and the
fix is the instrument shipped in #3 below.

**A fast lane. Dead.** Lag is not monotonically harmful — it is monotonically *helpful* up to
4h in the point estimates (§SS.7), and no bucket shows forward drift. A 5-minute cadence would
buy a cohort that looks exactly like the one we already own. Whatever the wallets' edge is, it
is not "we saw the print late".

**Wallet rank. Still no verdict, and now for a reason that is itself a finding.** On the
continuation of the 2026-10-21 test — which pre-registered "act when the rank correlation is
below +0.15 on ≥30 overlapping wallets" and declined to act on 16 — today's population is
1,041 wallets with truth-joined bets, but only **27** have ≥8 bets in each half of a
2026-08-20 split (§SS.6):

- Spearman ρ(H1 edge, H2 edge) = **−0.100**, permutation p = **0.616** (2,000 shuffles)
- top-minus-bottom quintile forward spread: **−2.58pp**, shuffled-null p = 0.680 (null p95 +8.23pp)
- H1 edge mean −0.76pp, H2 edge mean −0.31pp — the population is calibrated to zero, which is
  what a copier of *entries* into an efficient market should measure

The reason the sample cannot grow is **truth coverage: 4,005 markets cached against 295,404
distinct conditionIds seen in `ObservedTrade` — 1.4%.** The wallet axis is unanswerable at n≥30
without fetching settlement truth for the markets our wallets actually trade, and that is a
finite, priceable job (~2,000 markets by print count) rather than an open question. Direction
today is the same as 10-21: none.

---

## #1 — Book STANDARD's fills, because one cent of entry is worth 62% of the 90-day profit. Lane A, proposed.

**Hypothesis.** If the entry is the only variable that matters (the mark path is flat at every
horizon and every lag), then STANDARD's unbooked entry cost is the largest single error in the
profit record, and booking fills will move the 90-day realised return materially — the
fill-aware resolver that already runs for C-200 (`c6222f7`, 2026-10-28) is the instrument.

**Measurement.** §SS.8 prices the lever on the book itself: **1c better entry on every settled
leg is worth +$1,439.33 on the last 90 days' settled notional ($28,882) = 5.0% of notional**, and
+$1,891.61 all-time (4.5%). The 90-day realised result it would re-price is **+$2,329.01 on
$28,882 = +8.1%**. One cent is **62% of the entire 90-day profit.** The same run measures the
book's capital productivity at **$11.14 per $1k-capital-day** (finished book: $13,932 on $133,941
over 1,250,708 capital-days), which against the $5,000/day target implies **$448,858 of open
capital at the current edge — 87× the $5,155 actually deployed.**

**Decision rule.** Adopt STANDARD fill-aware booking when, over ≥300 forward legs, the
resolver-stamped entry is worse than the booked mid by a **median ≥0.5c** and the re-booked
90-day ROI falls by **≥1.0pp** — i.e. when the bias is large enough to change a decision. Below
that, keep the mid and say so in the EOD line.

**Refutation.** If the stamped fills come back within ±0.3c of the mid on ≥300 legs (the
resolver finds the ask is not where the paper price says it is), then the entry-price thesis is
worthless at STANDARD's sizes, the 5.0%-of-notional number is a fiction and this question closes
for the quarter — and the highest-EV item becomes capital, not execution.

**Expected effect.** $0 direct, and it re-prices every ROI in the file. It is ranked first
because 5.0% of notional is ~11× the largest sizing shadow ever measured in this book
(+$145 live-era for the band map) and because every future sizing read inherits the answer.
**Cost: 2h** — the resolver exists; this is STANDARD's call site plus a re-read.

---

## #2 — Retire v66's calendar trigger. Not gate it. Lane A, proposed — supersedes my own 10-28 proposal.

**Hypothesis.** The rail's only function is to protect the 1,300-leg cap, that cap has not bound
since the sweep (44 slots of headroom then, 297 in the no-sweep counterfactual, book shrinking
**−4.73 legs/day**), and every measured early-exit horizon on a live mark destroys settlement
value — so the correct action is deletion, not the cap-pressure gate I proposed yesterday.

**Measurement.** §SS.5, as above: 12,254 legs of mark path, 3,345 settled legs paired hold-vs-exit
at 2.5h/24h with market-clustered CIs over 1,371 and 788 markets; plus 2026-10-28 §AO's price of
the slot the rail buys ($0.168/leg ex-outlier, $117.97 for 701 slots, 2.3% ever refilled). The
rule's own scope today: `standardStaleExitHours 168`, `standardStaleExitBandMin 0.60`,
**12 open STANDARD legs / $112.60 in scope** — the 10-24 sweep cleared the aged book, so the rail
is nearly dry and the change is cheap now.

**Decision rule.** Delete the `t.botId === "STANDARD"` branch (`update-pnl.ts:270-292`) when
`standardStaleExitFires` has fired zero times on organic flow in the 14 days to the change and
the open-in-scope population is <20 legs. Both hold today (12 legs; the only fire ever was the
2026-10-24 sweep).

**Refutation.** If within 30 days of retirement the `[STANDARD] open-position cap` skip counter
reaches **≥20 copies blocked**, slot pressure was real, the rail was load-bearing, and it comes
back — as the cap-pressure gate, not the calendar. Counted from DecisionJournal, not argued.

**Expected effect.** Removes a mechanism whose one firing transferred **−48.36% of notional**
(−$831.70 on 167 priced legs, one market −$807.01) and whose stated benefit was $0.64/day of
forgone slot value. Direct today: protects 12 legs / $112.60 and the next fire. **Cost: 0.5h**
(delete one branch + keep the predicate exported and unit-tested so the gate can reuse it).

---

## #3 — The discarded SELL prints are now persisted. Lane B, done this commit.

`src/lib/sell-log.ts` appends one JSONL line per non-BUY print (wallet, market, outcome, price,
size, venue print time) to `data/wallet-sells.jsonl`, called from `monitor-trades.ts` immediately
before the `continue` that has been dropping them since June. No prisma write, no
`ObservedTrade` row, no scoring input, no RuleSet field: **it changes nothing the bot decides.**
Best-effort by construction, and duplicates are expected because the append happens before the
DB dedupe — documented in the header, dedupe on (wallet, market, outcome, timestamp, price, size).
`tests/sell-log.test.ts` pins verbatim capture, append ordering and the never-throw path;
`npx vitest run` on the two log suites 6/6, `tsc --noEmit` clean.

Why it matters even though #SS.3 says the exit is not copyable *today*: whether a tracked wallet's
exit carries information **at our cadence** is a forward question that cannot be asked
retroactively, because the prints were never kept. The wallet axis (#SS.6) is also blocked on
data, not on method — this is the cheap half of unblocking it.

---

## Contradictions I am not resolving silently

- **The 30-day book is two different books.** STANDARD: **−$359.72 on $12,577 (−2.9%)**;
  BANKROLL_200: **+$1,438.68 on $4,857 (+29.6%)**. The profitable lane is 28% of notional, holds
  9 open legs / $302, and its exposure cap does not bind (2026-10-20: ~70× headroom — its limit is
  the funnel). The losing lane is 72% of notional with no cap at all. I am not proposing to
  port the cap (refused 2026-10-20 for a 13.6× halt plus a portfolio-gate freeze precedent), but
  nobody should read "the band is the only axis" as "the lane is not".
- **"Early exits lose money" is only true of live marks.** The 8,985 early-closed legs are
  **+$3,477 (+3.8%)** and the 6,503 404 expiries among them are calibrated to ±5c. The loss is
  specific to exiting at a live mark on an unsettled market. Bundling the two would be the
  same category error the 10-24 draft had to retract.
- **Today's exit alphas have CIs that span zero** (−$10,170 [−25,995, +1,139]; −$7,682
  [−23,318, +1,784]). The point estimates are large and consistent across two horizons and 1,371
  markets; the intervals are not. #2 is proposed on the *mechanism* (a slot that never binds
  cannot be worth an exit) plus these point estimates, not on a significance claim.
- **The 168h horizon favours exiting** (+$1,049.80, 316 legs, 68 markets) — reported above with
  its coverage artefact. It is the one number in this file that argues against #2 and I am not
  hiding it.
- **The 10-21 wallet read (n=16) and today's (n=27) agree in sign and neither clears the bar.**
  Both are below the pre-registered 30. Nobody should cite either as a verdict.

---

**IF YOU WEREN'T HERE:** I would book STANDARD's fills this week. Every other lever in this book
has now been measured to within an inch of its life — bands, exits, wallets, latency, sizing —
and the only one that has never been priced is the price we pay, which today's run values at
**5.0% of notional per cent** against a 90-day realised return of 8.1%. That is not a tuning
question; it is the difference between a strategy that survives contact with a real order book
and one that only exists in the ledger.

---

*Lane B, applied directly this commit: `scripts/profit-sellside.py` (new, §SS.1–SS.8: the flow
census by side, wallet round-trip timing, the exit signal priced on our own settled legs, the
reachability read, the mark path with paired settlement counterfactuals and a −24h control, the
wallet-rank test with permutation nulls, the decision-lag table and the entry-price/capital-day
arithmetic), `src/lib/sell-log.ts` + `tests/sell-log.test.ts`, and the `monitor-trades.ts` call
site. Read-only DB except the append-only sidecars. **No RuleSet row touched, no rule edited, no
`prisma/dev.db` write.***

*Defects caught in my own work before any number shipped: (1) my first wallet-rank run required
≥20 bets per half at a 2026-09-15 cut and returned **21 wallets**, which I nearly reported as a
failed test rather than what it is — a truth-coverage limit (1.4% of the markets we witness);
the cut now sits at 2026-08-20 with ≥8 per half and the coverage number is printed next to it.
(2) The +168h exit counterfactual is the only one with the sign I wanted and it is an artefact of
`MarketSnapshot` coverage collapsing to 1,038 legs; it is printed with its coverage and its
explanation, not quietly dropped. (3) §SS.3's 4-leg "alpha" of +$30.92 has a 3-market CI that
spans zero and is quoted only to show that the population is empty, never as evidence.*
