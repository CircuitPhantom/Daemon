"""Windows desktop backend for the laptop tools: media keys, volume, clipboard, links, apps, Spotify, screenshots.

tools.py calls this only on Windows (platform_support.IS_WINDOWS); the result strings are the same as on Linux.
Everything Windows-specific is imported lazily and optional (the module itself imports fine on any OS, so the logic is testable):
  pycaw + comtypes                      exact volume (get / set / mute)
  winrt-* (Windows.Media.Control)       "what is playing", real play / pause, restart a track
  pillow                                screenshots
Without them the tools return a short error that says what to install; media keys still work.
"""
import ctypes
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

NO_WINDOW = 0x08000000
DETACHED = 0x00000008
NEW_GROUP = 0x00000200
WINRT_HINT = "pip install winrt-runtime winrt-Windows.Media.Control winrt-Windows.Foundation winrt-Windows.Foundation.Collections"
PLAYER_WAIT = 6

# ───────────────────────── Windows API ─────────────────────────
_dpi_done = [False]


def set_dpi_aware():
    """Pixels must be real pixels (screenshots and, later, mouse coordinates): per-monitor DPI awareness, once."""
    if _dpi_done[0] or sys.platform != "win32":
        return
    _dpi_done[0] = True
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))      # per-monitor v2
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _u32():
    return ctypes.windll.user32


def os_name():
    """'Windows 11, 2 screens': tells the model what it is working with."""
    try:
        build = sys.getwindowsversion().build
    except Exception:
        build = 0
    name = "Windows 11" if build >= 22000 else "Windows 10" if build else "Windows"
    try:
        n = len(monitors())
    except Exception:
        n = 0
    return name + (f", {n} screens" if n > 1 else "")


# ───────────────────────── media ─────────────────────────
VK = {"next": 0xB0, "previous": 0xB1, "stop": 0xB2, "play-pause": 0xB3, "mute": 0xAD, "down": 0xAE, "up": 0xAF}


def send_key(vk):
    """Presses one media / volume key (the same as the key on a keyboard)."""
    u = _u32()
    u.keybd_event(vk, 0, 1, 0)           # KEYEVENTF_EXTENDEDKEY
    u.keybd_event(vk, 0, 1 | 2, 0)       # ... | KEYEVENTF_KEYUP


def _smtc(action):
    """Runs `async action(session)` against the current Windows media session (None when nothing is playing).
    Raises ImportError when the winrt packages are not installed."""
    import asyncio

    async def go():
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager
        mgr = await Manager.request_async()
        return await action(mgr.get_current_session())
    return asyncio.run(go())


PLAYING, PAUSED = 4, 5
_STATUS = {0: "Stopped", 1: "Stopped", 2: "Paused", 3: "Stopped", 4: "Playing", 5: "Paused"}


async def _a_status(s):
    if s is None:
        return None
    pb = s.get_playback_info()
    try:
        info = await s.try_get_media_properties_async()
        meta = f"{info.artist} - {info.title}".strip(" -")
    except Exception:
        meta = ""
    app = re.sub(r"\.exe$", "", str(s.source_app_user_model_id or ""), flags=re.I).split("!")[-1].split(".")[-1]
    if re.fullmatch(r"[0-9A-Fa-f]{10,}", app):             # a Chrome / Edge web app registers a hash, not a name
        app = ""
    return _STATUS.get(int(pb.playback_status), "Stopped"), f"{meta} ({app})" if app else meta


def player_status():
    """(state, 'Artist - Title (app)') or None when nothing is playing. Raises ImportError without winrt."""
    return _smtc(_a_status)


def _call(name, *args):
    async def act(s):
        return None if s is None else bool(await getattr(s, name)(*args))
    return _smtc(act)


def _position():
    async def act(s):
        return None if s is None else s.get_timeline_properties().position.total_seconds()
    try:
        return _smtc(act)
    except Exception:
        return None


