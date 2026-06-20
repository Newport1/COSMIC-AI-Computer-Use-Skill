#!/usr/bin/env python3
"""Persistent uinput absolute pointer for COSMIC/Wayland computer-use.

The default CLI commands auto-start a per-user daemon, send one command over a
Unix socket, and leave the virtual input device alive for later calls:

  mouse.py move X Y
  mouse.py click [left|right|middle]
  mouse.py move X Y click [left|right|middle]
  mouse.py double X Y
  mouse.py scroll N                 (+up / -down wheel notches)
  mouse.py drag X1 Y1 X2 Y2
  mouse.py key super+m              (COMPOSITOR shortcut via real uinput kbd:
                                     Super+M=maximize, alt+Tab, ctrl+w, Escape...)
  mouse.py status | stop | daemon

The daemon is intentionally self-contained (stdlib only) and uses /dev/uinput.
Coordinates are screenshot/physical pixels.  On COSMIC with 125% output scale,
empirical Xwayland-oracle testing showed ABS_X/ABS_Y values map to physical
screenshot pixels, not logical scaled pixels (500,500 lands at screenshot pixel
500,500), so no scale conversion is applied.
"""
from __future__ import annotations

import atexit
import errno
import fcntl
import json
import os
import re
import signal
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable

DEVICE_NAME = "cosmic-cu-mouse"
RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/cosmic-cu-{os.getuid()}")
SOCKET = Path(os.environ.get("COSMIC_CU_MOUSE_SOCKET", RUNTIME / "cosmic-cu-mouse.sock"))
STATE = Path(os.environ.get("COSMIC_CU_POINTER_STATE", RUNTIME / "cosmic-cu-pointer"))
LOG = Path(os.environ.get("COSMIC_CU_MOUSE_LOG", RUNTIME / "cosmic-cu-mouse.log"))

EV_SYN, EV_KEY, EV_REL, EV_ABS = 0, 1, 2, 3
SYN_REPORT = 0
REL_WHEEL = 8
ABS_X, ABS_Y = 0, 1
BTN_LEFT, BTN_RIGHT, BTN_MIDDLE, BTN_TOOL_MOUSE = 0x110, 0x111, 0x112, 0x146
INPUT_PROP_POINTER = 0x00
BUS_USB = 0x03

# ioctl constants from linux/uinput.h.  _IOW('U', n, int) is 0x40045500+n on
# Linux x86_64; UI_DEV_CREATE/DESTROY are _IO('U', n).
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_RELBIT = 0x40045566
UI_SET_ABSBIT = 0x40045567
UI_SET_PROPBIT = 0x4004556E
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502

BUTTONS = {"left": BTN_LEFT, "right": BTN_RIGHT, "middle": BTN_MIDDLE}

# Modifier + key names -> Linux input-event-codes.  Compositor shortcuts
# (Super+M = maximize, Alt+Tab, ...) only fire from a REAL input device, NOT from
# wtype's virtual-keyboard protocol, so they go through this uinput keyboard.
MODS = {
    "super": 125, "logo": 125, "meta": 125, "win": 125,  # KEY_LEFTMETA
    "ctrl": 29, "control": 29,                            # KEY_LEFTCTRL
    "alt": 56,                                            # KEY_LEFTALT
    "shift": 42,                                          # KEY_LEFTSHIFT
}
KEYS = {
    # letters
    "a": 30, "b": 48, "c": 46, "d": 32, "e": 18, "f": 33, "g": 34, "h": 35,
    "i": 23, "j": 36, "k": 37, "l": 38, "m": 50, "n": 49, "o": 24, "p": 25,
    "q": 16, "r": 19, "s": 31, "t": 20, "u": 22, "v": 47, "w": 17, "x": 45,
    "y": 21, "z": 44,
    # digits
    "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8, "8": 9, "9": 10, "0": 11,
    # named keys (lowercased on lookup)
    "escape": 1, "esc": 1, "tab": 15, "return": 28, "enter": 28, "space": 57,
    "backspace": 14, "delete": 111, "insert": 110,
    "up": 103, "down": 108, "left": 105, "right": 106,
    "home": 102, "end": 107, "pageup": 104, "pagedown": 109,
    "minus": 12, "equal": 13, "comma": 51, "period": 52, "slash": 53, "grave": 41,
    "f1": 59, "f2": 60, "f3": 61, "f4": 62, "f5": 63, "f6": 64,
    "f7": 65, "f8": 66, "f9": 67, "f10": 68, "f11": 87, "f12": 88,
}


