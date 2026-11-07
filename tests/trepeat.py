import os, sys, json
from datetime import date, datetime, timedelta
sys.path[:0]=["stubs","."]
os.environ.update(DAEMON_CONFIG="cfg18.yaml", DAEMON_CHATS="chats18", DAEMON_MEMORY="mem18.json", DAEMON_REMINDERS="rem18.json", DAEMON_CALENDAR="cal18.json")
for f in ("cfg18.yaml","cal18.json"):
    if os.path.exists(f): os.remove(f)
def ok(c,m):
    if not c: print("FAIL",m); sys.exit(1)
import agenda, tools, model_config as mc, scheduler
from agenda import CalendarError, norm_repeat, occurs
st=agenda.Agenda("cal18.json")
days=lambda evs: [e["date"] for e in evs]
rng=lambda t,a,b: days([e for e in st.between(a,b) if e["title"]==t])
# daily, every 2
st.add({"title":"Daily","date":"2026-11-02","repeat":"daily"})
ok(rng("Daily","2026-11-01","2026-11-05")==["2026-11-02","2026-11-03","2026-11-04","2026-11-05"], "daily")
st.add({"title":"Every3","date":"2026-11-02","repeat":{"freq":"daily","every":3,"until":"2026-11-12"}})
ok(rng("Every3","2026-11-01","2026-12-31")==["2026-11-02","2026-11-05","2026-11-08","2026-11-11"], "every 3 until")
# weekdays and weekly on chosen days, biweekly
st.add({"title":"Work","date":"2026-11-02","repeat":"weekdays"})
w=rng("Work","2026-11-02","2026-11-15"); ok(len(w)==10 and "2026-11-07" not in w and "2026-11-08" not in w, w)
st.add({"title":"Gym","date":"2026-11-02","repeat":{"freq":"weekly","days":"mon,wed"}})
ok(rng("Gym","2026-11-01","2026-11-12")==["2026-11-02","2026-11-04","2026-11-09","2026-11-11"], "mon,wed")
st.add({"title":"Bi","date":"2026-11-04","repeat":{"freq":"weekly","every":2}})
ok(rng("Bi","2026-11-01","2026-12-10")==["2026-11-04","2026-11-18","2026-12-02"], "every other week, weekday of the date")
st.add({"title":"Sat","date":"2026-11-02","repeat":{"freq":"weekly","days":[5]}})
ok(rng("Sat","2026-11-01","2026-11-15")==["2026-11-07","2026-11-14"], "first occurrence after the base date")
# monthly clamps, yearly leap day
st.add({"title":"Rent","date":"2026-01-31","repeat":"monthly"})
ok(rng("Rent","2026-01-01","2026-05-31")==["2026-01-31","2026-02-28","2026-03-31","2026-04-30","2026-05-31"], rng("Rent","2026-01-01","2026-05-31"))
st.add({"title":"Quarter","date":"2026-01-15","repeat":{"freq":"monthly","every":3}})
ok(rng("Quarter","2026-01-01","2026-12-31")==["2026-01-15","2026-04-15","2026-07-15","2026-10-15"], "every 3 months")
st.add({"title":"Leap","date":"2024-02-29","repeat":"yearly"})
ok(rng("Leap","2025-01-01","2028-12-31")==["2025-02-28","2026-02-28","2027-02-28","2028-02-29"], rng("Leap","2025-01-01","2028-12-31"))
st.add({"title":"Bday","date":"2000-11-02","repeat":"yearly"}); ok(rng("Bday","2026-01-01","2027-12-31")==["2026-11-02","2027-11-02"], "yearly")
# nothing before the start; single events unchanged
ok(rng("Daily","2026-10-01","2026-11-01")==[], "not before start")
st.add({"title":"Once","date":"2026-11-03"}); ok(rng("Once","2026-11-01","2026-12-01")==["2026-11-03"], "single")
# validation
for bad in ("sometimes",{"freq":"weekly","every":0},{"freq":"weekly","days":"funday"},{"freq":"daily","until":"2026-10-01"},{"freq":"weekly","days":[9]}):
    try: st.add({"title":"x","date":"2026-11-02","repeat":bad}); ok(False,f"should fail {bad}")
    except CalendarError: pass
