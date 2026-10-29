#!/usr/bin/env python3
"""Cost of a print: filament (parts, supports, colour-change purge, prime tower),
electricity and printer wear, per plate and per piece. Uses the same spec as make_3mf.py.

  python cost.py spec.json --prices prices.json            # cost of the project as specified
  python cost.py spec.json --prices prices.json --json cost.json
  python cost.py spec.json --prices prices.json --compare old_cost.json   # was / now
  python cost.py spec.json --prices prices.json --batch 30  # 30 sets: plates needed, cost per set

prices.json (ask the user per project; prices change, record them in REQUIREMENTS.md):
{
  "currency": "RUB",
  "filament_per_kg": {"Bambu PLA Basic": 1900, "Bambu PETG HF": 2100, "PLA": 1900},
  "electricity_per_kwh": 6.5,
  "printer_power_w": 105,          # P1S printing PLA, Bambu wiki average; PETG ~ +20%
  "wear_per_hour": 15              # printer price / expected life hours + nozzles, belts, plate
}
Keys of filament_per_kg may be preset names (with or without " @BBL ...") or a filament
type (PLA, PETG...). Anything missing is reported and counted as 0, never guessed.

Numbers come from PrusaSlicer reference slices (see slice_check.py) plus an estimate of
purge and prime-tower filament from the colour layout; Bambu Studio's own numbers after
slicing are the real ones. Purge per change uses the same colour-based flush volumes as
make_3mf.py (dark to light needs ~600 mm3, light to dark ~170 mm3).
"""
import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_3mf as M  # noqa: E402
from meshio_util import process_layers  # noqa: E402

DENSITY = {"PLA": 1.24, "PETG": 1.27, "TPU": 1.21, "ABS": 1.04, "ASA": 1.07, "PC": 1.20, "PVA": 1.23}
SLICE_MATERIAL = {"PLA": "PLA", "PETG": "PETG", "TPU": "TPU"}
TOWER_LINE = 0.42  # mm


def filament_type(preset):
    up = preset.upper()
    for t in ("PETG", "PLA", "TPU", "ABS", "ASA", "PVA", "PC"):
        if t in up.split(" @")[0]:
            return t
    return "PLA"


def price_per_kg(prices, preset):
    table = prices.get("filament_per_kg", {})
    short = preset.split(" @")[0]
    for key in (preset, short, filament_type(preset)):
        if key in table:
            return float(table[key]), key
    return None, None


class SliceCache:
    def __init__(self, nozzle):
        self.nozzle = nozzle
        self.dir = tempfile.mkdtemp(prefix="cost_")
        self.cache = {}

    def get(self, mesh, material, walls, infill, supports):
        h = hashlib.sha1(mesh.vertices.tobytes() + mesh.faces.tobytes()).hexdigest()[:16]
        key = (h, material, walls, infill, supports)
        if key in self.cache:
            return self.cache[key]
        stl = os.path.join(self.dir, f"{h}.stl")
        if not os.path.exists(stl):
            mesh.export(stl)
        js = os.path.join(self.dir, f"{h}_{material}_{walls}_{infill}.json")
        cmd = [sys.executable, os.path.join(HERE, "slice_check.py"), stl, "--material", material,
               "--nozzle", str(self.nozzle), "--walls", str(walls), "--infill", str(infill), "--json", js]
        if not supports:
            cmd.append("--no-support-pass")
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        res = {"grams": None, "minutes": None, "support_grams": 0.0}
        if os.path.exists(js):
            with open(js) as f:
                d = json.load(f)
            ns = d.get("no_supports", {})
            src = d.get("auto_supports", ns) if supports and d.get("auto_supports", {}).get("ok") else ns
            res = {"grams": src.get("filament_g"), "minutes": src.get("time_min"),
                   "support_grams": round((src.get("filament_g") or 0) - (ns.get("filament_g") or 0), 2) if supports else 0.0}
        elif r.returncode != 0:
            print(f"warning: reference slice failed: {r.stdout[-300:]}{r.stderr[-300:]}", file=sys.stderr)
        self.cache[key] = res
        return res


def as_int_percent(v, default):
    if v is None:
        return default
    try:
        return int(round(float(str(v).rstrip("%"))))
    except ValueError:
        return default


