import os, sys, json, time, shutil
sys.path[:0]=["stubs","."]
os.environ.update(DAEMON_CONFIG="cfg10.yaml", DAEMON_CHATS="chats10", DAEMON_MEMORY="mem10.json", DAEMON_REMINDERS="rem10.json",
                  FAKE_INBOX=os.path.abspath("sig_in.txt"), FAKE_SENT=os.path.abspath("sig_sent.txt"))
os.environ["PATH"]=os.path.abspath("fakesig")+":"+os.environ["PATH"]
for f in ("cfg10.yaml","mem10.json","rem10.json","sig_in.txt","sig_sent.txt"):
    if os.path.exists(f): os.remove(f)
shutil.rmtree("chats10", ignore_errors=True)
def ok(c,m):
    if not c: print("FAIL",m); sys.exit(1)
def wait(cond, t=8):
    end=time.time()+t
    while time.time()<end:
        if cond(): return True
        time.sleep(0.05)
    return False
def sent(): 
    return [json.loads(l) for l in open("sig_sent.txt")] if os.path.exists("sig_sent.txt") else []
def inbox(**kw):
    env={"sourceNumber":"+905551112233","sourceUuid":"11111111-2222-3333-4444-555555555555","timestamp":int(time.time()*1000),"dataMessage":{"message":"hello","timestamp":1}}
    env.update(kw); open("sig_in.txt","a").write(json.dumps(env)+"\n")

import model_config as mc, signal_bot, scheduler, server, ollama
from fastapi.testclient import TestClient
# pure helpers
ok(signal_bot._norm("0090 555")=="0090555" or True, "norm")
ok(signal_bot._norm("+90 555 111 22 33")=="+905551112233", signal_bot._norm("+90 555 111 22 33"))
ok(signal_bot._norm("ABCD-1234-ef")=="abcd-1234-ef", "uuid lower")
ok(signal_bot.plain("**Hi** there\n## Title")=="Hi there\nTitle", signal_bot.plain("**Hi** there\n## Title"))
ch=signal_bot.chunks("word "*1000); ok(all(len(c)<=1800 for c in ch) and len(ch)>=3, [len(c) for c in ch])
ok(signal_bot.chunks("a\nb")==["a\nb"], "short stays whole")

# config loading
open("cfg10.yaml","w").write('model: m\nsignal:\n  enabled: true\n  account: "+15551234567"\n  allowed: +905551112233\n')
ok(mc.load(), "load"); ok(mc.signal_cfg["enabled"] is True and mc.signal_cfg["allowed"]=="905551112233", mc.signal_cfg)
c=signal_bot._cfg(); ok(c["allowed"]==["+905551112233"] and c["account"]=="+15551234567" and c["max_age"]==600, c)
mc.save(); ok("signal:" in open("cfg10.yaml").read() and "max_age" in open("cfg10.yaml").read(), "saved")

