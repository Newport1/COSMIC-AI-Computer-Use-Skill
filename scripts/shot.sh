#!/usr/bin/env bash
# Quiet, non-interactive COSMIC screenshot for an AI observe→act loop.
# Prints the saved PNG path on stdout (last line) so callers can Read it.
# If scripts/mouse.py has written a last-commanded pointer state and ImageMagick
# is installed, prints an annotated copy with a synthetic cursor marker.
# Usage: shot.sh [save-dir]   (default: /tmp/ai-screen)
set -euo pipefail
DIR="${1:-/tmp/ai-screen}"
mkdir -p "$DIR"
IMG="$(cosmic-screenshot --interactive=false --notify=false --save-dir "$DIR" | tail -n 1)"
STATE="${COSMIC_CU_POINTER_STATE:-${XDG_RUNTIME_DIR:-/tmp}/cosmic-cu-pointer}"

if command -v convert >/dev/null 2>&1 && [ -r "$STATE" ]; then
  read -r X Y < <(python3 - "$STATE" <<'PY' 2>/dev/null || true
import json, sys
try:
    data = json.load(open(sys.argv[1]))
    print(int(data["x"]), int(data["y"]))
except Exception:
    pass
PY
)
  if [ -n "${X:-}" ] && [ -n "${Y:-}" ]; then
    OUT="${IMG%.png}.pointer.png"
    if convert "$IMG" \
      -stroke '#ff2d55' -strokewidth 3 \
      -draw "line $((X-18)),$Y $((X+18)),$Y line $X,$((Y-18)) $X,$((Y+18))" \
      -fill '#ff2d55' -stroke '#ffffff' -strokewidth 1 -pointsize 18 \
      -draw "text $((X+12)),$((Y-12)) '$X,$Y'" \
      "$OUT" 2>/dev/null; then
      echo "$OUT"
      exit 0
    fi
  fi
fi

echo "$IMG"
