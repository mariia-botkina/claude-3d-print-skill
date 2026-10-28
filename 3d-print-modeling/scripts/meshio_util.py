"""Shared helpers: load any model file as a trimesh, render OpenSCAD, profile values."""
import json
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