def plate_costs(spec, objs, plates, names, prices, cache, first_h, layer_h, events):
    colors = [f.get("color", "#FFFFFF") for f in (spec.get("filaments") or [{}])]
    proj = spec.get("settings") or {}
    out = []
    for pi, pl in enumerate(plates):
        on = [o for o in objs if o.plate == pi]
        grams_by_fil, minutes, support_g = {}, 0.0, 0.0
        ranges = []   # (zmin, zmax, filament) for colour layout
        missing_slice = False
        for o in on:
            st = dict(proj, **(o.settings or {}))
            walls = as_int_percent(st.get("wall_loops"), 2)
            infill = as_int_percent(st.get("sparse_infill_density"), 15)
            supports = str(st.get("enable_support", "0")) in ("1", "true", "True")
            base_z = min(p[0].bounds[0][2] for p in o.parts if p[2] == "normal_part")
            for (m, fil, subtype, pname, psettings) in o.parts:
                if subtype != "normal_part":
                    continue
                f = int(fil or o.filament or 1)
                mat = SLICE_MATERIAL.get(filament_type(names[f - 1]), "PLA")
                pst = dict(st, **(psettings or {}))
                r = cache.get(m, mat, as_int_percent(pst.get("wall_loops"), walls),
                              as_int_percent(pst.get("sparse_infill_density"), infill), supports)
                if r["grams"] is None:
                    missing_slice = True
                    continue
                grams_by_fil[f] = grams_by_fil.get(f, 0.0) + r["grams"]
                minutes += r["minutes"] or 0.0
                support_g += r["support_grams"] or 0.0
                ranges.append((m.bounds[0][2] - base_z, m.bounds[1][2] - base_z, f))
        # colour layout: filament changes per layer + height events
        top = max([r[1] for r in ranges] or [0])
        changes, tower_layers, prev_set, z = 0, 0, None, first_h
        ev = events.get(pi, {}).get("events", [])
        fil_events = sorted((e["bottom"], e["extruder"]) for e in ev if e["type"] == "filament")
        while z <= top + 1e-6 and ranges:
            mid = z - layer_h / 2
            cur = {f for (a, b, f) in ranges if a <= mid <= b}
            if fil_events:   # single-filament plate with height colour changes
                active = [f for (bz, f) in fil_events if bz <= mid]
                if active:
                    cur = {active[-1]}
            if len(cur) > 1:
                changes += len(cur) - 1
                tower_layers += 1
            if prev_set is not None and cur and prev_set and (not (cur & prev_set) or (len(prev_set) > 1 and len(cur) == 1)):
                changes += 1   # new filament, or back to one filament after a multi-colour layer
            if cur:
                prev_set = cur
            z = round(z + layer_h, 4)
        n_fil_plate = len({r[2] for r in ranges})
        dens = DENSITY.get(filament_type(names[0]), 1.24)
        used = sorted({r[2] for r in ranges} | {e["extruder"] for e in ev if e["type"] == "filament"})
        if spec.get("flush_volume") is not None:
            flush_mm3 = float(spec["flush_volume"])
        elif len(used) > 1:
            pairs = [M.flush_volume(colors[a - 1], colors[b - 1]) for a in used for b in used if a != b]
            flush_mm3 = sum(pairs) / len(pairs)
        else:
            flush_mm3 = 0.0
        purge_g = changes * flush_mm3 * dens / 1000.0
        tower_g = 0.0
        if n_fil_plate > 1 and spec.get("settings", {}).get("enable_prime_tower", "1") not in ("0", 0, False):
            width = 35.0
            per_layer_mm3 = 4 * width * 2 * TOWER_LINE * layer_h
            tower_g = tower_layers * per_layer_mm3 * dens / 1000.0
        # P1S + AMS change: cut and unload 28 s, load 29 s (Bambu machine profile), purge at
        # ~21 mm3/s with pulses, wipe and shake: about 1.5-2 min each, measured in Bambu's own G-code
        change_min = changes * (1.0 + flush_mm3 / 21.0 / 60.0 * 1.6)
        minutes += change_min
        out.append({
            "plate": pi + 1, "name": pl.get("name", f"Plate {pi + 1}"),
            "objects": len(on),
            "part_grams_by_filament": {str(k): round(v, 2) for k, v in grams_by_fil.items()},
            "part_grams": round(sum(grams_by_fil.values()), 2),
            "support_grams": round(support_g, 2),
            "filament_changes": changes, "purge_grams": round(purge_g, 2),
            "prime_tower_grams": round(tower_g, 2),
            "minutes": round(minutes, 1), "incomplete": missing_slice,
        })
    return out