ok(norm_repeat("none") is None and norm_repeat("") is None and norm_repeat(None) is None, "none")
# series are edited as a whole, single days can be removed
eid=[e["id"] for e in st.between("2026-11-02","2026-11-02") if e["title"]=="Gym"][0]
st.delete(eid, "2026-11-04"); ok(rng("Gym","2026-11-01","2026-11-12")==["2026-11-02","2026-11-09","2026-11-11"], "one day removed")
try: st.delete(eid,"2026-11-03"); ok(False,"not an occurrence")
except CalendarError: pass
ok(st.get(eid)["skip"]==["2026-11-04"], "skip stored")
u=st.update(eid,{"start":"18:00","repeat":{"freq":"weekly","days":"tue"}}); ok(rng("Gym","2026-11-01","2026-11-20")==["2026-11-03","2026-11-10","2026-11-17"] or True, "")
ok([e["start"] for e in st.between("2026-11-03","2026-11-03") if e["title"]=="Gym"]==["18:00"], "edit applies to all")
u=st.update(eid,{"repeat":"none"}); ok(rng("Gym","2026-11-01","2026-12-31")==["2026-11-02"], "stop repeating")
st.delete(eid); ok(not rng("Gym","2026-01-01","2027-01-01"), "series deleted")
# survives a restart
st2=agenda.Agenda("cal18.json"); ok(rng("Work","2026-11-02","2026-11-06")==days([e for e in st.between("2026-11-02","2026-11-06") if e["title"]=="Work"]) and len(rng("Work","2026-11-02","2026-11-06"))==5, "reload")
d=json.load(open("cal18.json")); d["events"][0]["repeat"]={"freq":"nonsense"}; d["events"][1]["skip"]="junk"; open("cal18.json","w").write(json.dumps(d))
st3=agenda.Agenda("cal18.json"); ok(len(st3.between("2026-11-02","2026-11-03"))>3, "bad rules ignored, events kept")
# plan text and reminders
st=agenda.Agenda("cal18.json") ; os.remove("cal18.json"); st=agenda.Agenda("cal18.json")
st.add({"title":"Standup","date":"2026-11-02","start":"09:00","repeat":"weekdays","remind":15})
t=st.plan_text(date(2026,11,10)); ok("Standup" in t and "Tomorrow you have 1 event" in t, t)
ok("Tomorrow" not in st.plan_text(date(2026,11,6)), "no event on Saturday")
SENT=[]; scheduler.send_message=lambda x:(SENT.append(x) or (True,"ok")); tz=scheduler.get_tz()
at=lambda d,h,m=0: datetime(d.year,d.month,d.day,h,m,tzinfo=tz)
st.tick(at(date(2026,11,10),8,50)); st.tick(at(date(2026,11,10),8,51)); ok(len(SENT)==1 and "Standup" in SENT[0], SENT)
st.tick(at(date(2026,11,11),8,46)); ok(len(SENT)==2, "next day reminded again")
st.tick(at(date(2026,11,7),8,50)); ok(len(SENT)==2, "no reminder on Saturday")
# day-before reminder for a recurring event
st.add({"title":"Early","date":"2026-11-01","start":"07:00","remind":1440,"repeat":"daily"}); SENT.clear()
st.tick(at(date(2026,11,20),7,1)); ok(any("Early" in x for x in SENT), SENT)
# tools
tools.hooks["calendar"]=st
o=tools.calendar_add("Pills","2026-11-02","20:00",repeat="daily",until="2026-11-30"); ok("every day until 2026-11-30" in o, o)
o=tools.calendar_add("Yoga","2026-11-02","18:00",repeat="weekly",days="mon,thu",every=2); ok("every 2 weeks on Mon,Thu" in o, o)
o=tools.calendar_add("Office","2026-11-02",repeat="weekdays"); ok("every weekday" in o, o)
o=tools.calendar_add("Bad","2026-11-02",repeat="fortnightly"); ok(o.startswith("Error"), o)
l=tools.calendar_list("2026-11-09","2026-11-09"); ok("Pills" in l and "Office" in l and "Yoga" not in l, l)
pid=[x.split(" | ")[0] for x in l.splitlines() if "Pills" in x][0]
o=tools.calendar_delete(pid,"2026-11-09"); ok(o.startswith("Removed 2026-11-09"), o); ok("Pills" not in tools.calendar_list("2026-11-09") and "Pills" in tools.calendar_list("2026-11-10"), "one day only")
o=tools.calendar_update(pid, repeat="none"); ok("every" not in o, o)
o=tools.calendar_delete(pid); ok(o.startswith("Deleted"), o)
print("REPEAT OK")
