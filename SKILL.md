---
name: cosmic-computer-use
description: >-
  Drive a COSMIC / Wayland desktop as an autonomous computer-use agent — SEE the
  screen (cosmic-screenshot), then ACT with real mouse (a no-daemon uinput
  helper) and keyboard (wtype), in a screenshot → reason → act → verify loop like
  Anthropic's reference computer use. Use whenever you must operate a GUI app on
  this machine: smoke-test or QA a desktop app by clicking/typing through it,
  reproduce a UI bug, walk a UI flow, or confirm a visual change a human would
  normally check. Full pointer control (move/click/double/drag/scroll) plus
  keyboard and chords; launches apps on the discrete NVIDIA GPU. NOT for browser
  automation (use claude-in-chrome) or headless/CLI tasks (just run them).
---

# COSMIC Computer Use

You are a **computer-use agent**: you operate this COSMIC/Wayland desktop the way
a person would — by looking at the screen and moving the mouse and typing — to
accomplish a goal you cannot reach through the filesystem or CLI alone (e.g.
verifying that a GUI app actually *behaves* correctly when clicked through).

This skill is modeled on Anthropic's reference **computer use** loop
(https://claude.com/blog/skills): a tight **observe → think → act → verify**
cycle where every action is decided from a fresh screenshot and confirmed by the
next one. You never act blind, and you never assert a result you didn't see.

## Capabilities on this machine

| Sense / actuator | Tool | Notes |
|---|---|---|
| **Eyes** | `cosmic-screenshot` → save PNG → **Read** it | full-res, 1:1 with mouse coords. Does NOT capture the cursor — verify by *effect*, not pointer position. |
| **Mouse** | `scripts/mouse.py` (bundled uinput helper) | absolute coords in screen space; no daemon, no sudo (uses `/dev/uinput`). move/click/double/drag/scroll. prefer ydotool when available |
| **Keyboard** | `wtype` | type strings, single keys, modifier chords. |
| **Brain** | your vision | read the screenshot, decide ONE next action, take it, re-screenshot. |

Run `scripts/preflight.sh` first — it reports which of eyes/keyboard/mouse are
live so you know whether you're in full computer-use mode or keyboard-only
fallback.

## First: MAXIMIZE the app under test

Before driving an app, **maximize its window** — targeting is reliable on a
large, full-screen window with stable element positions, and error-prone on a
small or occluded one (the cursor is invisible in screenshots, so you can't see a
miss). This is the single biggest reliability win (learned the hard way: an
un-maximized, terminal-occluded window is what makes a computer-use run flail).

```bash
# focus the app (click its body), then maximize:
python3 ~/.claude/skills/cosmic-computer-use/scripts/mouse.py move <x> <y> click left
wtype -M logo -k Up -m logo          # Super+Up = maximize on COSMIC
```
A freshly `gpu-launch.sh`-ed window usually opens focused and on top; maximize it,
screenshot, and only then start the loop. If the controlling terminal keeps
stealing the view, relaunch the app fresh (a new window grabs focus).

## The loop (do this, every action)

1. **Observe** — capture and **Read** a screenshot:
   ```bash
   IMG="$(~/.claude/skills/cosmic-computer-use/scripts/shot.sh)"; echo "$IMG"
   ```
   Then Read `$IMG`. Describe what you see and where the target is (pixel x,y).
2. **Think** — state the single next action and the exact target coordinates or
   keys. Coordinates are full-res screen pixels (this box: 1920×1080), read
   directly off the screenshot.
3. **Act** — one action (below), then a short settle (`sleep`).
4. **Verify** — screenshot + Read again. Did the expected change happen? If not,
   diagnose (missed target? wrong element? not focused?) and adjust — do NOT
   repeat the same blind action.

Stop when the goal's success criteria are met (and seen), or when you're blocked
(say what's blocking and what you saw).

## Acting — mouse

```bash
M=~/.claude/skills/cosmic-computer-use/scripts/mouse.py
python3 $M move 960 540                 # move pointer (absolute)
python3 $M move 840 446 click left      # move then left-click (typical)
python3 $M click right                  # right-click at current spot
python3 $M double 1120 510              # double-click at (x,y)
python3 $M scroll -3                    # wheel: -down / +up (notches)
python3 $M drag 200 300 600 300         # press at (200,300), move to (600,300), release
```
Coordinates are read straight off the screenshot — observe FIRST, then click.
After a click that should change the UI, screenshot and confirm the change.

## Acting — keyboard (wtype)

```bash
wtype "hello world"                 # type a string
wtype -k Return                     # keys: Return Tab Escape BackSpace Delete Left Right Up Down Home End
wtype -k logo                       # Super key
wtype -M ctrl -k a -m ctrl          # chord: Ctrl+A  (press -M, key -k, release -m)
wtype -M alt  -k Tab -m alt         # Alt+Tab (switch windows)
```
Note: `wtype --help` is broken on this build (prints "Missing argument to
--help"); that's cosmetic — the tool works.

## Using this to QA an app (the orchestrator/tester split)

For a real test pass, use the two bundled agent profiles (`agents/`):
- **`ui-test-orchestrator`** — turns a goal into a concrete, checkable **test
  plan**: numbered cases, each with steps (click/type), the exact expected
  on-screen result, and a pass/fail criterion. It does NOT drive the UI.
- **`ui-tester`** — executes ONE test plan via the loop above, capturing a
  screenshot as evidence for every case, and returns a structured report
  (per-case PASS/FAIL with the evidence image path and what it observed).

Pattern: orchestrator writes the plan → tester runs it on the live app. Keep test
artifacts (screenshots) under `/tmp/cu-run/` or a named run dir.

## Verifying-by-effect (because the cursor is invisible in shots)

`cosmic-screenshot` doesn't capture the pointer, so you cannot see *where* the
mouse is. Always pick targets whose **hit produces an unmistakable change**
(navigation, a selection highlight, a panel opening) and confirm THAT, not the
cursor. "No change after a click" is ambiguous — it may be a miss OR a click on
inert space; re-aim using a known-reactive target before concluding.

## Limits & anti-patterns

- **Don't act blind** — screenshot + Read before and after every action.
- **Don't trust a single coordinate guess** on a small/scaled element — verify by
  effect and re-aim. Window chrome positions shift; re-observe after focus changes.
- **One action per cycle** for anything stateful; batch only obviously-safe
  sequences (type-then-Enter).
- Mouse needs `/dev/uinput` writable (it is here, via ACL). If preflight shows
  mouse ✗, fall back to keyboard navigation (Tab/arrows/hotkeys) and say so.

## Files
- `scripts/preflight.sh` — capability check (eyes/keyboard/mouse/GPU).
- `scripts/shot.sh` — quiet screenshot, prints the PNG path.
- `scripts/mouse.py` — no-daemon uinput pointer (move/click/double/drag/scroll).
- `references/agent-loop.md` — the loop in depth: targeting from screenshots,
  recovery when an action misses, evidence discipline.
- `agents/ui-test-orchestrator.md` — writes a checkable test plan from a goal.
- `agents/ui-tester.md` — executes a test plan via the loop, returns a report.
