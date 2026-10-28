#!/usr/bin/env python3
"""Find closed pockets (internal cavities) that need a pause to embed something,
and work out where the pause must go.

  python find_pockets.py part.stl                         # list cavities + pause heights
  python find_pockets.py part.stl --insert 10x3           # round insert, diameter x height (magnet 10x3)
  python find_pockets.py part.stl --insert 20x10x3        # box insert, W x L x H
  python find_pockets.py part.stl --insert M3nut          # M3 hex nut (also M4nut, M5nut)
  python find_pockets.py part.stl --process "0.16mm Optimal @BBL X1C" --json pockets.json

A cavity is a closed void fully inside the part. Printing stops before the first layer
that would close it; the user drops the insert in and resumes. For each cavity the
script reports:
  - its size, floor and ceiling height
  - pause_z: the Bambu layer (print_z) to pause before; put it in the make_3mf spec
  - the free height between the cavity floor and the first covering layer
and, with --insert, whether the insert fits:
  ERROR  insert taller than the free height: the nozzle would hit it
  WARN   less than 0.1 mm to spare in height, or tight in XY
Pockets open to the top are not reported (insert after printing).
"""
import argparse
import json
import math
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from meshio_util import load_mesh, process_layers, snap_to_layer  # noqa: E402

NUTS = {"m2": (4.0, 1.6), "m2.5": (5.0, 2.0), "m3": (5.5, 2.4), "m4": (7.0, 3.2), "m5": (8.0, 4.0),
        "m6": (10.0, 5.0), "m8": (13.0, 6.5)}  # across flats, height


def parse_insert(text):
    t = text.lower().replace(" ", "")
    m = re.fullmatch(r"(m[\d.]+)nut", t)
    if m:
        af, h = NUTS[m.group(1)]
        return {"kind": "hex", "across_flats": af, "across_corners": af / math.cos(math.pi / 6), "h": h, "label": text}
    nums = [float(x) for x in re.split(r"[x*]", t)]
    if len(nums) == 2:
        return {"kind": "round", "d": nums[0], "h": nums[1], "label": text}
    if len(nums) == 3:
        return {"kind": "box", "w": nums[0], "l": nums[1], "h": nums[2], "label": text}
    raise SystemExit(f"cannot parse insert '{text}': use DxH, WxLxH or M3nut")


