import os, sys, json, time, threading, shutil, base64
sys.path[:0]=["stubs","."]
D=os.path.abspath("dmn44")
os.environ.update(DAEMON_CONFIG="cfg44.yaml", DAEMON_CHATS="chats44", DAEMON_MEMORY="mem44.json", DAEMON_FILES=D, DAEMON_TOOL_LOG=os.path.abspath("toollog44.jsonl"),
                  DISPLAY=":0")
os.environ.pop("WAYLAND_DISPLAY", None); os.environ["XDG_SESSION_TYPE"]="x11"
for f in ("cfg44.yaml","mem44.json","toollog44.jsonl"):
    if os.path.exists(f): os.remove(f)
shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
def ok(c,m=""):
    if not c: print("FAIL",m); sys.exit(1)
import model_config as mc; ok(mc.load())
import screeninput as si, tools, toolguard, agent, ollama
si_calls=[]
def runner(argv, timeout=6):
    si_calls.append(argv)
    if argv[:2]==["hyprctl","-j"]: return True, json.dumps([{"focused":True,"x":0,"y":0,"width":2880,"height":1800,"scale":1.5,"transform":0}])
    if argv[:2]==["swaymsg","-t"]: return True, json.dumps([{"focused":True,"rect":{"x":0,"y":0,"width":1920,"height":1080}}])
    return True, ""
si.runner=runner

# ── keys ──
ok(si.parse_combo("Ctrl+Shift+T")==(["ctrl","shift"],"t") and si.parse_combo("enter")==([],"enter") and si.parse_combo("super + l")==(["super"],"l"), "combos")
ok(si.parse_combo("PgDn")==([],"pagedown") and si.parse_combo("alt+F4")==(["alt"],"f4"), "aliases")
for bad in ("", "ctrl+shift", "foo", "hyper+a"):
    try: si.parse_combo(bad); ok(False, bad)
    except si.InputError: pass
ok(si.norm_combo("Ctrl + Alt + Delete")=="ctrl+alt+delete" and si.norm_combo("super+L")=="super+l", "norm")

