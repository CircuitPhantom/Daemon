import os, sys, shutil
sys.path[:0]=["stubs","."]
os.environ.update(DAEMON_CONFIG="cfg15.yaml", DAEMON_CHATS="chats15", DAEMON_MEMORY="mem15.json", DAEMON_REMINDERS="rem15.json", DAEMON_CALENDAR="cal15.json")
for f in ("cfg15.yaml","mem15.json","rem15.json","cal15.json"):
    if os.path.exists(f): os.remove(f)
shutil.rmtree("chats15", ignore_errors=True)
def ok(c,m):
    if not c: print("FAIL",m); sys.exit(1)
import server, model_config as mc, tools, agenda
from fastapi.testclient import TestClient
ok(tools.hooks.get("calendar") is agenda.store, "hook")
with TestClient(server.app) as c:
    r=c.post("/api/calendar",json={"title":"Dentist","date":"2026-11-02","start":"15:30","end":"16:00","remind":20}); ok(r.status_code==200, r.text)
    eid=r.json()["event"]["id"]
    ok(c.post("/api/calendar",json={"title":"","date":"2026-11-02"}).status_code==400, "empty title")
    ok(c.post("/api/calendar",json={"title":"x","date":"31.02.2026"}).status_code==400, "bad date")
    c.post("/api/calendar",json={"title":"Birthday","date":"2026-11-02"})
    r=c.get("/api/calendar",params={"start":"2026-11-01","end":"2026-11-30"}).json(); ok([e["title"] for e in r["events"]]==["Birthday","Dentist"] and r["today"], r)
    ok(c.get("/api/calendar",params={"start":"nonsense"}).status_code==400, "bad range")
    ok(c.get("/api/calendar").status_code==200, "default month")
    r=c.put(f"/api/calendar/{eid}",json={"title":"Dentist 2","start":""}); ok(r.json()["event"]["start"] is None and r.json()["event"]["title"]=="Dentist 2", r.text)
    ok(c.put("/api/calendar/nope",json={"title":"x"}).status_code==404, "404")
    ok(c.delete(f"/api/calendar/{eid}").status_code==200 and c.delete(f"/api/calendar/{eid}").status_code==404, "delete")
    s=c.get("/api/calendar-settings").json(); ok(s["briefing"] is False and s["briefing_time"]=="08:00" and "calls" in s, s)
    s=c.post("/api/calendar-settings",json={"briefing":True,"briefing_time":"7:30","briefing_call":False}).json(); ok(s["briefing"] and s["briefing_time"]=="07:30" and not s["briefing_call"], s)
    ok("briefing_time: 07:30" in open("cfg15.yaml").read() or "07:30" in open("cfg15.yaml").read(), "saved")
    ok(c.post("/api/calendar-settings",json={"briefing_time":"99"}).status_code==400 and c.post("/api/calendar-settings",json={"briefing":"yes"}).status_code==400, "validation")
    r=c.post("/api/calendar-briefing",json={"date":"2026-11-02"}).json(); ok("text" in r and r["events"]==1, r)
    ok(c.post("/api/calendar-briefing",json={"date":"zzz"}).status_code==400, "bad brief date")
print("calendar api OK")
