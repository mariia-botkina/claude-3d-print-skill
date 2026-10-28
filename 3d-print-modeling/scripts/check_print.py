#!/usr/bin/env python3
"""Printability check for FDM (defaults: Bambu Lab P1S, 0.4 mm nozzle, 0.2 mm layers).

Checks the model in the orientation it will be printed (Z up, as given):

  mesh      closed surface, consistent normals, self-intersections, stray shells
  size      fits the build volume (and the P1S no-print corner)
  layers    slices the part like a slicer would and finds
            - islands: areas that start in mid-air (need support)
            - overhangs steeper than --overhang deg, grouped into regions,
              with bridges told apart from cantilevers where possible
            - features too thin for the nozzle (< 1 line) or weak (< 2 lines)
            - thin horizontal plates (< 3 layers)
  stability first-layer contact, tall slender sections, tipping risk
  orient    (--orient) ranks candidate orientations by overhang/contact/height

Usage:
  python check_print.py part.stl [more files] [--material PLA] [--rotate RX RY RZ]
                        [--orient] [--json report.json] [-D name=value ...]

Messages are terse English; explain them to the user in their language.
Exit code: 0 = no errors, 1 = at least one ERROR, 2 = could not load a file.
"""
import argparse
import json
import math
import os
import sys
import time

import numpy as np
import trimesh

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from meshio_util import drop_to_bed, load_mesh, printer_defaults, rotation_matrix_deg  # noqa: E402

try:
    from shapely.geometry import MultiPolygon, Polygon, box
    from shapely.ops import unary_union
except ImportError:  # pragma: no cover
    sys.exit("shapely missing: run scripts/setup.sh")

ERROR, WARN, INFO = "ERROR", "WARN", "INFO"


class Report:
    def __init__(self, name):
        self.name = name
        self.checks = []
        self.stats = {}

    def add(self, cid, severity, msg, **data):
        self.checks.append({"id": cid, "severity": severity, "message": msg, **({"data": data} if data else {})})

    def worst(self):
        order = {ERROR: 2, WARN: 1, INFO: 0}
        return max((order[c["severity"]] for c in self.checks), default=-1)


# ---------------------------------------------------------------- mesh sanity

def check_mesh(mesh, rep):
    if len(mesh.faces) == 0:
        rep.add("empty", ERROR, "mesh has no triangles")
        return False
    if not mesh.is_watertight:
        rep.add("not_watertight", ERROR,
                "surface is not closed (holes or open edges); slicers may drop or fill parts unpredictably")
    if not mesh.is_winding_consistent:
        rep.add("winding", WARN, "face orientation is inconsistent (some normals flipped)")
    elif mesh.is_watertight and mesh.volume < 0:
        rep.add("inverted", WARN, "normals point inwards (negative volume); fix with mesh.invert()")
    degenerate = int((mesh.area_faces < 1e-10).sum())
    if degenerate:
        rep.add("degenerate", INFO, f"{degenerate} zero-area triangles")

    bodies = mesh.split(only_watertight=False)
    rep.stats["bodies"] = len(bodies)
    tiny = [b for b in bodies if (b.extents.max() < 1.0) or (b.is_watertight and abs(b.volume) < 0.5)]
    if tiny:
        rep.add("debris", WARN, f"{len(tiny)} tiny separate shell(s) under 1 mm: probably modelling debris",
                centers=[np.round(b.bounds.mean(axis=0), 1).tolist() for b in tiny[:10]])
    if len(bodies) > 1:
        rep.add("multi_body", INFO, f"{len(bodies)} separate bodies in one file (fine if intended, e.g. a print-in-place set)")

    try:
        import manifold3d
        mm = manifold3d.Manifold(manifold3d.Mesh(
            vert_properties=np.asarray(mesh.vertices, dtype=np.float32),
            tri_verts=np.asarray(mesh.faces, dtype=np.uint32)))
        status = mm.status()
        if str(status) not in ("Error.NoError", "NoError"):
            rep.add("non_manifold", WARN, f"manifold check failed: {status} (non-manifold edges or self-touching geometry)")
    except ImportError:
        pass
    except Exception as e:  # manifold3d raises on badly broken meshes
        rep.add("non_manifold", WARN, f"manifold check failed: {e}")
    return True