def _runtime_init() -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)


def screen_geometry() -> tuple[int, int, str]:
    if os.environ.get("SCREEN_W") and os.environ.get("SCREEN_H"):
        return int(os.environ["SCREEN_W"]), int(os.environ["SCREEN_H"]), "env"

    try:
        out = subprocess.check_output(["cosmic-randr", "list"], text=True, stderr=subprocess.DEVNULL, timeout=2)
        out = re.sub(r"\x1b\[[0-9;]*m", "", out)  # cosmic-randr colorizes even when piped
        m = re.search(r"(\d+)x(\d+)\s+@[^\n]*\(current\)", out)
        if m:
            return int(m.group(1)), int(m.group(2)), "cosmic-randr"
    except Exception:
        pass

    for modes in Path("/sys/class/drm").glob("*/modes"):
        try:
            first = modes.read_text().splitlines()[0]
            m = re.match(r"(\d+)x(\d+)", first)
            if m:
                return int(m.group(1)), int(m.group(2)), str(modes)
        except Exception:
            continue

    return 1920, 1080, "fallback"


def _emit(fd: int, etype: int, code: int, value: int) -> None:
    os.write(fd, struct.pack("llHHi", 0, 0, etype, code, value))


def _syn(fd: int) -> None:
    _emit(fd, EV_SYN, SYN_REPORT, 0)


class UInputMouse:
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.fd = self._open_device()
        self.x = 0
        self.y = 0
        atexit.register(self.close)

    def _open_device(self) -> int:
        fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        for ev in (EV_SYN, EV_KEY, EV_ABS, EV_REL):
            fcntl.ioctl(fd, UI_SET_EVBIT, ev)
        for b in (BTN_LEFT, BTN_RIGHT, BTN_MIDDLE, BTN_TOOL_MOUSE):
            fcntl.ioctl(fd, UI_SET_KEYBIT, b)
        for a in (ABS_X, ABS_Y):
            fcntl.ioctl(fd, UI_SET_ABSBIT, a)
        fcntl.ioctl(fd, UI_SET_RELBIT, REL_WHEEL)
        fcntl.ioctl(fd, UI_SET_PROPBIT, INPUT_PROP_POINTER)

        name = DEVICE_NAME.encode()[:79].ljust(80, b"\0")
        absmax = [0] * 64
        absmin = [0] * 64
        absfuzz = [0] * 64
        absflat = [0] * 64
        absmax[ABS_X] = self.width - 1
        absmax[ABS_Y] = self.height - 1

        payload = name
        payload += struct.pack("HHHH", BUS_USB, 0x1234, 0x5678, 1)
        payload += struct.pack("I", 0)
        payload += struct.pack("64i", *absmax)
        payload += struct.pack("64i", *absmin)
        payload += struct.pack("64i", *absfuzz)
        payload += struct.pack("64i", *absflat)
        os.write(fd, payload)
        fcntl.ioctl(fd, UI_DEV_CREATE)
        self._wait_for_hotplug()
        # BTN_TOOL_MOUSE is the important bit: without it, cosmic-comp/libinput
        # sees the device in /proc but ignores ABS_X/ABS_Y as pointer motion.
        _emit(fd, EV_KEY, BTN_TOOL_MOUSE, 1)
        _syn(fd)
        return fd

    @staticmethod
    def _wait_for_hotplug() -> None:
        deadline = time.time() + 3.0
        while time.time() < deadline:
            try:
                if DEVICE_NAME in Path("/proc/bus/input/devices").read_text():
                    break
            except Exception:
                pass
            time.sleep(0.05)
        # udev/logind/libinput hotplug is async after /proc appears.  Keep the
        # daemon alive and wait generously once, instead of creating/destroying a
        # device for every click.
        time.sleep(float(os.environ.get("COSMIC_CU_HOTPLUG_SETTLE", "1.2")))

    def close(self) -> None:
        fd = getattr(self, "fd", None)
        if fd is None:
            return
        try:
            _emit(fd, EV_KEY, BTN_TOOL_MOUSE, 0)
            _syn(fd)
            fcntl.ioctl(fd, UI_DEV_DESTROY)
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass
        self.fd = None

    def _clamp(self, x: int, y: int) -> tuple[int, int]:
        return max(0, min(self.width - 1, int(x))), max(0, min(self.height - 1, int(y)))

    def _save_state(self) -> None:
        tmp = STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"x": self.x, "y": self.y, "width": self.width, "height": self.height}) + "\n")
        tmp.replace(STATE)

    def move(self, x: int, y: int) -> None:
        self.x, self.y = self._clamp(x, y)
        _emit(self.fd, EV_KEY, BTN_TOOL_MOUSE, 1)
        _emit(self.fd, EV_ABS, ABS_X, self.x)
        _emit(self.fd, EV_ABS, ABS_Y, self.y)
        _syn(self.fd)
        self._save_state()
        time.sleep(0.03)

    def click(self, button: str = "left") -> None:
        code = BUTTONS[button]
        _emit(self.fd, EV_KEY, BTN_TOOL_MOUSE, 1)
        _emit(self.fd, EV_KEY, code, 1)
        _syn(self.fd)
        time.sleep(0.05)
        _emit(self.fd, EV_KEY, code, 0)
        _syn(self.fd)
        time.sleep(0.04)

    def scroll(self, notches: int) -> None:
        _emit(self.fd, EV_REL, REL_WHEEL, int(notches))
        _syn(self.fd)
        time.sleep(0.04)


