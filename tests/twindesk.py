# Windows desktop backend (win_desktop.py): everything is mocked, so this runs on Linux too. Real Windows is covered by
# `python daemon-agent.py --probe` and the manual checklist in docs/windows.md.
import importlib.util, io, json, os, sys, tempfile, time, types
sys.path[:0]=["stubs","."]
def ok(c,m=""):
    if not c: print("FAIL",m); sys.exit(1)
import platform_support as ps
import tools as T
import win_desktop as W
time.sleep_real = time.sleep
time.sleep = lambda s: None
ps.IS_WINDOWS = True                       # tools.py now takes the Windows branches

# ── media ──
keys = []
W.send_key = keys.append
def no_winrt(): raise ImportError("winrt")
W.player_status = no_winrt
ok(T.media_control("toggle")=="Done: toggle" and keys[-1]==0xB3, ("toggle key", keys))
ok(T.media_control("next")=="Done: next" and keys[-1]==0xB0, "next key")
ok(T.media_control("previous")=="Done: previous" and keys[-1]==0xB1, "previous key")
ok(T.media_control("PLAY")=="Done: PLAY".replace("PLAY","play") and keys[-1]==0xB3, "play key")
ok(T.media_control("stop")=="Done: stop" and keys[-1]==0xB2, "stop key")
r = T.media_control("status"); ok(r.startswith("Error") and "winrt" in r, r)
r = T.media_control("restart"); ok(r.startswith("Error") and "winrt" in r, r)
ok(T.media_control("dance")=="Error: action must be one of play, pause, toggle, next, previous, restart, stop, status", "bad action text unchanged")

state = {"s": "Paused", "meta": "Radiohead - Creep (Spotify)", "pos": 100.0, "none": False}
did = []
W.player_status = lambda: None if state["none"] else (state["s"], state["meta"])
def call(name, *a):
    did.append((name, a))
    if state["none"]: return None
    if name == "try_play_async": state["s"] = "Playing"
    elif name == "try_pause_async": state["s"] = "Paused"
    elif name == "try_skip_previous_async": state["pos"] = 0.5
    return True
W._call = call
W._position = lambda: state["pos"]
ok(T.media_control("status")=="Paused: Radiohead - Creep (Spotify)", T.media_control("status"))
ok(T.media_control("play")=="Done: play" and state["s"]=="Playing", "play via SMTC")
ok(T.media_control("pause")=="Done: pause" and state["s"]=="Paused", "pause via SMTC")
ok(T.media_control("toggle")=="Done: play" and state["s"]=="Playing", "toggle on paused plays (same text as Linux)")
ok(T.media_control("toggle")=="Done: toggle" and state["s"]=="Paused", "toggle on playing pauses")
did.clear(); state["s"]="Playing"; state["pos"]=100.0
ok(T.media_control("previous")=="Done: previous" and [d[0] for d in did].count("try_skip_previous_async")==2, ("previous twice when it restarted the track", did))
did.clear(); ok(T.media_control("restart")=="Done: restarted the current track" and did[0]==("try_change_playback_position_async",(0,)), did)
state["s"]="Paused"; did.clear(); T.media_control("next"); ok(("try_play_async",()) in did, "next on a paused player starts it")
state["none"]=True; W.PLAYER_WAIT=0
ok(T.media_control("status")=="Nothing is playing", "status without player")
ok(T.media_control("next")=="Nothing is playing. Start the player first (open_app), then try again", "no player")
state["none"]=False
# nothing loaded: play does nothing, next starts it
def stubborn(name, *a):
    if name == "try_skip_next_async": state["s"]="Playing"
    return True
W._call = stubborn; state["s"]="Paused"
ok(T.media_control("play").startswith("Done: play (the player had nothing loaded"), "play falls back to next")
W._call = lambda *a: True; state["s"]="Paused"
ok(T.media_control("play").startswith("Error: the player did not start"), "play that never starts")

