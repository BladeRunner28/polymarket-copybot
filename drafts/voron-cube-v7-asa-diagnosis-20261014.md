# Voron Design Cube v7 — print diagnosis (ASA, 0.2 mm, 0.6 nozzle)

**Printed:** `Voron_Design_Cube_v7_ASA_31m29s.gcode` · OrcaSlicer 2.4.2, generated 2026-10-14 10:55:11 ·
41.1 min · 5.02 m / 12.08 cm³ASA · 150 layers, Z 0.2 → **30.00 mm** (nominal 30 mm cube, no Z loss) ·
29.4 × 29.4 mm body.
**Machine:** `trident` (Voron Trident 350, AWD CoreXY) — Klipper v0.13.0-762-g9871eeef, Mainsail/Moonraker
v0.10.0, Cartographer v4 6.2.0.
**Source of every number below:** the machine's own Moonraker API (job history + live config) and the
sliced file's footer — not the photos. Photo references are to the six images sent.

---

## 1. What is actually healthy (so fixes target the real causes)

- **It completed.** `Exiting SD card print (position 1354813)` = EOF of the 1,354,813-byte file.
- **No machine fault in the session:** 0 × `Transition to shutdown state`, 0 × `Timer too close`,
  0 × `Lost communication`, 0 × `trsync` errors. Cone/current stats: all nodes `bus_state=active`,
  `rx_error=0`, `tx_error=0`, `rto=0.025` (no ramp).
- **Z is exact:** 150 × 0.2 = 30.00 mm — no over/under-extrusion signature in the vertical.
- **Walls are clean:** the side faces (photos 1–4) show even, parallel layer lines with no banding,
  no Z-wobble, no visible ringing around the logo pocket, and crisp vertical corners.
- **Chamfers are the "hexagons" you are seeing.** The model has large chamfered edges (slicer
  thumbnail confirms an octagonal silhouette). The "hexagonal pockets" and glossy bands in photos 2
  and 4 are those 45° facets catching light, **not** a defect.
- **Input shaping is configured and sane:** `mzv` 76.8 Hz X / 63.2 Hz Y, damping 0.047 / 0.035.

## 2. Findings, ranked by what it costs you

### F1 — Top/plate-facing surface is rippled and matt-grained (photos 5, 6)
The face in photos 5–6 reads as the **plate-facing (first) layer**: its texture is a *uniform,
isotropic* stipple (no directional extrusion pattern), it carries a flange in its own plane, and
there is a ring on the floor of the bore — that is the inner brim. On a **textured PEI** sheet this
stipple is the plate's imprint and is expected; on a smooth sheet it means the nozzle is ~0.1–0.2 mm
too low.
Independent of the plate, the recipe below is a known top-surface roughener:

```
; top_shell_layers = 4          but also
; top_shell_thickness = 0.6     -> 0.6 mm = 3 layers at 0.2 mm
; sparse_infill_density = 10%   gyroid
; sparse_infill_line_width = 0.6
```
At a 0.6 mm line width and 10 % gyroid the skin spans are large; a 3-layer (0.6 mm) top shell is
where **pillowing** (skin sagging into the infill voids) shows up as ribs, ripples and light-catching
high spots — the mottled, sandy look and the faint pattern ghosting on the top face.
**10-second check:** straightedge across the top face — light visible under the middle = pillowing.

### F2 — Ooze / stringing wisps (photos 4, 5, 6)
A visible filament wisp inside the logo pocket (photo 4) and across the bore mouth (photo 6). Profile:
`nozzle_temperature 260 · fan_max_speed 30% · retraction_length 0.8 · retraction_speed 30 ·
wipe 1 · z_hop 0.4 · retract_when_changing_layer 1`.
0.8 mm at 30 mm/s through a 0.6 CHT nozzle at 260 °C is on the low/slow side for ASA, and ASA picks
up moisture fast — wet ASA is the classic cause of both the wisps and a dull, sputtery surface.
**Order matters:** dry first, then touch retraction. Drying fixes the cause; more retraction only
hides it.

### F3 — Brim is fused, and a brim was printed INSIDE the bore
`brim_type = outer_and_inner` + `brim_object_gap = 0.1` + `brim_width = 5` → the outer brim needs a
knife (visible in photos 1–3), **and an inner brim ring lands inside the bore** (the ring on the
bore floor in photo 6), which rounds the bore's mouth and pushes a blade into the hole. The sharp
"X" beside the bore mouth in photo 1 reads as a *printed* feature, not a cut — but if it is a cut,
this is what caused it.

