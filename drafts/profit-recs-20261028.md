# Profit review — 2026-10-28

http://localhost:3013/drafts/profit-recs-20261028

**Cost basis on every ROI below: `simulatedPositionSize` = dollars at risk, never shares.** A BUY of
$n at price `p` is `n/p` shares, so settlement at `s` realises `n*(s/p − 1)` and an exit at `c`
realises `n*(c/p − 1)`. That identity is re-verified against `realizedPnl` on the whole cohort
before any number is used (max abs error **$0.0050**, §AO.1).

Every figure is computed by `scripts/profit-exits.py` (§AO, this commit), which imports the
settlement-truth and market-clustered bootstrap from the committed `scripts/profit-velocity.py`
rather than re-implementing them. Reproduce:

```
DATA_MODE=live python3 scripts/profit-exits.py            # ~15s, first run fetches truth
DATA_MODE=live python3 scripts/profit-exits.py --no-fetch # offline, cache only
```

---

## The number everyone quotes as v66's cost is not a cost

v66 (approved 2026-10-23) gave STANDARD its first stale-exit rail. On its first tick — 2026-10-24
07:06 UTC — it closed **701 legs / $7,321.20 at risk / −$350.52**, and every write-up since has
carried that as the price of the rule. It is a reclassification, not a loss: the marks were already
there, and on the night the book's realised+unrealised total moved $11,481.10 → $11,495.70. What
v66 actually did is buy one thing and pay for another, and neither has ever been priced:

| | measured now | source |
| --- | --- | --- |
| **Bought** — 701 leg slots freed | worth **$117.97** if every slot were refilled at the book's own ex-outlier per-leg rate; **$2.69** actually earned so far | §AO.3, §AO.4 |
| **Paid** — exit alpha on the 24% of the cohort whose markets have already settled | **−$831.70** (−48.36% of notional), of which **−$807.01 is one market** | §AO.5 |
| Cohort as executed | 701 legs, 136 at 0.60–0.80 (−21.71%) and 565 at 0.80–1.00 (+0.22%) | §AO.1 |

---

## What it bought: a resource this lane does not have

STANDARD's only scarce resource is a **leg count**: `standardMaxOpenPositions` = 1,300 (v64,
2026-10-20). It has **no notional cap at all** — `maxGrossExposureUsd` ($1,000) is applied to C-200
only (`score-trades.ts:198` and `:625`; STANDARD's three gates are the leg cap, the 0.85 entry cap
and the 0.4–0.6 band skip). The arithmetic proof is that the lane currently holds **$5,125 of open
notional = 5.1× that base** and there is no notional gate in its path to stop it.

So "capital-days released" — v66's stated justification, 604,756 of them — has **no economic content
for this lane**. What it could have bought is slots, and slots were not scarce:

- **1,256 open legs at the sweep = 44 slots of headroom (96.6% of cap)** — the number that made the
  rail look urgent.
- But the book was **already shrinking: 133 opens (4.43/day) vs 275 resolutions (9.17/day) over the
  30 days before the sweep = net −4.73 legs/day.** Headroom was going 44 → ~186 within a month on
  its own. §AO.4.
- Without the sweep the book would be **1,003 legs today, 297 slots of headroom** (§AO.4).
- **27.5% of the swept notional ($2,018) had scheduled end dates within 7 days** of the sweep;
  median end +69d, 80% within 90d (§AO.7). 24% of the cohort has already settled since.
- Refill: **16 new STANDARD legs in 4.2 days (3.8/day) = 2.3% of the release** — 186 days to consume.
- A slot is worth **$0.168/leg ex-outlier** (298 resolved-only legs since 2026-09-15: mean +$1.114,
  median −$18.00, top leg +$282 = 85% of the total). A permanently binding cap therefore costs
  **$0.64/day** of forgone slot value.

**That is the whole purchase: 701 slots bought for the price of an exit, at a moment when the lane
was generating ~140 slots/month by itself and the cap had no chance of binding.** The metric the
rule was judged by (capital-days, 1.03M → ≈425.5k, −59%) is real but has no price attached — and it
is the *only* metric that moved.

