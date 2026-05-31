#!/usr/bin/env bash
# embody-look.sh — capture ONE fresh still from the camera for vision analysis.
#
#   • Honors the camera privacy flag (~/.hermes/embody_camera_enabled; "0" = off).
#   • No preview (-n) so it NEVER draws over the kiosk face.
#   • Removes any prior capture FIRST, so the output path exists only if THIS
#     capture just succeeded — a stale frame can never be mistaken for "live".
#
# Prints the image path on success (hand it to vision_analyze); otherwise a
# single CAMERA_* line explaining why (and a non-zero exit).
#
# Deployed to ~/.local/bin/embody-look.sh on the Pi; versioned here in the repo.
set -uo pipefail

OUT="${1:-/tmp/embody_view.jpg}"
FLAG="$HOME/.hermes/embody_camera_enabled"

rm -f "$OUT"                                   # freshness guard: no stale leftovers

if [ -f "$FLAG" ] && [ "$(cat "$FLAG" 2>/dev/null)" = "0" ]; then
  echo "CAMERA_DISABLED: the camera is off for privacy. Ask the operator to turn the camera on from the touch panel to let you see."
  exit 3
fi

if rpicam-still -n --immediate --width 1296 --height 972 -o "$OUT" >/tmp/embody-look.err 2>&1 && [ -s "$OUT" ]; then
  echo "$OUT"
else
  echo "CAMERA_ERROR: capture failed — $(tail -1 /tmp/embody-look.err 2>/dev/null)"
  exit 1
fi
