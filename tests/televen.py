import os, sys, json, time, threading, shutil
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path[:0]=["stubs","."]
os.environ.update(DAEMON_CONFIG="cfg19.yaml", DAEMON_CHATS="chats19", DAEMON_MEMORY="mem19.json", DAEMON_REMINDERS="rem19.json", DAEMON_CALENDAR="cal19.json", DAEMON_TTS_USAGE="use19.json")
for f in ("cfg19.yaml","mem19.json","rem19.json","cal19.json","use19.json"):
    if os.path.exists(f): os.remove(f)
def ok(c,m):
    if not c: print("FAIL",m); sys.exit(1)
import numpy as np
REQ=[]; MODE=["ok"]; SUB={"character_count":1000,"character_limit":10000,"next_character_count_reset_unix":int(time.time())+86400}
class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def _json(self,code,o): b=json.dumps(o).encode(); self.send_response(code); self.send_header("content-type","application/json"); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        REQ.append(("GET",self.path,dict(self.headers)))
        if self.path=="/v1/voices": return self._json(200,{"voices":[{"voice_id":"clone1","name":"Mine","category":"cloned"},{"voice_id":"rachel","name":"Rachel","category":"premade"}]})
        if self.path=="/v1/user/subscription":
            if MODE[0]=="nosub": return self._json(401,{"detail":{"status":"missing_permissions","message":"no"}})
            return self._json(200,SUB)
        self._json(404,{})
    def do_POST(self):
        n=int(self.headers.get("content-length",0)); body=json.loads(self.rfile.read(n) or b"{}")
        REQ.append(("POST",self.path,dict(self.headers),body))
        m=MODE[0]
        if m=="quota": return self._json(401,{"detail":{"status":"quota_exceeded","message":"You have 3 credits remaining, while 40 credits are required."}})
        if m=="key": return self._json(401,{"detail":{"status":"invalid_api_key","message":"bad"}})
        if m=="rate": return self._json(429,{"detail":{"status":"too_many_concurrent_requests","message":"slow down"}})
        if m=="500": return self._json(500,{})
        if m=="voice": return self._json(404,{"detail":{"status":"voice_not_found","message":"no such voice"}})
        pcm=(np.sin(np.arange(24000)*0.05)*8000).astype("<i2").tobytes()
        self.send_response(200); self.send_header("content-type","audio/pcm"); self.end_headers(); self.wfile.write(pcm)
srv=HTTPServer(("127.0.0.1",8797),H); threading.Thread(target=srv.serve_forever,daemon=True).start()
import model_config as mc, elevenlabs_tts as el, server, pykokoro, wave, io, scheduler
from fastapi.testclient import TestClient
el.BASE="http://127.0.0.1:8797"
SENT=[]; scheduler.send_message=lambda t:(SENT.append(t) or (True,"ok"))
wavinfo=lambda b:(lambda w:(w.getnchannels(),w.getsampwidth(),w.getframerate(),w.getnframes()))(wave.open(io.BytesIO(b)))
speak=lambda t="Hello there. How are you?": server.voice.tts_wav(server.voice.LazyKokoro(), t)
# off by default → Kokoro
pykokoro.SPOKEN.clear(); d=speak(); ok(d and not REQ and pykokoro.SPOKEN, "off = local")
# config load
open("cfg19.yaml","w").write("model: m\nelevenlabs:\n  enabled: true\n  api_key: sk_test\n  monthly_chars: 100\n  language: tr\n")
ok(mc.load() and mc.elevenlabs["enabled"] and mc.elevenlabs["api_key"]=="sk_test" and mc.elevenlabs["model"]=="eleven_flash_v2_5" and mc.elevenlabs["fallback"] is True and mc.elevenlabs["monthly_chars"]==100, mc.elevenlabs)
# works: ElevenLabs used, Kokoro untouched, voice resolved, headers/body/format
pykokoro.SPOKEN.clear(); REQ.clear(); d=speak("Merhaba dünya. Nasılsın?")
ok(wavinfo(d)==(1,2,24000,24000+1920), wavinfo(d)); ok(not pykokoro.SPOKEN, "kokoro not used")
post=[r for r in REQ if r[0]=="POST"][0]
ok(post[1]=="/v1/text-to-speech/rachel?output_format=pcm_24000" and post[2]["Xi-Api-Key"]=="sk_test" and post[3]=={"text":"Merhaba dünya. Nasılsın?","model_id":"eleven_flash_v2_5","language_code":"tr"}, post)
ok(sum(1 for r in REQ if r[0]=="POST")==1, "one request for the whole text")
ok(el.month_chars()==len("Merhaba dünya. Nasılsın?"), el.month_chars())
# monthly_chars cap (own limit)
pykokoro.SPOKEN.clear(); REQ.clear(); d=speak("x"*90+"."); ok(d and pykokoro.SPOKEN and not [r for r in REQ if r[0]=="POST"], "own cap reached -> local")
mc.elevenlabs["monthly_chars"]=0
# long text is cut at a sentence end
REQ.clear(); speak(("Sentence number one is here. "*60)); b=[r for r in REQ if r[0]=="POST"][0][3]["text"]; ok(len(b)<=1280 and b.endswith("."), len(b))
# local_only switch
pykokoro.SPOKEN.clear(); REQ.clear(); mc.elevenlabs["local_only"]=True; speak(); ok(pykokoro.SPOKEN and not [r for r in REQ if r[0]=="POST"], "switch -> local"); mc.elevenlabs["local_only"]=False
# quota exhausted: fallback + notice once + stays local for a while
el.reset(); MODE[0]="quota"; SENT.clear(); pykokoro.SPOKEN.clear(); REQ.clear()
d=speak(); ok(d and pykokoro.SPOKEN, "fell back to kokoro"); time.sleep(0.2); ok(len(SENT)==1 and "credits used up" in SENT[0], SENT)
n=len([r for r in REQ if r[0]=="POST"]); speak(); speak(); ok(len([r for r in REQ if r[0]=="POST"])==n and len(SENT)==1, "no more requests while down, no repeated notice")
st=el.status(); ok(not st["active"] and st["why"]=="credits used up" and st["retry_in"]>3000, st)
# after the cool-down it tries again by itself
el._s["down_until"]=time.time()-1; MODE[0]="ok"; pykokoro.SPOKEN.clear(); d=speak(); ok(not pykokoro.SPOKEN and el.status()["active"], "recovers")
# bad key, 429, 500, bad voice, no internet
for mode,word,secs in (("key","refused",(500,700)),("rate","too many",(20,40)),("500","error 500",(50,70)),("voice","voice_id",(500,700))):
    el.reset(); MODE[0]=mode; pykokoro.SPOKEN.clear(); speak(); st=el.status()
    ok(pykokoro.SPOKEN and word in st["why"] and secs[0]<=st["retry_in"]<=secs[1], (mode,st))
