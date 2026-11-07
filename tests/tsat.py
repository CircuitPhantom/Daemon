import types, os, sys, time, threading, subprocess, json, urllib.request
sys.path[:0]=["stubs","."]
os.environ.update(DAEMON_CONFIG="cfg18.yaml", DAEMON_CHATS="chats18", DAEMON_MEMORY="mem18.json", DAEMON_REMINDERS="rem18.json", DAEMON_CALENDAR="cal18.json")
for f in ("cfg18.yaml","mem18.json","rem18.json","cal18.json"):
    if os.path.exists(f): os.remove(f)
def ok(c,m=""):
    if not c: print("FAIL",m); sys.exit(1)
import model_config as mc
r=subprocess.run([sys.executable,"satellite_setup.py"],capture_output=True,text=True); ok("--token" in r.stdout, r.stdout+r.stderr)
tok=mc.satellite["token"] if mc.satellite["token"] else None
mc.load(); tok=mc.satellite["token"]; ok(len(tok)>=32 and mc.satellite["enabled"], "setup wrote token")
ok(oct(os.stat("cfg18.yaml").st_mode)[-3:]=="600")
import server, tools, satellite, auth, uvicorn, ollama
# offline first
r=tools.available_functions["media_control"](action="status"); ok("offline" in r, r)
cfg=uvicorn.Config(server.app,host="127.0.0.1",port=8795,log_level="warning"); us=uvicorn.Server(cfg)
th=threading.Thread(target=us.run,daemon=True); th.start()
for _ in range(100):
    try: urllib.request.urlopen("http://127.0.0.1:8795/api/auth/status",timeout=1); break
    except Exception: time.sleep(0.2)
server.voice.stt.transcribe=lambda *a,**k:(iter([types.SimpleNamespace(text=" hey daemon time")]),None)
# PIN on: agent endpoints must still use the token only
auth.set_pin("4821")
def get(path,tk=None,data=None,ctype="application/json"):
    h={"Content-Type":ctype}
    if tk: h["Authorization"]="Bearer "+tk
    try:
        with urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8795"+path,data=data,headers=h),timeout=20) as r: return r.status,r.read()
    except urllib.error.HTTPError as e: return e.code,e.read()
ok(get("/api/sat/config")[0]==401 and get("/api/sat/config","wrong")[0]==401, "no token")
st,b=get("/api/sat/config",tok); ok(st==200 and "phrase" in json.loads(b)["wake"], b)
ok(get("/api/settings")[0]==401, "dashboard still locked")
st,b=get("/api/sat/transcribe",tok,b"\0"*40000,"application/octet-stream"); ok(st==200 and "text" in json.loads(b), (st,b))
st,b=get("/api/sat/turn",tok,json.dumps({"text":"hello"}).encode()); ok(st==200 and b'"type"' in b, (st,b[:200]))
ok(get("/api/sat/turn","bad",json.dumps({"text":"hello"}).encode())[0]==401, "turn needs token")
import importlib.util, numpy as np
sp=importlib.util.spec_from_file_location("dagent","daemon-agent.py"); dag=importlib.util.module_from_spec(sp); sp.loader.exec_module(dag)
srv=dag.Server("http://127.0.0.1:8795",tok)
ok(srv.config()["wake"]["phrase"]=="hey daemon", "agent reads config")
ok("hey daemon" in srv.transcribe(np.zeros(16000,dtype=np.float32),"Daemon."), "agent transcribe")
evs=[]; srv.turn("what time",evs.append,threading.Event()); ok(evs and evs[-1]["type"]=="done", evs[-2:])
shim=types.ModuleType("model_config"); shim.wake=dict(srv.config()["wake"]); real=sys.modules["model_config"]; sys.modules["model_config"]=shim
import importlib; sys.modules.pop("wakeword",None); import wakeword as _w
ok(_w.find_wake("hey daemon what time",shim.wake["phrase"],shim.wake["aliases"])=="what time", "wakeword with the shim"); sys.modules["model_config"]=real; sys.modules.pop("wakeword",None)
fw=types.ModuleType("faster_whisper")
class FW:
    def __init__(self,*a,**k): self.args=(a,k)
    def transcribe(self,audio,**k): return iter([types.SimpleNamespace(text=" hey daemon what time")]),None
