import os, sys, json, subprocess, struct, zlib, shutil
sys.path[:0]=["stubs","."]
D=os.path.abspath("dmn45")
os.environ.update(DAEMON_CONFIG="cfg45.yaml", DAEMON_CHATS="chats45", DAEMON_MEMORY="mem45.json", DAEMON_INBOX=os.path.abspath("inbox45.json"), DAEMON_FILES=D, DAEMON_JOBS=os.path.abspath("jobs45.json"))
for f in ("cfg45.yaml","mem45.json","inbox45.json","jobs45.json"):
    if os.path.exists(f): os.remove(f)
shutil.rmtree("chats45", ignore_errors=True)
def ok(c,m=""):
    if not c: print("FAIL",m); sys.exit(1)
import model_config as mc; ok(mc.load())
import ollama, pwa, server, auth, inbox
from fastapi.testclient import TestClient

# the service worker, run in node
open("sw45.js","w").write(pwa.SW)
r=subprocess.run(["node","tpwa_sw.js","sw45.js"],capture_output=True,text=True); ok("SW OK" in r.stdout, r.stdout+r.stderr)

m=pwa.manifest(); st=m["share_target"]
ok(m["display"]=="standalone" and m["start_url"]=="/" and st["action"]=="/share" and st["method"]=="POST" and st["enctype"]=="multipart/form-data", m)
ok(st["params"]["files"][0]["name"]=="files" and st["params"]["text"]=="text" and st["params"]["url"]=="url", st)
ok({i["sizes"] for i in m["icons"]}=={"192x192","512x512"}, m["icons"])
def png_ok(b, size):
    ok(b[:8]==b"\x89PNG\r\n\x1a\n", "signature")
    w,h=struct.unpack(">II", b[16:24]); ok((w,h)==(size,size), (w,h))
    idat=b[b.index(b"IDAT")+4:b.index(b"IEND")-8]; raw=zlib.decompress(idat); ok(len(raw)==size*(size*3+1), len(raw))
png_ok(pwa.icon_png(192),192); png_ok(pwa.icon_png(512),512); png_ok(pwa.icon_png(100),192)

with TestClient(server.app) as c:
    r=c.get("/manifest.webmanifest"); ok(r.status_code==200 and r.headers["content-type"].startswith("application/manifest+json") and r.json()["share_target"], r.headers)
    r=c.get("/sw.js"); ok(r.status_code==200 and "javascript" in r.headers["content-type"] and "handleShare" in r.text and r.headers["service-worker-allowed"]=="/", r.headers)
    for s in (192,512):
        r=c.get(f"/icon-{s}.png"); ok(r.status_code==200 and r.headers["content-type"]=="image/png" and len(r.content)>500, s)
    html=c.get("/").text; ok('rel="manifest" href="/manifest.webmanifest"' in html and "serviceWorker.register('/sw.js')" in html and "shared=" in html, "page links")
    r=c.post("/share", data={"text":"x"}); ok(r.status_code==200 and "Open Daemon" in r.text, "fallback page when the worker is not active")
    # with the PIN lock on, the app files stay reachable but data does not
    auth.set_pin("1234"); ok(auth.active())
    ok(c.get("/manifest.webmanifest").status_code==200 and c.get("/sw.js").status_code==200 and c.get("/icon-192.png").status_code==200, "open paths")
    ok(c.get("/api/inbox").status_code==401, "locked")
    r=c.post("/share", data={"text":"x"}); ok(r.status_code==401 and "enter the PIN" in r.text, (r.status_code, r.text))
    r=c.post("/api/auth/login", json={"pin":"1234"}); ok(r.status_code==200, r.text)
    r=c.post("/api/inbox", json={"text":"https://a.example/x read this\nT","files":[{"name":"p.txt","data":"aGVsbG8="}],"tags":["shared"]}); ok(r.status_code==200 and "shared" in r.json()["item"]["tags"] and r.json()["item"]["files"], r.text)
    auth.disable()
    # the token endpoint for Shortcuts and scripts
    mc.satellite.update(enabled=True, token="t"*40)
    ok(c.post("/api/sat/inbox", json={"text":"hi"}).status_code==401, "needs the token")
    r=c.post("/api/sat/inbox", json={"text":"from a shortcut #ios","tags":["a"]}, headers={"Authorization":"Bearer "+"t"*40}); ok(r.status_code==200 and r.json()["id"], r.text)
    it=[x for x in inbox.items(10) if x["id"]==r.json()["id"]][0]; ok(it["src"]=="shortcut" and set(it["tags"])=={"a","ios"}, it)
    ok(c.post("/api/sat/inbox", json={"text":"  "}, headers={"Authorization":"Bearer "+"t"*40}).status_code==400, "empty")
print("PWA OK")
