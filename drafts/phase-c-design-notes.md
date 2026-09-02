# Phase C Design Notes — Constraint-Based Cross-Venue Arb

**Source:** drafts/wang-calibration-audit.md §4 (Phase C) + reference reading of
homerun's `cross_platform.py` / `negrisk.py` / `ctf_basic_arb.py` (AGPL-3.0 —
read-only; concepts reimplemented, no code vendored). Prepared 2026-08-31 for
the Sep 15–30 design window. Validation data: `~/prediction-market-data` (50G
PMA dataset, both venues, resolved markets).

---

## 1. The invariant families (what to detect)

### 1a. Cross-platform divergence (homerun cross_platform.py)
Same event trades on Polymarket AND Kalshi → buy the cheap venue, sell/hedge the
expensive one.
- **Safeguards (their documented false-positive classes, each must be replicated):**
  - Platform filter: iterate PM markets only, never Kalshi-vs-Kalshi (avoids same-platform false matches).
  - Outcome guard: parse Kalshi ticker suffix (`-TIE`/`-WIN`/`-AWY`) + question text; never match WIN vs TIE.
  - Multiway guard: stricter matching when the event has 2+ Kalshi sub-markets.
  - Resolution divergence: flag "90-min" vs "advance" resolution mismatches (soccer).
  - Minimum profit: reject marginal post-fee spreads — **post-fee profit floor 0.03** (two taker fills, non-atomic execution).
- **Matching:** fuzzy Jaccard token similarity on question text + deterministic ticker-prefix parse.
- **For CopyBot:** matching = event-level (Polymarket market ↔ Kalshi event ticker) via question text + category; a `CrossVenueQuote` record with pmPrice, kalshiPrice, fees, net edge.

### 1b. Exclusivity / one-of-many (homerun negrisk.py)
Mutually exclusive + exhaustive outcomes (NegRisk-flagged events, elections):
- Buy YES on ALL outcomes when Σ cost < 1.00 → guaranteed profit.
- **CRITICAL guard:** date-based "by X" markets are CUMULATIVE, not exclusive —
  "event by March" + "event by June" both resolve YES if the event happens in
  March. Buying NO across date markets = correlated loss. Only verified
  exactly-one-wins events qualify.
- **For CopyBot:** Polymarket NegRisk markets (event with multiple tokens summing < 1) —
  needs the NegRisk flag from the Gamma API; paper-trade only.

### 1c. Implication / conditional (from oracle3 + ctf_basic_arb)
- If outcome A ⇒ outcome B (implication), then P(A) ≤ P(B); violation = sell A / buy B.
- CTF structural: split/merge against book capacity (`best_bid_size`/`ask_size`) —
  buy a bundle below its parts, or merge tokens above their parts.

## 2. CopyBot-specific design constraints

- **Paper-only + measurement-first:** Phase C ships as a *detection + shadow
  journal* first (log violations with net edge, track would-have-been PnL),
  exactly like the A2 pattern. Live sizing only after 2-week validation.
- **Kalshi leg gate:** v37 circuit breaker (realized ≥ −$50) must recover before
  any real Kalshi routing — arb legs are market-neutral but still execute there.
- **Data sources:** Kalshi trade API (cursor pagination pattern from PMA
  `kalshi/client.py`), Polymarket CLOB quotes via existing adapter, NegRisk flag
  via Gamma API. The PMA dataset provides the backtest harness for all three
  invariant families (resolved markets, both venues, ~2y history).
- **Execution realism:** two legs are non-atomic — model both taker fees
  (Polymarket taker fee ~0.02–0.03 on CLOB; Kalshi fee schedule) + the fill
  probability question (see homerun cox_trainer note) before netting.

## 3. Deliverables for the Sep 15–30 window

1. Backtest script on the PMA dataset: scan resolved markets for exclusivity
   violations (ΣYES < 0.97 near close) and cross-platform divergences (matched
   PM/Kalshi pairs, post-fee net > 0.03); report frequency + captured edge +
   decay (how often the gap closes before resolution).
2. `CrossVenueQuote` / `ArbSignal` DB model + detection service (poll both
   venues, ~60s cadence per homerun).
3. Shadow journal: `[ARB] type=exclusivity|divergence|implication net=…` rows
   with would-have-been PnL; daily report section once ≥1 week of data.

## 4. Reference files
- `/tmp/homerun/backend/services/strategies/cross_platform.py` (AGPL — read-only)
- `/tmp/homerun/backend/services/strategies/negrisk.py`
- `/tmp/homerun/backend/services/strategies/ctf_basic_arb.py`
- `/Users/xsnyde2/prediction-market-data/data/kalshi|polymarket` (parquet schemas in drafts/pma-audit.md)
