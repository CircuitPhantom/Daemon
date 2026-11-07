"""Mouse and keyboard for the `computer` tool. This file runs on the LAPTOP (daemon-agent.py loads it through tools.py),
or on the server when Daemon itself runs on the computer you want to control.

It does not move anything by itself: it builds the commands of the programs that do, and picks them for your desktop.

  X11 (and XWayland-free sessions)       xdotool
  Wayland, any compositor                ydotool (needs the ydotoold service) for clicks, typing and keys;
                                         wtype for typing and keys when the compositor supports it (not GNOME)
  Hyprland / Sway, moving the pointer    hyprctl dispatch movecursor / swaymsg seat - cursor set  (exact positions)
                                         other Wayland desktops: ydotool mousemove --absolute

Arch:   sudo pacman -S ydotool wtype xdotool      (ydotool: systemctl --user enable --now ydotool; your user needs the
        `input` group, or the ydotoold socket: see the ydotool wiki page)
Check:  python daemon-agent.py --test-input       shows what was found and moves the pointer to the middle of the screen

The model works in the coordinates of the screenshot it was shown (`grab_geometry` in tools.py remembers how that picture
relates to the real screen). One screen is supported; with several screens use the main one.
"""
import json
import os
import re
import shutil
import subprocess
import time

BUTTONS = {"left": 1, "middle": 2, "right": 3}
YDO_BUTTON = {"left": 0, "right": 1, "middle": 2}            # ydotool click: 0xC0 + n = click, 0x40 + n = down, 0x80 + n = up
MODS = {"ctrl": "ctrl", "control": "ctrl", "alt": "alt", "shift": "shift", "super": "super", "win": "super", "meta": "super",
        "logo": "super", "cmd": "super"}
MOD_ORDER = ["ctrl", "alt", "shift", "super"]
MOD_CODE = {"ctrl": 29, "shift": 42, "alt": 56, "super": 125}
WTYPE_MOD = {"ctrl": "ctrl", "alt": "alt", "shift": "shift", "super": "logo"}
# name: (xdotool / wtype key name, evdev code)
KEYS = {"enter": ("Return", 28), "return": ("Return", 28), "esc": ("Escape", 1), "escape": ("Escape", 1), "tab": ("Tab", 15),
        "space": ("space", 57), "backspace": ("BackSpace", 14), "delete": ("Delete", 111), "del": ("Delete", 111),
        "insert": ("Insert", 110), "up": ("Up", 103), "down": ("Down", 108), "left": ("Left", 105), "right": ("Right", 106),
        "home": ("Home", 102), "end": ("End", 107), "pageup": ("Page_Up", 104), "pagedown": ("Page_Down", 109),
        "minus": ("minus", 12), "equal": ("equal", 13), "comma": ("comma", 51), "period": ("period", 52), "slash": ("slash", 53),
        "semicolon": ("semicolon", 39), "apostrophe": ("apostrophe", 40), "grave": ("grave", 41), "backslash": ("backslash", 43),
        "bracketleft": ("bracketleft", 26), "bracketright": ("bracketright", 27), "print": ("Print", 99),
        "capslock": ("Caps_Lock", 58), "menu": ("Menu", 127),
        "super": ("Super_L", 125), "ctrl": ("Control_L", 29), "alt": ("Alt_L", 56), "shift": ("Shift_L", 42)}  # pressed alone
for _i, _c in enumerate("qwertyuiop"):
    KEYS[_c] = (_c, 16 + _i)
for _i, _c in enumerate("asdfghjkl"):
    KEYS[_c] = (_c, 30 + _i)
for _i, _c in enumerate("zxcvbnm"):
    KEYS[_c] = (_c, 44 + _i)
for _i, _c in enumerate("1234567890"):
    KEYS[_c] = (_c, 2 + _i)
for _i in range(1, 13):
    KEYS[f"f{_i}"] = (f"F{_i}", 59 + _i - 1 if _i <= 10 else 87 + _i - 11)
ALIASES = {"pgup": "pageup", "page_up": "pageup", "pgdn": "pagedown", "page_down": "pagedown", "ret": "enter", "-": "minus",
           "=": "equal", ",": "comma", ".": "period", "/": "slash", ";": "semicolon", "'": "apostrophe", "`": "grave",
           "\\": "backslash", "[": "bracketleft", "]": "bracketright", " ": "space"}
