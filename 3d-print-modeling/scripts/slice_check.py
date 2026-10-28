#!/usr/bin/env python3
"""Reference slice with PrusaSlicer (headless) to cross-check printability.

Bambu Studio cannot run in the sandbox, so this uses PrusaSlicer configured to
approximate a Bambu Lab P1S with a 0.4 nozzle. The numbers are a reference,
not the final word: the user slices the 3MF in Bambu Studio.

What it gives:
  - whether slicing succeeds at all (broken meshes, empty layers)
  - slicer warnings (supports needed, empty layers, thin features dropped)
  - estimated time and filament for: no supports, and auto supports
    -> the difference is what supports would cost
  - parts of the model that produce no extrusion (lost thin details)

Usage:
  python slice_check.py part.stl [--material PLA|PETG] [--layer 0.2]
                        [--infill 15] [--walls 2] [--json out.json] [--keep-gcode DIR]
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from meshio_util import load_mesh  # noqa: E402

MATERIALS = {
    "PLA": {"filament_type": "PLA", "filament_density": 1.24, "temperature": 220, "bed_temperature": 55,
            "max_volumetric_speed": 21},
    "PETG": {"filament_type": "PETG", "filament_density": 1.27, "temperature": 255, "bed_temperature": 70,
             "max_volumetric_speed": 12},
    "TPU": {"filament_type": "FLEX", "filament_density": 1.21, "temperature": 230, "bed_temperature": 35,
            "max_volumetric_speed": 3.6},
}

# Rough P1S-like motion settings so the time estimate is in the right ballpark
P1S_INI = """
printer_technology = FFF
bed_shape = 0x0,256x0,256x256,0x256
max_print_height = 256
nozzle_diameter = 0.4
filament_diameter = 1.75
gcode_flavor = marlin2
use_relative_e_distances = 1
layer_gcode = G92 E0
machine_max_acceleration_extruding = 10000
machine_max_acceleration_travel = 10000
machine_max_acceleration_x = 20000
machine_max_acceleration_y = 20000
machine_max_feedrate_x = 500
machine_max_feedrate_y = 500
machine_max_feedrate_z = 20
perimeter_speed = 200
external_perimeter_speed = 200
infill_speed = 270
solid_infill_speed = 250
top_solid_infill_speed = 200
support_material_speed = 150
bridge_speed = 50
gap_fill_speed = 250
travel_speed = 500
first_layer_speed = 50
default_acceleration = 10000
perimeter_acceleration = 5000
infill_acceleration = 10000
bridge_acceleration = 5000
first_layer_acceleration = 500
travel_acceleration = 10000
top_solid_layers = 5
bottom_solid_layers = 3
fill_pattern = grid
first_layer_height = 0.2
skirts = 0
brim_width = 0
support_material_auto = 1
support_material_threshold = 0
support_material_style = organic
support_material_contact_distance = 0.2
complete_objects = 0
"""


def parse_gcode(path):
    info = {}
    with open(path, encoding="utf-8", errors="ignore") as f:
        tail = f.readlines()[-400:]
    for line in tail:
        m = re.match(r"; estimated printing time \(normal mode\) = (.+)", line)
        if m:
            info["time"] = m.group(1).strip()
        m = re.match(r"; total filament used \[g\] = ([\d.]+)", line)
        if m:
            info["filament_g"] = float(m.group(1))
        m = re.match(r"; filament used \[mm\] = ([\d.]+)", line)
        if m:
            info["filament_m"] = round(float(m.group(1)) / 1000, 2)
        m = re.match(r"; support material extrusion.*", line)
    return info


def time_to_min(t):
    total = 0
    for val, unit in re.findall(r"(\d+)([dhms])", t or ""):
        total += int(val) * {"d": 1440, "h": 60, "m": 1, "s": 1 / 60}[unit]
    return round(total, 1)


def run_slice(exe, stl, ini, out_gcode, supports, timeout):
    cmd = [exe, "--export-gcode", "--load", ini,
           "--support-material" if supports else "--no-support-material",
           "--center", "128,128", "--output", out_gcode, stl]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    log = (r.stdout or "") + (r.stderr or "")
    lines = [l.strip() for l in log.splitlines() if l.strip() and "=>" not in l]
    warnings = []
    for i, line in enumerate(lines):
        low = line.lower()
        if low.startswith("slicing result exported") or low.endswith(".stl"):
            continue
        if "detected print stability issues" in low:
            # the issue list follows on a later line, e.g. "Floating bridge anchors, Loose extrusions"
            detail = next((l for l in lines[i + 1:i + 4] if "," in l or "extrusion" in l.lower() or "bridg" in l.lower()), "")
            warnings.append("stability issues: " + detail if detail else line)
            continue
        if any(k in low for k in ("warning", "error", "empty layer", "consider enabling supports", "no extrusion")):
            if not low.startswith("print warning: detected"):
                warnings.append(line)
    ok = r.returncode == 0 and os.path.exists(out_gcode)
    return ok, warnings, log


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("--material", default="PLA", choices=sorted(MATERIALS))
    ap.add_argument("--layer", type=float, default=0.2)
    ap.add_argument("--infill", type=int, default=15)
    ap.add_argument("--walls", type=int, default=2)
    ap.add_argument("--json")
    ap.add_argument("--keep-gcode", help="directory to keep the reference gcode in")
    ap.add_argument("--timeout", type=int, default=900)
    a = ap.parse_args()

    exe = shutil.which("prusa-slicer") or shutil.which("PrusaSlicer")
    if not exe:
        sys.exit("prusa-slicer is not installed: run scripts/setup.sh (needs apt). Skip this step if apt is unavailable.")

    work = tempfile.mkdtemp(prefix="slice_")
    # PrusaSlicer reads STL/3MF/OBJ; normalise everything (incl. .scad) to STL
    mesh = load_mesh(a.file)
    stl = os.path.join(work, "model.stl")
    mesh.export(stl)

    mat = MATERIALS[a.material]
    ini = os.path.join(work, "p1s.ini")
    with open(ini, "w") as f:
        f.write(P1S_INI)
        f.write(f"layer_height = {a.layer}\nperimeters = {a.walls}\nfill_density = {a.infill}%\n")
        f.write(f"filament_type = {mat['filament_type']}\nfilament_density = {mat['filament_density']}\n")
        f.write(f"temperature = {mat['temperature']}\nfirst_layer_temperature = {mat['temperature']}\n")
        f.write(f"bed_temperature = {mat['bed_temperature']}\nfirst_layer_bed_temperature = {mat['bed_temperature']}\n")
        f.write(f"filament_max_volumetric_speed = {mat['max_volumetric_speed']}\n")

    result = {"file": a.file, "slicer": "PrusaSlicer (P1S approximation)", "material": a.material}
    for label, sup in (("no_supports", False), ("auto_supports", True)):
        gc = os.path.join(work, f"{label}.gcode")
        ok, warns, log = run_slice(exe, stl, ini, gc, sup, a.timeout)
        entry = {"ok": ok, "warnings": warns[:20]}
        if ok:
            entry.update(parse_gcode(gc))
            entry["time_min"] = time_to_min(entry.get("time"))
            if a.keep_gcode:
                os.makedirs(a.keep_gcode, exist_ok=True)
                shutil.copy(gc, os.path.join(a.keep_gcode, f"{os.path.splitext(os.path.basename(a.file))[0]}_{label}.gcode"))
        else:
            entry["log_tail"] = log[-1500:]
        result[label] = entry

    ns, ws = result["no_supports"], result["auto_supports"]
    print(f"== reference slice of {os.path.basename(a.file)} ({a.material}, {a.layer} mm, {a.walls} walls, {a.infill}% infill)")
    if not ns["ok"]:
        print("   [ERROR] slicing failed:\n" + ns.get("log_tail", "")[-800:])
    else:
        print(f"   without supports: {ns.get('time', '?')}, {ns.get('filament_g', '?')} g")
        if ws.get("ok"):
            extra_g = round(ws.get("filament_g", 0) - ns.get("filament_g", 0), 2)
            extra_t = round(ws.get("time_min", 0) - ns.get("time_min", 0), 1)
            result["support_cost"] = {"grams": extra_g, "minutes": extra_t}
            if extra_g > 0.05:
                print(f"   with auto supports: {ws.get('time', '?')}, {ws.get('filament_g', '?')} g  -> supports cost ~{extra_g} g, ~{extra_t} min: the slicer thinks supports are needed")
            else:
                print("   auto supports add nothing: the slicer sees no area that needs support")
        for w in sorted(set(ns["warnings"]))[:10]:
            print(f"   [slicer] {w}")
    print("   note: PrusaSlicer approximation; Bambu Studio numbers will differ somewhat")
    if a.json:
        with open(a.json, "w") as f:
            json.dump(result, f, indent=1)
    sys.exit(0 if ns["ok"] else 1)


if __name__ == "__main__":
    main()
