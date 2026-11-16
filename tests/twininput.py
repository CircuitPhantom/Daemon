# Windows mouse and keyboard (win_input.py + the Windows side of screeninput.py and tools.screen_input), all mocked: runs on Linux.
# Real Windows is covered by `python daemon-agent.py --test-input` and the checklist in docs/windows.md.
import ctypes, json, os, sys, tempfile, time
sys.path[:0]=["stubs","."]
def ok(c,m=""):
    if not c: print("FAIL",m); sys.exit(1)
import platform_support as ps
import screeninput as si, win_input as wi, win_desktop as W, tools as T
time.sleep = lambda s: None
ps.IS_WINDOWS = True

# ── structures: the size of INPUT decides whether SendInput accepts the call ──
if ctypes.sizeof(ctypes.c_void_p) == 8:
    ok(ctypes.sizeof(wi.INPUT)==40 and ctypes.sizeof(wi.MOUSEINPUT)==32 and ctypes.sizeof(wi.KEYBDINPUT)==24, (ctypes.sizeof(wi.INPUT),))
else:
    ok(ctypes.sizeof(wi.INPUT)==28, ctypes.sizeof(wi.INPUT))

# ── key resolution ──
us = {"c": (0x43, 0), "-": (0xBD, 0), "'": (0xDE, 0), "i": (0x49, 0)}
tr = {"c": (0x43, 0), "-": (0xBF, 0), "'": (0x32, SHIFT := 1), "\\": (0x51, 6), "i": (0xDE, 0), "1": (0x31, 0)}      # Turkish Q: ' is shift+2, \ is AltGr+Q, i is the apostrophe key
sc = lambda table: (lambda ch: table.get(ch))
ok(wi.resolve_key("enter")==(0x0D, []) and wi.resolve_key("f5")==(0x74, []) and wi.resolve_key("pagedown")==(0x22, []), "named keys")
ok(wi.resolve_key("c", sc(us))==(0x43, []) and wi.resolve_key("minus", sc(us))==(0xBD, []), "US layout")
ok(wi.resolve_key("minus", sc(tr))==(0xBF, []), "Turkish minus is another key")
ok(wi.resolve_key("apostrophe", sc(tr))==(0x32, ["shift"]), "needs shift on Turkish")
ok(wi.resolve_key("backslash", sc(tr))==(0x51, ["ctrl", "alt"]), "AltGr = ctrl+alt")
ok(wi.resolve_key("i", sc(tr))==(0xDE, []) and wi.resolve_key("i", sc(us))==(0x49, []), "the key that types i on this layout")
ok(wi.resolve_key("z", None)==(0x5A, []) and wi.resolve_key("slash", sc({}))==(0xBF, []) and wi.resolve_key("7", None)==(0x37, []), "fallbacks without a layout")
try: wi.resolve_key("nonsense"); ok(False, "unknown key")
except wi.InputBlocked: pass
ev = wi.key_events(["ctrl", "shift"], "t", sc(us))
ok(ev==[("key",0xA2,False,False),("key",0xA0,False,False),("key",0x54,False,False),("key",0x54,True,False),("key",0xA0,True,False),("key",0xA2,True,False)] or ev[0][1]==0xA2, ev)
ok([e[1] for e in ev]==[0xA2,0xA0,0x54,0x54,0xA0,0xA2] and [e[2] for e in ev]==[False,False,False,True,True,True], "mods down, key, mods up in reverse")
ok(wi.key_events([], "super")[0]==("key",0x5B,False,True), "Windows key is an extended key")
ok(all(e[3] for e in wi.key_events([], "left")[:2]) and not wi.key_events([], "enter")[0][3], "arrows are extended, enter is not")
ev = wi.key_events(["shift"], "apostrophe", sc(tr)); ok([e[1] for e in ev]==[0xA0,0x32,0x32,0xA0], "shift not pressed twice")

# ── text ──
ev = wi.text_events("çay")
ok([e[1] for e in ev]==[0xE7,0xE7,ord("a"),ord("a"),ord("y"),ord("y")] and all(e[0]=="uni" for e in ev) and [e[2] for e in ev][:2]==[False, True], ev)
ok(len(wi.text_events("\U0001F600"))==4, "an emoji is two UTF-16 units, each down + up")
ev = wi.text_events("a\tb"); ok(ev[2][0]=="key" and ev[2][1]==0x09, "tab becomes the Tab key")
ok(len(wi.text_events("a\r\nb".replace("\n","")))==4, "carriage returns dropped")

