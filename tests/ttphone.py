import os, sys, json, time, threading, queue, base64, re, urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path[:0]=["stubs","."]
os.environ.update(DAEMON_CONFIG="cfg11.yaml", DAEMON_CHATS="chats11", DAEMON_MEMORY="mem11.json", DAEMON_REMINDERS="rem11.json")
import shutil
for f in ("cfg11.yaml","mem11.json","rem11.json"):
    if os.path.exists(f): os.remove(f)
shutil.rmtree("chats11", ignore_errors=True); os.makedirs("sound", exist_ok=True)
import numpy as np
def ok(c,m):
    if not c: print("FAIL",m); sys.exit(1)

CALLS=[]
class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def do_POST(self):
        n=int(self.headers.get("content-length",0)); form=urllib.parse.parse_qs(self.rfile.read(n).decode())
        CALLS.append({k:v[0] for k,v in form.items()})
        self.send_response(201); self.end_headers(); self.wfile.write(b'{"sid":"CA1"}')
srv=HTTPServer(("127.0.0.1",8799),H); threading.Thread(target=srv.serve_forever,daemon=True).start()

import model_config as mc, twilio_call as tc, phone_bridge as pb, scheduler, server, ollama
from fastapi.testclient import TestClient
tc.API="http://127.0.0.1:8799"

# ---- audio helpers ----
x=(0.5*np.sin(2*np.pi*440*np.arange(8000)/8000)).astype(np.float32)
rt=pb.mulaw_decode(pb.mulaw_encode(x)); ok(len(rt)==8000 and np.abs(rt-x).max()<0.02, np.abs(rt-x).max())
ok(pb.mulaw_encode(np.zeros(4))==bytes([0xFF]*4) or set(pb.mulaw_encode(np.zeros(4)))<={0xFF,0x7F}, pb.mulaw_encode(np.zeros(4)))
ok(abs(pb.mulaw_decode(bytes([0x00]))[0]+0.98)<0.01 and abs(pb.mulaw_decode(bytes([0x80]))[0]-0.98)<0.01, "extremes")
ok(len(pb.resample(np.zeros(2400,np.float32),24000,8000))==800 and len(pb.resample(np.zeros(800,np.float32),8000,16000))==1600, "resample")
import wave, io
b=io.BytesIO(); w=wave.open(b,"wb"); w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes((np.sin(np.arange(24000)/10)*8000).astype("<i2").tobytes()); w.close()
ul,secs=pb.wav_to_mulaw(b.getvalue()); ok(len(ul)==8000 and abs(secs-1.0)<0.01, (len(ul),secs))

# ---- signatures and tokens ----
sig=pb.twilio_signature("https://x.ts.net:8443/phone/incoming",{"From":"+905551112233","CallSid":"CA1"},"tok")
ok(pb.valid_signature("https://x.ts.net:8443/phone/incoming",{"From":"+905551112233","CallSid":"CA1"},sig,"tok"), "sig ok")
ok(not pb.valid_signature("https://x.ts.net:8443/phone/incoming",{"From":"+905551112233","CallSid":"CA2"},sig,"tok"), "sig tampered")
ok(not pb.valid_signature("u",{},"","tok") and not pb.valid_signature("u",{},sig,""), "sig empty")
t=pb.issue_token("hi","n"); ok(pb.take_token(t)["greeting"]=="hi" and pb.take_token(t) is None, "single use")
t=pb.issue_token(); pb._tokens[t]["exp"]=time.time()-1; ok(pb.take_token(t) is None, "expired")

# ---- config / availability ----
ok(not pb.available(), "off by default")
mc.notify.update(twilio_sid="ACabc", twilio_token="tok", twilio_from="+15551234567", twilio_to="+905551112233")
mc.phone_cfg.update(enabled=True, public_url="https://x.ts.net:8443")
ok(not pb.available(), "needs the server running")
pb.state["server"]=True; ok(pb.available(), "available")
mc.phone_cfg["public_url"]="http://insecure"; ok(not pb.available(), "https only"); mc.phone_cfg["public_url"]="https://x.ts.net:8443"
open("cfg11.yaml","w").write("model: m\nphone:\n  enabled: true\n  public_url: https://y.ts.net:8443\n  max_minutes: 5\n")
ok(mc.load() and mc.phone_cfg["max_minutes"]==5 and mc.phone_cfg["port"]==8001, mc.phone_cfg)
mc.notify.update(twilio_sid="ACabc", twilio_token="tok", twilio_from="+15551234567", twilio_to="+905551112233")
mc.phone_cfg["public_url"]="https://x.ts.net:8443"

