#!/usr/bin/env python3
"""Compare nozzle sizes for the parts of a project: what detail each nozzle loses,
what gets fragile, and how long/heavy the print is.

  python nozzle_advice.py part1.stl part2.stl [--nozzles 0.2,0.4,0.6,0.8] [--current 0.4]
                          [--material PLA] [--no-time] [--json advice.json]

Per part and nozzle (layers = Bambu's default for that nozzle):
  lost     volume of features thinner than one line: the slicer drops them (letters, filigree, ribs)
  fragile  volume of features thinner than two lines: they print, but weak/gappy
  time/g   PrusaSlicer reference slice with Bambu's defaults for that nozzle (2 walls of that
           nozzle's line width, so bigger nozzles also mean thicker, heavier walls);
           skip with --no-time (~10-60 s per part and nozzle)

Then a recommendation:
  - a part that loses detail on the current nozzle -> the largest nozzle that keeps it
  - a part that keeps all detail on a bigger nozzle and prints >= 25% faster -> suggest it
  - a project mixing both: one 3MF holds one nozzle, so the options are one nozzle for
    everything or one 3MF per nozzle; the totals for each option are printed.
Nothing is decided here: show the table to the user and ask.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_print as cp  # noqa: E402
from meshio_util import NOZZLES, load_mesh, printer_defaults, process_layers  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def detail_at(mesh, nozzle):
    P = printer_defaults(nozzle)
    try:
        P["layer"] = process_layers(None, nozzle)[1]
    except Exception:
        pass
    rep = cp.Report("x")
    cp.analyse_layers(mesh, rep, P, P["overhang_deg"], 25.0)
    cp.check_thin_plates(mesh, rep, P)
    out = {"lost": [], "weak": [], "thin_plates": False, "layer": P["layer"]}
    for c in rep.checks:
        if c["id"] == "too_thin":
            out["lost"] = c.get("data", {}).get("regions", [])
        elif c["id"] == "thin_walls":
            out["weak"] = c.get("data", {}).get("regions", [])
        elif c["id"] == "thin_plates":
            out["thin_plates"] = True
    return out


def slice_time(path, nozzle, material):
    tmp = tempfile.mkdtemp(prefix="nz_")
    js = os.path.join(tmp, "s.json")
    r = subprocess.run([sys.executable, os.path.join(HERE, "slice_check.py"), path, "--nozzle", str(nozzle),
                        "--material", material, "--no-support-pass", "--json", js],
                       capture_output=True, text=True, timeout=1800)
    if r.returncode != 0 or not os.path.exists(js):
        return None
    with open(js) as f:
        ns = json.load(f).get("no_supports", {})
    return {"time": ns.get("time"), "minutes": ns.get("time_min"), "grams": ns.get("filament_g")}


def fmt_min(m):
    if m is None:
        return "?"
    h, mm = divmod(int(round(m)), 60)
    return f"{h}h{mm:02d}m" if h else f"{mm}m"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--nozzles", default=",".join(f"{n:g}" for n in NOZZLES))
    ap.add_argument("--current", type=float, default=0.4, help="nozzle in the printer now")
    ap.add_argument("--material", default="PLA")
    ap.add_argument("--no-time", action="store_true")
    ap.add_argument("--json")
    a = ap.parse_args()
    nozzles = [float(x) for x in a.nozzles.split(",")]
    if a.current not in nozzles:
        nozzles = sorted(nozzles + [a.current])

    results = []
    for f in a.files:
        mesh = load_mesh(f)
        mesh.apply_translation([0, 0, -mesh.bounds[0][2]])
        tmp_stl = f
        if not f.lower().endswith(".stl"):
            tmp_stl = os.path.join(tempfile.mkdtemp(prefix="nz_"), os.path.basename(f) + ".stl")
            mesh.export(tmp_stl)
        row = {"file": f, "nozzles": {}}
        for n in nozzles:
            d = detail_at(mesh, n)
            t = None if a.no_time else slice_time(tmp_stl, n, a.material)
            vol = lambda regs: round(sum(r["area_mm2"] for r in regs) * d["layer"], 2)  # noqa: E731
            lost_v = vol(d["lost"])
            row["nozzles"][f"{n:g}"] = {"lost": len(d["lost"]) if lost_v >= 0.05 else 0, "lost_mm3": lost_v,
                                        "weak": len(d["weak"]), "weak_mm3": vol(d["weak"]),
                                        "lost_regions": d["lost"][:5], "thin_plates": d["thin_plates"], "slice": t}
        # recommendation per part
        cur = row["nozzles"][f"{a.current:g}"]
        keep = [n for n in nozzles if row["nozzles"][f"{n:g}"]["lost"] == 0]
        rec, why = a.current, "current nozzle is fine"
        if cur["lost"]:
            if keep:
                rec = max(keep)
                why = f"{cur['lost_mm3']} mm3 of detail ({cur['lost']} region(s)) is dropped with {a.current:g}; {rec:g} keeps it"
            else:
                rec = min(nozzles)
                why = "detail is lost even with the smallest nozzle: thicken the features"
        else:
            cur_t = (cur["slice"] or {}).get("minutes")
            for n in sorted([n for n in keep if n > a.current], reverse=True):
                r = row["nozzles"][f"{n:g}"]
                t = (r["slice"] or {}).get("minutes")
                if r["weak_mm3"] <= cur["weak_mm3"] + 0.05 and cur_t and t and t <= 0.75 * cur_t:
                    rec, why = n, f"keeps all detail and prints in {fmt_min(t)} instead of {fmt_min(cur_t)}"
                    break
        row["recommended"], row["why"] = rec, why
        results.append(row)

    # print
    print(f"== nozzle comparison ({a.material}; nozzle now: {a.current:g})")
    for row in results:
        print(f"-- {os.path.basename(row['file'])}")
        print("   nozzle | lost detail, mm3 | fragile (<2 lines), mm3 | time    | grams")
        for n in nozzles:
            r = row["nozzles"][f"{n:g}"]
            s = r["slice"] or {}
            mark = " <- now" if n == a.current else (" <- suggested" if n == row["recommended"] else "")
            print(f"   {n:<6g} | {r['lost_mm3']:>16} | {r['weak_mm3']:>23} | {fmt_min(s.get('minutes')):<7} | {s.get('grams', '?')}{mark}")
        print(f"   suggestion: {row['recommended']:g} ({row['why']})")

    recs = {row["recommended"] for row in results}
    plan = {}
    if len(results) > 1:
        print("-- project")
        if len(recs) == 1:
            print(f"   all parts: nozzle {recs.pop():g}")
        else:
            for n in sorted(recs):
                print(f"   nozzle {n:g}: " + ", ".join(os.path.basename(r["file"]) for r in results if r["recommended"] == n))
            if not a.no_time:
                for n in nozzles:
                    rows = [r["nozzles"][f"{n:g}"] for r in results]
                    if all(x["slice"] for x in rows):
                        tot = sum(x["slice"]["minutes"] or 0 for x in rows)
                        lost = round(sum(x["lost_mm3"] for x in rows if x["lost"]), 2)
                        plan[f"all_{n:g}"] = {"minutes": tot, "lost_mm3": lost}
                        print(f"   option: everything on {n:g}: {fmt_min(tot)}" + (f", drops {lost} mm3 of detail" if lost else ""))
                split = sum((r["nozzles"][f"{r['recommended']:g}"]["slice"] or {}).get("minutes") or 0 for r in results)
                plan["split"] = {"minutes": split}
                print(f"   option: one 3MF per nozzle: {fmt_min(split)} printing + a nozzle swap")
            print("   one 3MF holds one nozzle: ask which option the user wants")
    if any(r["recommended"] != a.current for r in results):
        print(f"   remember: after printing with another nozzle, put the {a.current:g} back (and tell Bambu Studio)")
    if a.json:
        with open(a.json, "w") as f:
            json.dump({"current": a.current, "parts": results, "project_options": plan}, f, indent=1)


if __name__ == "__main__":
    main()
