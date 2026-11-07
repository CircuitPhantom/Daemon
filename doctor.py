#!/usr/bin/env python3
"""Checks that this computer is ready to run Daemon and says what is missing.

  venv/bin/python doctor.py             quick local checks
  venv/bin/python doctor.py --online    also test the cloud model and the ElevenLabs voice (uses a few tokens/characters)
"""
import importlib
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
OK, BAD, WARN = "\033[32m✓\033[0m", "\033[31m✗\033[0m", "\033[33m!\033[0m"
bad = warn = 0


def show(kind, text, hint=""):
    global bad, warn
    bad += kind == BAD
    warn += kind == WARN
    print(f" {kind} {text}" + (f"\n     → {hint}" if hint and kind != OK else ""))


def run(cmd, timeout=40):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return 1, str(e)


print("Python")
show(OK if sys.version_info >= (3, 10) else BAD, f"Python {sys.version.split()[0]}", "Python 3.10 or newer is needed")
for mod, pip, needed in (("fastapi", "fastapi", 1), ("uvicorn", "uvicorn[standard]", 1), ("pydantic", "pydantic", 1),
                         ("yaml", "pyyaml", 1), ("numpy", "numpy", 1),
                         ("faster_whisper", "faster-whisper", 1), ("pykokoro", "pykokoro", 1),
                         ("websockets", "websockets", 0), ("sounddevice", "sounddevice", 0), ("edge_tts", "edge-tts", 0),
                         ("miniaudio", "miniaudio", 0), ("PIL", "pillow", 0), ("pypdf", "pypdf", 0)):
    try:
        importlib.import_module(mod)
        show(OK, mod)
    except Exception as e:
        hint = f"pip install {pip}" + (" (also: portaudio system package)" if mod == "sounddevice" else "")
        why = {"edge_tts": "the free Edge voice", "miniaudio": "the Edge voice", "PIL": "photos you send",
               "pypdf": "reading PDFs you send"}.get(mod, "phone calls / wake word")
        show(BAD if needed else WARN, f"{mod} missing ({type(e).__name__})", hint + ("" if needed else f"   ({why} need it)"))

print("\nFiles")
for f in ("three.min.js", "marked.min.js", "highlight.min.js", "github-dark.min.css"):
    show(OK if (HERE / "static/lib" / f).stat().st_size > 1000 else BAD, f"static/lib/{f}", "run ./setup.sh to download it") if (HERE / "static/lib" / f).exists() \
        else show(BAD, f"static/lib/{f} missing", "run ./setup.sh to download it")
show(OK if (HERE / "index.html").exists() else BAD, "index.html")
try:
    import monitor
    v = monitor.ui_file_version()
    show(OK if v == monitor.UI_VERSION else BAD, f"index.html matches the server (page {v}, server {monitor.UI_VERSION})",
         "an old index.html: copy the newest one (bash deploy.sh does that for every file)")
except Exception as e:
    show(BAD, f"monitor.py could not be loaded: {type(e).__name__}: {e}", "copy monitor.py and the other new files")
copies = sorted(p.name for p in HERE.glob("*([0-9]).*"))
show(WARN if copies else OK, "no browser copies like name(1).py" if not copies else "browser copies in this folder: " + ", ".join(copies),
     "these are not used; the real file may be older. Delete them and copy the files again")

print("\nSettings")
try:
    import model_config as mc
    show(OK if mc.CONFIG_PATH.exists() else WARN, f"config: {mc.CONFIG_PATH}", "no config.yaml yet: defaults are used (restore your backup with ./setup.sh --restore FILE)")
    es = mc.env_status()
    if es["found"] or es["refs"] or es["auto"]:
        show(BAD if es["missing"] else OK, f"secrets: {es['names']} values in {mc.ENV_PATH.name}, {es['refs']} used as ${{NAME}}, {es['auto']} by DAEMON_<SECTION>_<FIELD>"
             if not es["missing"] else f"secrets: {', '.join(es['missing'])} is used in config.yaml but not set",
             f"add {', '.join(es['missing'])}=... to {mc.ENV_PATH}")
except Exception as e:
    show(BAD, f"config could not be loaded: {e}")
    sys.exit(1)

print("\nModel")
llm_ok = bool(mc.llm["api_key"] and mc.llm["base_url"] and mc.llm["model"])
show(OK if llm_ok else BAD, f"model {mc.llm['model']} at {mc.llm['base_url']}" if llm_ok else "the model is not set up",
     "fill llm.base_url, llm.api_key and llm.model in config.yaml (Anthropic: https://api.anthropic.com/v1)")
if mc.stt["device"] == "cuda":
    show(OK if shutil.which("nvidia-smi") else WARN, "stt.device is cuda", "no NVIDIA GPU found here: set stt.device: cpu and compute_type: int8")

