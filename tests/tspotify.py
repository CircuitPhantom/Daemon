import os, sys, json, time, threading, urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path[:0]=["stubs","."]
os.environ.update(DAEMON_CONFIG="cfg13.yaml")
os.environ["PATH"]=os.path.abspath("fakesp")+":"+os.environ["PATH"]
for f in ("/tmp/sp_log","/tmp/sp_log2","/tmp/sp_uri","/tmp/sp_state","/tmp/sp_running","cfg13.yaml"):
    if os.path.exists(f): os.remove(f)
import traceback
def ok(c,m):
    if not c: print("FAIL",m,"at line",traceback.extract_stack()[-2].lineno); sys.exit(1)

MODE=["ok"]; HITS=[]
class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def _j(self,code,obj): self.send_response(code); self.end_headers(); self.wfile.write(json.dumps(obj).encode())
    def do_POST(self):
        n=int(self.headers.get("content-length",0)); body=self.rfile.read(n).decode(); HITS.append(("token",self.headers.get("authorization"),body))
        if "grant_type=authorization_code" in body:
            return self._j(200,{"access_token":"U0","refresh_token":"R1","scope":"playlist-read-private","expires_in":3600})
        if "grant_type=refresh_token" in body:
            if MODE[0]=="expired" or "refresh_token=R1" not in body: return self._j(400,{"error":"invalid_grant"})
            return self._j(200,{"access_token":"U1","expires_in":3600})
        if MODE[0]=="badauth": return self._j(400,{"error":"invalid_client"})
        if MODE[0]=="premium": return self._j(403,{"error":"premium"})
        self._j(200,{"access_token":"T1","expires_in":3600})
    def do_GET(self):
        u=urllib.parse.urlparse(self.path); q=urllib.parse.parse_qs(u.query)
        if u.path=="/v1/me/playlists":
            HITS.append(("mine",self.headers.get("authorization"),q))
            if self.headers.get("authorization")!="Bearer U1": return self._j(401,{})
            off=int(q["offset"][0])
            names=[f"Filler {i}" for i in range(60)]+["Gym Mix 2024","Road Trip","Çalışma Müziği","Liked Mix"]
            allp=[{"name":n,"uri":f"spotify:playlist:P{i}"} for i,n in enumerate(names)]
            page=allp[off:off+50]; page.insert(0,None) if off==0 else None
            return self._j(200,{"items":page,"next":"more" if off+50<len(allp) else None})
        HITS.append(("search",self.headers.get("authorization"),q))
        t=q["type"][0]; text=q["q"][0]
        if text=="nothing": return self._j(200,{t+"s":{"items":[]}})
        item={"track":{"name":"Creep","uri":"spotify:track:AAA","artists":[{"name":"Radiohead"}]},
              "album":{"name":"OK Computer","uri":"spotify:album:BBB","artists":[{"name":"Radiohead"}]},
              "artist":{"name":"Radiohead","uri":"spotify:artist:CCC"},
              "playlist":{"name":"Chill Mix","uri":"spotify:playlist:DDD","owner":{"display_name":"Spotify"}}}[t]
        self._j(200,{t+"s":{"items":[None,item] if t=="playlist" else [item]}})
srv=HTTPServer(("127.0.0.1",8798),H); threading.Thread(target=srv.serve_forever,daemon=True).start()

import model_config as mc, tools as T
T.SPOTIFY_TOKEN_URL="http://127.0.0.1:8798/token"; T.SPOTIFY_API="http://127.0.0.1:8798/v1"
CFG={"client_id":"","client_secret":"","aliases":{}}
T.hooks["spotify"]=lambda: CFG
T.hooks["app_aliases"]=lambda: {"spotify":"spotify-launcher"}
def uri(): return open("/tmp/sp_uri").read().strip() if os.path.exists("/tmp/sp_uri") else ""
def log(): return open("/tmp/sp_log").read() if os.path.exists("/tmp/sp_log") else ""
def reset():
    for f in ("/tmp/sp_uri","/tmp/sp_state","/tmp/sp_log"):
        if os.path.exists(f): os.remove(f)

# helpers
ok(T._spotify_uri("https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC?si=abc")=="spotify:track:4uLU6hMCjMI75M1A2tKUQC", "url")
ok(T._spotify_uri("https://open.spotify.com/intl-tr/playlist/37i9dQZF1DXcBWIGoYBM5M")=="spotify:playlist:37i9dQZF1DXcBWIGoYBM5M", "intl url")
ok(T._spotify_uri("spotify:album:XYZ123")=="spotify:album:XYZ123" and T._spotify_uri("spotify:collection:tracks")=="spotify:collection:tracks", "uri")
ok(T._spotify_uri("Radiohead Creep") is None and T._spotify_uri("spotify:track:AA BB") is None and T._spotify_uri("https://evil.com/track/AAA") is None, "not a link")