def check_size(mesh, rep, P):
    ext = mesh.extents
    rep.stats["size_mm"] = [round(float(x), 2) for x in ext]
    bx, by, bz = P["bed_x"], P["bed_y"], P["bed_z"]
    if ext[2] > bz:
        rep.add("too_tall", ERROR, f"height {ext[2]:.1f} mm exceeds build height {bz:.0f} mm")
    fits_xy = (ext[0] <= bx and ext[1] <= by) or (ext[1] <= bx and ext[0] <= by)
    if not fits_xy:
        rep.add("too_big", ERROR, f"footprint {ext[0]:.1f} x {ext[1]:.1f} mm does not fit the {bx:.0f} x {by:.0f} mm bed; split the part")
    elif max(ext[0], ext[1]) > bx - 2 * 5:
        rep.add("near_bed_limit", WARN, "footprint is within 5 mm of the bed edge; brim/skirt may not fit, check the no-print corner")


# ---------------------------------------------------------------- layer analysis

def to_polys(geom):
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return list(geom.geoms)
    return [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]


def layer_polygons(mesh, z_values):
    sections = mesh.section_multiplane(plane_origin=[0, 0, 0], plane_normal=[0, 0, 1], heights=list(z_values))
    out = []
    for sec in sections:
        if sec is None:
            out.append(None)
            continue
        try:
            polys = [p.buffer(0) for p in sec.polygons_full]
            # section_multiplane returns 2D coords in the plane frame; for a Z plane at origin this is world XY
            out.append(unary_union(polys) if polys else None)
        except Exception:
            out.append(None)
    return out


class RegionTracker:
    """Groups per-layer 2D problem patches into 3D regions across consecutive layers."""

    def __init__(self):
        self.regions = []

    def add(self, z, geom, gap):
        for poly in to_polys(geom):
            if poly.area <= 0:
                continue
            hit = None
            for r in self.regions:
                if r["z_end"] >= z - gap * 1.5 and r["last"].distance(poly) < 0.5:
                    hit = r
                    break
            if hit is None:
                hit = {"z_start": z, "z_end": z, "area_sum": 0.0, "max_area": 0.0, "bounds": list(poly.bounds),
                       "last": poly, "layers": 0}
                self.regions.append(hit)
            hit["z_end"] = z
            hit["area_sum"] += poly.area
            hit["max_area"] = max(hit["max_area"], poly.area)
            b = poly.bounds
            hb = hit["bounds"]
            hit["bounds"] = [min(hb[0], b[0]), min(hb[1], b[1]), max(hb[2], b[2]), max(hb[3], b[3])]
            hit["last"] = poly
            hit["layers"] += 1

    def summary(self, step, min_area=0.0):
        out = []
        for r in self.regions:
            if r["max_area"] < min_area:
                continue
            b = r["bounds"]
            out.append({
                "z_mm": [round(r["z_start"], 2), round(r["z_end"], 2)],
                "xy_bounds_mm": [round(v, 1) for v in b],
                "size_mm": [round(b[2] - b[0], 1), round(b[3] - b[1], 1)],
                "layers": r["layers"],
                "area_mm2": round(r["area_sum"], 1),
                "max_layer_area_mm2": round(r["max_area"], 2),
            })
        out.sort(key=lambda r: -r["area_mm2"])
        return out


def supported_pieces(diff_poly, prev, tol):
    """How many separate edges of an overhang patch rest on the previous layer."""
    edge = diff_poly.boundary.intersection(prev.buffer(tol))
    if edge.is_empty:
        return [], edge
    parts = list(getattr(edge, "geoms", [edge]))
    merged = unary_union([p.buffer(tol) for p in parts])
    return to_polys(merged), edge