print("\nDesktop tools")
for label, cmds, need in (("audio player", ("pw-play", "paplay", "aplay"), 0), ("media control", ("playerctl",), 0),
                          ("clipboard", ("wl-copy", "xclip", "xsel"), 0), ("volume", ("wpctl", "pactl"), 0),
                          ("open links", ("xdg-open",), 0)):
    found = next((c for c in cmds if shutil.which(c)), None)
    show(OK if found else WARN, f"{label}: {found or ' / '.join(cmds) + ' not found'}", "install one of them (see MIGRATION.md)")

print("\nSignal")
if mc.signal_cfg["enabled"]:
    cli = mc.signal_cfg["cli"] or "signal-cli"
    if not shutil.which(cli):
        show(BAD, f"{cli} not found", "install signal-cli")
    elif not shutil.which("java"):
        show(BAD, "java not found", "install a JDK (Arch: sudo pacman -S jdk-openjdk; archlinux-java set java-XX-openjdk)")
    else:
        code, out = run([cli, "listAccounts"])
        acc = str(mc.signal_cfg["account"]).lstrip("+")
        show(OK if code == 0 and acc and acc in out.replace("+", "") else BAD, f"account {mc.signal_cfg['account']} registered here",
             "restore the Signal data from your backup (./setup.sh --restore FILE) or register again. Output: " + out[:120])
    show(OK if mc.signal_cfg["allowed"] else WARN, "signal.allowed set", "who may chat with Daemon (your number or UUID)")
else:
    show(WARN, "signal is off (signal.enabled: false)")

print("\nPhone calls")
n = mc.notify
if n["twilio_sid"] and n["twilio_token"]:
    show(OK, "Twilio keys set")
    if mc.phone_cfg["enabled"]:
        url = mc.phone_cfg["public_url"]
        show(OK if url.startswith("https://") else BAD, f"phone.public_url = {url or '(empty)'}", "your Tailscale Funnel address, e.g. https://NAME.tailnet.ts.net:8443")
        show(OK if shutil.which("tailscale") else BAD, "tailscale installed", "install Tailscale and run: sudo tailscale up")
        if shutil.which("tailscale"):
            code, out = run(["tailscale", "status"], 10)
            show(OK if code == 0 else BAD, "tailscale is connected", "sudo tailscale up")
        show(WARN, "Twilio: set the incoming-call webhook to " + (url + "/phone/incoming" if url else "<public_url>/phone/incoming"), "Twilio console > Phone Numbers > your number > Voice > A call comes in")
else:
    show(WARN, "Twilio is not set up (notify.twilio_*), phone calls are off")

print("\nLaptop agent")
if mc.satellite["enabled"]:
    show(OK if len(mc.satellite["token"]) >= 16 else BAD, "satellite.enabled with a token", "python satellite_setup.py")
    show(WARN, "the server's own microphone is not used (the laptop agent does that); tools sent to the laptop: " + ", ".join(mc.satellite["tools"]))
    if mc.wake["enabled"] is False:
        show(WARN, "wake.enabled is false: the laptop agent will not listen for the wake word", "turn on Settings > Wake word in the dashboard")
agent_conf = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "daemon-agent.json"
if agent_conf.exists():
    import json
    import urllib.request
    c = json.loads(agent_conf.read_text())
    try:
        urllib.request.urlopen(urllib.request.Request(c["server"].rstrip("/") + "/api/sat/config", headers={
            "Authorization": "Bearer " + c["token"], "User-Agent": "daemon-agent/1.0"}), timeout=8)
        show(OK, "this laptop reaches " + c["server"] + " and the token is accepted")
    except Exception as e:
        show(BAD, f"this laptop cannot use {c['server']}: {e}", "check the address (the one you open the dashboard with), the token, and satellite.enabled on the server")
    code, out = run(["systemctl", "--user", "is-active", "daemon-agent.service"], 5)
    show(OK if out == "active" else WARN, f"daemon-agent service: {out or 'not installed'}", "./setup-agent.sh")
elif not mc.satellite["enabled"]:
    show(OK, "single-computer setup (no laptop agent)")

print("\nService")
code, out = run(["systemctl", "--user", "is-active", "daemon.service"], 5)
show(OK if out == "active" else WARN, f"daemon service: {out or 'not installed'}", "./install-service.sh")
s = socket.socket()
s.settimeout(1)
busy = s.connect_ex(("127.0.0.1", int(os.environ.get("DAEMON_PORT", 8000)))) == 0
s.close()
show(OK if busy else WARN, "dashboard port 8000 " + ("answers" if busy else "is free (Daemon is not running)"))

if "--online" in sys.argv:
    print("\nOnline tests")
    if mc.llm["api_key"]:
        import llm
        t = llm.test()
        show(OK if t["ok"] else BAD, "cloud model: " + t["info"])
    if mc.elevenlabs["enabled"] and mc.elevenlabs["api_key"]:
        import elevenlabs_tts
        t = elevenlabs_tts.test("Test.")
        show(OK if t["ok"] else BAD, "ElevenLabs: " + t["info"])

print(f"\n{bad} problem(s), {warn} note(s).")
sys.exit(1 if bad else 0)
