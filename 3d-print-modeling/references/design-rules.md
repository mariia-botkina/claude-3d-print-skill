# FDM design rules (structure and printability)

Read this when designing the structure of a part or fixing a check_print.py finding.
Numbers for this printer are in printer-profile.md.

## Contents
1. Orientation
2. Avoiding supports
3. Joints and fits
4. Strength
5. Multi-colour with the AMS
6. Text and relief
7. Large objects
8. Embedded hardware
9. Fixing check_print.py findings

## 1. Orientation

Choose the print orientation while designing, not after: it decides strength, support,
surface quality and accuracy.
- Largest flat face on the bed when possible: best adhesion, no support.
- Layers are weakest in tension along Z. Clips, hooks, cantilever snaps, thin pegs: lay
  them so the bending stress runs along the layers (the arm lies flat on the bed).
- Round holes and round pins are accurate when their axis is vertical (Z).
- The top surface and the side walls look best; the bottom takes the plate texture;
  supported faces look rough. Put the "show" face up or on the side.
- If two requirements conflict (strength vs appearance), ask the owner which wins.

## 2. Avoiding supports

In order of preference:
1. Split the part into pieces that each print flat, then join them.
2. 45 deg chamfer or gusset under ledges instead of a flat ceiling.
3. Teardrop or flat-topped horizontal holes; a diamond for small holes.
4. Bridges: keep spans under ~20 mm, anchored on both ends.
5. Sacrificial layer: a 0.2 mm skin over a hole that starts mid-air, drilled out after.
6. Only then supports: tree supports, with "support on build plate only" when possible,
   and keep them away from visible faces.

## 3. Joints and fits

Use the fits table in printer-profile.md (measured values beat defaults).
- **Pins and holes**: pin chamfered 0.4 mm at the tip; hole countersunk 0.3 mm at the entry.
- **Press fit**: short engagement (3-6 mm) is enough; crush ribs (3-4 small ribs ~0.3 mm)
  make a press fit tolerant of printer variation.
- **Dovetails and slots**: clearance on both flanks; a lead-in chamfer; a stop at the end.
- **Snap-fit cantilever**: arm length >= 5x thickness, undercut 0.5-1.0 mm, arm printed
  flat; PLA snaps survive few cycles, PETG many.
- **Keyed parts**: one asymmetric feature (a flat on a round pin, an offset tab) makes wrong
  assembly impossible.
- **Print-in-place hinges/chains**: 0.35-0.40 mm gap, no gap bridging the first layer,
  break-free test coupon first.
- **Glue joints**: 0.1 mm gap per side and alignment pins.
- **Threads**: printed threads only >= M8-ish and coarse; otherwise heat-set inserts
  (hole per insert datasheet) or captive nuts (hex pocket +0.2 mm).

## 4. Strength

- More walls beat more infill: 3-4 walls (wall_loops) for loaded parts, 15-25 % infill.
- Fillets at inside corners (R >= 1 mm) remove stress risers.
- Avoid long thin pegs in Z; make them horizontal or thicker (>= 5 mm) or add a metal pin.
- Thin plates: >= 1 mm, ribs underneath rather than a thicker plate.

## 5. Multi-colour with the AMS

- Inlays (text, logos) as separate parts of the same object ("parts" in the 3MF spec),
  0.4-0.6 mm deep, flush with the surface: crisp, cheap in purge.
- Colour by height (bands, a contrasting top, layered signs): one purge per change, cheap;
  done with `filament` layer events in the 3MF. Raised text on a flat sign is the classic
  case: base in one colour, text from the base's top surface up in another.
- Colour changes every layer over the whole height (e.g. coloured text on a vertical face)
  cost a purge per layer: warn about filament waste and time, suggest top-face text or
  separate glued parts instead.
- Minimum colour feature ~0.8 mm wide in XY.
- Multi-colour plates get a prime tower; make_3mf.py keeps the back-right corner free for it.

## 6. Text and relief

- Use Liberation Sans / DejaVu (installed) unless the owner asks for another font; check
  fc-list before using a font name; Cyrillic and Church Slavonic need a font with those
  glyphs (ask the owner for the font file if a specific one is required).
- Size rules in printer-profile.md. Bold weights print far better than regular.
- Top-surface text prints cleanest; text on vertical walls is fine embossed, poor
  engraved below 6 mm.

## 7. Large objects

- Bed is 256 x 256 mm; height 256 mm. Split larger objects with alignment pins or
  dovetails, seams on hidden faces or along design lines, numbered parts.
- Big flat parts warp less with rounded corners and a brim (mouse ears on corners).

## 8. Embedded hardware

Closed pockets filled during a pause (`find_pockets.py`, layer events in the 3MF):
- Pocket = insert + 0.2 mm in XY (round magnets: diameter + 0.2; nuts: across flats
  + 0.2, hex pocket), + 0.2 mm in height so the nozzle clears the insert.
- Put the pocket floor and ceiling on the layer grid (multiples of the layer height
  above the first layer); otherwise the printed pocket is up to one layer shallower.
- At least 3 layers (0.6 mm) above the insert; the first one bridges over it, so keep
  pockets under ~20 mm across or the roof sags onto the insert.
- Magnets: mark the polarity in the instructions; steel parts can pull a magnet up out
  of its pocket, so pause close to the closing layer (the script does).
- Open pockets (glued in after printing) need no pause: pocket +0.1 mm for a press fit.
- Heat-set inserts: hole per insert spec, wall around >= 1.6 mm.

## 9. Fixing check_print.py findings

| Finding | Usual fixes (ask before changing the design) |
|---|---|
| islands | rotate the part; add a 45 deg chamfer below; split; support |
| flat_ceilings | chamfer/gusset; split; bridge it by adding a support wall; support |
| overhangs | rotate; reduce angle; accept if small and not visible |
| long_bridges | add a pillar/rib; shorten span; split |
| too_thin | thicken to >= 0.8 mm; remove the detail; scale the detail |
| thin_walls | thicken to >= 0.8 mm (1.2 if loaded) |
| thin_plates | >= 0.6 mm, better 1.0; ribs |
| adhesion | bigger base; brim; reorient; mouse ears |
| slender | thicker section; print lying down; add a support rib |
| not_watertight / non_manifold | fix the source geometry (in OpenSCAD: avoid coincident faces, overlap unions by 0.01 mm); trimesh repair only as a last resort |
| debris | find the stray shell in the source and remove it |
| too_big | split the part (section 7) |
