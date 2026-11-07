import os, sys, json, time, threading, contextvars
sys.path[:0]=["stubs","."]
os.environ.update(DAEMON_CONFIG="cfg35.yaml", DAEMON_MEMORY="mem35.json", DAEMON_REMINDERS="rem35.json")
for f in ("cfg35.yaml","mem35.json","rem35.json"):
    if os.path.exists(f): os.remove(f)
def ok(c,m=""):
    if not c: print("FAIL",m); sys.exit(1)
# old config: profiles saved before the new tools existed; signal.data_dir kept
open("cfg35.yaml","w").write('model: m\nsignal:\n  data_dir: /srv/signal\ntool_profiles:\n  Assistant: [read_file, write_file]\n  Full: [read_file]\n  Mine: [get_time]\n')
import model_config as mc, tools; ok(mc.load())
ok(mc.signal_cfg["data_dir"]=="/srv/signal", mc.signal_cfg)
a=mc.tool_profiles["Assistant"]; ok("send_file" in a and "inbox_add" in a and "read_file" in a and "web_search" not in a, a)
ok(mc.tool_profiles["Full"]==list(tools.available_functions), "Full = everything")
ok(mc.tool_profiles["Mine"]==["get_time"], "own profiles untouched")
mc.tool_profiles["Assistant"].remove("inbox_add"); mc.save(); mc.load()
ok("inbox_add" not in mc.tool_profiles["Assistant"], "a tool you removed later stays removed")
ok("data_dir: /srv/signal" in open("cfg35.yaml").read() and "tools_seen" in open("cfg35.yaml").read(), "saved")

# memory: forget never removes a random note
import memstore
memstore.add("The user's name is Poyraz."); memstore.add("The user has a cat named Pasha.")
ok(memstore.forget("the user") .startswith("Nothing to forget") , memstore.forget("the user"))
ok(memstore.forget("dog named Rex")=="No matching memory found." and len(memstore.items())==2, "no match keeps both")
ok("Pasha" in memstore.forget("cat Pasha") and len(memstore.items())==1, "right one")

# reminders
import reminders
from datetime import datetime
from zoneinfo import ZoneInfo
tz=ZoneInfo("Europe/Istanbul"); fri=datetime(2026,11,6,10,0,tzinfo=tz)          # a Friday, 10:00
ok(reminders.parse_when("friday 9:00", fri).date().isoformat()=="2026-11-13", reminders.parse_when("friday 9:00", fri))
ok(reminders.parse_when("friday 11:00", fri).date().isoformat()=="2026-11-06", "later today")
r=reminders.Reminders(); r.add("call mom", "in 2 hours"); r.add("buy milk", "in 3 hours")
ok(r.cancel("the reminder") is None and len(r.list_items())==2, "vague words cancel nothing")
ok(r.cancel("milk")["text"]=="buy milk", "cancel by word")
ok(r.cancel("reminder")["text"]=="call mom", "only one left: cancel it")

# uploads: text cut in the middle of a character at 4096 bytes
import uploads
data=("a"*4095+"ş"+"b"*10).encode()
ok(uploads._looks_text(data), "multi-byte at the edge is still text")
ok(not uploads._looks_text(b"\xff\xfe\x00\x01"*2000), "binary")

# llm: a tool call without a result never reaches the cloud
import llm
from types import SimpleNamespace as N
msgs=[{"role":"user","content":"hi"},{"role":"assistant","content":"","tool_calls":[N(function=N(name="get_time",arguments={}))]},
      {"role":"user","content":"stop that"}]
out=llm.to_openai_messages(msgs)
ok([m["role"] for m in out]==["user","assistant","tool","user"] and out[2]["tool_call_id"]==out[1]["tool_calls"][0]["id"], out)
out=llm.to_openai_messages(msgs[:2]); ok(out[-1]["role"]=="tool", "at the end too")

# agent: a stopped reply leaves no call without a result; tool threads see the turn's context
import agent, toolguard
ev=threading.Event()
class Cl:
    def chat(self, **k):
        def g():
            yield N(message=N(content="", thinking="", tool_calls=[N(function=N(name="get_time",arguments={}))]))
            ev.set()
        return g()
hist=[{"role":"user","content":"x"}]
agent.run_stream(Cl(), "m", False, [tools.available_functions["get_time"]], hist, lambda *a: None, ev)
ok("tool_calls" not in hist[-1], hist[-1])
seen={}
def probe(): seen["ctx"]=toolguard.current.get(); return "ok"
toolguard.current.set({"source":"signal"}); agent.call_tool(probe, {}); ok(seen["ctx"]=={"source":"signal"}, seen)

# calendar and get_time use notify.timezone, not the server clock
import agenda, scheduler
mc.notify["timezone"]="Pacific/Kiritimati"                  # UTC+14: a different date than UTC most of the day
ok(agenda.today()==datetime.now(ZoneInfo("Pacific/Kiritimati")).date(), "agenda today")
tools.hooks["tz"]=scheduler.get_tz; ok("+14" in tools.get_time(), tools.get_time())
mc.notify["timezone"]="Europe/Istanbul"
print("OK review")