class UInputKeyboard:
    """Real uinput keyboard, for COMPOSITOR shortcuts (Super+M, Alt+Tab, ...).

    wtype types into apps but cosmic-comp ignores its virtual-keyboard protocol
    for global shortcuts; a real input device is required.  Keep wtype for typing
    text into the focused app; use this for window-manager chords.
    """

    def __init__(self) -> None:
        self.fd = self._open_device()
        atexit.register(self.close)

    def _open_device(self) -> int:
        fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        fcntl.ioctl(fd, UI_SET_EVBIT, EV_SYN)
        fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
        for code in set(MODS.values()) | set(KEYS.values()):
            fcntl.ioctl(fd, UI_SET_KEYBIT, code)
        name = b"cosmic-cu-kbd".ljust(80, b"\0")
        payload = name + struct.pack("HHHH", BUS_USB, 0x1234, 0x5679, 1) + struct.pack("I", 0)
        payload += struct.pack("64i", *([0] * 64)) * 4
        os.write(fd, payload)
        fcntl.ioctl(fd, UI_DEV_CREATE)
        # async hotplug, same lesson as the mouse — wait once, stay alive.
        time.sleep(float(os.environ.get("COSMIC_CU_HOTPLUG_SETTLE", "1.2")))
        return fd

    def combo(self, spec: str) -> None:
        parts = [p.strip().lower() for p in spec.split("+") if p.strip()]
        if not parts:
            raise ValueError("empty key combo")
        *mod_names, key_name = parts
        mods = []
        for m in mod_names:
            if m not in MODS:
                raise ValueError(f"unknown modifier: {m}")
            mods.append(MODS[m])
        if key_name not in KEYS:
            raise ValueError(f"unknown key: {key_name}")
        code = KEYS[key_name]
        for m in mods:
            _emit(self.fd, EV_KEY, m, 1)
            _syn(self.fd)
            time.sleep(0.02)
        _emit(self.fd, EV_KEY, code, 1)
        _syn(self.fd)
        time.sleep(0.06)
        _emit(self.fd, EV_KEY, code, 0)
        _syn(self.fd)
        time.sleep(0.02)
        for m in reversed(mods):
            _emit(self.fd, EV_KEY, m, 0)
            _syn(self.fd)
        time.sleep(0.03)

    def close(self) -> None:
        fd = getattr(self, "fd", None)
        if fd is None:
            return
        try:
            fcntl.ioctl(fd, UI_DEV_DESTROY)
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass
        self.fd = None


