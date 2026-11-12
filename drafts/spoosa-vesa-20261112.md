# SPOOSA reverse-engineered — GENERIC VESA spacer/adapter, 1/4″-20 heatset points

**Updated 2026-11-12** · Source: https://www.naaackers.com/nackhabitat/articles/new-vesa-mounting-prototypes
· Mesh generator: `scripts/spoosa-generator.py` (trimesh + manifold3d) · STEP build:
`scripts/spoosa-step.py` (CadQuery/OpenCascade) · Parts: `cad/spoosa/`

## What the SPOOSA is, per the product page

> "a spacer + adapter combo that goes in between your VESA mount and monitor, giving you x1, x2, x4 or
> x8 1/4″-20 threaded holes for mounting additional hardware."

Flagship use: hanging a portable monitor (16–21″ UPERFECT, 7″ AndyCine/Shinobi, Corsair Xeneon Edge)
off the main display on a 1/4″ arm. The author is building **8–10 size/shape variations**. The related
**Veptor** line ships 2- and 4-screw versions for 75 mm and 100 mm VESA — which is why **2-screw
patterns are first-class** here rather than a special case.

## It is generic now — any VESA, within the bed

The first pass hardcoded 10 profiles. That was the wrong shape of answer, and it had a concrete flaw:
**12 of its 40 parts could not be printed on this machine at all.** A 400×400 pattern needs a 460 mm
plate, 600×400 needs 660 mm — the Trident's bed is 350 mm. Geometry that cannot be manufactured is not
a deliverable. So the interface is arbitrary:

```bash
.venv-cad/bin/python scripts/spoosa-generator.py --vesa 200x150 --inserts 4 --relief
.venv-cad/bin/python scripts/spoosa-generator.py --vesa 130x130 --insert-grid 3x3 --relief
.venv-cad/bin/python scripts/spoosa-generator.py --vesa 110x110 --screws 2 --inserts 2 --relief
.venv-cad/bin/python scripts/spoosa-generator.py --all-insert-counts --relief   # every named pattern that fits
```

| flag | meaning |
|---|---|
| `--vesa WxH` | **any** pattern, e.g. `200x150`, `130x130`. Supersedes `--profile`. |
| `--screws 2\|4` | 4 = rectangular pattern, 2 = horizontal pair (portable monitors) |
| `--screw-d` | VESA clearance; auto **4.4 (M4)**, or **6.6 (M6)** for patterns ≥ 300 mm |
| `--inserts 1\|2\|4\|8` | the Spoosa's four variants |
| `--insert-grid RxC` | **any** matrix, e.g. `2x3`. Overrides `--inserts`. |
| `--bed WxD` | build volume, default **350x350**; larger plates are **refused, not emitted** |
| `--plate-t`, `--margin`, `--wall`, `--corner-r`, `--insert-preset`, `--relief` | geometry knobs |

### "Within reason" is now a measured boundary

Default 30 mm margin on a 350 mm bed:

| margin | largest square VESA that fits |
|---|---|
| 30 mm | **290 mm** |
| 25 mm | 300 mm |
| 20 mm | 310 mm |
| 15 mm | 320 mm |

The hard floor is the insert boss: Ø15.5 means the plate must exceed the pattern by **19.5 mm**
minimum, so below ~15 mm the margin starts fighting the boss. **Anything over ~290 mm needs a
segmented plate — a different design, which I have not built.** Today's run: **28 generated, 12 refused.**

## The design, and the two things that decide whether it works

**Assembly order:** VESA screw → arm plate → *this spacer* → monitor's threaded insert.

1. **The screw head bears on the ARM, not on this part.** So VESA holes are plain clearance bores, not
   countersinks — countersinking here would weaken the bore and do nothing.
2. **Stock VESA screws become short by exactly the plate thickness.** At `plate_t = 9 mm` you need
   **M4 × (stock + 9)**; most monitors ship 12–16 mm, so **≈25 mm**. Recorded per part as
   `screw_shortfall_mm`. A spacer that fits perfectly and cannot be bolted up is a failed part.

**Faces:** `z = 0` is the monitor face (flat, presses on the monitor back); `z = plate_t` is the arm
face, where the insert bores open — so accessories bolt on from the arm side and the monitor face
stays flat, nothing trapped.

## The 1/4″-20 heatset requirement — now MEASURED, not assumed

The operator supplied the actual hardware (2026-11-12): **RUTHEX 1/4-20 × 12.7**
(amazon.com/dp/B09MTS6ZZQ). It is a **tapered knurled** insert:

| dimension | value |
|---|---|
| across the **top** | **8.7 mm** |
| across the **bottom** | **7.9 mm** |
| overall height | **12.7 mm** |

That taper is the whole design problem. A straight bore has to satisfy two constraints at once:

- **clear the small end** → bore > 7.9 mm, or the insert will not enter;
- **stay under the large end** → bore < 8.7 mm, or the knurl has nothing to melt into and the insert
  spins under torque.

So the defensible band is **8.0–8.5 mm**, and the preset default is **Ø8.3**. **RUTHEX publishes no
drill table** — their own review page contains a customer asking for one — so 8.3 is reasoned, not
authoritative. That is exactly why the generator now ships a **fit-test coupon**:

```bash
.venv-cad/bin/python scripts/spoosa-generator.py --coupon 8.1,8.2,8.3,8.4,8.5 --plate-t 15
```