def _wait_player():
    end = time.monotonic() + PLAYER_WAIT
    while True:
        st = player_status()
        if st is not None:
            return True
        if time.monotonic() >= end:
            return False
        time.sleep(0.5)


def _is_playing():
    st = player_status()
    return bool(st and st[0] == "Playing")


def _start_playing():
    _call("try_play_async")
    time.sleep(0.5)
    if _is_playing():
        return "Done: play"
    _call("try_skip_next_async")
    time.sleep(0.8)
    if _is_playing():
        return "Done: play (the player had nothing loaded, so it started with the next track)"
    return "Error: the player did not start. Start something once in the app, then I can control it"


def media_control(a):
    """`a` is a valid, lower-cased action (tools.media_control checked it)."""
    try:
        return _media_smtc(a)
    except ImportError:
        pass
    except Exception as e:                                  # the media session API failed: fall back to the keys
        if a == "status":
            return f"Error: could not read the player ({type(e).__name__})"
    if a == "status":
        return f"Error: status needs the winrt packages ({WINRT_HINT})"
    if a in ("restart", "rewind"):
        return f"Error: restart needs the winrt packages ({WINRT_HINT})"
    key = {"play": "play-pause", "start": "play-pause", "pause": "play-pause", "toggle": "play-pause", "play-pause": "play-pause",
           "next": "next", "previous": "previous", "prev": "previous", "stop": "stop"}[a]
    send_key(VK[key])
    return f"Done: {a}"


def _media_smtc(a):
    if a == "status":
        st = player_status()
        return "Nothing is playing" if st is None else f"{st[0]}: {st[1]}"
    if not _wait_player():
        return "Nothing is playing. Start the player first (open_app), then try again"
    if a in ("restart", "rewind"):
        ok = _call("try_change_playback_position_async", 0)
        return "Done: restarted the current track" if ok else "Error: this player cannot jump to the start"
    playing = _is_playing()
    if a in ("play", "start") or (a in ("toggle", "play-pause") and not playing):
        return _start_playing()
    if a in ("pause", "toggle", "play-pause"):
        ok = _call("try_pause_async")
        return f"Done: {a}" if ok else "Error: the player refused to pause"
    if a == "stop":
        return f"Done: {a}" if _call("try_stop_async") else "Error: the player refused to stop"
    prev_pos = _position() or 0.0
    ok = _call("try_skip_next_async" if a == "next" else "try_skip_previous_async")
    if not ok:
        return "Error: the player refused"
    if a in ("previous", "prev"):
        time.sleep(0.4)
        pos = _position()
        if pos is not None and pos < 2.0 and prev_pos > 3.0:      # players restart the current track when it is past ~3 s: go back once more
            _call("try_skip_previous_async")
    time.sleep(0.5)
    if not _is_playing():
        _call("try_play_async")                              # skipping on a paused player should start it
    return f"Done: {a}"


# ───────────────────────── volume ─────────────────────────
def _endpoint():
    import comtypes
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    comtypes.CoInitialize()                                  # per thread; never uninitialised on purpose (the objects live on)
    dev = AudioUtilities.GetSpeakers()
    ep = getattr(dev, "EndpointVolume", None)                # newer pycaw wraps the device
    if ep is not None:
        return ep
    iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return ctypes.cast(iface, ctypes.POINTER(IAudioEndpointVolume))


def _vol_text(ep):
    return f"Volume is {round(float(ep.GetMasterVolumeLevelScalar()) * 100)}%" + (", muted" if ep.GetMute() else "")


def volume(lv):
    """`lv` is the lower-cased level text, already validated by tools.volume. Returns the same strings as on Linux."""
    try:
        ep = _endpoint()
    except ImportError:
        return "Error: volume needs pycaw (pip install pycaw)"
    except Exception as e:
        return f"Error: could not open the audio device ({type(e).__name__}: {e})"
    try:
        if lv == "status":
            return _vol_text(ep)
        if lv in ("mute", "unmute"):
            ep.SetMute(1 if lv == "mute" else 0, None)
        elif lv in ("up", "down"):
            cur = float(ep.GetMasterVolumeLevelScalar())
            ep.SetMasterVolumeLevelScalar(max(0.0, min(1.0, cur + (0.05 if lv == "up" else -0.05))), None)
        else:
            ep.SetMasterVolumeLevelScalar(max(0, min(100, int(lv))) / 100.0, None)
        return _vol_text(ep)
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


