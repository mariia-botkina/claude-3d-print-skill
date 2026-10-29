#!/usr/bin/env python3
"""Build a Bambu Studio project (.3mf) from a JSON spec: plates, layout, print
settings and AMS filament assignment, ready to open and slice.

  python make_3mf.py spec.json -o Project.3mf
  python make_3mf.py --example > spec.json        # annotated example spec
  python make_3mf.py --list-filaments [PLA]       # filament presets available
  python make_3mf.py --list-processes

Spec (JSON). Paths are relative to the spec file. Every key but "plates" is optional.

{
  "project": "Lantern",
  "nozzle": 0.4,                               # 0.2 | 0.4 | 0.6 | 0.8 (P1S presets for each)
  "process": "0.20mm Standard @BBL X1C",      # Bambu process preset (P1S uses the X1C ones); omit = nozzle's default
  "bed_type": "Textured PEI Plate",            # Cool Plate | Engineering Plate | High Temp Plate | Textured PEI Plate
  "filaments": [                               # AMS slots in order: slot 1, 2, ...
    {"preset": "Bambu PLA Basic", "color": "#F2F2F2", "label": "white"},
    {"preset": "Bambu PLA Basic", "color": "#1E1E1E", "label": "black"}
  ],
  "settings": {"wall_loops": 3, "sparse_infill_density": "20%"},   # project-wide overrides
  "plates": [
    {"name": "Body", "objects": [
      {"file": "body.stl", "name": "Body", "filament": 1,
       "rotate": [0, 0, 0],                     # degrees, applied before placing
       "copies": 1,
       "settings": {"enable_support": 1, "support_type": "tree(auto)"},   # per-object overrides
       "parts": [                              # optional extra volumes of the same object
         {"file": "text.stl", "filament": 2, "type": "normal_part"},       # multi-colour inlay
         {"file": "dense.stl", "type": "modifier_part", "settings": {"sparse_infill_density": "50%"}}
       ]}
    ]},
    {"name": "Small parts", "objects": [{"file": "clip.stl", "copies": 4}]},
    {"name": "Coaster", "objects": [{"file": "coaster.stl", "filament": 1}],
     "events": [                                # pauses and colour changes by height, per plate
       {"type": "pause", "z": 4.2, "note": "insert 10x3 magnet, N up"},   # z = pocket ceiling (find_pockets.py)
       {"type": "filament", "z": 5.6, "filament": 2}                      # from 5.6 mm up: slot 2
     ]}
  ],
  "pause_park": {"x": 65, "y": 245, "lift": 10}  # optional; where the head waits during pauses
}

Events: "z" is a height on the part; the event happens before the first layer that lies
entirely above it (snapped to the process' layer grid; the script prints the layer
number). "print_z" instead of "z" gives the exact Bambu layer top. Pauses lift the
nozzle, park the head and wait (M400 U1); colour changes switch the AMS slot for the
whole plate, so every object on such a plate must use a single filament.

Objects are placed in the orientation given (after "rotate"), dropped onto the
bed, and packed on their plate; objects that do not fit raise an error. Use
"plates": "auto" with a top-level "objects" list to let the script fill as
many plates as needed (then put events in a top-level "events" list with "plate": N). Extra parts ("parts") must already sit in the same
coordinate frame as the main file (export them from the same model).
"""
import argparse
import datetime
import io
import json
import math
import os
import sys
import uuid
import zipfile
from xml.sax.saxutils import escape as _escape

import numpy as np
import trimesh

HERE = os.path.dirname(os.path.abspath(__file__))


BAD_NAME_CHARS = '<>:/\\|?*"'


def safe_name(text):
    """Bambu Studio rejects names with < > : / \\ | ? * " (error "Invalid name"): replace them."""
    out = str(text)
    for ch, rep in ((":", " -"), ("/", "-"), ("\\", "-"), ("|", "-"), ("?", ""), ("*", ""),
                    ("<", "("), (">", ")"), ('"', "'")):
        out = out.replace(ch, rep)
    return " ".join(out.split())


# Patterns Bambu Studio accepts at 100% sparse infill (its top_surface_pattern list).
# Any other pattern with 100% makes Bambu Studio stop with "... doesn't support 100% density".
FULL_DENSITY_PATTERNS = {"concentric", "zig-zag", "monotonic", "monotonicline", "globalmonotonicline",
                         "alignedrectilinear", "hilbertcurve", "archimedeanchords", "octagramspiral"}
FULL_DENSITY_DEFAULT = "zig-zag"   # Bambu's "Rectilinear", what its own dialog switches to


def is_full_density(v):
    try:
        return float(str(v).strip().rstrip("%")) >= 100.0 - 1e-6
    except ValueError:
        return False


def fix_full_density(settings, inherited_pattern, where):
    """If settings set 100% infill with a pattern Bambu rejects at 100%, switch to rectilinear."""
    if "sparse_infill_density" not in settings or not is_full_density(settings["sparse_infill_density"]):
        return False
    pattern = settings.get("sparse_infill_pattern", inherited_pattern)
    if pattern in FULL_DENSITY_PATTERNS:
        return False
    settings["sparse_infill_pattern"] = FULL_DENSITY_DEFAULT
    print(f"note: {where}: 100% infill with '{pattern}' is rejected by Bambu Studio; "
          f"using rectilinear ({FULL_DENSITY_DEFAULT})", file=sys.stderr)
    return True


def escape(text, entities=None):
    """XML-escape for attribute values (quotes included)."""
    return _escape(str(text), {'"': "&quot;", **(entities or {})})

sys.path.insert(0, HERE)
from meshio_util import band_split, load_mesh, rotation_matrix_deg  # noqa: E402

