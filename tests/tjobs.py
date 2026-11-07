import os, sys, json, time, threading, shutil
from types import SimpleNamespace as N
sys.path[:0]=["stubs","."]
D=os.path.abspath("dmn42")
os.environ.update(DAEMON_CONFIG="cfg42.yaml", DAEMON_CHATS="chats42", DAEMON_MEMORY="mem42.json", DAEMON_REMINDERS="rem42.json",
                  DAEMON_INBOX=os.path.abspath("inbox42.json"), DAEMON_FILES=D, DAEMON_JOBS=os.path.abspath("jobs42.json"),
                  DAEMON_TOOL_LOG=os.path.abspath("toollog42.jsonl"))
for f in ("cfg42.yaml","mem42.json","rem42.json","inbox42.json","jobs42.json","toollog42.jsonl"):
    if os.path.exists(f): os.remove(f)
shutil.rmtree("chats42", ignore_errors=True); shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
def ok(c,m=""):
    if not c: print("FAIL",m); sys.exit(1)
def wait(cond, t=10):
    end=time.time()+t
    while time.time()<end:
        if cond(): return True
        time.sleep(0.03)
    return False
import model_config as mc; ok(mc.load())
import ollama, jobs, tools, scheduler, toolguard, server, conversation as conv
from fastapi.testclient import TestClient

SENT=[]; FILES=[]
scheduler.send_message=lambda t:(SENT.append(t) or (True,"ok"))
tools.hooks["send_file"]=lambda f,c,w:(FILES.append((f,c,w)) or (True,"sent"))
def web_search(query: str, count: int = 5, fresh: str = "") -> str:
    return "1. Result for " + query
tools.available_functions["web_search"]=web_search

class Fake:
    def __init__(self): self.mode="normal"; self.calls=[]; self.gate=threading.Event(); self.long=False
    def chat(self, model=None, messages=None, tools=None, think=None, stream=False, **kw):
        self.calls.append({"tools":[t.__name__ for t in tools or []], "system":messages[0]["content"], "user":messages[1]["content"]})
        if self.mode=="slow": self.gate.wait(8)
        if self.mode=="error": raise RuntimeError("Anthropic error: 500 boom")
        last=messages[-1]; role=last["role"] if isinstance(last,dict) else last.role
        content=last["content"] if isinstance(last,dict) else last.content
        if role=="user" and "needle" in content:
            call=N(function=N(name="web_search", arguments={"query":"needle facts"}))
            return N(message=N(content="", thinking="", tool_calls=[call], role="assistant"))
        text=("Long. "*400) if self.long else "Done: "+(content[:30] if role=="tool" else "plain")+"\n\nSources: https://x.example"
        return N(message=N(content=text, thinking="", tool_calls=None, role="assistant"))
fake=Fake(); jobs.manager.client=fake

# tool list: no approval-needing tools, no recursion
mc.jobs["tools"]=["web_search","execute_command","screenshot","start_job","computer","write_file","get_time","bogus"]
ok(jobs.job_tools()==["web_search","get_time"], jobs.job_tools())
mc.jobs["tools"]=list(mc.DEFAULTS["jobs"]["tools"]); ok("web_search" in jobs.job_tools() and "inbox_add" in jobs.job_tools(), jobs.job_tools())

