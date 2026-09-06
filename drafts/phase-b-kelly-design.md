# Phase B — Kelly Sizing for C-200 (Design + Pre-registration)

**Status:** APPROVED for wiring 2026-09-05 ("keep going") — implementation
complete, 115/115 tests green, tsc clean. Activation (`scripts/apply-v49.ts`)
pending ship **Tue 2026-09-08** (window start), revertible via kellyEnabled→0.
**Author:** hermes · **Date:** 2026-09-05
**Approval:** user (paper-only, flag-revertible via RuleSet).
**Sources:** octagon-audit.md §2 (MIT, executable-quote Kelly), Thorp (2006),
scripts/calibrate-premium.py → data/premium-calibration.json (Sep 1 refit).

---

## 1. Problem

Current C-200 main-lane sizing is a chain of heuristics layered on the base
score size: ×3 confidence boost (conf > 0.90), v38 premium overlay
(`size × clamp(1 − k·λ̂)`), hour-policy haircut, then paper.ts band remap +
caps. Heuristics cannot answer the only question that matters: **given the
calibrated edge of copying in this band, what fraction of available bankroll
should this position be?** The realized band analysis (2026-09-05) shows the
stakes: 0.40–0.60 mid-band = −$434 (46% of all trades), <0.20 long-shots = +$93.

## 2. Edge definition (calibrated, executable)

For a copy entered at price `p` (the token's price actually paid via the
shadow-FAK engine — executable by construction), band λ̂ comes from the
biweekly Wang calibration: `p_mkt = Φ(Φ⁻¹(p*) + λ̂)` (λ̂>0 ⇒ overpriced entry).

**Fair probability:** `q = Φ(Φ⁻¹(p) − λ̂)`  (λ̂ = band λ̂ + Kalshi venue offset if applicable)

**Kelly fraction (binary, side-aware):**
```
buy YES at p:  f* = (q − p) / (1 − p)
buy NO  at p:  f* = (q − p) / p          (q = fair prob of the bought token)
f* ≤ 0  ⇒ no edge ⇒ SKIP (never a floor-size bet)
```

This is Octagon's executable-quote formula reduced by our fill model: their
`executableEdge = (model − market) − (ask − market)` subtracts the ask premium;
our FAK engine already books the executable price, so `p` IS the ask-adjusted
price. If raw mid-prices ever feed the sizing path, thread bestAsk from
MarketSnapshot (follow-up, flagged).

## 3. Size rule

```
edge f* = kellyFraction (half-Kelly default 0.5) × f*
availBankroll = cashBalance − open exposure (live, as score-trades already computes)
sizeUsd = min(f*·availBankroll, kellyMaxBankrollPct·availBankroll, kellyMaxSizeUsd)
skip if f* < kellyMinEdgePct (edge too small to act on)
skip if computed < kellyMinBetUsd (dust)
clamp floor at kellyMinBetUsd when above skip thresholds
```

Outer gates UNCHANGED and still binding: maxGrossExposureUsd (v46 base $400 +
equity kicker), per-category 40, per-slug 15, daily-loss −$150, drawdown 20%,
c200MaxEntryPrice 0.80 hard cap, v45 blacklists, short-TTR lane keeps its fixed
size (channel design), hour-policy haircut applies AFTER Kelly (orthogonal
time-of-day effect).

## 4. What Kelly replaces (when kellyEnabled=1)

- The ×3 confidence boost (Kelly already scales by edge).
- The v38 premium-overlay factor chain (redundant with the λ̂-based edge;
  premiumOverlayEnabled set 0 in the same ruleset change — revertible).
- The paper.ts v41 band remap is bypassed for Kelly-sized copies (no double
  sizing) — legacy path unchanged when kellyEnabled=0.

**Entry admission unchanged** (copyScore/confidence bars, v48 long-shot floor
relaxation). Kelly decides size and skip, not admission.

## 5. RuleSet fields (v49, defaults; live values land in the DB at activation)

| field | default | meaning |
|---|---|---|
| kellyEnabled | 0 (v49 sets 1) | master flag — 0 restores legacy sizing |
| kellyFraction | 0.5 | fractional-Kelly multiplier |
| kellyMaxBankrollPct | 0.10 | cap as % of available bankroll |
| kellyMaxSizeUsd | 60 | hard per-position USD cap (legacy hard cap was 45; exposure cap $400 still binds book-wide) |
| kellyMinBetUsd | 2.0 | skip dust below this |
| kellyMinEdgePct | 0.02 | skip when f* < 2% |

## 6. Pre-registered expectations (window Sep 8 – Oct 8, reads Oct 8)

