# Orca checklist — ASA warping controls + per-material pressure advance

**For:** 2026-11-13, 09:00 CST · **Slicer:** OrcaSlicer **2.5.0** (confirmed from the sliced file's own
metadata) · **Machine:** Voron Trident `trident`, Rapido UHF 2.0, hardened 0.6 CHT

Field labels below were read out of **OrcaSlicer v2.5.0's own `PrintConfig.cpp`**, not from memory. If
a label still doesn't match your build, use Orca's settings **search box** and type the internal key —
the key is what the search indexes.

**This is slicer-only.** Nothing here touches Klipper, the config, or the machine.

---

## Step 0 — know which profile you are editing (1 min)

The running job's footer says the profile in use is:

- **Filament:** `Voron PolyMaker ASA - Trident - .6mm CHT`
- **Process:** the ASA process used for `BC-250-pro-v2`

**Brim is a PROCESS setting; the two fan fields are FILAMENT settings; pressure advance is FILAMENT.**
If you change the wrong one you will edit system defaults and the next slice will not change. Confirm
the active profile names in the top bar before each edit.

---

## A. Record the current values first (no machine, 2 min)

Search each key and write down what you see, so tomorrow's change is a diff and not a memory:

| key | where | current (measured today) |
|---|---|---|
| `brim_type` | Process | `no_brim` |
| `brim_width` | Process | `0` |
| `close_fan_the_first_x_layers` | Filament | `1` |
| `full_fan_speed_layer` | Filament | `2` |
| `fan_min_speed` | Filament | `15 %` |
| `fan_max_speed` | Filament | `30 %` |
| `pressure_advance` | Filament | `0.0462` |
| `enable_pressure_advance` | Filament | on |

Also: with the enclosure closed and everything cold, note the actual chamber temperature from a
thermometer if you have one. **The machine has no chamber thermistor** — `chamber_temperature = 40` in
the profile is not measured by anything.

---

## B. ASA warping — three fields (the highest-value change)

### B1. Brim — Process settings, search `brim_type`

- **`brim_type`**: `no_brim` → **`outer_only`** (dropdown label: *Outer only*)
- **`brim_width`**: `0` → **`5`** mm
- **`brim_object_gap`**: leave at `0.125`

> Valid `brim_type` values in 2.5.0 are `auto_brim`, `brim_ears`, `painted`, `outer_only`,
> `inner_only`, `outer_and_inner`, `no_brim`, `leading_edge_only`. There is **no `outer`** — that is
> why the dropdown matters more than the key name here.

### B2. Delay the fan — Filament settings, search `close_fan_the_first_x_layers`

- **`close_fan_the_first_x_layers`**: `1` → **`3`** (try 5 if the first attempt still lifts)

Label verified: *"No cooling for the first"*. Currently one layer of fan-off on ASA, which is not a
warm-up.

### B3. Push back full fan — Filament settings, search `full_fan_speed_layer`

- **`full_fan_speed_layer`**: `2` → **`8`**
- Optional, only if B2+B3 are not enough: **`fan_max_speed`** `30` → **`20`** %

Label verified: *"Full fan speed at layer"*. Reaching full ASA fan at layer 2 is the single most
warping-friendly thing in this profile.

### The refutation test (write it down before you slice)

- **Prediction:** cancels below 35 % progress fall for ASA.
- **Refuted if:** the next 10 ASA jobs that run ≥ 0.1 h still cancel early at the same rate
  (measured baseline: 26 of 44 cancels landed below 35 %). That would move the cause to **bed prep or
  chamber temperature**, not brim/cooling — and the next step becomes first-layer squish and a chamber
  measurement, not more fan changes.

---

## C. Pressure advance per material — needs heat, one at a time

**All six materials currently share `0.0462`, which is an ASA number.** That is a surface-finish
defect generator on the others.

### Procedure, per filament

1. Select that filament's profile (ASA first — it is 93 % of your history).
2. **Calibration → Pressure Advance** in Orca; slice and print the generated test on the ASA process.
3. Read the band where the wall joins are cleanest; Orca prints the PA value on each band.
4. Type that number into the **filament's** `pressure_advance` field (search `pressure_advance`), with
   `enable_pressure_advance` on.
5. **Record it in the table below before moving to the next material.** A measured PA that is not
   written into the profile is a number that will be lost.

### Sanity ranges — expectations, not targets

If a measurement lands far outside these, that is a **finding**, not a failed test — say so rather than
tuning to the expected number:

| material | typical PA, direct drive | note |
|---|---|---|
| ASA / ABS | 0.03 – 0.06 | current 0.0462 sits here |
| PLA | 0.015 – 0.03 | much lower than ASA |
| PETG | 0.03 – 0.06 | |
| TPU | 0.10 – 0.20 | very high; soft filament lags badly |
| PET-CF | 0.03 – 0.06 | hardened nozzle already confirmed |

### Results table — fill this in and I will read it back

| material | PA before | PA after | test band | notes |
|---|---|---|---|---|
| ASA | 0.0462 | | | |
| ABS | 0.0462 | | | |
| PLA | 0.0462 | | | |
| PETG | 0.0462 | | | |
| TPU | 0.0462 | | | |
| PET-CF | 0.0462 | | | |

**Automatic verification:** once you slice the first ASA part with the new settings, the gcode footer
carries `brim_type`, `brim_width` and `pressure_advance` resolved — I can read them off the printer
without asking you, which is how we confirm the change actually landed in the profile and not just in
the dialog.

---

## D. Not tomorrow, on purpose

- **`filament_max_volumetric_speed = 16`** stays. It is inherited and probably wrong, but changing it
  changes all six materials at once and you ranked speed last.
- **`max_accel`** stays at the slicer's 10,000. The Y input-shaper ceiling is 11,653 mm/s², so raising
  it buys corner blur, not speed.
- **No Klipper config edits. No input-shaper recalibration.** Nothing in this checklist requires the
  printer to be anything but idle.

---

## E. Session mechanics

- Machine must be **idle** — tonight's `BC-250-pro-v2_ASA_12h43m` was at 10.5 % at 11:00 with an
  estimated 12.7 h, so it should be done well before 09:00. I will confirm before we start.
- **Stop signal: say "stop calibration"** and I stop at the next safe point, never mid-move.
- Order if time is short: **B before C.** B is free and attacks the measured failure class (warping);
  C is per-material polish on your #2 axis.
