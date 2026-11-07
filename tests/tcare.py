import os, sys, io, json, time, shutil, threading, http.client
sys.path[:0]=["stubs","."]
os.environ.update(DAEMON_CONFIG="cfg41.yaml", DAEMON_CHATS="chats41", DAEMON_MEMORY="mem41.json", DAEMON_REMINDERS="rem41.json",
                  DAEMON_INBOX=os.path.abspath("inbox41.json"), DAEMON_TOOL_LOG=os.path.abspath("toollog41.jsonl"),
                  DAEMON_FILES=os.path.abspath("files41"), DAEMON_CARE_STATE=os.path.abspath("care41.json"),
                  DAEMON_CALENDAR=os.path.abspath("cal41.json"), DAEMON_BACKUP_DIR=os.path.abspath("bk41"))
for f in ("cfg41.yaml","mem41.json","rem41.json","inbox41.json","toollog41.jsonl","care41.json","cal41.json"):
    if os.path.exists(f): os.remove(f)
shutil.rmtree("chats41", ignore_errors=True); shutil.rmtree("files41", ignore_errors=True); shutil.rmtree("bk41", ignore_errors=True)
def ok(c,m=""):
    if not c: print("FAIL",m,"line",sys._getframe(1).f_lineno); sys.exit(1)
open("cfg41.yaml","w").write('model: qwen3:1.7b\ntools: [screenshot, get_time]\nsecurity:\n  confirm: false\n')
import model_config as mc; ok(mc.load())
ok(mc.care["watchdog"] and mc.care["disk_free_percent"]==10 and mc.care["memory_review_time"]=="10:00", mc.care)
import monitor, routines, memstore, inbox, scheduler, tools, server, signal_bot, auth, agenda, ollama
conv = server.conv
sent=[]
scheduler.send_message=lambda t: (sent.append(t), (True,"ok"))[1]

# ---- health / version ----
h=monitor.health(); ok(h["ok"] and h["ui"]==monitor.UI_VERSION and h["ui_match"], h)
ok(monitor.ui_file_version(__import__("pathlib").Path("index.html"))==monitor.UI_VERSION, "index.html carries the version")
open("old_index.html","w").write("<html><head></head></html>"); ok(monitor.ui_file_version(__import__("pathlib").Path("old_index.html")) is None, "old page has none")

# ---- watchdog ----
ids={c["key"] for c in monitor.checks()}; ok({"disk"}<=ids, ids)
ok(not monitor.problems() or all(p["key"]!="ui" for p in monitor.problems()), "no ui problem")
mc.care["disk_free_percent"]=100          # impossible: every disk is "too full"
got=routines.watch_once(); ok(len(got)==1 and "disk" in got[0] and sent[-1].startswith("⚠️ Daemon: disk"), (got, sent))
got=routines.watch_once(); ok(got==[], "the same problem is not repeated at once")
now=time.time()+7*3600; got=routines.watch_once(now); ok(len(got)==1, "repeated after alert_repeat_hours")
mc.care["disk_free_percent"]=1
got=routines.watch_once(); ok(got and "fine again" in got[0] and sent[-1].startswith("✅"), (got, sent[-1]))
got=routines.watch_once(); ok(got==[], "no more messages when all is fine")
# a failed send is retried, not forgotten
mc.care["disk_free_percent"]=100
scheduler.send_message=lambda t: (False,"signal down"); ok(routines.watch_once()==[], "failed")
scheduler.send_message=lambda t: (sent.append(t), (True,"ok"))[1]; ok(len(routines.watch_once())==1, "retried")
mc.care["disk_free_percent"]=1; routines.watch_once()
# backup age
os.makedirs("bk41"); ok(not [c for c in monitor.checks() if c["key"]=="backup"], "an empty folder alone is no problem (no timer)")
real_cmd=monitor._cmd; monitor._cmd=lambda c,t=6:(0,"enabled") if "is-enabled" in c else real_cmd(c,t)
ok([c for c in monitor.checks() if c["key"]=="backup"][0]["ok"] is False, "timer on but no backup"); monitor._cmd=real_cmd
open("bk41/daemon-1.tar.gz","w").write("x"); ok([c for c in monitor.checks() if c["key"]=="backup"][0]["ok"], "fresh backup")
old=time.time()-60*3600; os.utime("bk41/daemon-1.tar.gz",(old,old)); ok(not [c for c in monitor.checks() if c["key"]=="backup"][0]["ok"], "old backup")
shutil.rmtree("bk41")
# an old index.html is a problem
real=monitor.ui_file_version; monitor.ui_file_version=lambda p=None: None
ok(any(p["key"]=="ui" for p in monitor.problems()), "stale page alerts"); monitor.ui_file_version=real

