#!/usr/bin/env python3
"""Cut a small test piece out of a model: print only the feature you need to check
(a fit, a slot, a hinge, a snap) instead of the whole part.

  python test_slice.py part.stl --z 0 6 -o test.stl                 # bottom 6 mm, full XY
  python test_slice.py part.stl --box 10 -5 0 40 25 8 -o test.stl   # x0 y0 z0 x1 y1 z1
  python test_slice.py part.stl --around 25 10 4 12 -o test.stl     # cube of half-size 12 mm around x y z
  python test_slice.py lid.stl box.stl --z 20 26 -o lid_t.stl box_t.stl   # same cut on mating parts

Coordinates are the model's own (same as check_print.py and render.py). The cut piece is
dropped onto the bed; a piece cut from the middle of a part starts on the flat cut face.
Prints the mass and time of the test piece against the full part (reference slice), so
the saving is visible. Check the piece with check_print.py: a cut can create overhangs
or islands the full part does not have.
"""
import argparse
import os
import subprocess
import sys
import json
import tempfile

import numpy as np
import trimesh

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from meshio_util import load_mesh  # noqa: E402


def cut(mesh, lo, hi):
    lo = np.asarray(lo, float)
    hi = np.asarray(hi, float)
    ext = hi - lo
    box = trimesh.creation.box(extents=ext)
    box.apply_translation((lo + hi) / 2)
    try:
        piece = trimesh.boolean.intersection([mesh, box], engine="manifold")
    except Exception as e:
        sys.exit(f"cut failed: {e}")
    if piece.is_empty or len(piece.faces) == 0:
        sys.exit("the box does not overlap the model")
    return piece


def ref_slice(path, material, nozzle):
    js = os.path.join(tempfile.mkdtemp(prefix="ts_"), "s.json")
    subprocess.run([sys.executable, os.path.join(HERE, "slice_check.py"), path, "--material", material,
                    "--nozzle", str(nozzle), "--no-support-pass", "--json", js],
                   capture_output=True, text=True, timeout=1800)
    if not os.path.exists(js):
        return None
    with open(js) as f:
        return json.load(f).get("no_supports", {})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--z", nargs=2, type=float, metavar=("Z0", "Z1"))
    g.add_argument("--box", nargs=6, type=float, metavar=("X0", "Y0", "Z0", "X1", "Y1", "Z1"))
    g.add_argument("--around", nargs=4, type=float, metavar=("X", "Y", "Z", "R"))
    ap.add_argument("-o", "--out", nargs="+", required=True)
    ap.add_argument("--material", default="PLA")
    ap.add_argument("--nozzle", type=float, default=0.4)
    ap.add_argument("--no-slice", action="store_true", help="skip the reference slices (faster)")
    a = ap.parse_args()
    if len(a.out) != len(a.files):
        ap.error("give one output per input file")

    for src, dst in zip(a.files, a.out):
        mesh = load_mesh(src)
        mesh.apply_translation([0, 0, -mesh.bounds[0][2]])   # same frame as check_print.py
        lo, hi = mesh.bounds
        pad = 1.0
        if a.z:
            box_lo = [lo[0] - pad, lo[1] - pad, a.z[0]]
            box_hi = [hi[0] + pad, hi[1] + pad, a.z[1]]
        elif a.box:
            box_lo, box_hi = a.box[:3], a.box[3:]
        else:
            x, y, z, r = a.around
            box_lo, box_hi = [x - r, y - r, max(0.0, z - r)], [x + r, y + r, z + r]
        piece = cut(mesh, box_lo, box_hi)
        piece.apply_translation([0, 0, -piece.bounds[0][2]])
        piece.export(dst)
        vf, vp = abs(mesh.volume), abs(piece.volume)
        line = (f"{os.path.basename(src)} -> {dst}: {piece.extents[0]:.1f} x {piece.extents[1]:.1f} x "
                f"{piece.extents[2]:.1f} mm, {vp / max(vf, 1e-9):.0%} of the part's volume")
        if not a.no_slice:
            full = ref_slice(src, a.material, a.nozzle) or {}
            part = ref_slice(dst, a.material, a.nozzle) or {}
            if full.get("filament_g") and part.get("filament_g"):
                line += (f"; test {part['filament_g']} g / {part.get('time', '?')} "
                         f"instead of {full['filament_g']} g / {full.get('time', '?')}")
        print(line)
    print("next: check_print.py on the test piece; the cut faces sit flat, but new overhangs can appear")


if __name__ == "__main__":
    main()
