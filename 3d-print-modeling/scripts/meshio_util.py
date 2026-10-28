"""Shared helpers: load any model file as a trimesh, render OpenSCAD, profile values."""
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np
import trimesh

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)


def printer_defaults():
    """Numbers from references/printer-profile.md, kept in sync by hand."""
    return {
        "bed_x": 256.0, "bed_y": 256.0, "bed_z": 256.0,
        # P1S: the corner with the purge/cutter area is not printable
        "exclude": [(0.0, 0.0, 18.0, 28.0)],
        "nozzle": 0.4,
        "layer": 0.2,
        "overhang_deg": 45.0,
        "density": {"PLA": 1.24, "PETG": 1.27, "TPU": 1.21, "ABS": 1.04, "ASA": 1.07},
    }


def openscad_bin():
    return shutil.which("openscad")


def scad_to_stl(scad_path, out_stl=None, defines=None, timeout=900):
    """Render an OpenSCAD file to STL. defines: {"width": 40} -> -D width=40."""
    exe = openscad_bin()
    if not exe:
        sys.exit("openscad is not installed: run scripts/setup.sh first")
    if out_stl is None:
        out_stl = os.path.splitext(scad_path)[0] + ".stl"
    cmd = [exe, "-o", out_stl]
    for k, v in (defines or {}).items():
        cmd += ["-D", f"{k}={json.dumps(v)}"]
    cmd.append(scad_path)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0 or not os.path.exists(out_stl):
        sys.exit(f"OpenSCAD failed for {scad_path}:\n{r.stderr[-3000:]}")
    warnings = [l for l in r.stderr.splitlines() if "WARNING" in l or "ERROR" in l]
    return out_stl, warnings


def load_mesh(path, scad_defines=None):
    """Load STL/OBJ/3MF/PLY/OFF or render .scad first. Returns one Trimesh (all bodies merged)."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".scad":
        tmp = tempfile.mkdtemp(prefix="scad_")
        stl, _ = scad_to_stl(path, os.path.join(tmp, "model.stl"), scad_defines)
        path = stl
    loaded = trimesh.load(path, force=None, process=True)
    if isinstance(loaded, trimesh.Scene):
        geoms = [g for g in loaded.dump(concatenate=False) if isinstance(g, trimesh.Trimesh)]
        if not geoms:
            raise ValueError(f"{path}: no triangle meshes inside")
        mesh = trimesh.util.concatenate(geoms)
    else:
        mesh = loaded
    return mesh


def rotation_matrix_deg(rx=0.0, ry=0.0, rz=0.0):
    m = np.eye(4)
    for angle, axis in ((rx, [1, 0, 0]), (ry, [0, 1, 0]), (rz, [0, 0, 1])):
        if angle:
            m = trimesh.transformations.rotation_matrix(np.radians(angle), axis) @ m
    return m


def drop_to_bed(mesh):
    """Return a copy sitting on z=0, centred on the origin in XY."""
    m = mesh.copy()
    lo, hi = m.bounds
    m.apply_translation([-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]])
    return m


# ---------------------------------------------------------------- layer grid

def process_layers(process=None):
    """(first_layer_height, layer_height) for a Bambu process preset name (default preset if None)."""
    assets = os.path.join(SKILL_DIR, "assets", "bambu")
    with open(os.path.join(assets, "presets.json"), encoding="utf-8") as f:
        presets = json.load(f)
    name = process or presets["meta"]["default_process"]
    if name not in presets["process"]:
        hits = [n for n in presets["process"] if n.lower().startswith(name.lower())]
        if len(hits) != 1:
            raise ValueError(f"unknown process preset '{name}'")
        name = hits[0]
    p = presets["process"][name]
    return float(p.get("initial_layer_print_height", 0.2)), float(p.get("layer_height", 0.2)), name


def layer_tops(first, h, top):
    """print_z (top) of every layer up to height `top`."""
    zs = [first]
    while zs[-1] < top - 1e-6:
        zs.append(round(zs[-1] + h, 4))
    return zs


def snap_to_layer(z, first, h):
    """The first layer whose material lies at or above height z, as Bambu's print_z (layer top).

    Slicers cut each layer at its mid-height, so a layer belongs to "above z" as soon as
    its mid-plane is at or above z. An event "at z" (pause or filament change) happens
    before that layer. For a cavity ceiling at z this is the first layer that closes it.
    Returns (print_z, bottom_of_that_layer, layer_number_1_based)."""
    bottom, top, n = 0.0, first, 1
    while (bottom + top) / 2 < z - 1e-6:
        bottom, top, n = top, round(top + h, 4), n + 1
    return round(top, 4), round(bottom, 4), n


def band_split(mesh, start_filament, cuts):
    """Split a mesh at filament-change heights for colour previews: [(piece, filament)]."""
    cuts = sorted(c for c in cuts if mesh.bounds[0][2] < c[0] < mesh.bounds[1][2])
    if not cuts:
        return [(mesh, start_filament)]
    from trimesh.intersections import slice_mesh_plane
    out, cur, lo = [], start_filament, None
    for z, f in cuts + [(None, None)]:
        piece = mesh
        if lo is not None:
            piece = slice_mesh_plane(piece, [0, 0, 1], [0, 0, lo], cap=True)
        if z is not None:
            piece = slice_mesh_plane(piece, [0, 0, -1], [0, 0, z], cap=True)
        if len(piece.faces):
            out.append((piece, cur))
        lo, cur = z, f
    return out
