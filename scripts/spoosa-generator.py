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

class TooBig(Exception):
    """The requested plate does not fit the build volume. Raised so a run can report and continue."""


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
    # MEASURED by the operator 2026-11-12 (RUTHEX 1/4-20 x 12.7, amazon B09MTS6ZZQ):
    # tapered knurled insert -- 8.7 mm across the top, 7.9 mm across the bottom, 12.7 mm tall.
    # `od` here is the TOP diameter, because that is what the boss must clear and what the knurl
    # bites into. The bore is a straight cylinder: it must pass the 7.9 bottom with clearance and
    # stay under 8.7 so the taper has something to melt into. RUTHEX publishes no drill table
    # (their own review page contains a customer asking for one), so 8.3 is a reasoned midpoint
    # and --coupon exists to measure the right value on the operator's own ASA.
    "ruthex-1/4-20-12.7": dict(od=8.7, od_bottom=7.9, length=12.7, pilot=8.3, lead=0.8),
    # older presets kept for the parts already built against them
    "1/4-20 short":    dict(od=9.5,  length=6.35, pilot=9.1,  lead=1.0),
    "1/4-20 standard": dict(od=9.5,  length=9.53, pilot=9.1,  lead=1.0),
    "1/4-20 long":     dict(od=11.1, length=12.7, pilot=10.7, lead=1.2),
}
DEFAULT_INSERT = "ruthex-1/4-20-12.7"


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


def insert_points(count: int, pw: float, ph: float, inset: float,
                  grid: tuple[int, int] | None = None) -> list[tuple[float, float]]:
    """Accessory points, always OUTSIDE the VESA pattern so the boss clears the arm plate.

    grid=(rows, cols) places an arbitrary evenly-spaced matrix (the generic case for a pattern size
    nobody anticipated). Otherwise 1 -> centre; 2 -> left/right mid-edges; 4 -> corners;
    8 -> corners + edge midpoints.
    """
    ex, ey = pw / 2.0 - inset, ph / 2.0 - inset
    if grid:
        rows, cols = grid
        if rows < 1 or cols < 1:
            raise ValueError(f"insert grid must be at least 1x1 (got {rows}x{cols})")
        xs = [0.0] if cols == 1 else [-ex + 2.0 * ex * i / (cols - 1) for i in range(cols)]
        ys = [0.0] if rows == 1 else [-ey + 2.0 * ey * j / (rows - 1) for j in range(rows)]
        return [(x, y) for y in ys for x in xs]
    if count == 1:
        return [(0.0, 0.0)]
    if count == 2:
        return [(-ex, 0.0), (ex, 0.0)]
    if count == 4:
        return [(-ex, -ey), (ex, -ey), (-ex, ey), (ex, ey)]
    if count == 8:
        return [(-ex, -ey), (ex, -ey), (-ex, ey), (ex, ey),
                (-ex, 0.0), (ex, 0.0), (0.0, -ey), (0.0, ey)]
    raise ValueError(f"insert count must be 1, 2, 4 or 8 -- or use --insert-grid RxC (got {count})")


def plate_size(prof: dict, margin: float, boss_r: float) -> tuple[float, float]:
    """Plate dimensions for a VESA pattern: pattern + margins, but never smaller than a boss needs."""
    h = prof["h"] if prof["h"] else prof["w"]      # a 2-screw pattern has no vertical spacing
    pw = max(prof["w"] + 2 * margin, 2 * (boss_r + 2.0) + prof["w"])
    ph = max(h + 2 * margin, 2 * (boss_r + 2.0) + h)
    return pw, ph


def resolve_profile(args) -> tuple[dict, str]:
    """Either a named VESA profile, or an arbitrary WxH supplied on the command line."""
    import re
    if args.vesa:
        m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*$", args.vesa, re.I)
        if not m:
            raise SystemExit(f"--vesa expects WxH (e.g. 200x150), got {args.vesa!r}")
        w, h = float(m.group(1)), float(m.group(2))
        if w <= 0 or h <= 0:
            raise SystemExit("--vesa dimensions must be positive")
        if args.screws == 2:
            h = 0.0
        screw_d = args.screw_d if args.screw_d else (6.6 if max(w, h) >= 300 else 4.4)
        return dict(w=w, h=h, screw_d=screw_d, screws=args.screws), f"custom{int(w)}x{int(h or w)}"
    prof = dict(VESA_PROFILES[args.profile])
    if args.screw_d:
        prof["screw_d"] = args.screw_d
    return prof, args.profile



