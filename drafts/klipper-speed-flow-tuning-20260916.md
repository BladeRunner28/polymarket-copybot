# Klipper speed & flow tuning review — Voron Trident 350

**Date:** 2026-09-16 · **Machine:** Voron Trident 350 (AWD CoreXY, 48 V) · **Sources read:** `printer.cfg` (user upload 2026-09-11), `macros.cfg` (2026-09-11), sliced-file config footer from `BC-250-pro-v2_ASA_2h8m.gcode` (2026-09-11 session), Klipper `master` source (`toolhead.py`, `shaper_calibrate.py`, `shaper_defs.py`), Config_Reference (fetched 2026-09-16).

> Note: this dashboard renders drafts as plain text (`<pre>`), so markdown syntax below is literal.

---

## 1. Headline — the binding limit is in the slicer, not the printer

`filament_max_volumetric_speed = 16` mm³/s (all three filaments) on the ASA profile
"Voron PolyMaker ASA - Trident - .6mm CHT".

At 0.25 mm layer x 0.66 mm width that is **97 mm/s** of wall speed. The hotend is a Rapido UHF 2.0
with a 0.6 CHT nozzle, whose realistic ceiling is 45-60 mm³/s for ASA. **Roughly two thirds of the
machine is switched off in one profile field.** Every acceleration discussion is downstream of it.

Also read from the same footer: `filament_flow_ratio = 0.9883`, `filament_adaptive_volumetric_speed = 0`,
`enable_filament_ramming = 1`, `purge_in_prime_tower = 1`,
`change_filament_gcode = G91 / G1 Z5 F600 / G90 / PAUSE`, and `enable_pressure_advance` +
`pressure_advance` listed as non-default (so the **slicer** sets pressure advance; `printer.cfg` has
both lines commented out).

## 2. Printer config as read (printer.cfg, 2026-09-11)

| setting | value | where |
|---|---|---|
| `max_velocity` | 600 | `[printer]` L82 |
| `max_accel` | 20000 | `[printer]` L83 |
| `minimum_cruise_ratio` | 0.5 | `[printer]` L86 |
| `square_corner_velocity` | 7 | `[printer]` L87 |
| input shaper | `mzv` X 76.8 Hz (d 0.047) / Y 63.2 Hz (d 0.035) | `[input_shaper]` L685 |
| X/Y drivers | TMC5160, 48 V, `run_current: 1.75` | `[tmc5160 stepper_x…]` |
| extruder driver | TMC2209, `run_current: 0.85` (no hold_current → defaults to run) | `[tmc2209 extruder]` L313 |
| extruder mech | `gear_ratio: 50:10`, `rotation_distance: 22.074550` | `[extruder]` |
| nozzle / filament | 0.600 mm / 1.750 mm | `[extruder]` L290 |
| `pressure_advance` | **not set** (commented out, L300) | `[extruder]` |

Accelerometer (`adxl345` + `resonance_tester`) is present, so all resonance work is re-measurable in
minutes.

## 3. Ceiling 1 — melt (the one that binds today)

```
mm/s = mm3/s / (layer_height x extrusion_width)     0.25 x 0.66 = 0.165 mm^2/mm
```

| profile cap | wall speed |
|---|---|
| 16 mm³/s (today) | 97 mm/s |
| 30 | 182 mm/s |
| 45 | 273 mm/s |
| 55 | 333 mm/s |

Measurement: Orca → Calibration → **Max volumetric speed**, in the real ASA at the real temperature.
Expect 45-60. Then set the cap to ~90% of the clean value.

Decision tree at the stall point (all three are distinguishable in one test):

- temperature droop > 5 °C → heater-limited (the 90 W planar ceramic should hold, so this would be a fault)
- clean extrusion, no droop → melt-zone-limited, this is the real number
- **skipping / gaps before either** → extruder-torque-limited → raise `run_current` 0.85 → 1.0 → 1.15 A RMS, watch motor temperature

