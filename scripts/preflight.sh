#!/usr/bin/env bash
# Preflight: confirm the computer-use tools are present and, when possible,
# verify that the mouse helper actually moves the compositor pointer. Exit 0 if
# eyes+keyboard are available (the minimum); mouse is reported separately.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "session=$XDG_SESSION_TYPE desktop=${XDG_CURRENT_DESKTOP:-?}"
ok_eyes=0; ok_kbd=0; ok_mouse=0

command -v cosmic-screenshot >/dev/null && { echo "EYES: cosmic-screenshot ✓"; ok_eyes=1; } || echo "EYES: cosmic-screenshot ✗"
command -v wtype >/dev/null && { echo "KEYBOARD: wtype ✓"; ok_kbd=1; } || echo "KEYBOARD: wtype ✗"

# Mouse: the bundled persistent uinput helper. Needs rw on /dev/uinput.
if [ -w /dev/uinput ] || getfacl /dev/uinput 2>/dev/null | grep -q "user:$USER:rw"; then
  if python3 "$HERE/mouse.py" status >/dev/null 2>&1; then
    if command -v xdotool >/dev/null 2>&1 && command -v xterm >/dev/null 2>&1 && [ -n "${DISPLAY:-}" ]; then
      LOGDIR="${TMPDIR:-/tmp}/cu-run"; mkdir -p "$LOGDIR"
      xterm -geometry 220x60+250+120 -title cosmic-cu-preflight >/dev/null 2>"$LOGDIR/preflight-xterm.err" & xp=$!
      trap 'kill "$xp" 2>/dev/null || true' EXIT
      sleep 0.8
      xdotool search --name cosmic-cu-preflight windowactivate 2>/dev/null || true
      # First sanity-check the oracle: xdotool must see a known-good X move on
      # the Xterm surface before we trust it to judge uinput movement.
      xdotool mousemove 500 500 >/dev/null 2>&1 || true
      sleep 0.1
      before="$(xdotool getmouselocation 2>/dev/null || true)"
      python3 "$HERE/mouse.py" move 700 500 >/dev/null 2>&1 || true
      sleep 0.3
      after="$(xdotool getmouselocation 2>/dev/null || true)"
      if printf '%s\n' "$before" | grep -q 'x:500 y:500' && printf '%s\n' "$after" | grep -q 'x:700 y:500'; then
        echo "MOUSE: uinput helper ✓ (verified warp with Xwayland oracle)"; ok_mouse=1
      else
        echo "MOUSE: helper ran but warp verification failed (before='$before' after='$after')"
      fi
    else
      echo "MOUSE: uinput helper starts ✓ (install xdotool+xterm for warp verification)"; ok_mouse=1
    fi
  else echo "MOUSE: /dev/uinput writable but helper failed — see: python3 $HERE/mouse.py status"; fi
else
  echo "MOUSE: /dev/uinput not writable by $USER — keyboard-only mode"
fi

command -v switcherooctl >/dev/null && echo "GPU: switcherooctl ✓ (launch -g 1 = NVIDIA dGPU)" || echo "GPU: switcherooctl ✗ (use __NV_PRIME_RENDER_OFFLOAD=1 env)"
# cosmic-randr colorizes even when piped; strip ANSI before matching.
screen_info="$(cosmic-randr list 2>/dev/null | sed $'s/\x1b\\[[0-9;]*m//g' \
  | grep -oE '[0-9]+x[0-9]+ @[^(]*\(current\)|Scale: [0-9]+%' | paste -sd ' ' -)"
echo "screen: ${screen_info:-1920x1080 (assumed)}"
echo "SUMMARY: eyes=$ok_eyes keyboard=$ok_kbd mouse=$ok_mouse"
[ "$ok_eyes" = 1 ] && [ "$ok_kbd" = 1 ]
