import os, sys, json, threading, urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path[:0]=["stubs","."]
os.environ.update(DAEMON_CONFIG="cfg20.yaml")
def ok(c,m=""):
    if not c: print("FAIL",m); sys.exit(1)
QUEUE=[]; SEARCH=[]; IGN=[]; MODE=["ok"]; CALLS=[]; ACTIVE=["d1"]; FAILS=[0]; NOW={}
DEVS=[{"id":"d1","name":"Arch laptop","type":"Computer","is_active":True},
      {"id":"d2","name":"Poyraz's iPhone","type":"Smartphone","is_active":False},
      {"id":"d3","name":"Kitchen Speaker","type":"Speaker","is_active":False}]
class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def _j(self,code,obj=None):
        self.send_response(code); self.end_headers()
        if obj is not None: self.wfile.write(json.dumps(obj).encode())
    def body(self):
        n=int(self.headers.get("content-length",0)); return self.rfile.read(n).decode()
    def do_POST(self):
        self.body(); u=urllib.parse.urlparse(self.path); q=urllib.parse.parse_qs(u.query)
        if u.path=="/v1/me/player/queue": QUEUE.append(q["uri"][0]); CALLS.append(("POST",u.path,None,self.headers.get("authorization"))); return self._j(204)
        if u.path=="/v1/me/player/next":
            CALLS.append(("POST",u.path,None,self.headers.get("authorization")))
            if QUEUE and MODE[0]!="ignore": NOW.clear(); NOW.update(dev=q["device_id"][0], uri=QUEUE.pop(0), ctx=None)
            return self._j(204)
        self._j(200,{"access_token":"U1","expires_in":3600})
    def do_GET(self):
        u=urllib.parse.urlparse(self.path); CALLS.append(("GET",u.path,None,self.headers.get("authorization")))
        if MODE[0]=="scope": return self._j(403,{"error":{"status":403,"message":"Insufficient client scope"}})
        for x in DEVS: x["is_active"]=(x["id"]==ACTIVE[0])
        if u.path=="/v1/me/player/devices": return self._j(200,{"devices":[] if MODE[0]=="none" else DEVS})
        if u.path=="/v1/search":
            q=urllib.parse.parse_qs(u.query); SEARCH.append((q,self.headers.get("authorization")))
            return self._j(200,{"tracks":{"items":[{"name":"505 (blocked)","uri":"spotify:track:BAD","is_playable":False,"artists":[{"name":"AM"}]},{"name":"505","uri":"spotify:track:GOOD","is_playable":True,"artists":[{"name":"Arctic Monkeys"}]}]}})
        if u.path.startswith("/v1/tracks/"): return self._j(200,{"album":{"uri":"spotify:album:ALB"}})
        if u.path=="/v1/me": return self._j(200,{"id":"user42"})
        if u.path=="/v1/me/player":
            if not NOW: return self._j(204)
            return self._j(200,{"is_playing":True,"device":{"id":NOW["dev"],"name":"x"},"item":{"uri":NOW.get("uri",""),"name":"Song"},"context":{"uri":NOW["ctx"]} if NOW.get("ctx") else None})
        self._j(404,{})
    def do_PUT(self):
        b=self.body(); u=urllib.parse.urlparse(self.path); CALLS.append(("PUT",u.path+("?"+u.query if u.query else ""),json.loads(b) if b else None,self.headers.get("authorization")))
        if MODE[0]=="premium": return self._j(403,{"error":{"status":403,"message":"Player command failed: Premium required","reason":"PREMIUM_REQUIRED"}})
        if u.path=="/v1/me/player" and b: ACTIVE[0]=json.loads(b)["device_ids"][0]
        if u.path=="/v1/me/player/play" and FAILS[0]>0: FAILS[0]-=1; return self._j(404,{"error":{"status":404,"message":"Device not found","reason":"NO_ACTIVE_DEVICE"}})
        if u.path=="/v1/me/player/play":
            CALLS[-1]=CALLS[-1]+(ACTIVE[0],)
            if MODE[0] not in ("ignore","queue_only") and not (MODE[0]=="ignore_first" and not IGN):
                q=urllib.parse.parse_qs(u.query); bd=json.loads(b)
                if not (MODE[0]=="album_only" and "uris" in bd):          # the phone ignores {"uris": [...]}
                    NOW.clear(); NOW.update(dev=q["device_id"][0], uri=(bd.get("uris") or [(bd.get("offset") or {}).get("uri","")])[0], ctx=bd.get("context_uri"))
            if MODE[0]=="ignore_first": IGN.append(1)
        if MODE[0]=="gone": return self._j(404,{"error":{"status":404,"message":"Device not found","reason":"NO_ACTIVE_DEVICE"}})
        self._j(204)