Vendor claims are ceilings, not promises: UHF melt zone is advertised at 75 mm³/s; measured Rapido
HF + CHT reports cluster at 30-35 mm³/s (ABS), and one classic Rapido HF test measured 15-17 mm³/s
against a 24 mm³/s claim. CHT nozzles buy flow with back-pressure — which is why the extruder is the
next pinch point after the slicer cap is raised.

## 4. Ceiling 2 — motion (what the config really allows)

### 4a. `max_accel: 20000` is past the shaper's budget

Recomputed with Klipper's own model (`shaper_calibrate.py`: `find_shaper_max_accel` →
`_get_shaper_smoothing` ≤ `TARGET_SMOOTHING = 0.12` mm):

| axis | shaper | suggested max_accel | smoothing at 20000 | vs budget |
|---|---|---|---|---|
| X | mzv 76.8 Hz / 0.047 | ≤ 17 226 mm/s² | 0.139 mm | +16% |
| Y | mzv 63.2 Hz / 0.035 | ≤ 11 653 mm/s² | 0.206 mm | **+72%** |

Over-budget acceleration does not present as ringing, it presents as **corner rounding** — which is
why pushing accel further feels like it stops helping. The honest statement is "Y corners blur ~0.2 mm
above ~11.7k", not "the machine cannot run 20k".

Two levers:

- **Shaper type** is an accel lever: at 63.2 Hz / 0.035, ZV allows 15 365 mm/s², MZV 11 653, ZVD 7 683. `SHAPER_CALIBRATE` picks by `score = smoothing x vibrations^1.5`, not by maximum acceleration — so ZV is a deliberate vibration-for-accel trade.
- **Fix the source**: 63 Hz on a CNC-aluminium + carbon-beam gantry points at belt tension / gantry span, not motor torque. Re-tension, re-run `TEST_RESONANCES`, compare Y frequency — if it rises, the belt was loose.

### 4b. `minimum_cruise_ratio: 0.5` caps every short move

Klipper: `mcr_pseudo_accel = max_accel * (1 - ratio)`; for a move of length d from rest,
`v ≤ sqrt(a·d·(1−r))`, i.e. cruise distance ≥ r·d (Config_Reference's own example: r = 0.5 gives a
1.5 mm move a 0.75 mm cruise).

| segment | r = 0.5 (today) | r = 0.3 | r = 0.2 |
|---|---|---|---|
| 5 mm | 224 mm/s | 265 | 283 |
| 10 mm | 316 mm/s | 374 | 400 |
| 20 mm | 447 mm/s | 529 | 566 |

The r-cap sits below `max_velocity` for every move shorter than **36.0 mm** (r = 0.5), 22.5 mm (0.2) —
so on real part geometry this ratio, not `max_velocity`, is what the toolhead obeys. Lowering
0.5 → 0.2 buys +26% on short moves and **demands +26% flow** (5 mm segment: 37 → 47 mm³/s).

### 4c. `square_corner_velocity: 7` → 15 is nearly free

| scv | Y accel budget (63.2 Hz) |
|---|---|
| 7 (today) | 11 653 |
| 10 | 11 653 |
| 15 | 11 079 (−5%) |
| 20 | 9 364 (−20%) |
| 25 | 7 650 (−34%) |

Recommendation: **15**, not the forum default of 25.

### 4d. `max_velocity: 600` is a travel setting

600 mm/s at 0.25 x 0.66 mm would need ~99 mm³/s — 2-3x any 0.6-nozzle hotend. 48 V, AWD, the CNC
frame, the carbon beam and more motor current buy acceleration and quality-at-acceleration; none of
them move the melt ceiling.

## 5. Paste-ready printer.cfg diffs — three options

Runtime-testable first (no restart, safe to bisect on a benchy):

```
SET_VELOCITY_LIMIT ACCEL=11500 SQUARE_CORNER_VELOCITY=15 MINIMUM_CRUISE_RATIO=0.3
SET_VELOCITY_LIMIT ACCEL=20000 MINIMUM_CRUISE_RATIO=0.2
```

