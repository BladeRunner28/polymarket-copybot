# The 2 → 24h TTR floor: corrected to the population the gate binds — and it reaches nothing

**2026-11-23 · Lane B · approvals `apr-profit-floor-ttr-all-lane-basis` · card `profit-floor-ttr-all-lane-basis`**

**Status: instruments amended and verified. NO RULE CHANGED** — live floor still
`minTimeToResolutionHours = 2` (RuleSet v73), no RuleSet read/write, no prisma write, DB opened
`mode=ro`. Applying the flip remains Lane A and remains the operator's call (§6).

Two defects were reported on the card and a third was found while fixing them:

1. **Population (card's finding, fixed).** The shadow that will decide the flip measured
   **STANDARD only**; the gate it shadows is **global**. On the corrected all-lane basis the
   2-24h band is **488 settled legs / −13.32%**, of which BANKROLL_200 owns **381 legs and 88% of
   the dollars**. The pre-registered trigger (n ≥ 150, ROI ≤ +3%) is therefore **fired**, and it
   fires on a population the old shadow could not see.
2. **Mechanism (new).** Even on the right population, **the flip blocks nothing**. The short-TTR
   lane rescue clears the very skip the floor would add for every ttr ∈ [2, 72]h leg, and the live
   lane window is 72h. Running the scorer itself on a 22,464-case grid: **0 decisions, lane flags
   or sizes change**, with three controls armed. The band-removal counterfactual the card prices
   (+$26.2/day) prices a block that cannot happen.
3. **The band is two opposite populations.** Inside 2-24h the $10 lane copies return
   **+7.65%** and the main-funnel copies on the same markets return **−26.92%** at 2.4× the clip.
   The loss is a **size** signal, not an admission signal — and size is Lane A.

---

## 1. Defect 1 — the shadow measured one lane; the gate binds every lane

`minTimeToResolutionHours` is a single hard skip at `src/lib/scoring/trade.ts:124`, inside the one
`scoreTrade(..., rules)` call every lane makes (`scripts/score-trades.ts:592`). There is no per-lane
guard on it: grep it and the only other references are the field definition
(`src/lib/rules.ts:22`), its default (l.368) and the settings label. Raising it 2 → 24 therefore
binds STANDARD and BANKROLL_200 alike, while `scripts/ttr-floor-shadow.py` carried
`BOT = "STANDARD"` on the settled cohort, the openings denominator and the trailing rate.

**Forward window** (the shadow's own clock: settled, `openedAt ≥ 2026-10-23`, deduped to one leg per
`bot|wallet|market|outcome`, 31.56 days):

| population | band legs | notional | PnL | ROI | share of band $ |
|---|---:|---:|---:|---:|---:|
| **ALL lanes (decision arm)** | **488** | **$8,694.07** | **−$1,157.79** | **−13.32%** | 100% |
| BANKROLL_200 | 381 | $7,675.67 | −$955.12 | −12.44% | 88.3% |
| STANDARD (the old arm) | 107 | $1,018.40 | −$202.67 | −19.90% | 11.7% |
| kept ≥24h (all lanes) | 135 | $3,799.42 | +$520.44 | +13.70% | — |

Undeduped on the same window the band reads 492 legs / $8,740.04 / −$1,120.41 / −12.80% — the
dedupe moves 4 legs and 0.5pp, so nothing here turns on it. The pre-registered decision is
unchanged in text and threshold, and on the combined arm it now reads **FLIP**
(488 ≥ 150 settled legs, −13.32% < +3.0%). The artifact keeps the pre-change numbers reachable in
`bands_undeduped` and keeps STANDARD as `by_lane.STANDARD`.

**Card's own measurement, re-run today** (`python3 scripts/profit-tenor.py` §S15, ruleSetVersion ≥ 68,
deduped, 26.3d — the card's cut was 24.3d, which is why the dollars differ):

| population | blocked legs | notional | PnL | ROI | book kept after |
|---|---:|---:|---:|---:|---:|
| all lanes | 451 | $7,974 | −$590.30 | −7.4% | +13.9% |
| STANDARD | 97 | $838 | −$75.68 | −9.0% | +31.4% |
| BANKROLL_200 | 354 | $7,136 | −$514.59 | −7.2% | +8.8% |

Sign, direction and the 8:1 dollar split reproduce. The card's correction was right; it was
incomplete.

## 2. Defect 2 — the flip cannot reach the band it was priced on

The TTR skip is not evaluated in isolation. `laneEligible` (`trade.ts:98`) is true when the leg's ttr
sits in `[shortTtrMinHours, shortTtrMaxHours]` and its adverse drift is ≤ `shortTtrMaxDrift`; if every
hard skip on the leg is a drift or "resolves in" skip and its score clears `shortTtrMinCopyScore`,
then `laneRescuesGateFailures` (`trade.ts:268`) **clears them all**. The leg then continues to the
main path (`trade.ts:337`) or the $10 lane path (`trade.ts:402`) — precisely the two paths it takes
today. The live RuleSet carries:

```
minTimeToResolutionHours = 2      shortTtrMinHours = 2       shortTtrMaxHours = 72
shortTtrMinCopyScore     = 35     shortTtrMaxDrift = 0.05    maxPriceDrift     = 0.004
```

The lane window **contains the entire 2-24h band**, and its drift window (5¢) is looser than the
drift gate (0.4¢), so it is the looser gate that decides. Consequence: raising the floor to 24h adds
a skip that is immediately cleared. Nothing else changes — not the size, not the lane flag, not the
admission.

**Measured, not argued** (`npx tsx scripts/ttr-floor-reach-probe.ts` — it runs `scoreTrade` with the
active RuleSet twice per case, floor 2 vs floor 24, over ttr × drift × price × wallet score × spread
× liquidity):

```
  LIVE ruleset, floor 2 -> 24            reached     0 / 22464   [none]
  control A: lane disabled               reached    75 / 22464   [2-24h 75]
  control B: lane window 2-12h           reached    15 / 22464   [2-24h 15]
  control C: lane score bar 999          reached  1115 / 22464   [2-24h 1115]
  controls: A=75 B=15 C=1115 -> ARMED (each control reaches >0, so the probe can fail)
```

The controls are the point: disable the rescue, shorten the window, or raise its score bar and the
same probe starts moving decisions. The mechanism is wired; it simply does not bind here.

**Confirmed on the real book**, not only on a grid — band legs admitted since approval:

| admission path | legs | avg clip | notional | PnL | ROI | score (median) | max adverse drift |
|---|---:|---:|---:|---:|---:|---:|---:|
| short-TTR lane copies (all B200) | 296 | $11.56 | $3,420.91 | **+$261.77** | **+7.65%** | 60.5 | 0.050 |
| main funnel (107 STANDARD + 85 B200) | 192 | $27.46 | $5,273.16 | −$1,419.56 | **−26.92%** | 85.2 | 0.045 |

Every one of the 488 legs is inside the lane window, scores ≥ 37.4 (bar 35) and carries adverse drift
≤ 0.05 (window 0.05): `reachable = 0 of 488`. Admission path is read from
`DecisionJournal.reasonsJson` ("Short-TTR lane: …"), not inferred from price or size.

**So the card's +$26.2/day is not the flip's value.** It is the value of *removing* the band, and no
setting of `minTimeToResolutionHours` can remove it. The measured decomposition is worth stating
plainly: the band's loss sits entirely in **192 main-funnel legs losing $1,419.56 at a $27.46 average
clip**, while **296 lane copies in the same band earn $261.77 at $11.56**. Removing the band would
have banked the loss *and* thrown away the profit.

## 3. What shipped

| file | change | revert |
|---|---|---|
| `scripts/ttr-floor-shadow.py` | decision population = **all lanes** (STANDARD/BANKROLL_200 as sub-arms + `by_lane`); `band_admission_path` (lane vs main-funnel); `reach` block + machine-readable `action`; decision basis = deduped (raw kept as `bands_undeduped`); calibration replay pinned to STANDARD so it still reproduces the study; alerting now speaks on a **verdict/basis transition**, not every run | `git revert <commit>` |
| `scripts/ttr-floor-reach-probe.ts` | **new** read-only probe: runs `scoreTrade` under the live RuleSet at floor 2 vs 24, with three controls that must reach >0 | delete file |
| `data/ttr-floor-shadow.json` | regenerated: all-lane verdict **FLIP**, reach **0 of 488**, `action` = DO NOT APPLY | `git checkout HEAD~1 -- data/ttr-floor-shadow.json` |

Nothing reads the artifact programmatically (grep: only drafts and the two instruments name it), so
the shape change breaks no code path. The cron wrapper
(`scripts/cron-scripts/copybot-ttr-floor-shadow.sh`) is unchanged: it `exec`s the script with
`--quiet` and has no `tail` budget to outrun.

**Alert hygiene.** The old guard spoke on every run once the verdict was actionable, i.e. a daily
re-post of one settled line. It now speaks when the verdict *changes* or when the basis changes, and
stays silent otherwise. Verified in three states: repeat run → no output; artifact reset to the
pre-change state (`ACCUMULATING`, no basis stamp) → one report; next run → silence.

## 4. Verification

1. **Population parity (old vs new).** The pre-change script (`git show HEAD:scripts/ttr-floor-shadow.py`)
   run on today's rows with `--since 2024-01-01` returns **3,510 legs / $43,199.00 / −$4,844.12 /
   −11.21%**; the new script's `bands_undeduped` arm returns the **same figures to the cent**. The
   row selection and the TTR axis are unchanged; only the lane scope and the reporting grew.
2. **The old forward artifact reproduces exactly.** `by_lane_undeduped.STANDARD` in the new
   artifact reads **109 legs / 105 markets / $1,036.40 / −$165.29** with a kept band of **53 legs /
   46 markets / $1,002.78 / +$365.21** — digit for digit the artefact committed on 2026-11-23 07:20,
   which is the pre-change instrument's entire output. The deduped STANDARD arm (`by_lane.STANDARD`)
   reads 107 / $1,018.40 / −$202.67; both are printed, neither is hidden.
3. **Calibration mode still writes its own file** (`data/ttr-floor-shadow-calibration.json`) and never
   touches the forward artifact. Its all-history read is now **−11.21% on 3,510 legs** rather than the
   −12.78% recorded on 2026-10-25 — the difference is data growth (pre-existing legs that have settled
   since), **not** this change: the old script on today's rows returns −11.21% too (item 1).
4. **Reach probe**: 0/22,464 live; controls 75/15/1,115 (§2).
5. **No rule touched**: `minTimeToResolutionHours` is 2 in the active RuleSet before and after; both
   new/changed scripts open the DB `mode=ro` and contain no prisma write.
6. **Cross-check of the card's own instrument**: `scripts/profit-tenor.py` §S15 re-run today reproduces
   the sign and the lane split (§1 table).

**Limits worth naming.** The reach claim is a property of the code path, so it holds for any TTR
axis; the band *counts* use the shadow's documented axis (last snapshot at/before entry+15min,
re-based to entry). The probe rebuilds decision inputs from a grid, not from each historical row's
full input vector — a per-leg replay would need spread and liquidity at decision time, which the
journal does not store. The band's per-leg classification (lane vs main) comes from the journal's own
reason string and is complete for all 488 legs.