# ── what is sent to Windows ──
sent = []
wi.send = lambda ev: sent.append(list(ev)); wi.layout_scan = lambda: sc(us)
curs = []; wi.set_cursor = lambda x, y: curs.append((x, y))
wi.do("move", -300, 45); ok(curs==[(-300, 45)], curs)
wi.do("click", "left", 1); ok(sent[-1]==[("mouse",2,0),("mouse",4,0)], sent[-1])
sent.clear(); wi.do("click", "left", 2); ok(len(sent)==2 and all(len(x)==2 for x in sent), "double click = two pairs, a pause between")
wi.do("click", "right", 1); ok(sent[-1]==[("mouse",8,0),("mouse",0x10,0)], "right button")
wi.do("button", True, "left"); wi.do("button", False, "left"); ok(sent[-2]==[("mouse",2,0)] and sent[-1]==[("mouse",4,0)], "drag buttons")
wi.do("scroll", 3); ok(sent[-1]==[("mouse",0x800,(-360)&0xFFFFFFFF)], sent[-1])           # down = negative wheel
wi.do("scroll", -2); ok(sent[-1]==[("mouse",0x800,240)], sent[-1])
sent.clear(); wi.do("type", "x"*150); ok(len(sent)==5 and all(len(x)<=64 for x in sent), "long text goes in pieces")
sent.clear(); wi.do("key", ["ctrl"], "c"); ok([e[1] for e in sent[0]]==[0xA2,0x43,0x43,0xA2], sent)
try: wi.do("explode"); ok(False, "unknown")
except wi.InputBlocked: pass
ok("access denied" in wi._refused(5) and "secure" in wi._refused(0), "refusal text")

# ── screeninput on Windows ──
d = si.detect()
ok(d["session"]=="windows" and d["move"]=="sendinput" and d["unicode"] and not d["missing"], d)
ok(si.cmd_move(d, 10.4, -5.6)==[["win","move",10,-6]] and si.cmd_click(d,"right")==[["win","click","right",1]] and si.cmd_click(d,"left",2)==[["win","click","left",2]], "cmds")
ok(si.cmd_button(d, True)==[["win","button",True,"left"]] and si.cmd_type(d,"hi")==[["win","type","hi"]] and si.cmd_scroll(d,-3)==[["win","scroll",-3]], "cmds 2")
ok(si.cmd_key(d, "Ctrl+Shift+T")==[["win","key",["ctrl","shift"],"t"]] and si.cmd_key(d, "super")==[["win","key",[],"super"]], si.cmd_key(d, "Ctrl+Shift+T"))
try: si.cmd_key(d, "ctrl+nonsense"); ok(False, "bad key")
except si.InputError: pass
calls = []
wi.do = lambda *a: calls.append(a)
si.execute(si.cmd_type(d, "x") + si.cmd_key(d, "enter")); ok(calls==[("type","x"),("key",[],"enter")], calls)
def refuse(*a): raise wi.InputBlocked("Windows refused the input (access denied)")
wi.do = refuse
try: si.execute(si.cmd_type(d, "x")); ok(False, "refusal must raise")
except si.InputError as e: ok("refused" in str(e), e)
wi.do = lambda *a: calls.append(a)
ok(si.SENSITIVE_WINDOW.search("Windows Security: Enter your credentials") and si.SENSITIVE_WINDOW.search("KeePassXC: Database") and si.SENSITIVE_WINDOW.search("Kullanıcı Hesabı Denetimi") and not si.SENSITIVE_WINDOW.search("Code: main.py"), "sensitive windows")
ok("alt+tab" in si.shortcuts(d) and "super+d" in si.shortcuts(d), "Windows shortcut list names the habits the tool checks")

mons = [{"name":"DISPLAY1","rect":(0,0,1920,1080),"primary":True}, {"name":"DISPLAY2","rect":(-1280,-100,0,924),"primary":False}]
W.monitors = lambda: mons; W.foreground_point = lambda: (-600, 300); W.cursor_pos = lambda: (-640, 500)
ms = si.monitors(d); ok([m["name"] for m in ms]==["DISPLAY2","DISPLAY1"] and ms[0]["focused"] and not ms[1]["focused"], ms)     # left to right, the focused one flagged
ok(si.logical_screen(d)==(-1280,-100,3200,1180), si.logical_screen(d))
ok(si.pointer_position(d)==(-640,500), "pointer")
ok(si.to_screen(d, 640, 512, (1280,1024), (1280,1024), (-1280,0,1280,1024))==(-640.0, 512.0), "screenshot -> virtual pixels, negative origin")
ok(si.to_screen(d, 100, 100, (3200,1180), (3200,1180))==(-1180.0, 0.0), "without a box: all screens")