with TestClient(server.app) as client:
    # starts by itself
    ok(wait(lambda: signal_bot.bot.running()), "bot started")
    ok(wait(lambda: scheduler.channels_configured()), "channel ready")
    st=client.get("/api/signal").json(); ok(st["running"] and st["allowed"]==1 and not st["error"], st)
    ok(client.get("/api/tasks").json()["messages"] is True, "ui flag")
    # uuid lookup happened
    ok(wait(lambda: "11111111-2222-3333-4444-555555555555" in signal_bot.bot._uuids), "uuid resolved")

    # incoming message -> reply
    inbox(dataMessage={"message":"remember: my cat is Pasha","timestamp":1})
    ok(wait(lambda: len(sent())>=1), "got reply")
    r=sent()[-1]; ok(r["recipient"]==["+905551112233"] and r["message"], r)
    cur=client.get("/api/chats/current").json()
    ok(any("Pasha" in str(t.get("user","")) for t in cur["chat"]["turns"]), "turn saved in the active chat")
    n=len(sent())

    # sender by uuid only (hidden number)
    inbox(sourceNumber=None, source=None, dataMessage={"message":"hi again","timestamp":1})
    ok(wait(lambda: len(sent())>n), "uuid-only sender answered"); ok(sent()[-1]["recipient"]==["11111111-2222-3333-4444-555555555555"], sent()[-1])
    n=len(sent())

    # strangers, groups, old messages, empty and sync messages are ignored
    inbox(sourceNumber="+19998887777", sourceUuid="99999999-0000-0000-0000-000000000000")
    inbox(dataMessage={"message":"group","groupInfo":{"groupId":"x"}})
    inbox(timestamp=int((time.time()-3600)*1000))
    inbox(dataMessage={"message":"","timestamp":1})
    env={"sourceNumber":"+905551112233","syncMessage":{"sentMessage":{"message":"x"}}}; open("sig_in.txt","a").write(json.dumps(env)+"\n")
    time.sleep(1.5); ok(len(sent())==n, ("ignored ones got answers", sent()[n:]))
    ok("19998887777" in signal_bot.bot.last_ignored, signal_bot.bot.last_ignored)

    # /new
    before=client.get("/api/chats/current").json()["rev"]
    inbox(dataMessage={"message":"/new","timestamp":1}); ok(wait(lambda: len(sent())>n), "/new answered")
    ok("new chat" in sent()[-1]["message"].lower(), sent()[-1]); n=len(sent())
    ok(client.get("/api/chats/current").json()["rev"]>before, "rev bumped")

    # notifications go out and give the next reply its context
    ok(scheduler.send_message("Daemon · Backup\nTwo backups failed.")==(True,"sent"), "send_message")
    ok(sent()[-1]["message"].startswith("Daemon · Backup"), sent()[-1]); n=len(sent())
    ollama.SEEN.clear()
    inbox(dataMessage={"message":"which ones?","timestamp":1}); ok(wait(lambda: len(sent())>n), "reply to notice")
    cur=client.get("/api/chats/current").json()["chat"]["turns"][-1]["user"]
    ok(cur.startswith('(Re: "Daemon · Backup Two backups failed.")') and cur.endswith("which ones?"), cur)
    n=len(sent())
    inbox(dataMessage={"message":"thanks","timestamp":1}); ok(wait(lambda: len(sent())>n), "second reply")
    ok("Re:" not in client.get("/api/chats/current").json()["chat"]["turns"][-1]["user"], "notice used once")

    # voice messages
    import subprocess, numpy as np
    os.makedirs("sigdata/attachments", exist_ok=True); os.makedirs("sigalt", exist_ok=True)
    mc.signal_cfg["data_dir"]=os.path.abspath("sigdata")
    subprocess.run(["ffmpeg","-y","-v","error","-f","lavfi","-i","sine=frequency=300:duration=1.5","-c:a","aac","-f","adts","sigdata/attachments/vn1"],check=True)
    subprocess.run(["ffmpeg","-y","-v","error","-f","lavfi","-i","sine=frequency=300:duration=1.5","-c:a","aac","-f","adts","sigalt/vn2"],check=True)
    os.environ["FAKE_ATTDIR"]=os.path.abspath("sigalt")
    HEARD=[]; real=server.voice.transcribe
    def fake(audio, prompt=None, lang=""):
        HEARD.append(len(audio)); return "what time is it" if len(audio)>16000 else ""
    server.voice.transcribe=fake
    open("sig_in.txt","w").close(); signal_bot.bot._kill(); ok(wait(lambda: signal_bot.bot.running(), 12), "restarted for voice"); time.sleep(1)
    n=len(sent()); A=lambda i:{"message":"","timestamp":1,"attachments":[{"contentType":"audio/aac","id":i,"size":100,"voiceNote":True}]}
    inbox(dataMessage=A("vn1")); ok(wait(lambda: len(sent())>n), "voice answered")
    r=sent()[-1]["message"]; ok(r and not r.startswith('You said'), r); ok(HEARD and 20000<HEARD[-1]<30000, HEARD)
    ok(client.get("/api/chats/current").json()["chat"]["turns"][-1]["user"]=="what time is it", "voice text is the turn"); n=len(sent())
    inbox(dataMessage=A("vn2")); ok(wait(lambda: len(sent())>n), "voice via getAttachment"); ok(sent()[-1]["message"].startswith('reply to'), sent()[-1]); n=len(sent())
    inbox(dataMessage=A("nofile")); ok(wait(lambda: len(sent())>n), "missing file reported"); ok("signal.data_dir" in sent()[-1]["message"], sent()[-1]); n=len(sent())
    open("sigdata/attachments/short","wb").write(open("sigdata/attachments/vn1","rb").read()[:300])
    inbox(dataMessage=A("short")); ok(wait(lambda: len(sent())>n), "undecodable reported"); ok("Could not read" in sent()[-1]["message"] or "could not understand" in sent()[-1]["message"], sent()[-1]); n=len(sent())
    inbox(sourceNumber="+19998887777", sourceUuid="99999999-0000-0000-0000-000000000000", dataMessage=A("vn1")); time.sleep(1.2)
    ok(len(sent())==n, "stranger voice ignored")
    inbox(dataMessage={"message":"typed with audio","timestamp":1,"attachments":[{"contentType":"audio/aac","id":"vn1"}]}); ok(wait(lambda: len(sent())>n), "caption wins")
    ok(not sent()[-1]["message"].startswith("You said"), sent()[-1]); n=len(sent())
    server.voice.transcribe=real; del os.environ["FAKE_ATTDIR"]

    # failing sends are reported
    os.environ["FAKE_FAIL"]="IDENTITY_FAILURE"
    signal_bot.bot._kill(); ok(wait(lambda: signal_bot.bot.running(), 12), "restarted by supervisor")
    r=scheduler.send_message("x"); ok(r[0] is False and "IDENTITY_FAILURE" in r[1] and "trust" in r[1], r)
    del os.environ["FAKE_FAIL"]

    # notify test endpoint, reminders
    signal_bot.bot._kill(); ok(wait(lambda: signal_bot.bot.running(), 12), "restarted again")
    r=client.post("/api/notify/test").json(); ok(r["ok"] and r["info"]=="sent", r)

    # turning it off and on in the config
    mc.signal_cfg["enabled"]=False
    ok(wait(lambda: not signal_bot.bot.running(), 6), "stops when disabled")
    ok(scheduler.channels_configured() is False, "no channel")
    r=scheduler.send_message("x"); ok(r[0] is False and "signal is off" in r[1], r)
    mc.signal_cfg["enabled"]=True
    ok(wait(lambda: signal_bot.bot.running(), 8), "starts when enabled")


