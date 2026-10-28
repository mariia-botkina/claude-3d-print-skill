#!/usr/bin/env python3
"""Regenerate assets/bambu/*.json from Bambu Studio's system profiles.

Maintainer tool, not used by the skill at runtime. Run it when Bambu Studio
updates its profiles or when you switch printer:

    git clone --depth 1 --filter=blob:none --sparse https://github.com/bambulab/BambuStudio bs
    git -C bs sparse-checkout set resources/profiles/BBL
    python tools/build_bambu_profiles.py --profiles bs/resources/profiles/BBL \
        --skeleton path/to/any_bambu_project.3mf

It resolves the "inherits"/"include" chains of the machine, process and
filament presets compatible with --printer and writes:

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
    variants = prof.get("filament_extruder_variant") or prof.get("print_extruder_variant")
    if isinstance(variants, list) and STD_VARIANT in variants:
        return variants.index(STD_VARIANT), len(variants)
    return 0, 1


def norm_scalar_list(value, tpl_value, vidx, vcount):
    """Fit a preset value to the length the project file uses."""
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profiles", required=True, help="BambuStudio/resources/profiles/BBL")
    ap.add_argument("--skeleton", required=True, help="any project .3mf saved by Bambu Studio")
    ap.add_argument("--printer", default="Bambu Lab P1S 0.4 nozzle")
    ap.add_argument("--process", default="0.20mm Standard @BBL X1C")
    ap.add_argument("--filament", default="Bambu PLA Basic @BBL P1S 0.4 nozzle")
    ap.add_argument("--bed-type", default="Textured PEI Plate")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..",
                                                  "3d-print-modeling", "assets", "bambu"))
    a = ap.parse_args()

    with zipfile.ZipFile(a.skeleton) as z:
        tpl = json.loads(z.read("Metadata/project_settings.config"))
    n_tpl = len(tpl["filament_settings_id"])

    P = Profiles(a.profiles)
    machine = P.resolve("machine", a.printer)
    m_vidx, m_vcount = variant_index(machine)

    # compatible presets
    processes, filaments = {}, {}
    for name in P.names("process"):
        raw = P.load("process", name)
        if raw.get("instantiation") == "true" and a.printer in raw.get("compatible_printers", []):
            processes[name] = P.resolve("process", name)
    for name in P.names("filament"):
        raw = P.load("filament", name)
        if raw.get("instantiation") == "true" and a.printer in raw.get("compatible_printers", []):
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
            base[k] = norm_scalar_list(machine[k], tpl[k], m_vidx, m_vcount)
        else:
            base[k] = machine[k]
    proc = processes[a.process]
    for k in process_keys & set(proc):
        base[k] = norm_scalar_list(proc[k], tpl.get(k), m_vidx, m_vcount) if k in tpl else proc[k]
    base["printer_settings_id"] = a.printer
    base["print_settings_id"] = a.process
    base["default_print_profile"] = machine.get("default_print_profile", a.process)
    base["print_compatible_printers"] = proc.get("compatible_printers", [a.printer])
    base["inherits_group"] = []  # rebuilt by make_3mf
    for k in ("print_extruder_variant", "printer_extruder_variant"):
        if k in base:
            base[k] = [STD_VARIANT]
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
        "printer": a.printer, "default_process": a.process, "default_filament": a.filament,
        "profiles_version": json.load(open(os.path.join(a.profiles, "..", "BBL.json"))).get("version", "?"),
    }}
    for name, p in processes.items():
        presets["process"][name] = {k: (norm_scalar_list(p[k], tpl.get(k), m_vidx, m_vcount) if k in tpl else p[k])
                                    for k in process_keys & set(p)}
    for name in filaments:
        presets["filament"][name] = filament_slot_values(name)

    # collapse filament arrays in base to one slot of the default filament
    for k in list(filament_keys | slot_extra):
        if k in base and isinstance(base[k], list) and n_tpl and len(base[k]) == n_tpl * chunk_of(k):
            base[k] = base[k][:chunk_of(k)]
    for k, v in presets["filament"][a.filament].items():
        base[k] = v
    base["filament_colour"] = ["#FFFFFF"]
    base["curr_bed_type"] = a.bed_type

    roles = {
        "machine": sorted(machine_keys),
        "process": sorted(process_keys),
        "filament": sorted(filament_keys),
        "slot_extra": sorted(slot_extra),
        "slot_chunk": {k: chunk_of(k) for k in sorted(filament_keys | slot_extra) if chunk_of(k) != 1},
        "skeleton_app_version": tpl.get("version", ""),
    }

    os.makedirs(a.out, exist_ok=True)
    for fn, obj in (("base_project_settings.json", base), ("presets.json", presets), ("key_roles.json", roles)):
        with open(os.path.join(a.out, fn), "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=1, ensure_ascii=False, sort_keys=True)
    print(f"process presets: {len(processes)}, filament presets: {len(filaments)}")
    print("filaments:", ", ".join(sorted(re.sub(r" @.*", "", n) for n in filaments)))


if __name__ == "__main__":
    main()