# ── volume ──
class EP:
    def __init__(s): s.v, s.m = 0.30, False
    def GetMasterVolumeLevelScalar(s): return s.v
    def SetMasterVolumeLevelScalar(s, v, c): s.v = v
    def GetMute(s): return s.m
    def SetMute(s, m, c): s.m = bool(m)
ep = EP(); W._endpoint = lambda: ep
ok(T.volume("status")=="Volume is 30%", T.volume("status"))
ok(T.volume("50")=="Volume is 50%" and T.volume("150%")=="Volume is 100%", "set and clamp")
ok(T.volume("up")=="Volume is 100%" and T.volume("0")=="Volume is 0%" and T.volume("down")=="Volume is 0%", "up/down clamp")
ep.v = 0.5; ok(T.volume("up")=="Volume is 55%" and T.volume("down")=="Volume is 50%", "steps of 5")
ok(T.volume("mute")=="Volume is 50%, muted" and T.volume("unmute")=="Volume is 50%", "mute")
ok(T.volume("loud")=="Error: level must be a number from 0 to 100, or up, down, mute, unmute, status", "bad level")
def missing(): raise ImportError("pycaw")
W._endpoint = missing; ok("pycaw" in T.volume("status"), T.volume("status"))
def broken(): raise OSError("no device")
W._endpoint = broken; ok(T.volume("status").startswith("Error: could not open the audio device"), T.volume("status"))

# ── clipboard ──
store = {"t": ""}
W.clipboard_get = lambda: store["t"]
W.clipboard_set = lambda t: store.update(t=t)
ok(T.clipboard_read()=="Clipboard is empty", "empty")
ok(T.clipboard_write("merhaba \u011f\u00fc\u015f")=="Copied 11 characters to the clipboard" and store["t"]=="merhaba \u011f\u00fc\u015f", "write")
ok(T.clipboard_read()=="merhaba \u011f\u00fc\u015f", "read")
T.clipboard_write("x"*200_000); ok(len(store["t"])==100_000, "limit")
def busy(*a): raise OSError("the clipboard is busy")
W.clipboard_get = busy; W.clipboard_set = busy
ok(T.clipboard_read()=="Error: the clipboard is busy" and T.clipboard_write("a").startswith("Error: could not write"), "busy")

# ── links ──
opened = []
os.startfile = opened.append
ok(T.open_url("https://example.com/a?b=1&c=2")=="Opened https://example.com/a?b=1&c=2" and opened==["https://example.com/a?b=1&c=2"], "open_url")
ok(T.open_url("file:///C:/x").startswith("Error: the URL must start with") and T.open_url("calc.exe").startswith("Error") and len(opened)==1, "only http(s)")
def bad(u): raise OSError("no handler")
os.startfile = bad; ok(T.open_url("http://a.b")=="Error: no handler", "startfile error")

# ── apps ──
d = tempfile.mkdtemp()
for sub, names in (("appdata", ["Notepad++.lnk", "Games/Steam.lnk", "Uninstall Foo.lnk", "Spotify.lnk"]), ("pdata", ["Visual Studio Code.lnk", "Spotify.lnk", "Kitap Okuyucu \u00c7.lnk"])):
    for n in names:
        p = os.path.join(d, sub, "Microsoft", "Windows", "Start Menu", "Programs", *n.split("/")); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "w").close()