srv=HTTPServer(("127.0.0.1",8793),H); threading.Thread(target=srv.serve_forever,daemon=True).start()
import tools as T
T.SPOTIFY_TOKEN_URL="http://127.0.0.1:8793/token"; T.SPOTIFY_API="http://127.0.0.1:8793/v1"
open("sp_tok20.json","w").write(json.dumps({"refresh_token":"R1"}))
CFG={"client_id":"id","client_secret":"sec","aliases":{"liked songs":"spotify:collection:tracks"},"token_file":os.path.abspath("sp_tok20.json")}
T.hooks["spotify"]=lambda: CFG
T.hooks["app_aliases"]=lambda: {}
LP=lambda: [c for c in CALLS if c[0]=="PUT"][-1]
# list
r=T.spotify_devices(); ok("Arch laptop (Computer), playing now" in r and "Kitchen Speaker (Speaker)" in r, r)
ok(CALLS[-1][3]=="Bearer U1", "user token used")
# matching
D=T._spotify_devices(CFG)
for said,want in (("my phone","d2"),("iphone","d2"),("telefon","d2"),("kitchen speaker","d3"),("mutfak hoparlör","d3"),("laptop","d1"),("Arch Laptop","d1"),("speaker","d3")):
    m=T._match_device(D,said); ok(m and m["id"]==want, (said,m))
