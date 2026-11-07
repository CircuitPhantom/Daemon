import os, sys, json, time, shutil, base64
sys.path[:0]=["stubs","."]
D=os.path.abspath("dmn31")
os.environ.update(DAEMON_CONFIG="cfg31.yaml", DAEMON_CHATS="chats31", DAEMON_MEMORY="mem31.json", DAEMON_REMINDERS="rem31.json",
                  DAEMON_INBOX=os.path.abspath("inbox31.json"), DAEMON_FILES=D,
                  FAKE_INBOX=os.path.abspath("sig_in.txt"), FAKE_SENT=os.path.abspath("sig_sent.txt"))
os.environ["PATH"]=os.path.abspath("fakesig")+":"+os.environ["PATH"]
for f in ("cfg31.yaml","mem31.json","rem31.json","sig_in.txt","sig_sent.txt","inbox31.json"):
    if os.path.exists(f): os.remove(f)
shutil.rmtree("chats31", ignore_errors=True); shutil.rmtree(D, ignore_errors=True)
os.makedirs(D+"/notes")
open(D+"/notes/shopping.txt","w").write("milk\neggs\n")
open("/tmp/secret31.txt","w").write("top secret")
def ok(c,m=""):
    if not c: print("FAIL",m); sys.exit(1)
def wait(cond, t=15):
    end=time.time()+t
    while time.time()<end:
        if cond(): return True
        time.sleep(0.05)
    return False
open("cfg31.yaml","w").write('model: qwen3:1.7b\ntools: [send_file, inbox_add, inbox_search, inbox_recent]\nuploads:\n  dir: %s/uploads\nsecurity:\n  confirm: false\nsignal:\n  enabled: true\n  account: "+15551234567"\n  allowed: +905551112233\n' % D)
import model_config as mc; ok(mc.load())
import inbox, tools, server, signal_bot, uploads, ollama
from fastapi.testclient import TestClient
# --- inbox core
a=inbox.add("Şarkı sözleri hakkında harika bir makale https://example.com/a #müzik fikir")
ok(a["kind"]=="link" and a["url"]=="https://example.com/a" and a["tags"]==["muzik"], a)
b=inbox.add("Robot kolu için fikir: servo yerine step motor kullan")
r=uploads.process("battery.txt", b"Lithium cells degrade faster when charged to 100 percent."); c=inbox.add("pil notu", [r])
ok(c["kind"]=="file" and "Lithium" in c["excerpt"], c)
ok([x["id"] for x in inbox.search("sarki makale")]==[a["id"]], inbox.search("sarki makale"))      # accents + both words
ok(inbox.search("makaleyi")[0]["id"]==a["id"], "prefix match")
ok(inbox.search("lithium degrade")[0]["id"]==c["id"], "file text found")
ok(inbox.search("battery")[0]["id"]==c["id"], "file name found")
ok(inbox.search("step motor")[0]["id"]==b["id"] and not inbox.search("nonexistentword"), "robot")
ok(inbox.search("makale robot")==[], "all words must match")
ok(len(inbox.items(tag="#muzik"))==1, "tag filter")
ok("Saved" in tools.inbox_add(text="call dentist friday", tags="todo"), "tool add")
ok("dentist" in tools.inbox_search(query="dentist") and "empty" not in tools.inbox_recent(count=3), "tool search")
ok(inbox.delete(inbox.items()[0]["id"]) and not inbox.delete("zzzz"), "delete")
ok({"inbox_add","inbox_search","send_file"} <= set(tools.available_functions) and tools.available_functions["send_file"].__doc__, "registered")
ok("inbox_search" in mc.DEFAULT_PROFILES["Read only"] and "send_file" not in mc.DEFAULT_PROFILES["Read only"] and "send_file" in mc.DEFAULT_PROFILES["Assistant"], "profiles")