# ── commands per desktop ──
x11=si.detect(); ok(x11["session"]=="x11" and x11["move"]=="xdotool", x11)
ok(si.cmd_move(x11,10.4,20.6)==[["xdotool","mousemove","--sync",10,21]], si.cmd_move(x11,10.4,20.6))
ok(si.cmd_click(x11,"right")==[["xdotool","click",3]] and si.cmd_click(x11,"left",2)==[["xdotool","click","--repeat",2,"--delay",90,1]], "x11 click")
ok(si.cmd_key(x11,"ctrl+shift+t")==[["xdotool","key","--","ctrl+shift+t"]] and si.cmd_key(x11,"enter")==[["xdotool","key","--","Return"]], "x11 key")
ok(si.cmd_type(x11,"hello")==[["xdotool","type","--delay",12,"--","hello"]], "x11 type")
ok(si.cmd_scroll(x11,3)==[["xdotool","click","--repeat",3,"--delay",40,5]] and si.cmd_scroll(x11,-2)[0][-1]==4, "x11 scroll")
ok(si.cmd_button(x11,True)==[["xdotool","mousedown",1]] and si.cmd_button(x11,False)==[["xdotool","mouseup",1]], "x11 buttons")
os.environ.pop("DISPLAY"); os.environ["WAYLAND_DISPLAY"]="wayland-1"; os.environ["HYPRLAND_INSTANCE_SIGNATURE"]="abc"
hy=si.detect(); ok(hy["session"]=="wayland" and hy["compositor"]=="hyprland" and (hy["move"],hy["click"],hy["type"],hy["scroll"])==("hyprctl","ydotool","wtype","ydotool"), hy)
ok(si.cmd_move(hy,100,50)==[["hyprctl","dispatch","movecursor",100,50]], "hypr move")
ok(si.cmd_click(hy,"left")==[["ydotool","click","0xc0"]] and si.cmd_click(hy,"right")==[["ydotool","click","0xc1"]], si.cmd_click(hy,"right"))
ok(si.cmd_click(hy,"left",2)==[["ydotool","click","--repeat",2,"--next-delay",90,"0xc0"]], "ydotool double")
ok(si.cmd_button(hy,True)==[["ydotool","click","0x40"]] and si.cmd_button(hy,False)==[["ydotool","click","0x80"]], "ydotool buttons")
ok(si.cmd_key(hy,"ctrl+l")==[["ydotool","key","29:1","38:1","38:0","29:0"]] and si.cmd_key(hy,"ctrl+comma")==[["wtype","-M","ctrl","-k","comma","-m","ctrl"]], si.cmd_key(hy,"ctrl+l"))
ok(si.cmd_type(hy,"hi")==[["wtype","-d",12,"--","hi"]] and si.cmd_scroll(hy,3)==[["ydotool","mousemove","--wheel","-x",0,"-y",-3]], "wayland type/scroll")
# the hyprland pointer uses logical coordinates: 2880x1800 at scale 1.5 = 1920x1200; screenshot 1440x900 of the real 2880x1800
ok(si.to_screen(hy,720,450,(1440,900),(2880,1800))==(960.0,600.0), si.to_screen(hy,720,450,(1440,900),(2880,1800)))
gn=dict(hy, compositor="gnome", move="ydotool", type="ydotool", key="ydotool")
ok(si.cmd_key(gn,"ctrl+shift+t")==[["ydotool","key","29:1","42:1","20:1","20:0","42:0","29:0"]], si.cmd_key(gn,"ctrl+shift+t"))
ok(si.cmd_move(gn,5,6)==[["ydotool","mousemove","--absolute","-x",5,"-y",6]], "ydotool move")
ok(si.to_screen(gn,720,450,(1440,900),(2880,1800))==(1440.0,900.0), "real size scaling")
os.environ.pop("HYPRLAND_INSTANCE_SIGNATURE"); os.environ["SWAYSOCK"]="/x"
sw=si.detect(); ok(sw["compositor"]=="sway" and sw["move"]=="swaymsg", sw)
ok(si.cmd_move(sw,1,2)==[["swaymsg","seat","-","cursor","set",1,2]] and si.cmd_click(sw,"left")[0]==["ydotool","click","0xc0"], "sway")
ok(si.to_screen(sw,960,540,(1920,1080),(1920,1080))==(960.0,540.0), "sway map")
try: si.to_screen(hy,5000,5,(1440,900),(2880,1800)); ok(False,"outside")
except si.InputError as e: ok("outside the screenshot" in str(e), e)
try: si.to_screen(hy,5,5,(0,0),(0,0)); ok(False,"no shot")
except si.InputError as e: ok("screenshot first" in str(e), e)
none=dict(si.detect(), move="", click="", type="", key="", scroll="", missing=["ydotool"])
try: si.cmd_click(none); ok(False,"nothing")
except si.InputError as e: ok("ydotool" in str(e), e)
os.environ.pop("SWAYSOCK"); os.environ.pop("WAYLAND_DISPLAY"); os.environ["DISPLAY"]=":0"; os.environ["XDG_SESSION_TYPE"]="x11"

# ── tools.screen_input (the laptop side) ──
tools.grab_geometry.update(real=(2000,1000), view=(1000,500), at=time.time())
tools._active_window=lambda: "Firefox: Example"
si_calls.clear(); r=tools.screen_input("click", x=100, y=50); ok(r.startswith("OK ") and json.loads(r[3:])["did"]=="clicked (left) at (100, 50)", r)
ok(si_calls==[["xdotool","mousemove","--sync","200","100"],["xdotool","click","1"]], si_calls)
si_calls.clear(); tools.screen_input("double_click", x=10, y=10); ok(si_calls[-1][:3]==["xdotool","click","--repeat"], si_calls)
si_calls.clear(); r=tools.screen_input("drag", x=100, y=100, x2=300, y2=200); ok("dragged" in r and [c[1] for c in si_calls if c[0]=="xdotool"]==["mousemove","mousedown","mousemove","mouseup"], si_calls)
si_calls.clear(); tools.screen_input("type", text="hello\nworld"); ok(si_calls==[["xdotool","type","--delay","12","--","hello"],["xdotool","key","--","Return"],["xdotool","type","--delay","12","--","world"]], si_calls)
si_calls.clear(); r=tools.screen_input("key", keys="ctrl+l, enter"); ok(si_calls==[["xdotool","key","--","ctrl+l"],["xdotool","key","--","Return"]] and "ctrl+l then enter" in r, (si_calls, r))
si_calls.clear(); tools.screen_input("scroll", amount=-4, x=500, y=250); ok(si_calls[0][:2]==["xdotool","mousemove"] and si_calls[1][-1]=="4", si_calls)
# letters the key tables do not have are pasted
clip={"v":"old"}; tools.clipboard_read=lambda: clip["v"]; tools.clipboard_write=lambda t: clip.__setitem__("v",t) or "ok"
si_calls.clear(); r=tools.screen_input("type", text="şğı merhaba"); ok(r.startswith("OK") and si_calls==[["xdotool","key","--","ctrl+v"]] and clip["v"]=="old", (si_calls, clip))
# a password prompt gets no text
tools._active_window=lambda: "Authentication Required - polkit"
si_calls.clear(); r=tools.screen_input("type", text="secret"); ok(r.startswith("Error: not typed") and not si_calls, r)
tools._active_window=lambda: "Firefox"
for bad,word in ((dict(action="key",keys=""),"keys is empty"),(dict(action="key",keys="ctrl+zzz"),"unknown key"),(dict(action="fly"),"unknown action"),(dict(action="type",text=""),"empty"),(dict(action="click",x=5000,y=5),"outside")):
    r=tools.screen_input(**bad); ok(r.startswith("Error") and word in r, (bad,r))
