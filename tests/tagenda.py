import os, sys, json, time, shutil
from datetime import date, datetime, timedelta
sys.path[:0]=["stubs","."]
os.environ.update(DAEMON_CONFIG="cfg14.yaml", DAEMON_CHATS="chats14", DAEMON_MEMORY="mem14.json", DAEMON_REMINDERS="rem14.json",
                  DAEMON_CALENDAR="cal14.json", FAKE_INBOX=os.path.abspath("sig_in.txt"), FAKE_SENT=os.path.abspath("sig_sent.txt"))
os.environ["PATH"]=os.path.abspath("fakesig")+":"+os.environ["PATH"]
for f in ("cfg14.yaml","mem14.json","rem14.json","cal14.json","sig_in.txt","sig_sent.txt"):
    if os.path.exists(f): os.remove(f)
shutil.rmtree("chats14", ignore_errors=True)
def ok(c,m):
    if not c: print("FAIL",m); sys.exit(1)
import model_config as mc, agenda, scheduler, tools, twilio_call, phone_bridge
from agenda import CalendarError
ref=date(2026,10,31)  # Saturday
pd=lambda t: agenda.parse_date(t, ref)
ok(pd("today")==ref and pd("tomorrow")==date(2026,11,1) and pd("2026-11-02")==date(2026,11,2), "basic dates")
ok(pd("friday")==date(2026,11,6) and pd("saturday")==ref and pd("next monday")==date(2026,11,2) and pd("cuma")==date(2026,11,6), "weekdays")
ok(pd("05.11.2026")==date(2026,11,5) and pd("in 3 days")==date(2026,11,3) and pd("1.1")==date(2027,1,1) and pd("31.10")==ref, "formats")
for bad in ("", "someday", "2026-13-40", "31.02.2026"):
    try: pd(bad); ok(False, "should fail "+bad)
    except CalendarError: pass
pt=agenda.parse_time
ok(pt("15:30")=="15:30" and pt("9")=="09:00" and pt("9.30")=="09:30" and pt("9am")=="09:00" and pt("12 am")=="00:00" and pt("12pm")=="12:00" and pt("3:30 PM")=="15:30", "times")
ok(pt("")is None and pt("all day") is None and pt(None) is None, "all-day")
for bad in ("25:00","9:75","13pm","noonish"):
    try: pt(bad); ok(False,"should fail "+bad)
    except CalendarError: pass
ok(agenda.say_time("15:30")=="3:30 PM" and agenda.say_time("00:00")=="12 AM" and agenda.say_time("12:00")=="12 PM", "say")

st=agenda.Agenda("cal14.json")
a=st.add({"title":"  Dentist ","date":"2026-11-02","start":"15:30","end":"16:15","remind":30,"notes":"bring card"})
b=st.add({"title":"Mom's birthday","date":"2026-11-02"})
c=st.add({"title":"Gym","date":"2026-11-02","start":"07:00"})
st.add({"title":"Later","date":"2026-12-01"})
ok(a["title"]=="Dentist" and a["remind"]==30 and b["start"] is None and b["remind"] is None, (a,b))
day=st.between("2026-11-02","2026-11-02")
ok([e["title"] for e in day]==["Mom's birthday","Gym","Dentist"], [e["title"] for e in day])   # all-day first
for bad in ({"title":"","date":"2026-11-02"},{"title":"x"},{"title":"x","date":"2026-11-02","start":"10:00","end":"09:00"},
            {"title":"x","date":"2026-11-02","start":"10:00","remind":"abc"},{"title":"x","date":"2026-11-02","start":"10:00","remind":99999}):
    try: st.add(bad); ok(False,f"should fail {bad}")
    except CalendarError: pass
r=st.add({"title":"All day with remind","date":"2026-11-03","remind":10}); ok(r["remind"] is None, "no remind without time")
# update
u=st.update(a["id"],{"start":"all day"}); ok(u["start"] is None and u["end"] is None and u["remind"] is None, u)
u=st.update(a["id"],{"start":"16:00","end":"17:00","date":"tomorrow" if False else "2026-11-04","remind":15}); ok(u["date"]=="2026-11-04" and u["end"]=="17:00", u)
try: st.update("nope",{"title":"x"}); ok(False,"missing")
except CalendarError as e: ok("no event" in str(e), e)
# persistence + external edit picked up
st2=agenda.Agenda("cal14.json"); ok(len(st2.between("2026-01-01","2027-01-01"))==5, "reload")
d=json.load(open("cal14.json")); d["events"].append({"id":"zz","title":"Edited by hand","date":"2026-11-09","start":None,"end":None,"notes":"","remind":None})
d["events"].append({"id":"bad","title":"","date":"nope"}); time.sleep(0.01); open("cal14.json","w").write(json.dumps(d))
ok(any(e["id"]=="zz" for e in st.between("2026-11-09","2026-11-09")), "hand edit seen"); ok(len(st.between("2026-01-01","2027-01-01"))==6, "bad one dropped")
st.delete("zz")
try: st.delete("zz"); ok(False,"twice")
except CalendarError: pass
open("cal14.json","w").write("{not json"); st3=agenda.Agenda("cal14.json")
ok(os.path.exists("cal14.json.broken") and st3.between("2000-01-01","2100-01-01")==[], "broken file kept")
os.remove("cal14.json.broken")

