#!/usr/bin/env python3
"""Self-contained uinput virtual ABSOLUTE pointer for COSMIC/Wayland computer-use.

No daemon, no root, no third-party deps — needs only rw on /dev/uinput (user1 has
it via ACL).  Creates a virtual absolute-positioned mouse whose coordinate space
is the screen (default 1920x1080), so coordinates read from a screenshot map 1:1.

Usage:
  uinput_mouse.py move X Y
  uinput_mouse.py click [left|right|middle]      (move first if you want a target)
  uinput_mouse.py move X Y click [left|right|middle]
  uinput_mouse.py double X Y
  uinput_mouse.py scroll N        (+up / -down, wheel notches)
  uinput_mouse.py drag X1 Y1 X2 Y2

Env: SCREEN_W, SCREEN_H override the 1920x1080 default.
"""
import ctypes, fcntl, os, struct, sys, time

SCREEN_W = int(os.environ.get("SCREEN_W", "1920"))
SCREEN_H = int(os.environ.get("SCREEN_H", "1080"))

# event types
EV_SYN, EV_KEY, EV_REL, EV_ABS = 0, 1, 2, 3
SYN_REPORT = 0
REL_WHEEL = 8
ABS_X, ABS_Y = 0, 1
BTN_LEFT, BTN_RIGHT, BTN_MIDDLE = 0x110, 0x111, 0x112

# ioctls (_IOW('U', n, int) on x86_64; _IO('U', n) for create/destroy)
UI_SET_EVBIT  = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_RELBIT = 0x40045566
UI_SET_ABSBIT = 0x40045567
UI_DEV_CREATE  = 0x5501
UI_DEV_DESTROY = 0x5502

BUTTONS = {"left": BTN_LEFT, "right": BTN_RIGHT, "middle": BTN_MIDDLE}


def _emit(fd, etype, code, value):
    # struct input_event: timeval(2*long) type(H) code(H) value(i)  -> "llHHi"
    os.write(fd, struct.pack("llHHi", 0, 0, etype, code, value))


def _syn(fd):
    _emit(fd, EV_SYN, SYN_REPORT, 0)


def open_device():
    fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    for ev in (EV_SYN, EV_KEY, EV_ABS, EV_REL):
        fcntl.ioctl(fd, UI_SET_EVBIT, ev)
    for b in (BTN_LEFT, BTN_RIGHT, BTN_MIDDLE):
        fcntl.ioctl(fd, UI_SET_KEYBIT, b)
    for a in (ABS_X, ABS_Y):
        fcntl.ioctl(fd, UI_SET_ABSBIT, a)
    fcntl.ioctl(fd, UI_SET_RELBIT, REL_WHEEL)

    # legacy uinput_user_dev: char name[80]; input_id(4*H); u32 ff_effects_max;
    # s32 absmax[64]; absmin[64]; absfuzz[64]; absflat[64]
    name = b"cosmic-cu-mouse".ljust(80, b"\0")
    bustype, vendor, product, version = 0x03, 0x1234, 0x5678, 1
    absmax = [0] * 64; absmin = [0] * 64; absfuzz = [0] * 64; absflat = [0] * 64
    absmax[ABS_X] = SCREEN_W - 1
    absmax[ABS_Y] = SCREEN_H - 1
    payload = name
    payload += struct.pack("HHHH", bustype, vendor, product, version)
    payload += struct.pack("I", 0)
    payload += struct.pack("64i", *absmax)
    payload += struct.pack("64i", *absmin)
    payload += struct.pack("64i", *absfuzz)
    payload += struct.pack("64i", *absflat)
    os.write(fd, payload)
    fcntl.ioctl(fd, UI_DEV_CREATE)
    time.sleep(0.4)  # let the compositor enumerate the new device
    return fd


def move(fd, x, y):
    x = max(0, min(SCREEN_W - 1, int(x)))
    y = max(0, min(SCREEN_H - 1, int(y)))
    _emit(fd, EV_ABS, ABS_X, x)
    _emit(fd, EV_ABS, ABS_Y, y)
    _syn(fd)
    time.sleep(0.05)


def click(fd, button="left"):
    b = BUTTONS[button]
    _emit(fd, EV_KEY, b, 1); _syn(fd); time.sleep(0.04)
    _emit(fd, EV_KEY, b, 0); _syn(fd); time.sleep(0.04)


def scroll(fd, n):
    _emit(fd, EV_REL, REL_WHEEL, int(n)); _syn(fd); time.sleep(0.05)


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__); return 2
    fd = open_device()
    try:
        i = 0
        did = False
        while i < len(a):
            cmd = a[i]
            if cmd == "move":
                move(fd, a[i+1], a[i+2]); i += 3; did = True
            elif cmd == "click":
                btn = a[i+1] if i+1 < len(a) and a[i+1] in BUTTONS else "left"
                click(fd, btn); i += 2 if btn != "left" or (i+1 < len(a) and a[i+1] in BUTTONS) else 1; did = True
            elif cmd == "double":
                move(fd, a[i+1], a[i+2]); click(fd); time.sleep(0.05); click(fd); i += 3; did = True
            elif cmd == "scroll":
                scroll(fd, a[i+1]); i += 2; did = True
            elif cmd == "drag":
                x1, y1, x2, y2 = a[i+1], a[i+2], a[i+3], a[i+4]
                move(fd, x1, y1)
                _emit(fd, EV_KEY, BTN_LEFT, 1); _syn(fd); time.sleep(0.08)
                move(fd, x2, y2); time.sleep(0.08)
                _emit(fd, EV_KEY, BTN_LEFT, 0); _syn(fd)
                i += 5; did = True
            else:
                print(f"unknown cmd: {cmd}", file=sys.stderr); return 2
        if did:
            print("ok")
        return 0
    finally:
        time.sleep(0.1)
        fcntl.ioctl(fd, UI_DEV_DESTROY)
        os.close(fd)


if __name__ == "__main__":
    sys.exit(main())