BED = 256.0
PLATE_STRIDE = BED * 1.2          # Bambu lays plates out on a grid with 20% gaps
EXCLUDE = (0.0, 0.0, 18.0, 28.0)  # P1S: no-print corner (purge chute)
MARGIN = 6.0
GAP = 6.0
TOWER = (160.0, 205.0, 256.0, 256.0)  # area kept free for the prime tower on multi-filament plates
APP_VERSION = "02.06.00.51"

EXAMPLE = {
    "project": "Example",
    "process": "0.20mm Standard @BBL X1C",
    "bed_type": "Textured PEI Plate",
    "filaments": [{"preset": "Bambu PLA Basic", "color": "#F2F2F2", "label": "white"},
                  {"preset": "Bambu PLA Basic", "color": "#202020", "label": "black"}],
    "settings": {"wall_loops": 2, "sparse_infill_density": "15%", "brim_type": "auto_brim"},
    "plates": [{"name": "Main", "objects": [{"file": "part.stl", "name": "Part", "filament": 1,
                                             "settings": {"enable_support": 0}}]}],
}


# ------------------------------------------------------------------ profiles

def load_assets(nozzle=None):
    from meshio_util import nozzle_dir
    ASSETS = nozzle_dir(nozzle)
    with open(os.path.join(ASSETS, "base_project_settings.json"), encoding="utf-8") as f:
        base = json.load(f)
    with open(os.path.join(ASSETS, "presets.json"), encoding="utf-8") as f:
        presets = json.load(f)
    with open(os.path.join(ASSETS, "key_roles.json"), encoding="utf-8") as f:
        roles = json.load(f)
    return base, presets, roles


def find_filament(presets, name):
    """Accepts a full preset name or a short one ("Bambu PLA Basic"); picks the variant for this printer/nozzle."""
    fil = presets["filament"]
    if name in fil:
        return name
    same = [n for n in fil if n.split(" @")[0].lower() == name.lower()]
    if not same:
        same = [n for n in fil if n.lower().startswith(name.lower())]
    if not same:
        raise SystemExit(f"filament preset '{name}' not available for {presets['meta']['printer']}; try --list-filaments")
    model = presets["meta"]["printer"].replace("Bambu Lab ", "").split()[0]   # "P1S"
    for pref in (f"@BBL {model}", "@BBL X1C", "@BBL X1", "@BBL P1P"):
        hits = [n for n in same if pref in n]
        if hits:
            return sorted(hits, key=len)[0]
    if len({n.split(" @")[0] for n in same}) > 1:
        raise SystemExit(f"filament preset '{name}' is ambiguous: {sorted(same)[:8]}")
    return sorted(same, key=len)[0]


def find_process(presets, name):
    if name in presets["process"]:
        return name
    hits = [n for n in presets["process"] if n.lower().startswith(name.lower())]
    if len(hits) == 1:
        return hits[0]
    raise SystemExit(f"process preset '{name}' not found; options: {sorted(presets['process'])}")


def as_cfg(v):
    """Bambu stores every value as a string (or list of strings)."""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return [as_cfg(x) for x in v]
    return v


def build_project_settings(spec, base, presets, roles, n_plates):
    cfg = json.loads(json.dumps(base))
    proc_name = find_process(presets, spec.get("process", presets["meta"]["default_process"]))
    for k, v in presets["process"][proc_name].items():
        cfg[k] = v
    cfg["print_settings_id"] = proc_name

    fils = spec.get("filaments") or [{"preset": "Bambu PLA Basic", "color": "#FFFFFF"}]
    names = [find_filament(presets, f.get("preset", "Bambu PLA Basic")) for f in fils]
    n = len(names)
    slot_keys = set(roles["filament"]) | set(roles["slot_extra"])
    chunk = roles.get("slot_chunk", {})
    for k in slot_keys:
        c = chunk.get(k, 1)
        default = base.get(k)
        vals = []
        for i, nm in enumerate(names):
            pv = presets["filament"][nm].get(k)
            if pv is None:
                pv = (default[:c] if isinstance(default, list) and default else [default] * c)
            vals.extend(pv)
        if any(v is not None for v in vals):
            cfg[k] = vals
    colors = [f.get("color", "#FFFFFF").upper() for f in fils]
    cfg["filament_colour"] = colors
    cfg["filament_multi_colour"] = colors
    cfg["filament_colour_type"] = ["1"] * n
    cfg["filament_self_index"] = [str(i + 1) for i in range(n)]
    cfg["filament_map"] = ["1"] * n
    cfg["filament_nozzle_map"] = ["0"] * n
    cfg["filament_volume_map"] = ["0"] * n
    cfg["filament_is_mixed"] = ["0"] * n
    cfg["filament_mixed_components"] = [""] * n
    cfg["default_filament_colour"] = [""] * n
    flush = spec.get("flush_volume", 280)
    cfg["flush_volumes_matrix"] = [("0" if i == j else str(flush)) for i in range(n) for j in range(n)]
    cfg["flush_volumes_vector"] = ["140"] * (2 * n)
    cfg["wipe_tower_x"] = [str(TOWER[0] + 5)] * n_plates
    cfg["wipe_tower_y"] = [str(TOWER[1] + 5)] * n_plates
    cfg["enable_prime_tower"] = "1" if n > 1 else cfg.get("enable_prime_tower", "1")
    if spec.get("bed_type"):
        cfg["curr_bed_type"] = spec["bed_type"]

    # user overrides (project wide), recorded so Bambu shows them as modified
    changed_proc = []
    proj_settings = dict(spec.get("settings") or {})
    fix_full_density(proj_settings, cfg.get("sparse_infill_pattern"), "project settings")
    spec["settings"] = proj_settings
    for k, v in proj_settings.items():
        if k not in cfg:
            print(f"warning: setting '{k}' is not a known Bambu key; written anyway", file=sys.stderr)
        cfg[k] = as_cfg(v)
        if k in roles["process"]:
            changed_proc.append(k)
    fil_changed = []
    for i, f in enumerate(fils):
        changed = []
        for k, v in (f.get("settings") or {}).items():
            c = chunk.get(k, 1)
            arr = cfg.get(k)
            if isinstance(arr, list) and len(arr) >= (i + 1) * c:
                vv = as_cfg(v) if isinstance(v, list) else [as_cfg(v)] * c
                arr[i * c:(i + 1) * c] = vv
                changed.append(k)
        fil_changed.append(";".join(changed))
    cfg["different_settings_to_system"] = [";".join(changed_proc)] + fil_changed + [""]
    cfg.pop("inherits_group", None)  # Bambu Studio does not write it for system presets
    cfg["filament_settings_id"] = names
    return cfg, names, colors