# a window like these gets no typed text (a password prompt, a password manager, an authentication dialog)
SENSITIVE_WINDOW = re.compile(r"password|passphrase|parola|şifre|sifre|bitwarden|keepass|1password|lastpass|proton pass|"
                              r"authenticat|polkit|sudo|unlock|pinentry|gnome-keyring|kwallet", re.I)

runner = None            # tests replace this: fn(argv, timeout) -> (ok, output)


class InputError(Exception):
    pass


def run(argv, timeout=6):
    argv = [str(a) for a in argv]
    if runner is not None:
        return runner(argv, timeout)
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return False, f"{argv[0]} is not installed"
    except subprocess.TimeoutExpired:
        return False, f"{argv[0]} did not answer"
    return r.returncode == 0, (r.stdout + r.stderr).strip()


# ── keys ──
def parse_combo(text):
    """'Ctrl+Shift+T' -> (['ctrl', 'shift'], 't'). Raises InputError for something that is not a key press."""
    parts = [ALIASES.get(p, p) for p in str(text).strip().lower().replace(" ", "").split("+") if p]
    if not parts:
        raise InputError("no key given")
    *mod_parts, key = parts
    mods = []
    for p in mod_parts:
        if p not in MODS:
            raise InputError(f"'{p}' is not a modifier (ctrl, alt, shift, super)")
        if MODS[p] not in mods:
            mods.append(MODS[p])
    if key in MODS:
        if mods:
            raise InputError("a key is missing after the modifiers, e.g. ctrl+c")
        key = MODS[key]                                   # just the Super key (some launchers open on it)
    if key not in KEYS:
        raise InputError(f"unknown key '{key}'. Use letters, digits, enter, esc, tab, space, backspace, delete, arrows, "
                         "home, end, pageup, pagedown, print, f1-f12, with ctrl/alt/shift/super and +")
    return sorted(mods, key=MOD_ORDER.index), key


def norm_combo(text):
    """'Ctrl + Alt + Delete' -> 'ctrl+alt+delete' (for the blocked list)."""
    try:
        mods, key = parse_combo(str(text).replace(" ", ""))
    except InputError:
        return str(text).lower().replace(" ", "")
    return "+".join(mods + [key])


# ── what this desktop has ──
def session():
    if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_SESSION_TYPE") == "wayland":
        return "wayland"
    return "x11" if os.environ.get("DISPLAY") else "none"


def compositor():
    d = (os.environ.get("XDG_CURRENT_DESKTOP") or "").lower()
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") or "hyprland" in d:
        return "hyprland"
    if os.environ.get("SWAYSOCK") or "sway" in d:
        return "sway"
    return "kde" if "kde" in d else "gnome" if "gnome" in d else d or "unknown"


def detect():
    s, comp = session(), compositor()
    has = lambda n: bool(shutil.which(n)) if runner is None else True
    found = {n: has(n) for n in ("xdotool", "ydotool", "wtype", "hyprctl", "swaymsg")}
    if s == "x11":
        ok = found["xdotool"]
        return {"session": s, "compositor": comp, "found": found, "move": "xdotool" if ok else "", "click": "xdotool" if ok else "",
                "type": "xdotool" if ok else "", "key": "xdotool" if ok else "", "scroll": "xdotool" if ok else "",
                "missing": [] if ok else ["xdotool"]}
    if s == "wayland":
        move = "hyprctl" if comp == "hyprland" and found["hyprctl"] else "swaymsg" if comp == "sway" and found["swaymsg"] else \
            "ydotool" if found["ydotool"] else ""
        click = "ydotool" if found["ydotool"] else "swaymsg" if comp == "sway" and found["swaymsg"] else ""
        typ = "wtype" if found["wtype"] and comp != "gnome" else "ydotool" if found["ydotool"] else ""
        key = typ
        scroll = "ydotool" if found["ydotool"] else ""
        missing = [n for n, v in (("ydotool", move == "" or click == "" or scroll == ""), ("wtype or ydotool", typ == "")) if v]
        return {"session": s, "compositor": comp, "found": found, "move": move, "click": click, "type": typ, "key": key,
                "scroll": scroll, "missing": missing}
    return {"session": s, "compositor": comp, "found": found, "move": "", "click": "", "type": "", "key": "", "scroll": "",
            "missing": ["a graphical session (DISPLAY or WAYLAND_DISPLAY)"]}