One small block, one bore per diameter, ~15 minutes of printing. Press an insert into each; the correct
one goes in with firm pressure and will not spin once cool. **Book the winner, then build the real
parts with `--insert-preset` matching it** — a bore 0.2 mm out is the difference between a fitting and a
spinning joint, and ASA lot-to-lot differences are larger than that.

Boss OD = top OD + 2 × 3 mm wall = **Ø14.7**.

### What a 12.7 mm insert does to the plate

This is the consequence worth stating plainly: **the plate thickness floor moves from 8.4 mm to 14.7 mm**
(12.7 mm of insert + 2 mm of backing). The default `--plate-t` is therefore **15.0**, and the generator
refuses anything thinner.

| part | 9 mm plate (old, 6.35 insert) | **15 mm plate (measured 12.7 insert)** |
|---|---|---|
| 100×100 × 4 | 110 cm³ / 117 g | **141 cm³ / 151 g** |

A 15 mm spacer is still a defensible product — it *is* a spacer, and the standoff is the function — but
it is **+28 % material** versus the earlier guess, and that is the honest cost of the real insert.
If that mass matters, the right move is the two-part design (thin plate + separate boss ring), not a
thinner plate with a protruding insert.

## Printable set (350 mm bed, **15 mm plate**, measured insert, relief on)

| VESA | plate (mm) | @4× | ≈ print time @41 g/h |
|---|---|---|---|
| 75×75 / 75 2-screw | 135 × 135 × 15 | 108 cm³ / **116 g** | 2.8 h |
| 100×100 / 100 2-screw | 160 × 160 × 15 | 141 cm³ / **151 g** | 3.7 h |
| 100×200 | 160 × 260 × 15 | 212 cm³ / **227 g** | 5.5 h |
| 200×100 | 260 × 160 × 15 | 212 cm³ / **227 g** | 5.5 h |
| 200×200 | 260 × 260 × 15 | 312 cm³ / **334 g** | 8.1 h |
| 400×200 · 400×400 · 600×400 | — | **refused: exceeds the bed** | — |

All 28 (10 patterns… 7 printable patterns × 4 insert counts) were rebuilt against the measured insert;
`manifest.json` records the preset used per part. One older part (`custom110x110`, built at 9 mm with the
pre-measurement preset) is still in the index and is flagged by its `insert_preset` field rather than
silently mixed in.

**Weight relief is on by default and is not cosmetic:** at 15 mm the pocket is 12 mm deep, which is what
keeps a 160 × 160 plate at 141 cm³ instead of the ~270 cm³ a solid slab would cost.

## Two kernels agree — the geometry is checked, not asserted

`spoosa-generator.py` builds meshes on manifold3d; `spoosa-step.py` rebuilds the same part on
OpenCascade and exports **STEP** (editable, analytic faces) alongside STL. They share no code. All
**28 printable parts** were rebuilt in both and each STEP was re-imported and re-measured:

| | result |
|---|---|
| parts compared | **28 of 28** matched to the manifest |
| volume delta (trimesh vs OpenCascade) | **0.03 % – 0.81 %**, all within 1 % |
| worst case | 75×75 × 8 at 0.81 % |
| 100×100 × 4 (the reference part) | 109.8 vs 109.4 cm³ — 0.35 % |

Every part is refused unless it is a **single watertight body**; exported STLs were re-loaded from disk
and re-verified against the manifest within 1 % volume.

### A defect this exercise caught in my own generator

The generator used to **overwrite** `manifest.json` on every run rather than merging. After building
the full set and then one custom part, the "record of what was built" described **one** part while
**71 STLs** sat on disk — an index that lies, which is worse than no index. The manifest now merges by
filename, and anything on disk that is not in it is named explicitly:

```
14 STL(s) on disk are NOT in the manifest (built under older settings or not reproducible now)
   — pass --clean to remove them
```

Those 14 are the 12 TV-pattern plates that the bed check now refuses, plus two earlier custom parts.
**They are listed, not deleted**: `--clean` is opt-in and never implied.

## Honest limitations

- **No strength analysis, no physical test.** The Spoosa has a published strength video; this is a
  geometric reconstruction that has never been loaded, dropped, or hung off an arm.
- **Insert dimensions are unmeasured defaults** (table above).
- **The 30 mm margin is a guess** standing in for the arm's real footprint, and it drives the entire
  plate size — replacing it with the real footprint may shrink every part substantially.
- **No segmentation** for patterns over ~290 mm.
- **No ribs or shelling** beyond the flat relief pocket; a production part would likely be a two-part
  spacer + plate.
- Patterns ≥ 300 mm assume **M6** clearance automatically; override with `--screw-d` if the monitor
  disagrees.

## When you send the monitors

Per monitor I need: **VESA pattern** (W×H, or "2-screw, 75 mm apart"), **screw thread and stock
length**, **back clearance** around the VESA holes, and **what the 1/4″ points are for** (ball-head
arm, magic arm, direct bolt-on). Then it is one command each:

```bash
.venv-cad/bin/python scripts/spoosa-generator.py --vesa 100x100 --inserts 4 --margin 24 --relief
.venv-cad/bin/python scripts/spoosa-step.py    --profile 100x100 --inserts 4
```

## Open questions before this gets printed

1. **Which arm(s)** — the margin and insert placement should follow the arm's real footprint.
2. **Measure your heatset inserts** (OD + length); the whole geometry hangs off those two numbers.
3. **Do you want the 2-part version** (thin plate + separate standoff ring) so one plate serves several
   spacer heights? That is the version worth tooling.