def execute(mouse: UInputMouse, keyboard: UInputKeyboard, argv: list[str]) -> str:
    i = 0
    did = False
    while i < len(argv):
        cmd = argv[i]
        if cmd == "key":
            keyboard.combo(argv[i + 1])
            i += 2
        elif cmd == "move":
            mouse.move(int(float(argv[i + 1])), int(float(argv[i + 2])))
            i += 3
        elif cmd == "click":
            button = argv[i + 1] if i + 1 < len(argv) and argv[i + 1] in BUTTONS else "left"
            mouse.click(button)
            i += 2 if i + 1 < len(argv) and argv[i + 1] in BUTTONS else 1
        elif cmd == "double":
            mouse.move(int(float(argv[i + 1])), int(float(argv[i + 2])))
            mouse.click("left")
            time.sleep(0.05)
            mouse.click("left")
            i += 3
        elif cmd == "scroll":
            mouse.scroll(int(float(argv[i + 1])))
            i += 2
        elif cmd == "drag":
            x1, y1, x2, y2 = map(lambda v: int(float(v)), argv[i + 1 : i + 5])
            mouse.move(x1, y1)
            _emit(mouse.fd, EV_KEY, BTN_LEFT, 1)
            _syn(mouse.fd)
            time.sleep(0.08)
            mouse.move(x2, y2)
            time.sleep(0.08)
            _emit(mouse.fd, EV_KEY, BTN_LEFT, 0)
            _syn(mouse.fd)
            i += 5
        else:
            raise ValueError(f"unknown cmd: {cmd}")
        did = True
    return "ok" if did else "noop"


def serve() -> int:
    _runtime_init()
    if SOCKET.exists():
        SOCKET.unlink()
    width, height, source = screen_geometry()
    mouse = UInputMouse(width, height)
    keyboard = UInputKeyboard()
    LOG.write_text(f"daemon pid={os.getpid()} geometry={width}x{height} source={source}\n")

    def stop(_signum=None, _frame=None):
        try:
            SOCKET.unlink()
        except FileNotFoundError:
            pass
        mouse.close()
        keyboard.close()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(SOCKET))
    os.chmod(SOCKET, 0o600)
    srv.listen(8)
    while True:
        conn, _ = srv.accept()
        with conn:
            data = conn.recv(4096).decode().strip()
            if not data:
                continue
            try:
                req = json.loads(data)
                argv = req.get("argv", [])
                if argv == ["status"]:
                    resp = {"ok": True, "status": "running", "pid": os.getpid(), "width": width, "height": height}
                elif argv == ["stop"]:
                    resp = {"ok": True, "status": "stopping"}
                    conn.sendall((json.dumps(resp) + "\n").encode())
                    stop()
                else:
                    resp = {"ok": True, "result": execute(mouse, keyboard, argv)}
            except Exception as exc:
                resp = {"ok": False, "error": str(exc)}
            conn.sendall((json.dumps(resp) + "\n").encode())


def _request(argv: Iterable[str]) -> dict:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect(str(SOCKET))
    s.sendall((json.dumps({"argv": list(argv)}) + "\n").encode())
    data = s.recv(4096).decode()
    s.close()
    return json.loads(data)


def _daemon_running() -> bool:
    try:
        return bool(_request(["status"]).get("ok"))
    except Exception:
        try:
            SOCKET.unlink()
        except FileNotFoundError:
            pass
        return False


def ensure_daemon() -> None:
    _runtime_init()
    if _daemon_running():
        return
    with LOG.open("ab") as log:
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "daemon"],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
            close_fds=True,
        )
    deadline = time.time() + 6.0
    while time.time() < deadline:
        if _daemon_running():
            return
        time.sleep(0.1)
    raise RuntimeError(f"mouse daemon did not start; see {LOG}")


def client(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help", "help"}:
        print(__doc__)
        return 0 if argv else 2
    if argv[0] == "daemon":
        return serve()
    ensure_daemon()
    resp = _request(argv)
    if not resp.get("ok"):
        print(resp.get("error", resp), file=sys.stderr)
        return 1
    if argv == ["status"]:
        print(json.dumps(resp, sort_keys=True))
    else:
        print(resp.get("result", "ok"))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(client(sys.argv[1:]))
    except BrokenPipeError:
        sys.exit(1)
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EPERM):
            print(f"permission denied opening /dev/uinput: {exc}", file=sys.stderr)
        else:
            print(str(exc), file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
