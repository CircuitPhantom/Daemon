"""Mouse and keyboard on Windows for the `computer` tool (SendInput). screeninput.py calls this; nothing else does.

How it works
  pointer      SetCursorPos in real pixels (the process is per-monitor DPI aware, so negative coordinates of a screen left of or
               above the main one work and a 150 % scaled screen is not off by 50 %)
  clicks       SendInput mouse events at the pointer
  typing       SendInput with KEYEVENTF_UNICODE: the text arrives as characters, whatever keyboard layout is active
               (Turkish Q, English, ...). Some games, remote-desktop windows and a few terminals ignore that kind of input
  key presses  virtual keys. A single character key (a, 1, minus ...) means "the key that types that character on the active
               layout" (VkKeyScanEx), so ctrl+minus and a Turkish layout both do what a person would expect; named keys
               (enter, f5, arrows, ...) are the same on every layout
Limits that no program can get around (the tool answers with an error that says so): windows of programs running as administrator
(UIPI: a normal process cannot send them input), the lock screen, the sign-in screen and UAC prompts (secure desktop).
"""
import ctypes
import re
import sys
import time

# ctypes structures with explicit sizes (wintypes.DWORD is 8 bytes on Linux, which would make the tests lie)
u32, i32, u16 = ctypes.c_uint32, ctypes.c_int32, ctypes.c_uint16
ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", i32), ("dy", i32), ("mouseData", u32), ("dwFlags", u32), ("time", u32), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", u16), ("wScan", u16), ("dwFlags", u32), ("time", u32), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", u32), ("wParamL", u16), ("wParamH", u16)]


class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]       # all three: the union's size decides sizeof(INPUT)


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", u32), ("u", _U)]


INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x1, 0x2, 0x4
MOUSE_DOWN = {"left": 0x0002, "right": 0x0008, "middle": 0x0020}
MOUSE_UP = {"left": 0x0004, "right": 0x0010, "middle": 0x0040}
MOUSEEVENTF_WHEEL = 0x0800
WHEEL_DELTA = 120

MODS_VK = {"ctrl": 0xA2, "alt": 0xA4, "shift": 0xA0, "super": 0x5B}          # left ctrl / alt / shift / Windows key
NAMED_VK = {"enter": 0x0D, "esc": 0x1B, "tab": 0x09, "space": 0x20, "backspace": 0x08, "delete": 0x2E, "insert": 0x2D,
            "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
            "print": 0x2C, "capslock": 0x14, "menu": 0x5D}
for _i in range(1, 13):
    NAMED_VK[f"f{_i}"] = 0x70 + _i - 1
EXTENDED = {"delete", "insert", "up", "down", "left", "right", "home", "end", "pageup", "pagedown", "print", "menu", "super"}
PUNCT_CHAR = {"minus": "-", "equal": "=", "comma": ",", "period": ".", "slash": "/", "semicolon": ";", "apostrophe": "'",
              "grave": "`", "backslash": "\\", "bracketleft": "[", "bracketright": "]"}
US_VK = {"-": 0xBD, "=": 0xBB, ",": 0xBC, ".": 0xBE, "/": 0xBF, ";": 0xBA, "'": 0xDE, "`": 0xC0, "\\": 0xDC, "[": 0xDB, "]": 0xDD}
SHIFT, CTRL, ALT = 1, 2, 4            # VkKeyScan's shift-state bits


class InputBlocked(Exception):
    pass


# ───────────────────────── key resolution (pure, testable) ─────────────────────────
def resolve_key(key, scan=None):
    """(virtual key, extra modifiers) for the key name `key` (a name from screeninput.KEYS).
    `scan(char)` -> (vk, state) like VkKeyScanEx on the active layout, or None when the layout has no such character."""
    if key in NAMED_VK:
        return NAMED_VK[key], []
    if key in MODS_VK or key == "super":
        return MODS_VK[key], []
    ch = PUNCT_CHAR.get(key, key)
    hit = scan(ch) if scan and len(ch) == 1 else None
    if hit:
        vk, state = hit
        extra = [m for bit, m in ((SHIFT, "shift"), (CTRL, "ctrl"), (ALT, "alt")) if state & bit]       # AltGr is ctrl+alt
        return vk, extra
    if ch in US_VK:
        return US_VK[ch], []
    if len(ch) == 1 and ch.isalnum():
        return ord(ch.upper()), []
    raise InputBlocked(f"no key for '{key}'")


