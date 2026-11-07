import os, sys, json, time, shutil, threading
sys.path[:0]=["stubs","."]
os.environ.update(DAEMON_CONFIG="cfg34.yaml", DAEMON_CHATS="chats34", DAEMON_MEMORY="mem34.json", DAEMON_REMINDERS="rem34.json",
                  DAEMON_INBOX=os.path.abspath("inbox34.json"), DAEMON_TOOL_LOG=os.path.abspath("toollog34.jsonl"),
                  FAKE_INBOX=os.path.abspath("sig_in.txt"), FAKE_SENT=os.path.abspath("sig_sent.txt"))
os.environ["PATH"]=os.path.abspath("fakesig")+":"+os.environ["PATH"]
for f in ("cfg34.yaml","mem34.json","rem34.json","sig_in.txt","sig_sent.txt","inbox34.json","toollog34.jsonl"):
    if os.path.exists(f): os.remove(f)
shutil.rmtree("chats34", ignore_errors=True)
def ok(c,m=""):
    if not c: print("FAIL",m); sys.exit(1)
def wait(cond, t=15):
    end=time.time()+t
    while time.time()<end:
        if cond(): return True
        time.sleep(0.05)
    return False
open("cfg34.yaml","w").write('model: qwen3:1.7b\ntools: [execute_command, get_time]\nsignal:\n  enabled: true\n  account: "+15551234567"\n  allowed: +905551112233\n')
import model_config as mc; ok(mc.load())
ok(mc.security["confirm"] and "execute_command" in mc.security["confirm_tools"] and mc.security["confirm_seconds"]==90, mc.security)
import toolguard, tools, agent, server, signal_bot, ollama
import uvicorn, http.client
# unit
ok(toolguard.summary("execute_command",{"cmnd":"ls   -la ~"})=="ls -la ~", toolguard.summary("execute_command",{"cmnd":"ls   -la ~"}))
ok("notes.txt (5 characters): hello" in toolguard.summary("write_file",{"file":"notes.txt","content":"hello"}), "write summary")
ok(toolguard.check("execute_command",{"cmnd":"x"})==(True,"task"), "a task never asks")
ok(toolguard.check("get_time",{})==(True,"auto"), "a safe tool never asks")
ok(toolguard.answer_text("hello") is None and toolguard.answer_text("yes") is None, "nothing open: not an answer")

def sent(): return [json.loads(l) for l in open("sig_sent.txt")] if os.path.exists("sig_sent.txt") else []
class R:
    def __init__(self, code, body): self.status_code, self.body = code, body
    def json(self): return json.loads(self.body)
class C:
    def _req(self, m, path, body=None):
        h=http.client.HTTPConnection("127.0.0.1",8812,timeout=30)
        h.request(m, path, body=json.dumps(body) if body is not None else None, headers={"Content-Type":"application/json"})
        r=h.getresponse(); return R(r.status, r.read())
    def get(self, p): return self._req("GET", p)
    def post(self, p, json=None): return self._req("POST", p, json)
