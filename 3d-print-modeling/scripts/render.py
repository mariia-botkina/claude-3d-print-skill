#!/usr/bin/env python3
"""Render preview images of a model so it can be looked at before printing.

  python render.py part.stl -o part_views.png            # 4 views: iso front/back, front, top
  python render.py part.stl -o p.png --overhang 45       # paint overhangs red, ceilings orange
  python render.py part.stl -o p.png --report rep.json   # also mark problems from check_print.py
  python render.py a.stl b.stl -o set.png --layout       # several parts side by side
  python render.py part.scad -D width=40 -o p.png        # renders the .scad first

Engine: OpenSCAD preview under a virtual display (correct hidden surfaces, colours),
falling back to matplotlib if OpenSCAD/Xvfb are missing. Look at the image
yourself with the Read tool before showing it to the user.
"""
import argparse
import atexit
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from meshio_util import load_mesh, rotation_matrix_deg  # noqa: E402

BASE = np.array([0.62, 0.70, 0.80])
OVERHANG = np.array([0.90, 0.20, 0.15])
CEILING = np.array([0.98, 0.60, 0.10])
LIGHT = np.array([0.4, -0.6, 0.7]) / np.linalg.norm([0.4, -0.6, 0.7])

VIEWS = {  # matplotlib (elev, azim)
    "iso front": (25, -60),
    "iso back": (25, 120),
    "iso below": (-30, -60),
    "front": (0, -90),
    "top": (90, -90),
    "bottom": (-90, -90),
    "side": (0, 0),
}
SCAD_CAM = {  # OpenSCAD gimbal rotation rx,ry,rz
    "iso front": (55, 0, 25),
    "iso back": (55, 0, 205),
    "iso below": (125, 0, 25),
    "front": (90, 0, 0),
    "top": (0, 0, 0),
    "bottom": (180, 0, 0),
    "side": (90, 0, 90),
}

_XVFB = {"proc": None, "display": None}