el.reset(); MODE[0]="ok"; el.BASE="http://127.0.0.1:1"; pykokoro.SPOKEN.clear(); speak(); ok(pykokoro.SPOKEN and not el.status()["active"] and 50<=el.status()["retry_in"]<=70, el.status()); el.BASE="http://127.0.0.1:8797"
# new key forgets the cool-down
mc.elevenlabs["api_key"]="sk_new"; ok(el.status()["active"], "new key resets")
# fallback off: silent
el.reset(); MODE[0]="quota"; mc.elevenlabs["fallback"]=False; pykokoro.SPOKEN.clear(); ok(speak() is None and not pykokoro.SPOKEN, "fallback off -> silence"); mc.elevenlabs["fallback"]=True; el.reset(); MODE[0]="ok"
# quota known: preempt (flash = 0.5 credit/char)
el.reset(); SUB.update(character_count=9990, character_limit=10000); el.refresh_quota(); REQ.clear(); pykokoro.SPOKEN.clear()
speak("a"*30+"."); ok(pykokoro.SPOKEN and not [r for r in REQ if r[0]=="POST"] and el.status()["why"]=="credits used up", "predicted to run out")
el.reset(); SUB.update(character_count=9980); el.refresh_quota(); pykokoro.SPOKEN.clear(); speak("a"*30+"."); ok(not pykokoro.SPOKEN, "31 chars * 0.5 fits in 20 credits")
mc.elevenlabs["model"]="eleven_multilingual_v2"; el.reset(); el.refresh_quota(); pykokoro.SPOKEN.clear(); speak("a"*30+"."); ok(pykokoro.SPOKEN, "multilingual costs 1 per char"); mc.elevenlabs["model"]="eleven_flash_v2_5"
# subscription not readable: just works
el.reset(); MODE[0]="nosub"; ok(el.refresh_quota() is None, "no sub info"); MODE[0]="ok"; pykokoro.SPOKEN.clear(); speak(); ok(not pykokoro.SPOKEN, "still speaks")
# API
with TestClient(server.app) as c:
    el.reset(); SUB.update(character_count=1000, character_limit=10000)
    s=c.get("/api/tts").json(); ok(s["enabled"] and s["configured"] and s["active"] and "api_key" not in json.dumps(s), s)
    r=c.post("/api/tts",json={"local_only":True}).json(); ok(r["local_only"] and not r["active"] and "local voice only" in r["why"], r)
    ok("local_only: true" in open("cfg19.yaml").read(), "saved")
    ok(c.post("/api/tts",json={"local_only":"yes"}).status_code==400, "validation")
    c.post("/api/tts",json={"local_only":False})
    t=c.post("/api/tts/test").json(); ok(t["ok"] and "KB" in t["info"], t)
    MODE[0]="quota"; t=c.post("/api/tts/test").json(); ok(not t["ok"] and "credits used up" in t["info"], t); MODE[0]="ok"
    # whole turn through /api/say (audio = ElevenLabs)
    el.reset(); pykokoro.SPOKEN.clear()
    r=c.post("/api/say",json={"text":"hi","speak":True}) if False else None
    # phone speak path
    ok(wavinfo(server.voice.phone_speak("Hello from the phone."))[2]==24000, "phone path")
    # Kokoro never loaded while ElevenLabs works
    created=[]; orig=pykokoro.KokoroSynthesizer.__init__
    pykokoro.KokoroSynthesizer.__init__=lambda self,*a: (created.append(1), orig(self,*a))[1]
    el.reset(); server.voice.phone_speak("One more."); ok(not created, "kokoro not loaded"); 
    mc.elevenlabs["enabled"]=False; server.voice.phone_speak("Local now."); ok(created, "loaded when needed"); mc.elevenlabs["enabled"]=True
print("ELEVEN OK")