tools.grab_geometry.update(real=(0,0), view=(0,0)); ok("take a screenshot first" in tools.screen_input("click", x=1, y=1), "no geometry yet")
tools.grab_geometry.update(real=(2000,1000), view=(1000,500))
si.runner=lambda argv,t=6:(False,"Failed to connect to socket /tmp/.ydotool_socket") ; os.environ.pop("DISPLAY"); os.environ["WAYLAND_DISPLAY"]="w"
r=tools.screen_input("key", keys="enter"); ok("ydotoold" in r or "wtype failed" in r, r); si.runner=runner; os.environ.pop("WAYLAND_DISPLAY"); os.environ["DISPLAY"]=":0"

# ── the model's tool: tools.computer ──
ok(tools.available_functions["computer"] is tools.computer and "screen_input" in tools.REMOTE_CAPABLE and "screen_input" not in tools.available_functions, "registered")
ok("screen_input" not in mc.satellite["tools"], "the laptop must opt in itself")
import llm; sc=llm.tool_schema(tools.computer)["function"]; ok(sc["parameters"]["required"]==["action"], sc)
CFG={"max_actions":3,"settle_seconds":0,"blocked_keys":["ctrl+alt+delete","super+l"]}
tools.hooks["computer_cfg"]=lambda: CFG; tools.hooks["vision"]=lambda: True
SHOTS=[]
def fake_capture(where="", clipboard=False, focus=False, zoom="", units="", monitor=""):
    SHOTS.append(1); return {"name":"screenshots/x.jpg","size":"1000x500","window":"Firefox: Example","sees":True}
tools._capture=fake_capture; tools._keys_cache.update(text="none known (test)", at=9e12)
REMOTE=[]
tools.remote["names"]=lambda: {"media_control"}; tools.remote["call"]=lambda name,args:(REMOTE.append((name,args)) or "OK "+json.dumps({"did":"clicked (left) at (1, 2)","window":"Firefox"}))
ctx={"source":"web","emit":None,"out":[],"computer_seen":True}
ok(tools.computer("click",x=1,y=2).startswith("Error: computer control only works in a chat"), "no turn")
tok=toolguard.current.set(ctx)
try:
    ok(tools.computer("explode").startswith("Error: action must be"), "bad action")
    r=tools.computer("click",goal="test",x=1,y=2); ok(r.startswith("Done: clicked (left) at (1, 2).") and "Window in front: Firefox: Example" in r and "Actions left this turn: 2" in r and REMOTE[0][0]=="screen_input" and REMOTE[0][1]["x"]==1, r)
    r=tools.computer("screenshot"); ok(not r.startswith("Error") and "Actions left this turn: 2" in r and len(REMOTE)==1, r)       # looking is free and stays on this side
    r=tools.computer("key",keys="Ctrl + Alt + Delete"); ok("blocked" in r and len(REMOTE)==1, r)
    r=tools.computer("key",keys="enter, super+l"); ok("blocked" in r, r)
    tools.computer("type",text="a"); tools.computer("type",text="b")
    r=tools.computer("click",x=1,y=1); ok(r.startswith("Error: the limit of 3 actions") and len(REMOTE)==3, r)
    ok(tools.computer("screenshot").startswith("Done") is False and "Actions left this turn: 0" in tools.computer("screenshot"), "screenshots still work at the limit")
    # no vision
    tools.hooks["vision"]=lambda: False; ok("cannot look at pictures" in tools.computer("screenshot"), "vision"); tools.hooks["vision"]=lambda: True
    # the laptop failed / refused
    ctx["computer_n"]=0; tools.remote["call"]=lambda n,a:"Error: screen_input is not allowed on this laptop (start the agent with --allow screen_input)"
    r=tools.computer("click",x=1,y=2); ok(r.startswith("Error: screen_input is not allowed") and ctx["computer_n"]==0, r)
    # no laptop agent set up: the server's own desktop needs DAEMON_ALLOW_INPUT=1
    tools.remote["names"]=lambda: set()
    r=tools.computer("click",x=1,y=2); ok("DAEMON_ALLOW_INPUT=1" in r, r)
    os.environ["DAEMON_ALLOW_INPUT"]="1"; si_calls.clear(); tools.grab_geometry.update(real=(1000,500), view=(1000,500))
    r=tools.computer("click",x=10,y=20); ok(r.startswith("Done: clicked") and ["xdotool","click","1"] in si_calls, (r, si_calls)); del os.environ["DAEMON_ALLOW_INPUT"]
