# v51 — Dead-zone ×0.25 + long-shot ×2.0 + Kelly band rails (2026-09-07 C-200 daily report changes 1+2, user-approved — explicit Kelly-window freeze override)

Source: copybot-c200-daily-report (2026-09-07 18:00 CDT). User approved "I approve
these changes", then chose FULL implementation over the map-only option via
clarify (explicit override of the precommit-mid-oct-kelly-gate freeze, which
opens Sep 8). Code-only — NO RuleSet bump (no rule fields changed), so the
tuning-review "rule-changes-since-v50=0" counter stays honest.

## Evidence (regime-split, from the report's fresh N=1,223 calibration)

- **0.40–0.60 dead zone**: current regime z=−3.75, −$205.01 (N=141 since Aug 28;
  Sep 1+ alone −$190 on N=73, z=−3.58 ≈ −$27/day). Survives the regime split.
- **<0.20 long-shot**: z=+4.82 pooled, +$239.71 current regime, positive in both
  sub-periods (Aug 28–31 +$105, Sep 1+ +$202) — the only regime-robust edge.
- Explicitly NOT touched (report's own regime caveat): hour gates (no current-
  regime hour survives |z|≥2), 0.20–0.40 (edge is legacy-driven), ≥0.60
  favorite drag (already fixed in current regime: z=−1.51/−0.65 ns).

## Changes (all in the C-200 sizing path — STANDARD untouched)

### 1. `src/lib/paper.ts` `mapBankroll200Size` (legacy path + short-TTR lane)
- 0.40–0.60: ×0.5 → **×0.25** (was ×0.75 v42, ×1.0 pre-v42)
- <0.20: ×1.5 → **×2.0**
- ≥0.60 stays ×0.5 (current-regime drag already fixed — leave alone)
- Lane copies bypass Kelly and ride this map, so this is what actually cuts the
  live dead-zone bleed (main-lane Kelly already skips 0.40–0.60 via λ̂=+0.03).

### 2. NEW `applyKellyBandRails` (pure fn, same file) + wiring in `scripts/score-trades.ts`
Kelly-sized main-lane admits (which bypass the band map) get band rails so the
Kelly path cannot contradict the map on the two regime-robust findings while λ̂
tables sit between refits:
- dead zone [0.40, 0.60): `min(kellySize, legacyEquiv)` — cap (legacy-equiv =
  clampPaperSize(mapBankroll200Size(decisionSize, entry)), i.e. the ×0.25 map)
- long-shot <0.20: `max(kellySize, legacyEquiv)` — floor (×2.0 map)
- all other bands pass through
- Logged as `[KELLY-RAIL]` only when the rail binds. **Inert today**: Kelly
  skips the dead zone (λ̂=+0.03 → f*≤0) and fully funds <0.20 (λ̂=−0.91) up to
  kellyMaxSizeUsd $100 — the rails bind only if the Sep 15 / Oct 1 mid-window
  λ̂ refits move those bands against the findings (the report's insurance).

## Verification

tsc clean · **118/118 tests** (paper-sizing updated to the v51 multipliers +
3 new rail tests: cap binds / floor lifts / pass-through bands + boundaries at
0.20/0.40/0.59/0.60) · commit `…` (see git log).

## Notes

- Explicit freeze override per user choice ("Full implementation now") — the
  Kelly window (Sep 8–Oct 8) will measure the v51 configuration; flag this in
  the Oct 8 precommit read alongside v50.
- The report's open question (dead zone flipping sign at the Sep-1 boundary:
  +$183 Aug 28–31 z=+1.86 → −$190 Sep 1+ z=−3.58) remains worth a one-off
  ruleSetVersion split during the window (observability-only, allowed) before
  the Oct 8 read.