# plan text
st=agenda.Agenda("cal14.json")
ok("nothing planned" in st.plan_text(ref), st.plan_text(ref))
st.add({"title":"Dentist","date":"2026-11-02","start":"15:30","end":"16:15"}); st.add({"title":"Mom's birthday","date":"2026-11-02"})
st.add({"title":"Standup","date":"2026-11-03","start":"09:00"})
t=st.plan_text(date(2026,11,2)); ok("2 things" in t and "All day: Mom's birthday." in t and "At 3:30 PM until 4:15 PM: Dentist." in t and "Tomorrow you have 1 event." in t, t)
ok(t.index("All day")<t.index("At 3:30"), "order")
for i in range(10): st.add({"title":f"E{i}","date":"2026-11-10","start":f"{8+i}:00"})
ok("And 2 more." in st.plan_text(date(2026,11,10)), st.plan_text(date(2026,11,10)))

# tool texts
tools.hooks["calendar"]=st
o=tools.calendar_add("Call bank","2026-11-05","10am",remind_minutes=20); ok(o.startswith("Added:") and "Call bank" in o, o)
o=tools.calendar_list("2026-11-02","2026-11-05"); ok("Dentist" in o and "Call bank" in o and "all day" in o, o)
eid=[l.split(" | ")[0] for l in o.splitlines() if "Call bank" in l][0]
o=tools.calendar_update(eid, time="11:30", remind_minutes=0); ok("11:30" in o and "remind" not in o, o)
o=tools.calendar_update(eid, notes="ask about fees"); ok("ask about fees" in o, o)
ok(tools.calendar_update(eid).startswith("Error"), "nothing to change")
ok(tools.calendar_add("x","blah").startswith("Error"), "bad date is an error text")
ok("No events" in tools.calendar_list("2030-01-01"), "empty")
o=tools.calendar_delete(eid); ok(o.startswith("Deleted:"), o); ok(tools.calendar_delete(eid).startswith("Error"), "gone")
tools.hooks.pop("calendar"); ok("only available" in tools.calendar_list(), "no hook")
for n in ("calendar_list","calendar_add","calendar_update","calendar_delete"): ok(n in tools.available_functions, n)

# config
open("cfg14.yaml","w").write("model: m\ncalendar:\n  briefing: true\n  briefing_time: '7:05'\n  briefing_call: false\n")
ok(mc.load() and mc.calendar_cfg["briefing"] is True and mc.calendar_cfg["briefing_time"]=="07:05" and mc.calendar_cfg["briefing_call"] is False and mc.calendar_cfg["briefing_skip_empty"] is True, mc.calendar_cfg)
open("cfg14.yaml","w").write("model: m\ncalendar:\n  briefing_time: '25:99'\n"); mc.load(); ok(mc.calendar_cfg["briefing_time"]=="08:00" and mc.calendar_cfg["briefing"] is False, mc.calendar_cfg)
mc.calendar_cfg.update(briefing=True,briefing_time="08:00"); mc.save(); ok("calendar:" in open("cfg14.yaml").read() and "briefing_time" in open("cfg14.yaml").read(), "saved")

# briefing + reminders with fake send / call
SENT=[]; CALLS=[]
scheduler.send_message=lambda text: (SENT.append(text) or (True,"ok"))
twilio_call.configured=lambda: True
phone_bridge.available=lambda: True
twilio_call.place_talk_call=lambda g,n="": (CALLS.append((g,n)) or (True,"calling"))
tz=scheduler.get_tz()
at=lambda d,h,m=0: datetime(d.year,d.month,d.day,h,m,tzinfo=tz)
d2=date(2026,11,2)
mc.calendar_cfg.update(briefing=True,briefing_time="08:00",briefing_call=True,briefing_skip_empty=True)
st.tick(at(d2,7,59)); ok(not SENT and not CALLS, "too early")
st.tick(at(d2,8,0)); ok(len(SENT)==1 and len(CALLS)==1 and "Dentist" in CALLS[0][0] and "Dentist" in CALLS[0][1] and "Dentist" in SENT[0], (SENT,CALLS))
st.tick(at(d2,8,1)); st.tick(at(d2,9,0)); ok(len(SENT)==1 and len(CALLS)==1, "only once per day")
st2=agenda.Agenda("cal14.json"); st2.tick(at(d2,9,0)); ok(len(CALLS)==1, "remembered across restarts")
d9=date(2026,11,9); st.tick(at(d9,8,5)); ok(len(CALLS)==1, "empty day is skipped")
mc.calendar_cfg["briefing_skip_empty"]=False; st.state_reset=st._state.pop("briefed"); st.tick(at(d9,8,5)); ok(len(CALLS)==2 and "nothing planned" in CALLS[1][0], "empty day when asked")
st._state.pop("briefed"); st.tick(at(date(2026,11,3),12,30)); ok(len(CALLS)==2, "more than 3 h late is skipped")
mc.calendar_cfg["briefing_call"]=False; st._state.pop("briefed",None); n=len(SENT); st.tick(at(d2,8,2)); ok(len(CALLS)==2 and len(SENT)==n+1, "message only")
# manual brief
r=st.brief(d9, manual=True); ok(r["message"] and r["events"]==10 or r["events"]==0, r)
mc.calendar_cfg.update(briefing=False)
# event reminders
SENT.clear(); st=agenda.Agenda("cal14.json"); st.add({"title":"Pills","date":"2026-11-02","start":"20:00","remind":30})
st.tick(at(d2,19,20)); ok(not SENT, "not yet"); st.tick(at(d2,19,31)); ok(len(SENT)==1 and "Pills" in SENT[0] and "20:00" in SENT[0], SENT)
st.tick(at(d2,19,40)); ok(len(SENT)==1, "once")
st.add({"title":"Missed","date":"2026-11-02","start":"21:00","remind":30}); st.tick(at(d2,23,0)); ok(len(SENT)==1, "too late for a reminder")
e=[x for x in st.between("2026-11-02","2026-11-02") if x["title"]=="Pills"][0]
st.update(e["id"],{"start":"21:30"}); st.tick(at(d2,21,5)); ok(len(SENT)==2, "moved event reminded again")
print("agenda OK")