# ------------------------------------------------------------------ geometry

class Obj:
    def __init__(self, name, parts, filament, settings):
        self.name = name
        self.parts = parts          # [(mesh, filament or None, subtype, name, settings)]
        self.filament = filament
        self.settings = settings or {}
        lo = np.min([p[0].bounds[0] for p in parts if p[2] == "normal_part"], axis=0)
        hi = np.max([p[0].bounds[1] for p in parts if p[2] == "normal_part"], axis=0)
        self.center = (lo + hi) / 2
        self.size = hi - lo
        self.pos = None   # plate-local x, y of the centre
        self.plate = None


def load_object(o, base_dir, idx):
    T = rotation_matrix_deg(*o.get("rotate", [0, 0, 0]))
    main = load_mesh(os.path.join(base_dir, o["file"]))
    main.apply_transform(T)
    if main.is_watertight and main.volume < 0:
        main.invert()
    name = o.get("name") or os.path.splitext(os.path.basename(o["file"]))[0]
    parts = [(main, o.get("filament"), "normal_part", name, {})]
    for p in o.get("parts", []):
        m = load_mesh(os.path.join(base_dir, p["file"]))
        m.apply_transform(T)
        parts.append((m, p.get("filament"), p.get("type", "normal_part"),
                      p.get("name") or os.path.splitext(os.path.basename(p["file"]))[0], p.get("settings", {})))
    objs = []
    for c in range(int(o.get("copies", 1))):
        nm = name if o.get("copies", 1) == 1 else f"{name} #{c + 1}"
        objs.append(Obj(nm, [(m.copy(), f, t, n, s) for (m, f, t, n, s) in parts], o.get("filament", 1), o.get("settings")))
    return objs


def rects_overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def pack(objs, keep_out):
    """Shelf packing inside the bed. Returns True if every object got a position."""
    if len(objs) == 1:
        o = objs[0]
        w, d = o.size[0], o.size[1]
        r = (BED / 2 - w / 2, BED / 2 - d / 2, BED / 2 + w / 2, BED / 2 + d / 2)
        if w <= BED - 2 * MARGIN and d <= BED - 2 * MARGIN and not any(rects_overlap(r, k) for k in keep_out):
            o.pos = (BED / 2, BED / 2)
            return True
    order = sorted(objs, key=lambda o: -o.size[1])
    x, y, row_h = MARGIN, MARGIN, 0.0
    placed = []
    for o in order:
        w, d = o.size[0], o.size[1]
        for _ in range(400):
            if x + w > BED - MARGIN:
                x, y, row_h = MARGIN, y + row_h + GAP, 0.0
            if y + d > BED - MARGIN:
                return False
            r = (x, y, x + w, y + d)
            blocker = next((k for k in keep_out + placed if rects_overlap(r, k)), None)
            if blocker is None:
                break
            x = blocker[2] + GAP
        else:
            return False
        o.pos = (x + w / 2, y + d / 2)
        placed.append((x - GAP / 2, y - GAP / 2, x + w + GAP / 2, y + d + GAP / 2))
        x += w + GAP
        row_h = max(row_h, d)
    # centre the whole group on the bed
    lo = np.min([[o.pos[0] - o.size[0] / 2, o.pos[1] - o.size[1] / 2] for o in objs], axis=0)
    hi = np.max([[o.pos[0] + o.size[0] / 2, o.pos[1] + o.size[1] / 2] for o in objs], axis=0)
    shift = (BED / 2 - (lo[0] + hi[0]) / 2, BED / 2 - (lo[1] + hi[1]) / 2)
    moved = [(o.pos[0] + shift[0], o.pos[1] + shift[1]) for o in objs]
    rects = [(p[0] - o.size[0] / 2, p[1] - o.size[1] / 2, p[0] + o.size[0] / 2, p[1] + o.size[1] / 2) for p, o in zip(moved, objs)]
    if all(r[0] >= MARGIN and r[1] >= MARGIN and r[2] <= BED - MARGIN and r[3] <= BED - MARGIN
           and not any(rects_overlap(r, k) for k in keep_out) for r in rects):
        for o, p in zip(objs, moved):
            o.pos = p
    return True