srv=uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=8812, log_level="warning"))
threading.Thread(target=srv.run, daemon=True).start()
if True:
    c=C()
    ok(wait(lambda: signal_bot.bot.running()), "bot up"); time.sleep(1.5)
    def stream_turn(text, answer=None, stop_at_approve=False):
        evs=[]
        h=http.client.HTTPConnection("127.0.0.1",8812,timeout=60)
        h.request("POST","/api/say/stream",body=json.dumps({"text":text,"speak":False}),headers={"Content-Type":"application/json"})
        r=h.getresponse()
        while True:
            line=r.readline()
            if not line: break
            if not line.strip(): continue
            ev=json.loads(line); evs.append(ev)
            if ev["type"]=="approve":
                if stop_at_approve:
                    h.sock.close(); h.close(); break
                if answer is not None:
                    ok(c.get("/api/approvals").json()["approvals"][0]["tool"]=="execute_command", "listed")
                    ok(c.post(f"/api/approvals/{ev['id']}", json={"ok":answer}).status_code==200, "answered")
        return evs
    # approve from the dashboard -> runs
    evs=stream_turn("runcmd: echo approved-run", answer=True)
    ap=[e for e in evs if e["type"]=="approve"]; ok(ap and ap[0]["args"]=="echo approved-run" and ap[0]["timeout"]==90, ap)
    ok(any(e["type"]=="approved" and e["ok"] for e in evs), "approved event")
    tool=[e for e in evs if e["type"]=="tool"][0]; ok("approved-run" in tool["output"], tool)
    # deny -> not run
    evs=stream_turn("runcmd: echo should-not-run", answer=False)
    tool=[e for e in evs if e["type"]=="tool"][0]; ok(tool["output"].startswith("Not run") and "should-not-run" not in tool["output"], tool)
    ok(c.post("/api/approvals/zzzzzz", json={"ok":True}).status_code==404, "unknown id")
    ok(c.post("/api/approvals/zzzzzz", json={"ok":"yes"}).status_code==400, "bad body")
    # page closed while waiting -> refused quickly (not after 90 s)
    t0=time.time(); stream_turn("runcmd: echo closed-tab", stop_at_approve=True)
    ok(wait(lambda: not c.get("/api/approvals").json()["approvals"], 5) and time.time()-t0<6, "cancel ends the wait")
    ok(wait(lambda: not server.conv.lock.locked(), 5), "turn finished")
    # timeout
    mc.security["confirm_seconds"]=1
    evs=stream_turn("runcmd: echo too-late"); tool=[e for e in evs if e["type"]=="tool"][0]
    ok("no answer within 1 s" in tool["output"], tool["output"])
    mc.security["confirm_seconds"]=20
    # Signal: asked on Signal, "yes" answers it while the turn is still running
    n=len(sent())
    env={"sourceNumber":"+905551112233","timestamp":int(time.time()*1000),"dataMessage":{"message":"runcmd: echo from-signal","timestamp":1}}
    open("sig_in.txt","a").write(json.dumps(env)+"\n")
    ok(wait(lambda: any("wants to use execute_command" in m["message"] for m in sent()[n:]), 20), sent()[n:])
    ok(c.get("/api/approvals").json()["approvals"][0]["source"]=="signal", "listed for the dashboard too")
    env["timestamp"]=int(time.time()*1000); env["dataMessage"]={"message":"yes","timestamp":2}
    open("sig_in.txt","a").write(json.dumps(env)+"\n")
    ok(wait(lambda: any("OK, running execute_command" in m["message"] for m in sent()[n:]), 10), sent()[n:])
    ok(wait(lambda: any(m["message"]=="Got it." for m in sent()[n:]), 15), sent()[n:])
    # a stranger's "yes" is ignored
    # the log
    log=c.get("/api/toollog").json()["items"]
    ok(log[0]["tool"]=="execute_command" and log[0]["source"]=="signal" and log[0]["decision"]=="approved", log[0])
    dec=[x["decision"] for x in log]; ok(any(d.startswith("refused: you said no") for d in dec) and any("no answer within" in d for d in dec), dec)
    ok(oct(os.stat("toollog34.jsonl").st_mode & 0o777)=="0o600", "log is private")
    # switch off -> runs without asking
    r=c.post("/api/security", json={"confirm":False}).json(); ok(r["confirm"] is False and "execute_command" in r["choices"], r)
    evs=stream_turn("runcmd: echo no-ask"); ok(not any(e["type"]=="approve" for e in evs) and "no-ask" in [e for e in evs if e["type"]=="tool"][0]["output"], evs)
    ok(c.get("/api/toollog").json()["items"][0]["decision"]=="auto", "auto logged")
    ok(c.post("/api/security", json={"confirm_tools":["nope"]}).status_code==400 and c.post("/api/security", json={"confirm_seconds":5}).status_code==400, "validation")
    r=c.post("/api/security", json={"confirm":True,"confirm_tools":["write_file"],"confirm_seconds":30}).json()
    ok(r["confirm_tools"]==["write_file"] and r["confirm_seconds"]==30, r)
    mc.load(); ok(mc.security=={"confirm":True,"confirm_tools":["write_file"],"confirm_seconds":30}, mc.security)
    ok("busy" in c.get("/api/chats/rev").json(), "rev")
print("OK security")
