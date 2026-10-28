#!/usr/bin/env python3
"""Regenerate assets/bambu/*.json from Bambu Studio's system profiles.

Maintainer tool, not used by the skill at runtime. Run it when Bambu Studio
updates its profiles or when you switch printer:

    git clone --depth 1 --filter=blob:none --sparse https://github.com/bambulab/BambuStudio bs
    git -C bs sparse-checkout set resources/profiles/BBL
    python tools/build_bambu_profiles.py --profiles bs/resources/profiles/BBL \
        --skeleton path/to/any_bambu_project.3mf [--model "Bambu Lab P1S"] [--nozzles 0.2,0.4,0.6,0.8]

For every nozzle it resolves the "inherits"/"include" chains of the machine, process
and filament presets compatible with "<model> <nozzle> nozzle" and writes, into
assets/bambu/nozzle_<d>/:

  base_project_settings.json  full project config: printer + default process
                              + one default filament slot
  presets.json                {"process": {...}, "filament": {...}} values
                              normalised to the standard extruder variant
  key_roles.json              which config keys belong to process / filament /
                              machine (make_3mf.py needs this)

--skeleton is a 3MF saved by Bambu Studio. Only its key layout and the
defaults for keys no preset defines are used; its printer is replaced.
"""
import argparse
import json
import os
import re
import zipfile

STD_VARIANT = "Direct Drive Standard"
# Keys stored once per extruder variant in system presets ("_2": twice, normal + silent mode).
# A project file keeps only the selected variant, exactly like Bambu Studio saves it.
VARIANT_KEYS = {
 "print_options_with_variant": [
  "bridge_speed",
  "default_acceleration",
  "enable_height_slowdown",
  "enable_overhang_speed",
  "gap_infill_speed",
  "initial_layer_acceleration",
  "initial_layer_infill_speed",
  "initial_layer_speed",
  "initial_layer_travel_acceleration",
  "inner_wall_acceleration",
  "inner_wall_speed",
  "internal_solid_infill_speed",
  "outer_wall_acceleration",
  "outer_wall_speed",
  "overhang_1_4_speed",
  "overhang_2_4_speed",
  "overhang_3_4_speed",
  "overhang_4_4_speed",
  "overhang_totally_speed",
  "print_extruder_id",
  "print_extruder_variant",
  "slowdown_end_acc",
  "slowdown_end_height",
  "slowdown_end_speed",
  "slowdown_start_acc",
  "slowdown_start_height",
  "slowdown_start_speed",
  "small_perimeter_speed",
  "small_perimeter_threshold",
  "sparse_infill_acceleration",
  "sparse_infill_speed",
  "support_interface_speed",
  "support_speed",
  "top_solid_infill_flow_ratio",
  "top_surface_acceleration",
  "top_surface_speed",
  "travel_acceleration",
  "travel_short_distance_acceleration",
  "travel_speed",
  "travel_speed_z",
  "vertical_shell_speed"
 ],
 "filament_options_with_variant": [
  "filament_adaptive_volumetric_speed",
  "filament_bridge_speed",
  "filament_cooling_before_tower",
  "filament_deretraction_speed",
  "filament_enable_overhang_speed",
  "filament_extruder_variant",
  "filament_flow_ratio",
  "filament_flush_temp",
  "filament_flush_volumetric_speed",
  "filament_long_retractions_when_cut",
  "filament_max_volumetric_speed",
  "filament_overhang_1_4_speed",
  "filament_overhang_2_4_speed",
  "filament_overhang_3_4_speed",
  "filament_overhang_4_4_speed",
  "filament_overhang_totally_speed",
  "filament_pre_cooling_temperature",
  "filament_pre_cooling_temperature_nc",
  "filament_ramming_travel_time",
  "filament_ramming_travel_time_nc",
  "filament_ramming_volumetric_speed",
  "filament_ramming_volumetric_speed_nc",
  "filament_retract_before_wipe",
  "filament_retract_length_nc",
  "filament_retract_restart_extra",
  "filament_retract_when_changing_layer",
  "filament_retraction_distances_when_cut",
  "filament_retraction_length",
  "filament_retraction_minimum_travel",
  "filament_retraction_speed",
  "filament_wipe",
  "filament_wipe_distance",
  "filament_z_hop",
  "filament_z_hop_types",
  "long_retractions_when_ec",
  "nozzle_temperature",
  "nozzle_temperature_initial_layer",
  "override_process_overhang_speed",
  "retraction_distances_when_ec",
  "slow_down_min_speed",
  "volumetric_speed_coefficients"
 ],
 "printer_options_with_variant_1": [
  "deretraction_speed",
  "hotend_cooling_rate",
  "hotend_heating_rate",
  "long_retractions_when_cut",
  "nozzle_flush_dataset",
  "nozzle_type",
  "nozzle_volume",
  "printer_extruder_id",
  "printer_extruder_variant",
  "retract_before_wipe",
  "retract_length_toolchange",
  "retract_lift_above",
  "retract_lift_below",
  "retract_restart_extra",
  "retract_restart_extra_toolchange",
  "retract_when_changing_layer",
  "retraction_distances_when_cut",
  "retraction_length",
  "retraction_minimum_travel",
  "retraction_speed",
  "wipe",
  "wipe_distance",
  "z_hop",
  "z_hop_types"
 ],
 "printer_options_with_variant_2": [
  "machine_max_acceleration_e",
  "machine_max_acceleration_extruding",
  "machine_max_acceleration_retracting",
  "machine_max_acceleration_travel",
  "machine_max_acceleration_x",
  "machine_max_acceleration_y",
  "machine_max_acceleration_z",
  "machine_max_jerk_e",
  "machine_max_jerk_x",
  "machine_max_jerk_y",
  "machine_max_jerk_z",
  "machine_max_speed_e",
  "machine_max_speed_x",
  "machine_max_speed_y",
  "machine_max_speed_z"
 ]
}  # from Bambu Studio PrintConfig.cpp (*_options_with_variant*)


