import os, sys, json, time, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path[:0]=["stubs","."]
os.environ.update(DAEMON_CONFIG="cfg21.yaml", DAEMON_CHATS="chats21", DAEMON_MEMORY="mem21.json", DAEMON_REMINDERS="rem21.json", DAEMON_CALENDAR="cal21.json", DAEMON_TTS_USAGE="use21.json")
for f in ("cfg21.yaml","mem21.json","rem21.json","cal21.json"):
    if os.path.exists(f): os.remove(f)
import inspect
def ok(c,m):
    if not c: print("LINE", inspect.stack()[1].lineno)
    if not c: print("FAIL",m); sys.exit(1)
REQ=[]; MODE=["ok"]
def sse(h, chunks):
    h.send_response(200); h.send_header("content-type","text/event-stream"); h.end_headers()
    for c in chunks: h.wfile.write(b"data: "+json.dumps(c).encode()+b"\n\n"); h.wfile.flush()
    h.wfile.write(b"data: [DONE]\n\n")
D=lambda **k:{"choices":[{"delta":k}]}
class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def _err(self,code,body,hdr=None):
        b=json.dumps(body).encode(); self.send_response(code); self.send_header("content-type","application/json")
        for k,v in (hdr or {}).items(): self.send_header(k,v)
        self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        REQ.append(("GET",self.path)); b=json.dumps({"data":[{"id":"llama-3.3-70b-versatile"},{"id":"gpt-oss-20b"}]}).encode(); self.send_response(200); self.end_headers(); self.wfile.write(b)
    def do_POST(self):
        n=int(self.headers.get("content-length",0)); body=json.loads(self.rfile.read(n))
        REQ.append(("POST",self.path,dict(self.headers),body)); m=MODE[0]
        if m=="401": return self._err(401,{"error":{"message":"Invalid API Key","type":"invalid_request_error","code":"invalid_api_key"}})
        if m=="daily": return self._err(429,{"error":{"message":"Rate limit reached for model in organization on tokens per day (TPD): Limit 100000","code":"rate_limit_exceeded"}},{"retry-after":"1200"})
        if m=="rate": return self._err(429,{"error":{"message":"Rate limit reached on requests per minute (RPM)","code":"rate_limit_exceeded"}},{"retry-after":"7"})
        if m=="413": return self._err(413,{"error":{"message":"Request too large for model, tokens per minute","code":"rate_limit_exceeded"}})
        if m=="toolfail": return self._err(400,{"error":{"message":"Failed to call a function","code":"tool_use_failed"}})
        if m=="500": return self._err(500,{"error":{"message":"boom"}})
        if m=="404": return self._err(404,{"error":{"message":"The model `x` does not exist","code":"model_not_found"}})
        last=body["messages"][-1]
        if not body["stream"]:
            msg={"role":"assistant","content":"<think>hmm</think>OK"}
            self.send_response(200); self.send_header("content-type","application/json"); self.end_headers(); return self.wfile.write(json.dumps({"choices":[{"message":msg}]}).encode())
        if m=="think":
            return sse(self,[D(content="<thi"),D(content="nk>plan it</th"),D(content="ink>Hello "),D(content="world"),D(reasoning="deep thought")])
        if last["role"]=="user" and "time" in last["content"]:
            return sse(self,[D(role="assistant",content=""),D(tool_calls=[{"index":0,"id":"x","function":{"name":"get_time","arguments":""}}]),D(tool_calls=[{"index":0,"function":{"arguments":"{}"}}])])
        if last["role"]=="tool": return sse(self,[D(content="It is "),D(content="now: "+last["content"][:5])])
        return sse(self,[D(content="Hi "),D(content="there")])
srv=ThreadingHTTPServer(("127.0.0.1",8796),H); threading.Thread(target=srv.serve_forever,daemon=True).start()

import model_config as mc, llm, tools, scheduler, agent, server
from fastapi.testclient import TestClient
SENT=[]; scheduler.send_message=lambda t:(SENT.append(t) or (True,"ok"))
open("cfg21.yaml","w").write("llm:\n  base_url: http://127.0.0.1:8796/v1\n  api_key: gsk_test\n  model: llama-3.3-70b-versatile\n")
ok(mc.load(), mc.llm)
# a failing cloud request shows the real error as the reply of the turn; the next turn works again
MODE[0]="401"
ev=[]; server.conv.turn_job("hello", False, lambda e: ev.append(e), threading.Event())
errs=[e for e in ev if e["type"]=="error"]
ok(errs and "401" in errs[0]["message"] and "invalid_api_key" in errs[0]["message"], ev[-2:])
MODE[0]="ok"; ev=[]; server.conv.turn_job("hello", False, lambda e: ev.append(e), threading.Event())
d=[e for e in ev if e["type"]=="done"]; ok(d and d[0]["reply"]=="Hi there", ev[-2:])
print("LLM CHAT OK")
