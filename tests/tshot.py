import os, sys, io, json, time, shutil, threading, subprocess, urllib.request, http.client, importlib.util
sys.path[:0]=["stubs","."]
os.environ.update(DAEMON_CONFIG="cfg40.yaml", DAEMON_CHATS="chats40", DAEMON_MEMORY="mem40.json", DAEMON_REMINDERS="rem40.json",
                  DAEMON_TOOL_LOG=os.path.abspath("toollog40.jsonl"), DAEMON_FILES=os.path.abspath("files40"))
for f in ("cfg40.yaml","mem40.json","rem40.json","toollog40.jsonl"):
    if os.path.exists(f): os.remove(f)
shutil.rmtree("chats40", ignore_errors=True); shutil.rmtree("files40", ignore_errors=True)
def ok(c,m=""):
    if not c: print("FAIL",m); sys.exit(1)
def wait(cond,t=15):
    end=time.time()+t
    while time.time()<end:
        if cond(): return True
        time.sleep(0.05)
    return False
open("cfg40.yaml","w").write('model: qwen3:1.7b\ntools: [screenshot, get_time]\nsecurity:\n  confirm: false\n')
subprocess.run([sys.executable,"satellite_setup.py"],capture_output=True)
import model_config as mc; ok(mc.load()); tok=mc.satellite["token"]
import tools, server, ollama
from PIL import Image
def fake():
    im=Image.new("RGB",(3000,1700),(10,80,200)); b=io.BytesIO(); im.save(b,"PNG"); return b.getvalue()
# 1) the grabber: fake binary on PATH writes a png; result is shrunk to a jpeg
os.makedirs("fakeshot",exist_ok=True)
open("fakeshot/grim","w").write("#!/bin/bash\ncp %s \"$1\"\n"%os.path.abspath("fake_screen.png"))
open("fake_screen.png","wb").write(fake()); os.chmod("fakeshot/grim",0o755)
os.environ["PATH"]=os.path.abspath("fakeshot")+":"+os.environ["PATH"]; os.environ["WAYLAND_DISPLAY"]="wayland-0"
data,ext,w,h=tools._grab_screen()
ok(ext=="jpg" and max(w,h)==tools.SHOT_EDGE and data[:2]==b"\xff\xd8", (ext,w,h))
# no screenshot tool at all -> clear error
os.environ["PATH"]="/nonexistent"
try: tools._grab_screen(); ok(False,"should raise")
except RuntimeError as e: ok("grim" in str(e), e)
os.environ["PATH"]=os.path.abspath("fakeshot")+":/usr/bin:/bin"
# 2) local screenshot tool + vision hook
real_call=tools.remote["call"]; tools.remote["call"]=None
tools.hooks["vision"]=lambda: False
box=[]; tools.shots.set(box)
out=tools.screenshot(); ok(out.startswith("Screenshot taken") and "cannot look" in out and not box, out)
name=out.split("File name: ")[1].split("\n")[0]
ok(name.startswith("screenshots/screen-") and (tools._files_dir()/name).exists(), name)
tools.hooks["vision"]=lambda: True
out=tools.screenshot(); ok("follows in the next message" in out and len(box)==1 and len(box[0])>1000, out)
tools.remote["call"]=real_call; tools.remote["names"]=lambda: set()
# 3) a turn through the server: the model gets the picture once, then it is gone from the history
for i in range(45): tools._save_shot(b"x"*10,"jpg")   # pruning
ok(len(list((tools._files_dir()/"screenshots").glob("screen-*")))<=tools.SHOT_KEEP, "pruned")
server.conv.vision_flags=lambda: (True,True)
import uploads; uploads.model_sees=lambda *a,**k: True
ollama.SEEN.clear()
evs=[]
def run():
    server.conv.turn_job("shot:", False, lambda e: evs.append(e), threading.Event(), source="web")
run()
done=[e for e in evs if e.get("type")=="done"]; ok(done and not [e for e in evs if e.get("type")=="error"], evs[-2:])
seen_img=[s for s in ollama.SEEN if isinstance(s["last"],dict) and s["last"].get("images")]
ok(len(seen_img)==1 and seen_img[0]["last"]["role"]=="user", "model got the screenshot as a user message")
ok(not any(isinstance(m,dict) and m.get("images") for m in server.conv.messages), "images dropped after the turn")
ok(any(isinstance(m,dict) and "not kept" in str(m.get("content")) for m in server.conv.messages), "placeholder kept")
tl=[json.loads(l) for l in open("toollog40.jsonl")]; ok(tl[-1]["tool"]=="screenshot", tl[-1])
# 4) model cannot see -> no image
tools.hooks["vision"]=lambda: False; ollama.SEEN.clear(); evs.clear(); run()
ok(not [s for s in ollama.SEEN if isinstance(s["last"],dict) and s["last"].get("images")], "no image for a blind model")
# 5) laptop path: agent endpoint + upload through the Server class
cfg=__import__("uvicorn").Config(server.app,host="127.0.0.1",port=8796,log_level="warning"); us=__import__("uvicorn").Server(cfg)
threading.Thread(target=us.run,daemon=True).start()
for _ in range(100):
    try: urllib.request.urlopen("http://127.0.0.1:8796/api/auth/status",timeout=1); break
    except Exception: time.sleep(0.2)
sp=importlib.util.spec_from_file_location("dagent","daemon-agent.py"); dag=importlib.util.module_from_spec(sp); sp.loader.exec_module(dag)
srv=dag.Server("http://127.0.0.1:8796",tok)
n=srv.shot(data,"jpg"); ok(n.startswith("screenshots/") and (tools._files_dir()/n).read_bytes()==data, n)
bad=dag.Server("http://127.0.0.1:8796","nope")
try: bad.shot(data,"jpg"); ok(False,"token needed")
except Exception as e: ok("401" in str(e), e)
ok("screen_grab" in dag.load_tools(set()), "agent may run screen_grab")
tools.shot_sink["fn"]=srv.shot
r=tools.screen_grab(); ok(r.startswith("OK {") and json.loads(r[3:])["name"].startswith("screenshots/") and json.loads(r[3:])["size"]==f"{w}x{h}", r)
tools.shot_sink["fn"]=None
# server-side screenshot() asks the laptop when the satellite is on
calls=[]
tools.remote["call"]=lambda n,a:(calls.append(n), "OK "+tools._save_shot(data,"jpg")+f" {w}x{h}")[1]
tools.remote["names"]=lambda: {"system_info"}
box=[]; tools.shots.set(box); tools.hooks["vision"]=lambda: True
r=tools.screenshot(); ok(calls==["screen_grab"] and box, (calls,r))
r=tools.screenshot(where="server"); ok(calls==["screen_grab"], "where=server stays local")
tools.remote["call"]=lambda n,a:"Error: the laptop is offline"
r=tools.screenshot(); ok(r.startswith("Error") and "offline" in r, r)
print("PASS tshot")