def analyse_layers(mesh, rep, P, overhang_deg, bridge_max):
    layer = P["layer"]
    nozzle = P["nozzle"]
    top = float(mesh.bounds[1][2])
    n = int(math.ceil(top / layer))
    step = layer
    if n > 900:  # keep big parts fast: coarser sampling, results stay indicative
        step = top / 900
        rep.add("coarse_layers", INFO, f"tall part: analysed every {step:.2f} mm instead of every layer")
    zs = np.arange(step / 2, top, step)
    t0 = time.time()
    layers = layer_polygons(mesh, zs)

    max_offset = step * math.tan(math.radians(overhang_deg))
    islands, thin_print, thin_weak = [], RegionTracker(), RegionTracker()
    overhangs, bridges = RegionTracker(), []
    prev = None
    areas = []
    for i, (z, cur) in enumerate(zip(zs, layers)):
        a = cur.area if cur is not None else 0.0
        areas.append(a)
        if cur is None or cur.is_empty:
            prev = cur
            continue
        if i == 0:
            rep.stats["first_layer_area_mm2"] = round(a, 1)
        else:
            if prev is None or prev.is_empty:
                if i > 0:
                    for p in to_polys(cur):
                        islands.append({"z_mm": round(float(z), 2), "area_mm2": round(p.area, 2),
                                        "center_mm": [round(p.centroid.x, 1), round(p.centroid.y, 1)]})
            else:
                floating = []
                for p in to_polys(cur):
                    if p.area > 0.05 and not p.intersects(prev):
                        floating.append(p)
                        islands.append({"z_mm": round(float(z), 2), "area_mm2": round(p.area, 2),
                                        "center_mm": [round(p.centroid.x, 1), round(p.centroid.y, 1)]})
                diff = cur.difference(prev.buffer(max_offset))
                if floating:
                    diff = diff.difference(unary_union(floating).buffer(0.01))
                # ignore slivers thinner than a line: they print fine as part of the perimeter
                diff = diff.buffer(-nozzle / 2).buffer(nozzle / 2)
                for dp in to_polys(diff):
                    if dp.area < 0.5:
                        continue
                    pieces, _ = supported_pieces(dp, prev, nozzle)
                    if len(pieces) >= 2:
                        span = max(a.distance(b) for k, a in enumerate(pieces) for b in pieces[k + 1:])
                        bridges.append({"z_mm": round(float(z), 2), "span_mm": round(span, 1),
                                        "area_mm2": round(dp.area, 1),
                                        "center_mm": [round(dp.centroid.x, 1), round(dp.centroid.y, 1)]})
                    else:
                        overhangs.add(float(z), dp, step)
        # thin features: what disappears after an opening by r
        too_thin = None
        for r, tracker in ((nozzle / 2 * 0.95, thin_print), (nozzle * 0.95, thin_weak)):
            opened = cur.buffer(-r).buffer(r)
            lost = cur.difference(opened.buffer(0.01))
            if too_thin is not None and not too_thin.is_empty:
                lost = lost.difference(too_thin.buffer(0.05))
            lost = unary_union([p for p in to_polys(lost) if p.area > 0.02])
            if too_thin is None:
                too_thin = lost
            if not lost.is_empty:
                tracker.add(float(z), lost, step)
        prev = cur
    rep.stats["layer_analysis_s"] = round(time.time() - t0, 1)

    # islands
    if islands:
        big = [x for x in islands if x["area_mm2"] >= 0.3]
        if big:
            rep.add("islands", ERROR,
                    f"{len(big)} area(s) start in mid-air (nothing below): need supports, a different orientation, or a 45 deg chamfer under them",
                    islands=big[:20])

    # flat ceilings hanging from one side (layer based); sloped overhangs come from face normals
    oh = overhangs.summary(step, min_area=1.0)
    flat_big = [r for r in oh if r["layers"] <= 2 and r["max_layer_area_mm2"] > 4]
    if flat_big:
        rep.add("flat_ceilings", WARN,
                f"{len(flat_big)} unsupported ledge(s)/ceiling(s) hanging from one side, largest {flat_big[0]['size_mm'][0]} x {flat_big[0]['size_mm'][1]} mm at z {flat_big[0]['z_mm'][0]}: needs support or a 45 deg chamfer/gusset under it",
                regions=flat_big[:10])

    # bridges
    if bridges:
        long_b = [b for b in bridges if b["span_mm"] > bridge_max]
        if long_b:
            rep.add("long_bridges", WARN,
                    f"{len(long_b)} bridge layer(s) longer than {bridge_max:.0f} mm (max {max(b['span_mm'] for b in long_b)} mm): expect sagging",
                    bridges=sorted(long_b, key=lambda b: -b["span_mm"])[:10])
        else:
            rep.add("bridges", INFO, f"{len(bridges)} short bridge layer(s), longest {max(b['span_mm'] for b in bridges)} mm: fine")

    # thin features
    # tiny wedges at acute corners (letters, sharp tips) are normal: only report thin areas that are
    # long enough to matter
    def long_enough(r):
        return max(r["size_mm"]) >= 1.5
    tp = [r for r in thin_print.summary(step, min_area=0.05) if long_enough(r)]
    if tp:
        rep.add("too_thin", ERROR,
                f"features thinner than one line ({nozzle:.2f} mm) in {len(tp)} region(s): the slicer will drop them",
                regions=tp[:15])
    tw = [r for r in thin_weak.summary(step, min_area=0.1) if long_enough(r) and r["area_mm2"] >= 2]
    if tw:
        rep.add("thin_walls", WARN,
                f"walls/features under {2 * nozzle:.1f} mm (fewer than 2 lines) in {len(tw)} region(s): fragile, may print gappy",
                regions=tw[:15])

    # stability
    areas = np.array(areas)
    rep.stats["max_layer_area_mm2"] = round(float(areas.max()) if len(areas) else 0.0, 1)
    first = areas[0] if len(areas) else 0.0
    hull = trimesh.path.polygons.projected(mesh, normal=[0, 0, 1])
    footprint = hull.convex_hull.area if hull is not None else first
    rep.stats["footprint_mm2"] = round(float(footprint), 1)
    h = mesh.extents[2]
    if first < 1e-6:
        rep.add("no_contact", ERROR, "nothing touches the bed in the first layer")
    else:
        contact_ratio = first / max(footprint, 1e-6)
        slender = h / math.sqrt(first)
        if first < 30 or contact_ratio < 0.1 or slender > 6:
            rep.add("adhesion", WARN,
                    f"small first-layer contact ({first:.0f} mm2, {contact_ratio * 100:.0f}% of the footprint, height/base ratio {slender:.1f}): risk of detaching or tipping; consider a brim or another orientation")
    # slender necks high up
    if len(areas) > 10:
        upper = areas[int(len(areas) * 0.2):]
        idx = np.where((upper > 0) & (upper < 8.0))[0]
        if len(idx) and h > 20:
            z_neck = zs[int(len(areas) * 0.2) + idx[0]]
            rep.add("slender", WARN, f"section narrower than ~3 x 3 mm at z {z_neck:.1f} mm on a {h:.0f} mm tall part: may wobble or snap")