def key_events(mods, key, scan=None):
    """The events (kind, vk, up, extended) of one key press with modifiers, in order."""
    vk, extra = resolve_key(key, scan)
    allm = list(mods) + [m for m in extra if m not in mods]
    ev = [("key", MODS_VK[m], False, m == "super") for m in allm]
    ext = key in EXTENDED
    ev += [("key", vk, False, ext), ("key", vk, True, ext)]
    ev += [("key", MODS_VK[m], True, m == "super") for m in reversed(allm)]
    return ev


def text_events(text):
    """Unicode key events for `text` (UTF-16 code units, so emoji work). A tab becomes the Tab key; a newline must not get here."""
    ev = []
    for ch in text.replace("\r", ""):
        if ch == "\t":
            ev += [("key", NAMED_VK["tab"], False, False), ("key", NAMED_VK["tab"], True, False)]
            continue
        data = ch.encode("utf-16-le")
        for i in range(0, len(data), 2):
            unit = int.from_bytes(data[i:i + 2], "little")
            ev += [("uni", unit, False, False), ("uni", unit, True, False)]
    return ev


# ───────────────────────── Windows API ─────────────────────────
def _api():
    if sys.platform != "win32":
        raise InputBlocked("mouse and keyboard control is only available on Windows here")
    import win_desktop
    win_desktop.set_dpi_aware()                              # pointer coordinates must be real pixels
    return ctypes.windll.user32, ctypes.windll.kernel32


def _build(events):
    u, _ = _api()
    arr = (INPUT * len(events))()
    for i, e in enumerate(events):
        if e[0] == "mouse":                                   # ("mouse", flags, data)
            arr[i].type = INPUT_MOUSE
            arr[i].mi = MOUSEINPUT(0, 0, e[2] & 0xFFFFFFFF, e[1], 0, 0)
            continue
        kind, vk, up, ext = e
        arr[i].type = INPUT_KEYBOARD
        flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if ext else 0)
        if kind == "uni":
            arr[i].ki = KEYBDINPUT(0, vk, flags | KEYEVENTF_UNICODE, 0, 0)
        else:
            arr[i].ki = KEYBDINPUT(vk, u.MapVirtualKeyW(vk, 0) & 0xFFFF, flags, 0, 0)
    return arr


def send(events):
    """Sends the events with SendInput. Raises InputBlocked when Windows refuses (locked screen, UAC prompt, ...)."""
    if not events:
        return
    u, k = _api()
    arr = _build(events)
    u.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int]
    u.SendInput.restype = ctypes.c_uint
    n = u.SendInput(len(events), arr, ctypes.sizeof(INPUT))
    if n != len(events):
        raise InputBlocked(_refused(k.GetLastError()))


def _refused(code):
    return ("Windows refused the input"
            + (" (access denied: a locked screen, the sign-in screen or a UAC prompt is in front, or UIPI blocks it)" if code == 5 else
               " (the input is blocked by another thread, a locked screen or a secure prompt)" if code in (0, 1) else f" (error {code})"))


def set_cursor(x, y):
    u, _ = _api()
    if not u.SetCursorPos(int(x), int(y)):
        raise InputBlocked("Windows would not move the pointer (a locked screen or a secure prompt is in front)")


def get_cursor():
    import win_desktop
    return win_desktop.cursor_pos()