def describe(d=None):
    d = d or detect()
    out = [f"session: {d['session']} ({d['compositor']})",
           "found: " + (", ".join(n for n, v in d["found"].items() if v) or "nothing")]
    for k in ("move", "click", "type", "key", "scroll"):
        out.append(f"{k}: {d[k] or 'NOT AVAILABLE'}")
    if d["missing"]:
        out.append("missing: " + ", ".join(d["missing"]))
    return "\n".join(out)


# ── the commands (lists of argv, so they can be checked without a desktop) ──
def cmd_move(d, x, y):
    x, y = int(round(x)), int(round(y))
    b = d["move"]
    if b == "xdotool":
        return [["xdotool", "mousemove", "--sync", x, y]]
    if b == "hyprctl":
        return [["hyprctl", "dispatch", "movecursor", x, y]]
    if b == "swaymsg":
        return [["swaymsg", "seat", "-", "cursor", "set", x, y]]
    if b == "ydotool":
        return [["ydotool", "mousemove", "--absolute", "-x", x, "-y", y]]
    raise InputError("no way to move the pointer: " + ", ".join(d["missing"]))


def cmd_click(d, button="left", count=1):
    button = button if button in BUTTONS else "left"
    b = d["click"]
    if b == "xdotool":
        c = ["xdotool", "click"] + (["--repeat", count, "--delay", 90] if count > 1 else []) + [BUTTONS[button]]
        return [c]
    if b == "ydotool":
        c = ["ydotool", "click"] + (["--repeat", count, "--next-delay", 90] if count > 1 else []) + [hex(0xC0 + YDO_BUTTON[button])]
        return [c]
    if b == "swaymsg":
        n = {"left": "button1", "middle": "button2", "right": "button3"}[button]
        return [["swaymsg", "seat", "-", "cursor", act, n] for _ in range(count) for act in ("press", "release")]
    raise InputError("no way to click: " + ", ".join(d["missing"]))


def cmd_button(d, down, button="left"):
    b = d["click"]
    if b == "xdotool":
        return [["xdotool", "mousedown" if down else "mouseup", BUTTONS[button]]]
    if b == "ydotool":
        return [["ydotool", "click", hex((0x40 if down else 0x80) + YDO_BUTTON[button])]]
    if b == "swaymsg":
        return [["swaymsg", "seat", "-", "cursor", "press" if down else "release", {"left": "button1", "middle": "button2", "right": "button3"}[button]]]
    raise InputError("no way to press a mouse button: " + ", ".join(d["missing"]))


def cmd_type(d, text):
    b = d["type"]
    if b == "xdotool":
        return [["xdotool", "type", "--delay", 12, "--", text]]
    if b == "wtype":
        return [["wtype", "-d", 12, "--", text]]
    if b == "ydotool":
        return [["ydotool", "type", "--key-delay", 12, "--", text]]
    raise InputError("no way to type: " + ", ".join(d["missing"]))


PUNCT = {"minus", "equal", "comma", "period", "slash", "semicolon", "apostrophe", "grave", "backslash", "bracketleft", "bracketright"}
_keymap = {"name": None}


def keymap(d):
    """The active keyboard layout's name on Hyprland ('Turkish', 'English (US)' ...), '' when unknown. Asked once."""
    if _keymap["name"] is None:
        _keymap["name"] = ""
        if d.get("move") == "hyprctl" or d.get("found", {}).get("hyprctl"):
            ok, raw = run(["hyprctl", "-j", "devices"])
            try:
                kbs = json.loads(raw).get("keyboards", []) if ok else []
                kb = next((k for k in kbs if k.get("main")), kbs[0] if kbs else {})
                _keymap["name"] = str(kb.get("active_keymap") or "")
            except (ValueError, AttributeError):
                pass
    return _keymap["name"]


def cmd_key(d, combo):
    mods, key = parse_combo(combo)
    xkey, code = KEYS[key]
    b = d["key"]
    if b == "wtype" and d.get("found", {}).get("ydotool") and key not in PUNCT:
        b = "ydotool"            # a real (uinput) keyboard: the desktop and every app (Blender, XWayland) see its modifiers;
                                 # wtype's virtual keyboard loses them in some apps. Punctuation stays on wtype (layouts differ)
        if key == "i" and re.search(r"turkish|\btr\b", keymap(d), re.I) and not re.search(r"\bf\b|f-", keymap(d), re.I):
            code = 40            # Turkish Q: the i key sits where US has the apostrophe (US i = ı there)
    if b == "xdotool":
        return [["xdotool", "key", "--", "+".join(mods + [xkey])]]
    if b == "wtype":
        argv = ["wtype"]
        for m in mods:
            argv += ["-M", WTYPE_MOD[m]]
        argv += ["-k", xkey]
        for m in reversed(mods):
            argv += ["-m", WTYPE_MOD[m]]
        return [argv]
    if b == "ydotool":
        seq = [f"{MOD_CODE[m]}:1" for m in mods] + [f"{code}:1", f"{code}:0"] + [f"{MOD_CODE[m]}:0" for m in reversed(mods)]
        return [["ydotool", "key"] + seq]
    raise InputError("no way to press keys: " + ", ".join(d["missing"]))


