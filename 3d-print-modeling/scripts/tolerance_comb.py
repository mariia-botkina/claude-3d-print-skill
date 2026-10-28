#!/usr/bin/env python3
"""Build the tolerance comb as a ready-to-print Bambu project.

  python tolerance_comb.py -o out_dir [--material "Bambu PLA Basic"] [--color "#F2F2F2"]
                           [--nominal 8] [--clearances 0,0.05,0.1,0.15,0.2,0.25,0.3,0.4]

Writes out_dir/tolerance_comb.3mf (plate + round pin + square peg on one plate),
the STLs and a preview image. How to read the result is written at the top of
assets/tolerance_comb.scad; record it in references/printer-profile.md.
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCAD = os.path.join(os.path.dirname(HERE), "assets", "tolerance_comb.scad")
sys.path.insert(0, HERE)
from meshio_util import scad_to_stl  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--material", default="Bambu PLA Basic")
    ap.add_argument("--color", default="#F2F2F2")
    ap.add_argument("--nominal", type=float, default=8.0)
    ap.add_argument("--clearances", default=None, help="comma list, mm per side")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    defines = {"nominal": a.nominal}
    if a.clearances:
        defines["clearances"] = [float(x) for x in a.clearances.split(",")]
    files = {}
    for part in ("plate", "round_pin", "square_pin"):
        stl = os.path.join(a.out, f"comb_{part}.stl")
        d = dict(defines, part=part)
        scad_to_stl(SCAD, stl, d)
        files[part] = os.path.basename(stl)

    spec = {
        "project": "Tolerance comb",
        "filaments": [{"preset": a.material, "color": a.color}],
        "plates": [{"name": "Tolerance comb", "objects": [
            {"file": files["plate"], "name": "Comb plate"},
            {"file": files["round_pin"], "name": "Round pin"},
            {"file": files["square_pin"], "name": "Square peg"},
        ]}],
    }
    spec_path = os.path.join(a.out, "tolerance_comb.spec.json")
    with open(spec_path, "w") as f:
        json.dump(spec, f, indent=1)
    out3mf = os.path.join(a.out, "tolerance_comb.3mf")
    subprocess.run([sys.executable, os.path.join(HERE, "make_3mf.py"), spec_path, "-o", out3mf], check=True)
    subprocess.run([sys.executable, os.path.join(HERE, "render.py"),
                    *[os.path.join(a.out, f) for f in files.values()], "--layout",
                    "-o", os.path.join(a.out, "tolerance_comb_preview.png"), "--views", "iso front,top"], check=True)
    print(out3mf)


if __name__ == "__main__":
    main()