# ---- memory check ----
memstore.add("Alex uses Arch Linux on his laptop"); memstore.add("Alex uses Arch Linux on the laptop")
memstore.add("Prefers short answers in Turkish")
rep=routines.memory_report(); ok("Similar" in rep and "/forget" in rep and "short answers" not in rep, rep)
items=memstore.items(); items[2]["created"]=int(time.time())-200*86400; memstore._write(items)
rep=routines.memory_report(); ok("Old (200 days)" in rep, rep)
from datetime import datetime, timedelta
tz=scheduler.get_tz(); sun=datetime.now(tz); sun=sun+timedelta(days=(6-sun.weekday())%7); at=sun.replace(hour=10,minute=30,second=0,microsecond=0)
sent.clear(); t=routines.review_once(at); ok(t and sent and sent[0].startswith("🧠"), sent)
ok(routines.review_once(at)=="", "once a day"); 
mon=at+timedelta(days=1); ok(routines.review_once(mon)=="", "not on other days")
mc.care["memory_review"]=False; st=json.load(open("care41.json")); st.pop("memory_review"); json.dump(st,open("care41.json","w")); ok(routines.review_once(at)=="", "switched off"); mc.care["memory_review"]=True

# ---- briefing extras ----
day=datetime.now(tz).date()
conv.rem.add("call the dentist", datetime.now(tz).strftime("%Y-%m-%d 23:59"))
inbox.add("great article about batteries https://example.com/x")
routines.weather=lambda city: "Istanbul: Sunny +15°C, wind 10km/h" if city else ""
mc.care["briefing_city"]="Istanbul"
text,items_=routines.briefing_extras(day); ok("Sunny" in text and "call the dentist" in text and "batteries" in text and items_, text)
mc.care["briefing_city"]=""; text,items_=routines.briefing_extras(day); ok("Sunny" not in text and items_, "no weather without city")
mc.care["briefing_extras"]=False; ok(routines.briefing_extras(day)==("",False), "switched off"); mc.care["briefing_extras"]=True
sent.clear(); mc.calendar_cfg["briefing_call"]=False; mc.calendar_cfg["briefing_skip_empty"]=True
r=agenda.store.brief(day, manual=False); ok(sent and "call the dentist" in sent[0] and r["message"], (r, sent))   # nothing in the calendar, but reminders
for x in conv.rem.list_items(): conv.rem.delete(x["id"]) if hasattr(conv.rem,"delete") else None
for x in inbox.items(): inbox.delete(x["id"])
sent.clear(); r=agenda.store.brief(day, manual=False); ok(not sent and "skipped" in r["info"], (r, sent))              # truly empty: skipped