with TestClient(server.app) as c:
    # a normal job
    j=jobs.manager.submit("find the needle please", source="web"); ok(j["status"] in ("queued","running") and len(j["id"])==4, j)
    ok(wait(lambda: jobs.manager.get(j["id"])["status"]=="done"), jobs.manager.get(j["id"]))
    g=jobs.manager.get(j["id"]); ok(g["result"].startswith("Done: 1. Result for needle facts") and any(s.startswith("web_search: query=needle facts") for s in g["steps"]) and g["model_calls"]==2, g)
    ok(wait(lambda: SENT), SENT); ok(SENT[0].startswith(f"✅ Job {j['id']} done") and "Sources: https://x.example" in SENT[0] and not FILES, SENT[0])
    ok(g["file"].startswith(f"jobs/{j['id']}-") and "Sources" in open(os.path.join(D,g["file"])).read(), g["file"])
    ok("background job" in fake.calls[0]["system"] and "untrusted" in fake.calls[0]["system"] and "Current time" in fake.calls[0]["user"], fake.calls[0])
    ok("execute_command" not in fake.calls[0]["tools"] and "start_job" not in fake.calls[0]["tools"] and "web_search" in fake.calls[0]["tools"], fake.calls[0]["tools"])
    import inbox; ok(any("Job result" in x["text"] and "job" in x["tags"] for x in inbox.items(10)), "saved to the inbox")
    log=[json.loads(l) for l in open("toollog42.jsonl")]; ok(any(e["tool"]=="web_search" and e["source"]=="task" for e in log), log[-2:])
    # a long result is attached
    SENT.clear(); fake.long=True; j2=jobs.manager.submit("long one"); ok(wait(lambda: jobs.manager.get(j2["id"])["status"]=="done" and SENT))
    ok(len(SENT[0])<2000 and "full text is attached" in SENT[0] and FILES and FILES[0][0].startswith("jobs/") and FILES[0][2]=="phone", (len(SENT[0]), FILES)); fake.long=False
    # an error
    SENT.clear(); fake.mode="error"; j3=jobs.manager.submit("will fail"); ok(wait(lambda: jobs.manager.get(j3["id"])["status"]=="error" and SENT))
    ok("500 boom" in jobs.manager.get(j3["id"])["error"] and SENT[0].startswith(f"⚠️ Job {j3['id']} failed"), SENT)
    # cancel a running job; no message
    SENT.clear(); fake.mode="slow"; fake.gate.clear(); j4=jobs.manager.submit("slow one"); ok(wait(lambda: jobs.manager.get(j4["id"])["status"]=="running"))
    ok(jobs.manager.cancel(j4["id"]) is True); fake.gate.set(); ok(wait(lambda: jobs.manager.get(j4["id"])["status"]=="cancelled"), jobs.manager.get(j4["id"]))
    time.sleep(0.3); ok(not SENT, SENT); ok(jobs.manager.cancel(j4["id"]) is False, "finished job")
    # queue: one slot
    mc.jobs["max_running"]=1; fake.gate.clear(); a=jobs.manager.submit("first"); b=jobs.manager.submit("second")
    ok(wait(lambda: jobs.manager.get(a["id"])["status"]=="running")); time.sleep(0.5); ok(jobs.manager.get(b["id"])["status"]=="queued", "waits for a free slot")
    ok(jobs.manager.cancel(b["id"]) and jobs.manager.get(b["id"])["status"]=="cancelled", "cancel a queued job")
    c2=jobs.manager.submit("third"); fake.mode="normal"; fake.gate.set()
    ok(wait(lambda: jobs.manager.get(a["id"])["status"]=="done" and jobs.manager.get(c2["id"])["status"]=="done"), [jobs.manager.get(x["id"])["status"] for x in (a,c2)])
    mc.jobs["max_running"]=2
    # validation
    for bad in ("", "  ", "x"*4001):
        try: jobs.manager.submit(bad); ok(False,"should raise")
        except ValueError: pass
    mc.jobs["enabled"]=False
    try: jobs.manager.submit("x"); ok(False,"off")
    except ValueError as e: ok("turned off" in str(e), e)
    mc.jobs["enabled"]=True
    # the tool the model uses
    out=tools.start_job(task="research needle", title="Needle"); ok(out.startswith("Job ") and "started in the background" in out, out)
    mc.jobs["enabled"]=False; out=tools.start_job(task="x"); ok(out.startswith("Error: background jobs are turned off"), out); mc.jobs["enabled"]=True
    ok(tools.start_job.__doc__ and "background" in tools.start_job.__doc__, "doc")
    ok(wait(lambda: not any(x["status"] in jobs.ACTIVE for x in jobs.manager.list())), "all idle")
    # Signal
    hs=conv.handle_signal
    ok("/job <what to do>" in hs("/help"), "help")
    ok(hs("/job").startswith("Usage: /job"), hs("/job"))
    r=hs("/job find the needle"); ok(r.startswith("Job ") and "started" in r, r); jid=r.split()[1]
    ok(wait(lambda: jobs.manager.get(jid)["status"]=="done"))
    ok(jid in hs("/jobs") and "✅" in hs("/jobs"), hs("/jobs"))
    ok(hs(f"/job {jid}").startswith(f"Job {jid}: ") and "Sources:" in hs(f"/job {jid}"), hs(f"/job {jid}"))
    ok(hs("/job #"+jid).startswith("Job "+jid), "with #")
    ok(hs("/cancel").startswith("Usage: /cancel") or "not running" in hs("/cancel"), hs("/cancel"))
    ok(hs(f"/cancel {jid}")=="That job is not running." and hs("/cancel zzzz")=="No job with that id.", "cancel replies")
    fake.mode="slow"; fake.gate.clear(); r=hs("/job slow thing"); sid=r.split()[1]
    ok(wait(lambda: jobs.manager.get(sid)["status"]=="running")); ok(hs("/cancel")==f"Stopping job {sid}.", "one active job needs no id"); fake.gate.set(); fake.mode="normal"
    ok(wait(lambda: jobs.manager.get(sid)["status"]=="cancelled"))
    # API
    r=c.get("/api/jobs").json(); ok(r["enabled"] and r["jobs"] and "web_search" in r["tools"] and r["max_running"]==2, r)
    r=c.post("/api/jobs", json={"prompt":"api needle job"}); ok(r.status_code==200 and r.json()["job"]["id"], r.text); aid=r.json()["job"]["id"]
    ok(c.post("/api/jobs", json={"prompt":"  "}).status_code==400, "empty")
    ok(wait(lambda: c.get("/api/jobs/"+aid).json()["status"]=="done")); d=c.get("/api/jobs/"+aid).json(); ok(d["prompt"]=="api needle job" and d["result"].startswith("Done:") and d["steps"], d)
    brief=[x for x in c.get("/api/jobs").json()["jobs"] if x["id"]==aid][0]; ok("prompt" not in brief and len(brief["result"])<=300, brief)
    ok(c.post(f"/api/jobs/{aid}/cancel").status_code==409 and c.post("/api/jobs/zzzz/cancel").status_code==404 and c.get("/api/jobs/zzzz").status_code==404, "errors")
    ok(c.delete(f"/api/jobs/{aid}").status_code==200 and c.get(f"/api/jobs/{aid}").status_code==404 and c.delete("/api/jobs/zzzz").status_code==404, "delete")
    ok(c.get("/api/settings").json()["profiles"]["Assistant"].count("start_job")==1, "start_job in the Assistant profile")

# persistence: a job that was running when the server stopped
jobs.manager.stop(); time.sleep(0.2)
data=json.load(open("jobs42.json")); ok(isinstance(data,list) and len(data)>=5, len(data))
data.insert(0,{"id":"dead","title":"was running","prompt":"p","source":"web","status":"running","created":time.time(),"started":time.time(),"finished":0,"steps":[],"model_calls":0,"result":"","error":"","file":"","sent":""})
json.dump(data,open("jobs42.json","w")); m2=jobs.Jobs(fake); m2._load()
ok(m2.get("dead")["status"]=="interrupted" and "stopped" in m2.get("dead")["error"], m2.get("dead"))
print("JOBS OK")