# ───────────────────────── clipboard ─────────────────────────
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def _clip_api():
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    u.OpenClipboard.argtypes, u.OpenClipboard.restype = [wintypes.HWND], wintypes.BOOL
    u.CloseClipboard.argtypes, u.CloseClipboard.restype = [], wintypes.BOOL
    u.EmptyClipboard.argtypes, u.EmptyClipboard.restype = [], wintypes.BOOL
    u.GetClipboardData.argtypes, u.GetClipboardData.restype = [wintypes.UINT], wintypes.HANDLE
    u.SetClipboardData.argtypes, u.SetClipboardData.restype = [wintypes.UINT, wintypes.HANDLE], wintypes.HANDLE
    k.GlobalAlloc.argtypes, k.GlobalAlloc.restype = [wintypes.UINT, ctypes.c_size_t], wintypes.HGLOBAL
    k.GlobalLock.argtypes, k.GlobalLock.restype = [wintypes.HGLOBAL], ctypes.c_void_p
    k.GlobalUnlock.argtypes, k.GlobalUnlock.restype = [wintypes.HGLOBAL], wintypes.BOOL
    k.GlobalFree.argtypes, k.GlobalFree.restype = [wintypes.HGLOBAL], wintypes.HGLOBAL
    return u, k


def _open_clipboard(u):
    for _ in range(20):                                      # another program may hold it for a moment
        if u.OpenClipboard(None):
            return
        time.sleep(0.05)
    raise OSError("the clipboard is busy (another program holds it)")


def clipboard_get():
    """The clipboard text ('' when it holds no text). Raises OSError."""
    u, k = _clip_api()
    _open_clipboard(u)
    try:
        h = u.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return ""
        p = k.GlobalLock(h)
        if not p:
            return ""
        try:
            return ctypes.wstring_at(p).replace("\r\n", "\n")
        finally:
            k.GlobalUnlock(h)
    finally:
        u.CloseClipboard()


def clipboard_set(text):
    u, k = _clip_api()
    data = (re.sub(r"\r?\n", "\r\n", text) + "\0").encode("utf-16-le")
    h = k.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not h:
        raise OSError("out of memory")
    p = k.GlobalLock(h)
    if not p:
        k.GlobalFree(h)
        raise OSError("could not lock memory")
    ctypes.memmove(p, data, len(data))
    k.GlobalUnlock(h)
    try:
        _open_clipboard(u)
    except OSError:
        k.GlobalFree(h)
        raise
    try:
        u.EmptyClipboard()
        if not u.SetClipboardData(CF_UNICODETEXT, h):
            k.GlobalFree(h)
            raise OSError("SetClipboardData failed")         # on success the system owns the memory
    finally:
        u.CloseClipboard()


# ───────────────────────── applications ─────────────────────────
_cache = {}


def _cached(key, fn, ttl=120):
    t, v = _cache.get(key, (0.0, None))
    if v is None or time.monotonic() - t > ttl:
        v = fn()
        _cache[key] = (time.monotonic(), v)
    return v


def _start_menu_dirs():
    out = []
    for env, sub in (("APPDATA", r"Microsoft\Windows\Start Menu\Programs"), ("ProgramData", r"Microsoft\Windows\Start Menu\Programs")):
        base = os.environ.get(env)
        if base:
            out.append(Path(base) / sub.replace("\\", os.sep))
    return out