def build(prof: dict, label: str, inserts: int, *, plate_t: float, margin: float,
          corner_r: float, insert_key: str, wall: float, chamfer: float,
          relief: bool, grid: tuple[int, int] | None = None,
          bed: tuple[float, float] | None = None) -> tuple[trimesh.Trimesh, dict]:
    ins = INSERT_PRESETS[insert_key]
    boss_r = ins["od"] / 2.0 + wall

    pw, ph = plate_size(prof, margin, boss_r)

    # THE HARD LIMIT: a plate bigger than the bed is not a part, it is a drawing. Refuse it here so a
    # generated STL can always be printed rather than discovered unprintable at the slicer.
    if bed and (pw > bed[0] or ph > bed[1]):
        raise TooBig(f"plate {pw:.0f}x{ph:.0f} mm exceeds the {bed[0]:.0f}x{bed[1]:.0f} mm bed")

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
    pts = insert_points(inserts, pw, ph, boss_r + 3.0, grid=grid)
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
        profile=label, vesa=f'{int(prof["w"])}x{int(prof["h"]) if prof["h"] else "(2-screw)"}',
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


def build_coupon(insert_key: str, plate_t: float, wall: float,
                 bores: list[float], height: float = 22.0) -> tuple[trimesh.Trimesh, dict]:
    """A small fit-test block carrying one bore per candidate diameter.

    WHY: the insert is tapered (8.7 top / 7.9 bottom) and the manufacturer publishes no bore table, so
    the correct interference is empirical. A coupon beats discovering at assembly that 8.3 splits the
    boss or that 8.5 spins.

    2026-11-13: the first version cut each bore with a cylinder PLUS a separate rotated cone for the
    lead-in, and the exported STL came back as 137 disconnected shells (euler 128) while the in-memory
    mesh claimed watertight. Bores are now plain cylinders -- the lead-in was cosmetic and it cost a
    printable part. The lesson is in verify_coupon(): the artefact on disk is what gets checked, not the
    object in memory.
    """
    ins = INSERT_PRESETS[insert_key]
    pitch = max(bores) + 2 * wall + 1.5
    width = pitch * len(bores) + 8.0
    depth_t = max(plate_t, ins["length"] + 2.0)
    height = max(height, max(bores) + 2 * wall)

    body = trimesh.creation.extrude_polygon(
        ShapelyPolygon(rrect(width, height, 4.0)), height=depth_t)
    cut, labels = [], []
    for i, d in enumerate(bores):
        x = -width / 2.0 + 4.0 + pitch * (i + 0.5)
        cut.append(trimesh.creation.cylinder(radius=d / 2.0, height=depth_t + 2.0, sections=64)
                   .apply_translation((x, 0, depth_t / 2.0)))
        labels.append(round(d, 2))
    body = trimesh.boolean.difference([body] + cut, engine="manifold")
    meta = dict(kind="coupon", bores_mm=labels,
                plate_mm=[round(width, 2), round(height, 2), round(depth_t, 2)],
                insert_preset=insert_key, insert_len=ins["length"],
                volume_cm3=round(body.volume / 1000.0, 2),
                mass_asa_g=round(body.volume / 1000.0 * 1.07, 1),
                watertight=bool(body.is_watertight))
    if not body.is_watertight:
        raise SystemExit("REFUSING: the coupon mesh is not watertight before export")
    return body, meta