def money(plates, names, prices):
    elec = prices.get("electricity_per_kwh")
    power = float(prices.get("printer_power_w", 105))
    wear = prices.get("wear_per_hour")
    missing = set()
    for p in plates:
        fil_cost = 0.0
        for f, g in p["part_grams_by_filament"].items():
            ppk, _ = price_per_kg(prices, names[int(f) - 1])
            if ppk is None:
                missing.add(names[int(f) - 1].split(" @")[0])
                continue
            fil_cost += g / 1000 * ppk
        # waste (supports, purge, tower) priced at the first filament's price as an estimate
        waste_g = p["support_grams"] + p["purge_grams"] + p["prime_tower_grams"]
        ppk0 = None
        for f in sorted(p["part_grams_by_filament"], key=int):
            ppk0, _ = price_per_kg(prices, names[int(f) - 1])
            if ppk0:
                break
        waste_cost = waste_g / 1000 * (ppk0 or 0)
        hours = p["minutes"] / 60
        e_cost = hours * power / 1000 * float(elec) if elec is not None else 0.0
        w_cost = hours * float(wear) if wear is not None else 0.0
        p["cost"] = {"filament": round(fil_cost, 2), "waste": round(waste_cost, 2),
                     "electricity": round(e_cost, 2), "wear": round(w_cost, 2),
                     "total": round(fil_cost + waste_cost + e_cost + w_cost, 2)}
        p["grams_total"] = round(p["part_grams"] + waste_g, 2)
    if elec is None:
        missing.add("electricity_per_kwh")
    if wear is None:
        missing.add("wear_per_hour")
    return sorted(missing)


def hints(plates, spec):
    out = []
    for p in plates:
        tot = max(p["grams_total"], 1e-6)
        if p["support_grams"] > 0.1 * tot:
            out.append(f"plate {p['plate']}: supports are {p['support_grams']:.1f} g ({p['support_grams'] / tot:.0%}): reorient, chamfer or split to avoid them")
        waste = p["purge_grams"] + p["prime_tower_grams"]
        if waste > 0.3 * tot:
            out.append(f"plate {p['plate']}: purge + prime tower {waste:.1f} g ({waste / tot:.0%}) for {p['filament_changes']} filament changes: "
                       "fewer colour changes (colour only on the top layers, fewer colours per layer), more copies per plate so the purge is shared, "
                       "or purge into infill/objects (ask first)")
    inf = (spec.get("settings") or {}).get("sparse_infill_density")
    if inf and as_int_percent(inf, 15) > 25:
        out.append(f"project infill {inf}: more walls usually give strength for less plastic than dense infill")
    return out


def batch_plan(spec, base_dir, n_sets, has_multi):
    """Copies of the whole project as sets, packed onto as few plates as possible."""
    objs_spec = []
    plates = spec.get("plates", [])
    src = [o for pl in plates for o in pl.get("objects", [])] if plates != "auto" else spec.get("objects", [])
    for o in src:
        o2 = dict(o)
        o2["copies"] = int(o.get("copies", 1)) * n_sets
        objs_spec.append(o2)
    events = [e for pl in (plates if plates != "auto" else []) for e in pl.get("events", [])]
    bspec = dict(spec, plates="auto", objects=objs_spec)
    bspec["events"] = []
    if events:
        print("note: batch plan ignores height events (pauses, colour changes); they apply per plate", file=sys.stderr)
    objs, bplates = M.assign_plates(bspec, base_dir, has_multi)
    return bspec, objs, bplates