class Profiles:
    def __init__(self, root):
        self.root = root
        self.cache = {}
        self.index = {}  # (kind, preset name) -> path; file names do not always match "name"
        for kind in ("machine", "process", "filament"):
            for dirpath, _, files in os.walk(os.path.join(root, kind)):
                for fn in files:
                    if fn.endswith(".json"):
                        path = os.path.join(dirpath, fn)
                        try:
                            with open(path, encoding="utf-8") as f:
                                name = json.load(f).get("name", fn[:-5])
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            continue
                        self.index[(kind, name)] = path

    def load(self, kind, name):
        key = (kind, name)
        if key not in self.cache:
            with open(self.index[key], encoding="utf-8") as f:
                self.cache[key] = json.load(f)
        return self.cache[key]

    def resolve(self, kind, name):
        chain, d = [], self.load(kind, name)
        chain.append(d)
        while d.get("inherits"):
            d = self.load(kind, d["inherits"])
            chain.append(d)
        out = {}
        for d in reversed(chain):
            for inc in d.get("include", []):
                out.update(self.load(kind, inc))
            out.update(d)
        for k in ("inherits", "include", "instantiation", "type", "from"):
            out.pop(k, None)
        return out

    def names(self, kind):
        return sorted(n for k, n in self.index if k == kind)


def variant_index(prof):
    variants = (prof.get("filament_extruder_variant") or prof.get("print_extruder_variant")
                or prof.get("printer_extruder_variant"))
    if isinstance(variants, list) and STD_VARIANT in variants:
        return variants.index(STD_VARIANT), len(variants)
    return 0, 1


def pick_variant(key, value, vidx, vcount):
    """Reduce a per-variant list to the selected variant, as Bambu writes it into a project."""
    if not isinstance(value, list) or vcount <= 1:
        return value
    if key in VARIANT_KEYS["printer_options_with_variant_2"] and len(value) == 2 * vcount:
        return value[2 * vidx:2 * vidx + 2]
    if key in VARIANT_KEYS["printer_options_with_variant_1"] or key in VARIANT_KEYS["print_options_with_variant"]:
        if len(value) == vcount:
            return [value[vidx]]
    return value