def _display():
    """Return a DISPLAY for OpenSCAD, starting one Xvfb for the whole run if needed."""
    if os.environ.get("DISPLAY"):
        return os.environ["DISPLAY"]
    if _XVFB["display"]:
        return _XVFB["display"]
    if not shutil.which("Xvfb"):
        return None
    for n in range(87, 120):
        if not os.path.exists(f"/tmp/.X11-unix/X{n}") and not os.path.exists(f"/tmp/.X{n}-lock"):
            proc = subprocess.Popen(["Xvfb", f":{n}", "-screen", "0", "1280x1024x24", "-nolisten", "tcp"],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            import time
            for _ in range(50):
                if os.path.exists(f"/tmp/.X11-unix/X{n}"):
                    break
                time.sleep(0.1)
            _XVFB.update(proc=proc, display=f":{n}")
            atexit.register(proc.terminate)
            return _XVFB["display"]
    return None


def _scad_ok():
    return shutil.which("openscad") is not None and _display() is not None


def simplify(mesh, max_faces):
    if len(mesh.faces) <= max_faces:
        return mesh
    try:
        return mesh.simplify_quadric_decimation(face_count=max_faces)
    except Exception:
        idx = np.random.default_rng(0).choice(len(mesh.faces), max_faces, replace=False)
        sub = mesh.copy()
        sub.update_faces(np.sort(idx))
        return sub


def face_colors(mesh, overhang_deg, base=BASE):
    n = mesh.face_normals
    shade = 0.45 + 0.55 * np.clip(n @ LIGHT, 0, 1)
    cols = np.tile(base, (len(n), 1)) * shade[:, None]
    if overhang_deg is not None:
        zmin = mesh.bounds[0][2]
        on_bed = mesh.triangles[:, :, 2].max(axis=1) < zmin + 0.3
        limit = -math.sin(math.radians(90 - overhang_deg))
        steep = (n[:, 2] < limit) & ~on_bed
        flat = (n[:, 2] < -0.985) & ~on_bed
        cols[steep] = OVERHANG * (0.6 + 0.4 * shade[steep, None])
        cols[flat] = CEILING * (0.6 + 0.4 * shade[flat, None])
    return np.clip(cols, 0, 1)


def draw(ax, meshes_colors, elev, azim, title, markers=()):
    allv = np.vstack([m.vertices for m, _ in meshes_colors])
    lo, hi = allv.min(axis=0), allv.max(axis=0)
    for m, cols in meshes_colors:
        pc = Poly3DCollection(m.triangles, facecolors=cols, edgecolors="none", linewidths=0)
        ax.add_collection3d(pc)
    for (x, y, z, label, color) in markers:
        ax.scatter([x], [y], [z], s=60, c=color, depthshade=False, edgecolors="black", zorder=10)
        ax.text(x, y, z, " " + label, fontsize=7, color="black", zorder=11)
    c = (lo + hi) / 2
    r = (hi - lo).max() / 2 * 1.05 + 1e-6
    ax.set_xlim(c[0] - r, c[0] + r)
    ax.set_ylim(c[1] - r, c[1] + r)
    ax.set_zlim(c[2] - r, c[2] + r)
    ax.set_box_aspect((1, 1, 1))
    ax.view_init(elev=elev, azim=azim)
    ax.set_title(title, fontsize=9)
    ax.set_axis_off()


def markers_from_report(path):
    with open(path) as f:
        rep = json.load(f)
    if isinstance(rep, list):
        rep = rep[0]
    out = []
    colors = {"ERROR": "red", "WARN": "orange", "INFO": "yellow"}
    for c in rep.get("checks", []):
        d = c.get("data", {})
        col = colors.get(c["severity"], "yellow")
        for it in d.get("islands", [])[:8]:
            out.append((it["center_mm"][0], it["center_mm"][1], it["z_mm"], "island", col))
        for it in d.get("regions", [])[:6]:
            b = it.get("xy_bounds_mm")
            if b:
                z = it["z_mm"][0] if isinstance(it.get("z_mm"), list) else it.get("z_mm", 0)
                out.append(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, z, c["id"], col))
        for it in d.get("bridges", [])[:4]:
            out.append((it["center_mm"][0], it["center_mm"][1], it["z_mm"], "bridge", col))
        for p in d.get("sample_points", [])[:4]:
            out.append((p[0], p[1], p[2], c["id"], col))
    return out


def layout_side_by_side(meshes, gap=10.0):
    placed, x = [], 0.0
    for m in meshes:
        m = m.copy()
        lo, hi = m.bounds
        m.apply_translation([x - lo[0], -(lo[1] + hi[1]) / 2, -lo[2]])
        x += (hi[0] - lo[0]) + gap
        placed.append(m)
    return placed


