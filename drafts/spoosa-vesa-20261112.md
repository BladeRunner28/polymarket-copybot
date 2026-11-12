# SPOOSA reverse-engineered — parametric VESA spacer/adapter with 1/4″-20 heatset points

**Date:** 2026-11-12 · **Source:** https://www.naaackers.com/nackhabitat/articles/new-vesa-mounting-prototypes
· **Generator:** `scripts/spoosa-generator.py` · **Parts:** `cad/spoosa/` (40 STL + `manifest.json`)

## What the SPOOSA is, per the product page

> "a spacer + adapter combo that goes in between your VESA mount and monitor, giving you x1, x2, x4 or
> x8 1/4″-20 threaded holes for mounting additional hardware."

Flagship use: hanging a portable monitor (16–21″ UPERFECT, 7″ AndyCine/Shinobi field monitors, Corsair
Xeneon Edge) off the main display on a 1/4″ arm. Author is developing **8–10 size/shape variations**,
each to fit different VESA arms and monitor sizes. Closed beta, Q2 2026 ETA. Related products ship
alongside: **Veptor / Veptor Edge** — 1/4″ VESA adapters for portable monitors, in **2- and 4-screw
versions for 75 mm and 100 mm VESA**.

That "2-screw and 4-screw for 75/100" detail is why this generator models **2-screw patterns as
first-class VESA profiles** rather than assuming a rectangle.

## The design, and the one thing that decides whether it works

**Assembly order:** VESA screw → arm plate → *this spacer* → monitor's threaded insert.

Two consequences most people get wrong:

1. **The screw head bears on the ARM, not on this part.** So the VESA holes here are plain clearance
   bores (Ø4.4 for M4, Ø6.6 for M6), not countersinks. Adding a countersink would weaken the bore and
   do nothing.
2. **Stock VESA screws become too short by exactly the plate thickness.** At `plate_t = 9 mm` you need
   **M4 × (stock + 9 mm)** — most monitors ship 12–16 mm screws, so **25 mm** is the practical buy.
   The manifest records `screw_shortfall_mm` per part for this reason. A spacer that fits perfectly
   and cannot be bolted up is a failed part.

**Face convention:** `z = 0` is the monitor face (flat, presses on the monitor back); `z = plate_t` is
the arm face, where the 1/4″-20 insert bores open. Accessories bolt on from the arm side, so the
monitor face stays flat and nothing is trapped.

## The 1/4″-20 heatset requirement

The operator asked for heatset inserts rather than moulded threads. The bores are therefore sized for
a brass insert, **not** for a 1/4″-20 tap:

| preset | insert OD | length | pilot bore | plate_t needed |
|---|---|---|---|---|
| `1/4-20 short` ← **default** | 9.5 mm | 6.35 mm | **Ø9.1** | ≥ 8.4 mm |
| `1/4-20 standard` | 9.5 mm | 9.53 mm | Ø9.1 | ≥ 11.5 mm |
| `1/4-20 long` | 11.1 mm | 12.7 mm | Ø10.7 | ≥ 14.7 mm |

**These are defaults, not measurements.** A heatset bore 0.2 mm oversize spins under torque; 0.2 mm
undersize splits an ASA boss as the insert goes in. Measure your actual inserts before printing — the
generator refuses to build a part whose plate is thinner than the insert plus 2 mm of backing.

Boss OD is `insert OD + 2 × 3 mm wall` = **Ø15.5** for the default. The generator **refuses** any
layout that leaves less than 2 mm between an insert bore and a VESA screw hole; the tightest part in
the whole set measures **12.5 mm**, so nothing is close to that limit.

## Coverage — every common VESA profile

Generated ×4 insert counts (1/2/4/8) = **40 parts**, all **watertight single-body solids**:

| VESA profile | screws | plate (mm) | mass @ 4× |
|---|---|---|---|
| 75×75 | 4 × M4 | 135 × 135 × 9 | 88 g |
| 100×100 | 4 × M4 | 160 × 160 × 9 | 118 g |
| 100×200 | 4 × M4 | 160 × 260 × 9 | 181 g |
| 200×100 | 4 × M4 | 260 × 160 × 9 | 181 g |
| 200×200 | 4 × M4 | 260 × 260 × 9 | 277 g |
| 400×200 | 4 × M6 | 460 × 260 × 9 | 469 g |
| 400×400 | 4 × M6 | 460 × 460 × 9 | 790 g ⚠ |
| 600×400 | 4 × M6 | 660 × 460 × 9 | 1110 g ⚠ |
| 75, 2-screw | 2 × M4 | 135 × 135 × 9 | 88 g |
| 100, 2-screw | 2 × M4 | 160 × 160 × 9 | 118 g |

M4 clearance for MIS-D/E; Ø6.6 for MIS-F class (200×200 and up). Full per-count numbers in
`cad/spoosa/manifest.json`.

**Weight relief is on by default for the numbers above** and it is not cosmetic: pocketing the monitor
face between the VESA pads and the insert ring takes 100×100 4× from **227 cm³ / 243 g to 110 cm³ /
117 g** — a 52 % saving, leaving a 3 mm web.

At the **41 g/h** throughput implied by the operator's own last completed job (519.5 g over 12.7 h), a
117 g plate is roughly **2.9 h** of printer time.

## Honest limitations

- **The big patterns are geometrically valid and practically silly.** 400×400 at 790 g and 600×400 at
  1110 g are not parts anyone should print for a monitor-mounted accessory. Those VESA sizes belong to
  TVs, which do not need an offset spacer — if a large-format version is wanted, the right design is a
  thin plate plus standoff washers, not a 9 mm slab. I generated them because "all VESA profiles" was
  the ask; I am not recommending them.
- **No strength analysis and no physical test.** The Spoosa has a published strength-test video. This
  is a geometric reconstruction — it has not been loaded, dropped, or hung off a 1/4″ arm.
- **Insert dimensions are unmeasured defaults** (see table above).
- **No ribs or shelling beyond the flat relief pocket.** A real product would likely be a two-part
  spacer + plate or a ribbed moulding; that is the v2 conversation.
- **The plate margin (30 mm) is a guess** chosen to seat bosses outside the VESA pattern. A tighter
  margin reduces mass and may still clear the arm plate — but that needs the arm's footprint, which I
  do not have.

## Regenerating / changing it

```bash
.venv-cad/bin/python scripts/spoosa-generator.py --all-insert-counts \
    --insert-preset "1/4-20 short" --plate-t 9.0 --relief
# one part only:
.venv-cad/bin/python scripts/spoosa-generator.py --profile 100x100 --inserts 8 --plate-t 12 \
    --insert-preset "1/4-20 long" --margin 24 --relief
```

Every parameter is a flag: `--plate-t`, `--margin`, `--corner-r`, `--wall`, `--relief`,
`--insert-preset`, `--inserts`. Add a VESA size by appending one line to `VESA_PROFILES`.

## Open questions before this gets printed

1. **Which arm(s) and which monitor(s)** are you actually mounting? The margin and insert layout should
   follow the arm's real footprint, not my 30 mm guess.
2. **Measure your heatset inserts** (OD + length) — the whole geometry hangs off those two numbers.
3. **What are the inserts for** — a 1/4″ ball-head arm, a magic-arm, or direct bolt-on accessories?
   That decides whether the 1×/2×/4×/8× points should sit on the edge, the corners, or the centre.
4. **Do you want the 2-part version** (thin plate + separate standoff ring) so the same plate works at
   several spacer heights? That is the version that would actually be worth tooling.