def cmd_scroll(d, amount):
    """amount > 0 scrolls down, < 0 up (in notches)."""
    n = abs(int(amount))
    b = d["scroll"]
    if b == "xdotool":
        return [["xdotool", "click", "--repeat", n, "--delay", 40, 5 if amount > 0 else 4]]
    if b == "ydotool":
        return [["ydotool", "mousemove", "--wheel", "-x", 0, "-y", -n if amount > 0 else n]]
    raise InputError("no way to scroll: " + ", ".join(d["missing"]))


def execute(cmds):
    for c in cmds:
        ok, out = run(c)
        if not ok:
            hint = ""
            if c[0] == "ydotool" and re.search(r"socket|connect|ydotoold|refused|permission", out, re.I):
                hint = " (is the ydotoold service running? systemctl --user enable --now ydotool)"
            raise InputError(f"{c[0]} failed: {out[:160] or 'no details'}{hint}")


# ── the pointer position the compositor needs ──
def logical_screen(d):
    """(x, y, width, height) of ALL screens together, in the units the pointer commands use (the screenshot covers all of them),
    or None when that is the same as the screenshot's real size (X11 and ydotool)."""
    try:
        if d["move"] == "hyprctl":
            ok, out = run(["hyprctl", "-j", "monitors"])
            boxes = []
            for m in (json.loads(out) if ok else []):
                sc = float(m.get("scale") or 1) or 1
                w, h = m["width"], m["height"]
                if m.get("transform") in (1, 3, 5, 7):
                    w, h = h, w
                boxes.append((m.get("x", 0), m.get("y", 0), w / sc, h / sc))
            return _union(boxes)
        if d["move"] == "swaymsg":
            ok, out = run(["swaymsg", "-t", "get_outputs", "-r"])
            return _union([(o["rect"]["x"], o["rect"]["y"], o["rect"]["width"], o["rect"]["height"])
                           for o in (json.loads(out) if ok else []) if o.get("rect") and o.get("active", True)])
    except (ValueError, KeyError, TypeError):
        pass
    return None


def monitors(d):
    """[{name, x, y, w, h, focused}] in pointer units (Hyprland, Sway), left to right; [] elsewhere."""
    out = []
    try:
        if d["move"] == "hyprctl":
            ok, raw = run(["hyprctl", "-j", "monitors"])
            for m in (json.loads(raw) if ok else []):
                sc = float(m.get("scale") or 1) or 1
                w, h = m["width"], m["height"]
                if m.get("transform") in (1, 3, 5, 7):
                    w, h = h, w
                out.append({"name": m.get("name", ""), "x": m.get("x", 0), "y": m.get("y", 0), "w": w / sc, "h": h / sc,
                            "focused": bool(m.get("focused")), "id": m.get("id"),
                            "ws": (m.get("activeWorkspace") or {}).get("id")})
        elif d["move"] == "swaymsg":
            ok, raw = run(["swaymsg", "-t", "get_outputs", "-r"])
            for o in (json.loads(raw) if ok else []):
                if o.get("rect") and o.get("active", True):
                    r = o["rect"]
                    out.append({"name": o.get("name", ""), "x": r["x"], "y": r["y"], "w": r["width"], "h": r["height"],
                                "focused": bool(o.get("focused"))})
    except (ValueError, KeyError, TypeError):
        return []
    return sorted(out, key=lambda m: (m["x"], m["y"]))


def _active_monitor_id(d):
    """Hyprland: the monitor id of the window that has the focus (the app just opened, usually), else None."""
    if d.get("move") != "hyprctl":
        return None
    ok, raw = run(["hyprctl", "-j", "activewindow"])
    try:
        return json.loads(raw).get("monitor") if ok and raw.strip().startswith("{") else None
    except ValueError:
        return None