def check_sloped_overhangs(mesh, rep, P, overhang_deg):
    """Faces steeper than the limit, grouped into connected regions (horizontal ceilings excluded:
    the layer analysis handles those as bridges/ledges/islands)."""
    nz = mesh.face_normals[:, 2]
    zmin = mesh.bounds[0][2]
    limit = -math.sin(math.radians(90 - overhang_deg - 0.5))  # a designed 45 deg chamfer passes
    near_bed = mesh.triangles[:, :, 2].max(axis=1) < zmin + P["layer"] * 1.5
    mask = (nz < limit) & (nz >= -0.985) & ~near_bed
    idx = np.where(mask)[0]
    if len(idx) == 0:
        return
    adj = mesh.face_adjacency
    keep = mask[adj[:, 0]] & mask[adj[:, 1]]
    comps = trimesh.graph.connected_components(adj[keep], nodes=idx, min_len=1)
    regions = []
    for c in comps:
        c = np.asarray(c)
        area = float(mesh.area_faces[c].sum())
        if area < 2.0:
            continue
        tri = mesh.triangles[c]
        lo, hi = tri.reshape(-1, 3).min(axis=0), tri.reshape(-1, 3).max(axis=0)
        steep = float(np.degrees(np.arccos(np.clip(-nz[c].min(), -1, 1))))  # 0 = flat ceiling
        regions.append({"area_mm2": round(area, 1), "worst_angle_from_vertical_deg": round(90 - steep, 0),
                        "z_mm": [round(float(lo[2]), 1), round(float(hi[2]), 1)],
                        "xy_bounds_mm": [round(float(v), 1) for v in (lo[0], lo[1], hi[0], hi[1])]})
    if not regions:
        return
    regions.sort(key=lambda r: -r["area_mm2"])
    total = sum(r["area_mm2"] for r in regions)
    sev = WARN if regions[0]["area_mm2"] > 20 else INFO
    rep.add("overhangs", sev,
            f"{len(regions)} sloped overhang region(s) steeper than {overhang_deg:.0f} deg from vertical, {total:.0f} mm2 in total; largest {regions[0]['area_mm2']} mm2 up to {regions[0]['worst_angle_from_vertical_deg']:.0f} deg at z {regions[0]['z_mm'][0]}-{regions[0]['z_mm'][1]}",
            regions=regions[:15])


