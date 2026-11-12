#!/bin/sh
# freecad-cmd.sh -- run a Python script through FreeCAD's own interpreter, headlessly, on macOS.
#
# WHY THIS EXISTS: FreeCAD's macOS bundle ships NO `FreeCADCmd` binary (unlike Linux). What it does
# ship is a conda Python at Contents/Resources/bin/python plus the C++ modules as FreeCAD.so / Part.so
# in Contents/Resources/lib. Putting those on sys.path is what makes headless FreeCAD possible here.
# Verified 2026-11-12: FreeCAD 1.1.4, Python 3.11.14, Part kernel volume matches analytic to 0.001%.
#
# Usage:  scripts/freecad-cmd.sh /path/to/script.py [args...]
set -eu

FC_APP="${FC_APP:-/Applications/FreeCAD.app}"
RES="$FC_APP/Contents/Resources"
PY="$RES/bin/python"

[ -x "$PY" ] || { echo "FATAL: FreeCAD not installed at $FC_APP (no $PY)" >&2; exit 1; }
[ -f "$RES/lib/FreeCAD.so" ] || { echo "FATAL: FreeCAD.so missing under $RES/lib" >&2; exit 1; }

[ "$#" -ge 1 ] || { echo "usage: $0 <script.py> [args...]" >&2; exit 2; }
SCRIPT="$1"; shift

exec env \
  FC_PYTHONPATH="$RES/lib:$RES/Mod:$RES/bin" \
  DYLD_LIBRARY_PATH="$RES/lib" \
  "$PY" -c "
import sys, runpy
sys.path[:0] = ['$RES/lib', '$RES/Mod', '$RES/Mod/Part', '$RES/bin']
sys.argv = ['$SCRIPT'] + sys.argv[1:]
runpy.run_path('$SCRIPT', run_name='__main__')
" "$@"
