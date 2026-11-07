import os, sys, json, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path[:0]=["stubs","."]
os.environ.update(DAEMON_CONFIG="cfg23.yaml", DAEMON_CHATS="chats23", DAEMON_MEMORY="m23.json", DAEMON_REMINDERS="r23.json", DAEMON_CALENDAR="c23.json", DAEMON_TTS_USAGE="u23.json")
for f in ("cfg23.yaml","u23.json"):
    if os.path.exists(f): os.remove(f)
import numpy as np
MODE=["ok"]; HITS=[0]
class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def do_GET(self): self.send_response(404); self.end_headers()
    def do_POST(self):
        self.rfile.read(int(self.headers.get("content-length",0))); HITS[0]+=1
        m=MODE[0]
        def j(c,o): b=json.dumps(o).encode(); self.send_response(c); self.send_header("content-type","application/json"); self.end_headers(); self.wfile.write(b)
        if m=="500once" and HITS[0]==1: return j(500,{"detail":"boom"})
        if m=="500": return j(503,{"detail":"overloaded"})
        if m=="text": return j(400,{"detail":{"status":"invalid_text","message":"text is empty after cleaning"}})
        if m=="model": return j(400,{"detail":{"status":"bad","message":"model_id is not valid"}})
        if m=="conc": return j(429,{"detail":{"status":"too_many_concurrent_requests","message":"too many concurrent requests"}})
        self.send_response(200); self.send_header("content-type","audio/pcm"); self.end_headers(); self.wfile.write((np.sin(np.arange(24000)*0.05)*8000).astype("<i2").tobytes())
srv=HTTPServer(("127.0.0.1",8798),H); threading.Thread(target=srv.serve_forever,daemon=True).start()
import model_config as mc, elevenlabs_tts as el
el.BASE="http://127.0.0.1:8798"; mc.elevenlabs.update(enabled=True, api_key="k", voice_id="v")
def ok(c,m):
    if not c: print("FAIL",m); sys.exit(1)
MODE[0]="500once"; HITS[0]=0; ok(el.speak("hello there")  is not None and HITS[0]==2, ("retry",HITS)); ok(el.status()["active"], "still active")
MODE[0]="text"; HITS[0]=0; ok(el.speak("hello") is None and HITS[0]==1, "text refused once"); ok(el.status()["active"], "text error does not pause the voice")
MODE[0]="ok"; ok(el.speak("hello") is not None, "next sentence fine")
MODE[0]="500"; HITS[0]=0; ok(el.speak("hello") is None and HITS[0]==2, "retried then down"); st=el.status(); ok(not st["active"] and "503" in st["why"] and "overloaded" in st["why"], st)
el.reset() if hasattr(el,"reset") else None
with el._lock: el._s.update(down_until=0.0, kind="", reason="")
MODE[0]="model"; ok(el.speak("hello") is None and "model" in el.status()["why"], el.status())
with el._lock: el._s.update(down_until=0.0, kind="", reason="")
MODE[0]="conc"; ok(el.speak("hello") is None and "simultaneous" in el.status()["why"], el.status())
print("EL2 OK")
