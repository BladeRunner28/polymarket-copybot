# Why the Kalshi leg is doing no trades — gate-dormancy review

**Date:** 2026-09-13 · **Author:** Hermes · **Status:** review + option set → **user decision: OPTION A (retire Kalshi
copy-routing at Phase C kickoff)**; carded as `retire-kalshi-copy-routing` (roadmap, Scheduled). No code or rule changed today —
the Kelly window (Sep 8–Oct 8) blocks implementation.
**Roadmap refs:** phase-c, phase-kalshi1, tr16-kalshi-adapter · **Predecessor:** drafts/kalshi-whale-review.md

## The question

The Kalshi circuit breaker was cleared on 2026-09-05 (reprice took `kalshiRealized`
from −$50.70 to −$37.99; it is **+$27.82** today). The sidecar's Kalshi adapter is
healthy (TR-16, live-verified). Yet the last Kalshi-venue trade was opened
**2026-08-30 23:44** — 13 days ago, with 0 since the unblock. Why?

## Answer in one line

The venue gate is a **two-variable test whose two variables are read from two
different stages of the same score**, and the rules that raise one leg now lower the
other. Since v37 it is effectively unsatisfiable for the C-200 funnel — nothing is
broken, the gate just cannot be cleared.

## The gate (only path that creates a Kalshi trade)

`scripts/score-trades.ts:579–586` — per C-200 leg:

```
kalshiEligible = result.copyScore    >= rules.kalshiMinCopyScore   (80)
              && result.confidence   >= rules.kalshiMinConfidence  (0.75)
              && kalshiRealized      >= rules.kalshiCircuitBreakerPnl (−50)
if (botId === "BANKROLL_200" && result.confidence > 0.8 && kalshiEligible) executionVenue = "Kalshi";
```

`kalshiRealized` is **+$27.82** → breaker leg passes (there is no other Kalshi-specific alert or error; the leg is silent by design, not failing).

The two score legs are the problem, because `confidence` and `copyScore` are not the
same number (`src/lib/scoring/trade.ts`):

| Stage | What it is | Where computed |
|---|---|---|
| `confidence` | `round((copyScore − 35) / 65, 2)` from the **pre-boost composite** (wallet quality, category fit, entry timing, spread, liquidity, thesis) | line 143, **before** the swarm/sentiment adjustments |
| `copyScore` | the **post-adjustment** score — swarm +25 / sentiment `delta×scale`, then the v34 clamp at `regulatoryScoreCap` | returned at line 316 |

So `confidence > 0.8` ⟺ pre-boost composite **≥ 87.33**, while `copyScore ≥ 80` is read
off the post-adjustment value. Post-v37 the two legs measure the same latent variable at
two stages, and every adjustment that moves one moves the other in the opposite direction.

## What actually changed on Aug 31 (the day the flow died)

Before v37 the stored `confidence` was derived from the **post-boost** score (pre-clamp);
from v37 (activated **2026-08-31 04:58**) it is the **pre-boost composite**. Verified on
stored rows:

- Pre-v37 (Aug 30, Kalshi rows): composite 65.3 + 25 swarm = 90.3 → `copyScore` 90.3,
  `confidence` 0.85 (= (90.3−35)/65 ✓). Another: composite 73.4 + 25 = 98.4 →
  `confidence` 0.98, `copyScore` clamped 79.0.
- Post-v37 (Sep 12 C-200): composite 88.2 → `confidence` **0.82** ✓ but the sentiment
  boost then hit the v34 clamp → `copyScore` **79.0**.

Last Kalshi trade: **2026-08-30 23:44**. v37 activation: **2026-08-31 04:58**. The flow
stopped at the semantic switch, not at the breaker (which only explains the
Sep 1–5 gap).

## The three blocks (all structural)

1. **v37 confidence semantics** — the C-200 funnel's pre-boost composite essentially never
   reaches 87.33. Since Aug 31 only **5 of 553 C-200 copies** cleared `confidence > 0.8`,
   vs 92 in the 20 days before.
2. **v34 clamp vs the score bar** — `regulatoryScoreCap = 79` < `kalshiMinCopyScore = 80`.
   Any sentiment-boosted signal is structurally banned from the venue leg, *and* that is
   exactly the class most likely to have a high composite.