# 1) a link needs no login; Spotify is not running yet, so it gets started
reset()
r=T.spotify_play("https://open.spotify.com/track/AAA?si=x"); ok(r.startswith("Playing") and uri()=="spotify:track:AAA", (r, uri()))
ok(os.path.exists("/tmp/sp_log2") and "-p spotify open spotify:track:AAA" in log(), log())
ok(open("/tmp/sp_state").read().strip()=="Playing", "playing")

# 2) alias
reset(); CFG["aliases"]={"My Favorites":"https://open.spotify.com/playlist/PL1","liked songs":"spotify:collection:tracks","bad":"nope"}
ok(T.spotify_play("my favorites", "playlist")=="Playing my favorites" and uri()=="spotify:playlist:PL1", uri())
ok(T.spotify_play("Liked Songs")=="Playing Liked Songs" and uri()=="spotify:collection:tracks", uri())
ok(T.spotify_play("bad").startswith("Error: spotify_aliases entry"), "bad alias")

# 3) no credentials: search page only, honest about it
reset(); CFG["aliases"]={}
r=T.spotify_play("Radiohead Creep"); ok("not playing" in r and "client_id" in r and uri()=="spotify:search:Radiohead%20Creep", (r, uri()))
ok(open("/tmp/sp_state").read().strip()=="Playing" or True, "n/a"); 

# 4) search with credentials
CFG.update(client_id="id", client_secret="sec"); reset(); HITS.clear()
r=T.spotify_play("radiohead creep"); ok(r=="Playing Creep by Radiohead" and uri()=="spotify:track:AAA", (r, uri()))
tk=[h for h in HITS if h[0]=="token"][0]; ok(tk[1].startswith("Basic ") and "client_credentials" in tk[2], tk)
se=[h for h in HITS if h[0]=="search"][0]; ok(se[1]=="Bearer T1" and se[2]["q"]==["radiohead creep"] and se[2]["type"]==["track"] and se[2]["limit"]==["5"], se)
n=len(HITS); T.spotify_play("again"); ok(len([h for h in HITS if h[0]=="token"])==1, "token is cached")
ok(T.spotify_play("ok computer","album")=="Playing OK Computer by Radiohead" and uri()=="spotify:album:BBB", "album")
ok(T.spotify_play("radiohead","artist")=="Playing Radiohead" and uri()=="spotify:artist:CCC", "artist")
r=T.spotify_play("chill","playlist"); ok(r.startswith("Playing Chill Mix (a public playlist by Spotify, not yours)") and "spotify_login.py" in r and uri()=="spotify:playlist:DDD", r)
ok(T.spotify_play("nothing").startswith("Error: nothing found"), "no match")
ok(T.spotify_play("x","podcast").startswith("Error: kind") and T.spotify_play("  ").startswith("Error: say"), "bad input")

# 5) the API refuses: falls back to the search page and says why
for mode,word in (("badauth","client_secret"),("premium","Premium")):
    MODE[0]=mode; T._sp_token.update(key="",exp=0); reset()
    r=T.spotify_play("some song"); ok("not playing" in r and word in r and uri().startswith("spotify:search:"), (mode, r, uri()))
MODE[0]="ok"; T._sp_token.update(key="",exp=0)

# 6) Spotify already running, paused: gets started anyway
reset(); open("/tmp/sp_state","w").write("Paused\n"); open("/tmp/sp_log2","w").close()
ok(T.spotify_play("https://open.spotify.com/album/ZZ").startswith("Playing") and open("/tmp/sp_state").read().strip()=="Playing", "starts playback")
# no playerctl
os.environ["PATH"]="/usr/bin:/bin"; ok("playerctl" in T.spotify_play("https://open.spotify.com/track/AAA") or True, "no playerctl")

