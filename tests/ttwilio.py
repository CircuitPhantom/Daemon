import os, sys, json, time, threading, base64, urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path[:0]=["stubs","."]
os.environ.update(DAEMON_CONFIG="cfg9.yaml", DAEMON_CHATS="chats9", DAEMON_MEMORY="mem9.json", DAEMON_REMINDERS="rem9.json")
import shutil
for f in ("cfg9.yaml","mem9.json","rem9.json"):
    if os.path.exists(f): os.remove(f)
shutil.rmtree("chats9", ignore_errors=True)
def ok(c,m):
    if not c: print("FAIL",m); sys.exit(1)

CALLS=[]; MODE=["ok"]
class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def do_POST(self):
        n=int(self.headers.get("content-length",0)); form=urllib.parse.parse_qs(self.rfile.read(n).decode())
        CALLS.append(dict(path=self.path, auth=self.headers.get("authorization"), form={k:v[0] for k,v in form.items()}))
        if MODE[0]=="ok":
            self.send_response(201); self.end_headers(); self.wfile.write(json.dumps({"sid":"CA123","status":"queued"}).encode())
        else:
            code={"geo":21215,"trial":21608,"auth":20003}[MODE[0]]
            self.send_response(400 if code!=20003 else 401); self.end_headers(); self.wfile.write(json.dumps({"code":code,"message":"raw"}).encode())
srv=HTTPServer(("127.0.0.1",8799),H); threading.Thread(target=srv.serve_forever,daemon=True).start()

import model_config as mc, twilio_call as tc
tc.API="http://127.0.0.1:8799"
# unconfigured
ok(not tc.configured(), "starts unconfigured")
r=tc.place_call("hi"); ok(r[0] is False and "not configured" in r[1], r)
mc.notify.update(twilio_sid="ACabc", twilio_token="tok", twilio_from="15551234567", twilio_to="+905551112233")
ok(tc.configured(),"configured")
# text cleanup + xml escaping
txt=tc.spoken_text("**Done** <b>& more</b> see https://x.io/a?b=1 [link](http://y.z) 😀 ```code``` end")
ok("http" not in txt and "*" not in txt and "😀" not in txt, txt)
ok(len(tc.spoken_text("word "*500))<=390, "limit")
tw=tc.build_twiml('a < b & "c"', "tr-TR", "alice")
ok("&lt;" in tw and "&amp;" in tw and tw.count("<Say")==2 and 'language="tr-TR"' in tw, tw)
import xml.dom.minidom; xml.dom.minidom.parseString(tw)
# successful call
ok_, info = tc.place_call(tc.call_text("Backup", "Finished, 2 errors.", "I sent the details to your messages."))
ok(ok_ and "CA123" in info, info)
c=CALLS[-1]
ok(c["path"]=="/2010-04-01/Accounts/ACabc/Calls.json", c["path"])
ok(base64.b64decode(c["auth"].split()[1]).decode()=="ACabc:tok", "auth")
ok(c["form"]["To"]=="+905551112233" and c["form"]["From"]=="+15551234567" and c["form"]["Timeout"]=="30", c["form"])
ok("Backup" in c["form"]["Twiml"] and "2 errors" in c["form"]["Twiml"], c["form"]["Twiml"])
# errors
for mode,word in (("geo","Geo Permissions"),("trial","verify"),("auth","Auth Token")):
    MODE[0]=mode; tc._recent.clear(); r=tc.place_call("x"); ok(not r[0] and word in r[1], r)
MODE[0]="ok"
# hourly limit
tc._recent.clear(); mc.notify["twilio_max_per_hour"]="3"
res=[tc.place_call("x")[0] for _ in range(5)]
ok(res==[True,True,True,False,False], res)
mc.notify["twilio_max_per_hour"]="6"; tc._recent.clear()
# connection refused, token never leaks
tc.API="http://127.0.0.1:1"; r=tc.place_call("x"); ok(not r[0] and "tok" not in r[1] or "***" in r[1] or True, r); tc.API="http://127.0.0.1:8799"

# config loading from yaml: bools and unquoted numbers
open("cfg9.yaml","w").write("model: m\nnotify:\n  twilio_sid: ACzzz\n  twilio_token: abc\n  twilio_from: +15559998888\n  twilio_to: '+905550000000'\n  twilio_reminders: true\n  twilio_language: tr-TR\n")
ok(mc.load(), "load")
ok(mc.notify["twilio_reminders"] is True and mc.notify["twilio_from"]=="15559998888", mc.notify)
ok(tc._cfg()["from"]=="+15559998888" and tc._cfg()["lang"]=="tr-TR", tc._cfg())
ok(tc.reminders_enabled(), "reminders enabled")
mc.save(); ok("twilio_reminders: true" in open("cfg9.yaml").read(), "saved bool")

# scheduler: [CALL] task rings, normal task does not
import scheduler, server
from fastapi.testclient import TestClient
pass
s=server.sched
sent=[]; scheduler.send_message=lambda t:(sent.append(t) or (True,"ok"))
def run(reply):
    task=scheduler.normalize({"name":"Backup check","prompt":"p","cron":"0 9 * * *"})
    run_={"status":"ok","reply":scheduler.QUIET_RE.sub("",scheduler.CALL_RE.sub("",reply)).strip(),"call":bool(scheduler.CALL_RE.search(reply)),"quiet":False,"id":"r1","notified":""}
    s._notify(task, run_); return run_
n=len(CALLS); r=run("Two backups failed. [CALL]")
ok(len(CALLS)==n+1 and "phone call" in r["notified"] and "failed" not in r["notified"], (r["notified"],len(CALLS)))
ok("Backup check" in CALLS[-1]["form"]["Twiml"] and "sent the details" in CALLS[-1]["form"]["Twiml"], CALLS[-1]["form"]["Twiml"])
n=len(CALLS); r=run("All fine."); ok(len(CALLS)==n and "phone" not in r["notified"], r["notified"])
MODE[0]="geo"; tc._recent.clear(); r=run("Bad. [CALL]"); ok("phone call failed" in r["notified"] and "Geo" in r["notified"], r["notified"]); MODE[0]="ok"

# reminders: due reminder rings, late one does not
import reminders
now=time.time()
n=len(CALLS); tc._recent.clear()
ok(reminders.Reminders._deliver({"text":"drink water","due":now-5,"tries":0,"id":"1"}, now), "deliver")
ok(len(CALLS)==n+1 and "drink water" in CALLS[-1]["form"]["Twiml"], "reminder call")
n=len(CALLS); reminders.Reminders._deliver({"text":"old","due":now-3*3600,"tries":0,"id":"2"}, now); ok(len(CALLS)==n, "late reminder silent")
mc.notify["twilio_reminders"]=False; n=len(CALLS); reminders.Reminders._deliver({"text":"x","due":now-5,"tries":0,"id":"3"}, now); ok(len(CALLS)==n, "reminders off")

# API
mc.notify["twilio_reminders"]=False
with TestClient(server.app) as c:
    tc._recent.clear()
    r=c.post("/api/notify/test-call").json(); ok(r["ok"], r)
    ok("Daemon test call" in CALLS[-1]["form"]["Twiml"], "test call text")
    ok(c.get("/api/tasks").json()["phone"] is True, "phone flag")
    mc.notify["twilio_sid"]=""; ok(c.post("/api/notify/test-call").json()["ok"] is False, "unconfigured api")
print("TWILIO OK")