def screen_windows(d):
    """Hyprland: {screen name: [app names of the windows shown on it]} (the visible workspace of each screen)."""
    if d.get("move") != "hyprctl":
        return {}
    mons = monitors(d)
    ok, raw = run(["hyprctl", "-j", "clients"])
    try:
        clients = json.loads(raw) if ok else []
    except ValueError:
        return {}
    out = {m["name"]: [] for m in mons}
    for c in clients:
        m = next((m for m in mons if m.get("id") == c.get("monitor")), None)
        if not m or c.get("hidden") or c.get("mapped") is False or (c.get("workspace") or {}).get("id") != m.get("ws"):
            continue
        name = str(c.get("class") or c.get("initialClass") or c.get("title") or "?")[:30]
        if name not in out[m["name"]]:
            out[m["name"]].append(name)
    return out


def monitor_box(d, name=""):
    """(x, y, w, h, name) of the screen called `name`; when name is empty / unknown, the screen of the window that has the focus,
    else the focused screen. None: no monitor list."""
    mons = monitors(d)
    act = _active_monitor_id(d) if not name or not any(m["name"].lower() == str(name).lower() for m in mons) else None
    m = next((m for m in mons if name and m["name"].lower() == str(name).lower()), None) \
        or next((m for m in mons if act is not None and m.get("id") == act), None) \
        or next((m for m in mons if m["focused"]), mons[0] if mons else None)
    return (m["x"], m["y"], m["w"], m["h"], m["name"]) if m else None


def focused_box(d):
    """(x, y, width, height) of the screen that has the focus, in pointer units (Hyprland, Sway), else None."""
    b = monitor_box(d)
    return b[:4] if b else None


HYPR_MODS = ((64, "SUPER"), (4, "CTRL"), (8, "ALT"), (1, "SHIFT"))
NOTES_FILE = os.path.expanduser("~/.daemon-shortcuts.txt")


HYPR_DIR = os.path.expanduser("~/.config/hypr")
_LUA_DSP = re.compile(r"^HL\.Dispatcher\((\w+)\)\s*\d*$")
_EXEC = re.compile(r"exec|spawn", re.I)
_BINDISH = re.compile(r"bind|key|map", re.I)
_VARS = re.compile(r"^\s*(local\s+)?\$?(terminal|term|browser|launcher|menu|file_?manager|editor)\s*=", re.I)
_LUA_BIND = re.compile(r"""bind\w*\(\s*["']([^"']+)["']\s*,.*?exec(?:_cmd)?\(\s*(?:"([^"]*)"|'([^']*)'|\[\[(.*?)\]\]|(\w+))""", re.I)


def _hypr_binds():
    """[(combo, dispatcher, arg)] from hyprctl. With the Lua config the dispatcher only reads 'HL.Dispatcher(exec_cmd) 7'
    (arg unknown): then dispatcher = 'exec_cmd' and arg = None."""
    ok, out = run(["hyprctl", "-j", "binds"])
    if not ok:
        return []
    try:
        binds = json.loads(out)
    except ValueError:
        return []
    res, seen = [], set()
    for b in binds:
        key = str(b.get("key") or "").lower()
        if b.get("mouse") or not key or key.startswith(("mouse", "xf86")) or b.get("submap") not in (None, "", "global"):
            continue
        mask = int(b.get("modmask") or 0)
        combo = "+".join([n for bit, n in HYPR_MODS if mask & bit] + [str(b["key"])]).lower()
        if combo in seen:
            continue
        seen.add(combo)
        dsp, arg = str(b.get("dispatcher") or ""), str(b.get("arg") or "").strip()
        m = _LUA_DSP.match(dsp) or _LUA_DSP.match(arg)
        if m:
            dsp, arg = m.group(1), None
        desc = (b.get("description") or "").strip()
        res.append((combo, dsp, arg, desc))
    return res


def _norm_bind(combo):
    """'SUPER + SHIFT + Slash' -> 'super+shift+slash' (hyprctl's spelling)."""
    parts = [p.strip().lower() for p in str(combo).replace("$mainMod", "SUPER").split("+") if p.strip()]
    mods = [p for p in parts if p in ("super", "ctrl", "control", "alt", "shift", "mod4")]
    rest = [p for p in parts if p not in mods]
    names = {"control": "ctrl", "mod4": "super"}
    order = ["super", "ctrl", "alt", "shift"]
    mods = sorted({names.get(m, m) for m in mods}, key=order.index)
    return "+".join(mods + rest)