def plate_origin(i, n_plates):
    cols = max(1, math.ceil(math.sqrt(n_plates)))
    return ((i % cols) * PLATE_STRIDE, -(i // cols) * PLATE_STRIDE)


# ------------------------------------------------------------------ writing

def mesh_xml(mesh, oid, uid):
    v = np.asarray(mesh.vertices)
    f = np.asarray(mesh.faces)
    out = io.StringIO()
    out.write(f'  <object id="{oid}" p:UUID="{uid}" type="model">\n   <mesh>\n    <vertices>\n')
    for x, y, z in v:
        out.write(f'     <vertex x="{x:.6g}" y="{y:.6g}" z="{z:.6g}"/>\n')
    out.write('    </vertices>\n    <triangles>\n')
    for a, b, c in f:
        out.write(f'     <triangle v1="{a}" v2="{b}" v3="{c}"/>\n')
    out.write('    </triangles>\n   </mesh>\n  </object>\n')
    return out.getvalue()


def write_3mf(path, spec, objs, plates, cfg, names, colors, thumbs, extra_files=None):
    n_plates = len(plates)
    files = {}
    rels_obj, model_objs, build_items, settings_objs, assemble = [], [], [], [], []
    next_id = 1
    identify = 1000
    plate_instances = {i: [] for i in range(n_plates)}
    for k, o in enumerate(objs):
        part_ids = []
        sub_xml = []
        for (m, fil, subtype, pname, psettings) in o.parts:
            pid = next_id
            next_id += 1
            mm = m.copy()
            mm.apply_translation(-o.center)
            sub_xml.append(mesh_xml(mm, pid, str(uuid.uuid4())))
            part_ids.append(pid)
        oid = next_id
        next_id += 1
        obj_file = f"3D/Objects/object_{k + 1}.model"
        files[obj_file] = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
            'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
            'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p">\n'
            ' <metadata name="BambuStudio:3mfVersion">1</metadata>\n <resources>\n'
            + "".join(sub_xml) + ' </resources>\n <build/>\n</model>\n')
        rels_obj.append(obj_file)
        comps = "".join(
            f'    <component p:path="/{obj_file}" objectid="{pid}" p:UUID="{uuid.uuid4()}" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>\n'
            for pid in part_ids)
        model_objs.append(f'  <object id="{oid}" p:UUID="{uuid.uuid4()}" type="model">\n   <components>\n{comps}   </components>\n  </object>\n')
        ox, oy = plate_origin(o.plate, n_plates)
        tx, ty, tz = ox + o.pos[0], oy + o.pos[1], o.size[2] / 2
        tr = f"1 0 0 0 1 0 0 0 1 {tx:.6g} {ty:.6g} {tz:.6g}"
        build_items.append(f'  <item objectid="{oid}" p:UUID="{uuid.uuid4()}" transform="{tr}" printable="1"/>\n')
        assemble.append(f'   <assemble_item object_id="{oid}" instance_id="0" transform="{tr}" offset="0 0 0" />\n')

        fix_full_density(o.settings, cfg.get("sparse_infill_pattern"), f"object '{o.name}'")
        for (_, _, _, pname, psettings) in o.parts:
            if psettings:
                fix_full_density(psettings, o.settings.get("sparse_infill_pattern", cfg.get("sparse_infill_pattern")),
                                 f"part '{pname}'")
        meta = [f'    <metadata key="name" value="{escape(safe_name(o.name))}"/>\n',
                f'    <metadata key="extruder" value="{int(o.filament or 1)}"/>\n']
        for sk, sv in o.settings.items():
            meta.append(f'    <metadata key="{escape(sk)}" value="{escape(str(as_cfg(sv)))}"/>\n')
        parts_xml = []
        for pid, (m, fil, subtype, pname, psettings) in zip(part_ids, o.parts):
            pm = [f'      <metadata key="name" value="{escape(safe_name(pname))}"/>\n',
                  '      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>\n']
            if fil:
                pm.append(f'      <metadata key="extruder" value="{int(fil)}"/>\n')
            for sk, sv in (psettings or {}).items():
                pm.append(f'      <metadata key="{escape(sk)}" value="{escape(str(as_cfg(sv)))}"/>\n')
            parts_xml.append(f'    <part id="{pid}" subtype="{subtype}">\n' + "".join(pm) +
                             f'      <mesh_stat face_count="{len(m.faces)}" edges_fixed="0" degenerate_facets="0" facets_removed="0" facets_reversed="0" backwards_edges="0"/>\n    </part>\n')
        settings_objs.append(f'  <object id="{oid}">\n' + "".join(meta) + "".join(parts_xml) + '  </object>\n')
        identify += 1
        plate_instances[o.plate].append((oid, identify))

    today = datetime.date.today().isoformat()
    title = escape(safe_name(spec.get("project", "Project")))
    files["3D/3dmodel.model"] = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
        'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
        'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p">\n'
        f' <metadata name="Application">BambuStudio-{spec.get("app_version", APP_VERSION)}</metadata>\n'
        ' <metadata name="BambuStudio:3mfVersion">1</metadata>\n'
        f' <metadata name="Title">{title}</metadata>\n'
        f' <metadata name="CreationDate">{today}</metadata>\n'
        f' <metadata name="ModificationDate">{today}</metadata>\n'
        ' <resources>\n' + "".join(model_objs) + ' </resources>\n'
        f' <build p:UUID="{uuid.uuid4()}">\n' + "".join(build_items) + ' </build>\n</model>\n')
    files["3D/_rels/3dmodel.model.rels"] = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        + "".join(f' <Relationship Target="/{p}" Id="rel-{i + 1}" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n'
                  for i, p in enumerate(rels_obj))
        + '</Relationships>\n')

    plate_xml = []
    for i, pl in enumerate(plates):
        inst = "".join(
            '    <model_instance>\n'
            f'      <metadata key="object_id" value="{oid}"/>\n'
            '      <metadata key="instance_id" value="0"/>\n'
            f'      <metadata key="identify_id" value="{ident}"/>\n'
            '    </model_instance>\n' for oid, ident in plate_instances[i])
        thumb = (f'    <metadata key="thumbnail_file" value="Metadata/plate_{i + 1}.png"/>\n'
                 if f"Metadata/plate_{i + 1}.png" in thumbs else "")
        plate_xml.append(
            '  <plate>\n'
            f'    <metadata key="plater_id" value="{i + 1}"/>\n'
            f'    <metadata key="plater_name" value="{escape(safe_name(pl.get("name", "")))}"/>\n'
            '    <metadata key="locked" value="false"/>\n'
            '    <metadata key="filament_map_mode" value="Auto For Flush"/>\n'
            + thumb + inst + '  </plate>\n')
    files["Metadata/model_settings.config"] = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<config>\n' + "".join(settings_objs) + "".join(plate_xml)
        + '  <assemble>\n' + "".join(assemble) + '  </assemble>\n</config>\n')
    files["Metadata/project_settings.config"] = json.dumps(cfg, indent=4, ensure_ascii=False)
    files["Metadata/filament_sequence.json"] = json.dumps(
        {f"plate_{i + 1}": {"nozzle_sequence": [], "optimal_assignment": [], "sequence": []} for i in range(n_plates)})
    files["Metadata/slice_info.config"] = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<config>\n  <header>\n'
        '    <header_item key="X-BBL-Client-Type" value="slicer"/>\n'
        f'    <header_item key="X-BBL-Client-Version" value="{spec.get("app_version", APP_VERSION)}"/>\n'
        '  </header>\n</config>\n')
    files["[Content_Types].xml"] = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        ' <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        ' <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n'
        ' <Default Extension="png" ContentType="image/png"/>\n'
        ' <Default Extension="gcode" ContentType="text/x.gcode"/>\n</Types>\n')
    thumb_rel = ""
    if "Metadata/plate_1.png" in thumbs:
        thumb_rel = (' <Relationship Target="/Metadata/plate_1.png" Id="rel-2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail"/>\n'
                     ' <Relationship Target="/Metadata/plate_1.png" Id="rel-4" Type="http://schemas.bambulab.com/package/2021/cover-thumbnail-middle"/>\n'
                     ' <Relationship Target="/Metadata/plate_1.png" Id="rel-5" Type="http://schemas.bambulab.com/package/2021/cover-thumbnail-small"/>\n')
    files["_rels/.rels"] = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        ' <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n'
        + thumb_rel + '</Relationships>\n')

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", files.pop("[Content_Types].xml"))
        z.writestr("_rels/.rels", files.pop("_rels/.rels"))
        for name, data in files.items():
            z.writestr(name, data)
        for name, data in thumbs.items():
            z.writestr(name, data)
        for name, data in (extra_files or {}).items():
            z.writestr(name, data)


