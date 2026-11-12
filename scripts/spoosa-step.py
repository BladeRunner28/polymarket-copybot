#!/usr/bin/env python3
"""spoosa-step -- the same SPOOSA plate built in CadQuery (OpenCascade), exported as STEP + STL.

WHY THIS EXISTS ALONGSIDE scripts/spoosa-generator.py:
spoosa-generator.py builds meshes with trimesh+manifold3d -- fast, dependency-light, good for
batch-exporting 40 variants and for verifying watertightness. But an STL is a triangle soup: you can
slice it, you cannot edit it. STEP is the interchange format every real CAD tool reads, with analytic
faces and proper fillets. So this builds the identical part on the OpenCascade kernel.

The two kernels agreeing on volume is also a genuine cross-check: manifold3d and OpenCascade share no
code, so matching volumes to <0.5% means the geometry is what I think it is, not an artifact of one
library's boolean.

Run:  .venv-cad/bin/python scripts/spoosa-step.py --profile 100x100 --inserts 4
"""
from __future__ import annotations

import argparse
import importlib.util
import math
import os
import sys

import cadquery as cq

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "cad", "spoosa")

# Single source of truth: read the VESA/insert tables out of the trimesh generator rather than
# duplicating them here. The module filename has a hyphen so importlib-by-path is the way in; its
# main() is __main__-guarded, so loading it only defines tables and helpers.
_spec = importlib.util.spec_from_file_location(
    "spoosa_gen", os.path.join(os.path.dirname(os.path.abspath(__file__)), "spoosa-generator.py"))
assert _spec is not None and _spec.loader is not None, "cannot locate spoosa-generator.py alongside this script"
_gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gen)
VESA_PROFILES = _gen.VESA_PROFILES
INSERT_PRESETS = _gen.INSERT_PRESETS


def build(profile: str, inserts: int, plate_t: float, margin: float, corner_r: float,
          insert_key: str, wall: float, relief: bool):
    prof = VESA_PROFILES[profile]
    ins = INSERT_PRESETS[insert_key]
    boss_r = ins["od"] / 2.0 + wall

    pw = max(prof["w"] + 2 * margin, 2 * (boss_r + 2.0) + prof["w"])
    ph = max((prof["h"] if prof["h"] else prof["w"]) + 2 * margin,
             2 * (boss_r + 2.0) + (prof["h"] if prof["h"] else prof["w"]))

    if plate_t < ins["length"] + 2.0:
        raise SystemExit(f"plate_t {plate_t} too thin for a {ins['length']} mm insert")

    # plate
    body = cq.Workplane("XY").rect(pw, ph).extrude(plate_t)
    # rounded corners via fillet on the four vertical edges
    body = body.edges("|Z").fillet(min(corner_r, min(pw, ph) / 2.0 - 0.5))

    # VESA clearance bores (through)
    if prof["screws"] == 2:
        holes = [(-prof["w"] / 2.0, 0.0), (prof["w"] / 2.0, 0.0)]
    else:
        holes = [(-prof["w"] / 2.0, -prof["h"] / 2.0), (prof["w"] / 2.0, -prof["h"] / 2.0),
                 (-prof["w"] / 2.0, prof["h"] / 2.0), (prof["w"] / 2.0, prof["h"] / 2.0)]
    body = (body.faces(">Z").workplane(origin=(0, 0, 0))
            .pushPoints(holes).hole(prof["screw_d"]))

    # insert bores from the ARM face (z = plate_t), with a countersink lead-in
    ex, ey = pw / 2.0 - (boss_r + 3.0), ph / 2.0 - (boss_r + 3.0)
    if inserts == 1:
        pts = [(0.0, 0.0)]
    elif inserts == 2:
        pts = [(-ex, 0.0), (ex, 0.0)]
    elif inserts == 4:
        pts = [(-ex, -ey), (ex, -ey), (-ex, ey), (ex, ey)]
    else:
        pts = [(-ex, -ey), (ex, -ey), (-ex, ey), (ex, ey), (-ex, 0.0), (ex, 0.0), (0.0, -ey), (0.0, ey)]

    depth = ins["length"] + 0.5
    body = (body.faces(">Z").workplane(origin=(0, 0, plate_t))
            .pushPoints(pts).cboreHole(ins["pilot"], ins["pilot"] + 2 * ins["lead"], ins["lead"]))
    body = (body.faces(">Z").workplane(origin=(0, 0, plate_t))
            .pushPoints(pts).hole(ins["pilot"], depth))

    if relief:
        rim = boss_r + 2.0
        pock_w, pock_h = pw - 2 * rim, ph - 2 * rim
        d = plate_t - 3.0
        if pock_w > 10 and pock_h > 10 and d > 0.5:
            body = (body.faces("<Z").workplane(origin=(0, 0, 0))
                    .rect(pock_w, pock_h).cutBlind(-d))
    return body, dict(plate_w=round(pw, 2), plate_h=round(ph, 2), plate_t=plate_t,
                      boss_d=round(2 * boss_r, 2),
                      insert_pilot=ins["pilot"], insert_len=ins["length"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="100x100", choices=list(VESA_PROFILES))
    ap.add_argument("--inserts", type=int, default=4, choices=[1, 2, 4, 8])
    ap.add_argument("--plate-t", type=float, default=9.0)
    ap.add_argument("--margin", type=float, default=30.0)
    ap.add_argument("--corner-r", type=float, default=8.0)
    ap.add_argument("--insert-preset", default="1/4-20 short", choices=list(INSERT_PRESETS))
    ap.add_argument("--wall", type=float, default=3.0)
    ap.add_argument("--no-relief", action="store_true")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    body, meta = build(args.profile, args.inserts, args.plate_t, args.margin, args.corner_r,
                       args.insert_preset, args.wall, not args.no_relief)

    base = f"spoosa_{args.profile}_{args.inserts}x1q4-20"
    step_path = os.path.join(OUT_DIR, base + ".step")
    stl_path = os.path.join(OUT_DIR, base + "_cq.stl")
    cq.exporters.export(body, step_path)
    cq.exporters.export(body, stl_path)

    vol_cm3 = body.val().Volume() / 1000.0
    print(f"{base}")
    print(f"  plate {meta['plate_w']:.0f} x {meta['plate_h']:.0f} x {meta['plate_t']:.0f} mm")
    print(f"  volume {vol_cm3:.1f} cm3  ->  {vol_cm3 * 1.07:.0f} g ASA")
    print(f"  insert bore Ø{meta['insert_pilot']} x {meta['insert_len']} mm, boss Ø{meta['boss_d']}")
    print(f"  STEP {os.path.relpath(step_path, ROOT)}  ({os.path.getsize(step_path) // 1024} KB)")
    print(f"  STL  {os.path.relpath(stl_path, ROOT)}  ({os.path.getsize(stl_path) // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