## 5. What is *not* fixed, and is not mine to fix

The flip's pre-registration now reads FLIP on the trigger it was given. That verdict is **true and
inert at the same time**, which is exactly the kind of number that gets acted on wrongly later, so the
artifact carries `action` beside it. The live rule is unchanged.

## 6. The operator's decision (Lane A)

- **A — leave the floor at 2h. Recommended.** The flip changes no decision, no lane flag and no size;
  applying it would only put a rule on the books claiming a band was blocked when it was not, and it
  would invite a later read to attribute the band's PnL to a floor that never fired.
- **B — if the intent is to stop the band: move `shortTtrMaxHours`, not the floor.** The lane window
  is what makes the floor inert; 72 → below 24 restores reach. Collateral is small and already
  measured: the legs at 24-72h that depend on the rescue are 38 lane copies / $385.77 / −$20.29, and
  no main-path leg sits there. Price the exact new window with the reach probe before writing anything.
- **C — the real in-band lever is SIZE, not admission.** Main-funnel 2-24h legs lose $1,419.56 on
  $5,273.16 (−26.92%) at a $27.46 average clip; lane copies in the same band earn +7.65% at $11.56.
  That is the inverse-to-edge pattern the clip cards already chase, and it overlaps
  `profit-band-clip-rebalance` / `profit-residual-cheap-longdated-clip` — do not stack a third sizing
  card on the same cell. Refutation: a forward 150 main-path 2-24h legs at ≥ 0 ROI (or ex-top-5 ≥ 0)
  withdraws it.

**Do not ship A+B+C together**: B and C fix the same band from opposite ends, and C's measured value
shrinks to whatever B leaves behind.

## 7. Re-derivation

```bash
python3 scripts/ttr-floor-shadow.py                    # all-lane forward read + reach
python3 scripts/ttr-floor-shadow.py --only-bot STANDARD   # the old arm, side by side
npx tsx scripts/ttr-floor-reach-probe.ts               # the 0/22,464 result + 3 controls
python3 scripts/profit-tenor.py | sed -n '/S15/,/S8/p' # the card's own band counterfactual
```