---

## What it paid: the one population where marks are not calibrated

167 of the 701 legs (23.8%) sit in markets that have settled since. Re-priced at truth:

| | legs | notional | as executed | held to settlement | alpha |
| --- | --- | --- | --- | --- | --- |
| whole cohort | 167 | $1,719.80 | −$434.42 (**−25.26%**) | +$397.28 (**+23.10%**) | **−$831.70 (−48.36%)** |
| 0.60–0.80 | 64 | $811 | −55.23% | +43.39% | −$800.20 |
| 0.80–1.00 | 103 | $908 | +1.51% | +4.97% | **−$31.50 (−3.47%)**, CI [−$86, +$2] |

Market-clustered 95% CI on the cohort alpha: **[−$2,522, +$48]** — includes zero, and it should,
because the point estimate is one market: **Bolsonaro, 51 legs, sold at a NO mark of 0.204 that
settled at 1.000 = −$807.01.** Ex-the-10-extreme-markets the alpha is **−$0.39 on 11 markets**.

Bolsonaro is not a data defect. The mark was live (the CLOB/Gamma price at 07:07), and I checked the
snapshot trail: the market's own last collected snapshot was 2026-10-18 at YES 0.7905 / NO 0.2095,
and the exit took NO at 0.2045. **The position really was marked at 20c — it just resolved at 100c
two days later.** In the 0.60–0.80 band the median exit mark was **0.204 against a median settlement
of 0.984**: a 0.78 dislocation, in the median, on a live book.

**The control that turns this from one bad market into a mechanism (§AO.9).** STANDARD has exactly
two ways to leave a position without a resolution, and by elimination every non-sweep close is the
other one — the dead-slug 404 expiry, which books at the last known mark:

| close path | priced legs | notional | alpha | CI | mark error, median (p10 / p90) |
| --- | --- | --- | --- | --- | --- |
| dead-slug 404 expiry | **6,503** | $69,123 | **+$210.73 (+0.30%)** | [−3,231, +3,658] | **0.000** (−0.049 / +0.037) |
| v66 stale stop | 167 | $1,720 | −$831.70 (−48.36%) | [−2,522, +48] | −0.795 in the 0.60–0.80 half |

Six thousand five hundred exits at the last known mark are calibrated to **±5c**. The new rail fires
into the opposite population: **live, actively-repricing, long-dated favourites, at an arbitrary
hour, at whatever the mark says.** 404 expiries only happen on markets that have stopped trading,
which is precisely why their marks are accurate. v66 imported an exit into the noisiest marks the
book owns — and its alpha on 167 legs is **3.9× the entire alpha of 6,503 calibrated exits, with the
opposite sign.**

---

## #1 — Make the STANDARD stale exit fire on cap pressure, not on the calendar. Lane A, proposed.

**Hypothesis.** v66's only legitimate function is to protect the 1,300-leg cap; therefore gating it on
`headroom < 15% of standardMaxOpenPositions` **and** `trailing-7d net book growth > 0` loses nothing
where the rail is useful and removes its measured cost where the slot cap cannot bind.