def print_table(title, plates, cur, missing):
    print(f"== {title}")
    tot = {"g": 0.0, "min": 0.0, "cost": 0.0}
    for p in plates:
        c = p["cost"]
        extra = []
        if p["support_grams"]:
            extra.append(f"supports {p['support_grams']} g")
        if p["purge_grams"]:
            extra.append(f"purge {p['purge_grams']} g ({p['filament_changes']} changes)")
        if p["prime_tower_grams"]:
            extra.append(f"tower {p['prime_tower_grams']} g")
        print(f"   plate {p['plate']} '{p['name']}': {p['grams_total']} g ({p['part_grams']} g in parts"
              + (", " + ", ".join(extra) if extra else "") + f"), {p['minutes'] / 60:.1f} h"
              + f" -> {c['total']} {cur} (filament {c['filament']}, waste {c['waste']}, electricity {c['electricity']}, wear {c['wear']})"
              + (" [some parts could not be sliced]" if p["incomplete"] else ""))
        tot["g"] += p["grams_total"]
        tot["min"] += p["minutes"]
        tot["cost"] += c["total"]
    print(f"   total: {tot['g']:.1f} g, {tot['min'] / 60:.1f} h, {tot['cost']:.2f} {cur}")
    if missing:
        print(f"   not priced (counted as 0): {', '.join(missing)}: ask the user and add to prices.json")
    return tot


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec")
    ap.add_argument("--prices", help="prices.json (see above)")
    ap.add_argument("--json", help="write the result here")
    ap.add_argument("--compare", help="earlier --json result: print was / now")
    ap.add_argument("--batch", type=int, help="cost per set when printing this many sets")
    ap.add_argument("--sets-per-project", type=int, default=1,
                    help="how many finished items one project spec makes (for cost per item)")
    a = ap.parse_args()

    with open(a.spec, encoding="utf-8") as f:
        spec = json.load(f)
    prices = {}
    if a.prices:
        with open(a.prices, encoding="utf-8") as f:
            prices = json.load(f)
    cur = prices.get("currency", "RUB")
    base_dir = os.path.dirname(os.path.abspath(a.spec))
    nozzle = spec.get("nozzle", 0.4)
    base, presets, roles = M.load_assets(nozzle)
    names = [M.find_filament(presets, f.get("preset", "Bambu PLA Basic"))
             for f in (spec.get("filaments") or [{"preset": "Bambu PLA Basic"}])]
    first_h, layer_h, _ = process_layers(spec.get("process"), nozzle)
    cache = SliceCache(nozzle)

    def has_multi(objs):
        used = set()
        for o in objs:
            for (_, fil, subtype, _, _) in o.parts:
                if subtype == "normal_part":
                    used.add(int(fil or o.filament or 1))
        return len(used) > 1

    objs, plates = M.assign_plates(json.loads(json.dumps(spec)), base_dir, has_multi)
    colors = [f.get("color", "#FFFFFF") for f in (spec.get("filaments") or [{}])]
    events, _ = M.resolve_events(spec, plates, objs, colors, len(names))
    pc = plate_costs(spec, objs, plates, names, prices, cache, first_h, layer_h, events)
    missing = money(pc, names, prices)
    tot = print_table(f"cost of {os.path.basename(a.spec)} (PrusaSlicer reference + purge estimate)", pc, cur, missing)
    per_item = tot["cost"] / max(1, a.sets_per_project)
    if a.sets_per_project > 1:
        print(f"   per item ({a.sets_per_project} per project): {per_item:.2f} {cur}")
    result = {"spec": a.spec, "currency": cur, "plates": pc, "total": tot, "per_item": round(per_item, 2),
              "prices": prices, "missing_prices": missing}

    if a.batch:
        bspec, bobjs, bplates = batch_plan(spec, base_dir, a.batch, has_multi)
        bevents = {}
        bpc = plate_costs(bspec, bobjs, bplates, names, prices, cache, first_h, layer_h, bevents)
        money(bpc, names, prices)
        btot = print_table(f"batch of {a.batch} sets, packed onto {len(bplates)} plate(s)", bpc, cur, [])
        items = a.batch * a.sets_per_project
        print(f"   per item in the batch: {btot['cost'] / items:.2f} {cur} "
              f"({btot['g'] / items:.1f} g) vs {per_item:.2f} {cur} printed one project at a time")
        result["batch"] = {"sets": a.batch, "plates": bpc, "total": btot, "per_item": round(btot["cost"] / items, 2)}

    for h in hints(pc, spec):
        print(f"   hint: {h}")
    result["hints"] = hints(pc, spec)

    if a.compare and os.path.exists(a.compare):
        with open(a.compare) as f:
            old = json.load(f)
        ot = old.get("total", {})
        dg = tot["g"] - ot.get("g", 0)
        dc = tot["cost"] - ot.get("cost", 0)
        dm = tot["min"] - ot.get("min", 0)
        print(f"== was / now: {ot.get('g', 0):.1f} g -> {tot['g']:.1f} g ({dg:+.1f} g), "
              f"{ot.get('min', 0) / 60:.1f} h -> {tot['min'] / 60:.1f} h ({dm / 60:+.1f} h), "
              f"{ot.get('cost', 0):.2f} -> {tot['cost']:.2f} {cur} ({dc:+.2f})")
        result["compared_to"] = {"file": a.compare, "delta_g": round(dg, 2), "delta_cost": round(dc, 2), "delta_min": round(dm, 1)}
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