def cavity_cross_section(cav, z):
    """Largest inscribed circle and min-area rectangle of the cavity's section at height z."""
    try:
        from shapely.ops import polylabel, unary_union
        sec = cav.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
        if sec is None:
            return None
        planar, T = sec.to_2D()
        poly = unary_union(planar.polygons_full)
        if poly.is_empty:
            return None
        big = max(getattr(poly, "geoms", [poly]), key=lambda p: p.area)
        center = polylabel(big, tolerance=0.01)
        r = big.exterior.distance(center)
        for hole in big.interiors:
            r = min(r, hole.distance(center))
        rect = big.minimum_rotated_rectangle
        xs, ys = rect.exterior.coords.xy
        sides = sorted({round(math.dist((xs[i], ys[i]), (xs[i + 1], ys[i + 1])), 2) for i in range(4)})
        return {"inscribed_d": round(2 * r, 2), "rect": [sides[0], sides[-1]], "area": round(big.area, 2)}
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("--insert", action="append",
                    help="insert size; one value applies to every cavity, or repeat to match cavities in order")
    ap.add_argument("--process", help="Bambu process preset (sets layer height)")
    ap.add_argument("--nozzle", type=float, help="nozzle diameter (default 0.4); picks that nozzle's default process")
    ap.add_argument("--json")
    a = ap.parse_args()

    first, h, proc = process_layers(a.process, a.nozzle)
    mesh = load_mesh(a.file)
    mesh.apply_translation([0, 0, -mesh.bounds[0][2]])
    bodies = mesh.split(only_watertight=False)
    cavities = [b for b in bodies if b.is_watertight and b.volume < 0]
    cavities.sort(key=lambda c: (c.bounds[1][2], c.bounds[0][0]))
    inserts = [parse_insert(t) for t in (a.insert or [])]

    out = {"file": a.file, "process": proc, "layer_height": h, "first_layer": first, "cavities": []}
    worst = 0
    print(f"== {os.path.basename(a.file)}: {len(cavities)} closed cavit{'y' if len(cavities) == 1 else 'ies'} ({proc})")
    for i, c in enumerate(cavities):
        lo, hi = c.bounds
        floor, ceil_z = float(lo[2]), float(hi[2])
        pz, bottom, layer_no = snap_to_layer(ceil_z, first, h)
        # the first layer that actually has the hole in it (its mid-plane is above the floor)
        _, eff_floor, _ = snap_to_layer(floor + 1e-3, first, h)
        free_h = round(bottom - eff_floor, 3)
        sec = cavity_cross_section(c, (floor + ceil_z) / 2)
        item = {
            "n": i + 1,
            "center_mm": [round(float(v), 2) for v in (lo + hi) / 2],
            "size_mm": [round(float(v), 2) for v in (hi - lo)],
            "floor_z": round(floor, 3), "ceiling_z": round(ceil_z, 3),
            "pause_z": pz, "pause_layer": layer_no, "free_height_mm": free_h,
            "section": sec, "problems": [],
        }
        if abs(bottom - ceil_z) > 1e-3 or abs(eff_floor - floor) > 1e-3:
            item["problems"].append(("INFO", f"cavity floor/ceiling ({floor:.2f}/{ceil_z:.2f} mm) are not on {h} mm layer boundaries: "
                                     f"as printed the pocket runs {eff_floor:.2f}-{bottom:.2f} mm; align them to the layer grid"))
        ins = inserts[i] if i < len(inserts) else (inserts[0] if len(inserts) == 1 else None)
        if ins:
            item["insert"] = ins["label"]
            if ins["h"] > free_h + 1e-6:
                item["problems"].append(("ERROR", f"insert height {ins['h']} mm > free height {free_h} mm: the nozzle would hit it; deepen the pocket"))
            elif free_h - ins["h"] < 0.1:
                item["problems"].append(("WARN", f"only {free_h - ins['h']:.2f} mm above the insert: the nozzle may drag it; deepen by 0.2 mm"))
            if sec:
                if ins["kind"] == "round":
                    gap = sec["inscribed_d"] - ins["d"]
                    need = "diameter"
                elif ins["kind"] == "hex":
                    gap = sec["inscribed_d"] - ins["across_flats"]
                    need = "across flats"
                else:
                    gap = min(sec["rect"][0] - min(ins["w"], ins["l"]), sec["rect"][1] - max(ins["w"], ins["l"]))
                    need = "width/length"
                if gap < 0:
                    item["problems"].append(("ERROR", f"insert does not fit: pocket is {-gap:.2f} mm too small in {need}"))
                elif gap < 0.15:
                    item["problems"].append(("WARN", f"tight: {gap:.2f} mm play in {need}; printed pockets come out ~0.1-0.2 mm small, use +0.2 mm"))
        out["cavities"].append(item)
        sev = {"ERROR": 2, "WARN": 1, "INFO": 0}
        worst = max([worst] + [sev[p[0]] for p in item["problems"]])
        s = sec or {}
        print(f"   #{item['n']} at {item['center_mm'][:2]} size {item['size_mm']} mm, floor {floor:.2f} / ceiling {ceil_z:.2f} mm"
              + (f", inscribed d {s['inscribed_d']} mm" if s else ""))
        print(f"      pause before layer {layer_no} (pause_z {pz}); free height {free_h} mm" + (f"; insert {item.get('insert')}" if "insert" in item else ""))
        for sv, msg in item["problems"]:
            print(f"      [{sv}] {msg}")
    if not cavities:
        print("   nothing to embed: no fully enclosed voids")
    if a.json:
        with open(a.json, "w") as f:
            json.dump(out, f, indent=1)
    sys.exit(1 if worst == 2 else 0)


if __name__ == "__main__":
    main()