def check_thin_plates(mesh, rep, P, samples=3000):
    """Thickness of near-horizontal skins, measured with rays through the part."""
    layer = P["layer"]
    nz = mesh.face_normals[:, 2]
    flat = np.where(np.abs(nz) > 0.95)[0]
    if len(flat) == 0 or not mesh.is_watertight:
        return
    w = mesh.area_faces[flat]
    if w.sum() <= 0:
        return
    rng = np.random.default_rng(1)
    pick = rng.choice(flat, size=min(samples, max(200, len(flat) * 3)), p=w / w.sum())
    bary = rng.dirichlet([1, 1, 1], size=len(pick))
    tri = mesh.triangles[pick]
    pts = (tri * bary[:, :, None]).sum(axis=1)
    dirs = -mesh.face_normals[pick]
    origins = pts + dirs * 1e-3
    locs, ray_idx, tri_idx = mesh.ray.intersects_location(origins, dirs, multiple_hits=False)
    if len(ray_idx) == 0:
        return
    d = np.linalg.norm(locs - origins[ray_idx], axis=1)
    # only parallel skins count; a ray running into a slanted side near a sharp edge is not a "plate"
    facing = (mesh.face_normals[pick[ray_idx]] * mesh.face_normals[tri_idx]).sum(axis=1) < -0.95
    thin = (d < 3 * layer - 0.02) & facing
    if thin.any():
        p = pts[ray_idx][thin]
        sev = ERROR if (d[thin] < layer * 0.9).any() else WARN
        rep.add("thin_plates", sev,
                f"horizontal skin thinner than {3 * layer:.1f} mm (3 layers) in places, min {d[thin].min():.2f} mm: weak or see-through",
                sample_points=np.round(p[:10], 1).tolist())


# ---------------------------------------------------------------- orientation

def orientation_metrics(mesh, overhang_deg):
    m = drop_to_bed(mesh)
    nz = m.face_normals[:, 2]
    zmin = m.bounds[0][2]
    on_bed = (m.triangles[:, :, 2].max(axis=1) - zmin) < 0.05
    limit = -math.sin(math.radians(90 - overhang_deg))  # normal z below this = too steep
    over = (nz < limit) & ~on_bed
    contact = on_bed & (nz < -0.99)
    return {
        "overhang_mm2": round(float(m.area_faces[over].sum()), 1),
        "contact_mm2": round(float(m.area_faces[contact].sum()), 1),
        "height_mm": round(float(m.extents[2]), 1),
    }


def candidate_orientations(mesh, overhang_deg, top=4):
    cands = []
    for r in [(0, 0, 0), (180, 0, 0), (90, 0, 0), (-90, 0, 0), (0, 90, 0), (0, -90, 0)]:
        cands.append(("axis", r, rotation_matrix_deg(*r)))
    try:
        hull = mesh.convex_hull
        transforms, probs = trimesh.poses.compute_stable_poses(hull, n_samples=1, threshold=0.02)
        for T, p in list(zip(transforms, probs))[:6]:
            e = np.degrees(trimesh.transformations.euler_from_matrix(T, "sxyz"))
            cands.append(("stable", tuple(round(float(x), 1) for x in e), T))
    except Exception:
        pass
    seen, out = set(), []
    for kind, r, T in cands:
        m = mesh.copy()
        m.apply_transform(T)
        met = orientation_metrics(m, overhang_deg)
        key = (round(met["overhang_mm2"]), round(met["contact_mm2"]), round(met["height_mm"]))
        if key in seen:
            continue
        seen.add(key)
        # simple score: support area dominates, then contact, then height (time)
        score = met["overhang_mm2"] - 0.3 * met["contact_mm2"] + 0.5 * met["height_mm"]
        out.append({"rotate_xyz_deg": [round(float(x), 1) for x in r], "source": kind, **met, "score": round(score, 1)})
    out.sort(key=lambda x: x["score"])
    return out[:top]


# ---------------------------------------------------------------- main