os.environ.update(APPDATA=d+"/appdata", ProgramData=d+"/pdata")
W._cache.clear()
names = sorted(e["name"] for e in W.start_menu_entries())
ok(names==["Kitap Okuyucu \u00c7", "Notepad++", "Spotify", "Steam", "Visual Studio Code"], names)       # uninstaller left out, duplicates once
W._cache["uwp"] = (time.monotonic(), [{"name": "Calculator", "id": "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"}, {"name": "Takvim", "id": "T!App"}])
W.app_paths = lambda n: ""
launched = []
W.launch = lambda t: launched.append(t)
os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]
FOO = "foo.exe" if os.name == "nt" else "foo"      # Windows only finds names with a PATHEXT extension
open(os.path.join(d, FOO), "w").close(); os.chmod(os.path.join(d, FOO), 0o755)
T.hooks["app_aliases"] = lambda: {"browser": "foo", "tr": "foo"}
r = T.open_app("foo"); ok(r=="Started foo" and launched[-1][0]=="exe", (r, launched))
ok(T.open_app("browser").lower()=="started browser (as %s)" % FOO, T.open_app("browser"))      # which() may return foo.EXE
import shutil; _which = shutil.which; shutil.which = lambda n, *a, **k: _which(n, *a, **k) if n == "foo" else None      # the real PATH of this PC (code.cmd, ...) must not matter
ok(T.open_app("code")=="Started code (as Visual Studio Code.lnk)" and launched[-1][0]=="file", (T.open_app("code"), launched))
T.hooks["app_aliases"] = lambda: {"spotify": "spotify-launcher", "browser": "foo", "tr": "foo"}      # an alias copied from another computer
r = T.open_app("spotify"); ok(r=="Started spotify" and launched[-1]==("file", [e["path"] for e in W.start_menu_entries() if e["name"]=="Spotify"][0]), (r, launched[-1]))
ok(T.open_app("visual studio")=="Started visual studio (as Visual Studio Code.lnk)", "word part of a name")
ok(T.open_app("VisualStudioCode")=="Started VisualStudioCode (as Visual Studio Code.lnk)", "spaces ignored")
_w = shutil.which; shutil.which = lambda n, *a, **k: "C:/x/code.cmd" if n == "code" else _w(n, *a, **k)
ok(T.open_app("VS Code")=="Started VS Code (as code.cmd)" and launched[-1]==("file","C:/x/code.cmd"), ("synonym", launched[-1]))
shutil.which = _w
ok(T.open_app("notepad++")=="Started notepad++", "exact name, any case")
r = T.open_app("calculator"); ok(r=="Started calculator" and launched[-1]==("uwp","Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"), (r, launched))
r = T.open_app("S"); ok(r.startswith("Error: S was not found.") and "Similar: " in r and "Steam" in r and "app_aliases" in r, r)    # ambiguous substring: candidates, nothing started
n = len(launched); r = T.open_app("spotfy"); ok(r.startswith("Error") and "Spotify" in r and len(launched)==n, r)
ok("without arguments" in T.open_app("rm -rf /; x") and "without arguments" in T.open_app("..\\x"), "validation")
W.launch = lambda t: "it exited with code 3"; ok(T.open_app("foo")=="Error: foo failed, it exited with code 3", "launch error")
def boom(t): raise OSError("denied")
W.launch = boom; ok(T.open_app("foo")=="Error: could not start foo: denied", "launch exception")
T.hooks["app_aliases"] = lambda: (_ for _ in ()).throw(RuntimeError("x"))
W.launch = lambda t: None; ok(T.open_app("foo").startswith("Started"), "broken hook ignored")
# .bat goes through the shell association, not CreateProcess
ok(W._exe_target("C:/x/tool.cmd")==("file","C:/x/tool.cmd") and W._exe_target("C:/x/a.exe")==("exe","C:/x/a.exe"), "bat/cmd")
# Get-StartApps output: one object (not a list), Turkish names, garbage
class R: pass
def fake_run(out):
    def run(*a, **k): r = R(); r.stdout = out; return r
    return run
import subprocess
real_run = subprocess.run
for out, want in ((json.dumps([{"Name":"Hesap Makinesi","AppID":"A!x"},{"Name":"","AppID":"B"}]).encode(), ["Hesap Makinesi"]),
                  (json.dumps({"Name":"Tek \u015e","AppID":"T!x"}, ensure_ascii=False).encode("utf-8"), ["Tek \u015e"]), (b"not json", []), (b"", [])):
    W._cache.pop("uwp", None); subprocess.run = fake_run(out)
    ok([a["name"] for a in W.uwp_apps()]==want, (out, W.uwp_apps()))
