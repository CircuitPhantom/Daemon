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
        if m=="gemini400": 
            b=json.dumps([{"error":{"code":400,"message":"Function call is missing a thought_signature","status":"INVALID_ARGUMENT"}}]).encode(); self.send_response(400); self.end_headers(); return self.wfile.write(b)
        if m=="500": return self._err(500,{"error":{"message":"boom"}})
        if m=="404": return self._err(404,{"error":{"message":"The model `x` does not exist","code":"model_not_found"}})
        last=body["messages"][-1]
        if not body["stream"]:
            msg={"role":"assistant","content":"<think>hmm</think>OK"}
            self.send_response(200); self.send_header("content-type","application/json"); self.end_headers(); return self.wfile.write(json.dumps({"choices":[{"message":msg}]}).encode())
        if m=="think":
            return sse(self,[D(content="<thi"),D(content="nk>plan it</th"),D(content="ink>Hello "),D(content="world"),D(reasoning="deep thought")])
        if last["role"]=="user" and "time" in last["content"]:
            return sse(self,[D(role="assistant",content=""),D(tool_calls=[{"index":0,"id":"x","function":{"name":"get_time","arguments":""}}]),D(tool_calls=[{"index":0,"function":{"arguments":"{}"},"extra_content":{"google":{"thought_signature":"SIG123"}}}])])
        if last["role"]=="tool": return sse(self,[D(content="It is "),D(content="now: "+last["content"][:5])])
        return sse(self,[D(content="Hi "),D(content="there")])
srv=ThreadingHTTPServer(("127.0.0.1",8796),H); threading.Thread(target=srv.serve_forever,daemon=True).start()

import model_config as mc, llm, tools, scheduler, agent, server
from fastapi.testclient import TestClient
SENT=[]; scheduler.send_message=lambda t:(SENT.append(t) or (True,"ok"))
# schemas
sc=llm.tool_schema(tools.calendar_add)["function"]
ok(sc["name"]=="calendar_add" and sc["parameters"]["required"]==["title","date"] and sc["parameters"]["properties"]["remind_minutes"]["type"]=="integer" and "all-day" in sc["description"].lower(), sc)
ok("2026-11-02" in sc["parameters"]["properties"]["date"]["description"], sc["parameters"]["properties"]["date"])
allj=json.dumps([llm.tool_schema(f) for f in tools.available_functions.values()]); ok(len(allj)<16500, len(allj))
ok(llm.tool_schema(tools.remind_me)["function"]["parameters"]["required"]==["message","when"], "required")
# messages
A=llm.AttrDict
hist=[{"role":"system","content":"S"},{"role":"user","content":"time?"},{"role":"assistant","content":"","tool_calls":[A(function=A(name="get_time",arguments={})),A(function=A(name="calculate",arguments={"e":"1+1"}))]},
      {"role":"tool","content":"12:00","tool_name":"get_time"},{"role":"tool","content":"2","tool_name":"calculate"},{"role":"assistant","content":"It is 12"},{"role":"tool","content":"orphan","tool_name":"x"}]
