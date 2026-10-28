#!/usr/bin/env bash
# Install the toolchain into a fresh sandbox. Safe to run again (skips what is present).
# Python libs come from pip; OpenSCAD, PrusaSlicer, Xvfb and fonts from apt when it is reachable.
# Prints one status line per tool; the skill works with reduced checks if apt is blocked.
set -u
quiet() { "$@" >/dev/null 2>&1; }

need_pip=()
for mod in trimesh manifold3d shapely rtree scipy networkx lxml matplotlib; do
  python3 -c "import $mod" 2>/dev/null || need_pip+=("$mod")
done
if [ ${#need_pip[@]} -gt 0 ]; then
  pip install -q --break-system-packages "${need_pip[@]}" >/dev/null 2>&1 \
    || pip install -q "${need_pip[@]}" >/dev/null 2>&1
fi

need_apt=()
command -v openscad >/dev/null || need_apt+=(openscad)
command -v prusa-slicer >/dev/null || need_apt+=(prusa-slicer)
command -v Xvfb >/dev/null || need_apt+=(xvfb)
fc-list 2>/dev/null | grep -qi "Liberation Sans" || need_apt+=(fonts-liberation)
if [ ${#need_apt[@]} -gt 0 ] && command -v apt-get >/dev/null; then
  SUDO=""; [ "$(id -u)" != "0" ] && command -v sudo >/dev/null && SUDO="sudo"
  quiet $SUDO apt-get update -q
  DEBIAN_FRONTEND=noninteractive quiet $SUDO apt-get install -y -q --no-install-recommends "${need_apt[@]}"
fi

ok() { if eval "$2" >/dev/null 2>&1; then echo "ok      $1"; else echo "MISSING $1  ($3)"; fi; }
ok "python mesh libs"  "python3 -c 'import trimesh, manifold3d, shapely, rtree, matplotlib'" "check_print/make_3mf will not run"
ok "openscad"          "command -v openscad"     "no .scad rendering; model in Python (trimesh/manifold3d) instead"
ok "xvfb (previews)"   "command -v Xvfb"         "previews fall back to matplotlib"
ok "prusa-slicer"      "command -v prusa-slicer" "skip slice_check.py; rely on check_print.py"
ok "fonts"             "fc-list | grep -qi 'Liberation Sans'" "text() in OpenSCAD may fail; pick a font from fc-list"
