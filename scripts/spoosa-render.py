#!/usr/bin/env python3
"""Software-render SPOOSA parts to PNG.

This box has numpy + trimesh but no matplotlib, PIL, pyrender or VTK, and no offscreen GL. A painter's
-algorithm plot (mplot3d) would also draw the through-holes wrongly, and the holes are the whole point
of these parts. So: a small z-buffered rasteriser, flat-shaded, writing PNG directly (zlib + struct).

Usage is via the functions below; see main() for the three delivered views.
"""
import struct
import sys
import zlib

import numpy as np
import trimesh

BG = (13, 16, 21)
PLATE = (176, 186, 198)
CUT = (232, 148, 64)
COUPON = (170, 196, 214)
EDGE = (46, 54, 66)


def png_write(path, img):
    """Write an HxWx3 uint8 array as a PNG (filter 0, no palette)."""
    h, w, _ = img.shape
    raw = b"".join(b"\x00" + img[y].tobytes() for y in range(h))

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 6))
           + chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(png)


def view_matrix(azim, elev):
    a, e = np.radians(azim), np.radians(elev)
    rz = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
    rx = np.array([[1, 0, 0], [0, np.cos(e), -np.sin(e)], [0, np.sin(e), np.cos(e)]])
    return rx @ rz


def render(parts, out, w=1500, h=1050, azim=38, elev=26, pad=0.07, bg=BG,
           ground=True, two_sided=True):
    """parts: list of (mesh, (r,g,b)[, depth_bias]). Orthographic view into one PNG.

    depth_bias nudges a part toward the camera. It exists because a section's cap faces are exactly
    coplanar with the cut edges of the solid they came from, so without a bias the z-buffer tie is
    resolved arbitrarily and the caps vanish (measured: 1 orange pixel instead of ~12k).
    """
    tris, cols, biases = [], [], []
    for entry in parts:
        mesh, col = entry[0], entry[1]
        bias = entry[2] if len(entry) > 2 else 0.0
        v = mesh.vertices[mesh.faces]
        tris.append(v)
        nf = len(mesh.faces)
        arr = np.asarray(col, dtype=float)
        if arr.ndim == 1:                       # single colour for the whole part
            cols.append(np.tile(arr, (nf, 1)))
        else:                                   # per-face colours, already (nf, 3)
            cols.append(arr)
        if bias:
            biases.append(np.full(nf, float(bias)))
        else:
            biases.append(np.zeros(nf))
    T = np.concatenate(tris)
    C = np.concatenate(cols)
    B = np.concatenate(biases)

    # drop degenerate / non-finite triangles first -- otherwise the normal computation produces
    # NaN and the shading silently loses faces (it warned rather than failed, which is worse)
    ok = np.isfinite(T).all(axis=(1, 2))
    T, C, B = T[ok], C[ok], B[ok]
    keep = (np.linalg.norm(np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]), axis=1) > 1e-9)
    T, C, B = T[keep], C[keep], B[keep]

    R = view_matrix(azim, elev)
    V = T @ R.T

    # face normals in view space -> flat shading
    n = np.cross(V[:, 1] - V[:, 0], V[:, 2] - V[:, 0])
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    n = n / np.maximum(ln, 1e-12)

    # camera looks along -Z: keep the largest z. Flip to make y up on screen.
    L = np.array([-0.35, 0.55, 0.76])
    L = L / np.linalg.norm(L)
    # two_sided makes every surface lit, which is right for a closed part seen from outside. On a
    # section it makes concave bore walls read as convex bosses, so sections use one-sided lighting
    # and let the walls that face away go dark -- a recess then looks like a recess.
    lam = np.abs(n @ L) if two_sided else np.clip(n @ L, 0, None)
    amb = 0.34
    shade = np.clip(amb + (1 - amb) * lam, 0, 1)[:, None]
    rgb = np.clip(C * shade, 0, 255)

    xs, ys, zs = V[:, :, 0], -V[:, :, 1], V[:, :, 2] + B[:, None]

    # fit to frame
    x0, x1 = xs.min(), xs.max()
    y0, y1 = ys.min(), ys.max()
    span = max(x1 - x0, (y1 - y0) * w / h) * (1 + 2 * pad)
    scale = min(w, h) / span * (min(w, h) / max(w, h)) if False else (w / span)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    sx = (xs - cx) * scale + w / 2
    sy = (ys - cy) * scale + h / 2

    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, :] = bg
    zbuf = np.full((h, w), -1e18, dtype=np.float64)

    # optional contact shadow: a soft dark ellipse under the part
    if ground:
        gy = sy.max() + 6
        if gy < h - 2:
            yy = np.arange(h)[:, None]
            fall = np.clip(1 - (yy - gy) / (0.06 * h), 0, 1)
            img = np.clip(img.astype(float) * (1 - 0.35 * fall)[:, :, None], 0, 255).astype(np.uint8)

    order = np.argsort(zs.mean(axis=1))         # cheap early-out; z-buffer decides truth
    for i in order:
        tx, ty, tz = sx[i], sy[i], zs[i]
        minx, maxx = int(np.floor(tx.min())), int(np.ceil(tx.max()))
        miny, maxy = int(np.floor(ty.min())), int(np.ceil(ty.max()))
        minx, maxx = max(minx, 0), min(maxx, w - 1)
        miny, maxy = max(miny, 0), min(maxy, h - 1)
        if minx > maxx or miny > maxy:
            continue
        px = np.arange(minx, maxx + 1) + 0.5
        py = np.arange(miny, maxy + 1) + 0.5
        gx, gy = np.meshgrid(px, py)

        ax, ay = tx[0], ty[0]
        bx, by = tx[1], ty[1]
        cx2, cy2 = tx[2], ty[2]
        area = (bx - ax) * (cy2 - ay) - (cx2 - ax) * (by - ay)
        if abs(area) < 1e-9:
            continue
        w0 = ((bx - gx) * (cy2 - gy) - (cx2 - gx) * (by - gy)) / area
        w1 = ((cx2 - gx) * (ay - gy) - (ax - gx) * (cy2 - gy)) / area
        w2 = 1.0 - w0 - w1
        eps = -1e-6 if area > 0 else 1e-6
        mask = (w0 >= eps) & (w1 >= eps) & (w2 >= eps)
        if not mask.any():
            continue
        depth = w0 * tz[0] + w1 * tz[1] + w2 * tz[2]
        sub = zbuf[miny:maxy + 1, minx:maxx + 1]
        upd = mask & (depth > sub)
        if not upd.any():
            continue
        sub[upd] = depth[upd]
        img[miny:maxy + 1, minx:maxx + 1][upd] = rgb[i].astype(np.uint8)

    png_write(out, img)
    return out


