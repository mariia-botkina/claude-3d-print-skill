# Printer profile (global defaults)

These are the owner's standing defaults. They apply to every project unless the
project's REQUIREMENTS.md says otherwise. Values marked *(assumption)* have not
been confirmed by the owner: say so when you rely on one, and ask.

When the owner gives a new standing rule ("always...", "from now on...", a
measured fit), offer to add it here (it lives in the skill's GitHub repo, so
the change is a commit) instead of keeping it only in one project.

## Machine

| Item | Value |
|---|---|
| Printer | Bambu Lab P1S with AMS (4 slots) |
| Nozzle | 0.4 mm installed, stainless (no abrasive filaments: no CF/GF). Owns only 0.4; willing to buy another size when a project needs it (see Nozzles) |
| Build volume | 256 x 256 x 256 mm |
| No-print corner | front-left 18 x 28 mm (purge chute) |
| Default process | 0.20mm Standard @BBL X1C (Bambu uses the X1C process presets for the P1S) |
| Plate | Textured PEI Plate *(assumption: confirm on first project and record here)* |
| Slicer | Bambu Studio (owner slices herself; Claude only prepares the 3MF) |

## Materials

| Material | When | Notes |
|---|---|---|
| Bambu PLA Basic | default for everything | Softens near 55 C: not for cars, sunny windowsills, dishwashers |
| Bambu PETG HF / Basic | only when the structure needs it: heat, outdoor/UV, impact, flexing clips, parts that get bent on every use | Strings more; bridges worse; slightly bigger clearances |
| Bambu PLA Lite | never for finished items | |
| Support For PLA | optional interface material if the owner has it loaded | Ask; do not assume it is in the AMS |

Before assigning AMS slots, ask which colours/materials are loaded. Do not invent a
loadout.

## Nozzles

Owner's rule: whenever a project would print better on another nozzle, say so and ask;
both directions count (smaller for detail, bigger for speed on big simple parts).

| Nozzle | Default process | Thinnest feature | Min wall (2 lines) | Good for | Watch out |
|---|---|---|---|---|---|
| 0.2 | 0.10mm Standard @BBL X1C 0.2 nozzle | 0.2 mm | 0.4 mm | small text (< 4 mm), filigree, miniatures, fine lineart | 2-4x slower; clogs easier; no TPU, no CF/GF |
| 0.4 | 0.20mm Standard @BBL X1C | 0.4 mm | 0.8 mm | almost everything | |
| 0.6 | 0.30mm Standard @BBL X1C 0.6 nozzle | 0.6 mm | 1.2 mm | big, simple, strong parts; faster | loses small detail and text; heavier walls |
| 0.8 | 0.40mm Standard @BBL X1C 0.8 nozzle | 0.8 mm | 1.6 mm | very large utilitarian parts | visible thick layers; no fine detail |

- When the nozzle changes for a project, everything in it follows: `"nozzle"` in the 3MF
  spec (printer + process presets), `--nozzle` for check_print / slice_check /
  find_pockets / nozzle_advice, design numbers from this table, layer grid for pauses,
  and a line in REQUIREMENTS.md with the reason.
- Fits measured on one nozzle do not carry over: for another nozzle use the default fit
  table as *(assumption)* and offer a tolerance comb printed with that nozzle.
- Every report for a project on a non-installed nozzle ends with a reminder: swap the
  nozzle before printing, select it in Bambu Studio, and put the 0.4 back afterwards.

## Design numbers (0.4 nozzle, 0.2 layers)

| Rule | Value | Why |
|---|---|---|
| Thinnest feature that prints | 0.4 mm (one line) | the slicer drops anything thinner |
| Minimum wall | 0.8 mm (2 lines) | below this walls are gappy and fragile |
| Structural wall | 1.2-1.6 mm (3-4 lines) | anything that is loaded, clipped or screwed |
| Thin horizontal plate | >= 0.6 mm (3 layers), 1.0 mm preferred | thinner plates are see-through and brittle |
| Overhang without support | up to 45 deg from vertical | the P1S often manages 50-55, but design for 45 |
| Bridge | up to ~20-25 mm | longer spans sag |
| Embossed text | stroke >= 0.6 mm, height >= 0.6 mm, letter height >= 4 mm | |
| Engraved text | stroke >= 0.5 mm, depth 0.4-0.6 mm, letter height >= 5 mm | inner counters of small letters otherwise close up |
| Vertical holes | print about 0.1-0.2 mm undersize | measure with the tolerance comb |
| Horizontal holes > 6 mm | teardrop or flat-top shape | the top arc is an overhang |
| Bottom edges of mating parts | 0.4 mm chamfer | hides elephant's foot |
| Layer lines | weakest in Z (layers peel apart) | orient clips, hooks, pegs so the load runs along the layers |

## Fits (clearance per side)

Until measured, use these *(assumption)* values and label them as such:

| Fit | Clearance per side |
|---|---|
| Press fit (stays put, assembled by hand pressure) | 0.10 mm |
| Snug / friction fit (removable) | 0.15 mm |
| Sliding fit (moves freely, no wobble) | 0.20-0.25 mm |
| Loose / rotating fit | 0.30 mm |
| Print-in-place gap | 0.35-0.40 mm |
| PETG | add about 0.05 mm to each |

### Measured fits

Not measured yet. `scripts/tolerance_comb.py --nozzle <d>` builds the test print; record
results here (per nozzle):

| Nozzle | Material | Hole type | Press | Sliding | Loose | Date |
|---|---|---|---|---|---|---|
| | | | | | | |

## Output conventions

- One Bambu Studio project (3MF) per project, assembled: plates, layout, print settings,
  AMS filament assignment, per-object overrides. Built with `scripts/make_3mf.py`.
- Plates grouped by meaning (e.g. "Frame", "Icons, row 1") and by colour set, named.
- Object names match the part names used in conversation and in REQUIREMENTS.md.
- Alongside the 3MF: the editable source (.scad or .py), REQUIREMENTS.md, a preview PNG.
- Pauses (embedding magnets/nuts) park the head at the back left (X65 Y245) after a
  10 mm lift: the owner's choice ("move the head to the edge"). Written as per-layer
  custom G-code, never by changing the printer's pause G-code (that triggers Bambu's
  "Modified G-code" warning on every open): also the owner's choice.