def check_file(path, args, P):
    rep = Report(os.path.basename(path))
    defines = dict(kv.split("=", 1) for kv in (args.define or []))
    try:
        mesh = load_mesh(path, scad_defines=defines)
    except Exception as e:
        rep.add("load", ERROR, f"cannot load: {e}")
        return rep, None
    if args.rotate:
        mesh.apply_transform(rotation_matrix_deg(*args.rotate))
    if not check_mesh(mesh, rep):
        return rep, mesh
    # keep the model's own XY so reported coordinates match the source; only put it on the bed
    mesh.apply_translation([0, 0, -mesh.bounds[0][2]])
    check_size(mesh, rep, P)
    vol = abs(mesh.volume) / 1000.0 if mesh.is_watertight else None
    if vol is not None:
        rep.stats["volume_cm3"] = round(vol, 2)
        dens = P["density"].get(args.material.upper().split()[0], 1.24)
        rep.stats["mass_solid_g"] = round(vol * dens, 1)
    if mesh.is_watertight:
        analyse_layers(mesh, rep, P, args.overhang, args.bridge_max)
        check_sloped_overhangs(mesh, rep, P, args.overhang)
        check_thin_plates(mesh, rep, P)
    else:
        rep.add("layers_skipped", INFO, "layer analysis skipped until the surface is closed")
    if args.orient:
        rep.stats["orientation_candidates"] = candidate_orientations(mesh, args.overhang)
    return rep, mesh


def print_report(rep):
    tag = {ERROR: "[ERROR]", WARN: "[WARN] ", INFO: "[info] "}
    worst = rep.worst()
    verdict = {2: "NOT READY", 1: "PRINTABLE WITH CAVEATS", 0: "OK", -1: "OK"}[worst]
    print(f"== {rep.name}: {verdict}")
    s = rep.stats
    if "size_mm" in s:
        line = f"   size {s['size_mm'][0]} x {s['size_mm'][1]} x {s['size_mm'][2]} mm"
        if "volume_cm3" in s:
            line += f", volume {s['volume_cm3']} cm3 (solid {s['mass_solid_g']} g; real print with 15% infill is less)"
        print(line)
    for c in sorted(rep.checks, key=lambda c: {ERROR: 0, WARN: 1, INFO: 2}[c["severity"]]):
        print(f"   {tag[c['severity']]} {c['id']}: {c['message']}")
        d = c.get("data", {})
        for key in ("islands", "regions", "bridges"):
            for item in d.get(key, [])[:3]:
                print(f"            {item}")
    for o in s.get("orientation_candidates", []):
        print(f"   orient rotate {o['rotate_xyz_deg']}: overhang {o['overhang_mm2']} mm2, contact {o['contact_mm2']} mm2, height {o['height_mm']} mm")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--material", default="PLA")
    ap.add_argument("--layer", type=float, default=None, help="layer height, default from profile (0.2)")
    ap.add_argument("--nozzle", type=float, default=None)
    ap.add_argument("--overhang", type=float, default=None, help="max overhang from vertical, deg (45)")
    ap.add_argument("--bridge-max", type=float, default=25.0, help="longest acceptable bridge, mm")
    ap.add_argument("--rotate", type=float, nargs=3, metavar=("RX", "RY", "RZ"))
    ap.add_argument("--orient", action="store_true", help="also rank candidate orientations")
    ap.add_argument("--together", action="store_true",
                    help="treat all files as parts of ONE object (e.g. body + colour inlay) and check their union")
    ap.add_argument("--json", help="write the full report here")
    ap.add_argument("-D", "--define", action="append", help="OpenSCAD variable for .scad input, name=value")
    args = ap.parse_args()

    P = printer_defaults()
    if args.layer:
        P["layer"] = args.layer
    if args.nozzle:
        P["nozzle"] = args.nozzle
    if args.overhang is None:
        args.overhang = P["overhang_deg"]

    files = args.files
    if args.together and len(files) > 1:
        import tempfile
        from meshio_util import load_mesh as _lm
        meshes = [_lm(f) for f in files]
        try:
            import manifold3d  # noqa: F401
            merged = trimesh.boolean.union(meshes, engine="manifold")
        except Exception:
            merged = trimesh.util.concatenate(meshes)
        tmp = os.path.join(tempfile.mkdtemp(prefix="together_"), "+".join(os.path.splitext(os.path.basename(f))[0] for f in files) + ".stl")
        merged.export(tmp)
        files = [tmp]

    reports, worst = [], -1
    for f in files:
        rep, _ = check_file(f, args, P)
        print_report(rep)
        reports.append({"file": f, "stats": rep.stats, "checks": rep.checks})
        worst = max(worst, rep.worst())
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(reports if len(reports) > 1 else reports[0], fh, indent=1)
    if any(c["id"] == "load" for r in reports for c in r["checks"]):
        sys.exit(2)
    sys.exit(1 if worst == 2 else 0)


if __name__ == "__main__":
    main()