### F4 — Bottom flare (elephant foot) uncompensated
`xy_contour_compensation = 0`, `xy_hole_compensation = 0`, and **no `elephant_foot_compensation` key
in the profile at all** (`precise_z_height = 0`). A first layer squished by low Z with no compensation
flares the bottom ~1 mm (photos 1–3, under the brim), and shrinks holes.
**Check with calipers:** bottom 2 mm across = 30.0 mm? Holes at nominal? If 30.2–30.5 mm → enable it.

### F5 — Flow is compensated twice, in opposite directions
- `rotation_distance = 22.074550` vs the CW2 nominal **22.6789** → **+2.74 % extrusion** (smaller
  rotation_distance = more steps/mm).
- Orca profile `filament_flow_ratio = 0.9883` → **−1.17 %**.
Net ≈ **+1.55 %** vs nominal. This is *not* big enough to cause the top-surface texture (1.2 % of a
0.6 mm line = 7 µm) — do not chase it for this symptom. But two stacked fudge factors can disagree
after the next calibration. Collapse to one: 100 mm extrusion test → set the profile back to 1.000.

### F6 — Pressure advance is speed-independent
`pressure_advance = 0.0462` is a single value, while the profile prints outer walls at **150 mm/s**
and inner walls at **300 mm/s** (with `default_acceleration 10000`, outer wall 5000, top surface
200 mm/s). PA is a flow-rate function: a value tuned at one speed bulges one wall and starves the
other. Re-run Orca's PA test at the inner-wall speed and decide knowingly.

