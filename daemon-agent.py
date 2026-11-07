#!/usr/bin/env python3
"""Daemon laptop agent: wake word + desktop commands for a Daemon that runs on another computer (a home server).

What it does
  * Listens to THIS computer's microphone for the wake word (settings come from the server's dashboard:
    Settings > Wake word; the microphone name can be set here with --device).
  * Turns your speech into text HERE with Whisper (faster-whisper, your laptop is faster than the server) and sends only
    the text to the server, where the model runs. The spoken reply is played here.
  * Keeps a connection open so the model can use this computer's media keys, volume, clipboard, links and apps.

Needs on the laptop:  pip install numpy sounddevice websockets faster-whisper   (+ portaudio, playerctl, wl-clipboard or xclip)
                      pip install openwakeword                    (only if the server uses wake.engine: openwakeword)
Files next to it:     tools.py, wakeword.py and screeninput.py (copy them from the Daemon folder)

  python daemon-agent.py --server http://SERVER:8000 --token TOKEN
  python daemon-agent.py --no-wake        only the desktop commands (no microphone)
  python daemon-agent.py --stt-model base --stt-device cuda --stt-compute float16     choose the local Whisper
  python daemon-agent.py --server-stt     let the server do the speech-to-text instead
  python daemon-agent.py --allow execute_command   also let the model run shell commands here (off by default)
  python daemon-agent.py --allow screen_input      let the model use the mouse and keyboard here (the `computer` tool; off by default)
  python daemon-agent.py --test-input              check the mouse/keyboard tools of this desktop (moves the pointer to the screen's middle)
  touch ~/.daemon-stop                             emergency brake: while this file exists the mouse and keyboard are refused

Settings can also be saved in ~/.config/daemon-agent.json: {"server": "...", "token": "...", "device": "", "allow": [],
"stt_model": "small", "stt_device": "cpu", "stt_compute": "int8"}
"""
import argparse
import asyncio
import json
import os
import platform
import socket
import sys
import threading
import time
import types
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
CONF = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "daemon-agent.json"
SAFE = {"system_info", "media_control", "volume", "clipboard_read", "clipboard_write", "open_url", "open_app", "spotify_open", "screen_grab"}
UA = "daemon-agent/1.0"


def log(*a):
    print(time.strftime("%H:%M:%S"), "[agent]", *a, flush=True)


class LocalSTT:
    """Whisper on this computer. Loads on first use. If it cannot load, the server does the speech-to-text."""

    def __init__(self, model, device, compute, fallback):
        self.model_name, self.device, self.compute, self.fallback = model, device, compute, fallback
        self.model = None
        self.failed = ""
        self.lock = threading.Lock()

    def load(self):
        if self.model is not None or self.failed:
            return self.model
        try:
            from faster_whisper import WhisperModel
            t0 = time.time()
            self.model = WhisperModel(self.model_name, device=self.device, compute_type=self.compute)
            log(f"local Whisper ready ({self.model_name}, {self.device}, {self.compute}) in {time.time() - t0:.1f} s")
        except Exception as e:
            self.failed = f"{type(e).__name__}: {e}"
            log(f"local Whisper not available ({self.failed}): using the server for speech-to-text. pip install faster-whisper")
        return self.model

    def __call__(self, audio, prompt=None):
        if self.load() is None:
            return self.fallback(audio, prompt)
        t0 = time.time()
        with self.lock:
            segments, _ = self.model.transcribe(audio, vad_filter=True, condition_on_previous_text=False, initial_prompt=prompt)
            text = " ".join(s.text for s in segments).strip()
        log(f"heard {len(audio) / 16000:.1f} s in {time.time() - t0:.1f} s: {text[:80]!r}")
        return text