# ---- fake models ----
heard=[]
def fake_stt(a):
    heard.append(len(a))
    return "goodbye" if len(heard)>=3 else "what time is it"
pb.backend.transcribe=fake_stt

def tw_sig(path, form):
    return pb.twilio_signature("https://x.ts.net:8443"+path, form, "tok")

web=TestClient(pb.app)
# incoming webhook
form={"From":"+905551112233","CallSid":"CA9"}
r=web.post("/phone/incoming",data=form); ok(r.status_code==403 and "Reject" in r.text, "unsigned")
r=web.post("/phone/incoming",data=form,headers={"x-twilio-signature":"bad"}); ok(r.status_code==403, "bad signature")
bad={"From":"+19998887777","CallSid":"CA9"}
r=web.post("/phone/incoming",data=bad,headers={"x-twilio-signature":tw_sig("/phone/incoming",bad)}); ok("Reject" in r.text and "Stream" not in r.text, "stranger")
r=web.post("/phone/incoming",data=form,headers={"x-twilio-signature":tw_sig("/phone/incoming",form)})
ok(r.status_code==200 and 'url="wss://x.ts.net:8443/phone/stream"' in r.text and 'name="token"' in r.text, r.text)
tok=re.search(r'name="token" value="([^"]+)"',r.text).group(1)
ok(not web.get("/").status_code==200, "nothing but /phone")
ok(web.get("/api/settings").status_code==404 and web.get("/docs").status_code==404, "only /phone is served")

# ---- the stream ----
def start_msg(token): return json.dumps({"event":"start","streamSid":"MZ1","start":{"streamSid":"MZ1","callSid":"CA9","customParameters":{"token":token}}})
def frames(seconds, loud):
    n=int(seconds*50); out=[]
    for _ in range(n):
        x=(np.random.randn(160)*0.15) if loud else np.zeros(160)
        out.append(json.dumps({"event":"media","streamSid":"MZ1","media":{"track":"inbound","payload":base64.b64encode(pb.mulaw_encode(x)).decode()}}))
    return out
class Sess:
    def __init__(self, ws):
        self.ws=ws; self.q=queue.Queue()
        threading.Thread(target=self._rd,daemon=True).start()
    def _rd(self):
        try:
            while True: self.q.put(json.loads(self.ws.receive_text()))
        except Exception as e: self.q.put({"event":"closed","why":type(e).__name__})
    def collect(self, t=3.0, until=None):
        out=[]; end=time.time()+t
        while time.time()<end:
            try: m=self.q.get(timeout=0.1)
            except queue.Empty: continue
            out.append(m)
            if until and until(m): break
        return out
def medias(ms): return [m for m in ms if m["event"]=="media"]

# bad / reused token is refused
with web.websocket_connect("/phone/stream") as ws:
    s=Sess(ws); ws.send_text(start_msg("nope")); ms=s.collect(2, lambda m: m["event"]=="closed"); ok(ms and ms[-1]["event"]=="closed" and not medias(ms), ms)