fw.WhisperModel=FW; sys.modules["faster_whisper"]=fw
ls=dag.LocalSTT("base","cpu","int8",lambda a,p:"SERVER")
ok(ls(np.zeros(16000,dtype=np.float32),"Daemon.")=="hey daemon what time", "local stt")
sys.modules["faster_whisper"]=types.ModuleType("faster_whisper")      # no WhisperModel: falls back to the server
ls2=dag.LocalSTT("base","cpu","int8",lambda a,p:"SERVER")
ok(ls2(np.zeros(16000,dtype=np.float32))=="SERVER" and ls2.failed, "fallback to server stt")
sys.modules.pop("faster_whisper")
# agent subprocess with a fake playerctl
open("sat_state","w").write("playing")
env=dict(os.environ,FAKELOG=os.path.abspath("sat_log"),FAKESTATE=os.path.abspath("sat_state"),FAKELOADED=os.path.abspath("sat_loaded"),PATH=os.path.abspath("fakebin")+":"+os.environ["PATH"])
bad=subprocess.Popen([sys.executable,"daemon-agent.py","--no-wake","--server","http://127.0.0.1:8795","--token","wrongwrongwrongwrong"],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
time.sleep(3); ok(not satellite.hub.connected, "wrong token must not connect"); bad.kill()
ag=subprocess.Popen([sys.executable,"-u","daemon-agent.py","--no-wake","--server","http://127.0.0.1:8795","--token",tok],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
for _ in range(100):
    if satellite.hub.connected: break
    time.sleep(0.2)
ok(satellite.hub.connected and satellite.hub.name, "agent connected: "+(ag.stdout.read(500) if ag.poll() is not None else "still running"))
ok(satellite.hub.status()["connected"] and "media_control" in satellite.hub.tools, satellite.hub.status())
ok(server.conv.wake_state()["satellite"] and server.conv.wake_state()["running"], "wake state")
r=tools.available_functions["media_control"](action="status"); ok("Playing" in r, r)       # fake playerctl exists only on the "laptop"
ok(shutil_which:=__import__("shutil").which("playerctl") is None, "server has no playerctl")
r=tools.available_functions["clipboard_read"](); ok(r.startswith("Error"), r)
_oc=tools.remote["call"]; CALLED=[]
tools.remote["call"]=lambda n,a:(CALLED.append((n,a)),_oc(n,a))[1]
r=tools.available_functions["system_info"](); ok("Memory" in r and CALLED and CALLED[-1][0]=="system_info", (r,CALLED))
n=len(CALLED); r=tools.available_functions["system_info"](where="server"); ok("Memory" in r and len(CALLED)==n, "server stays local")
tools.remote["call"]=_oc
# a tool that is not in satellite.tools runs on the server
r=tools.available_functions["get_time"](); ok("Error" not in r)
# spotify low-level goes remote
r=tools._spotify_open("spotify:track:abc"); ok(isinstance(r,str), r)
# not allowed on the laptop by default
mc.satellite["tools"].append("execute_command")
r=tools.available_functions["execute_command"](cmnd="echo hi"); ok("not allowed on this laptop" in r, r)
mc.satellite["tools"].remove("execute_command")
r=tools.available_functions["execute_command"](cmnd="echo hi"); ok("hi" in r, r)           # back on the server
# disconnect
ag.kill(); ag.wait()
for _ in range(50):
    if not satellite.hub.connected: break
    time.sleep(0.2)
ok(not satellite.hub.connected, "disconnect noticed")
r=tools.available_functions["media_control"](action="status"); ok("offline" in r, r)
# off switch: tools run on the server again
subprocess.run([sys.executable,"satellite_setup.py","--off"],capture_output=True); mc.load()
ok(not satellite.enabled(), "off"); r=tools.available_functions["media_control"](action="status"); ok("offline" not in r, r)
print("ALL OK")
us.should_exit=True