# ------------------------------------------------------------------ self-check

def verify_3mf(path):
    """Structural checks mirroring what Bambu Studio's loader needs. Returns a list of problems."""
    import re
    import xml.etree.ElementTree as ET
    ns = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02",
          "p": "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"}
    P = "{%s}" % ns["p"]
    probs = []
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        for need in ("[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model",
                     "Metadata/model_settings.config", "Metadata/project_settings.config"):
            if need not in names:
                probs.append(f"missing {need}")
        if probs:
            return probs
        root = ET.fromstring(z.read("3D/3dmodel.model"))
        app = [m.text for m in root.findall("m:metadata", ns) if m.get("name") == "Application"]
        if not app or not app[0].startswith("BambuStudio-"):
            probs.append("Application metadata is not BambuStudio-*: Bambu would ignore plates/settings")
        sub_ids = {}
        for fn in names:
            if fn.startswith("3D/Objects/") and fn.endswith(".model"):
                r = ET.fromstring(z.read(fn))
                for o in r.findall("m:resources/m:object", ns):
                    if o.find("m:mesh", ns) is None:
                        probs.append(f"{fn}: object {o.get('id')} has no mesh")
                    sub_ids[("/" + fn, o.get("id"))] = o
        main_ids, comp_ids = set(), {}
        for o in root.findall("m:resources/m:object", ns):
            oid = o.get("id")
            main_ids.add(oid)
            comp_ids[oid] = []
            for c in o.findall("m:components/m:component", ns):
                key = (c.get(P + "path"), c.get("objectid"))
                if key not in sub_ids:
                    probs.append(f"object {oid}: component {key} not found")
                comp_ids[oid].append(c.get("objectid"))
        for it in root.findall("m:build/m:item", ns):
            if it.get("objectid") not in main_ids:
                probs.append(f"build item points to missing object {it.get('objectid')}")
        cfg = ET.fromstring(z.read("Metadata/model_settings.config"))
        for o in cfg.findall("object"):
            oid = o.get("id")
            if oid not in main_ids:
                probs.append(f"model_settings object {oid} not in 3dmodel.model")
                continue
            parts = [pt.get("id") for pt in o.findall("part")]
            if parts != comp_ids[oid]:
                probs.append(f"object {oid}: part ids {parts} != component ids {comp_ids[oid]}")
        for m in cfg.iter("metadata"):
            if m.get("key") in ("name", "plater_name") and any(c in (m.get("value") or "") for c in BAD_NAME_CHARS):
                probs.append(f"name with a character Bambu rejects: {m.get('value')!r}")
        title = [m.text for m in root.findall("m:metadata", ns) if m.get("name") == "Title"]
        if title and any(c in (title[0] or "") for c in BAD_NAME_CHARS):
            probs.append(f"project title with a character Bambu rejects: {title[0]!r}")
        for pl in cfg.findall("plate"):
            for mi in pl.findall("model_instance"):
                oid = [m.get("value") for m in mi.findall("metadata") if m.get("key") == "object_id"]
                if oid and oid[0] not in main_ids:
                    probs.append(f"plate references missing object {oid[0]}")
            for m in pl.findall("metadata"):
                if m.get("key") == "thumbnail_file" and m.get("value") not in names:
                    probs.append(f"thumbnail {m.get('value')} missing")
        ps = json.loads(z.read("Metadata/project_settings.config"))
        gcode_keys = ("machine_pause_gcode", "machine_start_gcode", "machine_end_gcode", "change_filament_gcode",
                      "layer_change_gcode", "before_layer_change_gcode", "filament_start_gcode", "filament_end_gcode",
                      "time_lapse_gcode", "template_custom_gcode")
        diffs = ps.get("different_settings_to_system", [])
        for d in diffs[1:]:
            hit = [k for k in (d or "").split(";") if k in gcode_keys]
            if hit:
                probs.append(f"preset G-code changed ({', '.join(hit)}): Bambu Studio will warn about modified G-code")
        # Bambu reads these as plain strings; anything else aborts loading the whole config
        for k in ("version", "name", "from", "url", "type", "setting_id", "filament_id",
                  "description", "instantiation", "inherits"):
            if k in ps and not isinstance(ps[k], str):
                probs.append(f"project_settings '{k}' must be a string, got {type(ps[k]).__name__}: Bambu stops reading the settings there")
        n = len(ps.get("filament_settings_id", []))
        for k in ("filament_colour", "filament_type", "nozzle_temperature", "filament_ids"):
            if len(ps.get(k, [])) != n:
                probs.append(f"project_settings {k} has {len(ps.get(k, []))} entries for {n} filaments")
        if len(ps.get("flush_volumes_matrix", [])) not in (n * n, 0):
            probs.append("flush_volumes_matrix size does not match filament count")
        if "Metadata/custom_gcode_per_layer.xml" in names:
            cg = ET.fromstring(z.read("Metadata/custom_gcode_per_layer.xml"))
            n_pl = len(cfg.findall("plate"))
            if cg.tag != "custom_gcodes_per_layer":
                probs.append("custom_gcode_per_layer.xml has the wrong root element")
            for pl in cg.findall("plate"):
                info = pl.find("plate_info")
                if info is None or not 1 <= int(info.get("id", 0)) <= n_pl:
                    probs.append("custom gcode refers to a missing plate")
                for lay in pl.findall("layer"):
                    for att in ("top_z", "type", "extruder", "color", "extra"):
                        if lay.get(att) is None:
                            probs.append(f"custom gcode layer is missing '{att}'")
                    if int(lay.get("type", -1)) == 2 and int(lay.get("extruder", 0)) > n:
                        probs.append("filament change to an undefined filament")
                if pl.find("mode") is None:
                    probs.append("custom gcode plate has no mode")
                for lay in pl.findall("layer"):
                    code = (lay.get("extra") or "") + "\n" + (lay.get("gcode") or "")
                    cmds = [l.split(";")[0].strip().upper() for l in code.splitlines()]
                    if any(c.startswith(("G90", "G91", "M82")) for c in cmds):
                        probs.append(f"custom G-code at z {lay.get('top_z')} changes positioning mode (G90/G91/M82): "
                                     "on Bambu firmware this can leave the extruder in absolute mode and stop extrusion")
        if is_full_density(ps.get("sparse_infill_density", "")) and ps.get("sparse_infill_pattern") not in FULL_DENSITY_PATTERNS:
            probs.append(f"100% infill with pattern '{ps.get('sparse_infill_pattern')}': Bambu Studio rejects it")
        glob_pat = ps.get("sparse_infill_pattern")
        for o in cfg.findall("object"):
            meta = {m.get("key"): m.get("value") for m in o.findall("metadata")}
            for pt in [meta] + [{m.get("key"): m.get("value") for m in p.findall("metadata")} for p in o.findall("part")]:
                if is_full_density(pt.get("sparse_infill_density", "")):
                    pat = pt.get("sparse_infill_pattern", meta.get("sparse_infill_pattern", glob_pat))
                    if pat not in FULL_DENSITY_PATTERNS:
                        probs.append(f"object {o.get('id')}: 100% infill with pattern '{pat}': Bambu Studio rejects it")
        used = set()
        for o in cfg.findall("object"):
            for m in o.iter("metadata"):
                if m.get("key") == "extruder":
                    used.add(int(m.get("value")))
        if used and max(used) > n:
            probs.append(f"an object uses filament {max(used)} but only {n} are defined")
    return probs