3. **Short-TTR lane** — the lane branch returns `confidence: 0` by design ("routing stays on
   Polymarket"). 296 of the 335 C-200 copies since Sep 5 are lane copies → structurally
   ineligible. The lane is the C-200 funnel's main channel now.

## The numbers (since the breaker cleared, 2026-09-05 08:39)

- C-200 copies: **335** · with `confidence > 0.8`: **1** (Sep 12 23:52, conf 0.82) · **eligible: 0** —
  that one is blocked by block 2 (`copyScore` 79.0 < 80).
- Copies the gate would have taken **if confidence still came from the post-boost score**:
  **20** (all `copyScore ≥ 87.5`, avg confidence 0.48) — and those 20 are **−$578.64**
  realized on Polymarket. Restoring the old semantics would route the *bleeding* class,
  not the historically +EV one.
- The class the gate selected when it fired (all-time, `confidence > 0.8`, both venues):
  **811 trades, Kalshi +$0.30/trade, Polymarket +$0.24/trade** — i.e. the selection rule was
  mildly +EV, not a loser.
- Kalshi leg by exit type: `closed` 73 trades **−$152.82** · `resolved` 19 trades **+$180.64**
  (early-exit bleed / natural resolution — same signature as the main book; N is small).
- Component comparison, Kalshi era vs C-200 main lane now: pre-boost composite **93.3 → 68.8**
  (thesis 77.1 → 45.8, timing 39.5 → 35.6, category fit 46.8 → 48.5).

## Side finding — the venue λ̂ offset is fitted on phantom prices

`data/premium-calibration.json` (`venueOffsetKalshi = +0.328`, refit **2026-09-01**) was
fitted by `scripts/calibrate-premium.py` from the Kalshi-venue rows, whose booked entries
were then the **constant 0.50 phantom** (reprice audit: all 73 closed rows `bookedEntry = 0.5`
exactly; real entries 0.073–0.924). The offset is added to λ̂ when sizing a Kalshi-routed
C-200 copy (`score-trades.ts:602, 682`) — a bigger λ̂ = more premium drag = smaller position.
It has **zero live impact today** (no routed trades), and the Sep 15 refit will recompute it
from the repriced rows. Any decision to revive routing should wait for that refit.

## What the venue leg is worth (honest read)

- Post-reprice, the 92 Kalshi rows' PnL is measured at **Polymarket reference prices** — the
  reprice rewrote their entries — so it carries **no information about Kalshi execution quality**.
- With TR-16, the sidecar resolves a Kalshi ticker only for genuine cross-listings; when it
  fails (the common case) the trade **books at the Polymarket reference price** with an
  execution note. So a "Kalshi" label today is mostly a routing label, not a different fill.
- Net: **no measurable venue edge either way**, and the copy-routing leg's original selection
  rule no longer maps to the population that made it look +EV.

## Options (nothing ships before the Oct 8 Kelly-window read)

| # | Option | Effort / risk | Notes |
|---|---|---|---|
| A | **Retire copy-routing to Kalshi**; keep the venue for Phase C cross-venue arb only | ~1h, LOW (delete the venue branch; sidecar adapter stays) | Removes an incoherent, silently-dead rule and a phantom-fitted sizing input. Kalshi stays in the stack via phase-c. |
| B | **Re-specify the gate on one variable** (bar read off the post-adjustment score, or a venue-specific bar) + shadow-measure 2 weeks | ~1–2h + 2wk shadow, MEDIUM | Must be measured, because the naive version (pre-v37 semantics) selects the −$578 class. |
| C | **Re-baseline the bars only** (lower `kalshiMinConfidence` / `kalshiMinCopyScore`) | ~1h, MEDIUM | Blunt: with the dual-variable mismatch intact, no bar maps cleanly to anything. |
| D | **Leave dormant / park** until Phase C replaces the leg | 0, none | Costs nothing: breaker is clear, adapter healthy, no alert fires. |

**Recommendation: A (or D now → A at Phase C kickoff).** The leg is not a missing
opportunity — it is a rule that cannot fire plus a sizing input fitted on phantom data.
If the user wants Kalshi copy flow back, B is the honest version, but it needs the
post-Oct-8 window and a shadow measurement, not a bar tweak.

## Honest caveats

- The counterfactual "20 copies" uses stored (1-dp) `copyScore`, so it is an estimate of the
  pre-v37 class, not an exact reconstruction.
- "The venue has no edge" is a statement about *this stack's* price source (PM reference on
  failed resolution) — it is not a claim about Kalshi's books.
- Lane copies are excluded from everything above except counts; their routing is intentional.
- Probes/queries are read-only over `prisma/dev.db` at 2026-09-13 08:40–09:00 CDT; RuleSet v53 active.
