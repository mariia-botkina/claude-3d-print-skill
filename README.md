# claude-3d-print-skill

A [Claude skill](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview) for
3D modelling aimed at FDM printing: from a thorough interview to a Bambu Studio project
file that is ready to slice.

Default setup: **Bambu Lab P1S + AMS, 0.4 mm nozzle, Bambu PLA Basic** (PETG when the
part needs it). Change `3d-print-modeling/references/printer-profile.md` and regenerate the
presets (see below) to use it with another Bambu printer.

## What it does

- **Interviews before modelling.** Asks many questions up front (with proposed defaults),
  including obvious ones, and confirms a written brief before generating anything.
- **Remembers requirements** per project in a `REQUIREMENTS.md` (confirmed values,
  unconfirmed assumptions, decision log, check results), plus a global printer profile.
  Conflicts between a new request and earlier decisions are raised, never silently resolved.
- **Checks printability** of every part:
  - mesh: closed surface, normals, non-manifold geometry, stray shells;
  - size against the build volume and the P1S no-print corner;
  - layer-by-layer analysis: islands starting in mid-air, unsupported ledges, bridges
    (with span), sloped overhangs, features thinner than one or two extrusion lines,
    thin horizontal skins, first-layer contact and tipping risk;
  - candidate orientations ranked by overhang, bed contact and height;
  - a reference slice in PrusaSlicer (time, grams, whether supports are needed).
- **Checks usability** with the same weight: proposes object-specific checks (finger
  access, tipping, assembly order, legibility, fit to real objects...) and asks which to run.
- **Asks before changing the design**, technical or visible, offering options.
- **Packages a Bambu Studio 3MF**: named plates, layout, process preset, per-object
  settings, AMS filament slots and colours, multi-colour parts and modifiers, thumbnails.
  Built from Bambu Studio's own system presets.
- **Pauses for embedded inserts.** Finds closed pockets, checks that the magnet or nut
  fits and that the nozzle will clear it, and writes a pause before the layer that closes
  the pocket. The head lifts and parks at the back while you insert, then you resume.
- **Colour changes by height** (bands, layered signs, a contrasting top) written into the
  3MF as AMS filament changes, with a colour preview first.
- **Nozzle advice.** Compares 0.2 / 0.4 / 0.6 / 0.8 mm nozzles per part (detail that would
  be dropped, fragile features, print time and weight) and asks when another nozzle would
  serve the project better, in both directions. Once chosen, the whole project follows:
  presets in the 3MF (bundled for all four sizes), checks, design numbers, and a reminder
  to swap the nozzle back.
- **Tolerance comb** to measure real press/sliding/loose fits of your printer and filament.
- Quick questions ("which plastic for a shower hook?") get a direct answer without the
  full workflow.

## Install

**Claude app**: download `3d-print-modeling.skill` from the [Releases](../../releases) page
(or zip the `3d-print-modeling/` folder) and add it as a custom skill, as described in
the skills settings of the Claude app.

**Claude Code**: copy or symlink the folder into your skills directory:

```bash
git clone https://github.com/mariia-botkina/claude-3d-print-skill
ln -s "$PWD/claude-3d-print-skill/3d-print-modeling" ~/.claude/skills/3d-print-modeling
```

The skill installs its toolchain on first use (`scripts/setup.sh`: OpenSCAD, PrusaSlicer,
Xvfb, fonts via apt; trimesh, manifold3d, shapely, matplotlib via pip). Without apt it
still runs the mesh checks and builds the 3MF.

## Layout

```
3d-print-modeling/
  SKILL.md                  workflow (what Claude reads first)
  references/               printer profile, interview, usability checks,
                            design rules, modelling conventions, REQUIREMENTS template,
                            3MF spec
  scripts/
    setup.sh                toolchain
    check_print.py          printability analysis
    slice_check.py          PrusaSlicer reference slice
    render.py               previews and problem overlays
    make_3mf.py             Bambu Studio project builder (+ --verify)
    find_pockets.py         closed pockets: pause layer, insert fit
    nozzle_advice.py        nozzle comparison per part
    tolerance_comb.py       fit calibration print
  assets/
    bambu/nozzle_<d>/       P1S machine/process/filament presets per nozzle (generated)
    tolerance_comb.scad
  evals/                    test cases (claude plugin eval format)
tools/
  build_bambu_profiles.py   regenerates assets/bambu from Bambu Studio's profiles
```

The scripts also work on their own:

```bash
python 3d-print-modeling/scripts/check_print.py part.stl --orient
python 3d-print-modeling/scripts/render.py part.stl -o views.png --overhang 45
python 3d-print-modeling/scripts/make_3mf.py --example > spec.json
python 3d-print-modeling/scripts/find_pockets.py coaster.stl --insert 10x3
python 3d-print-modeling/scripts/nozzle_advice.py plaque.stl box.stl
python 3d-print-modeling/scripts/make_3mf.py spec.json -o Project.3mf
```

## Updating the Bambu presets

```bash
git clone --depth 1 --filter=blob:none --sparse https://github.com/bambulab/BambuStudio bs
git -C bs sparse-checkout set resources/profiles/BBL
python tools/build_bambu_profiles.py --profiles bs/resources/profiles/BBL \
    --skeleton any_project_saved_by_bambu_studio.3mf \
    --model "Bambu Lab P1S" --nozzles 0.2,0.4,0.6,0.8
```

## Limitations

- Bambu Studio itself does not run in the sandbox: the slice check uses PrusaSlicer with
  P1S-like settings, so time and weight are estimates. You slice the 3MF in Bambu Studio.
- Painted colour regions are not generated; multi-colour designs use separate parts
  (inlays) or colour changes by height instead.
- Code CAD (OpenSCAD, Python) is strong for functional and geometric objects, weak for
  sculpted organic shapes.

## License

MIT for everything written for this repository, see [LICENSE](LICENSE).
The preset data in `3d-print-modeling/assets/bambu/` is extracted from
[Bambu Studio](https://github.com/bambulab/BambuStudio)'s profiles and stays under
Bambu Studio's AGPL-3.0 license (see `assets/bambu/NOTICE.md`).