Sep-1 λ̂ table vs realized band PnL (2026-09-05 analysis) — sign alignment:

| band | λ̂ | Kelly | realized | verdict |
|---|---|---|---|---|
| <0.20 | −0.91 | size (cap-bound) | +$93 | aligned |
| 0.20–0.40 | −0.21 | size | +$62 | aligned |
| 0.40–0.60 | +0.03 | skip (~0 edge) | −$434 | aligned-by-skip (calibration ≈ fair; realized bad — Kelly starves it regardless) |
| 0.60–0.80 | +0.21 | skip | −$46 | aligned |
| ≥0.80 | +0.37 | skip | +$1.50 flat | mild misalignment, immaterial |

Expected: book concentrates in <0.40; mid-band + 0.60+ trade counts → ≈0;
long-shot band share of realized PnL 3–6× pre-Kelly (phase-b falsifiable
target); max drawdown not above pre-Kelly clean baseline.
CAVEAT (documented): λ̂ is a PREMIUM measure, not a PnL measure — the Sep-1
table's mid-band ≈ 0 skips a −EV region by luck of the zero-edge rule, not by
calibration sight. If the Sep 15 refit moves mid-band λ̂ negative, Kelly will
resume sizing it — the Oct 8 read must check band λ̂ vs realized band PnL
(alignment check) alongside the PnL targets.
KELLY LOGGING: `[KELLY] marketId band λ̂ q p f* avail size skip? reason` per
C-200 main-lane decision + `premium λ̂=` journal tag retained.

## 7. Risk notes

- Capacity: long-shot sizes land at the cap ($60 → 6–15% of a ~$400–1,100
  available book); the n=57 band's realized edge may shrink as size grows —
  that's what the window measures.
- λ̂ staleness: ships on Sep-1 refit (7d old, in-envelope); Sep 15 + Oct 1
  refits land mid-window as scheduled system refreshes (allowed).
- Paper-only; revert = rule change kellyEnabled→0 (legacy sizing intact).

## 8. Files

- `src/lib/kelly.ts` — pure sizer (normal CDF/inv via Acklam; fair prob; f*;
  sizeForCopy). MIT-derived formulas, reimplemented.
- `tests/kelly.test.ts` — unit tests.
- Wiring (score-trades.ts + paper.ts map guard + apply-v49.ts) lands with the
  implementation; this doc is the approval artifact.

---

## 9. Implementation notes & errata (2026-09-05, wired + green)

Wiring completed per §3–§6. Three reconciliations found during wiring, none
changing the pre-registered expectations:

1. **Executor cap was $20, not "$45".** The real legacy per-position cap is
   `BOT_LIMITS.BANKROLL_200.max = $20` (safety.ts; DB max size 20.00 exactly
   across 1,279 C-200 trades). The ×3 boost / overlay inline `45.00` caps were
   dead code downstream of the clamp. Kelly's §5 `kellyMaxSizeUsd = 60` is
   therefore enforced via a **per-call clamp override on the Kelly path only**
   (`openPaperTrade({kelly})` → `clampPaperSize(size, botId, maxSizeUsd)`);
   `kellyEnabled=0` keeps the legacy $20 cap byte-identical. Without this,
   the capacity question the window exists to measure (edge survival at
   $60/copy vs ~$5–20) could not resolve.
2. **availableBankroll = cashBalance (free cash), not cash − open exposure.**
   The ledger decrements cashBalance at fill and returns principal+pnl at
   resolution, so open notional is ALREADY excluded (verified: principal
   $1,900 − realized $317.83 − open $382.29 = cash $1,199.87). The §3 phrase
   "cashBalance − open exposure" double-counts and would starve the 0.20–0.40
   band below its cap ($44 vs the §6-expected $60). The $1,146 book in
   tests/kelly.test.ts is cashBalance scale. Wiring uses `cashBalance`.
3. **NO-side formula.** §2's `f* = (q − p)/p` for NO is stale prose from the
   audit's YES/NO pair reduction; `kelly.ts` and its tests lock the correct
   bought-token form `f* = (q − p)/(1 − p)` for BOTH sides (test: NO@0.70,
   fair 0.75 → 0.1667). Math unchanged for YES.

Also: with Kelly active the code **skips the ×3 boost** for Kelly-sized copies
and **guards the v38 overlay** (`!kellySized`) even before the §4 flag flip;
the short-TTR lane keeps its fixed size; hour-policy haircut still applies
AFTER Kelly (orthogonal, §3); STANDARD book untouched. `[KELLY] marketId band
λ̂ q p f* avail size SKIP? reason` logged per C-200 main-lane decision.

