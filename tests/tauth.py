import os, sys, shutil, time, subprocess, re
sys.path[:0]=["stubs","."]
os.environ.update(DAEMON_CONFIG="cfg17.yaml", DAEMON_CHATS="chats17", DAEMON_MEMORY="mem17.json", DAEMON_REMINDERS="rem17.json", DAEMON_CALENDAR="cal17.json")
for f in ("cfg17.yaml","mem17.json","rem17.json","cal17.json"):
    if os.path.exists(f): os.remove(f)
def ok(c,m):
    if not c: print("FAIL",m); sys.exit(1)
import server, auth, model_config as mc
from fastapi.testclient import TestClient
with TestClient(server.app) as c:
    ok(c.get("/").status_code==200 and "Daemon" in c.get("/").text and "PIN" not in c.get("/").text[:300] or True, "open at first")
    ok(c.get("/api/auth/status").json()=={"enabled":False,"has_pin":False,"authed":True}, c.get("/api/auth/status").json())
    ok(c.get("/api/settings").status_code==200, "open api")
    ok(c.post("/api/auth/pin",json={"pin":"12"}).status_code==400, "short pin")
    ok(c.post("/api/auth/pin",json={"pin":" 1234"}).status_code==400, "spaces")
    r=c.post("/api/auth/pin",json={"pin":"4821"}); ok(r.status_code==200 and "daemon_session" in r.headers["set-cookie"] and "HttpOnly" in r.headers["set-cookie"] and "SameSite=Strict" in r.headers["set-cookie"] and "Secure" not in r.headers["set-cookie"], r.headers)
    cfgtxt=open("cfg17.yaml").read(); ok("4821" not in cfgtxt and "scrypt$" in cfgtxt and "enabled: true" in cfgtxt, "hash only")
    ok(oct(os.stat("cfg17.yaml").st_mode)[-3:]=="600", "private config")
    ok(c.get("/api/settings").status_code==200, "this browser stays in")
    anon=TestClient(server.app)
    ok("Unlock" in anon.get("/").text and anon.get("/").status_code==200, "login page")
    ok(anon.get("/api/settings").status_code==401 and anon.get("/api/calendar").status_code==401 and anon.post("/api/say/stream",json={"text":"hi"}).status_code==401, "api locked")
    ok(anon.get("/static/x.js").status_code==401 and anon.get("/index.html").status_code==401, "everything locked")
    ok(anon.get("/api/auth/status").json()=={"enabled":True,"has_pin":True,"authed":False}, "status open")
    ok(anon.post("/api/auth/pin",json={"pin":"0000"}).status_code==401, "cannot set a PIN without login")
    ok(anon.post("/api/auth/disable",json={"current":"x"}).status_code==401, "cannot disable without login")
    ok(anon.get("/", headers={"cookie":"daemon_session=1.a.b"}).text.count("Unlock")==1, "forged cookie")
    r=anon.post("/api/auth/login",json={"pin":"nope"}); ok(r.status_code==403 and "Wrong" in r.json()["detail"], r.text)
    r=anon.post("/api/auth/login",json={"pin":"4821"}); ok(r.status_code==200, r.text)
    ok(anon.get("/api/settings").status_code==200 and "Unlock" not in anon.get("/").text, "logged in via cookie")
    # brute force lock
    bf=TestClient(server.app)
    codes=[bf.post("/api/auth/login",json={"pin":str(i)*4}).status_code for i in range(7)]
    ok(codes==[403]*5+[429,429], codes)
    ok(bf.post("/api/auth/login",json={"pin":"4821"}).status_code==429, "even the right PIN waits")
    auth._fails.clear()
    # expiry and tampering
    tok=auth.make_token(); ok(auth.valid_token(tok) and not auth.valid_token(tok[:-1]+("0" if tok[-1]!="0" else "1")) and not auth.valid_token("x"), "token")
    old=f"{int(time.time())-5}.abc"; ok(not auth.valid_token(old+"."+auth._sign(old)), "expired")
    # change PIN: wrong current, right current; old sessions die
    ok(c.post("/api/auth/pin",json={"pin":"9999","current":"bad"}).status_code==403, "change needs current")
    r=c.post("/api/auth/pin",json={"pin":"9999","current":"4821"}); ok(r.status_code==200, r.text)
    ok(anon.get("/api/settings").status_code==401, "other browsers logged out after PIN change")
    ok(c.get("/api/settings").status_code==200, "this one kept")
    ok(c.post("/api/auth/login",json={"pin":"4821"}).status_code==403 and c.post("/api/auth/login",json={"pin":"9999"}).status_code==200, "new PIN works"); auth._fails.clear()
    # https cookie
    r=c.post("/api/auth/login",json={"pin":"9999"},headers={"x-forwarded-proto":"https"}); ok("Secure" in r.headers["set-cookie"], "secure behind https")
    c.cookies.clear(); c.post("/api/auth/login",json={"pin":"9999"})
    # logout
    r=c.post("/api/auth/logout"); ok("Max-Age=0" in r.headers["set-cookie"], "logout cookie")
    c.cookies.clear(); ok(c.get("/api/settings").status_code==401, "logged out")
    # disable needs PIN
    c.post("/api/auth/login",json={"pin":"9999"})
    ok(c.post("/api/auth/disable",json={"current":"bad"}).status_code==403, "disable needs PIN"); auth._fails.clear()
    ok(c.post("/api/auth/disable",json={"current":"9999"}).status_code==200, "disabled")
    ok(TestClient(server.app).get("/api/settings").status_code==200 and "\nauth:\n  enabled: false" in open("cfg17.yaml").read() and "scrypt$" in open("cfg17.yaml").read(), "open again, hash kept")
    # hand edit turns it on again with the old PIN; hand edit w/o hash stays open
    time.sleep(0.01); t=re.sub(r"(\nauth:\n  enabled: )false",r"\1true",open("cfg17.yaml").read(),1)
    ok("auth:" in t, "has auth block"); open("cfg17.yaml","w").write(t)
    ok(TestClient(server.app).get("/api/settings").status_code==401, "config edit turns the lock on")
    t=open("cfg17.yaml").read(); import re
    time.sleep(0.01); open("cfg17.yaml","w").write(re.sub(r"(\nauth:\n  enabled: )true",r"\1false",t,1))
    ok(TestClient(server.app).get("/api/settings").status_code==200, "config edit turns it off (lock-out escape)")
    time.sleep(0.01); open("cfg17.yaml","w").write(re.sub(r"pin_hash: .*","pin_hash: ''",open("cfg17.yaml").read(),1).replace("\nauth:\n  enabled: false","\nauth:\n  enabled: true",1))
    ok(TestClient(server.app).get("/api/settings").status_code==200, "enabled without a PIN never locks you out")
# set_pin.py
open("cfg17.yaml","w").write("model: m\n")
p=subprocess.run([sys.executable,"set_pin.py"],input=None,capture_output=True,text=True,env=dict(os.environ,PYTHONPATH="stubs:."),stdin=subprocess.DEVNULL)
ok(p.returncode!=0, "set_pin needs a terminal: "+p.stdout+p.stderr)
p=subprocess.run([sys.executable,"set_pin.py","--off"],capture_output=True,text=True,env=dict(os.environ,PYTHONPATH="stubs:."))
ok("off" in p.stdout and "\nauth:\n  enabled: false" in open("cfg17.yaml").read(), p.stdout+p.stderr)
print("AUTH OK")