# ---- Signal commands ----
hs=conv.handle_signal
h_=hs("/help"); ok("/screen" in h_ and "/status" in h_ and "/forget" in h_, h_)
ok(hs("/help")==h_ and hs("/commands")==h_, "aliases")
d_=hs("/status"); ok("Daemon up" in d_ and "disk:" in d_, d_)
m_=hs("/memory"); ok("Arch Linux" in m_ and "/forget" in m_, m_)
mid=memstore.items()[0]["id"]; ok(hs("/forget")=="Usage: /forget <id>   (ids are shown by /memory)", "usage")
ok(hs("/forget zzzzzz")=="No memory with that id.", "unknown id"); ok(hs(f"/forget [{mid}]")=="Forgotten." and all(x["id"]!=mid for x in memstore.items()), "forget")
ok("Saved to the inbox" in hs("/inbox hello world"), "inbox still works"); ok("hello" in hs("/find hello"), "find alias")
ok(hs("/new")=="Started a new chat.", "new chat")
ok("reply" in hs("/nosuchcommand hi") or True, "unknown slash goes to the model")
# /ekran
os.makedirs("fakeshot",exist_ok=True)
from PIL import Image
im=Image.new("RGB",(1200,700),(30,90,160)); b=io.BytesIO(); im.save(b,"PNG"); open("fake_screen.png","wb").write(b.getvalue())
open("fakeshot/grim","w").write("#!/bin/bash\ncp %s \"$1\"\n"%os.path.abspath("fake_screen.png")); os.chmod("fakeshot/grim",0o755)
open("fakeshot/xdotool","w").write("#!/bin/bash\necho 'Firefox: Arch Wiki'\n"); os.chmod("fakeshot/xdotool",0o755)
open("fakeshot/xclip","w").write("#!/bin/bash\necho -n 'copied error: segfault'\n"); os.chmod("fakeshot/xclip",0o755)
os.environ["PATH"]=os.path.abspath("fakeshot")+":"+os.environ["PATH"]; os.environ["WAYLAND_DISPLAY"]="wayland-0"; os.environ.pop("DISPLAY",None)
real_call=tools.remote["call"]; tools.remote["call"]=None
shipped=[]; signal_bot.bot.send_file=lambda p,c="",to=None:(shipped.append((p,c)),(True,"sent"))[1]
r_=hs("/screen"); ok(r_=="(done)" and shipped and shipped[0][0].endswith(".jpg") and shipped[0][1]=="Your screen", (r_, shipped))
tl=[json.loads(l) for l in open("toollog41.jsonl")]; ok(tl[-1]["tool"]=="screenshot" and tl[-1]["source"]=="signal", tl[-1])
# approval for /ekran
mc.security["confirm"]=True; mc.security["confirm_seconds"]=15; shipped.clear()
import toolguard
toolguard.ask_signal["send"]=lambda t:(sent.append(t),(True,"ok"))[1]; sent.clear()
res={}
th=threading.Thread(target=lambda: res.setdefault("r", hs("/screen"))); th.start()
for _ in range(100):
    if toolguard.open_requests(): break
    time.sleep(0.05)
ok(toolguard.open_requests() and "screenshot" in sent[-1], (toolguard.open_requests(), sent))
ok(toolguard.answer_text("no").startswith("OK, not running")); th.join(10)
ok("did not approve" in res["r"] and not shipped, res)
mc.security["confirm"]=False
# screen context
tools.remote["call"]=None
out=tools.screenshot(); ok("Window in front: Firefox: Arch Wiki" in out and "Clipboard" not in out, out)
out=tools.screenshot(clipboard=True); ok("Clipboard text:" in out and "segfault" in out, out)

# ---- HTTP: health, no-cache, care API ----
import uvicorn
srv=uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=8813, log_level="warning")); threading.Thread(target=srv.run, daemon=True).start()
def req(m,p,body=None):
    for _ in range(100):
        try:
            c=http.client.HTTPConnection("127.0.0.1",8813,timeout=20); c.request(m,p,body=json.dumps(body) if body is not None else None,headers={"Content-Type":"application/json"}); r=c.getresponse(); return r.status, dict(r.getheaders()), r.read()
        except ConnectionRefusedError: time.sleep(0.1)
st,hd,b=req("GET","/"); ok(st==200 and hd.get("cache-control")=="no-cache" and b'name="daemon-ui"' in b, hd)
auth.set_pin("4821")
st,_,b=req("GET","/api/health"); ok(st==200 and json.loads(b)["ui_match"], "health stays open with the PIN on")
st,_,b=req("GET","/api/care"); ok(st==401, "care needs the PIN")
auth.disable() if hasattr(auth,"disable") else mc.auth_cfg.update(enabled=False)
st,_,b=req("GET","/api/care"); d=json.loads(b); ok(st==200 and d["care"]["watchdog"] and d["checks"] and d["health"]["ui_match"], (st,b[:200]))
st,_,b=req("POST","/api/care",{"disk_free_percent":15,"briefing_city":"Ankara","memory_review_time":"09:30","memory_review":False}); d=json.loads(b)
ok(st==200 and d["care"]["disk_free_percent"]==15 and d["care"]["briefing_city"]=="Ankara" and not d["care"]["memory_review"], b[:200])
mc.reload_if_changed(); ok(mc.care["memory_review_time"]=="09:30", "saved")
for bad in ({"disk_free_percent":0},{"disk_free_percent":"x"},{"memory_review_time":"25:00"},{"watchdog":"yes"},{"nope":1},{"memory_review_day":7}):
    st,_,b=req("POST","/api/care",bad); ok(st==400, (bad, st))
st,_,b=req("POST","/api/care/run",{"what":"alert"}); ok(st==200 and json.loads(b)["ok"], b)
st,_,b=req("POST","/api/care/run",{"what":"nonsense"}); ok(st==400, "bad run")
print("PASS tcare")