class Server:
    """The few HTTP calls to the Daemon server."""

    def __init__(self, base, token):
        self.base, self.token = base.rstrip("/"), token

    def _req(self, path, data=None, ctype="application/json", timeout=60):
        req = urllib.request.Request(self.base + path, data=data, headers={
            "Authorization": "Bearer " + self.token, "Content-Type": ctype, "User-Agent": UA})
        return urllib.request.urlopen(req, timeout=timeout)

    def config(self):
        with self._req("/api/sat/config", timeout=15) as r:
            return json.loads(r.read())

    def transcribe(self, audio, prompt=None):
        from urllib.parse import quote
        q = "?prompt=" + quote(prompt) if prompt else ""
        with self._req("/api/sat/transcribe" + q, audio.astype("float32").tobytes(), "application/octet-stream", 120) as r:
            return json.loads(r.read()).get("text", "")

    def shot(self, data, ext):
        """Gives a screenshot to the server (it keeps the file); returns the name it saved it under."""
        with self._req("/api/sat/shot?ext=" + ext, data, "application/octet-stream", 60) as r:
            return json.loads(r.read())["name"]

    def turn(self, text, emit, cancel):
        """Streams the events of one spoken turn (NDJSON) into emit()."""
        with self._req("/api/sat/turn", json.dumps({"text": text}).encode(), timeout=600) as r:
            for line in r:
                if cancel.is_set():
                    return
                line = line.strip()
                if line:
                    emit(json.loads(line))


def load_args():
    saved = {}
    try:
        saved = json.loads(CONF.read_text())
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Daemon laptop agent")
    ap.add_argument("--server", default=saved.get("server") or os.environ.get("DAEMON_SERVER", ""))
    ap.add_argument("--token", default=saved.get("token") or os.environ.get("DAEMON_TOKEN", ""))
    ap.add_argument("--device", default=saved.get("device", ""), help="microphone name or number (python -m sounddevice)")
    ap.add_argument("--allow", action="append", default=list(saved.get("allow") or []), help="extra tool the server may run here")
    ap.add_argument("--no-wake", action="store_true", help="no microphone, desktop commands only")
    ap.add_argument("--test-input", action="store_true", help="check mouse/keyboard control on this desktop and exit")
    ap.add_argument("--stt-model", default=saved.get("stt_model", "small"), help="local Whisper model: tiny, base, small, medium...")
    ap.add_argument("--stt-device", default=saved.get("stt_device", "cpu"), help="cpu or cuda")
    ap.add_argument("--stt-compute", default=saved.get("stt_compute", "int8"), help="int8 (cpu) or float16 (cuda)")
    ap.add_argument("--server-stt", action="store_true", default=bool(saved.get("server_stt", False)), help="do the speech-to-text on the server")
    a = ap.parse_args()
    if a.test_input:
        return a
    if not a.server or not a.token:
        ap.error("--server and --token are needed (python satellite_setup.py on the server prints them)")
    if not a.server.startswith("http"):
        a.server = "http://" + a.server
    return a


# ── desktop commands ──
def load_tools(allow):
    import tools                                      # the same code the server uses, running here
    funcs = {n: f for n, f in tools.REMOTE_CAPABLE.items() if n in SAFE or n in allow}
    return funcs


STOP_FILE = Path.home() / ".daemon-stop"