def _config_programs():
    """{combo: command} from the Lua / conf files: what a key starts (hyprctl does not tell with the Lua config)."""
    out, variables = {}, {}
    for root, dirs, names in os.walk(HYPR_DIR, followlinks=True):
        if root.count(os.sep) - HYPR_DIR.count(os.sep) >= 4:
            dirs[:] = []
        for n in sorted(names):
            if not n.endswith((".lua", ".conf")):
                continue
            try:
                p = os.path.join(root, n)
                if os.path.getsize(p) > 300_000:
                    continue
                text = open(p, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            for m in re.finditer(r"^\s*(?:local\s+)?(\w+)\s*=\s*[\"']([^\"']+)[\"']", text, re.M):
                variables[m.group(1)] = m.group(2)
            for m in _LUA_BIND.finditer(text):
                cmd = next((g for g in m.groups()[1:] if g), "")
                out[_norm_bind(m.group(1))] = " ".join(variables.get(cmd, cmd).split())[:90]
            for m in re.finditer(r"^\s*bind\w*\s*=\s*([^,]*),\s*([^,]+),\s*exec\s*,\s*(.+)$", text, re.M):   # hyprland.conf
                combo = (m.group(1).strip() + " + " + m.group(2).strip()).replace(" ", " + ") if m.group(1).strip() else m.group(2)
                out[_norm_bind(combo)] = m.group(3).strip()[:90]
    return out


def _config_lines(limit=6000):
    """Lines of ~/.config/hypr that bind keys to programs, and the variables they use ($terminal, local browser = ...)."""
    out, size, files = [], 0, 0
    for root, dirs, names in os.walk(HYPR_DIR, followlinks=True):
        if root.count(os.sep) - HYPR_DIR.count(os.sep) >= 4:
            dirs[:] = []
        dirs[:] = [x for x in dirs if not x.startswith(".")]
        for n in sorted(names):
            if not n.endswith((".lua", ".conf")) or files >= 60:
                continue
            p = os.path.join(root, n)
            try:
                if os.path.getsize(p) > 300_000:
                    continue
                with open(p, encoding="utf-8", errors="replace") as f:
                    lines = f.read().splitlines()
            except OSError:
                continue
            files += 1
            got = []
            for ln in lines:
                s = " ".join(ln.split())
                if not s or s.startswith(("#", "--")):
                    continue
                if (_EXEC.search(s) and _BINDISH.search(s)) or _VARS.match(s):
                    got.append(s[:160])
            if got:
                block = os.path.relpath(p, HYPR_DIR) + ":\n" + "\n".join(got)
                if size + len(block) > limit:
                    block = block[:max(0, limit - size)]
                out.append(block)
                size += len(block)
            if size >= limit:
                return out
    return out


def shortcuts(d, limit=8500):
    """The desktop's keyboard shortcuts in a compact form, from Hyprland itself (hyprctl binds; with the Lua config also the
    config lines that say which program a key starts), plus the user's own notes in ~/.daemon-shortcuts.txt (any desktop)."""
    parts = []
    if d.get("move") == "hyprctl" or d.get("found", {}).get("hyprctl"):
        binds = _hypr_binds()
        progs = _config_programs() if any(a is None for _c, _w, a, _d in binds) or not binds else {}
        known, groups, unknown = [], {}, []
        for combo, what, arg, desc in binds:
            if desc:
                known.append(f"{combo}: {desc}"[:110])
            elif arg is None and what in ("exec_cmd", "exec"):
                if combo in progs:
                    known.append(f"{combo}: runs {progs[combo]}"[:110])
                else:
                    unknown.append(combo)
            elif arg:
                known.append(f"{combo}: {what} {arg}"[:110])
            else:
                groups.setdefault(what, []).append(combo)
        txt = []
        if known:
            txt.append("\n".join(known))
        if groups:
            txt.append("\n".join(f"{k}: {' '.join(v)}" for k, v in groups.items()))
        if unknown:
            txt.append(("start a program (not found which one): " if progs else
                        "start a program (which one: see the config lines below): ") + " ".join(unknown))
        if txt:
            parts.append("Hyprland key bindings (live, hyprctl binds; super+1..9 = workspaces; 'dms' = the DankMaterialShell "
                         "bar/launcher, e.g. spotlight = the app launcher):\n" + "\n".join(txt) if progs and any("dms" in v for v in progs.values())
                         else "Hyprland key bindings (live, hyprctl binds; grouped by what they do):\n" + "\n".join(txt))
        if (unknown and not progs) or not binds:
            cfg = _config_lines(max(1500, limit - sum(map(len, parts)) - 1500))
            if cfg:
                parts.append("From ~/.config/hypr (the lines that bind keys to programs):\n" + "\n".join(cfg))
    try:
        with open(NOTES_FILE, encoding="utf-8") as f:
            notes = f.read().strip()[:2500]
        if notes:
            parts.append("The user's own notes (" + NOTES_FILE.replace(os.path.expanduser("~"), "~") + "):\n" + notes)
    except OSError:
        pass
    return "\n\n".join(parts)[:limit]


def _union(boxes):
    if not boxes:
        return None
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[0] + b[2] for b in boxes), max(b[1] + b[3] for b in boxes)
    return x0, y0, x1 - x0, y1 - y0