finally:
    toolguard.current.reset(tok)
# scheduled tasks and jobs (no turn) never get it
ok(tools.computer("screenshot").startswith("Error: computer control only works"), "tasks")
tools.hooks["vision"]=lambda: True

# ── approval: asked once per turn, and always while security.confirm is on ──
mc.security["confirm_tools"]=["execute_command"]; ok(toolguard.needs_approval("computer") and not toolguard.needs_approval("send_file"), "always asked")
mc.security["confirm"]=False; ok(not toolguard.needs_approval("computer"), "off when confirmation is off"); mc.security["confirm"]=True
EV=[]
def answer_soon(ok_):
    def go():
        for _ in range(100):
            if toolguard.open_requests(): toolguard.answer(toolguard.open_requests()[0]["id"], ok_); return
            time.sleep(0.03)
    threading.Thread(target=go).start()
ctx2={"source":"web","emit":EV.append,"out":[],"computer_seen":True}; tok=toolguard.current.set(ctx2)
try:
    tools.remote["names"]=lambda: {"media_control"}; tools.remote["call"]=lambda name,args:"OK "+json.dumps({"did":"clicked","window":""})
    answer_soon(True); out=toolguard.run("computer", tools.computer, {"action":"click","goal":"open the settings","x":5,"y":6}, agent.call_tool)
    ok(out.startswith("Done"), out); ap=[e for e in EV if e["type"]=="approve"]; ok(len(ap)==1 and "goal: open the settings" in ap[0]["args"] and "click at (5, 6)" in ap[0]["args"], EV)
    ok("computer" in ctx2["grants"], ctx2)
    n=len(EV); out=toolguard.run("computer", tools.computer, {"action":"type","text":"x"}, agent.call_tool); ok(out.startswith("Done") and len(EV)==n, "second action: no new question")
    log=toolguard.recent(3); ok(log[0]["decision"]=="approved earlier this turn" and log[1]["decision"]=="approved", log)
finally:
    toolguard.current.reset(tok)
EV.clear(); ctx3={"source":"web","emit":EV.append,"out":[]}; tok=toolguard.current.set(ctx3)
try:
    answer_soon(False); out=toolguard.run("computer", tools.computer, {"action":"click","x":5,"y":6}, agent.call_tool)
    ok(out.startswith("Not run: the user did not approve") and "grants" not in ctx3, out)
finally:
    toolguard.current.reset(tok)
# Signal asks with a clear message
mc.computer["max_actions"]=3; SIG=[]; toolguard.ask_signal["send"]=lambda t:(SIG.append(t) or (True,"ok"))
ctx4={"source":"signal","emit":None,"out":[]}; tok=toolguard.current.set(ctx4)
try:
    answer_soon(True); toolguard.run("computer", tools.computer, {"action":"click","goal":"close the popup","x":1,"y":1}, agent.call_tool)
    ok(SIG and "control your mouse and keyboard" in SIG[0] and "up to 3 actions" in SIG[0] and "close the popup" in SIG[0], SIG)
finally:
    toolguard.current.reset(tok)

# ── the laptop agent ──
import importlib.util
spec=importlib.util.spec_from_file_location("dagent","daemon-agent.py"); dagent=importlib.util.module_from_spec(spec); spec.loader.exec_module(dagent)
funcs=dagent.load_tools(set()); ok("screen_input" not in funcs and "screen_grab" in funcs, sorted(funcs))
funcs=dagent.load_tools({"screen_input"}); ok("screen_input" in funcs, sorted(funcs))
ok(dagent.run_tool(dagent.load_tools(set()),"screen_input",{"action":"click"}).startswith("Error: screen_input is not allowed on this laptop (start the agent with --allow screen_input)"), "needs --allow")
dagent.STOP_FILE=__import__("pathlib").Path(os.path.abspath("stopfile44")); dagent.STOP_FILE.write_text("")
ok("emergency brake" in dagent.run_tool(funcs,"screen_input",{"action":"key","keys":"enter"}), "brake")
dagent.STOP_FILE.unlink()
si_calls.clear(); tools.grab_geometry.update(real=(1000,500), view=(1000,500)); r=dagent.run_tool(funcs,"screen_input",{"action":"key","keys":"enter"}); ok(r.startswith("OK ") and si_calls, r)
ok(dagent.load_args.__doc__ is None or True, "")