# ------------------------------------------------------------------ layer events

PAUSE, TOOLCHANGE, CUSTOM = 1, 2, 4   # CustomGCode::Type in Bambu Studio
# Pauses are written as a per-layer custom G-code (type CUSTOM) that parks the head and waits.
# Overriding the printer's machine_pause_gcode instead makes Bambu Studio warn about
# "modified G-code" every time the project opens, and marks the printer preset as modified.
PARK_DEFAULT = {"x": 65, "y": 245, "lift": 10}  # back-left, where Bambu's own filament change parks
MAX_Z_SAFE = 250.0


def plate_filaments(objs, plate):
    used = set()
    for o in objs:
        if o.plate != plate:
            continue
        for (_, fil, subtype, _, _) in o.parts:
            if subtype == "normal_part":
                used.add(int(fil or o.filament or 1))
    return used


def resolve_events(spec, plates, objs, colors, n_fil):
    """Snap pause / filament-change events to Bambu's layer grid and validate them.
    Returns {plate_index: [event, ...]} with print_z, layer and the Bambu fields filled in."""
    from meshio_util import process_layers, snap_to_layer
    first, h, proc = process_layers(spec.get("process"), spec.get("nozzle"))
    out = {}
    for pi, pl in enumerate(plates):
        evs = []
        top = max([o.size[2] for o in objs if o.plate == pi] or [0])
        used = plate_filaments(objs, pi)
        for e in pl.get("events", []):
            kind = e.get("type")
            if "print_z" in e:
                pz = round(float(e["print_z"]), 4)
                k = round((pz - first) / h)
                if abs(first + k * h - pz) > 1e-3:
                    raise SystemExit(f"plate {pi + 1}: print_z {pz} is not on the {h} mm layer grid; use \"z\" instead")
                bottom, layer = round(pz - h, 4), k + 1
            else:
                pz, bottom, layer = snap_to_layer(float(e["z"]), first, h)
            if pz > top + 1e-6:
                raise SystemExit(f"plate {pi + 1}: {kind} at {pz} mm is above everything on the plate ({top:.2f} mm)")
            ev = {"type": kind, "print_z": pz, "bottom": bottom, "layer": layer, "note": e.get("note", "")}
            if kind == "pause":
                ev.update(code=CUSTOM, extruder=min(used or {1}), color="", gcode="pause")
            elif kind == "filament":
                f = int(e["filament"])
                if not 1 <= f <= n_fil:
                    raise SystemExit(f"plate {pi + 1}: filament change to slot {f}, but only {n_fil} filament(s) are defined")
                if len(used) > 1:
                    raise SystemExit(
                        f"plate {pi + 1}: height colour changes need every object on the plate to use one filament "
                        f"(this plate uses {sorted(used)}); move multi-colour objects to another plate")
                ev.update(code=TOOLCHANGE, extruder=f, color=colors[f - 1], gcode="tool_change")
            else:
                raise SystemExit(f"plate {pi + 1}: unknown event type '{kind}' (use pause or filament)")
            evs.append(ev)
        evs.sort(key=lambda x: x["print_z"])
        for a_, b_ in zip(evs, evs[1:]):
            if abs(a_["print_z"] - b_["print_z"]) < 1e-6:
                raise SystemExit(f"plate {pi + 1}: two events on the same layer ({a_['print_z']} mm)")
        if evs:
            if n_fil == 1:
                mode = "SingleExtruder"
            elif len(used) <= 1:
                mode = "MultiAsSingle"
            else:
                mode = "MultiExtruder"
            out[pi] = {"events": evs, "mode": mode}
    return out, (first, h, proc)


