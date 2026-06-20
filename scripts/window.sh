#!/usr/bin/env bash
# Small COSMIC window helpers for computer-use runs.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

cmd="${1:-}"
case "$cmd" in
  maximize)
    # COSMIC default binding maximizes the FOCUSED window: Super+M
    # (from /usr/share/cosmic/.../Shortcuts/v1/defaults: (modifiers:[Super], key:"m"): Maximize).
    # The chord MUST go through mouse.py's real uinput keyboard — cosmic-comp
    # ignores wtype's virtual-keyboard protocol for global shortcuts.
    # Optional "X Y": click there first to SELECT/focus the target window, then maximize.
    if [ -n "${2:-}" ] && [ -n "${3:-}" ]; then
      python3 "$HERE/mouse.py" move "$2" "$3" click left >/dev/null
      sleep 0.4
    fi
    python3 "$HERE/mouse.py" key super+m
    ;;
  *)
    echo "usage: $0 maximize [X Y]   # X Y = click to focus the target window first" >&2
    exit 2
    ;;
esac