# ── Hyprland with Lua syntax: the dispatcher fails, ydotool steers by cursorpos; two monitors are one screenshot ──
os.environ.pop("DISPLAY"); os.environ["WAYLAND_DISPLAY"]="wayland-1"; os.environ["HYPRLAND_INSTANCE_SIGNATURE"]="abc"
POS=[500.0,500.0]; CALLS2=[]
def hrunner(argv, timeout=6):
    CALLS2.append(argv)
    if argv[:3]==["hyprctl","dispatch","movecursor"]: return True, "error: 3 [string \"return hl.dispatch(movecursor 960 540)\"]:1: ')' expected near '960'"
    if argv[:2]==["hyprctl","cursorpos"]: return True, "%d, %d" % (POS[0], POS[1])
    if argv[:2]==["ydotool","mousemove"]:
        POS[0]+=int(argv[3])*1.7; POS[1]+=int(argv[5])*1.7       # pointer acceleration: one unit moves 1.7 px
        return True, ""
    if argv[:2]==["hyprctl","-j"]: return True, json.dumps([{"x":0,"y":0,"width":2880,"height":1800,"scale":1.5,"transform":0,"focused":True},{"x":1920,"y":0,"width":1344,"height":768,"scale":1.0,"transform":0}])
    return True, ""
si.runner=hrunner; si._hypr["classic"]=None
hy=si.detect(); ok(si.logical_screen(hy)==(0,0,3264.0,1200.0), si.logical_screen(hy))
si.move_to(hy, 1632, 600); ok(abs(POS[0]-1632)<=2 and abs(POS[1]-600)<=2, POS); ok(si._hypr["classic"] is False, "remembers that the dispatcher does not work")
n=len([c for c in CALLS2 if c[:3]==["hyprctl","dispatch","movecursor"]]); si.move_to(hy, 100, 100); ok(len([c for c in CALLS2 if c[:3]==["hyprctl","dispatch","movecursor"]])==n and abs(POS[0]-100)<=2, "does not retry the dispatcher")
si.runner=runner; os.environ.pop("WAYLAND_DISPLAY"); os.environ.pop("HYPRLAND_INSTANCE_SIGNATURE"); os.environ["DISPLAY"]=":0"
print("COMPUTER OK")

# ── focused box + grid ──
import json as _j
calls=[]
def r1(cmd,*a,**k): 
    calls.append(cmd)
    return (True,_j.dumps([{"name":"DP-1","x":0,"y":0,"width":1920,"height":1080,"scale":1,"focused":False},{"name":"eDP-1","x":1920,"y":0,"width":1920,"height":1080,"scale":1.2,"focused":True}]))
orig=si.run; si.run=r1
fb=si.focused_box({"move":"hyprctl"}); ok(fb==(1920,0,1600.0,900.0), fb)
si.run=orig
d={"move":"hyprctl","found":{}}
p=si.to_screen(d,100,50,(1000,562),(1600,900),(1920,0,1600.0,900.0)); ok(abs(p[0]-(1920+160))<2 and abs(p[1]-80)<2, p)
from PIL import Image
g=tools._with_grid(Image.new("RGB",(400,300),(255,255,255))); ok(g.size==(400,300) and g.getpixel((100,150))!=(255,255,255), "grid drawn")
print("focus tests done")

# ── shortcuts ──
binds=[{"modmask":64,"key":"Return","dispatcher":"exec","arg":"kitty","description":"","mouse":False,"submap":""},
       {"modmask":65,"key":"Q","dispatcher":"killactive","arg":"","description":"Close window","mouse":False,"submap":""},
       {"modmask":64,"key":"mouse:272","dispatcher":"movewindow","arg":"","mouse":True,"submap":""}]