def pause_gcode(spec, events):
    """Settings for the per-layer park-and-wait G-code; the G-code itself is built per event
    by pause_block() because it uses the absolute Z of that layer."""
    park = dict(PARK_DEFAULT, **(spec.get("pause_park") or {}))
    pauses = [e for v in events.values() for e in v["events"] if e["type"] == "pause"]
    if not pauses:
        return None, None
    return park, {"x": park["x"], "y": park["y"], "lift": float(park["lift"])}


def pause_block(park, bottom_z, note=""):
    """Park-and-wait G-code inserted before the layer whose bottom is bottom_z.

    Only absolute XYZ moves and relative extrusion, exactly the modes Bambu's G-code runs in:
    no G90/G91 here, because on Bambu (Marlin-based) firmware G90 also switches the
    extruder to absolute mode, and the rest of the print then extrudes nothing.
    The next travel move of the slicer brings the nozzle back to the layer height."""
    lift_z = min(bottom_z + float(park["lift"]), MAX_Z_SAFE)
    lines = [
        f"; PAUSE: {' '.join(note.split())}" if note.strip() else "; PAUSE",
        "; lift, park at the back, wait for the user (3d-print-modeling skill)",
        "M400",
        "M83 ; relative extrusion, as in the rest of the file",
        "G1 E-0.8 F1800 ; retract so it does not ooze while parked",
        f"G1 Z{lift_z:.2f} F900",
        f"G1 X{float(park['x']):.0f} Y{float(park['y']):.0f} F12000",
        "M400 U1 ; pause, resume from the printer screen or the app",
        "G1 E0.8 F1800 ; undo the retract",
    ]
    return "\n".join(lines)


def custom_gcode_xml(events, pause_code):
    rows = ['<?xml version="1.0" encoding="utf-8"?>', "<custom_gcodes_per_layer>"]
    for pi in sorted(events):
        rows.append("<plate>")
        rows.append(f'<plate_info id="{pi + 1}"/>')
        for e in events[pi]["events"]:
            if e["type"] == "pause":
                code = pause_block(pause_code, e["bottom"], e["note"])
                extra, g = code, code
            else:
                extra, g = "", "tool_change"
            rows.append(f'<layer top_z="{e["print_z"]:g}" type="{e["code"]}" extruder="{e["extruder"]}" '
                        f'color="{escape(e["color"])}" extra="{escape(extra, {chr(10): "&#10;"})}" '
                        f'gcode="{escape(g, {chr(10): "&#10;"})}"/>')
        rows.append(f'<mode value="{events[pi]["mode"]}"/>')
        rows.append("</plate>")
    rows.append("</custom_gcodes_per_layer>")
    return "\n".join(rows) + "\n"


# ------------------------------------------------------------------ main