def load(path):
    m = trimesh.load(path)
    m.merge_vertices()
    return m


def cross_section(mesh, axis=1, offset=0.0):
    """Cut the mesh with a plane, then colour the cut faces so the bore depth is readable.

    Returns (solid, new_faces_mask) where mask marks the faces lying on the cut plane.
    """
    cut_mesh = mesh.slice_plane(plane_origin=[0, offset, 0], plane_normal=[0, axis, 0],
                                cap=True)
    if cut_mesh is None:
        raise SystemExit("slice_plane returned nothing")
    cut_mesh.merge_vertices()
    return cut_mesh


def section_at(mesh, axis="y", offset=0.0, tol=1e-4, up=True):
    """Cut the mesh and separate the cap faces so the cut reads as a section, not a floating slab.

    For the coupon every bore axis lies in y=0, so this one plane shows the full 15 mm bore depth --
    which is the whole reason the plate is 15 mm thick.

    The camera in render() always sits on the -Y/+Z side (view_z = (0,-sin e, cos e), independent of
    azimuth), so the retained half has to be the +Y one: its cut face then points back at the camera.
    Keeping the other half drew the outer skin and hid the caps -- which is exactly what the first
    attempt did.
    """
    idx = {"x": 0, "y": 1, "z": 2}[axis]
    normal = [0.0, 0.0, 0.0]
    normal[idx] = 1.0
    origin = [0.0, 0.0, 0.0]
    origin[idx] = offset

    solid = mesh.slice_plane(plane_origin=origin, plane_normal=normal, cap=True)
    if solid is None:
        raise SystemExit("slice_plane returned nothing")
    # keep the positive-side half regardless of which side slice_plane chose
    if solid.bounds[1][idx] <= offset + tol:
        solid = mesh.slice_plane(plane_origin=origin, plane_normal=[-x for x in normal], cap=True)
        if solid is None or solid.bounds[1][idx] <= offset + tol:
            raise SystemExit("could not keep the positive-side half of the section")
    solid.merge_vertices()
    on_plane = np.abs(solid.vertices[:, idx] - offset) < tol
    face_on = on_plane[solid.faces].all(axis=1)
    if not face_on.any():
        raise SystemExit("no cap faces found — the section would not read as a section")
    # ONE mesh with per-face colours. Splitting into two meshes put the caps coplanar with the cut
    # edges of the solid they came from, so the two fought for the same pixels and the caps lost.
    colours = np.tile(np.asarray(COUPON, dtype=float), (len(solid.faces), 1))
    colours[face_on] = np.asarray(CUT, dtype=float)

    # Turn the cut face UP so the section is the topmost surface. Without this the camera sits on the
    # far side of the retained half under this file's elevation convention, and the caps render as a
    # one-pixel sliver no matter what elevation is chosen (measured at 16 and 72 degrees).
    if up:
        rot = trimesh.transformations.rotation_matrix(np.radians(-90.0), [1, 0, 0])
        solid.apply_transform(rot)
    return solid, colours