def sent(): return [json.loads(l) for l in open("sig_sent.txt")] if os.path.exists("sig_sent.txt") else []
with TestClient(server.app) as client:
    ok(wait(lambda: signal_bot.bot.running()), "bot up")
    # --- inbox API
    g=client.get("/api/inbox").json(); ok(g["total"]>=3 and all("path" not in json.dumps(x) for x in g["items"]), g["total"])
    ok(len(client.get("/api/inbox?q=robot").json()["items"])==1, "api search")
    p=client.post("/api/inbox", json={"text":"from dashboard #web","files":[{"name":"n.txt","data":base64.b64encode(b"zebra facts").decode()}]}).json()
    ok(p["item"]["files"][0]["name"]=="n.txt" and p["item"]["tags"]==["web"], p)
    ok(client.get("/api/inbox?q=zebra").json()["items"][0]["id"]==p["item"]["id"], "uploaded file text searchable")
    ok(client.post("/api/inbox", json={"text":""}).status_code==400, "empty rejected")
    ok(client.delete("/api/inbox/"+p["item"]["id"]).status_code==200 and client.delete("/api/inbox/nope").status_code==404, "delete api")
    # --- Signal commands
    def inbox_msg(**dm):
        env={"sourceNumber":"+905551112233","timestamp":int(time.time()*1000),"dataMessage":dict({"timestamp":1},**dm)}
        open("sig_in.txt","a").write(json.dumps(env)+"\n")
    n=len(sent()); inbox_msg(message="/inbox buy a USB-C hub #shopping"); ok(wait(lambda: len(sent())>n, 30), ("reply", signal_bot.bot.last_ignored, signal_bot.bot.status(), open("sig_in.txt").read()[-300:]))
    ok("Saved to the inbox" in sent()[-1]["message"] and inbox.search("usb hub"), sent()[-1])
    n=len(sent()); inbox_msg(message="/find hub"); ok(wait(lambda: len(sent())>n)); ok("USB-C hub" in sent()[-1]["message"], sent()[-1])
    os.makedirs("sigdata/attachments", exist_ok=True); open("sigdata/attachments/ph1","wb").write(b"receipt total 42 lira")
    mc.signal_cfg["data_dir"]=os.path.abspath("sigdata")
    n=len(sent()); inbox_msg(message="/inbox receipt", attachments=[{"contentType":"text/plain","id":"ph1","filename":"receipt.txt"}]); ok(wait(lambda: len(sent())>n))
    ok(inbox.search("receipt lira")[0]["files"][0]["name"]=="receipt.txt", "signal file saved to inbox")
    n=len(sent()); inbox_msg(message="/inbox"); ok(wait(lambda: len(sent())>n)); ok("Latest in the inbox" in sent()[-1]["message"], sent()[-1])
    # --- model tools via chat
    def say(text):
        r=client.post("/api/say/stream", json={"text":text,"speak":False}); return [json.loads(l) for l in r.text.splitlines() if l.strip().startswith("{")]
    ev=say("inboxadd: remember to read about Kalman filters"); ok(inbox.search("kalman"), "model saved")
    # --- send_file: web chat -> card
    ev=say("sendfile:file=notes/shopping.txt"); f=[e for e in ev if e.get("type")=="files"]
    ok(f and f[0]["files"][0]["name"]=="shopping.txt" and f[0]["files"][0]["rel"]=="notes/shopping.txt", ev)
    g=client.get("/api/dl/notes/shopping.txt"); ok(g.status_code==200 and g.content==b"milk\neggs\n" and "attachment" in g.headers["content-disposition"], g.headers)
    turns=client.get("/api/chats/current").json()["chat"]["turns"]; ok(turns[-1]["out_files"][0]["name"]=="shopping.txt", turns[-1].keys())
    # --- send_file: where=phone -> Signal attachment with clean name
    n=len(sent()); ev=say("sendfile:file=notes/shopping.txt;where=phone"); ok(wait(lambda: len(sent())>n), "phone send")
    sp=sent()[-1]; ok(sp["attachment"] and sp["attachment"][0].endswith("/shopping.txt"), sp)
    ok(not os.path.exists(os.path.dirname(sp["attachment"][0])), "temp removed")
    # --- security: outside the folder is refused
    for bad in ("/tmp/secret31.txt","../secret31.txt","/etc/passwd","notes/../../secret31.txt","nope.txt"):
        out=tools.send_file(file=bad); ok(out.startswith("Error"), (bad,out))
    os.symlink("/tmp/secret31.txt", D+"/link.txt"); ok(tools.send_file(file="link.txt").startswith("Error"), "symlink escape")
    for bad in ("../secret31.txt","..%2Fsecret31.txt","%2e%2e/%2e%2e/etc/passwd","link.txt","/etc/passwd"):
        ok(client.get("/api/dl/"+bad).status_code==404, bad)
    # uploaded file can be sent too
    rel=uploads.process("memo.txt", b"hello")["rel"]; out=tools.send_file(file=os.path.join(D,"uploads",rel), where="phone"); ok("sent" in out, out)
    # outside a web turn it goes to Signal
    n=len(sent()); out=tools.send_file(file="notes/shopping.txt", caption="here"); ok("sent" in out and wait(lambda: len(sent())>n) and sent()[-1]["message"]=="here", out)
print("OK inbox")