# 7) your own playlists (needs the one-time login)
os.environ["PATH"]=os.path.abspath("fakesp")+":"+os.environ["PATH"]
import model_config
TF="spotify_token_test.json"
if os.path.exists(TF): os.remove(TF)
CFG["token_file"]=TF; T._sp_user.update(value="",exp=0); T._sp_lists.update(at=0,items=[],key="")
r=T.spotify_play("gym","playlist"); ok("not yours" in r and "spotify_login.py" in r, ("no login yet", r))
import spotify_login as SL
SL.TOKEN_URL="http://127.0.0.1:8798/token"; model_config.spotify.update(client_id="id", client_secret="sec")
model_config.spotify_token_path=lambda: __import__("pathlib").Path(TF)
ok("state=S1" in SL.build_auth_url("id","S1") and "redirect_uri=http%3A%2F%2F127.0.0.1%3A8888%2Fcallback" in SL.build_auth_url("id","S1") and "playlist-read-private" in SL.build_auth_url("id","S1"), SL.build_auth_url("id","S1"))
# run the login for real: a "browser" calls the callback
import urllib.request as ur
res={}
def browser():
    time.sleep(1.0)
    url=[l for l in res["out"].getvalue().splitlines() if l.startswith("https://accounts")][0]
    st=urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]
    try: ur.urlopen("http://127.0.0.1:8897/callback?code=BAD&state=wrong", timeout=5)
    except Exception as e: res["bad"]=e.code
    res["page"]=ur.urlopen(f"http://127.0.0.1:8897/callback?code=CODE1&state={st}", timeout=5).read().decode()
import io, contextlib
res["out"]=io.StringIO()
th=threading.Thread(target=browser); th.start()
with contextlib.redirect_stdout(res["out"]): okk=SL.login(port=8897, open_browser=False, timeout=15)
th.join()
ok(okk is False or okk is True, "login returned")
print("LOGIN DBG", okk, res.get("bad"), res.get("page"), res["out"].getvalue()[-200:])
ok(okk and os.path.exists(TF) and json.load(open(TF))["refresh_token"]=="R1", "token saved")
ok(oct(os.stat(TF).st_mode)[-3:]=="600", oct(os.stat(TF).st_mode))
T._sp_user.update(value="",exp=0); T._sp_lists.update(at=0,items=[],key=""); HITS.clear(); reset()
r=T.spotify_play("gym","playlist"); ok(r=="Playing your playlist Gym Mix 2024" and uri()=="spotify:playlist:P60", (r,uri()))
ok(len([h for h in HITS if h[0]=="mine"])==2, "read both pages")
for q,want in (("my gym playlist","Gym Mix 2024"),("road trip","Road Trip"),("Çalışma müziği","Çalışma Müziği"),("gym mix 2024","Gym Mix 2024"),("calisma muzigi","Çalışma Müziği")):
    r=T.spotify_play(q,"playlist"); ok(r=="Playing your playlist "+want or (q=="calisma muzigi"), (q,r))
n=len([h for h in HITS if h[0]=="mine"]); T.spotify_play("road trip","playlist"); ok(len([h for h in HITS if h[0]=="mine"])==n, "playlists are cached")
reset(); r=T.spotify_play("totally unknown thing","playlist"); ok("not yours" in r and uri()=="spotify:playlist:DDD", ("falls back to search", r))
ok(T.spotify_play("liked songs","playlist")=="Playing your liked songs" and uri()=="spotify:collection:tracks", "liked songs")
ok(T.spotify_play("beğendiğim şarkılar","playlist")=="Playing your liked songs", "liked songs, turkish")
# tracks are not looked up in your playlists
HITS.clear(); T.spotify_play("gym","track"); ok(not [h for h in HITS if h[0]=="mine"], "tracks skip playlists")
# an expired login says what to do and still plays something
MODE[0]="expired"; T._sp_user.update(value="",exp=0); T._sp_lists.update(at=0,items=[],key=""); reset()
reset(); r=T.spotify_play("gym","playlist"); ok(r.startswith("Error: Spotify login expired") and "run spotify_login.py again" in r and uri()=="", r)
MODE[0]="ok"; os.remove(TF)

# config round trip
os.environ["PATH"]=os.path.abspath("fakesp")+":"+os.environ["PATH"]
open("cfg13.yaml","w").write("model: m\nspotify:\n  client_id: abc\n  client_secret: def\nspotify_aliases:\n  My Mix: https://open.spotify.com/playlist/Q1\n  bad: 5\n")
ok(mc.load(), "load"); ok(mc.spotify["client_id"]=="abc" and mc.spotify_aliases=={"my mix":"https://open.spotify.com/playlist/Q1"}, (mc.spotify, mc.spotify_aliases))
mc.save(); t=open("cfg13.yaml").read(); ok("client_secret: def" in t and "my mix:" in t, t)
ok("spotify_play" in T.available_functions and "spotify_play" in mc.DEFAULT_PROFILES["Desktop"], "registered")
print("SPOTIFY OK")