def family(entries, out, gap_mm=28.0, **kw):
    """Place several plates side by side at TRUE relative scale, so the size range is honest."""
    placed, x = [], 0.0
    for path, col in entries:
        m = load(path)
        m.apply_translation([0, 0, -m.bounds[0][2]])      # sit on z=0
        w = m.bounds[1][0] - m.bounds[0][0]
        m.apply_translation([x + w / 2.0, 0, 0])
        placed.append((m, col))
        x += w + gap_mm
    return render(placed, out, **kw)


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    OUT = "drafts/renders"
    import os
    os.makedirs(OUT, exist_ok=True)

    if which in ("coupon", "all"):
        c = load("cad/spoosa/spoosa_coupon_8p1_8p2_8p3_8p4_8p5.stl")
        render([(c, COUPON)], f"{OUT}/coupon-iso.png", w=1500, h=820, azim=34, elev=32)
        solid, colours = section_at(c, "y", 0.0)
        # elev is measured FROM VERTICAL, not from the horizon: view_z = (0,-sin e, cos e). A low elev
        # is a near top-down view, which puts the cut plane edge-on and renders it invisible (it
        # covered ~1 pixel at elev=16). A section needs the camera nearly horizontal: elev ~72.
        render([(solid, colours)], f"{OUT}/coupon-section.png", w=1500, h=760, azim=22, elev=30, two_sided=False)
        print("coupon: iso + section")

    if which in ("hero", "all"):
        p = load("cad/spoosa/spoosa_200x200_8x1q4-20.stl")
        render([(p, PLATE)], f"{OUT}/plate-200x200-8-iso.png", w=1400, h=1050, azim=36, elev=30)
        print("hero: iso")

    if which in ("rim", "all"):
        p = load("cad/spoosa/spoosa_200x200_8x1q4-20.stl")
        # camera always sits above (+z), so flip the part to look at the MONITOR face where the rim is
        flip = p.copy()
        flip.apply_transform(trimesh.transformations.rotation_matrix(np.pi, [1, 0, 0]))
        render([(flip, PLATE)], f"{OUT}/plate-monitor-face-rim.png", w=1400, h=1050,
               azim=30, elev=64)
        # corner detail: one insert bore, its depth, and the rim edge together
        box = trimesh.creation.box(extents=[54, 54, 26]).apply_translation([119.6, 119.6, 9.0])
        detail = p.intersection(box, engine="manifold")
        render([(detail, PLATE)], f"{OUT}/bore-detail.png", w=1200, h=900, azim=42, elev=34)
        print("rim: monitor face + bore detail")

    if which in ("new", "all"):
        for fn, oz, el, out in [
            ("spoosa_100x100_8x1q4-20_win36_c2_e8.stl", 30, 34, "new-spacer-window.png"),
            ("spoosa_100x100_8x1q4-20_d75-100_c2_e8.stl", 34, 32, "new-adapter-75-100.png"),
        ]:
            path = f"cad/spoosa/{fn}"
            if os.path.exists(path):
                m = load(path)
                render([(m, PLATE)], f"{OUT}/{out}", w=1300, h=1000, azim=oz, elev=el)
                # plan view: the only way to read an outline with ears
                render([(m, PLATE)], f"{OUT}/{out.replace('.png', '-plan.png')}", w=1200, h=1000,
                       azim=0, elev=4)
                print(f"new: {out} + plan")

    if which in ("tray", "portable", "new", "all"):
        import glob
        for tp in sorted(glob.glob("cad/spoosa/spoosa_tray_*.stl")):
            tag = tp.split("spoosa_tray_")[-1].replace(".stl", "")
            m = load(tp)
            render([(m, PLATE)], f"{OUT}/tray-{tag}-iso.png", w=1500, h=1000, azim=34, elev=40)
            render([(m, PLATE)], f"{OUT}/tray-{tag}-plan.png", w=1300, h=950, azim=0, elev=4)
            print(f"tray {tag}: iso + plan")

    if which in ("portable", "new", "all"):
        import glob
        for pp in sorted(glob.glob("cad/spoosa/spoosa_portable_*.stl")):
            tag = pp.split("spoosa_portable_")[-1].replace(".stl", "")
            m = load(pp)
            render([(m, PLATE)], f"{OUT}/portable-{tag}-iso.png", w=1500, h=1000, azim=34, elev=38)
            render([(m, PLATE)], f"{OUT}/portable-{tag}-plan.png", w=1300, h=1000, azim=0, elev=4)
            print(f"portable {tag}: iso + plan")

    if which in ("family", "all"):
        family([
            ("cad/spoosa/spoosa_75x75_8x1q4-20.stl", PLATE),
            ("cad/spoosa/spoosa_100x100_8x1q4-20.stl", PLATE),
            ("cad/spoosa/spoosa_200x200_8x1q4-20.stl", PLATE),
        ], f"{OUT}/family.png", w=1600, h=760, azim=30, elev=22)
        print("family: 3 sizes")


if __name__ == "__main__":
    main()