si.run=lambda cmd,*a,**k:(True,_j.dumps(binds)) if "binds" in cmd else (False,"")
txt=si.shortcuts({"move":"hyprctl","found":{"hyprctl":"/usr/bin/hyprctl"}})
ok("super+return: exec kitty" in txt and "super+shift+q: Close window" in txt and "mouse" not in txt, txt)
si.run=orig
r=tools.screen_input("shortcuts"); ok(r.startswith("OK ") and "shortcuts" in r, r)
print("shortcut tests done")
hy2={"key":"wtype","found":{"ydotool":"/x"}}
ok(si.cmd_key(hy2,"super+space")==[["ydotool","key","125:1","57:1","57:0","125:0"]] and si.cmd_key(hy2,"shift+a")==[["ydotool","key","42:1","30:1","30:0","42:0"]] and si.cmd_key(hy2,"period")[0][0]=="wtype" and si.parse_combo("super")==([],"super"), "super via ydotool")
print("key tests done")

# ── zoom + pointer ring ──
from PIL import Image as _I
full=_I.new("RGB",(1920,1080),(255,255,255))
tools.grab_geometry.update(view=(1568,882), real=(1920,1080), box=(1920,0,1600.0,900.0))
ok(tools._to_view((1920+800,450),(1920,0,1600.0,900.0),(1568,882))==(784.0,441.0), tools._to_view((2720,450),(1920,0,1600.0,900.0),(1568,882)))
ok(tools._to_view((100,100),(1920,0,1600.0,900.0),(1568,882)) is None, "other monitor -> no ring")
tools.last_shot.update(full=full, pointer=(784,441))
data,ext,w,h=tools._zoom_shot(784,441); ok((w,h)==(1040,640) and ext=="jpg", (w,h))
data,ext,w,h=tools._zoom_shot(5,5); ok((w,h)==(1040,640), "edge clamp")
import io; z=_I.open(io.BytesIO(tools._zoom_shot(784,441)[0])); px=z.getpixel(((784-654)*4+16,(441-361)*4)); ok(px[0]>200 and px[2]<120, ("ring", px))
r=tools.screen_grab(zoom="784,441"); ok(r.startswith("OK "), r)
tools.last_shot.update(full=None); ok("screenshot first" in tools.screen_grab(zoom="1,1"), "zoom needs shot")
ok(toolguard.check("computer",{"action":"zoom"})==(True,"auto"), "zoom no approval")
print("zoom tests done")

# ── 0-1000 grid models ──
import model_config as _mc
_mc.llm["model"]="nvidia/nemotron-3.5-super-vl-120b-a12b"; ok(tools.coord_units({"coords":"auto"})=="1000", "auto nemotron")
_mc.llm["model"]="gpt-4o"; ok(tools.coord_units({"coords":"auto"})=="" and tools.coord_units({"coords":"1000"})=="1000", "auto other")
CFG.update(coords="1000", max_actions=30); REMOTE.clear(); CAPS=[]
def cap2(where="", clipboard=False, focus=False, zoom="", units="", monitor=""):
    CAPS.append((zoom,units)); return {"name":"screenshots/x.jpg","size":"1920x1080","window":"Firefox","sees":True}
tools._capture=cap2; tools.computer_view["size"]=(0,0)
tools.remote["names"]=lambda: {"media_control"}; tools.remote["call"]=lambda name,args:(REMOTE.append((name,args)) or "OK "+json.dumps({"did":"clicked (left) at (1, 2)","window":"Firefox"}))
tok=toolguard.current.set({"source":"web","grants":{"computer"},"computer_seen":True})
r=tools.computer("click",x=500,y=500); ok("screenshot first" in r, r)
r=tools.computer("screenshot"); ok("0-1000 grid" in r and CAPS[-1][1]=="1000" and tools.computer_view["size"]==(1920,1080), r)
r=tools.computer("click",x=500,y=250); ok(REMOTE[-1][1]["x"]==960 and REMOTE[-1][1]["y"]==270 and "at (500, 250)" in r, (REMOTE[-1], r))
r=tools.computer("zoom",x=100,y=100); ok(CAPS[-1]==("192,108","1000"), CAPS[-1])
r=tools.computer("click",x=1200,y=5); ok("outside the 0-1000" in r, r)
CFG["coords"]="pixels"; r=tools.computer("click",x=500,y=250); ok(REMOTE[-1][1]["x"]==500, REMOTE[-1])
toolguard.current.reset(tok)
# norm grid + zoom labels in units
from PIL import Image as _I2
g=tools._with_grid(_I2.new("RGB",(1920,1080),(255,255,255)),units="1000"); ok(g.getpixel((960,540))!=(255,255,255), "norm grid")
tools.grab_geometry.update(view=(1920,1080)); tools.last_shot.update(full=_I2.new("RGB",(1920,1080),(255,255,255)),pointer=None,units="1000")
d,e,w,h=tools._zoom_shot(960,540); ok(w==1040, w)
open("../zoom1000.jpg","wb").write(d)
print("grid1000 tests done")

