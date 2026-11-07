import os, sys, shutil
sys.path[:0]=["stubs","."]
os.environ.update(DAEMON_CONFIG="cfg33.yaml", DAEMON_CHATS="chats33", DAEMON_MEMORY="mem33.json", DAEMON_REMINDERS="rem33.json", DAEMON_INBOX="inbox33.json")
for f in ("cfg33.yaml",): 
    if os.path.exists(f): os.remove(f)
open("cfg33.yaml","w").write("model: qwen3:1.7b\nelevenlabs:\n  api_key: sk_x\n  model: eleven_v3\n")
def ok(c,m=""):
    if not c: print("FAIL",m); sys.exit(1)
import model_config as mc; ok(mc.load())
import server
from fastapi.testclient import TestClient
with TestClient(server.app) as c:
    g=c.get("/api/prefs").json(); ok(g["uploads"]["enabled"] and g["uploads"]["vision"]=="auto" and g["phone"]["speech_level"]==0.02 and g["elevenlabs"]["configured"], g)
    r=c.post("/api/prefs", json={"uploads":{"vision":"true","max_mb":500,"enabled":False},"elevenlabs":{"audio_tags_use":"lively","audio_tags":True},"phone":{"speech_level":0.045,"noise_mult":99,"min_speech_ms":10,"barge_ms":700}}).json()
    ok(r["uploads"]=={"enabled":False,"vision":"true","max_mb":200,"dir":r["uploads"]["dir"]}, r["uploads"])
    ok(r["phone"]["speech_level"]==0.045 and r["phone"]["noise_mult"]==10 and r["phone"]["min_speech_ms"]==40 and r["phone"]["barge_ms"]==700, r["phone"])
    ok(r["elevenlabs"]["audio_tags_use"]=="lively" and r["elevenlabs"]["audio_tags"], r["elevenlabs"])
    ok(c.post("/api/prefs", json={"uploads":{"vision":"maybe"}}).status_code==400 and c.post("/api/prefs", json={"elevenlabs":{"audio_tags_use":"x"}}).status_code==400 and c.post("/api/prefs", json={"phone":{"barge_ms":"fast"}}).status_code==400, "validation")
    ok(c.post("/api/prefs", json={}).status_code==200, "empty patch")
    # persisted and reloadable
    mc.uploads["max_mb"]=1; mc.load(); ok(mc.uploads["max_mb"]==200 and mc.uploads["vision"].lower()=="true" and mc.phone_cfg["barge_ms"]==700 and mc.elevenlabs["audio_tags_use"]=="lively", (mc.uploads, mc.phone_cfg))
    import uploads
    ok(not uploads.enabled(), "uploads disabled flag")
print("OK prefs")
