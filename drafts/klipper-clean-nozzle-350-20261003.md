# CLEAN_NOZZLE for a 350 mm Voron Trident — nozzle-brush macro, corrected and re-scaled

**Source model:** [Printables 1059809 — "Siboor Voron AWD Trident Bambu Nozzle Brush"](https://www.printables.com/model/1059809-siboor-voron-awd-trident-bambu-nozzle-brush) by **Ski3d**
(summary: *"Simple nozzle brush that mounts to the bed frame for the siboor awd trident (300mm bed)"* — read from the
Printables GraphQL API 2026-10-03, since the web page itself is behind a Cloudflare challenge.)

**Why the author built it:** *"Needed a way to wipe before cartographer does it z offset using touch."*
**Your machine matches the intent:** `klippy.log` shows `stepper_x / x1 / y / y1` (four X/Y motors = AWD) plus a
Cartographer v4 on `scanner`, i.e. the same probe strategy and the same gantry family.

**Nothing on the printer was touched. This is a paste-ready block for `macros.cfg` plus a calibration procedure you
run by hand.**

---

## 1. The author's macro, as published

```ini
[gcode_macro CLEAN_NOZZLE]
variable_start_x: 228
variable_start_y: 307
variable_start_z: 1
variable_wipe_dist: -35
variable_wipe_qty: 10
variable_wipe_spd: 200
variable_raise_distance: 20

gcode:
  {% if "xyz" not in printer.toolhead.homed_axes %}
   G28
  {% endif %}

  G90                                ; absolute positioning
  ## Move nozzle to start position
  G1 Z6
  G1 X{start_x} Y{start_y} F6000
  G1 Z{start_z} F1500

  ## Wipe nozzle
  {% for wipes in range(1, (wipe_qty + 1)) %}
   G1 X{start_x + wipe_dist} F{wipe_spd * 60}
   G1 X{start_x} F{wipe_spd * 60}
  {% endfor %}

  ## Raise nozzle
  G1 X282 Z{raise_distance}
```

His own tuning note is worth keeping: *"I stuck the brush as close as the bed as I could… i also use .5 for
variable_start_z. But i would start with 8 to make sure its brushing in the right area first then bring down your
variable_start_z."*

## 2. What does not carry over to a 350, and the four real defects

| | Issue | Why it matters on your machine |
|---|---|---|
| 1 | **`G1 X282 Z{raise_distance}` hard-codes X282** | 282 is arbitrary even on a 300 bed; on a 350 it is a coordinate nobody chose. The exit move must be a variable. |
| 2 | **The exit move is diagonal** (X and Z together) | It slides sideways *at wipe depth* while only rising. If `raise_distance` is ever reduced, the nozzle drags through the bristles on the way out. Lift first, then move. |
| 3 | **The wipe window is unguarded** | The wipe runs `start_x → start_x + wipe_dist` and back. If that window overshoots the brush's X extent, the nozzle grinds along the frame/bracket instead of the bristles. On a 350 there is more travel, so more room to get it wrong. |
| 4 | **The Z offset is ignored** | Klipper's `G1 Z…` is in g-code coordinates. Called with a live babystep offset (e.g. from a PAUSE), "Z1" is not 1 mm above the bed. Fixed with `SAVE_GCODE_STATE` + `SET_GCODE_OFFSET Z=0` + `RESTORE_GCODE_STATE` — Klipper's `RESTORE_GCODE_STATE` restores `homing_position` (i.e. the offset) along with speed and modes, so the offset comes back by itself. |
| 5 | **`start_x: 228` / `start_y: 307` are 300 mm numbers** | Y307 is ~7 mm past a 300 bed's edge, which is why the author needed a `position_max` that reaches it. Your bed edge is at ~355 and your frame sits further back again. |

Not defects, for the record: `F{wipe_spd * 60}` is correct (Klipper's `F` is mm/min, so 200 mm/s = 12000 mm/min),
`start_z` *is* the depth you wipe at, and wiping along X is right for this model (the bristle strip runs along X —
if you ever mount it rotated 90°, swap the wipe axis).

## 3. Corrected macro — 350 mm Trident (paste-ready, goes at the end of `macros.cfg`)

Every `#*` value is **measured once** per §4 — everything else is a safe default.

```ini
###############################################################
## CLEAN_NOZZLE - wipe the nozzle on the bed-frame brush
## Adapted for a 350 mm Voron Trident from Printables model
## 1059809 by Ski3d. Values marked #* must be calibrated (§4).
###############################################################
[gcode_macro CLEAN_NOZZLE]
description: Wipe the nozzle on the bed-frame brush
variable_start_x: 175          #* X the wipe returns to      [MEASURE]
variable_start_y: 357          #* Y of the brush             [MEASURE]
variable_start_z: 8            #* wipe depth: start at 8, walk down to 0.5-1.0
variable_wipe_dist: -40        #  wipe travel in X (negative = toward -X)
variable_wipe_qty: 10          #  back-and-forth passes
variable_wipe_spd: 100         #  mm/s (author used 200; slower is kinder to the probe)
variable_travel_z: 10          #  travel height - must clear the bristles
variable_raise_distance: 20    #  straight-up Z before leaving the brush
variable_park_x: 175           #  where to go afterwards (bed centre)
variable_park_y: 175
variable_brush_x_min: 140      #* left  end of the bristle strip  [MEASURE]
variable_brush_x_max: 210      #* right end of the bristle strip  [MEASURE]

gcode:
  {% if "xyz" not in printer.toolhead.homed_axes %}
    G28
  {% endif %}

  ## ---- guard: never wipe off the end of the brush -------------------
  {% set wipe_end = start_x + wipe_dist %}
  {% set x_lo = [start_x, wipe_end] | min %}
  {% set x_hi = [start_x, wipe_end] | max %}
  {% if x_lo < brush_x_min or x_hi > brush_x_max %}
    {action_raise_error("CLEAN_NOZZLE: wipe window X%0.1f-X%0.1f leaves the brush (X%0.1f-X%0.1f). Fix start_x / wipe_dist / brush_x_min / brush_x_max." % (x_lo, x_hi, brush_x_min, brush_x_max))}
  {% endif %}

  ## SAVE/RESTORE_GCODE_STATE carries the g-code offset (and speed/mode)
  ## across the wipe, so a live babystep offset cannot shift the wipe Z.
  SAVE_GCODE_STATE NAME=clean_nozzle
  G90
  SET_GCODE_OFFSET Z=0
  M400

  ## 1) rise to travel height BEFORE any XY motion
  G1 Z{travel_z} F1500
  ## 2) travel to the brush
  G1 X{start_x} Y{start_y} F6000
  ## 3) descend into the bristles (no XY motion while descending)
  G1 Z{start_z} F600
  ## 4) wipe - Z is held constant, because on a Trident the brush rides
  ##    on the bed frame and the bed is what moves in Z
  {% for wipes in range(1, wipe_qty + 1) %}
    G1 X{wipe_end} F{wipe_spd * 60}
    G1 X{start_x} F{wipe_spd * 60}
  {% endfor %}
  ## 5) straight up out of the brush, then park
  G1 Z{raise_distance} F1500
  G1 X{park_x} Y{park_y} F9000

  RESTORE_GCODE_STATE NAME=clean_nozzle   ; restores the Z offset as well
```

**Before pasting:** make sure the name is free. A second `[gcode_macro CLEAN_NOZZLE]` is a config error
(`Section 'gcode_macro CLEAN_NOZZLE' already exists`), and your config is split across several files:

```bash
grep -rn "CLEAN_NOZZLE" ~/printer_data/config/
```

Put the block in `~/printer_data/config/macros.cfg` — **never** inside the `#*# SAVE_CONFIG` block, which is
regenerated on the next `SAVE_CONFIG`.

## 4. One-time calibration (~20 min, three measurements)

### 4a. The Y reach — the only number that can crash the toolhead

The brush sits on the bed frame, i.e. **behind** the bed's 350 mm edge (the author's 307 on a 300 mm bed is ~2 mm
past that bed's edge). You must be able to *reach* it, and Klipper will refuse any move past `position_max`:

```bash
grep -n -A6 "\[stepper_y\]" ~/printer_data/config/printer.cfg | grep position_max
```

Then find the real limit by hand — jog in small steps with your hand on the power switch:

```gcode
G28
G90
G1 Z10 F1500
G91                ; relative
G1 Y5 F1200        ; repeat, watching the rear frame clearance
GET_POSITION       ; last value before contact = your true Y max
G90
```

- **Brush within `position_max`** → nothing to change; use that Y as `start_y`.
- **Brush beyond it** → either raise `position_max` in `[stepper_y]` (only as far as the toolhead physically clears,
  and re-check `position_endstop`), or move the brush forward on the frame. Raising a `position_max` past the
  machine's real travel is how a nozzle brush turns into a crashed gantry — verify by jogging, never by arithmetic.

### 4b. The X window

Jog the nozzle over the bristles and record both ends:

```gcode
G1 X140 Y357 F3000      ; use your measured Y
GET_POSITION            ; -> brush_x_min
G1 X210 Y357 F3000
GET_POSITION            ; -> brush_x_max
```

Set `start_x` to the end you want to start from and `wipe_dist` to `-(length - 5)` so the window stays ~5 mm inside
the measured extent. The guard in the macro refuses to run if you get this wrong, which is the point of it.

### 4c. The Z ladder — the only step that touches the brush

Start high and walk down, with the nozzle hot (a cold nozzle wipes nothing):

```gcode
M104 S150
CLEAN_NOZZLE           ; start_z = 8: verify the wipe passes OVER the bristles
```

Then set `start_z` to 6, 4, 2, 1, 0.5 and call it again each time. Stop when the nozzle is visibly wiping *through*
the bristles. The author's production value is 0.5-1.0.

**Watch the probe on every step, not just the nozzle.** Cartographer's touch mode stops *"as soon as the nozzle
touches the bed"*, so the nozzle is the contact element — but the Cartographer body and the brush's bracket and bolt
still sit at that height, and the deepest safe `start_z` is set by whichever of them touches the bristles first.

## 5. Integration: where the wipe belongs in PRINT_START

Cartographer's own PRINT_START template is explicit about why this mod exists, and it names the exact insertion point:

```gcode
  G28                       ; Home all axes
  M104 S150                 ; Heat nozzle to soften filament leftovers
  ("Heat bed to print temperature")
  ("Z_TILT_ADJUST")         ; Quad gantry level / Z tilt
  M109 S150                 ; Ensure nozzle is at 150C
  CLEAN_NOZZLE              ; <-- HERE: wipe the softened goop off first
  CARTOGRAPHER_TOUCH_HOME   ; Home for real Z0 - now the touch is off a clean nozzle
  ("BED_MESH_CALIBRATE ADAPTIVE=1")
  ("Heat to print temperature and prime")
```

Their docs add the constraint that makes this work: *"Make sure your nozzle is below 150 degrees"* for
`CARTOGRAPHER_TOUCH_HOME` — 150 °C is hot enough to soften leftover filament (their reason for `M104 S150`) and cool
enough for touch. Put `CLEAN_NOZZLE` **between `M109 S150` and `CARTOGRAPHER_TOUCH_HOME`**, in the macro that
OrcaSlicer calls as `PRINT_START` — not in the slicer's G-code box, so every job gets it.

## 6. What I have not verified

- **Your `printer.cfg` / `macros.cfg` were not read** — they live on the CM4, not on this machine; §4a's
  `position_max` line and the duplicate-name check are for you to run. If you already have a `CLEAN_NOZZLE` (e.g.
  from a purge-bucket mod), replace it rather than adding a second one.
- **The brush's actual coordinates** are unknown by construction: they depend on where the bracket's T-nut landed in
  the frame slot. Defaults are deliberately conservative and the X guard is deliberately loud.
- **The bristle-strip orientation** is assumed to run along X (true for the published macro; re-check if you rotate
  the mount).
- The model page was read through Printables' GraphQL API because the HTML is behind a Cloudflare challenge; the
  macro text above is transcribed from the model's own description.

---

## Paste-ready block (identical to §3)

```ini
###############################################################
## CLEAN_NOZZLE - wipe the nozzle on the bed-frame brush
## Adapted for a 350 mm Voron Trident from Printables model
## 1059809 by Ski3d. Values marked #* must be calibrated (§4).
###############################################################
[gcode_macro CLEAN_NOZZLE]
description: Wipe the nozzle on the bed-frame brush
variable_start_x: 175          #* X the wipe returns to      [MEASURE]
variable_start_y: 357          #* Y of the brush             [MEASURE]
variable_start_z: 8            #* wipe depth: start at 8, walk down to 0.5-1.0
variable_wipe_dist: -40        #  wipe travel in X (negative = toward -X)
variable_wipe_qty: 10          #  back-and-forth passes
variable_wipe_spd: 100         #  mm/s (author used 200; slower is kinder to the probe)
variable_travel_z: 10          #  travel height - must clear the bristles
variable_raise_distance: 20    #  straight-up Z before leaving the brush
variable_park_x: 175           #  where to go afterwards (bed centre)
variable_park_y: 175
variable_brush_x_min: 140      #* left  end of the bristle strip  [MEASURE]
variable_brush_x_max: 210      #* right end of the bristle strip  [MEASURE]

gcode:
  {% if "xyz" not in printer.toolhead.homed_axes %}
    G28
  {% endif %}

  ## ---- guard: never wipe off the end of the brush -------------------
  {% set wipe_end = start_x + wipe_dist %}
  {% set x_lo = [start_x, wipe_end] | min %}
  {% set x_hi = [start_x, wipe_end] | max %}
  {% if x_lo < brush_x_min or x_hi > brush_x_max %}
    {action_raise_error("CLEAN_NOZZLE: wipe window X%0.1f-X%0.1f leaves the brush (X%0.1f-X%0.1f). Fix start_x / wipe_dist / brush_x_min / brush_x_max." % (x_lo, x_hi, brush_x_min, brush_x_max))}
  {% endif %}

  ## SAVE/RESTORE_GCODE_STATE carries the g-code offset (and speed/mode)
  ## across the wipe, so a live babystep offset cannot shift the wipe Z.
  SAVE_GCODE_STATE NAME=clean_nozzle
  G90
  SET_GCODE_OFFSET Z=0
  M400

  ## 1) rise to travel height BEFORE any XY motion
  G1 Z{travel_z} F1500
  ## 2) travel to the brush
  G1 X{start_x} Y{start_y} F6000
  ## 3) descend into the bristles (no XY motion while descending)
  G1 Z{start_z} F600
  ## 4) wipe - Z is held constant, because on a Trident the brush rides
  ##    on the bed frame and the bed is what moves in Z
  {% for wipes in range(1, wipe_qty + 1) %}
    G1 X{wipe_end} F{wipe_spd * 60}
    G1 X{start_x} F{wipe_spd * 60}
  {% endfor %}
  ## 5) straight up out of the brush, then park
  G1 Z{raise_distance} F1500
  G1 X{park_x} Y{park_y} F9000

  RESTORE_GCODE_STATE NAME=clean_nozzle   ; restores the Z offset as well
```
