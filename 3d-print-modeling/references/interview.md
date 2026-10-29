# Interview before the first model

The owner wants as many questions as possible before the first generation, including
obvious ones, so that nothing is built on a misunderstanding. A wrong guess costs a
print (hours and filament); a question costs a minute.

## How to run it

- Ask in rounds of 6-12 numbered questions, grouped by theme. Give a proposed default
  for each ("default: PLA Basic, white") so the owner can answer "default" or only correct
  what matters. When AskUserQuestion is available, use it for quick multiple-choice items
  and plain numbered text for open ones.
- Use what is already known (REQUIREMENTS.md, printer-profile.md, earlier answers) to
  skip questions or to turn them into confirmations ("Printing on the P1S with PLA Basic,
  right?"). Still confirm anything that is only inferred.
- Every answer goes into REQUIREMENTS.md immediately. Anything you had to guess goes
  into "Assumptions (unconfirmed)", never into "Confirmed".
- Ask follow-ups when an answer opens a new branch (e.g. "it hangs on a wall" -> how, what
  load, screw or nail size).
- Finish with a short summary of the whole design brief and ask for explicit confirmation
  before generating anything. Only "yes" or corrections move you forward.
- Later turns: ask again whenever a request touches something not settled yet. Don't
  re-ask what is confirmed unless the new request conflicts with it (then see SKILL.md,
  "Conflicts").

## Question bank

Pick what applies; the starred ones are always asked on a new project.

### Purpose and use
- * What is it for, who uses it, where does it live (indoor, outdoor, kitchen, car, kids' room)?
- * What does success look like? What would make you say "this failed"?
- How is it handled: how often, by whom (adult, child, elderly), one hand or two?
- Loads: does it carry weight, get bent, get dropped, get clipped open and shut repeatedly?
- Environment: heat (sun, car, dishwasher, hot drinks), water, food contact, UV?
- Safety: small children (small detachable parts, magnets, sharp edges)?

### Size and fit to the real world
- * Overall size, and which dimensions are fixed vs flexible?
- * Does it attach to, hold or fit around a real object? Ask for exact measurements (calipers,
  ruler) and which measurements are critical. Offer a quick test slice (a thin print of just
  the fitting section) before the full part.
- Mounting: wall, table, magnet, adhesive, screws (which size), hook?
- Does it need to fit into something else (box, drawer, shelf, bag)?

### Look
- * Style and references: photos, sketches, existing products, "like X but Y".
- * Colours, and which AMS slots / filaments are loaded right now.
- Text: exact wording, language/script, font feel, size, embossed vs engraved vs inlay.
- Surface finish: which faces are visible (no support marks there), matte/glossy filament.
- Shape details: rounded vs sharp, ornament level, symmetry.

### Structure
- * One piece or several parts? If parts: how they join (press fit, snap, screws, glue,
  magnets, print-in-place), and whether it must come apart again.
- Tools allowed for assembly? Assembly time target?
- Moving parts (hinges, sliders, lids, drawers)? Required travel and feel (tight, free).
- Hollow vs solid, weight targets, filament budget.
- Splitting large parts that exceed 256 mm: where seams may be visible.

### Printing constraints
- Material if not the default (PLA Basic); reasons for PETG.
- Nozzle: if the brief has fine detail (small text, filigree, miniatures) say a 0.2 nozzle
  may be needed; if it is a big plain part, say a 0.6 would be faster. Ask whether she is
  open to it; the real comparison comes after the first model (nozzle_advice.py).
- Supports: acceptable at all? Where not?
- Post-processing tolerance: sanding, gluing, painting, inserting magnets/nuts mid-print.
- Quantity (one, a set, a batch), and deadline.
- Print time limits per plate.

### Cost
- * Filament price per kg for each material/colour this project uses, electricity price per
  kWh, printer wear per hour (prices change; ask every project).
- Target cost or mass per item, if there is one (optional, depends on the project).
- How many items in total (one, a set, a series)? Series change the default: lead with the
  cheapest variant and plan plates per batch.
- Where can material be cut without hurting the purpose (hidden faces, inner volume,
  decoration level), and where not (parts children grab, load-bearing parts)?

### Output
- * Plates: how to group parts (by colour, by sub-assembly, by priority)?
- Labels/numbering on parts for assembly?
- Anything else to deliver: STL/STEP, assembly instructions, a parameter list to tweak later?

### Usability checks
- * Propose 3-6 concrete usability checks for this specific object from
  references/usability-checks.md and ask which ones to run (see SKILL.md).

## Example opening round (new project, owner wrote "make a stand for my phone")

1. Which phone (model or measured width x thickness, with/without case)?
2. Portrait, landscape or both? Charging cable plugged in while on the stand?
3. Viewing angle: fixed (default 65 deg) or adjustable?
4. Where does it stand (desk, bedside, kitchen) and must it be stable against tapping the screen?
5. Look: minimal block, rounded organic, or with text/logo? Colour (default: PLA Basic, white)?
6. One piece (default) or foldable/flat-packable?
7. Any size limit (e.g. fits in a bag)?
8. Supports acceptable? (default: design so none are needed)
9. How many to print?
10. Usability checks I suggest: phone doesn't tip when tapped top corner; cable fits with
    the plug's real dimensions; phone can be lifted out with one hand. Run all three?