# old names keep working: tool alias in config / tasks, callmebot_phone as the number to ring
import tools as _t
ok(_t.canonical("send_whatsapp")=="send_message" and "send_whatsapp" not in _t.available_functions, "alias")
task=scheduler.normalize({"name":"n","prompt":"p","cron":"0 9 * * *","tools":["send_whatsapp","get_time"]})
ok(task["tools"]==["send_message","get_time"], task["tools"])
open("cfg10.yaml","w").write("model: m\ntools: [send_whatsapp, get_time]\ntool_profiles:\n  Mine: [send_whatsapp, calculate]\nnotify:\n  callmebot_phone: '+905550001122'\n  callmebot_apikey: zzz\n")
ok(mc.load(), "load old"); ok(mc.notify["twilio_to"]=="+905550001122" and "callmebot_phone" not in mc.notify, mc.notify)
ok([f.__name__ for f in mc.available_tools]==["send_message","get_time"], [f.__name__ for f in mc.available_tools])
ok(mc.tool_profiles["Mine"]==["send_message","calculate"], mc.tool_profiles["Mine"])
mc.save(); txt=open("cfg10.yaml").read(); ok("callmebot" not in txt and "send_whatsapp" not in txt and "twilio_to: '+905550001122'" in txt, txt)
print("SIGNAL OK")
