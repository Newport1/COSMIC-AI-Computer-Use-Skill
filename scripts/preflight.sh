#!/usr/bin/env bash
# Preflight: confirm the computer-use tools are present and the mouse helper can
# create a uinput device. Prints a capability summary. Exit 0 if eyes+keyboard
# are available (the minimum); mouse is reported separately.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "session=$XDG_SESSION_TYPE desktop=${XDG_CURRENT_DESKTOP:-?}"
ok_eyes=0; ok_kbd=0; ok_mouse=0

command -v cosmic-screenshot >/dev/null && { echo "EYES: cosmic-screenshot ✓"; ok_eyes=1; } || echo "EYES: cosmic-screenshot ✗"
command -v wtype >/dev/null && { echo "KEYBOARD: wtype ✓"; ok_kbd=1; } || echo "KEYBOARD: wtype ✗"

# Mouse: the bundled uinput helper (no daemon). Needs rw on /dev/uinput.
if [ -w /dev/uinput ] || getfacl /dev/uinput 2>/dev/null | grep -q "user:$USER:rw"; then
  if python3 "$HERE/mouse.py" move 1 1 >/dev/null 2>&1; then
    echo "MOUSE: uinput helper ✓ (no daemon needed)"; ok_mouse=1
  else echo "MOUSE: /dev/uinput writable but helper failed — see: python3 $HERE/mouse.py move 1 1"; fi
else
  echo "MOUSE: /dev/uinput not writable by $USER — keyboard-only mode"
fi

command -v switcherooctl >/dev/null && echo "GPU: switcherooctl ✓ (launch -g 1 = NVIDIA dGPU)" || echo "GPU: switcherooctl ✗ (use __NV_PRIME_RENDER_OFFLOAD=1 env)"
echo "screen: $(cosmic-randr list 2>/dev/null | grep -oE '[0-9]+x[0-9]+ @.*current' | head -1 || echo '1920x1080 (assumed)')"
echo "SUMMARY: eyes=$ok_eyes keyboard=$ok_kbd mouse=$ok_mouse"
[ "$ok_eyes" = 1 ] && [ "$ok_kbd" = 1 ]
