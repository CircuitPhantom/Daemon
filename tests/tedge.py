import os, sys, types, subprocess, io, wave, asyncio
sys.path[:0]=["stubs","."]
os.environ.update(DAEMON_CONFIG="cfg20.yaml", DAEMON_CHATS="chats20", DAEMON_MEMORY="mem20.json", DAEMON_REMINDERS="rem20.json", DAEMON_CALENDAR="cal20.json", DAEMON_TTS_USAGE="use20.json")
for f in ("cfg20.yaml","mem20.json","rem20.json","cal20.json","use20.json"):
    if os.path.exists(f): os.remove(f)
def ok(c,m):
    if not c: print("FAIL",m); sys.exit(1)
mp3=subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i","sine=frequency=440:duration=1","-ar","24000","-ac","1","-f","mp3","pipe:1"],capture_output=True).stdout
ok(len(mp3)>500,"mp3 made")
MODE=["ok"]; CALLS=[]
class Comm:
    def __init__(s,text,voice,rate="+0%",pitch="+0Hz"): CALLS.append((text,voice,rate,pitch))
    async def stream(s):
        if MODE[0]=="err": raise RuntimeError("403 handshake")
        if MODE[0]=="net": raise OSError("no route")
        if MODE[0]=="empty": yield {"type":"WordBoundary"}; return
        yield {"type":"audio","data":mp3[:len(mp3)//2]}; yield {"type":"WordBoundary"}; yield {"type":"audio","data":mp3[len(mp3)//2:]}
fake=types.ModuleType("edge_tts"); fake.Communicate=Comm; sys.modules["edge_tts"]=fake
import model_config as mc, edge_voice as ev, server, pykokoro, scheduler
wavinfo=lambda b:(lambda w:(w.getnchannels(),w.getsampwidth(),w.getframerate(),w.getnframes()))(wave.open(io.BytesIO(b)))
speak=lambda t="Hello there. How are you?": server.voice.tts_wav(server.voice.LazyKokoro(), t)
pykokoro.SPOKEN.clear(); d=speak(); ok(d and not CALLS and pykokoro.SPOKEN,"off = kokoro")
mc.edge_tts.update(enabled=True)
pykokoro.SPOKEN.clear(); d=speak(); ok(d and CALLS and not pykokoro.SPOKEN,"edge used")
c,sw,r,n=wavinfo(d); ok((c,sw,r)==(1,2,24000) and 24000<n<30000,("wav",c,sw,r,n))
ok(CALLS[0][1]=="en-US-AriaNeural","voice")
st=ev.status(); ok(st["active"] and st["configured"],st)
# error -> cooldown + kokoro
MODE[0]="err"; pykokoro.SPOKEN.clear(); d=speak(); ok(d and pykokoro.SPOKEN,"fallback kokoro")
ok(not ev.status()["active"] and "RuntimeError" in ev.status()["why"],ev.status())
n0=len(CALLS); MODE[0]="ok"; speak(); ok(len(CALLS)==n0,"cooldown skips edge")
ev.reset(); pykokoro.SPOKEN.clear(); speak(); ok(not pykokoro.SPOKEN,"works again after reset")
MODE[0]="net"; ev.reset(); speak(); ok("no connection" in ev.status()["why"],ev.status())
MODE[0]="empty"; ev.reset(); speak(); ok(not ev.status()["active"],"empty = down")
# fallback off -> silent
MODE[0]="err"; ev.reset(); mc.edge_tts["fallback"]=False; ok(speak() is None,"silent"); mc.edge_tts["fallback"]=True
# local only
MODE[0]="ok"; ev.reset(); mc.elevenlabs["local_only"]=True; n0=len(CALLS); speak(); ok(len(CALLS)==n0,"local only"); mc.elevenlabs["local_only"]=False
# test()
r=ev.test(); ok(r["ok"],r); MODE[0]="err"; r=ev.test(); ok(not r["ok"],r); MODE[0]="ok"
# ffmpeg fallback decoder when miniaudio missing
sys.modules["miniaudio"]=None; ev.reset(); d=speak(); ok(d and ev.status()["active"],"ffmpeg decode")
# endpoints
from fastapi.testclient import TestClient
cl=TestClient(server.app); j=cl.get("/api/tts").json(); ok("edge" in j and "gemini" not in j,j)
ok(cl.post("/api/tts/test?engine=edge").json()["ok"],"endpoint test")
# running inside an event loop
async def inloop(): return speak()
ok(asyncio.run(inloop()),"inside loop")
print("EDGE OK")
# dashboard controls
mc.elevenlabs["local_only"]=False; mc.edge_tts.update(enabled=False,primary=False)
r=cl.post("/api/tts",json={"edge_first":True}).json(); ok(r["edge"]["primary"] and r["edge"]["enabled"],r)
mc.elevenlabs.update(enabled=True,api_key="k"); ORDER=[]
import elevenlabs_tts as el
el.speak=lambda t:(ORDER.append("el"),None)[1]
oe=ev.speak; ev.speak=lambda t:(ORDER.append("edge"),None)[1]
speak(); ok(ORDER[:2]==["edge","el"],ORDER)
cl.post("/api/tts",json={"edge_first":False}); ORDER.clear(); speak(); ok(ORDER[:2]==["el","edge"],ORDER); ev.speak=oe
r=cl.post("/api/tts",json={"edge_voice":"en-GB-SoniaNeural"}).json(); ok(r["edge"]["voice"]=="en-GB-SoniaNeural" and r["edge"]["voices"],r)
ok(cl.post("/api/tts",json={"edge_voice":"x; rm"}).status_code==400,"bad voice")
ok(cl.post("/api/tts",json={}).status_code==400,"empty")
mc.reload_if_changed(); import yaml; ok(yaml.safe_load(open("cfg20.yaml"))["edge_tts"]["voice"]=="en-GB-SoniaNeural","saved")
mc.edge_tts["fallback"]=False; mc.save(); mc.load() if hasattr(mc,"load") else None
print("DASH OK")
