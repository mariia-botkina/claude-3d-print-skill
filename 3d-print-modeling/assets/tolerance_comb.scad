// Tolerance comb: finds the real fit clearances of YOUR printer + filament.
//
// Print the plate and the two test pins (flat on the bed, as exported).
// Try the round pin in each round hole and the square peg in each square
// hole, then note per row:
//   - the tightest hole the pin enters with firm hand pressure  -> press fit
//   - the tightest hole the pin slides through and turns freely -> sliding fit
//   - a hole where it moves with visible play                   -> loose fit
// The engraved number is the clearance PER SIDE in hundredths of a mm (15 = 0.15 mm),
// i.e. hole = pin + 2 x clearance.
// Write the results into references/printer-profile.md ("Measured fits").
//
// Render one part at a time:  openscad -D 'part="plate"' -o plate.stl tolerance_comb.scad
//                             openscad -D 'part="round_pin"' ...   'part="square_pin"'

/* [Part] */
part = "plate"; // [plate, round_pin, square_pin, all]

/* [Test] */
nominal = 8.0;            // pin diameter / peg side, mm
clearances = [0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40];
plate_thickness = 5.0;
pin_length = 12.0;
pitch = 14.0;
label_size = 5.0;          // big enough to engrave cleanly with a 0.4 nozzle
label_depth = 0.6;
chamfer = 0.4;            // on pin ends, hides elephant foot

$fn = 64;

n = len(clearances);
plate_w = n * pitch + 6;
plate_d = 2 * pitch + 16;

function label(c) = str(round(c * 100));

module plate() {
    difference() {
        cube([plate_w, plate_d, plate_thickness]);
        for (i = [0 : n - 1]) {
            x = 3 + pitch / 2 + i * pitch;
            c = clearances[i];
            // round holes, front row
            translate([x, 9 + pitch / 2, -1])
                cylinder(d = nominal + 2 * c, h = plate_thickness + 2);
            // square holes, back row
            translate([x, 9 + pitch * 1.5, plate_thickness / 2])
                cube([nominal + 2 * c, nominal + 2 * c, plate_thickness + 2], center = true);
            // engraved labels between the rows and at the front edge
            translate([x, 3.8, plate_thickness - label_depth])
                linear_extrude(label_depth + 1)
                    text(label(c), size = label_size, halign = "center", valign = "center",
                         font = "Liberation Sans:style=Bold");
        }
        // row markers
        translate([2.0, 9 + pitch / 2, plate_thickness - label_depth])
            linear_extrude(label_depth + 1) circle(d = 1.4);
        translate([2.0, 9 + pitch * 1.5, plate_thickness - label_depth])
            linear_extrude(label_depth + 1) square(1.4, center = true);
    }
}

module chamfered_cylinder(d, h, c) {
    hull() {
        translate([0, 0, c]) cylinder(d = d, h = h - 2 * c);
        cylinder(d = d - 2 * c, h = h);
    }
}

module round_pin() {
    // printed standing up, like most pins in real parts
    chamfered_cylinder(nominal, pin_length, chamfer);
}

module square_pin() {
    hull() {
        translate([0, 0, chamfer]) linear_extrude(pin_length - 2 * chamfer) square(nominal, center = true);
        linear_extrude(pin_length) square(nominal - 2 * chamfer, center = true);
    }
}

if (part == "plate") plate();
if (part == "round_pin") round_pin();
if (part == "square_pin") square_pin();
if (part == "all") {
    plate();
    translate([plate_w / 2 - 10, plate_d + 10, 0]) round_pin();
    translate([plate_w / 2 + 10, plate_d + 10 + nominal / 2, 0]) square_pin();
}
