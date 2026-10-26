# Pre-registered read — C-200 sub-$0.05 entry floor

**Status: GATE DATE PASSED (2026-10-24) — READ #2 TAKEN 2026-10-26, VERDICT `INSUFFICIENT_N` (n=31/60).**
The gate date passed **unread**: this instrument was not on cron, and the series held exactly one line
(the 2026-10-17 registration-day read) until 2026-10-26. It is now taken by `scripts/research-collect.py`
(daily fact sheet, `--if-stale-hours 12`) and every read records `gateDate`/`daysSinceGate`/`priorReadAt`.
Read #1 taken 2026-10-17 (day 0) · read #2 2026-10-26 (gate date +2d).
Instrument: `scripts/entry-floor-replay.py` · series: `data/entry-floor-read.jsonl` · approved from
copybot-research-daily REC 1.

## What was registered (fixed before the first run)

**Hypothesis.** C-200 legs entered below $0.05 are loss-making at any window (lifetime ROI ≤ −20%) while
0.05–0.15 legs stay strongly positive — so the missing sub-0.20 *flow* is a saved cost, not a lost edge, and
the operative variable is an entry **floor**, not the ×3.5 longshot size factor.

**Decision rule (verbatim, not editable after the fact).** By **2026-10-24**, if BOTH
**(a)** the `<0.05` cell holds ROI ≤ −20% at **n ≥ 60** settled C-200 legs, AND
**(b)** the trailing-7d sub-0.20 skip counterfactual nets **≥ +$25 across ≥ 30 resolved markets**,
then propose `c200MinEntryPrice = 0.05` (itself needing approval + a 7-day verify: 0 C-200 legs below 0.05
and no drop in the 7d gate SUM). If either fails → record the null and drop.

**Basis.** Settled legs = `PaperTrade.botId='BANKROLL_200'`, status `closed` **or** `resolved` (both settled
by lane doctrine: early exit vs natural). Counterfactual marks come from the shadow markers' row-level
`resolve` feeds — the same resolution convention the drift shadow uses — at a fixed **$10** clip
(`DRIFT_SHADOW_STAKE_USD`), deduped to one signal per `marketId|outcome|wallet` (earliest decision).

## Read #1 — settled C-200 legs by entry price (lifetime)

| Cell | n | Net PnL | ROI | Win rate | Resolved-only n / ROI |
|---|---|---|---|---|---|
| `<0.05` | 31 | **−$828.20** | **−55.2 %** | 19.4 % | 6 / **−100 %** (0 of 6) |
| 0.05–0.10 | 97 | +$4,524.36 | **+149.0 %** | 30.9 % | 33 / +205.2 % |
| 0.10–0.15 | 66 | +$1,339.16 | +90.0 % | 33.3 % | 21 / +117.7 % |
| 0.15–0.20 | 57 | +$627.23 | +51.6 % | 24.6 % | 14 / **+3.5 %** |
| `≥0.20` (reference) | 2,222 | −$54.39 | −0.4 % | 50.0 % | 792 / +22.4 % |

The edge is **monotone in the wrong direction at the bottom**: it peaks in **0.05–0.10**, decays through
0.10–0.20, and flips negative below $0.05. Two things worth naming:

- **The `<0.05` cell's natural settlements are 0-for-6.** Small n, but the sign is not ambiguous — and the
  lifetime figure is *not* an early-exit artefact (early exits would have *helped* the cell, not hurt it).
- **0.15–0.20 collapses to +3.5 % on resolution-only** — that cell's profit is carried by early exits, so a
  0.05 floor would leave untouched the cell with the weakest hold-to-settlement case.

## Read #1 — sub-0.20 skip counterfactual (trailing 7d, $10 clip)