**Measurement.** `scripts/profit-exits.py` §AO.10 backtests the gate day by day over 90 days from
`PaperTrade` alone (open legs, headroom, 7d opens minus resolutions, legs in v66's scope). Today:
**92 days with a leg in scope, the gate allows 50 (54%)**. In Jul–Aug, when the book ran 1,500–1,970
legs at +300 to +1,000 net/week, it fires every day — the regime the rail exists for. **In the last
30 days it allows 0/30**, including the sweep day (headroom 44 but net −9/week). §AO.3–AO.7 price the
two sides: $117.97 of slot value versus a measured −$831.70 alpha.

**Decision rule.** Ship when (a) the gate is unit-tested to refuse firing at headroom ≥ 15% of cap or
net growth ≤ 0, and (b) over 14 forward days it permits ≥1 fire if the book is in the growth regime
and 0 in the current one, and (c) the leg cap blocks **zero** copies on any day it suppresses.
(a)–(c) are all satisfied today by construction except the two-week observation window.

**Refutation.** If, in the 30 days after shipping, the `[STANDARD] open-position cap` block counter
hits **≥20 copies on days the gate suppressed**, slot pressure was real and the gate cost throughput
→ revert. The `STANDARD: open-position cap` skip reason already writes to DecisionJournal, so this
is a counted, not argued, threshold.

**Expected effect.** Removes a −48pp-of-notional tail on the only event available to measure
(−$831.70, one market dominant, CI spans zero); converts the rail's last-30-day firing rate from
30/30 days to 0/30; keeps it intact for the growth regime. It also stops the book from selling at
live marks in a lane whose marks are calibrated to ±5c only when markets are dead.
**Cost: 2h** (one predicate in `standardStaleExitFires` + the two inputs in `update-pnl` + 3 tests).

---

## #2 — The pre-registered refutation of v66 could not have been evaluated. Fixed. Lane B, done.

`closePaperTrade(tradeId, exitPrice, _reason)` **received the reason and discarded it**: every early
exit lands as `status='closed'`, so a v66 stop, a dead-slug 404 expiry and a C-200 recycle are the
same row. v66's own refutation clause — "the first 20 ORGANIC stopped legs realise worse than hold
by more than 1.0% of notional" — is therefore not computable, and the read the tuning review has
scheduled for 2026-10-31 would have had no denominator.

The only reason today's review could price the sweep separately is that it was **one timestamp and
the only non-404 close STANDARD had ever taken**. The next stop would have been invisible, and the
§AO.9 split by elimination would have silently stopped working.

Shipped this commit, code-only, no schema change and no prisma write:
`src/lib/close-log.ts` appends one JSONL line per early close (`id`, bot, market, entry, exit, size,
pnl, ageHours, reason) to `data/close-reasons.jsonl`; `closePaperTrade` calls it best-effort (a
failed append can never fail a close). `tests/close-log.test.ts` pins verbatim reason capture,
append-only ordering and the never-throw path. `npx vitest run` 606/606 pass, `tsc --noEmit` clean.

Also fixed in `scripts/profit-velocity.py`: `build_truth` froze any market it first saw unresolved —
`_fetch_one` returns the cached raw response without hitting the wire, so a record marked
`unsettled` stayed unsettled forever. **269 of 4,005 cached markets were frozen that way**; the 248
cohort markets re-fetched today resolved 21 of them. Unsettled records whose end date has passed are
now re-fetched. *This did not move today's printed coverage (91% on closed legs) — it is a latent
defect that would have quietly capped every truth-based section as markets settle.*

---

## #3 — What I am not doing, and the measurement that would unlock it

- **Do not narrow v66 to entry ≥ 0.80 on today's evidence.** The 0.60–0.80 loss looks like a band
  effect and is not one: **64 priced legs, of which two markets (Bolsonaro −$807.01, Yamal −$41.87)
  carry −$848.88 against a band total of −$800.20.** A 2-market "band finding" is exactly the
  artefact the 2026-10-20 review shipped and had to retract. The unlocking measurement is §AO.5
  re-run as those markets settle: **verdict at ≥150 priced legs across ≥40 markets**; if the band
  alpha is still outside ±2% of notional then, it is a band effect and the scope change is justified.
- **Do not retire the ≥0.80 half.** It is nearly free (−$31.50 on $908, −3.47%, CI includes zero)
  and it removes legs from the one band whose settlement edge is negative on two instruments
  (−4.3pp and −4.7pp). Right action, wrong reason, already done.
- **Do not touch the dead-slug 404 expiry.** 6,503 legs, alpha +0.30%, marks calibrated to ±5c. It
  is the best-behaved exit in the system and it looked like a problem only while it was being
  blamed for the band ROIs.
- **Do not liquidate the open 0.4–0.60 book** (139 legs, $1,686, +$519.68 unrealised, +30.8%, avg 88
  days). It is the tempting move — a band v63 refuses at entry, whose truth edge measures ≈0 — but
  the legs still open are exactly the ones whose marks went up, so the +30.8% is survivorship and
  the marks are, on the whole book's evidence, the most calibrated estimate available. No exit rail
  reaches that band on merit.

---

## Contradictions I am not resolving silently

- **The brief's own measured baseline is out of date.** It says "the stale-exit block is scoped
  `botId === "BANKROLL_200"` (`scripts/update-pnl.ts:240`), so STANDARD exits only on resolution or
  dead-slug 404." True until 2026-10-23; v66 added a STANDARD branch at `update-pnl.ts:270-292`.
  **The 2026-10-27 review quoted a pre-v66 code state**, which is what made v66 look like a
  measurement rather than a decision. The same brief's "1,269 open legs / 1,033,886 capital-days"
  is superseded: the lane is at **469 legs / ≈425.5k capital-days** today (both are time-integrated,
  so they drift hourly — the leg count is the stable half).
- **Yesterday's Bolsonaro attribution is not a market-level story.** The 10-27 review reported the
  market as −$1,053 for the week and "resolved NO and took the accumulated position with it".
  STANDARD's own legs in that market (§AO.11): **NO closed (the sweep) 51 legs −$475.27 at an average
  mark of 0.204; NO resolved 2 legs +$43.09; YES resolved 58 legs −$679.00 = −$1,111.18 on
  $1,397.80.** Two opposite mechanisms under one name: the rail sold NO at a 0.204 mark that settled
  1.000, and YES legs resolved to zero on 10-26 — the market's own loss, not the rail's. All lanes on
  that market net −$387.38 over its whole life.
- **0.4–0.6 still has three instruments, three answers** (STANDARD all-time +6.7%; 10-20 band report
  −7.67% CI [−14.48, −0.89]; 10-27 truth edge −0.1pp). New today: on 2,172 legs exited by 404
  expiry, exit alpha is −$762.94 (−2.95%) — the largest negative block in the exit system and still
  not a band verdict. Not used for anything.
- **§AB's 6,670-leg exit alpha (−$621, CI [−4,405, +3,240]) is unchanged by today's work** and is
  the population-level answer: the exit system as a whole is alpha-neutral. The finding is about
  *which* exit, not about exits.

---

**IF YOU WEREN'T HERE:** I would ship the cap-pressure gate on v66 today. Not because the alpha
estimate is precise — it is one market and the CI spans zero — but because the rule's entire premise
("recycle capital so it does not park") is false for a lane with no capital cap, and the metric it
was approved against had no price. A rule that can only act when the cap is near binding costs
nothing to make honest, and the 90-day backtest says it would still fire on 54% of the days a leg is
in scope — every one of them in the regime it was built for.

---

*Lane B, applied directly this commit: `scripts/profit-exits.py` (new, §AO.1–AO.11: the sweep
reproduced from its own predicate, the lane's resource inventory, slot pricing on resolved-only legs,
the no-sweep counterfactual, settlement-truth exit alpha with a market-clustered CI, the clearance
curve from scheduled end dates, the close-path decomposition by elimination, the surviving book's
profile, and the gate's 90-day backtest); `src/lib/close-log.ts` + `tests/close-log.test.ts`; the
`build_truth` freeze repair in `scripts/profit-velocity.py`. Read-only DB except the sidecar JSONL.
**No RuleSet row touched, no rule edited, no `prisma/dev.db` write.***

*Defects caught in my own work before any number shipped: (1) my first "before the sweep" snapshot
was hardcoded to 02:06 **UTC** when the sweep ran at 02:06 **CDT**, which shifted the open-book
comparison five hours and reported "1,256 → 1,256"; the instant is now taken from the data. (2) My
first run printed **0% settlement coverage** because `_fetch_one` refuses to re-hit the wire for a
raw response cached while the market was open — the same freeze §AO.9's parent script has, now
fixed. (3) The 0.60–0.80 band's bootstrap CI prints NaN: fewer than two markets with variance. I
left it visible rather than hiding the band line, because that NaN is the honest statement of how
much the band result is worth.*