_hypr = {"classic": None}          # does `hyprctl dispatch movecursor X Y` work on this Hyprland? (newer ones want Lua)


def move_to(d, x, y):
    """Puts the pointer at (x, y) in compositor units. Hyprland: the dispatcher, or when that does not work (newer versions use
    Lua syntax) ydotool relative moves steered by `hyprctl cursorpos` until the pointer is there."""
    x, y = int(round(x)), int(round(y))
    if d["move"] == "hyprctl" and _hypr["classic"] is not False:
        ok, out = run(["hyprctl", "dispatch", "movecursor", x, y])
        if ok and not re.search(r"error|expected|invalid", out, re.I):
            _hypr["classic"] = True
            return
        _hypr["classic"] = False
    if d["move"] == "hyprctl":
        if not d["found"].get("ydotool"):
            raise InputError("hyprctl cannot move the pointer on this Hyprland and ydotool is not installed")
        gain = 1.0
        for _ in range(10):
            pos = pointer_position(d)
            if pos is None:
                raise InputError("cannot read the pointer position (hyprctl cursorpos)")
            ex, ey = x - pos[0], y - pos[1]
            if abs(ex) <= 2 and abs(ey) <= 2:
                return
            sx, sy = int(round(ex / gain)), int(round(ey / gain))
            execute([["ydotool", "mousemove", "-x", sx, "-y", sy]])
            time.sleep(0.04)
            new = pointer_position(d)
            sent, moved = (sx * sx + sy * sy) ** 0.5, ((new[0] - pos[0]) ** 2 + (new[1] - pos[1]) ** 2) ** 0.5 if new else 0
            if sent > 10 and moved > 0:                              # learn how many pixels one ydotool unit really moves
                gain = max(0.1, min(10.0, moved / sent))
        raise InputError("could not place the pointer exactly (ydotool relative moves)")
    execute(cmd_move(d, x, y))


def to_screen(d, x, y, view, real, box=None):
    """Screenshot coordinates -> what the pointer command wants. view / real are (w, h); box = the area (x, y, w, h) the
    screenshot was taken of, in pointer units (when None: all screens on Hyprland / Sway, or the real size)."""
    if not view or not view[0]:
        raise InputError("take a screenshot first (computer action=screenshot): the coordinates refer to it")
    if not (0 <= x <= view[0] and 0 <= y <= view[1]):
        raise InputError(f"({x}, {y}) is outside the screenshot ({view[0]}x{view[1]})")
    ls = box or logical_screen(d)
    if ls:
        ox, oy, lw, lh = ls
        return ox + x * lw / view[0], oy + y * lh / view[1]
    rw, rh = real if real and real[0] else view
    return x * rw / view[0], y * rh / view[1]


def pointer_position(d):
    """Where the pointer is now, if the desktop can tell: (x, y) or None."""
    try:
        if d["compositor"] == "hyprland" and d["found"].get("hyprctl"):
            ok, out = run(["hyprctl", "cursorpos"])
            m = re.match(r"\s*(-?\d+),\s*(-?\d+)", out) if ok else None
            return (int(m.group(1)), int(m.group(2))) if m else None
        if d["session"] == "x11":
            ok, out = run(["xdotool", "getmouselocation"])
            m = re.match(r"x:(-?\d+) y:(-?\d+)", out) if ok else None
            return (int(m.group(1)), int(m.group(2))) if m else None
    except Exception:
        pass
    return None