subprocess.run = real_run

# ── Spotify ──
opened.clear(); os.startfile = opened.append
running = [True]; W.process_running = lambda exe: running[0]
W._is_playing = lambda: False; played = []
W._call = lambda n, *a: played.append(n) or True
ok(W.spotify_open("spotify:track:abc", True)=="" and opened==["spotify:track:abc"] and played==["try_play_async"], (opened, played))
played.clear(); ok(W.spotify_open("spotify:track:abc", False)=="" and not played, "play=False does not press play")
def nowinrt(n, *a): raise ImportError("winrt")
W._call = nowinrt; ok(W.spotify_open("spotify:track:abc", True)=="", "without winrt: Spotify decides itself")
os.startfile = bad; ok(W.spotify_open("spotify:track:abc")=="Error: Spotify is not installed (nothing handles spotify: links)", "no handler")
os.startfile = opened.append; running[0] = False
ok(W.spotify_open("spotify:track:abc")=="Error: Spotify did not start", "never starts")
# the tool wrapper on the agent side goes through the same function
T.remote["call"] = None; running[0] = True; W._call = lambda *a: True
ok(T._spotify_open("spotify:album:x", False)=="" , "T._spotify_open on Windows")

# ── screen ──
mons = [{"name":"DISPLAY1","rect":(0,0,1920,1080),"primary":True}, {"name":"DISPLAY2","rect":(-1280,0,0,1024),"primary":False}]
ok(W.choose_monitor(mons)["name"]=="DISPLAY1", "default primary")
ok(W.choose_monitor(mons, "", [(-100, 50)])["name"]=="DISPLAY2", "point on the left screen (negative coordinates)")
ok(W.choose_monitor(mons, "", [None, (5, 5)])["name"]=="DISPLAY1", "first usable point")
ok(W.choose_monitor(mons, "2")["name"]=="DISPLAY2" and W.choose_monitor(mons, "display2")["name"]=="DISPLAY2" and W.choose_monitor(mons, "Primary")["name"]=="DISPLAY1", "by number / name / primary")
try: W.choose_monitor(mons, "tv"); ok(False, "unknown screen must raise")
except RuntimeError as e: ok("DISPLAY1, DISPLAY2" in str(e), e)
try: W.choose_monitor([]); ok(False, "no screens")
except RuntimeError: pass
from PIL import Image, ImageGrab
asked = []
def fake_grab(bbox=None, all_screens=False, **k):
    asked.append((bbox, all_screens))
    return Image.new("RGB", (bbox[2]-bbox[0], bbox[3]-bbox[1]) if bbox else (3200, 1080), (10, 20, 30))
ImageGrab.grab = fake_grab
W.monitors = lambda: mons; W.cursor_pos = lambda: (-640, 500); W.foreground_point = lambda: None
data, box, name, names, ptr = W.grab(True)
ok(box==(-1280,0,1280,1024) and name=="DISPLAY2" and names==["DISPLAY1","DISPLAY2"] and ptr==(-640,500) and asked[-1]==((-1280,0,0,1024),True), (box, name, asked))
data, box, name, names, ptr = W.grab(False); ok(box is None and data[:4]==b"\x89PNG" and asked[-1]==(None,True), "all screens")
r = T.screen_grab(focus=True, units="1000")                       # the whole pipeline: grid, pointer ring, geometry
ok(r.startswith("OK ") and json.loads(r[3:])["monitor"]=="DISPLAY2", r)
ok(T.grab_geometry["box"]==(-1280,0,1280,1024) and T.grab_geometry["real"]==(1280,1024) and T.last_shot["pointer"] is not None, (T.grab_geometry, T.last_shot["pointer"]))
px, py = T.last_shot["pointer"]; ok(abs(px-640)<1 and abs(py-500)<1, (px, py))             # pointer (-640,500) on a screen that starts at x=-1280
def noscreen(*a, **k): raise OSError("access denied")
ImageGrab.grab = noscreen
r = T.screen_grab(); ok(r.startswith("Error: could not take a screenshot (OSError: access denied)"), r)
W.active_window = lambda: "Code: main.py"
ok(T._active_window()=="Code: main.py", "active window")

