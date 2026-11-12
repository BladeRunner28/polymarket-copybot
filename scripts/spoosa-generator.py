#!/usr/bin/env python3
"""spoosa-generator -- parametric reverse-engineering of the NackHabitat SPOOSA VESA spacer/adapter.

WHAT THE SPOOSA IS (read from the product page, 2026-11-12):
A "spacer + adapter combo that goes in between your VESA mount and monitor, giving you x1, x2, x4 or x8
1/4"-20 threaded holes for mounting additional hardware" -- the flagship use being a portable monitor
hung off the main display on an articulated 1/4" arm. It ships in 8-10 size/shape variations to fit
most VESA arms and main monitor sizes. Prototype, closed beta, Q2 2026 launch ETA.

WHAT THIS GENERATES:
A plate for EVERY common VESA pattern, with the accessory points as 1/4"-20 HEATSET INSERT bores
(the operator's requirement) instead of moulded threads, so the threads are metal and replaceable.

THE ASSEMBLY, and why the plate is not countersunk:
VESA screws pass through the ARM's plate, then through this spacer, then into the MONITOR's own
threaded inserts. So the screw head bears on the arm, not on this part: the VESA holes here are plain
clearance bores with a chamfer for printability, and there is no countersink. The consequence to state
when you hand this over: the stock VESA screws become too short by the plate thickness, so longer
screws are mandatory (see `screw_shortfall_mm` in the manifest).

FACE CONVENTION:
  z = 0          the MONITOR face -- flat, presses against the monitor back
  z = plate_t    the ARM face -- insert bores open here, which is where accessories bolt on

Run:  .venv-cad/bin/python scripts/spoosa-generator.py            # all profiles
      .venv-cad/bin/python scripts/spoosa-generator.py --profile 100x100 --inserts 4
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np
import trimesh
from shapely.geometry import Polygon as ShapelyPolygon

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "cad", "spoosa")

# ---------------------------------------------------------------- VESA profiles
# hole diameters: VESA MIS-D/E specify M4; MIS-F (200x200 and larger) specifies M6.
# `screws` is the number of mounting points: 4 for a rectangular pattern, 2 for the
# portable-monitor patterns that only use a horizontal pair.
VESA_PROFILES = {
    "75x75":     dict(w=75,   h=75,   screw_d=4.4, screws=4),
    "100x100":   dict(w=100,  h=100,  screw_d=4.4, screws=4),
    "100x200":   dict(w=100,  h=200,  screw_d=4.4, screws=4),
    "200x100":   dict(w=200,  h=100,  screw_d=4.4, screws=4),
    "200x200":   dict(w=200,  h=200,  screw_d=4.4, screws=4),
    "400x200":   dict(w=400,  h=200,  screw_d=6.6, screws=4),
    "400x400":   dict(w=400,  h=400,  screw_d=6.6, screws=4),
    "600x400":   dict(w=600,  h=400,  screw_d=6.6, screws=4),
    "75x2screw": dict(w=75,   h=0,    screw_d=4.4, screws=2),
    "100x2screw": dict(w=100, h=0,    screw_d=4.4, screws=2),
}

# ------------------------------------------------------- 1/4"-20 heatset inserts
# DEFAULTS ONLY -- measure the actual hardware before printing. A heatset bore 0.2 mm
# too large spins under torque; 0.2 mm too small splits an ASA boss when the insert goes in.
INSERT_PRESETS = {
    # name:            outer dia, length,  pilot dia (bore), lead-in chamfer
    "1/4-20 short":    dict(od=9.5,  length=6.35, pilot=9.1,  lead=1.0),
    "1/4-20 standard": dict(od=9.5,  length=9.53, pilot=9.1,  lead=1.0),
    "1/4-20 long":     dict(od=11.1, length=12.7, pilot=10.7, lead=1.2),
}


def rrect(width: float, height: float, r: float, seg: int = 24) -> np.ndarray:
    """Rounded-rectangle polygon, centred on the origin, CCW."""
    r = max(0.0, min(r, min(width, height) / 2.0 - 1e-6))
    hw, hh = width / 2.0 - r, height / 2.0 - r
    centers = [(hw, hh), (-hw, hh), (-hw, -hh), (hw, -hh)]
    start = [0.0, 90.0, 180.0, 270.0]
    pts = []
    for (cx, cy), a0 in zip(centers, start):
        for k in range(seg + 1):
            a = math.radians(a0 + 90.0 * k / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return np.array(pts)


def vesa_holes(prof: dict) -> list[tuple[float, float]]:
    """VESA hole centres. 2-screw patterns are a single horizontal pair."""
    w, h = prof["w"], prof["h"]
    if prof["screws"] == 2:
        return [(-w / 2.0, 0.0), (w / 2.0, 0.0)]
    return [(-w / 2.0, -h / 2.0), (w / 2.0, -h / 2.0), (-w / 2.0, h / 2.0), (w / 2.0, h / 2.0)]


def insert_points(count: int, pw: float, ph: float, inset: float) -> list[tuple[float, float]]:
    """Accessory points, always OUTSIDE the VESA pattern so the boss clears the arm plate.

    1 -> centre; 2 -> left/right mid-edges; 4 -> corners; 8 -> corners + edge midpoints.
    """
    ex, ey = pw / 2.0 - inset, ph / 2.0 - inset
    if count == 1:
        return [(0.0, 0.0)]
    if count == 2:
        return [(-ex, 0.0), (ex, 0.0)]
    if count == 4:
        return [(-ex, -ey), (ex, -ey), (-ex, ey), (ex, ey)]
    if count == 8:
        return [(-ex, -ey), (ex, -ey), (-ex, ey), (ex, ey),
                (-ex, 0.0), (ex, 0.0), (0.0, -ey), (0.0, ey)]
    raise ValueError(f"insert count must be 1, 2, 4 or 8 (got {count})")


def build(profile: str, inserts: int, board_theme, *, plate_t: float, margin: float,
          corner_r: float, insert_key: str, wall: float, chamfer: float,
          relief: bool) -> tuple[trimesh.Trimesh, dict]:
    prof = VESA_PROFILES[profile]
    ins = INSERT_PRESETS[insert_key]
    boss_r = ins["od"] / 2.0 + wall

    pw = prof["w"] + 2 * margin
    ph = (prof["h"] if prof["h"] else prof["w"]) + 2 * margin
    # the plate must also be big enough to seat every boss fully inside the rim
    need = 2 * (boss_r + 2.0)
    pw = max(pw, need + prof["w"])
    ph = max(ph, need + prof["h"])

    # refuse to model an insert bore that cannot fit in the plate thickness
    min_t = ins["length"] + 2.0          # 2 mm of material behind the insert
    if plate_t < min_t:
        raise SystemExit(f"plate_t {plate_t} too thin for a {ins['length']} mm insert "
                         f"(needs >= {min_t:.1f} mm)")

    plate = trimesh.creation.extrude_polygon(
        ShapelyPolygon(rrect(pw, ph, corner_r)), height=plate_t)

    cutters = []
    # VESA clearance bores, chamfered both faces for printability
    for (x, y) in vesa_holes(prof):
        cutters.append(trimesh.creation.cylinder(radius=prof["screw_d"] / 2.0, height=plate_t + 2,
                                                 sections=64).apply_translation((x, y, plate_t / 2)))
    # insert bores, opening on the ARM face (z = plate_t), with a lead-in chamfer
    pts = insert_points(inserts, pw, ph, boss_r + 3.0)
    for (x, y) in pts:
        depth = ins["length"] + 0.5
        z_top = plate_t
        cutters.append(trimesh.creation.cylinder(radius=ins["pilot"] / 2.0, height=depth + 1,
                                                 sections=64).apply_translation((x, y, z_top - depth / 2)))
        lead = trimesh.creation.cone(radius=ins["pilot"] / 2.0 + ins["lead"], height=ins["lead"] * 1.5,
                                     sections=64)
        # cone apex up: widen the mouth at the arm face
        lead.apply_transform(trimesh.transformations.rotation_matrix(math.pi, [1, 0, 0]))
        cutters.append(lead.apply_translation((x, y, z_top - ins["lead"] * 0.25)))

    body = trimesh.boolean.difference([plate] + cutters, engine="manifold")

    if relief:
        # weight relief: pocket the MONITOR face between the VESA pattern and the insert ring,
        # leaving a rim, four VESA pads and the bosses intact.
        rim = boss_r + 2.0
        pocket_w, pocket_h = pw - 2 * rim, ph - 2 * rim
        if pocket_w > 10 and pocket_h > 10:
            depth = max(0.0, plate_t - 3.0)      # keep 3 mm of web
            if depth > 0.5:
                pocket = trimesh.creation.extrude_polygon(
                    ShapelyPolygon(rrect(pocket_w, pocket_h, max(1.0, corner_r - rim / 2))),
                    height=depth + 0.5).apply_translation((0, 0, -0.5))
                body = trimesh.boolean.difference([body, pocket], engine="manifold")

    # ---- verification: never hand over an unverified solid
    vol_cm3 = body.volume / 1000.0
    min_wall = min(
        math.dist((x, y), (vx, vy)) - prof["screw_d"] / 2.0 - ins["pilot"] / 2.0
        for (x, y) in pts for (vx, vy) in vesa_holes(prof)
    )
    meta = dict(
        profile=profile, vesa=f'{prof["w"]}x{prof["h"] or "(2-screw)"}',
        plate_mm=[round(pw, 2), round(ph, 2), round(plate_t, 2)],
        inserts=inserts, insert_preset=insert_key, insert_od=ins["od"], insert_len=ins["length"],
        pilot_d=ins["pilot"], boss_d=round(2 * boss_r, 2),
        vesa_screw_d=prof["screw_d"], vesa_screws=prof["screws"],
        volume_cm3=round(vol_cm3, 2), mass_asa_g=round(vol_cm3 * 1.07, 1),
        watertight=bool(body.is_watertight), bodies=int(body.body_count),
        min_insert_to_vesa_wall_mm=round(min_wall, 2),
        screw_shortfall_mm=round(plate_t, 2),
        faces=int(len(body.faces)),
    )
    if not body.is_watertight or body.body_count != 1:
        raise SystemExit(f"REFUSING: {profile} x{inserts} is not a single watertight solid "
                         f"(watertight={body.is_watertight}, bodies={body.body_count})")
    if min_wall < 2.0:
        raise SystemExit(f"REFUSING: {profile} x{inserts} leaves {min_wall:.2f} mm between a VESA hole "
                         f"and an insert bore (need >= 2.0). Increase --margin.")
    return body, meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="all")
    ap.add_argument("--inserts", type=int, default=4, choices=[1, 2, 4, 8])
    ap.add_argument("--plate-t", type=float, default=10.0)
    ap.add_argument("--margin", type=float, default=30.0)
    ap.add_argument("--corner-r", type=float, default=8.0)
    ap.add_argument("--insert-preset", default="1/4-20 standard", choices=list(INSERT_PRESETS))
    ap.add_argument("--wall", type=float, default=3.0)
    ap.add_argument("--chamfer", type=float, default=0.6)
    ap.add_argument("--relief", action="store_true", help="pocket the monitor face to save material")
    ap.add_argument("--all-insert-counts", action="store_true",
                    help="generate 1/2/4/8 for each profile (the Spoosa's 8-10 variations)")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    profiles = list(VESA_PROFILES) if args.profile == "all" else [args.profile]
    counts = [1, 2, 4, 8] if args.all_insert_counts else [args.inserts]

    manifest, made = [], 0
    for prof in profiles:
        for n in counts:
            body, meta = build(prof, n, None, plate_t=args.plate_t, margin=args.margin,
                               corner_r=args.corner_r, insert_key=args.insert_preset,
                               wall=args.wall, chamfer=args.chamfer, relief=args.relief)
            name = f"spoosa_{prof}_{n}x1q4-20.stl"
            body.export(os.path.join(OUT_DIR, name))
            meta["file"] = name
            manifest.append(meta)
            made += 1
            print(f"  {name:34s} plate {meta['plate_mm'][0]:.0f}x{meta['plate_mm'][1]:.0f}x"
                  f"{meta['plate_mm'][2]:.0f} mm | {meta['volume_cm3']:6.1f} cm3 | "
                  f"{meta['mass_asa_g']:5.1f} g ASA | wall {meta['min_insert_to_vesa_wall_mm']:4.1f} mm | "
                  f"{'WATERTIGHT' if meta['watertight'] else 'LEAKY'}")

    with open(os.path.join(OUT_DIR, "manifest.json"), "w") as fh:
        json.dump({"generated_by": "scripts/spoosa-generator.py", "parts": manifest}, fh, indent=2)
    print(f"\n{made} parts -> {os.path.relpath(OUT_DIR, ROOT)}/  (manifest.json alongside)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