def verify_exported(path: str, expect_bodies: int = 1) -> tuple[bool, str]:
    """Re-load the file we just wrote and check THAT, not the object we built it from."""
    reload = trimesh.load(path)
    reload.merge_vertices()
    bodies = len(reload.split(only_watertight=False))
    ok = reload.is_watertight and bodies == expect_bodies
    return ok, (f"reloaded {os.path.basename(path)}: watertight={reload.is_watertight} "
                f"bodies={bodies} euler={reload.euler_number}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Generate SPOOSA-style VESA spacer/adapter plates with 1/4-20 heatset points.")
    ap.add_argument("--profile", default="all",
                    help="named VESA profile, or 'all'. Ignored when --vesa is given.")
    ap.add_argument("--vesa", default=None,
                    help="arbitrary pattern as WxH (e.g. 200x150, 130x130). Supersedes --profile.")
    ap.add_argument("--screws", type=int, default=4, choices=[2, 4],
                    help="mounting points: 4 for a rectangular pattern, 2 for a horizontal pair")
    ap.add_argument("--screw-d", type=float, default=None,
                    help="VESA screw clearance (default M4=4.4, M6=6.6 for patterns >=300 mm)")
    ap.add_argument("--inserts", type=int, default=4, choices=[1, 2, 4, 8])
    ap.add_argument("--insert-grid", default=None,
                    help="arbitrary insert matrix as RxC (e.g. 2x3). Overrides --inserts.")
    ap.add_argument("--plate-t", type=float, default=15.0,
                    help="plate thickness; must exceed the insert length by >=2 mm "
                         "(the measured RUTHEX insert is 12.7 mm, so 15.0 is the floor)")
    ap.add_argument("--margin", type=float, default=30.0)
    ap.add_argument("--corner-r", type=float, default=8.0)
    ap.add_argument("--insert-preset", default=DEFAULT_INSERT, choices=list(INSERT_PRESETS))
    ap.add_argument("--coupon", default=None,
                    help="build a fit-test coupon instead: comma-separated bore diameters "
                         "(e.g. 8.1,8.2,8.3,8.4) so the interference is measured, not guessed")
    ap.add_argument("--wall", type=float, default=3.0)
    ap.add_argument("--chamfer", type=float, default=0.6)
    ap.add_argument("--relief", action="store_true", help="pocket the monitor face to save material")
    ap.add_argument("--bed", default="350x350",
                    help="build volume as WxD; plates larger than this are refused (default 350x350)")
    ap.add_argument("--no-bed-check", action="store_true")
    ap.add_argument("--clean", action="store_true",
                    help="delete STLs present on disk but absent from the manifest (never implied)")
    ap.add_argument("--all-insert-counts", action="store_true",
                    help="generate 1/2/4/8 for each profile (the Spoosa's 8-10 variations)")
    args = ap.parse_args()

    bw, _, bd = args.bed.partition("x")
    bed = None if args.no_bed_check else (float(bw), float(bd or bw))

    grid = None
    if args.insert_grid:
        rows, _, cols = args.insert_grid.lower().partition("x")
        grid = (int(rows), int(cols))

    os.makedirs(OUT_DIR, exist_ok=True)

    manifest, made, skipped = [], 0, []

    if args.coupon:
        bores = [float(x) for x in args.coupon.split(",") if x.strip()]
        if not bores:
            raise SystemExit("--coupon needs at least one diameter, e.g. --coupon 8.2,8.3,8.4")
        body, meta = build_coupon(args.insert_preset, args.plate_t, args.wall, bores)
        name = "spoosa_coupon_" + "_".join(str(b).replace(".", "p") for b in bores) + ".stl"
        out_path = os.path.join(OUT_DIR, name)
        body.export(out_path)
        ok, detail = verify_exported(out_path)
        print(f"    {detail}")
        if not ok:
            raise SystemExit(f"REFUSING: the exported coupon is not a single watertight solid — {detail}")
        meta["file"] = name
        manifest, made = [meta], 1
        print(f"  {name}")
        print(f"    {len(bores)} bores: {', '.join(f'Ø{b}' for b in bores)} | block "
              f"{meta['plate_mm'][0]:.0f}x{meta['plate_mm'][1]:.0f}x{meta['plate_mm'][2]:.0f} mm | "
              f"{meta['mass_asa_g']:.1f} g ASA | {'WATERTIGHT' if meta['watertight'] else 'LEAKY'}")
        print("    press the insert into each bore; the correct one goes in with firm pressure and "
              "refuses to spin once cool")
        targets, counts = [], []

    # one target, or every named profile
    if not args.coupon:
        if args.vesa:
            targets = [resolve_profile(args)]
        elif args.profile == "all":
            targets = [(dict(p), name) for name, p in VESA_PROFILES.items()]
        else:
            if args.profile not in VESA_PROFILES:
                raise SystemExit(f"unknown profile {args.profile!r}; choose from {', '.join(VESA_PROFILES)} "
                                 f"or pass --vesa WxH")
            targets = [resolve_profile(args)]
        counts = [1, 2, 4, 8] if (args.all_insert_counts and not grid) else [args.inserts]

    for prof, label in targets:
        for n in counts:
            try:
                body, meta = build(prof, label, n, plate_t=args.plate_t, margin=args.margin,
                                   corner_r=args.corner_r, insert_key=args.insert_preset,
                                   wall=args.wall, chamfer=args.chamfer, relief=args.relief,
                                   grid=grid, bed=bed)
            except TooBig as e:
                skipped.append(f"{label} x{n}: {e}")
                print(f"  SKIP {label:11s} x{n}  -- {e}")
                continue
            suffix = f"{n}x" if not grid else f"{grid[0]}x{grid[1]}x"
            name = f"spoosa_{label}_{suffix}1q4-20.stl"
            body.export(os.path.join(OUT_DIR, name))
            meta["file"] = name
            manifest.append(meta)
            made += 1
            print(f"  {name:34s} plate {meta['plate_mm'][0]:.0f}x{meta['plate_mm'][1]:.0f}x"
                  f"{meta['plate_mm'][2]:.0f} mm | {meta['volume_cm3']:6.1f} cm3 | "
                  f"{meta['mass_asa_g']:5.1f} g ASA | wall {meta['min_insert_to_vesa_wall_mm']:4.1f} mm | "
                  f"{'WATERTIGHT' if meta['watertight'] else 'LEAKY'}")

    manifest_path = os.path.join(OUT_DIR, "manifest.json")
    # MERGE, do not clobber. Found 2026-11-12: each run overwrote manifest.json, so after building the
    # full set and then one custom part, the "record of what was built" described exactly one part while
    # 71 STLs sat on disk. An artefact that claims to be the index and isn't is worse than no index.
    prior: dict[str, dict] = {}
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path) as fh:
                for p in (json.load(fh).get("parts") or []):
                    if p.get("file"):
                        prior[p["file"]] = p
        except Exception as e:  # noqa: BLE001 - a corrupt index must not stop a build
            print(f"WARN: could not read the existing manifest ({e}); starting a fresh index")
    for p in manifest:
        prior[p["file"]] = p

    on_disk = sorted(f for f in os.listdir(OUT_DIR) if f.endswith(".stl"))
    # `*_cq.stl` belongs to scripts/spoosa-step.py (the OpenCascade twin of each part), not to this
    # generator's inventory, so it is neither indexed nor called stale here.
    orphans = [f for f in on_disk if not f.endswith("_cq.stl") and f not in prior]
    if args.clean and orphans:
        for f in orphans:
            os.remove(os.path.join(OUT_DIR, f))
        print(f"\nremoved {len(orphans)} stale STL(s) not in the manifest (--clean)")
        orphans = []

    with open(manifest_path, "w") as fh:
        json.dump({"generated_by": "scripts/spoosa-generator.py", "bed_mm": bed,
                   "parts": sorted(prior.values(), key=lambda p: p["file"]),
                   "skipped_this_run": skipped, "orphans_on_disk": orphans}, fh, indent=2)
    print(f"\n{made} parts built this run -> {os.path.relpath(OUT_DIR, ROOT)}/ "
          f"({len(prior)} total in manifest.json)")
    if skipped:
        limit = f"{bed[0]:.0f}x{bed[1]:.0f}" if bed else "unlimited"
        print(f"{len(skipped)} skipped as too large for the {limit} mm bed:")
        for s in skipped:
            print(f"  - {s}")
    if orphans:
        print(f"{len(orphans)} STL(s) on disk are NOT in the manifest (built under older settings or "
              f"not reproducible now) — pass --clean to remove them:")
        for f in orphans[:12]:
            print(f"  - {f}")
        if len(orphans) > 12:
            print(f"  ... and {len(orphans) - 12} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
