# Usability checks

Printability says "it will come off the printer". Usability says "it works in a hand, in
a room, for the people who use it". Treat both with the same weight.

For every new project, pick the 3-6 checks that matter most for this object, propose
them to the owner with one line each on how you would verify them, and ask which to run
and whether to add any. Record the agreed list in REQUIREMENTS.md and report on each
one after every generation.

Ways to verify, from cheapest to most reliable:
- **Geometry**: measure the model (clearances, gaps, reach, centre of mass, angles).
- **Render**: a view that shows the critical spot (cross-section, hand-scale reference).
- **Test coupon**: a small print of just the critical feature (a hinge, a slot, one joint).
- **Owner test**: something only a real print and a real hand can answer; write down
  exactly what to try and what result means pass.

## Catalogue

### Hands
- **Finger access**: can a finger reach and grip each removable part? Adult fingertip
  ~16-20 mm wide, child ~10-14 mm; a pinch needs ~8-10 mm clearance around the gripped
  edge, or a notch/finger scoop.
- **Grip size**: handles 25-35 mm thick for a full hand, at least 90-100 mm long.
- **Edges**: fillet/chamfer every edge a hand touches (>= 0.8 mm; >= 1.5 mm for kids).
- **Forces**: snap/press fits that need a sensible force (test coupon), lids that open
  with one hand if needed.

### Assembly
- **No-tool assembly** within the target time; count the steps.
- **Mistake-proofing**: parts that look alike but are not interchangeable get keys,
  asymmetric pins or engraved labels; correct orientation is obvious.
- **Order**: every part can actually be inserted in the intended order (no part blocked
  by an earlier one); check with the assembly sequence in the model.
- **Repeated assembly**: parts that are taken apart often should not rely on PLA snap
  fits (fatigue); prefer slots, magnets, gravity, or PETG.
- **Storage**: disassembled set fits the intended box/bag; the box itself is a part.

### Stability and robustness
- **Tipping**: centre of mass inside the base with margin; push test at the top edge
  (compute the tipping angle; > 15-20 deg for things that get bumped).
- **Drop/handling**: thin protrusions, long thin pegs, and Z-direction loads are the weak
  spots; check them against expected use (kids!).
- **Wear**: surfaces that slide or get inserted many times.

### Readability and look
- **Text legibility** at the viewing distance (letter height ~ distance / 200 as a
  minimum; 5 mm letters read at about 1 m).
- **Colour contrast** of text/inlays against the base colour.
- **Visible faces** free of support marks and seam lines (choose orientation and seam).

### Fit to the real world
- **Real-object fit**: critical dimensions taken from measurements, not guesses; propose
  a thin test slice of the fitting zone first.
- **Mounting**: screw head/shaft sizes, wall plugs, magnet pockets, adhesive area.
- **Environment**: heat, sun, water -> material choice.

### Safety
- Small detachable parts for children under 3 (choking: anything that fits a ~32 mm
  cylinder), swallowable magnets, sharp tips, pinch points in hinges.
