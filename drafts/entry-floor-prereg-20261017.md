# Pre-registered read — C-200 sub-$0.05 entry floor

**Status: PRE-REGISTERED, GATE PENDING (2026-10-24).** Read #1 taken 2026-10-17 (day 0).
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
- Today: **PENDING_DATE** — gate (a) ROI already passes (−55.2 %), gate (a) n is **31/60**, gate (b)
  resolved 52/30 and net +$1,483 both pass.
- **No rule, size, threshold, config or live-lane change was made.** Read-only throughout.