(`SET_VELOCITY_LIMIT` accepts VELOCITY / ACCEL / SQUARE_CORNER_VELOCITY / MINIMUM_CRUISE_RATIO —
verified in `toolhead.py cmd_SET_VELOCITY_LIMIT`.)

**Option A — quality-first (recommended baseline):** corners crisp, ~10% slower on short segments.

```
[printer]
max_velocity: 600           # unchanged — travel only
max_accel: 11500            # was 20000; the shaper's own Y budget is 11 653
minimum_cruise_ratio: 0.3   # was 0.5
square_corner_velocity: 15  # was 7
```

**Option B — speed-first:** keeps the accel, accepts ~0.2 mm Y corner smoothing, spends the flow
budget on short moves.

```
[printer]
max_accel: 20000            # unchanged; Y smoothing 0.206 mm vs 0.12 budget
minimum_cruise_ratio: 0.2   # 5 mm segment 224 -> 283 mm/s (needs ~47 mm³/s)
square_corner_velocity: 15  # was 7
```

**Option C — extruder current, only if the flow test stalls the extruder:**

```
[tmc2209 extruder]
run_current: 1.0            # was 0.85; then 1.15 only if it still skips
```

Never inside the `#*# SAVE_CONFIG` block — hand edits there are discarded on the next `SAVE_CONFIG`.

## 6. Slicer-side changes

- Filament profile → **Max volumetric speed**: 16 → measured × 0.9.
- **Pressure advance**: re-run the PA calibration at the new wall speed (PA tuned at 100 mm/s bulges at 280). It is currently set from the slicer, not from `printer.cfg`.
- Per-feature acceleration: keep outer walls inside the shaper budget, run infill/travel higher.
- Cooling: ASA in a chamber is fine; the classic cooling cap is PLA at 250+ mm/s with a single 5015.
- Unrelated but still open from the earlier extrusion investigation: zero the four Multimaterial values (`parking_pos_retraction`, `extra_loading_move`, `cooling_tube_retraction`, `cooling_tube_length`) — then `max_extrude_only_distance: 100` can go back to 50.

## 7. Order of operations

1. Measure flow (volumetric test, real filament).
2. Raise the filament cap → ~250 mm/s achievable on its own.
3. Option C only if the test stalls the extruder.
4. `SHAPER_CALIBRATE` (or drop `max_accel` per Option A) + `square_corner_velocity: 15`.
5. Lower `minimum_cruise_ratio` to 0.3 once flow supports it.
6. Re-tune PA at the new speed.
7. Mechanical pass at the new acceleration: belts, pulley grub screws, toolhead play; re-measure resonances and compare frequencies before/after.

## 8. Tooling left behind

- `~/.hermes/skills/homelab/klipper-speed-and-flow-tuning/scripts/shaper_max_accel.py` — offline `suggested max_accel` (zv/mzv/zvd, `--sweep-scv`, budget check vs configured accel). Verified to reproduce Klipper's own 17 226 / 11 653.
- `~/.hermes/skills/homelab/klipper-printer-diagnostics/scripts/scan_extrude_limits.py` — replays both Klipper extrusion guards over a sliced file; use as pre-flight after re-slicing at higher flow.

## 9. Open items / not verified

- **No process-profile numbers were available** at review time: `.orca_printer` is a binary attachment, never inlined into the session, and the document cache is cleared. `outer_wall_speed`, per-feature accelerations and the PA value are therefore unknown. Re-send the profile or a freshly sliced file to audit the slicer side properly.
- `printer.cfg` reviewed is the 2026-09-11 upload; no newer one has been sent.
- Pressure advance being slicer-set is inferred from the profile's non-default flags — confirm with `grep -n "SET_PRESSURE_ADVANCE\|M572" <file>.gcode | head`.
- Y-axis 63.2 Hz was not re-measured; the belt-tension hypothesis is untested.