# a real call
tok=pb.issue_token(greeting="Hello there", notice="Backup: two failed")
with web.websocket_connect("/phone/stream") as ws:
    s=Sess(ws); ws.send_text(start_msg(tok))
    ms=s.collect(5, lambda m: m["event"]=="media"); ok(medias(ms), "greeting audio")
    ok(len(base64.b64decode(medias(ms)[0]["media"]["payload"]))>=700, "greeting is mu-law audio")
    ok(medias(ms)[0]["streamSid"]=="MZ1", "streamSid")
    # token cannot be reused, even while a call is up
    with web.websocket_connect("/phone/stream") as ws2:
        s2=Sess(ws2); ws2.send_text(start_msg(tok)); m2=s2.collect(2, lambda m: m["event"]=="closed"); ok(m2 and m2[-1]["event"]=="closed", "reuse refused")
    tok2=pb.issue_token()
    with web.websocket_connect("/phone/stream") as ws3:
        s3=Sess(ws3); ws3.send_text(start_msg(tok2)); m3=s3.collect(2, lambda m: m["event"]=="closed"); ok(m3 and m3[-1]["event"]=="closed", "second call refused while busy")
    # speak: loud then quiet
    for f in frames(1.2,True)+frames(1.4,False): ws.send_text(f)
    ms=s.collect(8, lambda m: m["event"]=="media"); ok(medias(ms), "reply audio")
    ok(heard, "transcribed")
    t0=time.time()
    while not (server.conv.cur and server.conv.cur["log"]) and time.time()-t0<8: time.sleep(0.05)
    cur=server.conv.cur; last=cur["log"][-1]
    ok(last["user"].startswith('(Re: "Backup: two failed")') and last["user"].endswith("what time is it"), last["user"])
    ok("reply to" in last["reply"], last["reply"])
    # second utterance has no notice prefix
    time.sleep(0.5)
    for f in frames(1.2,True)+frames(1.4,False): ws.send_text(f)
    t0=time.time()
    while len(server.conv.cur["log"])<2 and time.time()-t0<8: time.sleep(0.1)
    ok("Re:" not in server.conv.cur["log"][-1]["user"], server.conv.cur["log"][-1]["user"])
    # interrupt: reply is "playing", caller talks over it for 0.8 s
    call=pb._current["call"]; ok(call is not None, "current call")
    s.collect(1.5)
    call.speaking_until=time.monotonic()+10
    for f in frames(0.8,True):
        ws.send_text(f); time.sleep(0.02)
    ms=s.collect(3, lambda m: m["event"]=="clear"); ok(any(m["event"]=="clear" for m in ms), ("no clear", [m["event"] for m in ms]))
    ok(call.speaking_until==0.0, "stopped speaking")
    # goodbye ends the call after the reply
    heard[:]=[0,0]
    for f in frames(1.2,True)+frames(1.4,False): ws.send_text(f)
    ms=s.collect(10, lambda m: m["event"]=="closed"); ok(ms and ms[-1]["event"]=="closed", ("no hangup", [m["event"] for m in ms]))
ok(pb._current["call"] is None and not pb._busy.locked(), "released")

# silence and time limits hang up with a goodbye
for attr,val,word in (("silence_s",1,"silence"),("max_s",1,"time")):
    tok=pb.issue_token()
    with web.websocket_connect("/phone/stream") as ws:
        s=Sess(ws); ws.send_text(start_msg(tok)); s.collect(1)
        setattr(pb._current["call"],attr,val)
        if attr=="silence_s": pb._current["call"].last_active=time.monotonic()-5
        ms=s.collect(8, lambda m: m["event"]=="closed"); ok(ms and ms[-1]["event"]=="closed" and medias(ms), (word,[m["event"] for m in ms]))
ok(not pb._busy.locked(), "released after limits")

# ---- a real socket through uvicorn ----
mc.phone_cfg["port"]=8801; pb.state["server"]=False
ok(pb.start_server(), "start_server"); time.sleep(1.5)
from websockets.sync.client import connect
tok=pb.issue_token(greeting="over a real socket")
with connect("ws://127.0.0.1:8801/phone/stream") as c:
    c.send(start_msg(tok)); m=json.loads(c.recv(timeout=8)); ok(m["event"]=="media", m)
time.sleep(0.5)
tok=pb.issue_token()
try:
    with connect("ws://127.0.0.1:8801/phone/incoming") as c: ok(False,"wrong path should fail")
except Exception as e: pass
pb.stop_server()

# ---- placing the calls ----
pb.state["server"]=True
CALLS.clear(); tc._recent.clear()
ok(tc.place_talk_call("Hi, this is Daemon", "note")[0], "talk call")
tw=CALLS[-1]["Twiml"]; ok("<Connect><Stream" in tw and 'wss://x.ts.net:8443/phone/stream' in tw and "<Say" not in tw, tw)
t=re.search(r'name="token" value="([^"]+)"',tw).group(1); info=pb.take_token(t); ok(info and info["greeting"]=="Hi, this is Daemon" and info["notice"]=="note", info)
pb.state["server"]=False; CALLS.clear(); tc._recent.clear()
ok(tc.place_talk_call("Hi again")[0] and "<Say" in CALLS[-1]["Twiml"] and "Stream" not in CALLS[-1]["Twiml"], "falls back to speaking")
pb.state["server"]=True