# ── wait after approval ──
CFG.update(coords="pixels", approval_delay=0.4); REMOTE.clear()
c2={"source":"web","grants":{"computer"},"computer_seen":True,"computer_approved_at":time.time()}; tok=toolguard.current.set(c2)
t0=time.time(); tools.computer("screenshot"); ok(time.time()-t0<0.3 and "computer_approved_at" in c2, "screenshot does not wait")
t0=time.time(); tools.computer("click",x=1,y=2); ok(0.3<time.time()-t0<1.0 and "computer_approved_at" not in c2, time.time()-t0)
t0=time.time(); tools.computer("click",x=1,y=2); ok(time.time()-t0<0.3, "only once")
toolguard.current.reset(tok)
print("approval delay tests done")

# ── screens: list, choice, lock per turn; plain screenshots do not change the click mapping ──
mons=[{"name":"DP-1","x":0,"y":0,"width":1920,"height":1080,"scale":1,"focused":False},{"name":"eDP-1","x":1920,"y":0,"width":1920,"height":1080,"scale":1.2,"focused":True}]
si.runner=lambda argv,t:(True,_j.dumps(mons)) if argv[:3]==["hyprctl","-j","monitors"] else (True,"")
hd={"move":"hyprctl","found":{"hyprctl":"x"}}
ok([m["name"] for m in si.monitors(hd)]==["DP-1","eDP-1"], si.monitors(hd))
ok(si.monitor_box(hd)==(1920,0,1600.0,900.0,"eDP-1") and si.monitor_box(hd,"dp-1")==(0,0,1920,1080,"DP-1") and si.monitor_box(hd,"nope")[4]=="eDP-1", "monitor_box")
ok(si.focused_box(hd)==(1920,0,1600.0,900.0), "focused_box")
si.runner=None
CAPS.clear()
def cap3(where="", clipboard=False, focus=False, zoom="", units="", monitor=""):
    CAPS.append(monitor); m=monitor or "eDP-1"
    return {"name":"x","size":"1920x1080","window":"Blender","sees":True,"monitor":m,"monitors":["DP-1","eDP-1"]}
tools._capture=cap3; CFG.update(coords="1000")
c3={"source":"web","grants":{"computer"},"computer_seen":True}; tok=toolguard.current.set(c3)
r=tools.computer("screenshot"); ok("shows the screen eDP-1; other screens: DP-1" in r and c3["computer_monitor"]=="eDP-1", r)
tools.computer("click",x=10,y=10); ok(CAPS[-1]=="eDP-1", CAPS)
r=tools.computer("screenshot",text="DP-1"); ok(CAPS[-1]=="DP-1" and "shows the screen DP-1; other screens: eDP-1" in r, r)
tools.computer("click",x=10,y=10); ok(CAPS[-1]=="DP-1", CAPS)
toolguard.current.reset(tok)
# plain screenshot keeps the computer mapping
tools.grab_geometry.update(view=(1920,1080), real=(1920,1080), box=(1920,0,1600.0,900.0))
print("screen tests done")

# ── look first: no click before the computer tool's own screenshot this turn; screens list their apps ──
CAPS.clear(); REMOTE.clear()
def cap4(where="", clipboard=False, focus=False, zoom="", units="", monitor=""):
    CAPS.append(monitor); return {"name":"x","size":"1920x1080","window":"Blender","sees":True,"monitor":"eDP-1","monitors":["DP-1","eDP-1"],
                                  "windows":{"DP-1":["firefox"],"eDP-1":["blender","kitty"]}}
tools._capture=cap4; CFG.update(coords="1000")
c5={"source":"web","grants":{"computer"}}; tok=toolguard.current.set(c5)
r=tools.computer("click",x=451,y=589); ok(r.startswith("Nothing done yet") and not REMOTE and c5["computer_seen"], r)
ok("eDP-1 (blender, kitty); other screens: DP-1 (firefox)" in r, r)
r=tools.computer("click",x=451,y=589); ok(r.startswith("Done") and REMOTE, r)
r=tools.computer("key",keys="enter"); ok(r.startswith("Done"), r)
toolguard.current.reset(tok)
c6={"source":"web","grants":{"computer"}}; tok=toolguard.current.set(c6); REMOTE.clear()
r=tools.computer("key",keys="enter"); ok(r.startswith("Done") and REMOTE, "keys need no look first")
toolguard.current.reset(tok)
# screeninput: active window's screen first, windows per screen
mons=[{"name":"DP-1","id":0,"x":0,"y":0,"width":1920,"height":1080,"scale":1,"focused":True,"activeWorkspace":{"id":1}},
      {"name":"eDP-1","id":1,"x":1920,"y":0,"width":1920,"height":1080,"scale":1.2,"focused":False,"activeWorkspace":{"id":2}}]