# ── probe ──
W.clipboard_get = lambda: store["t"]; W.clipboard_set = lambda t: store.update(t=t)
W.volume = lambda lv: "Volume is 10%"; W.media_control = lambda a: "Nothing is playing"
W.grab = lambda f=False, m="": (b"x"*5000, (0,0,10,10), "DISPLAY1", ["DISPLAY1"], (1,1))
W.resolve_app = lambda n, a=None: (("exe","C:/Windows/notepad.exe"), "program notepad.exe")
W.uwp_apps = lambda: [{"name":"a","id":"b"}]
lines = W.probe()
ok(len(lines)==10 and all(l.startswith(("OK  ","FAIL")) for l in lines), lines)
ok(any(l.startswith("OK   clipboard") for l in lines), lines)
W.volume = lambda lv: "Error: volume needs pycaw (pip install pycaw)"
ok(any(l.startswith("FAIL volume") and "pycaw" in l for l in W.probe()), "a failing check says why")

# ── agent ──
spec = importlib.util.spec_from_file_location("agent", "daemon-agent.py"); agent = importlib.util.module_from_spec(spec); spec.loader.exec_module(agent)
ok(agent.desktop_name().startswith("Windows"), agent.desktop_name())
ok(agent.ensure_session_env()==[], "no Linux session variables on Windows")
os.environ["APPDATA"] = d + "/roam"
ok(ps.agent_config_path().parts[-2:]==("daemon-agent","config.json") and "roam" in str(ps.agent_config_path()), ps.agent_config_path())
ps.IS_WINDOWS = False
ok(ps.agent_config_path().name=="daemon-agent.json", "Linux path unchanged")
ps.IS_WINDOWS = True
# the config file may carry a BOM (Notepad, PowerShell 5.1 Set-Content -Encoding UTF8)
conf = ps.agent_config_path(); conf.parent.mkdir(parents=True); conf.write_bytes(b"\xef\xbb\xbf" + json.dumps({"server":"http://s:1","token":"t"*20}).encode())
agent.CONF = conf; sys.argv = ["agent"]; a = agent.load_args(); ok(a.server=="http://s:1" and a.token=="t"*20, "BOM tolerated")
sys.argv = ["agent", "--probe"]; os.environ.pop("DAEMON_SERVER", None); ok(agent.load_args().probe, "--probe needs no server")
# wake word replies: winsound on Windows
fw = types.ModuleType("winsound"); fw.SND_MEMORY = 4; played_snd = []; fw.PlaySound = lambda d, f: played_snd.append((d, f)); sys.modules["winsound"] = fw
import wakeword; wakeword.play(b"RIFFdata"); ok(played_snd==[(b"RIFFdata", 4)], played_snd)
ps.IS_WINDOWS = False

# ── files ──
ps_text = open("setup-agent.ps1", "rb").read()
ok(all(b < 128 for b in ps_text), "setup-agent.ps1 must be ASCII (PowerShell 5.1 reads BOM-less files as ANSI)")
req = open("requirements-agent.txt", encoding="utf-8").read()
for pkg in ("pycaw", "winrt-Windows.Media.Control", "pillow"):
    ok(pkg in req, pkg)
ok(all('sys_platform == "win32"' in l for l in req.splitlines() if l.startswith(("pycaw", "winrt"))), "Windows-only packages carry the marker")
print("WINDESK OK")
