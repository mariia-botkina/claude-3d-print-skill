# Modelling workflow and code conventions

The owner should not need to read or edit code. Everything she may want to change is a
named parameter at the top of the source, mirrored in REQUIREMENTS.md, and she asks you
to change it in words. Code still has to be clean enough to put on GitHub.

## Which tool

| Situation | Tool |
|---|---|
| Most objects: boxes, holders, stands, ornaments, signs, assemblies of simple solids | OpenSCAD (.scad) |
| Technical generators driven by data or many variants (grids, patterns from images, families of sizes, CSV-driven sets) | Python: trimesh + manifold3d (+ shapely for 2D) |
| Organic / sculpted shapes | Say plainly that code CAD is weak at this; offer a stylised geometric version or ask for a mesh to start from |
| Editing a downloaded STL | trimesh + manifold3d booleans (cut, add a base, add holes); mesh repair |

OpenSCAD in the sandbox is version 2021.01 (CGAL backend, slow on heavy booleans).

## Project folder

```
<project>/
  REQUIREMENTS.md        brief, decisions, assumptions, usability checks
  <project>.scad         or <project>.py; one file unless it gets large
  parts/                 rendered STLs, one per part
  previews/              PNGs from render.py
  <project>.spec.json    make_3mf.py spec
  <Project>.3mf          deliverable
```

## OpenSCAD conventions

- Parameters first, grouped with Customizer comments so they also work in the OpenSCAD
  app: `/* [Size] */`, then `width = 80; // [40:200] outer width, mm`.
- Units are mm. Name parameters after what they mean to the owner ("icon_width"), not
  geometry ("w2").
- One module per part, plus `part = "all"; // [all, frame, lid, ...]` selector at the top
  so each part renders to its own STL: `openscad -D 'part="lid"' -o parts/lid.stl x.scad`.
- Every part modelled in its print orientation, sitting on z = 0. The "all" view may show
  the assembled state instead; say which in a comment.
- `$fn`: 32-48 while iterating, 96+ for the final render of visible round surfaces.
- Avoid coincident faces in differences: extend cutters 0.01-1 mm past the surface.
- Prefer hull() and linear_extrude() over minkowski() (very slow in 2021.01).
- Text: `text(..., font="Liberation Sans:style=Bold")`; check `fc-list` first.
- A short header comment: what the object is, how to render parts, which parameters
  matter.

## Python generator conventions

- CLI with argparse; every requirement-level parameter is a flag with a default and help.
- Build solids with manifold3d (robust booleans), convert to trimesh for export.
- Deterministic output, one STL per part, README-style docstring.
- Validate the result by calling check_print.py on what you generated.

## Iterating on the look

- Never change the visible design on your own. When a look decision is open, render
  2-3 variants side by side (`render.py a.stl b.stl c.stl --layout`), label them, and
  ask which one.
- After a change, show before/after when the difference is visual.

## Speed

- Render parts in parallel shell jobs when there are many.
- For big boolean-heavy OpenSCAD models, iterate with low $fn and render the final once.
- check_print.py on a dense mesh takes seconds; slice_check.py ~10-60 s per part.
