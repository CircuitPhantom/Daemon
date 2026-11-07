import os, sys, tempfile, threading, time
sys.path[:0]=["."]
d = tempfile.mkdtemp()
os.environ.update(PATH=os.path.abspath("fakebin")+":"+os.environ["PATH"], FAKELOG=d+"/log", FAKESTATE=d+"/state", FAKELOADED=d+"/loaded")
import tools as T
T.PLAYER_WAIT = 3
def ok(c,m):
    if not c: print("FAIL",m); sys.exit(1)
st = lambda v: open(d+"/state","w").write(v)
rd = lambda: open(d+"/state").read().strip()
# 1. freshly started Spotify, nothing ever played: play must still start music
st("stopped")
r = T.media_control("play"); print(r); ok(rd()=="playing" and r.startswith("Done: play (the player had nothing loaded"), (r, rd()))
# 2. already loaded + paused -> plain play works, no next needed
st("paused"); log0=open(d+"/log").read().count("next")
r = T.media_control("play"); ok(r=="Done: play" and rd()=="playing" and open(d+"/log").read().count("next")==log0, r)
# 3. already playing
ok(T.media_control("play")=="Done: play", "playing stays")
# 4. toggle: pause when playing, start when paused
ok(T.media_control("toggle")=="Done: toggle" and rd()=="paused", "toggle pauses")
ok(T.media_control("toggle")=="Done: play" and rd()=="playing", "toggle starts")
# 5. next on a paused player starts it
st("paused"); r=T.media_control("next"); ok(r=="Done: next" and rd()=="playing", (r, rd()))
# 6. player not there yet when asked (app still starting): waits and succeeds
os.remove(d+"/loaded"); st("gone")
threading.Timer(1.0, lambda: st("stopped")).start()
t=time.time(); r=T.media_control("play"); print(r, round(time.time()-t,1)); ok(rd()=="playing" and 1.0<=time.time()-t<4, (r,rd()))
# 7. no player at all -> clear message after the wait
st("gone"); t=time.time(); r=T.media_control("play"); ok(r.startswith("Nothing is playing") and "open_app" in r and 2.5<time.time()-t<5, (r, time.time()-t))
# 8. status / pause / bad
st("playing"); ok(T.media_control("status")=="Playing: Artist - Song (spotify)" and T.media_control("pause")=="Done: pause" and rd()=="paused", "status/pause")
ok(T.media_control("explode").startswith("Error"), "bad action")
print("MEDIA OK")