ok(T._match_device(D,"garage tv") is None, "no wrong guess")
# transfer
CALLS.clear(); r=T.spotify_transfer("my phone"); ok(r=="Playback moved to Poyraz's iPhone", r)
ok(("PUT","/v1/me/player",{"device_ids":["d2"],"play":True},"Bearer U1") in CALLS, CALLS)
CALLS.clear(); r=T.spotify_transfer("kitchen speaker", False); ok("paused" in r and CALLS[-1][2]=={"device_ids":["d3"],"play":False}, (r,CALLS))
ok(T.spotify_transfer("garage tv").startswith("Error: no device like 'garage tv'. Available: Arch laptop"), T.spotify_transfer("garage tv"))
# play on a device
CALLS.clear(); r=T.spotify_play("https://open.spotify.com/track/AAA?si=1", "track", "phone"); ok(r=="Playing https://open.spotify.com/track/AAA?si=1 on Poyraz's iPhone", r)
ok(("PUT","/v1/me/player/play?device_id=d2",{"context_uri":"spotify:album:ALB","offset":{"uri":"spotify:track:AAA"}},"Bearer U1") in [c[:4] for c in CALLS], CALLS)
CALLS.clear(); T.spotify_play("https://open.spotify.com/playlist/PL1","playlist","kitchen speaker"); ok(LP()[2]=={"context_uri":"spotify:playlist:PL1"} and "device_id=d3" in LP()[1], CALLS)
CALLS.clear(); T.spotify_play("Liked Songs","track","phone"); ok(LP()[2]=={"context_uri":"spotify:user:user42:collection"}, CALLS)
# a sleeping device is woken first (transfer, then play), and a play that fails twice while it wakes up is retried
ACTIVE[0]="d1"; CALLS.clear(); FAILS[0]=2; t0=__import__("time").time()
r=T.spotify_play("https://open.spotify.com/track/BBB","track","phone"); ok(r.endswith("on Poyraz's iPhone"), r)
kinds=[(c[0],c[1].split("?")[0]) for c in CALLS if c[0]=="PUT"]
ok(kinds[0]==("PUT","/v1/me/player") and kinds.count(("PUT","/v1/me/player/play"))==3, kinds)         # 2 failures + 1 success
ok([c for c in CALLS if c[0]=="PUT"][0][2]=={"device_ids":["d2"],"play":False}, CALLS)
ok(LP()[-1]=="d2", "device was active when the song started")
# an already active device gets the play command directly
ACTIVE[0]="d2"; CALLS.clear(); T.spotify_play("https://open.spotify.com/track/CCC","track","phone")
ok([c[1].split("?")[0] for c in CALLS if c[0]=="PUT"]==["/v1/me/player/play"], CALLS)
ACTIVE[0]="d1"
# Spotify answers 204 but the phone ignores the command: one more try, then an honest error
MODE[0]="ignore_first"; IGN.clear(); NOW.clear(); ACTIVE[0]="d2"; CALLS.clear()
r=T.spotify_play("https://open.spotify.com/track/DDD","track","phone"); ok(r.endswith("Poyraz's iPhone") and NOW["uri"]=="spotify:track:DDD", r)
ok(len([c for c in CALLS if c[0]=="PUT" and "/play" in c[1]])==2, "sent twice (album+offset ignored once, then the plain uris form)")
MODE[0]="ignore"; NOW.clear(); NOW.update(dev="d1", uri="spotify:track:OLD")
r=T.spotify_play("https://open.spotify.com/track/EEE","track","phone"); ok(r.startswith("Error: Spotify accepted the command but Poyraz's iPhone did not start it (now: Song on x"), r)
MODE[0]="ok"; NOW.clear(); ACTIVE[0]="d1"
# search with your own login: your market, and a version that is playable there
SEARCH.clear(); r=T.spotify_play("505","track","phone"); ACTIVE[0]="d1"; NOW.clear()
ok(SEARCH and SEARCH[-1][0]["market"]==["from_token"] and SEARCH[-1][1]=="Bearer U1", SEARCH)
ok("Playing 505 by Arctic Monkeys" in r, r)
# the phone ignores "play" but obeys "queue + next"
MODE[0]="queue_only"; NOW.clear(); QUEUE.clear(); ACTIVE[0]="d2"
r=T.spotify_play("https://open.spotify.com/track/QQQ","track","phone"); ok(r.endswith("Poyraz's iPhone") and NOW.get("uri")=="spotify:track:QQQ", (r,NOW))
MODE[0]="ok"; NOW.clear(); ACTIVE[0]="d1"
# the real Mi A3: ignores {"uris"}, obeys "album + offset"; and an already playing phone gets switched to the new song
MODE[0]="album_only"; NOW.clear(); NOW.update(dev="d2", uri="spotify:track:OLD"); ACTIVE[0]="d2"; CALLS.clear()
r=T.spotify_play("https://open.spotify.com/track/NEW","track","phone"); ok(r.endswith("Poyraz's iPhone") and NOW["uri"]=="spotify:track:NEW", (r,NOW))
ok(len([c for c in CALLS if c[0]=="PUT" and "/play" in c[1]])==1, "first try was enough")
MODE[0]="ok"; NOW.clear(); ACTIVE[0]="d1"
# errors are readable
MODE[0]="premium"; r=T.spotify_transfer("phone"); ok("Premium" in r, r)
MODE[0]="gone"; r=T.spotify_play("https://open.spotify.com/track/AAA","track","phone"); ok(r.startswith("Error") and "not available" in r, r)
MODE[0]="scope"; r=T.spotify_devices(); ok("spotify_login.py again" in r, r)
MODE[0]="none"; r=T.spotify_devices(); ok("No Spotify device is online" in r, r)
r=T.spotify_transfer("phone"); ok(r.startswith("Error: no Spotify device is online"), r)
MODE[0]="ok"
# no login yet
CFG["token_file"]=os.path.abspath("nothere.json"); T._sp_user.update(value="",exp=0)
r=T.spotify_devices(); ok("spotify_login.py" in r and "Premium" in r, r)
CFG.update(client_id="",client_secret=""); r=T.spotify_devices(); ok("client_id" in r, r)
# schema for the model
import inspect
for fn in (T.spotify_devices,T.spotify_transfer,T.spotify_play): ok(fn.__doc__ and "Args" in fn.__doc__ or fn is T.spotify_devices, fn.__name__)
ok({"spotify_devices","spotify_transfer"}<=set(T.available_functions), "registered")
import spotify_login; ok("user-modify-playback-state" in spotify_login.SCOPE and "playlist-read-private" in spotify_login.SCOPE, "scope")
print("SPOTIFY DEVICES OK")