# ── the tool, end to end ──
from PIL import Image, ImageGrab
ImageGrab.grab = lambda bbox=None, all_screens=False, **k: Image.new("RGB", (bbox[2]-bbox[0], bbox[3]-bbox[1]) if bbox else (3200,1180), (9,9,9))
ok(T.screen_input("click", x=5, y=5).startswith("Error: take a screenshot first"), "needs a screenshot")
r = T.screen_grab(focus=True); ok(r.startswith("OK ") and T.grab_geometry["box"]==(-1280,-100,1280,1024), (r, T.grab_geometry))
T.INPUT_STOP_FILE = __import__("pathlib").Path(tempfile.mkdtemp()) / "stop"
W.active_window = lambda: "Code: main.py"
T._input_blocked = lambda d, point=None: ""
calls.clear()
r = T.screen_input("click", x=640, y=512); ok(r.startswith("OK ") and calls==[("move",-640.0,412.0),("click","left",1)], (r, calls))
calls.clear(); r = T.screen_input("double_click", x=0, y=0); ok(calls==[("move",-1280.0,-100.0),("click","left",2)], calls)
calls.clear(); r = T.screen_input("right_click", x=1280, y=1024); ok(calls==[("move",0.0,924.0),("click","right",1)], calls)      # the far corner of the left screen
calls.clear(); r = T.screen_input("drag", x=10, y=10, x2=100, y2=50); ok([c[0] for c in calls]==["move","button","move","button"] and calls[1][1] is True and calls[3][1] is False, calls)
calls.clear(); r = T.screen_input("scroll", amount=4); ok(calls==[("scroll",4)], calls)
calls.clear(); r = T.screen_input("scroll", x=10, y=10, amount=-2); ok(calls==[("move",-1270.0,-90.0),("scroll",-2)], calls)
calls.clear(); r = T.screen_input("key", keys="ctrl+l, enter"); ok(calls==[("key",["ctrl"],"l"),("key",[],"enter")], calls)
calls.clear(); r = T.screen_input("type", text="Merhaba şüğ\nıkinci"); ok(r.startswith("OK ") and calls==[("type","Merhaba şüğ"),("key",[],"enter"),("type","ıkinci")], calls)   # typed as characters: no clipboard, no ctrl+v
clip = T.clipboard_read; T.clipboard_read = lambda: (_ for _ in ()).throw(AssertionError("the clipboard must stay untouched"))
calls.clear(); T.screen_input("type", text="çay"); T.clipboard_read = clip
calls.clear(); r = T.screen_input("type", text="a\r\nb"); ok(calls==[("type","a"),("key",[],"enter"),("type","b")], calls)
# guards
W.active_window = lambda: "KeePassXC: Unlock database"
calls.clear(); r = T.screen_input("type", text="secret"); ok(r.startswith("Error: not typed: the window in front looks like a password") and not calls, r)
W.active_window = lambda: "Code: main.py"
T._input_blocked = lambda d, point=None: "the window runs as administrator"
for kw in (dict(action="click", x=5, y=5), dict(action="type", text="a"), dict(action="key", keys="enter"), dict(action="scroll", amount=2)):
    calls.clear(); r = T.screen_input(**kw); ok(r.startswith("Error: not") and "administrator" in r and not calls, (kw, r))
T._input_blocked = lambda d, point=None: ""
open(T.INPUT_STOP_FILE, "w").close()
for kw in (dict(action="click", x=5, y=5), dict(action="type", text="a"), dict(action="key", keys="enter")):
    calls.clear(); r = T.screen_input(**kw); ok(r.startswith("Error: the emergency brake is on") and not calls, (kw, r))
ok(T.screen_input("shortcuts").startswith("OK ") and "alt+tab" in T.screen_input("shortcuts"), "shortcuts need no brake release")
os.remove(T.INPUT_STOP_FILE)
ok(T.screen_input("click", x=1, y=1).startswith("OK "), "works again when the file is gone")
r = T.screen_input("click", x=99999, y=5); ok(r.startswith("Error: (") and "outside the screenshot" in r, r)
r = T.screen_input("fly"); ok(r.startswith("Error: unknown action"), r)
# blocked_reason must never raise and must say nothing off Windows
ps.IS_WINDOWS = False
ok(wi.blocked_reason()=="" , "no Windows API here: no answer, no crash")
ps.IS_WINDOWS = True
# the agent: --test-input works through the same detect()
import importlib.util
spec = importlib.util.spec_from_file_location("agent", "daemon-agent.py"); ag = importlib.util.module_from_spec(spec); spec.loader.exec_module(ag)
ok(si.describe(d).splitlines()[0]=="session: windows (windows)", "describe")
print("WININPUT OK")