def render(meshes, out, views=("iso front", "iso back", "front", "top"), overhang=None, markers=(),
           size=4.0, title=None, max_faces=60000, colors=None):
    per = max(2000, max_faces // max(1, len(meshes)))
    meshes = [simplify(m, per) for m in meshes]
    palette = colors or [BASE, np.array([0.85, 0.75, 0.55]), np.array([0.6, 0.8, 0.6]), np.array([0.8, 0.6, 0.8])]
    mc = [(m, face_colors(m, overhang, palette[i % len(palette)])) for i, m in enumerate(meshes)]
    cols = min(len(views), 2 if len(views) == 4 else len(views))
    rows = math.ceil(len(views) / cols)
    fig = plt.figure(figsize=(size * cols, size * rows), dpi=110)
    for i, v in enumerate(views):
        ax = fig.add_subplot(rows, cols, i + 1, projection="3d")
        elev, azim = VIEWS[v]
        draw(ax, mc, elev, azim, v, markers)
    if title or overhang is not None:
        t = title or ""
        if overhang is not None:
            t += f"   red: overhang > {overhang:.0f} deg, orange: flat ceiling"
        fig.suptitle(t.strip(), fontsize=10)
    fig.tight_layout()
    fig.savefig(out, facecolor="white")
    plt.close(fig)
    return out


def thumbnail(meshes, out, px=512, bed=256.0):
    """Plate thumbnail for a Bambu 3MF: parts in plate coordinates, iso view, bed outline."""
    fig = plt.figure(figsize=(px / 100, px / 100), dpi=100)
    ax = fig.add_subplot(111, projection="3d")
    mc = [(simplify(m, 20000), face_colors(m, None)) for m in meshes]
    for m, cols in mc:
        ax.add_collection3d(Poly3DCollection(m.triangles, facecolors=face_colors(m, None), edgecolors="none"))
    ax.plot([0, bed, bed, 0, 0], [0, 0, bed, bed, 0], [0, 0, 0, 0, 0], color="0.6", lw=0.8)
    allv = np.vstack([m.vertices for m, _ in mc] + [np.array([[0, 0, 0], [bed, bed, 0]])])
    lo, hi = allv.min(axis=0), allv.max(axis=0)
    c = (lo + hi) / 2
    r = (hi - lo).max() / 2
    ax.set_xlim(c[0] - r, c[0] + r)
    ax.set_ylim(c[1] - r, c[1] + r)
    ax.set_zlim(0, 2 * r)
    ax.set_box_aspect((1, 1, 1))
    ax.view_init(elev=35, azim=-60)
    ax.set_axis_off()
    fig.subplots_adjust(0, 0, 1, 1)
    fig.savefig(out, transparent=True)
    plt.close(fig)
    return out


def _rgb(c):
    return "[" + ",".join(f"{float(v):.3f}" for v in c) + "]"


def overlay_meshes(mesh, overhang_deg):
    """Steep-overhang and flat-ceiling faces as separate thin meshes, nudged outwards."""
    n = mesh.face_normals
    zmin = mesh.bounds[0][2]
    on_bed = mesh.triangles[:, :, 2].max(axis=1) < zmin + 0.3
    limit = -math.sin(math.radians(90 - overhang_deg))
    flat = (n[:, 2] < -0.985) & ~on_bed
    steep = (n[:, 2] < limit) & ~on_bed & ~flat
    out = []
    for mask, col in ((steep, OVERHANG), (flat, CEILING)):
        idx = np.where(mask)[0]
        if len(idx):
            sub = mesh.submesh([idx], append=True)
            sub.vertices = sub.vertices + np.array([0, 0, -0.04])
            out.append((sub, col))
    return out


def render_scad(meshes, out, views, overhang=None, markers=(), colors=None, px=520, title=None):
    work = tempfile.mkdtemp(prefix="render_")
    palette = colors or [BASE, np.array([0.85, 0.75, 0.55]), np.array([0.6, 0.8, 0.6]), np.array([0.8, 0.6, 0.8])]
    lines = []
    for i, m in enumerate(meshes):
        p = os.path.join(work, f"m{i}.stl")
        m.export(p)
        lines.append(f'color({_rgb(palette[i % len(palette)])}) import("{p}");')
        if overhang is not None:
            for j, (sub, col) in enumerate(overlay_meshes(m, overhang)):
                q = os.path.join(work, f"o{i}_{j}.stl")
                sub.export(q)
                lines.append(f'color({_rgb(col)}) import("{q}");')
    if meshes:
        diag = float(np.linalg.norm(np.vstack([m.extents for m in meshes]).max(axis=0)))
    else:
        diag = 10.0
    mcol = {"red": "[0.9,0.1,0.1]", "orange": "[1,0.55,0]", "yellow": "[0.95,0.85,0.1]"}
    for (x, y, z, label, color) in markers:
        lines.append(f"color({mcol.get(color, '[1,0,0]')}) translate([{x},{y},{z}]) sphere(r={max(0.8, diag / 60):.2f}, $fn=20);")
    scad = os.path.join(work, "scene.scad")
    with open(scad, "w") as f:
        f.write("\n".join(lines) + "\n")
    env = dict(os.environ, DISPLAY=_display())
    imgs = []
    for v in views:
        rx, ry, rz = SCAD_CAM[v]
        png = os.path.join(work, f"v_{v.replace(' ', '_')}.png")
        cmd = ["openscad", "--preview", "-o", png, f"--imgsize={px},{px}", "--viewall", "--autocenter",
               f"--camera=0,0,0,{rx},{ry},{rz},0", "--colorscheme=Tomorrow", "--projection=p", scad]
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=300)
        if r.returncode != 0 or not os.path.exists(png):
            raise RuntimeError(r.stderr[-800:])
        imgs.append((v, png))
    if len(imgs) == 1 and not title:
        shutil.copy(imgs[0][1], out)
        return out
    cols = 2 if len(imgs) == 4 else min(3, len(imgs))
    rows = math.ceil(len(imgs) / cols)
    fig = plt.figure(figsize=(4.2 * cols, 4.2 * rows + 0.4), dpi=110)
    for i, (v, png) in enumerate(imgs):
        ax = fig.add_subplot(rows, cols, i + 1)
        ax.imshow(plt.imread(png))
        ax.set_title(v, fontsize=9)
        ax.set_axis_off()
    t = title or ""
    if overhang is not None:
        t += f"   red: overhang > {overhang:.0f} deg, orange: flat ceiling; dots: problem spots"
    if t.strip():
        fig.suptitle(t.strip(), fontsize=10)
    fig.tight_layout()
    fig.savefig(out, facecolor="white")
    plt.close(fig)
    return out