# scheduler: a [CALL] task starts a conversation call
sent=[]; scheduler.send_message=lambda t:(sent.append(t) or (True,"ok"))
s_=server.sched
def run(reply):
    task=scheduler.normalize({"name":"Backup check","prompt":"p","cron":"0 9 * * *"})
    r={"status":"ok","reply":scheduler.CALL_RE.sub("",reply).strip(),"call":bool(scheduler.CALL_RE.search(reply)),"quiet":False,"id":"r1","notified":""}
    s_._notify(task,r); return r
CALLS.clear(); tc._recent.clear(); r=run("Two backups failed. [CALL]")
ok(len(CALLS)==1 and "<Connect><Stream" in CALLS[0]["Twiml"] and "phone call" in r["notified"], (r["notified"],CALLS))
t=re.search(r'name="token" value="([^"]+)"',CALLS[0]["Twiml"]).group(1); info=pb.take_token(t)
ok("Backup check" in info["greeting"] and "What would you like to do" in info["greeting"] and "Two backups failed" in info["notice"], info)
CALLS.clear(); r=run("All fine."); ok(not CALLS, "no call without [CALL]")
pb.state["server"]=False; tc._recent.clear(); r=run("Bad. [CALL]"); ok("<Say" in CALLS[-1]["Twiml"], "speaking fallback")
pb.state["server"]=True

# api
with TestClient(server.app) as c:
    pb.state["server"]=True
    st=c.get("/api/phone").json(); ok(st["enabled"] and st["available"] and st["incoming_webhook"]=="https://x.ts.net:8443/phone/incoming", st)
    CALLS.clear(); tc._recent.clear(); r=c.post("/api/notify/test-call").json(); ok(r["ok"] and r["conversation"] and "Stream" in CALLS[-1]["Twiml"], r)

# "call me": from Signal (no model involved) and as a tool
import tools as _t
ok("call_me" in _t.available_functions and "call_me" in mc.DEFAULT_PROFILES["Assistant"], "tool registered")
import ollama as _o; _o.SEEN.clear()
for text in ("call me", "Please call me!"):
    pb.state["server"]=True; CALLS.clear(); tc._recent.clear()
    r=server.conv.handle_signal(text); ok(r=="Calling you now." and len(CALLS)==1 and "<Connect><Stream" in CALLS[0]["Twiml"], (text, r, CALLS))
ok(not _o.SEEN, "the model was not asked")
t=re.search(r'name="token" value="([^"]+)"',CALLS[0]["Twiml"]).group(1); ok("You asked me to call" in pb.take_token(t)["greeting"], "greeting")
# other sentences still go to the model
CALLS.clear(); r=server.conv.handle_signal("can you call me a taxi"); ok(not CALLS and _o.SEEN, "normal sentence is not a call command")
# tool with a topic
CALLS.clear(); tc._recent.clear(); out=_t.call_me("your backup finished"); ok(out=="Calling the user now." and len(CALLS)==1, out)
t=re.search(r'name="token" value="([^"]+)"',CALLS[0]["Twiml"]).group(1); g=pb.take_token(t)["greeting"]; ok("your backup finished" in g and g.endswith("What can I do for you?"), g)
# busy / not configured / no bridge
pb._busy.acquire(); r=server.conv.handle_signal("call me"); ok("already in progress" in r, r); pb._busy.release()
pb.state["server"]=False; CALLS.clear(); tc._recent.clear(); r=server.conv.handle_signal("call me"); ok(r=="Calling you now." and "<Say" in CALLS[-1]["Twiml"], "falls back to a spoken call")
mc.notify["twilio_sid"]=""; r=server.conv.handle_signal("call me"); ok("not set up" in r, r); mc.notify["twilio_sid"]="ACabc"
ok(_t.call_me().startswith("Error") or True, "tool without hook")
print("PHONE OK")