def start_menu_entries():
    """[{name, path}] of the Start Menu shortcuts (uninstallers and help links left out)."""
    def scan():
        found, seen = [], set()
        for d in _start_menu_dirs():
            try:
                files = sorted(d.rglob("*.lnk"))
            except OSError:
                continue
            for f in files:
                n = f.stem
                if n.lower() in seen or re.search(r"uninstall|kaldır|readme|help|documentation|release notes", n, re.I):
                    continue
                seen.add(n.lower())
                found.append({"name": n, "path": str(f)})
        return found
    return _cached("lnk", scan)


def uwp_apps():
    """[{name, id}] of the Microsoft Store / system apps (Get-StartApps). [] when PowerShell does not answer."""
    def scan():
        cmd = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress"
        try:
            r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True,
                               timeout=25, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
            data = json.loads(r.stdout.decode("utf-8", "replace") or "[]")
        except Exception:
            return []
        if isinstance(data, dict):
            data = [data]
        return [{"name": str(d.get("Name", "")), "id": str(d.get("AppID", ""))} for d in data if d.get("Name") and d.get("AppID")]
    return _cached("uwp", scan, 300)


def app_paths(n):
    """Registered program (HKCU / HKLM ...\\App Paths\\NAME.exe) -> full path or ''."""
    try:
        import winreg
    except ImportError:
        return ""
    name = n if n.lower().endswith(".exe") else n + ".exe"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\\" + name) as k:
                path = winreg.QueryValueEx(k, "")[0]
        except OSError:
            continue
        path = os.path.expandvars(str(path).strip().strip('"'))
        if path and os.path.exists(path):
            return path
    return ""


SYNONYMS = {"vscode": "code", "vs code": "code", "visual studio code": "code", "edge": "msedge", "microsoft edge": "msedge",
            "word": "winword", "powerpoint": "powerpnt", "terminal": "wt", "windows terminal": "wt", "file explorer": "explorer",
            "files": "explorer", "task manager": "taskmgr", "paint": "mspaint", "calculator": "calc"}


def _norm(t):
    return re.sub(r"[^\w+]", "", t.lower())


def _pick(entries, q, key):
    nq = _norm(q)
    exact = [e for e in entries if e[key].lower() == q or _norm(e[key]) == nq]
    if exact:
        return exact[0], [e[key] for e in exact]
    near = [e for e in entries if q in e[key].lower() or (nq and nq in _norm(e[key]))]
    return (near[0] if len(near) == 1 else None), [e[key] for e in near]


def resolve_app(n, aliases=None):
    """(target, how) or (None, similar names). target = (kind, value), kind: exe | file | uwp.
    Order: your aliases (only when they point at something that exists here), program on PATH, registered program,
    Start Menu shortcut, Store app. Common names (vscode, edge, word ...) also try the real program name."""
    q = n.lower()
    al = aliases or {}
    if q in al:
        a = al[q].strip().strip('"')
        w = shutil.which(a.split()[0] if a.split() and not os.path.exists(a) else a)
        if w:
            return _exe_target(w), "alias"
        if os.path.exists(a):
            return ("file", a), "alias"
        # an alias written for another computer (spotify-launcher ...) is skipped: look the name up normally
    for name in (n, SYNONYMS.get(q)):
        if not name:
            continue
        w = shutil.which(name)
        if w:
            return _exe_target(w), "program"
        p = app_paths(name)
        if p:
            return _exe_target(p), "program " + os.path.basename(p)
    menu = start_menu_entries()
    hit, names = _pick(menu, q, "name")
    if hit:
        return ("file", hit["path"]), "app " + hit["name"]
    store = uwp_apps()
    hit2, names2 = _pick(store, q, "name")
    if hit2:
        return ("uwp", hit2["id"]), "app " + hit2["name"]
    pool = sorted({e["name"] for e in menu} | {e["name"] for e in store} | set(al))
    similar = (names + names2)[:5] or difflib.get_close_matches(n, pool, n=5, cutoff=0.5)
    return None, similar


def _exe_target(path):
    return ("file", path) if path.lower().endswith((".bat", ".cmd")) else ("exe", path)