def norm_scalar_list(value, tpl_value, vidx, vcount, key=None):
    """Fit a preset value to the length the project file uses."""
    if key is not None:
        reduced = pick_variant(key, value, vidx, vcount)
        if reduced is not value:
            return reduced
    if not isinstance(value, list) or not isinstance(tpl_value, list):
        return value
    if len(value) == len(tpl_value):
        return value
    if len(tpl_value) == 1 and value:
        if vcount > 1 and len(value) == vcount:
            return [value[vidx]]
        return [value[0]]
    return value


def per_slot(value, vidx, vcount, chunk):
    """Value a filament preset gives for ONE slot, as a list of `chunk` items."""
    if not isinstance(value, list):
        return [value] * chunk
    if chunk == 1:
        if vcount > 1 and len(value) == vcount:
            return [value[vidx]]
        return [value[0]] if value else [""]
    if vcount > 1 and len(value) == vcount * chunk:
        return value[vidx * chunk:(vidx + 1) * chunk]
    v = list(value[:chunk])
    while len(v) < chunk:
        v.append(v[-1] if v else "")
    return v


def build(P, tpl, profiles_dir, printer, process, filament, bed_type, out, brands):
    n_tpl = len(tpl["filament_settings_id"])
    machine = P.resolve("machine", printer)
    m_vidx, m_vcount = variant_index(machine)
    process = process or machine.get("default_print_profile")
    if not filament:
        dflt = machine.get("default_filament_profile") or []
        filament = dflt[0] if isinstance(dflt, list) and dflt else dflt

    # compatible presets
    processes, filaments = {}, {}
    for name in P.names("process"):
        raw = P.load("process", name)
        if raw.get("instantiation") == "true" and printer in raw.get("compatible_printers", []):
            processes[name] = P.resolve("process", name)
    for name in P.names("filament"):
        raw = P.load("filament", name)
        if brands and not name.startswith(tuple(b + " " for b in brands)):
            continue
        if raw.get("instantiation") == "true" and printer in raw.get("compatible_printers", []):
            filaments[name] = P.resolve("filament", name)
    machine_keys = set(machine) - {"name", "setting_id", "compatible_printers"}
    process_keys = set().union(*[set(p) for p in processes.values()]) - {"name", "setting_id", "compatible_printers", "compatible_printers_condition"}
    filament_keys = set().union(*[set(f) for f in filaments.values()]) - {"name", "setting_id", "compatible_printers", "compatible_printers_condition", "filament_id"}

    # keys stored per filament slot even though no preset defines them
    slot_extra = {k for k, v in tpl.items()
                  if isinstance(v, list) and len(v) == n_tpl and k.startswith("filament_")} - filament_keys
    slot_extra |= {"default_filament_colour", "filament_ids", "filament_settings_id"}

    def chunk_of(k):
        v = tpl.get(k)
        if isinstance(v, list) and n_tpl and len(v) % n_tpl == 0 and len(v) >= n_tpl:
            return len(v) // n_tpl
        return 1

    # ---- base project settings: printer + default process + 1 filament slot
    base = dict(tpl)
    for k in machine_keys:
        if k in tpl:
            base[k] = norm_scalar_list(machine[k], tpl[k], m_vidx, m_vcount, k)
        else:
            base[k] = pick_variant(k, machine[k], m_vidx, m_vcount)
    proc = processes[process]
    p_vidx, p_vcount = variant_index(proc)
    for k in process_keys & set(proc):
        base[k] = norm_scalar_list(proc[k], tpl.get(k), p_vidx, p_vcount, k) if k in tpl else pick_variant(k, proc[k], p_vidx, p_vcount)
    base["printer_settings_id"] = printer
    base["print_settings_id"] = process
    base["default_print_profile"] = machine.get("default_print_profile", process)
    base["print_compatible_printers"] = proc.get("compatible_printers", [printer])
    base["inherits_group"] = []  # rebuilt by make_3mf
    for k in ("print_extruder_variant", "printer_extruder_variant"):
        base[k] = [STD_VARIANT]
    for k in ("print_extruder_id", "printer_extruder_id"):
        base[k] = ["1"]
    base["print_compatible_printers"] = [printer]
    # strip identity of whoever made the skeleton
    for k in list(base):
        if k.lower().startswith(("user_", "designer")):
            base.pop(k)

    def filament_slot_values(fname):
        f = filaments[fname]
        vidx, vcount = variant_index(f)
        vals = {}
        for k in filament_keys:
            if k in f:
                vals[k] = per_slot(f[k], vidx, vcount, chunk_of(k))
        vals["filament_settings_id"] = [fname]
        vals["filament_ids"] = [f.get("filament_id", "")]
        vals["filament_extruder_variant"] = [STD_VARIANT]
        return vals

    presets = {"process": {}, "filament": {}, "meta": {
        "printer": printer, "default_process": process, "default_filament": filament,
        "nozzle": float(machine.get("nozzle_diameter", ["0.4"])[0]),
        "profiles_version": json.load(open(os.path.join(profiles_dir, "..", "BBL.json"))).get("version", "?"),
    }}
    for name, p in processes.items():
        pv, pc = variant_index(p)
        presets["process"][name] = {k: (norm_scalar_list(p[k], tpl.get(k), pv, pc, k) if k in tpl else pick_variant(k, p[k], pv, pc))
                                    for k in process_keys & set(p)}
    for name in filaments:
        presets["filament"][name] = filament_slot_values(name)

    # collapse filament arrays in base to one slot of the default filament
    for k in list(filament_keys | slot_extra):
        if k in base and isinstance(base[k], list) and n_tpl and len(base[k]) == n_tpl * chunk_of(k):
            base[k] = base[k][:chunk_of(k)]
    for k, v in presets["filament"][filament].items():
        base[k] = v
    base["filament_colour"] = ["#FFFFFF"]
    base["curr_bed_type"] = bed_type

    roles = {
        "machine": sorted(machine_keys),
        "process": sorted(process_keys),
        "filament": sorted(filament_keys),
        "slot_extra": sorted(slot_extra),
        "slot_chunk": {k: chunk_of(k) for k in sorted(filament_keys | slot_extra) if chunk_of(k) != 1},
        "skeleton_app_version": tpl.get("version", ""),
    }

    os.makedirs(out, exist_ok=True)
    for fn, obj in (("base_project_settings.json", base), ("presets.json", presets), ("key_roles.json", roles)):
        with open(os.path.join(out, fn), "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=1, ensure_ascii=False, sort_keys=True)
    print(f"{printer}: {len(processes)} process presets (default {process}), {len(filaments)} filament presets")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profiles", required=True, help="BambuStudio/resources/profiles/BBL")
    ap.add_argument("--skeleton", required=True, help="any project .3mf saved by Bambu Studio")
    ap.add_argument("--model", default="Bambu Lab P1S", help="printer model as in the preset names")
    ap.add_argument("--nozzles", default="0.2,0.4,0.6,0.8")
    ap.add_argument("--brands", default="Bambu,Generic", help="filament preset brands to keep (empty = all)")
    ap.add_argument("--bed-type", default="Textured PEI Plate")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..",
                                                  "3d-print-modeling", "assets", "bambu"))
    a = ap.parse_args()
    with zipfile.ZipFile(a.skeleton) as z:
        tpl = json.loads(z.read("Metadata/project_settings.config"))
    P = Profiles(a.profiles)
    brands = [b for b in a.brands.split(",") if b]
    for n in a.nozzles.split(","):
        printer = f"{a.model} {n} nozzle"
        build(P, tpl, a.profiles, printer, None, None, a.bed_type, os.path.join(a.out, f"nozzle_{n}"), brands)


if __name__ == "__main__":
    main()