def assign_plates(spec, base_dir, has_multi):
    plates_spec = spec.get("plates", "auto")
    all_objs, plates = [], []
    if plates_spec == "auto":
        pending = []
        for i, o in enumerate(spec.get("objects", [])):
            pending += load_object(o, base_dir, i)
        while pending:
            plate_objs = []
            for o in list(pending):
                trial = plate_objs + [o]
                keep = [EXCLUDE] + ([TOWER] if has_multi(trial) else [])
                if pack(trial, keep):
                    plate_objs = trial
                    pending.remove(o)
            if not plate_objs:
                o = pending[0]
                raise SystemExit(f"'{o.name}' ({o.size[0]:.0f} x {o.size[1]:.0f} mm) does not fit on a {BED:.0f} mm plate")
            idx = len(plates)
            pack(plate_objs, [EXCLUDE] + ([TOWER] if has_multi(plate_objs) else []))
            for o in plate_objs:
                o.plate = idx
            plates.append({"name": f"Plate {idx + 1}",
                           "events": [e for e in spec.get("events", []) if int(e.get("plate", 1)) == idx + 1]})
            all_objs += plate_objs
    else:
        for pi, pl in enumerate(plates_spec):
            objs = []
            for i, o in enumerate(pl.get("objects", [])):
                objs += load_object(o, base_dir, i)
            keep = [EXCLUDE] + ([TOWER] if has_multi(objs) else [])
            if objs and not pack(objs, keep):
                raise SystemExit(f"plate '{pl.get('name', pi + 1)}' is too full: move objects to another plate")
            for o in objs:
                o.plate = pi
                if o.size[2] > BED:
                    raise SystemExit(f"'{o.name}' is {o.size[2]:.0f} mm tall, more than the {BED:.0f} mm build height")
            plates.append({"name": pl.get("name", f"Plate {pi + 1}"), "events": pl.get("events", [])})
            all_objs += objs
    return all_objs, plates


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", nargs="?")
    ap.add_argument("-o", "--out")
    ap.add_argument("--no-thumbnails", action="store_true")
    ap.add_argument("--example", action="store_true")
    ap.add_argument("--list-filaments", nargs="?", const="", metavar="FILTER")
    ap.add_argument("--list-processes", action="store_true")
    ap.add_argument("--nozzle", type=float, help="nozzle for --list-* (a spec sets its own \"nozzle\")")
    ap.add_argument("--verify", metavar="3MF", help="only run the structural self-check on an existing 3MF")
    a = ap.parse_args()

    if a.verify:
        probs = verify_3mf(a.verify)
        print("OK" if not probs else "\n".join(probs))
        sys.exit(1 if probs else 0)
    spec = None
    if a.spec and not (a.example or a.list_filaments is not None or a.list_processes):
        with open(a.spec, encoding="utf-8") as f:
            spec = json.load(f)
    base, presets, roles = load_assets(spec.get("nozzle") if spec else a.nozzle)
    if a.example:
        print(json.dumps(EXAMPLE, indent=2))
        return
    if a.list_filaments is not None:
        for n in sorted(presets["filament"]):
            if a.list_filaments.lower() in n.lower():
                print(n)
        return
    if a.list_processes:
        print("\n".join(sorted(presets["process"])))
        return
    if not a.spec or not a.out:
        ap.error("spec and -o are required")

    base_dir = os.path.dirname(os.path.abspath(a.spec))
    n_fil = len(spec.get("filaments") or [1])

    def has_multi(objs):
        used = set()
        for o in objs:
            for (_, fil, subtype, _, _) in o.parts:
                if subtype == "normal_part":
                    used.add(int(fil or o.filament or 1))
        return len(used) > 1

    objs, plates = assign_plates(spec, base_dir, has_multi)
    for o in objs:
        for (_, fil, _, _, _) in o.parts:
            if int(fil or o.filament or 1) > n_fil:
                raise SystemExit(f"'{o.name}' uses filament {fil or o.filament} but only {n_fil} filament slot(s) are defined")
    cfg, names, colors = build_project_settings(spec, base, presets, roles, len(plates))
    events, (first_h, layer_h, proc_name) = resolve_events(spec, plates, objs, colors, n_fil)
    extra_files, park = {}, None
    if events:
        park_cfg, park = pause_gcode(spec, events)
        extra_files["Metadata/custom_gcode_per_layer.xml"] = custom_gcode_xml(events, park_cfg or PARK_DEFAULT)

    thumbs = {}
    if not a.no_thumbnails:
        try:
            import tempfile
            from render import preview
            tmp = tempfile.mkdtemp(prefix="thumb_")
            for i in range(len(plates)):
                meshes, cols = [], []
                for o in objs:
                    if o.plate != i:
                        continue
                    for (m, fil, subtype, _, _) in o.parts:
                        if subtype != "normal_part":
                            continue
                        mm = m.copy()
                        mm.apply_translation(-o.center + [o.pos[0], o.pos[1], o.size[2] / 2])
                        start = int(fil or o.filament or 1)
                        cuts = [(e["bottom"], e["extruder"]) for e in events.get(i, {}).get("events", [])
                                if e["type"] == "filament"]
                        for piece, f in band_split(mm, start, cuts):
                            meshes.append(piece)
                            hexc = colors[f - 1].lstrip("#")
                            cols.append(np.array([int(hexc[j:j + 2], 16) / 255 for j in (0, 2, 4)]))
                if meshes:
                    p = os.path.join(tmp, f"plate_{i + 1}.png")
                    preview(meshes, p, views=["iso front"], colors=cols)
                    with open(p, "rb") as fh:
                        thumbs[f"Metadata/plate_{i + 1}.png"] = fh.read()
        except Exception as e:  # thumbnails are cosmetic; Bambu regenerates them on slicing
            print(f"thumbnails skipped: {e}", file=sys.stderr)

    write_3mf(a.out, spec, objs, plates, cfg, names, colors, thumbs, extra_files)
    problems = verify_3mf(a.out)
    if problems:
        print("3MF self-check FAILED:\n  " + "\n  ".join(problems), file=sys.stderr)
        sys.exit(1)
    print(f"wrote {a.out}: {presets['meta']['printer']}, {cfg['print_settings_id']}; {len(plates)} plate(s), {len(objs)} object(s), filaments: "
          + ", ".join(f"{i + 1}={n.split(' @')[0]} {c}" for i, (n, c) in enumerate(zip(names, colors))))
    for i, pl in enumerate(plates):
        names_on = [o.name for o in objs if o.plate == i]
        print(f"  plate {i + 1} '{pl['name']}': " + ", ".join(names_on))
        for e in events.get(i, {}).get("events", []):
            if e["type"] == "pause":
                print(f"    pause before layer {e['layer']} (print_z {e['print_z']} mm; everything below {e['bottom']} mm is done)"
                      + (f": {e['note']}" if e["note"] else ""))
            else:
                print(f"    from layer {e['layer']} ({e['bottom']} mm up): filament {e['extruder']} {e['color']}"
                      + (f" ({e['note']})" if e["note"] else ""))
    if events:
        print(f"  layers: {proc_name}, first layer {first_h} mm, then {layer_h} mm")
    if park:
        print(f"  pauses (custom G-code on the layer) lift the nozzle {park['lift']:.0f} mm above the layer, park the head at X{park['x']} Y{park['y']}, then wait (M400 U1)")


if __name__ == "__main__":
    main()