def preview(meshes, out, views=("iso front", "iso back", "front", "top"), overhang=None, markers=(),
            colors=None, title=None, engine="auto"):
    """Best available renderer. Returns the output path."""
    if engine in ("auto", "openscad") and _scad_ok():
        try:
            return render_scad(meshes, out, list(views), overhang, markers, colors, title=title)
        except Exception as e:
            if engine == "openscad":
                raise
            print(f"openscad render failed, using matplotlib: {e}", file=sys.stderr)
    return render([subdivide(m) for m in meshes], out, views=views, overhang=overhang,
                  markers=markers, title=title, colors=colors)


def subdivide(mesh):
    """Smaller triangles sort better in matplotlib's painter algorithm."""
    try:
        import trimesh
        edge = max(mesh.extents.max() / 25, 0.5)
        v, f = trimesh.remesh.subdivide_to_size(mesh.vertices, mesh.faces, max_edge=edge, max_iter=6)
        if len(f) < 150000:
            return trimesh.Trimesh(v, f, process=False)
    except Exception:
        pass
    return mesh


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--views", default=None,
                    help="comma list from: " + ", ".join(VIEWS) + " (default: iso front,iso back,front,top; "
                         "with --overhang: iso front,iso back,iso below,front)")
    ap.add_argument("--engine", default="auto", choices=["auto", "openscad", "matplotlib"])
    ap.add_argument("--overhang", type=float, help="highlight overhangs steeper than this many degrees")
    ap.add_argument("--report", help="check_print.py JSON report: mark problem spots")
    ap.add_argument("--rotate", type=float, nargs=3)
    ap.add_argument("--layout", action="store_true", help="place several parts side by side")
    ap.add_argument("--title")
    ap.add_argument("-D", "--define", action="append")
    a = ap.parse_args()

    defines = dict(kv.split("=", 1) for kv in (a.define or []))
    meshes = [load_mesh(f, scad_defines=defines) for f in a.files]
    if a.rotate:
        for m in meshes:
            m.apply_transform(rotation_matrix_deg(*a.rotate))
    if a.layout and len(meshes) > 1:
        meshes = layout_side_by_side(meshes)
    elif a.report:
        for m in meshes:  # same frame as check_print.py: own XY, z from 0
            m.apply_translation([0, 0, -m.bounds[0][2]])
    markers = markers_from_report(a.report) if a.report else ()
    if a.views:
        views = [v.strip() for v in a.views.split(",") if v.strip()]
    elif a.overhang is not None:
        views = ["iso front", "iso back", "iso below", "front"]
    else:
        views = ["iso front", "iso back", "front", "top"]
    title = a.title or ", ".join(os.path.basename(f) for f in a.files)
    if a.engine == "matplotlib":
        render([subdivide(m) for m in meshes], a.out, views=views, overhang=a.overhang, markers=markers, title=title)
    else:
        preview(meshes, a.out, views=views, overhang=a.overhang, markers=markers, title=title, engine=a.engine)
    print(a.out)


if __name__ == "__main__":
    main()