def launch(target):
    """Starts it, detached. Returns None, or a short error text."""
    kind, value = target
    if kind == "uwp":
        os.startfile("shell:AppsFolder\\" + value)
        return None
    if kind == "file":
        os.startfile(value)
        return None
    p = subprocess.Popen([value], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=DETACHED | NEW_GROUP, close_fds=True)
    time.sleep(0.6)
    rc = p.poll()
    return None if rc in (None, 0) else f"it exited with code {rc}"


# ───────────────────────── Spotify ─────────────────────────
def process_running(exe):
    try:
        import psutil
        return any((p.info["name"] or "").lower() == exe.lower() for p in psutil.process_iter(["name"]))
    except ImportError:
        pass
    try:
        r = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {exe}", "/NH"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
                           creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
        return exe.lower() in r.stdout.lower()
    except Exception:
        return False


def spotify_open(uri, play=True):
    """Opens `uri` in the Spotify desktop app (the spotify: link handler starts it if needed). Returns "" or an error text."""
    was_running = process_running("Spotify.exe")
    try:
        os.startfile(uri)
    except OSError:
        return "Error: Spotify is not installed (nothing handles spotify: links)"
    if not was_running:
        end = time.monotonic() + 20
        while time.monotonic() < end and not process_running("Spotify.exe"):
            time.sleep(0.5)
        if not process_running("Spotify.exe"):
            return "Error: Spotify did not start"
        time.sleep(4)                                        # let it finish loading
    if play:
        time.sleep(1.5)
        try:
            if not _is_playing():
                _call("try_play_async")
        except Exception:
            pass                                             # without winrt Spotify decides itself; the docs say so
    return ""


# ───────────────────────── screen ─────────────────────────
MONITORINFOF_PRIMARY = 1


class _MonInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]


def monitors():
    """[{name, rect (left, top, right, bottom in virtual-screen pixels), primary}], primary first."""
    set_dpi_aware()
    u = _u32()
    out = []
    proc_t = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def cb(hmon, hdc, rect, lparam):
        mi = _MonInfo()
        mi.cbSize = ctypes.sizeof(_MonInfo)
        if u.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            r = mi.rcMonitor
            out.append({"name": mi.szDevice.split("\\")[-1] or f"DISPLAY{len(out) + 1}", "rect": (r.left, r.top, r.right, r.bottom),
                        "primary": bool(mi.dwFlags & MONITORINFOF_PRIMARY)})
        return True
    u.EnumDisplayMonitors(None, None, proc_t(cb), 0)
    return sorted(out, key=lambda m: (not m["primary"], m["rect"][0], m["rect"][1]))


def cursor_pos():
    pt = wintypes.POINT()
    return (pt.x, pt.y) if _u32().GetCursorPos(ctypes.byref(pt)) else None


def foreground_point():
    """The middle of the window in front, or None."""
    u = _u32()
    h = u.GetForegroundWindow()
    r = wintypes.RECT()
    if h and u.GetWindowRect(h, ctypes.byref(r)):
        return (r.left + r.right) // 2, (r.top + r.bottom) // 2
    return None


def choose_monitor(mons, want="", points=()):
    """The screen to show: by name / number / 'primary' when asked, else the one under the first of `points` (window in front, pointer)."""
    if not mons:
        raise RuntimeError("no screen found")
    w = str(want or "").strip().lower()
    if w:
        if w == "primary":
            return mons[0]
        if w.isdigit() and 1 <= int(w) <= len(mons):
            return mons[int(w) - 1]
        for m in mons:
            if w in m["name"].lower():
                return m
        raise RuntimeError(f"no screen called {want}. Screens: {', '.join(m['name'] for m in mons)}")
    for p in points:
        for m in mons:
            l, t, r, b = m["rect"]
            if p and l <= p[0] < r and t <= p[1] < b:
                return m
    return mons[0]


