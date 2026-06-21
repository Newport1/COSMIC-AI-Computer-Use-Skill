# COSMIC AI Computer-Use Skill

A small, auditable skill that lets an AI agent **drive a COSMIC / POPOS / LINUX/ Wayland desktop**
the way a person would: take a screenshot, reason about it, then move the real
mouse and press real keys — an observe → act → verify loop.

It is deliberately tiny and dependency-light: a few stdlib-Python and shell
scripts, no compositor patches, no root.

## What works

| Capability | How |
|---|---|
| **See the screen** | `cosmic-screenshot` → PNG the agent reads |
| **See the pointer** | `cosmic-screenshot` can't capture the cursor, so `shot.sh` draws a synthetic crosshair at the last commanded pointer position (needs ImageMagick) |
| **Move / click / drag / scroll** | `scripts/mouse.py` — a persistent **uinput** virtual mouse, absolute coordinates in screenshot pixels |
| **Compositor shortcuts** (maximize, Alt+Tab…) | `scripts/mouse.py key super+m` — a real **uinput keyboard** |
| **Type into apps** | `wtype` |
| **Select + maximize a window** | `scripts/window.sh maximize [X Y]` |

## Two things that make this actually work on COSMIC

These were found the hard way; they are the difference between "the helper exits 0"
and "the pointer actually moves":

1. **The uinput mouse must advertise `BTN_TOOL_MOUSE` and emit it pressed.**
   cosmic-comp/libinput will see an `ABS_X/ABS_Y` device in `/proc/bus/input/devices`
   but ignore its motion as pointer input unless `BTN_TOOL_MOUSE` is present. With it,
   absolute coordinates map 1:1 to **physical screenshot pixels** (no scale math needed,
   even at 125% output scale).

2. **Compositor shortcuts need a *real* input device, not `wtype`.**
   cosmic-comp ignores `wtype`'s virtual-keyboard protocol for global shortcuts
   (Super+M, Alt+Tab, …). `wtype` still works fine for typing text *into* the focused
   app; window-manager chords go through `mouse.py key …` (a real uinput keyboard).

A third lesson is baked into the design: the device is **persistent** (a tiny per-user
daemon over a Unix socket in `$XDG_RUNTIME_DIR`), not created-and-destroyed per call —
cosmic-comp's udev→libinput hotplug is async and a per-call device is often destroyed
before it is ever added.

## Requirements

- A COSMIC / Wayland session.
- Write access to `/dev/uinput` (this is the only privileged bit). Typically granted by
  an ACL or by adding your user to the `input` group:
  `sudo setfacl -m u:$USER:rw /dev/uinput` (re-apply on reboot, or use a udev rule).
- `cosmic-screenshot` and `wtype` (required).
- Optional but recommended: `imagemagick` (the `convert` cursor overlay) and
  `xdotool` + `xterm` (lets `preflight.sh` *verify* pointer movement, not just that the
  helper ran).

Everything is stdlib Python 3 + bash; no pip installs.

## Quick start

```bash
scripts/preflight.sh           # reports eyes / keyboard / mouse, verifies a real warp
IMG=$(scripts/shot.sh /tmp/cu) # screenshot (+ cursor overlay); prints PNG path
python3 scripts/mouse.py move 960 540 click left
scripts/window.sh maximize 960 540   # click to select, then maximize
python3 scripts/mouse.py key alt+Tab
python3 scripts/mouse.py stop   # tear down the daemon + virtual devices
```

Coordinates are full-resolution screenshot pixels — read them straight off the PNG.

## Files

- `SKILL.md` — agent-facing instructions (the observe→act→verify loop).
- `scripts/preflight.sh` — capability check; verifies real pointer movement when `xdotool`+`xterm` exist.
- `scripts/shot.sh` — quiet screenshot, prints PNG path, optional cursor overlay.
- `scripts/mouse.py` — persistent uinput mouse **and** keyboard daemon (`move`/`click`/`double`/`drag`/`scroll`/`key`/`status`/`stop`).
- `scripts/window.sh` — window helpers (`maximize [X Y]`).
- `agents/` — optional orchestrator/tester agent profiles for QA runs.

## Safety

The scripts drive your real pointer and keyboard. They never click destructive buttons
on their own — the agent decides actions from screenshots. Keep runs observable, and use
`mouse.py stop` to remove the virtual devices when done.

Portable by design: no hardcoded paths, screen geometry auto-detected from `cosmic-randr`
(falling back to `/sys/class/drm`), runtime files under `$XDG_RUNTIME_DIR`.
