import os, sys, json, time, threading
sys.path[:0]=["stubs","."]
os.environ.update(DAEMON_CONFIG="cfg4.yaml", DAEMON_CHATS="chats4", DAEMON_MEMORY="mem4.json", DAEMON_REMINDERS="rem4.json")
import shutil
for f in ("cfg4.yaml","mem4.json","rem4.json"):
    if os.path.exists(f): os.remove(f)
shutil.rmtree("chats4", ignore_errors=True)
os.makedirs("sound", exist_ok=True)
from fastapi.testclient import TestClient
import server, ollama, pykokoro, numpy as np
def ok(c,m):
    if not c: print("FAIL",m); sys.exit(1)
def events(c, url, **kw):
    with c.stream("POST", url, **kw) as r:
        ok(r.status_code==200 and r.headers["content-type"].startswith("application/x-ndjson"), r.status_code)
        return [json.loads(l) for l in r.iter_lines() if l]
with TestClient(server.app) as c:
    ev = events(c, "/api/say/stream", json={"text":"long one","speak":True})
    kinds = [e["type"] for e in ev]
    print(kinds)
    ok(kinds[0]=="user" and kinds[-1]=="done" and "thinking" in kinds, kinds)
    text = "".join(e["text"] for e in ev if e["type"]=="delta")
    ok(text.strip().startswith("First sentence is here.") and ev[-1]["reply"]==text.strip(), text)
    aud = [e for e in ev if e["type"]=="audio"]
    ok(len(aud)>=2 and [a["seq"] for a in aud]==list(range(len(aud))), len(aud))
    print("spoken pieces:", pykokoro.SPOKEN)
    ok(pykokoro.SPOKEN[0].startswith("First sentence is here") and any("code block" in s for s in pykokoro.SPOKEN) and not any("x" in s.split() for s in pykokoro.SPOKEN), pykokoro.SPOKEN)
    # first audio arrives before done and before the last delta
    ok(kinds.index("audio") < kinds.index("done"), kinds)
    # no speak -> no audio
    ev = events(c, "/api/say/stream", json={"text":"hello","speak":False})
    ok(not [e for e in ev if e["type"]=="audio"] and ev[-1]["reply"]=="reply to: hello", ev[-1])
    # tool flow with preamble reset
    ev = events(c, "/api/say/stream", json={"text":"remember: I like tea","speak":False})
    kinds=[e["type"] for e in ev]; print(kinds)
    ok("reset" in kinds and "tool" in kinds and ev[-1]["reply"]=="Got it." and ev[-1]["tools"][0]["name"]=="remember", ev[-1])
    ev = events(c, "/api/say/stream", json={"text":"plain","speak":False})
    ok(ev[-1]["type"]=="done" and ev[-1]["reply"]=="reply to: plain", ev[-1])
    # saved & rev
    cur = c.get("/api/chats/current").json(); ok(len(cur["chat"]["turns"])==4 and cur["rev"]==ev[-1]["rev"], cur["rev"])
    ok(c.get("/api/chats/rev").json()["rev"]==cur["rev"], "rev endpoint")
    # voice stream (stub whisper)
    class Seg: 
        def __init__(s,t): s.text=t
    server.voice.stt.transcribe = lambda a, **k: ([Seg(" what time is it")], None)
    ev = events(c, "/talk/stream", content=np.zeros(16000, np.float32).tobytes(), headers={"Content-Type":"application/octet-stream"})
    ok({k:v for k,v in ev[0].items() if k!="turn"}=={"type":"user","text":"what time is it"} and ev[0].get("turn") and ev[-1]["type"]=="done" and any(e["type"]=="audio" for e in ev), [e["type"] for e in ev])
    ev = events(c, "/talk/stream", content=np.zeros(100, np.float32).tobytes(), headers={"Content-Type":"application/octet-stream"})
    ok(ev==[{"type":"done","user":"","reply":"","thinking":"","tools":[],"rev":ev[0]["rev"]}], ev)
    # cancel: the stream generator is closed (what uvicorn does on disconnect) -> cancel is set, turn stops
    import asyncio
    ollama.DELAY[0]=0.2
    resp = server.say_stream(server.SayIn(text="long slow", speak=True))
    async def consume():
        it = resp.body_iterator
        async for chunk in it:
            if b'"delta"' in chunk: break
        await it.aclose()
    asyncio.run(consume())
    t0=time.time()
    while server.conv.lock.locked() and time.time()-t0<5: time.sleep(0.05)
    ok(not server.conv.lock.locked() and time.time()-t0 < 2, "lock released quickly after cancel")
    last = c.get("/api/chats/current").json()["chat"]["turns"][-1]
    print("cancelled turn:", last["reply"]); ok(last["user"]=="long slow" and last["reply"].endswith("…") and len(last["reply"])<40, last)
    ollama.DELAY[0]=0
    # error path
    orig = server.agent.run_stream
    def boom(*a, **k): raise RuntimeError("ollama down")
    server.agent.run_stream = boom
    ev = events(c, "/api/say/stream", json={"text":"x","speak":False}); ok(ev[-1]["type"]=="error" and "ollama down" in ev[-1]["message"], ev)
    server.agent.run_stream = orig
    # search
    r = c.get("/api/chats", params={"q":"TEA"}).json(); ok(len(r["chats"])==1 and "tea" in r["chats"][0]["snippet"].lower() and r["query"]=="TEA", r)
    ok(c.get("/api/chats", params={"q":"zzzz"}).json()["chats"]==[], "no hits")
    # reminders API
    r = c.post("/api/reminders", json={"text":"stretch","when":"in 20 minutes"}).json(); ok(len(r["reminders"])==1 and r["reminders"][0]["text"]=="stretch", r)
    ok(c.post("/api/reminders", json={"text":"x","when":"blah"}).status_code==400, "bad when")
    rid = r["reminders"][0]["id"]; ok(c.delete(f"/api/reminders/{rid}").json()["reminders"]==[], "delete"); ok(c.delete("/api/reminders/nope").status_code==404, "404")
    # profiles
    s = c.get("/api/settings").json(); print(list(s["profiles"]))
    ok(set(s["profiles"])=={"Off","Read only","Assistant","Desktop","Full"} and len(s["profiles"]["Full"])== 37, s["profiles"].keys())
    s = c.post("/api/settings", json={"profile":"Read only"}).json(); ok(sorted(n for n,v in s["tools"].items() if v)==sorted(s["profiles"]["Read only"]), "apply")
    ok(c.post("/api/settings", json={"profile":"nope"}).status_code==404, "bad profile")
    c.put("/api/profiles/Mine", json={"tools":["get_time","bogus","get_time"]}); s=c.get("/api/settings").json(); ok(s["profiles"]["Mine"]==["get_time"], s["profiles"]["Mine"])
    c.delete("/api/profiles/Mine"); ok("Mine" not in c.get("/api/settings").json()["profiles"], "del profile")
    ok("tool_profiles:" in open("cfg4.yaml").read(), "saved to yaml")
    # wake settings validation + start attempt (no sounddevice here -> error status)
    ok(c.post("/api/settings", json={"wake":{"engine":"bad"}}).status_code==400, "engine validate")
    s = c.post("/api/settings", json={"wake":{"enabled":True,"phrase":"hey daemon"}}).json(); time.sleep(0.5)
    st = c.get("/api/wake").json(); print("wake status:", st); ok(not st["running"] and "sounddevice" in st["error"], st)
    c.post("/api/settings", json={"wake":{"enabled":False}})
print("STREAM BACKEND OK")