def ensure_session_env():
    """The service may start at boot before you log in to the desktop, without WAYLAND_DISPLAY / HYPRLAND_INSTANCE_SIGNATURE /
    DISPLAY: apps then die at once ("cannot open display"). Look the running session up and fill in what is missing (cheap).
    Returns the names it changed."""
    changed = []
    rt = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    if not os.path.isdir(rt):
        return changed
    if "XDG_RUNTIME_DIR" not in os.environ:
        os.environ["XDG_RUNTIME_DIR"] = rt
        changed.append("XDG_RUNTIME_DIR")
    wd = os.environ.get("WAYLAND_DISPLAY", "")
    if not wd or not os.path.exists(os.path.join(rt, wd)):
        socks = sorted(p for p in Path(rt).glob("wayland-*") if not p.name.endswith(".lock") and p.is_socket())
        if socks:
            os.environ["WAYLAND_DISPLAY"] = socks[0].name
            changed.append("WAYLAND_DISPLAY")
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
    if not sig or not os.path.isdir(os.path.join(rt, "hypr", sig)):
        dirs = sorted((p for p in Path(rt, "hypr").glob("*") if (p / ".socket.sock").exists()), key=lambda p: p.stat().st_mtime) \
            if Path(rt, "hypr").is_dir() else []
        if dirs:
            os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = dirs[-1].name
            os.environ.setdefault("XDG_CURRENT_DESKTOP", "Hyprland")
            changed.append("HYPRLAND_INSTANCE_SIGNATURE")
    if os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("XDG_SESSION_TYPE"):
        os.environ["XDG_SESSION_TYPE"] = "wayland"
        changed.append("XDG_SESSION_TYPE")
    if not os.environ.get("DISPLAY"):                                   # XWayland (Blender, Steam ...) or X11
        xs = sorted(Path("/tmp/.X11-unix").glob("X*")) if Path("/tmp/.X11-unix").is_dir() else []
        if xs:
            os.environ["DISPLAY"] = ":" + xs[0].name[1:]
            changed.append("DISPLAY")
    if "DBUS_SESSION_BUS_ADDRESS" not in os.environ and os.path.exists(os.path.join(rt, "bus")):
        os.environ["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={rt}/bus"
        changed.append("DBUS_SESSION_BUS_ADDRESS")
    return changed


def run_tool(funcs, name, args):
    fixed = ensure_session_env()
    if fixed:
        print(f"[agent] desktop session found: set {', '.join(fixed)}", flush=True)
    if name == "screen_input" and STOP_FILE.exists():
        return f"Error: the emergency brake is on ({STOP_FILE} exists): the user stopped mouse and keyboard control"
    fn = funcs.get(name)
    if fn is None:
        return f"Error: {name} is not allowed on this laptop (start the agent with --allow {name})"
    try:
        cap = int(os.environ.get("DAEMON_MAX_OUT", "4000")) or None
        if name == "screen_input" and str(args.get("action", "")).lower() == "shortcuts" and cap:
            cap = max(cap, 10000)                      # the key bindings list is longer than other answers
        return str(fn(**args))[:cap]
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


def desktop_name():
    """'Arch Linux, Hyprland (wayland)': tells the model what it is working with."""
    distro = ""
    try:
        for ln in open("/etc/os-release", encoding="utf-8"):
            if ln.startswith("PRETTY_NAME="):
                distro = ln.split("=", 1)[1].strip().strip('"')
    except OSError:
        distro = platform.system()
    de = os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("DESKTOP_SESSION") or ""
    if not de and os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        de = "Hyprland"
    kind = os.environ.get("XDG_SESSION_TYPE") or ("wayland" if os.environ.get("WAYLAND_DISPLAY") else "x11" if os.environ.get("DISPLAY") else "")
    return ", ".join(x for x in (distro, de + (f" ({kind})" if kind and de else kind)) if x)[:80]


async def link(a, funcs):
    """Keeps the WebSocket to the server open; reconnects forever."""
    import websockets
    url = a.server.replace("http", "ws", 1) + "/ws/satellite"
    delay = 2
    while True:
        try:
            hdr = {"Authorization": "Bearer " + a.token}
            try:                                       # websockets 14+ says additional_headers, older versions extra_headers
                conn = websockets.connect(url, additional_headers=hdr, ping_interval=20, ping_timeout=20, max_size=1_000_000)
            except TypeError:
                conn = websockets.connect(url, extra_headers=hdr, ping_interval=20, ping_timeout=20, max_size=1_000_000)
            async with conn as ws:
                await ws.send(json.dumps({"type": "hello", "name": socket.gethostname(), "tools": sorted(funcs), "desktop": desktop_name()}))
                log("connected to", a.server)
                delay = 2
                async for raw in ws:
                    m = json.loads(raw)
                    if m.get("type") == "call":
                        asyncio.create_task(answer(ws, funcs, m))
        except Exception as e:
            log(f"no connection ({type(e).__name__}: {e}), retrying in {delay} s")
        await asyncio.sleep(delay)
        delay = min(delay * 2, 30)


async def answer(ws, funcs, m):
    log("tool:", m.get("tool"), m.get("args"))
    out = await asyncio.to_thread(run_tool, funcs, m.get("tool"), m.get("args") or {})
    try:
        await ws.send(json.dumps({"type": "result", "id": m.get("id"), "output": out}))
    except Exception:
        pass


# ── wake word ──
def start_wake(a, srv):
    cfg = srv.config()["wake"]
    if a.device:
        cfg["input_device"] = a.device
    cfg["enabled"] = True
    shim = types.ModuleType("model_config")             # wakeword.py reads its settings from model_config.wake
    shim.wake = cfg
    sys.modules["model_config"] = shim
    import wakeword
    if a.server_stt:
        transcribe = srv.transcribe
    else:
        transcribe = LocalSTT(a.stt_model, a.stt_device, a.stt_compute, srv.transcribe)
        threading.Thread(target=transcribe.load, daemon=True, name="whisper-load").start()    # load while starting up
    listener = wakeword.WakeListener(transcribe=transcribe,
                                     run_turn=lambda text, emit, cancel: srv.turn(text, emit, cancel))
    listener.start()
    log(f"wake word on ({cfg['engine']}: {cfg['phrase'] if cfg['engine'] == 'whisper' else cfg['oww_model']})")
    return listener, cfg


def test_input():
    """What can this desktop do? Takes a screenshot (the pointer coordinates refer to it), then moves the pointer to the middle."""
    import tools
    import screeninput as si
    d = si.detect()
    print(si.describe(d))
    if d["missing"] or not d["move"]:
        print("\nInstall the missing tools (see the top of screeninput.py), then run this again.")
        return 1
    tools.shot_sink["fn"] = lambda data, ext: tools._save_shot(data, ext)
    out = tools.screen_grab(focus=True)                  # the screen that has the focus, like the computer tool
    print("\nscreenshot:", out[:160])
    view, real = tools.grab_geometry["view"], tools.grab_geometry["real"]
    if not view[0]:
        print("The screenshot did not work, so the pointer cannot be mapped. Fix that first (grim / scrot / spectacle).")
        return 1
    print(f"screenshot {view[0]}x{view[1]}, real screen {real[0]}x{real[1]}")
    box = tools.grab_geometry.get("box")
    if box:
        print("pointer area (the focused screen): x=%d y=%d %dx%d" % tuple(box))
    ok_, mons = si.run(["hyprctl", "-j", "monitors"]) if d["move"] == "hyprctl" else (False, "")
    if ok_:
        try:
            for m in json.loads(mons):
                print("  monitor %s: %dx%d at (%s, %s), scale %s" % (m.get("name"), m["width"], m["height"], m.get("x"), m.get("y"), m.get("scale")))
        except Exception:
            pass
    cx, cy = view[0] // 2, view[1] // 2
    print(f"\nmoving the pointer to the middle ({cx}, {cy}) of the screenshot...")
    print(tools.screen_input("move", x=cx, y=cy))
    time.sleep(0.4)
    for fx, fy in ((0.05, 0.1), (0.95, 0.9)):
        x, y = int(view[0] * fx), int(view[1] * fy)
        tools.screen_input("move", x=x, y=y)
        time.sleep(0.3)
        p, e = si.pointer_position(d), si.to_screen(d, x, y, view, real, tools.grab_geometry.get('box'))
        print(f"corner test ({x}, {y}): pointer {p}, expected ({e[0]:.0f}, {e[1]:.0f})")
    print(tools.screen_input("move", x=cx, y=cy)[:60])
    time.sleep(0.4)
    pos = si.pointer_position(d)
    px, py = si.to_screen(d, cx, cy, view, real, tools.grab_geometry.get('box'))
    if pos:
        off = max(abs(pos[0] - px), abs(pos[1] - py))
        print(f"pointer is at {pos}, expected about ({px:.0f}, {py:.0f}): {'OK' if off <= 8 else 'OFF BY ' + str(int(off)) + ' px - tell Poyraz/Claude your desktop and this output'}")
    else:
        print("This desktop cannot tell the pointer position: look at the screen, the pointer should be in the middle.")
    return 0


def main():
    a = load_args()
    if a.test_input:
        sys.exit(test_input())
    srv = Server(a.server, a.token)
    funcs = load_tools(set(a.allow))
    import tools
    tools.shot_sink["fn"] = srv.shot                    # screenshots go to the server, which keeps them
    log("desktop tools:", ", ".join(sorted(funcs)))
    listener = None
    while not a.no_wake:
        try:
            listener, cfg = start_wake(a, srv)
            break
        except urllib.error.HTTPError as e:
            log(f"server refused ({e.code}): check --token and that satellite.enabled is true on the server")
        except Exception as e:
            log(f"cannot reach the server yet ({e}), retrying in 10 s")
        time.sleep(10)
    if listener is not None:
        def watch():                                    # restart the wake listener if the microphone failed
            while True:
                time.sleep(15)
                if not listener.state["running"] and listener.state["error"]:
                    log("wake word stopped:", listener.state["error"], "- retrying")
                    time.sleep(10)
                    listener.start()
        threading.Thread(target=watch, daemon=True).start()
    try:
        asyncio.run(link(a, funcs))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