- **62 deduped skip signals** (from 206 skip rows), **52 resolved** (83.9 % coverage), mean entry **$0.0916**.
- **Net +$1,483.66** dust-inclusive · **+$596.20 ex-dust** (<$0.10 excluded, n=26) · 26 dust rows excluded.
- Band detail: `<0.05` 20 signals/12 resolved/**1 win**, net **+$102.22** (best single win **$212.22** =
  21× on the clip) · `0.05–0.10` +$785.24 (6 wins/14) · `0.10–0.15` +$449.06 (7/13) · `0.15–0.20` +$147.14 (5/13).

## Read #2 — 2026-10-26 (gate date +2d), the first read on/after the gate

| Cell | n | Net PnL | ROI | Win rate | Resolved-only n / ROI |
|---|---|---|---|---|---|
| `<0.05` | 31 | **−$828.20** | **−55.2 %** | 19.4 % | 6 / **−100 %** (0 of 6) |
| 0.05–0.10 | 100 | +$4,464.56 | **+144.1 %** | 30.0 % | 35 / +192.6 % |
| 0.10–0.15 | 71 | +$1,161.68 | +69.6 % | 31.0 % | 25 / +76.7 % |
| 0.15–0.20 | 64 | +$1,119.97 | +76.4 % | 25.0 % | 21 / +73.3 % |
| `≥0.20` (reference) | 2,259 | −$65.35 | −0.5 % | 49.8 % | 823 / +21.6 % |

**Verdict `INSUFFICIENT_N` — gate A n=31/60; gate B resolved 55/30 and net +$5,250.66 both pass.**
Per the registered rule ("if either fails: record the null and drop the card") the answer this gate can
give is a **null**, and the n gate cannot move: the `<0.05` cell held **31 settled legs on 2026-10-17 and
still holds 31 on 2026-10-26** — nine days, zero new settled sub-$0.05 C-200 legs. The population the gate
is counting has stopped flowing, so "reach 60" is not a matter of waiting. Recording the null is a rule
decision (Lane A), not an instrument one, and is left to the owner.

Read #2 counterfactual: 66 deduped signals, 55 resolved (83.3 %), dust-inclusive **+$5,250.66**,
ex-dust (<$0.10) **+$279.14 on 37**, and the single best win $3,323.33 = **63.3 % of the whole net** —
so gate (b) still passes only because of one dust-sized ticket, exactly as finding 1 predicted.

## Three findings that matter more than the numbers

**1. Gate (b) is not a discriminating gate.** It passes on both bases — dust-inclusive (+$1,483) and
ex-dust (+$596) — and at a ~9¢ mean entry a single 21× winner is $212, i.e. **14 % of the entire result and
the whole of the `<0.05` net**. The "+$25 across 30 resolved" bar is cleared by essentially any sample at
these prices, so the decision rests entirely on gate (a) reaching n ≥ 60. *I am not proposing to change it
mid-flight* — the floor is cheap, reversible, and the settled-cell evidence is the primary case — but the
permanent record should say plainly that (b) adds little. Any strengthening now would be post-hoc-informed,
because I have already seen this data.

**2. The rule's own n gate may force a NULL by default.** The `<0.05` cell has 31 lifetime legs. Reaching 60
by 2026-10-24 requires 29 more settled legs in a week from the thinnest band in the book. If they don't
arrive, the pre-registered answer is "record the null and drop" — not "the floor is wrong", and not "the
floor is right". Worth knowing now rather than on the 24th.

**3. The research brief's headline counterfactual basis does not reproduce.** The brief said "409
copy-eligible decisions at a mean **3.6 ¢** (404 skips, 5 copies)". From the live DB, trailing 7d:
**206** skip rows at mean **7.35 ¢** (`detectedPrice`), **62** deduped signals at **9.16 ¢**, and **8**
`FillIntent` rows below $0.20. No basis I can construct yields 409/3.6¢ — so that figure joins the voided
skip-tag line. **This instrument's basis is the authority going forward.**

## Collector defect fixed (2026-10-17)

`scripts/research-collect.py` reported "leading skip tag (first entry of `reasonsJson`)". `reasonsJson` is
the **boost** field and is `[]` on ~91 % of skips; the real reasons live in `risksJson`. It now counts
**every** entry of `risksJson` with a `reasonsJson` fallback, and adds a distinct-market count. Re-run
verified exit 0; the true 24h mix is:

> coalesced into open copy — same wallet/market/outcome already open (v5 ×314) · price drifted 0.005 since
> entry > max 0.0040 (too late) ×43 · short-ttr lane (relaxed drift & score bar) ×28 · confidence 0.34 <
> min 0.7 ×12 · resolves in 0.0h < min 2h ×10

**The top skip reason is not an edge decision at all — it is de-duplication (×314 of 400).** That reframes
any "we are refusing good flow" narrative built on raw skip counts: the largest bucket was never refused on
merit.

## What happens next

- Readings are appended by the instrument each time it runs, so 2026-10-24 is answered by a **series**, not
  an impression. Verdict states: `PENDING_DATE` → `INSUFFICIENT_N` → `PROPOSE_FLOOR_0.05` / `NULL_DROP`.
  **That sentence was false between 2026-10-17 and 2026-10-26** — nothing ran the instrument, so the
  series was one point and the gate date passed unread. Fixed 2026-10-26; the read now runs in the daily
  fact sheet and any read taken after the gate date prints `GATE WAS UNREAD` if no prior read exists on
  or after it.
- Latest read: **`INSUFFICIENT_N`** (2026-10-26) — gate (a) ROI passes (−55.2 %) but n is **31/60** and
  static since 10-17; gate (b) passes on a single dust ticket (63.3 % of its net).
- **No rule, size, threshold, config or live-lane change was made.** Read-only throughout.