def layout_scan():
    """VkKeyScanEx for the keyboard layout of the window in front: scan(char) -> (vk, shift state) or None."""
    u, _ = _api()
    u.GetKeyboardLayout.restype = ctypes.c_void_p
    u.VkKeyScanExW.argtypes = [ctypes.c_wchar, ctypes.c_void_p]
    u.VkKeyScanExW.restype = ctypes.c_short
    pid = ctypes.c_uint32()
    h = u.GetForegroundWindow()
    tid = u.GetWindowThreadProcessId(h, ctypes.byref(pid)) if h else 0
    hkl = u.GetKeyboardLayout(tid)

    def scan(ch):
        r = u.VkKeyScanExW(ch, hkl)
        if r == -1 or (r & 0xFF) == 0xFF:
            return None
        return r & 0xFF, (r >> 8) & 0xFF
    return scan


# ───────────────────────── what a command does ─────────────────────────
def click(button, count):
    ev = []
    for i in range(count):
        ev.append(("mouse", MOUSE_DOWN[button], 0))
        ev.append(("mouse", MOUSE_UP[button], 0))
    if count == 1:
        send(ev)
        return
    for i in range(count):
        send(ev[2 * i:2 * i + 2])
        time.sleep(0.09)


def button(down, which):
    send([("mouse", (MOUSE_DOWN if down else MOUSE_UP)[which], 0)])


def scroll(notches):
    """notches > 0 scrolls down, < 0 up."""
    send([("mouse", MOUSEEVENTF_WHEEL, (-WHEEL_DELTA * int(notches)) & 0xFFFFFFFF)])


def type_text(text):
    ev = text_events(text)
    for i in range(0, len(ev), 64):                           # in pieces: a long text must not block the input queue
        send(ev[i:i + 64])
        time.sleep(0.005)


def do(op, *a):
    """Runs one command of screeninput's Windows command lists: ['win', op, args...]."""
    if op == "move":
        set_cursor(a[0], a[1])
    elif op == "click":
        click(a[0], int(a[1]))
    elif op == "button":
        button(bool(a[0]), a[1])
    elif op == "type":
        type_text(a[0])
    elif op == "key":
        send(key_events(list(a[0]), a[1], layout_scan()))
    elif op == "scroll":
        scroll(a[0])
    else:
        raise InputBlocked(f"unknown command {op}")


# ───────────────────────── administrator windows (UIPI) ─────────────────────────
def blocked_reason(point=None):
    """'' when input can reach the window (the one under `point`, else the one in front), else why not.
    A normal process cannot send input to a window of a program that runs as administrator."""
    try:
        u, k = _api()
        if _elevated(k, ctypes.windll.advapi32, k.GetCurrentProcess()):
            return ""
        if point:
            h = u.WindowFromPoint(ctypes.c_longlong(int(point[0]) & 0xFFFFFFFF | (int(point[1]) << 32)))
            h = u.GetAncestor(h, 2) if h else 0
        else:
            h = u.GetForegroundWindow()
        if not h:
            return ""
        pid = ctypes.c_uint32()
        u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        k.OpenProcess.restype = ctypes.c_void_p
        ph = k.OpenProcess(0x1000, False, pid.value)
        if not ph:
            return ("that window belongs to a program Windows does not let this agent touch (it runs as administrator or is a "
                    "system program)")
        try:
            e = _elevated(k, ctypes.windll.advapi32, ph)
        finally:
            k.CloseHandle(ph)
        if e:
            return ("the window runs as administrator: Windows does not let a normal program send it mouse or keys (UIPI). "
                    "Click or type there yourself, or start the agent as administrator (not recommended)")
    except Exception:
        return ""
    return ""


def _elevated(k, adv, proc):
    """True when the process behind the handle runs elevated (or its token cannot be opened by us, which means the same)."""
    tok = ctypes.c_void_p()
    adv.OpenProcessToken.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
    if not adv.OpenProcessToken(ctypes.c_void_p(proc), 0x8, ctypes.byref(tok)):      # TOKEN_QUERY
        return k.GetLastError() == 5
    try:
        elev = ctypes.c_uint32()
        size = ctypes.c_uint32()
        ok = adv.GetTokenInformation(tok, 20, ctypes.byref(elev), ctypes.sizeof(elev), ctypes.byref(size))      # TokenElevation
        return bool(ok and elev.value)
    finally:
        k.CloseHandle(tok)