o=llm.to_openai_messages(hist)
ok(o[2]["tool_calls"][0]["id"]=="call_1" and o[2]["tool_calls"][1]["function"]["arguments"]=='{"e": "1+1"}' and o[3]=={"role":"tool","tool_call_id":"call_1","content":"12:00"} and o[4]["tool_call_id"]=="call_2" and o[6]["role"]=="user", o)
# think splitter
sp=llm.ThinkSplit(); r=[sp.feed(x) for x in ("a<th","ink>b</th","ink>c","d<")]; ok("".join(x[0] for x in r)=="acd" and "".join(x[1] for x in r)=="b" and sp.flush()==("<",""), r)
# Gemini signatures
o=llm.to_openai_messages([{"role":"assistant","content":"","tool_calls":[A(function=A(name="a",arguments={}),extra_content={"google":{"thought_signature":"S"}}),A(function=A(name="b",arguments={}))]}],google=True)
ok(o[0]["tool_calls"][0]["extra_content"]["google"]["thought_signature"]=="S" and o[0]["tool_calls"][1]["extra_content"]==llm.SKIP_SIG, o)
o=llm.to_openai_messages([{"role":"assistant","content":"","tool_calls":[A(function=A(name="b",arguments={}))]}]); ok("extra_content" not in o[0]["tool_calls"][0], "no placeholder for other providers")
# client
open("cfg21.yaml","w").write("llm:\n  base_url: http://127.0.0.1:8796/v1\n  api_key: gsk_test\n  model: llama-3.3-70b-versatile\n")
ok(mc.load() and mc.llm["timeout"]==60 and llm.name()=="127.0.0.1" and llm.configured(), mc.llm)
R=llm.Client(); REQ.clear()
r=R.chat(model="ignored",messages=[{"role":"system","content":"S"},{"role":"user","content":"hello"}],tools=[tools.get_time],stream=False,think=True,options={"num_ctx":8192})
ok(r.message.content=="OK" and r.message.thinking=="hmm", ("cloud answer",r))
p=[x for x in REQ if x[0]=="POST"][0]; ok(p[1]=="/v1/chat/completions" and p[2]["Authorization"]=="Bearer gsk_test" and p[3]["model"]=="llama-3.3-70b-versatile" and p[3]["tools"][0]["function"]["name"]=="get_time" and "daemon" in p[2]["User-Agent"], p)
chunks=list(R.chat(messages=[{"role":"user","content":"hello"}],stream=True)); ok("".join(c.message.content for c in chunks)=="Hi there", chunks)
MODE[0]="think"; ch=list(R.chat(messages=[{"role":"user","content":"hello"}],stream=True,think=True)); MODE[0]="ok"
ok("".join(c.message.content for c in ch)=="Hello world" and "".join(c.message.thinking for c in ch)=="plan itdeep thought", ch)
# full agent loop with a tool call
msgs=[{"role":"system","content":"S"},{"role":"user","content":"what time is it"}]; ev=[]
reply,th,used=agent.run_stream(R,None,False,[tools.get_time],msgs,lambda k,d:ev.append((k,d)))
ok(used and used[0]["name"]=="get_time" and reply.startswith("It is now:"), (reply,used))
last=[x for x in REQ if x[0]=="POST"][-1][3]["messages"]
ok(last[-1]["role"]=="tool" and last[-2]["tool_calls"][0]["id"]==last[-1]["tool_call_id"], last[-2:])
ok(last[-2]["tool_calls"][0]["extra_content"]["google"]["thought_signature"]=="SIG123", "signature sent back")
ok(llm.status()["last_ok_ago"] is not None and llm.status()["last_error"]=="" , llm.status())
# errors raise with the real message and are remembered; a key/quota problem is sent to you once
def fails(mode, word, notify):
    llm._s.update(notified=False,last_error="",last_error_at=0.0); SENT.clear(); MODE[0]=mode
    try: R.chat(messages=[{"role":"user","content":"a"}]); ok(False,(mode,"should raise"))
    except RuntimeError as e: err=str(e)
    time.sleep(0.15); st=llm.status(); MODE[0]="ok"
    ok(word in err and st["last_error"] and st["last_error_ago"]<5 and bool(SENT)==notify, (mode,err,st,SENT))
    return err
ok(fails("401","401",True).startswith("127.0.0.1 error:"), "message shape")
fails("daily","tokens per day",True); fails("rate","retry after 7",False); fails("500","boom",False); fails("404","model_not_found",True)
fails("gemini400","thought_signature",False)
e=fails("413","too large",False); ok("too large" in llm.status()["last_error"], llm.status())
n0=len([x for x in REQ if x[0]=="POST"]); MODE[0]="toolfail"
try: R.chat(messages=[{"role":"user","content":"a"}]); ok(False,"x")
except RuntimeError as e: ok("tool" in str(e).lower() or "function" in str(e).lower(), e)
ok(len([x for x in REQ if x[0]=="POST"])-n0==2, "a broken tool call is asked again once"); MODE[0]="ok"
# the notice is only sent once until a request works again
llm._s.update(notified=False); SENT.clear(); MODE[0]="401"
for _ in range(2):
    try: R.chat(messages=[{"role":"user","content":"a"}])
    except RuntimeError: pass
time.sleep(0.2); ok(len(SENT)==1, SENT); MODE[0]="ok"; R.chat(messages=[{"role":"user","content":"a"}]); ok(llm._s["notified"] is False, "reset after success")
# no internet
good=mc.llm["base_url"]; mc.llm["base_url"]="http://127.0.0.1:1/v1"
try: R.chat(messages=[{"role":"user","content":"a"}]); ok(False,"x")
except RuntimeError as e: ok("error" in str(e), e)
mc.llm["base_url"]=good
# not set up
key=mc.llm["api_key"]; mc.llm["api_key"]=""
try: R.chat(messages=[{"role":"user","content":"a"}]); ok(False,"x")
except RuntimeError as e: ok("not set up" in str(e), e)
ok(not llm.configured() and not llm.test()["ok"], "unconfigured"); mc.llm["api_key"]=key
# API
with TestClient(server.app) as c:
    s=c.get("/api/llm").json(); ok(s["configured"] and s["model"]=="llama-3.3-70b-versatile" and "gsk_test" not in json.dumps(s), s)
    t=c.post("/api/llm/test").json(); ok(t["ok"] and 'answered "OK"' in t["info"], t)
    MODE[0]="401"; t=c.post("/api/llm/test").json(); ok(not t["ok"] and "401" in t["info"], t); MODE[0]="ok"
    ev=[]; server.conv.turn_job("what time is it", False, lambda e: ev.append(e), threading.Event())
    d=[e for e in ev if e["type"]=="done"][0]; ok(d["reply"].startswith("It is now"), d)
    ok(c.get("/api/llm").json()["last_ok_ago"]<5, "status after a turn")
print("LLM OK")
