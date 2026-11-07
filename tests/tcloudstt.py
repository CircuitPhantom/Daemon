import types, os, sys, threading, json, time
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path[:0]=["stubs","."]
os.environ.update(DAEMON_CONFIG="cfg19.yaml", DAEMON_CHATS="chats19", DAEMON_MEMORY="mem19.json", DAEMON_REMINDERS="rem19.json", DAEMON_CALENDAR="cal19.json")
for f in ("cfg19.yaml","mem19.json","rem19.json","cal19.json"):
    if os.path.exists(f): os.remove(f)
def ok(c,m=""):
    if not c: print("FAIL",m); sys.exit(1)
import numpy as np
import model_config as mc, cloud_stt, server
seen=[]; mode=["ok"]
class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def do_POST(self):
        body=self.rfile.read(int(self.headers["Content-Length"])); seen.append((self.path,self.headers.get("Authorization"),body))
        if mode[0]=="401": self.send_response(401); self.end_headers(); return
        if mode[0]=="429": self.send_response(429); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Type","application/json"); self.end_headers(); self.wfile.write(json.dumps({"text":" hello from cloud"}).encode())
srv=HTTPServer(("127.0.0.1",8794),H); threading.Thread(target=srv.serve_forever,daemon=True).start()
local=[]
server.voice.stt.transcribe=lambda audio,**k:(local.append(k) or iter([types.SimpleNamespace(text=" local text")]),None)
aud=np.zeros(16000,dtype=np.float32)
ok(server.voice.transcribe(aud)=="local text", "disabled -> local")
mc.stt_cloud.update(enabled=True, base_url="http://127.0.0.1:8794/openai/v1", api_key="gsk_x", model="whisper-large-v3-turbo", language="tr")
cloud_stt.reset()
ok(server.voice.transcribe(aud,prompt="Daemon.")=="hello from cloud", "cloud used")
p,auth,body=seen[-1]
ok(p=="/openai/v1/audio/transcriptions" and auth=="Bearer gsk_x", (p,auth))
ok(b'name="model"\r\n\r\nwhisper-large-v3-turbo' in body and b'name="language"\r\n\r\ntr' in body and b'name="prompt"\r\n\r\nDaemon.' in body and b"RIFF" in body and b'filename="speech.wav"' in body, body[:300])
ok(server.voice.transcribe(aud,lang="en")=="hello from cloud" and b'name="language"\r\n\r\nen' in seen[-1][2], "lang override")
mode[0]="429"; cloud_stt.reset(); n=len(seen)
ok(server.voice.transcribe(aud)=="local text", "429 -> local")
ok(server.voice.transcribe(aud)=="local text" and len(seen)==n+1, "cooldown: cloud not called again")
ok(not cloud_stt.usable() and "rate limit" in cloud_stt.status()["why"], cloud_stt.status())
mode[0]="401"; cloud_stt.reset()
ok(server.voice.transcribe(aud)=="local text" and cloud_stt._s["down_until"]-time.time()>500, "bad key waits long")
mode[0]="ok"; cloud_stt.reset(); ok(server.voice.transcribe(aud)=="hello from cloud", "recovers")
mc.stt_cloud["base_url"]="http://127.0.0.1:1/x"; cloud_stt.reset()
ok(server.voice.transcribe(aud)=="local text", "network error -> local")
# config round trip
mc.save(); txt=open("cfg19.yaml").read(); ok("stt_cloud:" in txt and "gsk_x" in txt and oct(os.stat("cfg19.yaml").st_mode)[-3:]=="600", "saved private")
mc.load(); ok(mc.stt_cloud["language"]=="tr" and mc.stt_cloud["timeout"]==20, "reload")
# warm-up does not crash
server.voice.warm_up_whisper()
print("CLOUD STT OK")