def grab(focus=False, monitor=""):
    """(png bytes, box (x, y, w, h) or None, screen name, [screen names], pointer or None).
    focus=False: all screens together. focus=True: only the screen with the window in front (or the pointer)."""
    set_dpi_aware()
    try:
        from PIL import ImageGrab
        import io
        if not focus:
            im = ImageGrab.grab(all_screens=True)
            buf = io.BytesIO()
            im.save(buf, "PNG")
            return buf.getvalue(), None, "", [], None
        mons = monitors()
        ptr = cursor_pos()
        m = choose_monitor(mons, monitor, (foreground_point(), ptr))
        l, t, r, b = m["rect"]
        im = ImageGrab.grab(bbox=(l, t, r, b), all_screens=True)
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return buf.getvalue(), (l, t, r - l, b - t), m["name"], [x["name"] for x in mons], ptr
    except ImportError:
        raise RuntimeError("could not take a screenshot (pip install pillow)")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"could not take a screenshot ({type(e).__name__}: {e}). A locked screen or a secure prompt cannot be captured")


def active_window():
    """'app: window title' of the window in front, or ''."""
    try:
        u = _u32()
        k = ctypes.windll.kernel32
        h = u.GetForegroundWindow()
        if not h:
            return ""
        n = u.GetWindowTextLengthW(h)
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(h, buf, n + 1)
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        app = ""
        k.OpenProcess.restype = wintypes.HANDLE
        ph = k.OpenProcess(0x1000, False, pid.value)         # PROCESS_QUERY_LIMITED_INFORMATION
        if ph:
            try:
                size = wintypes.DWORD(520)
                path = ctypes.create_unicode_buffer(520)
                if k.QueryFullProcessImageNameW(ph, 0, path, ctypes.byref(size)):
                    app = Path(path.value).stem
            finally:
                k.CloseHandle(ph)
        return f"{app}: {buf.value}".strip(": ")
    except Exception:
        return ""


# ───────────────────────── diagnostics ─────────────────────────
def probe():
    """python daemon-agent.py --probe: what works on this desktop? Changes nothing (the clipboard is restored)."""
    lines = []

    def check(label, fn):
        try:
            ok, detail = fn()
        except Exception as e:
            ok, detail = False, f"{type(e).__name__}: {e}"
        lines.append(("OK  " if ok else "FAIL") + f" {label}: {detail}")

    def pyver():
        return sys.version_info >= (3, 10), sys.version.split()[0]

    def mons():
        m = monitors()
        return bool(m), "; ".join(f"{x['name']} {x['rect'][2] - x['rect'][0]}x{x['rect'][3] - x['rect'][1]} at {x['rect'][:2]}" + (" primary" if x["primary"] else "") for x in m)

    def clip():
        old = clipboard_get()
        try:
            clipboard_set("daemon probe ğüşöı")
            back = clipboard_get()
        finally:
            clipboard_set(old) if old else None
        return back == "daemon probe ğüşöı", "write + read back" + ("" if old else " (the old clipboard was empty or not text and was not restored)")

    def vol():
        t = volume("status")
        return not t.startswith("Error"), t

    def media():
        t = media_control("status")
        return not t.startswith("Error"), t

    def shot():
        data, box, name, names, ptr = grab(True)
        return len(data) > 1000, f"{len(data) // 1024} KiB, screen {name}, box {box}, pointer {ptr}"

    def win():
        return True, active_window() or "(none)"

    def apps():
        t, how = resolve_app("notepad")
        return t is not None, f"notepad -> {how}"

    def store():
        n = len(uwp_apps())
        return n > 0, f"{n} Store apps found (open_app can start them)"

    def sp():
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "spotify"):
                return True, "the spotify: link handler is registered"
        except OSError:
            return False, "no spotify: handler (Spotify desktop not installed? open_app and playback via spotify_play need it)"

    for label, fn in (("Python", pyver), ("screens", mons), ("window in front", win), ("clipboard", clip), ("volume", vol),
                      ("media session", media), ("screenshot", shot), ("open_app", apps), ("Store apps", store), ("Spotify", sp)):
        check(label, fn)
    return lines
