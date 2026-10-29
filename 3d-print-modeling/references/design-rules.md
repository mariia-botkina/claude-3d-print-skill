# FDM design rules (structure and printability)

Read this when designing the structure of a part or fixing a check_print.py finding.
Numbers for this printer are in printer-profile.md; they are given for the 0.4 nozzle.
For another nozzle scale line-based numbers (thinnest feature, walls, text strokes) by
nozzle / 0.4 and use that nozzle's layer height (printer-profile.md, Nozzles).

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
10. Saving material

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
- Count filament changes before building: (colours on a layer - 1) per layer, plus one
  when the colour set changes. Each is ~1.5-2 min and 0.2-0.8 g of purge + tower on the
  P1S. To cut them: inlays 0.4 mm (2 layers) instead of 0.6; all colour features of a
  plate on the same layers (aligned depths), so one change serves all; one material per
  plate; colour by height (one change) instead of inlays where the design allows.
- Colour features on the first layer (face-down inlays): crisp face on the textured plate,
  but the slow first layer then waits for every change; tiny islands of another colour on
  layer 1 can be dragged. Make them at least ~2 mm across.

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
| too_thin | thicken to >= 0.8 mm; remove the detail; scale the detail; a 0.2 nozzle (nozzle_advice.py) |
| thin_walls | thicken to >= 0.8 mm (1.2 if loaded) |
| thin_plates | >= 0.6 mm, better 1.0; ribs |
| adhesion | bigger base; brim; reorient; mouse ears |
| slender | thicker section; print lying down; add a support rib |
| not_watertight / non_manifold | fix the source geometry (in OpenSCAD: avoid coincident faces, overlap unions by 0.01 mm); trimesh repair only as a last resort |
| debris | find the stray shell in the source and remove it |
| too_big | split the part (section 7) |

## 10. Saving material

Roughly in order of effect. Each is a design change: offer it with the saving in grams
and money (cost.py --compare) and what it costs in look, strength or time.

**Print settings (often the biggest share)**
- Infill 10-15 % for parts that are not loaded; gyroid or lightning for decorative parts
  (lightning only supports top skins, so not for anything handled roughly). Strength comes
  from walls, not from dense infill: 3 walls + 15 % beats 2 walls + 40 %.
- Fewer top/bottom layers on parts whose top/bottom is not visible or loaded (top 4,
  bottom 3 with 0.2 mm layers); check that the top does not pillow.
- Thicker layers (0.24-0.28 mm Draft presets) save time, not plastic; use them for speed.
- Modifiers: dense infill only where screws, pegs or clips go (a modifier part with its
  own infill), sparse elsewhere.

**Geometry**
- Hollow or shell big volumes: a box-shaped solid becomes walls + ribs; plates get ribs
  underneath instead of more thickness.
- Cut-outs, lattices and windows in panels that only need stiffness, when the look allows.
- Smallest size that still works: ask whether dimensions are fixed or "about".
- Thin decorative relief instead of thick blocks; text engraved or 0.4-0.6 mm embossed.
- Combine parts that are always used together; split parts only where it saves supports.

**Waste**
- Supports: orientation, 45 deg chamfers, bridges and splitting are cheaper than support
  material (design-rules section 2). Tree supports use less than normal ones.
- Brim only for small-contact or warp-prone parts; mouse ears instead of a full brim.
- Multi-colour (AMS): every filament change purges 0.1-0.5 g plus prime-tower material.
  Cheapest: colour only on the top 2-3 layers (inlay flush with the surface) and on as few
  layers as possible; colour by height instead of per-layer alternation; many copies per
  plate so one purge serves all; purge into infill or into a sacrificial object (ask).
  Avoid full-height colour (text on vertical faces).

**Tests**
- Print only the feature under test (test_slice.py): a 3-5 mm slice through a fit, one
  hinge knuckle pair, one clip, one slot with its peg. Thin, low infill.
- Reuse measured fits (printer-profile.md) instead of re-testing them per project.
- Batch several test pieces on one plate; log grams per test.

**Series**
- Fill plates: cost.py --batch shows cost per item with copies sharing one plate (purge
  and warm-up shared). Group identical colour sets on the same plate.

