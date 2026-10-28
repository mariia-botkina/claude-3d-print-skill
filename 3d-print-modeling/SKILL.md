---
name: 3d-print-modeling
description: 3D modelling for FDM printing (Bambu Lab P1S + AMS by default) from interview to a ready Bambu Studio 3MF. Use whenever the user mentions 3D modelling, 3D printing, a printer, STL/3MF/OpenSCAD/STEP files, filament, supports, tolerances or fits, or asks to design, model, fix or check any physical object (including embedding magnets or nuts and multi-colour prints), part, holder, case, stand, figurine, sign or replacement piece, even without saying "print" (every model is assumed to be for the printer). Also for quick printing questions (material, orientation, will this print). Russian triggers - 3д, 3D-модель, моделирование, печать, напечатать, принтер, пластик, филамент, поддержки, зазор, STL, 3MF.
---

# 3D modelling for printing

Every model is for the printer. The job is a part that prints cleanly and works in a
real hand, built from requirements the user actually confirmed. Default machine and
house rules: `references/printer-profile.md` (read it at the start of any 3D task).

Talk to the user in their language. Messages from the scripts are English: translate
and explain them; never paste raw tool output as the answer.

## Two modes

**Quick mode**: a question with no model to produce ("which plastic for a shower
hook?", "will this overhang print?", "what clearance for a lid?"). Answer from
printer-profile.md and `references/design-rules.md`, mention the relevant house default,
and offer the full workflow only if a model is actually wanted. No setup, no files.

**Project mode**: anything that ends in a model or a file (new design, change to an
existing project, checking/fixing an STL, preparing a 3MF). Follow the workflow below.

## Project workflow

```
0 setup (background) -> 1 load context -> 2 interview -> 3 usability checks
-> 4 design proposal -> 5 model -> 6 verify -> 7 fix loop (ask) -> 8 package -> 9 record
```

### 0. Setup
Run `bash scripts/setup.sh` at the start of project mode, in the background while you
talk (first run in a fresh sandbox takes 1-3 min; later runs are instant). It installs
OpenSCAD, PrusaSlicer, Xvfb, fonts and the Python mesh libraries and prints what is
available. If something is missing, continue with what works and say what you could not
check.

### 1. Load context
- Read `references/printer-profile.md`.
- Continuing a project? Its `REQUIREMENTS.md` is the memory of the project. Look for it in
  the conversation's attachments, project files, the user's linked folder or repo. If it
  is not reachable, ask the user to attach it (and the source file) rather than
  reconstructing requirements from memory.
- New project: create `REQUIREMENTS.md` from `references/requirements-template.md`.

### 2. Interview before the first model
The user wants many questions up front, including obvious ones: a misunderstanding costs
a print, a question costs a minute. Follow `references/interview.md`:
- rounds of 6-12 numbered questions with a proposed default for each;
- everything you had to guess goes to "Assumptions (unconfirmed)" and gets confirmed;
- end with a short brief and wait for an explicit yes before modelling.

Do not start modelling "to show something" before the brief is confirmed. If the user
explicitly says to go ahead without answers, list the assumptions you are making, mark
them in REQUIREMENTS.md, and go.

### 3. Usability checks
Printability and usability carry the same weight. For each new project propose 3-6
concrete checks from `references/usability-checks.md` that fit this object (finger
access, tipping, assembly order, legibility, real-object fit...), each with how you will
verify it, and ask which to run and what to add. Record the agreed list.

### 4. Design proposal
Before writing code, present the structure: parts and their purpose, joints and fit
classes (with the clearance you will use and whether it is measured or assumed), print
orientation per part and why, material and AMS slot per part, plate grouping, expected
supports. Ask for confirmation. For any decision about how it looks, offer 2-3 options
(rendered side by side when it helps) and let the user choose; never pick the look for
them.

### 5. Model
Conventions are in `references/modeling-workflow.md`. In short: OpenSCAD by default,
Python (trimesh + manifold3d) for technical/data-driven generators; parameters at the top
named in the user's terms and mirrored in REQUIREMENTS.md; one part per STL, each in its
print orientation on z = 0. The user should never have to edit code: she asks, you
change parameters.

### 6. Verify (every generation, every part)
1. `python scripts/render.py part.stl -o previews/part.png --overhang 45` and look at the
   image yourself with Read. Does it match the brief? Anything odd?
2. `python scripts/check_print.py parts/*.stl --json check.json` (add `--orient` when the
   orientation is not obvious). Errors = will fail; warnings = risky; info = fyi.
   Parts of one multi-colour object (body + inlay) are checked together with
   `--together body.stl inlay.stl`: an inlay alone always looks thin.
3. `python scripts/slice_check.py part.stl` (add `--nozzle` if not 0.4) for a PrusaSlicer reference slice (time,
   grams, whether supports are needed, slicer stability warnings). Reference only: final
   numbers come from Bambu Studio.
4. Run the agreed usability checks (measure the geometry, render the critical spot,
   or specify an owner test).
5. On the first full model, and whenever detail or size changes a lot, run
   `nozzle_advice.py` (see "Nozzle choice").
6. With findings, render again with `--report check.json` to mark the problem spots.

### 7. Fix loop: ask first
Do not silently change the design to fix a finding, technical or visible. For each issue:
what is wrong (plain words, where, why it matters), 2-3 fix options with their trade-off
and one recommendation (fix menu in design-rules.md section 9), then the user's choice.
Group several issues into one message. Exceptions: pure mesh hygiene that changes nothing
in shape (closing a gap from coincident faces, removing a stray 0.01 mm shell) can be
fixed and reported.

### 8. Package
Build the Bambu Studio project with `scripts/make_3mf.py` (spec format in
`references/bambu-3mf.md`): named plates, layout, process preset, per-object settings,
AMS slots with the confirmed filaments and colours, multi-colour parts, pauses and colour
changes by height (section below). Ask about the AMS
loadout if it is not confirmed. Deliver with SendUserFile (or the conversation's file
tool): the `.3mf`, the source (`.scad`/`.py`), `REQUIREMENTS.md`, and a preview PNG.

### 9. Record
Update REQUIREMENTS.md in the same turn as every decision: confirmed values, decision
log (options offered -> chosen), check results per version, open questions. Deliver the
updated file with each version. If the user states a rule for all future projects (a
measured fit, a plate type, a material policy), offer to add it to
`references/printer-profile.md` in the skill repo.

## Conflicts
When a new request contradicts a confirmed requirement or an earlier decision, do not
pick a side. Quote both ("R3 says sliding fit 0.2 mm; now you ask for a tight press
fit"), offer the options (replace, keep, make it a parameter / variant), and let the user
choose. Log the result.

## Report format (short, in the reply)
```
<Part/plate>: ready | ready with caveats | not ready
- <finding in plain words> -> <proposed fix options or "fine as is">
Usability: <check>: pass / to test on the print: <what to try>
Estimate (PrusaSlicer reference): ~<time>, ~<g> PLA; supports: none / <where>
Nozzle: <d> (installed) | <d>: swap before printing, put the 0.4 back afterwards
Waiting for your decision: <numbered questions>
```
Keep it to what the user needs to decide or know. Full JSON reports stay in files.

## Nozzle choice
The owner has a 0.4 nozzle and will buy another size when a project needs it. Raise it
in both directions, at two moments:
- **Interview**: fine detail in the brief (text under ~4 mm, filigree, miniatures, thin
  lineart) -> mention that a 0.2 nozzle may be needed; big simple utilitarian parts ->
  mention that 0.6 would be faster. Do not decide yet.
- **After the first model**: run `python scripts/nozzle_advice.py parts/*.stl`. It shows,
  per part and nozzle, the detail that would be dropped, the fragile features, and the
  reference print time and weight, plus project-level options (everything on one nozzle
  vs one 3MF per nozzle; a 3MF holds one nozzle).

When the advice differs from the installed nozzle, ask, with the numbers: what is lost
on the current nozzle, how much slower/faster the alternative is, and the options. Never
switch silently. Once the user picks a nozzle for the project:
- set `"nozzle"` in the 3MF spec (Bambu presets for 0.2/0.4/0.6/0.8 are bundled) and pass
  `--nozzle` to check_print / slice_check / find_pockets;
- use that nozzle's design numbers (printer-profile.md, Nozzles) and re-check the parts;
- fits measured on another nozzle become assumptions; offer the tolerance comb with
  `--nozzle`;
- record the nozzle and the reason in REQUIREMENTS.md;
- end every report with a reminder: swap the nozzle and select it in Bambu Studio before
  printing, and put the 0.4 back afterwards.

## Pauses and colour changes by height
Both go into the 3MF as layer events (`"events"` in the make_3mf spec, see
`references/bambu-3mf.md`); the user does not set them by hand in Bambu Studio.

**Embedded inserts (magnets, nuts, coins, weights).** Two ways in, both end the same:
- the user names what goes where ("10x3 magnets in the base"): design a closed pocket
  (insert + 0.2 mm in XY, + 0.2 mm in height, floor and ceiling on the layer grid);
- the model already has closed voids: `check_print.py` reports them as `cavities`.

Then run `python scripts/find_pockets.py part.stl --insert 10x3` (DxH, WxLxH or M3nut;
repeat --insert per pocket). It gives each pocket's pause layer and fails if the insert
would stick out above the closing layer (the nozzle would hit it) or not fit. Show the
user the list (pocket, insert, layer number, height) and confirm before building the
3MF. In the report say what to insert at which pause and which way up (magnet
polarity), and that the head lifts and parks at the back while waiting.

**Colour by height** (bands, layered signs, a contrasting top): the user describes it in
words ("top 2 mm black"); translate to heights, show a preview with
`render.py part.stl --bands "#F2F2F2;8.0:#1A1A1A"`, confirm, then add `filament` events.
A plate with height colour changes must hold only single-filament objects; multi-colour
objects (inlays as parts) go on another plate.

## Tolerance comb
If no fits are measured yet (printer-profile.md, "Measured fits") and the project has
joints, offer the tolerance comb: `python scripts/tolerance_comb.py -o comb/` builds a
ready 3MF (round and square fits, 0-0.40 mm per side). Explain how to read it (see the
header of `assets/tolerance_comb.scad`) and record the results in the profile.

## Files
- `scripts/setup.sh` install toolchain
- `scripts/check_print.py` printability analysis (mesh, size, islands, overhangs, bridges, thin features, adhesion, orientation ranking)
- `scripts/slice_check.py` PrusaSlicer reference slice
- `scripts/render.py` previews, variants side by side, problem overlays, colour bands
- `scripts/make_3mf.py` Bambu Studio project builder (plates, settings, AMS, pauses, colour by height, --verify)
- `scripts/find_pockets.py` closed pockets: pause layer and insert fit
- `scripts/nozzle_advice.py` per-part nozzle comparison: lost detail, fragile features, time, grams
- `scripts/tolerance_comb.py` + `assets/tolerance_comb.scad` fit calibration print
- `assets/bambu/nozzle_<d>/` P1S presets per nozzle (0.2/0.4/0.6/0.8) extracted from Bambu Studio (regenerate with `tools/build_bambu_profiles.py` in the repo)
- `references/` printer-profile, interview, usability-checks, design-rules, modeling-workflow, requirements-template, bambu-3mf