### F7 — Cosmetic: aligned seam
`seam_position = aligned` stacks every seam on one corner (the dotted vertical line of zits on photo
4's corner). `nearest`/`back` + `staggered_inner_seams = 1` hides it. No functional effect.

### F8 — Accel exceeds the shaper's budget on Y (only matters if this cube is a dimensional gauge)
Verified with the tuning script against this machine's own shaper data:

```
axis 1  mzv 76.8 Hz damp 0.047 scv 7 -> suggested max_accel <= 17,226 mm/s^2
axis 2  mzv 63.2 Hz damp 0.035 scv 7 -> suggested max_accel <= 11,653 mm/s^2
at max_accel 20000: smoothing X 0.139 mm / Y 0.206 mm   (Klipper budget 0.12)
```
`[printer] max_accel = 20000` is thus above Y's quality ceiling by 72 % → **corners round ~0.2 mm
rather than ringing**. If the cube is being used to judge dimensions, run 12,000 mm/s² (inside
budget); the print will be ~1–2 min slower.

## 3. What to change, in order (Orca profile / filament profile)

```
# Filament (ASA) — dry the spool FIRST: 4–6 h @ 75 °C
filament_flow_ratio        0.9883 -> 1.000   (after a 100 mm extrusion check)
retraction_length          0.8    -> 1.0     (only if wisps survive drying)
# Process
top_shell_thickness        0.6    -> 1.0   (or 0, so top_shell_layers = 4–5 governs)
top_shell_layers           4      -> 5
sparse_infill_density      10%    -> 15%
top_surface_speed          200    -> 150
elephant_foot_compensation 0/off  -> 0.15  (only if calipers show a flare)
brim_type                  outer_and_inner -> outer_only
brim_object_gap            0.1    -> 0.25
seam_position              aligned -> nearest   (+ staggered_inner_seams = 1)
# Printer (only for dimensional work)
[printer] max_accel        20000  -> 12000
```

**No `printer.cfg` change is required for the surface issues** — nothing in the machine config
explains them. The `[extruder]/[printer]/[input_shaper]` values are all sane for this machine.

## 4. Decision set

- **A (recommended): dry the spool + the top-shell/infill + brim block above, reprint the same cube.**
  One cluster of variables, 41 min, addresses F1–F4 together. If the surface comes back matte-smooth,
  moisture was the main driver; if only the ripples go, F1 was.
- **B: settings only, no drying** — isolates the slicer variables from moisture, but you will have
  two causes tangled if the result is ambiguous.
- **C: full calibration ladder before the next functional ASA part** — extrusion (e-steps +
  flow 1.000) → PA at 300 mm/s → first layer/Z → then reprint. ~1.5 h of test prints; do it once,
  before anything where dimensions or finish matter.

## 5. Open questions I could not settle from here

1. **Plate type** — textured PEI or smooth? It decides whether photos 5–6 are "expected imprint"
   (then F1 is only the pillowing half) or "nozzle 0.2 mm too low".
2. **Which face was on the plate** — I read it as the bore face (flange in-plane + inner brim ring
   inside the bore). If instead the X/logo face was down, the flank orientation changes but the fix
   list above does not.
3. **Spool history** — how long has this ASA been open, and has it been dried since? That is F2's
   whole evidence chain.
4. **The 4 `klippy_shutdown` jobs** before this one (nozzle-scrubber ×3, BC-250 ×1): this log has
   rotated past them, so their reason is not in hand. If any were crashes rather than cancels, they
   are worth a separate look — nothing in the cube's own session points that way.

## 6. One machine note worth watching (unrelated to surface finish)

The mainboard CAN node reports **`bytes_invalid = 4461`** (framing corruption on the wire) while the
toolhead reports 32 and the scanner 0. `bytes_retransmit` is 338 and `rto` holds at 0.025 s, so there
is no present failure — but if a future print dies with `Lost communication with MCU`, start the
investigation here rather than at the config.

---

## 7. Update — after the user's answers (2026-10-14)

**Plate = textured PEI.** That settles §2/F1's first half and *strikes* one of my readings: the
uniform, isotropic stipple across the face in photos 5–6 **is the plate's imprint on the plate-facing
(first) layer — expected, not a defect.** Consequence: photos 5–6 are the *bottom* of the print, so
the "rough top surface" I described was mis-attributed. The walls (photos 1–4) came out glossy with
clean layer lines. **The pillowing hypothesis is therefore unverified by these photos** — it stays on
the list as a file-side risk (`top_shell_thickness 0.6` over 10 % gyroid at a 0.6-wide line) to be
checked on the next print with a straightedge, not as a confirmed defect.

**Spool = several weeks old (ASA).** ASA is hygroscopic, so moisture becomes the leading hypothesis
for the two remaining surface symptoms — the wisps (photo 4 pocket, photo 6 bore mouth) and the dull
finish. Measurable test rather than an opinion: **weigh the spool, dry 4–6 h @ 75 °C, weigh again** —
more than ~2–3 g lost means it was carrying water. Caveat that argues for *mild* moisture: the walls
came out glossy, and heavy moisture usually dulls every face. **Dry before touching retraction** —
drying removes the cause, retraction only hides it.

**The crash fix is real, and verified from the machine** (not taken on faith):

```
printer state          ready · 0 shutdowns · 0 restarts/reconnects in this session
Toolhead board         [mcu ebbcan] loads UUID 336abf1555f3  (matches the config)
Toolhead firmware      v0.13.0-762-g9871eeef  == klippy's own Git version  OK
Cube print             ran to EOF (position 1354813 = full file)
```

Two corrections to §6 and one leftover from the repair:

1. **`bytes_invalid` withdrawn as an action item.** Sampled twice 60 s apart: **4,536 → 4,536, +0 while
   idle.** It is cumulative since that MCU's boot and equals 0.005 % of the 89 MB read — history from
   the crash era, not an active fault. Keep it only as a bookmark if a print ever dies with
   `Lost communication`; do not chase it now.
2. **Leftover: the mainboard is still on an old build.** `mcu` reports **v0.13.0-464-g48f0b3ca** while
   klippy and the toolhead are on **v0.13.0-762-g9871eeef** — ~300 commits behind. Free fix, and now
   is the moment to do it: reflash the M8P so all nodes share one build. Sequence it after any can0
   work, because flashing the bridge MCU needs an interface that stays up. (The Cartographer v4 6.2.0
   is its own firmware lineage — leave it alone.)
3. The new board's UUID is what proves the swap; the section name `[mcu ebbcan]` is legacy and says
   nothing about which board is installed.

**Unchanged by these answers** — still worth doing on the reprint: `brim_type = outer_only` +
`brim_object_gap = 0.25` (removes both the fused brim and the brim ring inside the bore);
`top_shell_thickness` → 1.0 or 0 so `top_shell_layers` governs; `sparse_infill_density` 15 %;
`seam_position = nearest`. And calipers on the bottom 2 mm decide `elephant_foot_compensation`
(30.0 mm = leave it off; 30.2–30.5 mm = enable 0.15).