cl=[{"class":"blender","monitor":1,"workspace":{"id":2},"mapped":True},{"class":"firefox","monitor":0,"workspace":{"id":1}},
    {"class":"hidden-app","monitor":0,"workspace":{"id":5}}]
def rr(argv,t):
    if argv[:3]==["hyprctl","-j","monitors"]: return True,_j.dumps(mons)
    if argv[:3]==["hyprctl","-j","activewindow"]: return True,_j.dumps({"class":"blender","monitor":1})
    if argv[:3]==["hyprctl","-j","clients"]: return True,_j.dumps(cl)
    return True,""
si.runner=rr
ok(si.monitor_box(hd)[4]=="eDP-1", "active window's screen wins over the mouse focus")
ok(si.monitor_box(hd,"DP-1")[4]=="DP-1", "named screen")
ok(si.screen_windows(hd)=={"DP-1":["firefox"],"eDP-1":["blender"]}, si.screen_windows(hd))
si.runner=None
print("look-first tests done")
c7={"source":"web","grants":{"computer"}}; tok=toolguard.current.set(c7)
ok("controlling the computer" in tools.screenshot(), "plain screenshot blocked during computer use")
toolguard.current.reset(tok)
print("block tests done")
# key bindings come once per turn with the first screenshot
tools._keys_cache.update(text="close: super+q", at=9e12)
c8={"source":"web","grants":{"computer"}}; tok=toolguard.current.set(c8)
r1=tools.computer("screenshot"); r2=tools.computer("screenshot")
ok("key bindings" in r1 and "close: super+q" in r1 and "key bindings" not in r2, (r1[-200:], r2[-100:]))
toolguard.current.reset(tok)
# agent: more rounds while the computer is in use, longer tool output
import agent as _ag
ok(_ag._limit(6)==6, "normal turn")
tok=toolguard.current.set({"grants":{"computer"}}); CFG["max_actions"]=30; ok(_ag._limit(6)==38, _ag._limit(6)); toolguard.current.reset(tok)
ok(_ag._out_cap("computer")==10000 and _ag._out_cap("x")==4000, "cap")
print("keys+rounds tests done")

# ── screen kept across turns; text=<screen> on a click switches + looks first; unbound alt+tab refused ──
CAPS.clear(); REMOTE.clear(); tools.computer_view.update(monitor="", monitors=[], at=0)
def cap5(where="", clipboard=False, focus=False, zoom="", units="", monitor=""):
    CAPS.append(monitor); m=monitor or "eDP-1"
    return {"name":"x","size":"1920x1080","window":"","sees":True,"monitor":m,"monitors":["DP-1","eDP-1"]}
tools._capture=cap5; tools._keys_cache.update(text="close: super+q\nsuper+tab: runs dms ipc call hypr toggleOverview", at=9e12)
t1={"source":"web","grants":{"computer"}}; tok=toolguard.current.set(t1)
tools.computer("screenshot", text="DP-1"); ok(CAPS[-1]=="DP-1", CAPS)
toolguard.current.reset(tok)
t2={"source":"web","grants":{"computer"}}; tok=toolguard.current.set(t2)
tools.computer("screenshot"); ok(CAPS[-1]=="DP-1", ("next turn keeps DP-1", CAPS))
r=tools.computer("click", x=10, y=10, text="eDP-1"); ok(r.startswith("Nothing done yet") and CAPS[-1]=="eDP-1" and not REMOTE, r[:80])
r=tools.computer("click", x=10, y=10, text="eDP-1"); ok(r.startswith("Done") and REMOTE, r[:80])
r=tools.computer("key", keys="alt+tab"); ok("does nothing on this desktop" in r and len(REMOTE)==1, r)
r=tools.computer("key", keys="super+tab"); ok(r.startswith("Done"), r[:60])
toolguard.current.reset(tok)
print("screen memory tests done")

si._keymap["name"]="Turkish"; ok(si.cmd_key({"key":"wtype","found":{"ydotool":"x"}},"ctrl+i")==[["ydotool","key","29:1","40:1","40:0","29:0"]], "tr i")
si._keymap["name"]="English (US)"; ok(si.cmd_key({"key":"wtype","found":{"ydotool":"x"}},"i")==[["ydotool","key","23:1","23:0"]], "us i")
print("layout tests done")
