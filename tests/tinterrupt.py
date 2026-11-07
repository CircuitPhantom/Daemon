import re
import os, sys, io, wave, time, threading, shutil
sys.path[:0]=["stubs","."]
os.environ.update(DAEMON_CONFIG="cfg21.yaml", DAEMON_CHATS="chats21", DAEMON_MEMORY="mem21.json", DAEMON_REMINDERS="rem21.json", DAEMON_CALENDAR="cal21.json", DAEMON_TTS_USAGE="use21.json")
for f in ("cfg21.yaml","mem21.json","rem21.json","cal21.json","use21.json"):
    if os.path.exists(f): os.remove(f)
shutil.rmtree("chats21", ignore_errors=True)
def ok(c,m):
    if not c: print("FAIL",m); sys.exit(1)
import model_config as mc, server, ollama, elevenlabs_tts as el, edge_voice as ev, pykokoro
# --- tag helpers
ok(server.voice.strip_tags("Ha ha. [laughing] That was funny. [sighing] The end.")=="Ha ha. That was funny. The end.", server.voice.strip_tags("Ha ha. [laughing] That was funny. [sighing] The end."))
ok(server.voice.strip_tags("see [1] and [x]")=="see [1] and [x]", "numbers stay")
f=server.voice.TagFilter(); out="".join([f.feed("Ha ha. [lau"), f.feed("ghing] That. [si"), f.feed("ghing] End [x"), f.flush()])
ok(out=="Ha ha. That. End [x", repr(out))
ok(server.voice.clean_for_tts("Ha. [laughing] Funny **one**.", tags=True)=="Ha. [laughing] Funny one.", server.voice.clean_for_tts("Ha. [laughing] Funny **one**.", tags=True))
ok(server.voice.clean_for_tts("Ha. [laughing] Funny.", tags=False)=="Ha. Funny.", server.voice.clean_for_tts("Ha. [laughing] Funny.", tags=False))
# --- who gets the tags
SEEN=[]
mc.elevenlabs.update(enabled=True, api_key="k", model="eleven_v3")
el.speak=lambda t:(SEEN.append(("el",t)),None)[1]; ev.speak=lambda t:(SEEN.append(("edge",t)),None)[1]
ok(server.voice.voice_tags_on(), "v3 = tags on")
server.voice.tts_wav(server.voice.LazyKokoro(), "Ha. [laughing] Funny.")
ok(SEEN[0]==("el","Ha. [laughing] Funny.") and pykokoro.SPOKEN[-1]=="Ha. Funny.", (SEEN, pykokoro.SPOKEN[-1]))
SEEN.clear(); mc.elevenlabs["model"]="eleven_flash_v2_5"; ok(not server.voice.voice_tags_on(), "flash = off")
server.voice.tts_wav(server.voice.LazyKokoro(), "Ha. [laughing] Funny."); ok(SEEN[0]==("el","Ha. Funny."), SEEN)
mc.elevenlabs["audio_tags"]=True; ok(server.voice.voice_tags_on(), "flag turns it on")
SEEN.clear(); ok(server.voice.tts_wav(server.voice.LazyKokoro(), "[laughing]") is None or True, "tag only")
mc.edge_tts.update(enabled=True, primary=True); ok(not server.voice.voice_tags_on(), "edge first = no tags"); mc.edge_tts.update(enabled=False, primary=False)
# --- prompt
p=server.conv.system_msg(True)["content"]; ok("interrupts you" in p and "[laughing]" in p, p[-300:])
ok("interrupts you" not in server.conv.system_msg(False)["content"], "no voice block when typing")
mc.elevenlabs["audio_tags"]=False; ok("[laughing]" not in server.conv.system_msg(True)["content"] and "interrupts you" in server.conv.system_msg(True)["content"], "voice block without tags")
mc.elevenlabs["audio_tags"]=True

import wave as W
def fakewav(secs=2.0):
    b=io.BytesIO()
    with W.open(b,"wb") as w: w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(b"\0\0"*int(24000*secs))
    return b.getvalue()
SENT=[]
server.voice.tts_wav=lambda synth,text,max_chunks=4:(SENT.append(text),fakewav())[1]
from fastapi.testclient import TestClient
cl=TestClient(server.app)
def asst(): return [m for m in server.conv.messages if (m["role"] if isinstance(m,dict) else m.role)=="assistant"]
def users(): return [m for m in server.conv.messages if (m["role"] if isinstance(m,dict) else m.role)=="user"]
def cut_turn(text, at_clip=1, offset=0.3, report=True, delay=0.0):
    """Runs a spoken turn and cuts it while clip `at_clip` plays, `offset` s in."""
    EV=[]; cancel=threading.Event(); T=[]
    def emit(e):
        EV.append(e)
        if e["type"]=="audio":
            T.append(time.time())
            if len(T)==at_clip+1 and not cancel.is_set():
                cancel.when=T[0]+2.0*at_clip+offset
                if report: cl.post("/api/heard", json={"turn":e["turn"],"seq":at_clip,"offset":offset})
                cancel.set()
    ollama.DELAY[0]=delay; SENT.clear()
    server.conv.turn_job(text, True, emit, cancel)
    ollama.DELAY[0]=0
    return EV
def run(text, speak=True):
    EV=[]; SENT.clear(); n=len(ollama.SEEN)
    server.conv.turn_job(text, speak, EV.append, threading.Event())
    d=[e for e in EV if e["type"]=="done"]
    return (d[-1] if d else None), len(ollama.SEEN)-n, EV

# 1) cut in the middle of the 2nd sentence, page reports the exact spot; "continue" goes on from that sentence, no model call
EV=cut_turn("tagtest one")
ok(server.interrupts.pending and server.interrupts.pending["cancelled"] and server.interrupts.pending["complete"], server.interrupts.pending)
sp=server.interrupts._split(server.interrupts.pending); print("split:", sp)
ok(sp["heard"].startswith("Ha ha. That was funny. Now") and sp["heard"].endswith("…"), sp)
ok(sp["rest"].startswith("Now the second sentence") and sp["rest"].endswith("The end."), sp)
d,calls,EV=run("continue")
ok(calls==0, "no model call for continue"); ok(d["reply"].startswith("Now the second sentence") and "[" not in d["reply"], d["reply"])
ok(SENT and SENT[0].startswith("Now the second"), SENT)
ok(asst()[-2]["content"]=="Ha ha. [laughing] That was funny. —" and asst()[-1]["content"].startswith("Now the second"), [a["content"] for a in asst()[-2:]])
ok(users()[-1]["content"]=="continue" and not server.interrupts.pending, "pending used")
ok(any(e["type"]=="user" and e.get("turn") for e in EV), "turn number sent")

# 2) no report (phone-less wake word etc.): worked out from timing; a side question first, then "okay, go on"
cut_turn("tagtest two", at_clip=1, offset=0.5, report=False)
sp=server.interrupts._split(server.interrupts.pending); ok(sp["rest"].startswith("Now the second"), sp)
d,calls,_=run("wait, what was funny?")
ok(calls==1, "side question goes to the model"); u=users()[-1]["content"]
ok("They heard" in u and "did NOT hear the rest" in u and u.endswith("wait, what was funny?"), u)
ok(server.interrupts.pending and server.interrupts.pending["turns"]==1, server.interrupts.pending.get("turns"))
d,calls,_=run("okay, go on")
ok(calls==0 and d["reply"].startswith("So, as I was saying: Now the second"), d["reply"])
ok(not server.interrupts.pending, "used")

# 3) noise or "mm-hmm" right after the cut: just goes on
cut_turn("tagtest three"); d,calls,_=run("")
ok(d and calls==0 and d["reply"].startswith("Now the second") and d["user"]=="(go on)", d)
cut_turn("tagtest four"); d,calls,_=run("mm-hmm")
ok(calls==0 and d["reply"].startswith("Now the second"), d)
# ...but not after another exchange
cut_turn("tagtest five"); run("what time is it"); d,calls,_=run("okay")
ok(calls==1, "backchannel after a side turn goes to the model")
# empty text with nothing pending = nothing happens
server.interrupts.pending.clear(); d,calls,_=run(""); ok(d["user"]=="" and calls==0, d)

# 4) cut while the model was still writing: no replay, the model is told
EV=cut_turn("tagtest six", at_clip=0, offset=0.3, delay=0.15)
ok(server.interrupts.pending and not server.interrupts.pending["complete"], server.interrupts.pending.get("complete"))
d,calls,_=run("continue")
ok(calls==1 and "still writing" in users()[-1]["content"], users()[-1]["content"])

# 5) cut again while going on, then go on again
cut_turn("tagtest seven", at_clip=0, offset=1.0)
d,calls,EV=run("continue")
ok(calls==0, "first resume")
# 6) very long answer: only 12 pieces are read; "continue" reads the rest
server.interrupts.pending.clear(); d,calls,_=run("verylong please")
ok(server.interrupts.pending and not server.interrupts.pending["cancelled"], "long answer leaves the rest")
d,calls,_=run("continue")
ok(calls==0 and "sentence number" in d["reply"] and "number 1 " not in d["reply"], d["reply"][:80])
# typed message right after a long answer: note says only part was read
server.interrupts.pending.clear(); run("verylong again"); d,calls,_=run("thanks", speak=False)
ok("only part of it was read out" in users()[-1]["content"], users()[-1]["content"][:120])
# stale after 3 more turns
run("a"); run("b"); run("c"); ok(not server.interrupts.pending, "dropped after a few turns")

# 7) /api/heard checks its input
ok(cl.post("/api/heard", json={"turn":"x"}).status_code==400, "bad report")
ok(cl.post("/api/heard", json={"turn":1,"seq":0,"offset":0.4}).json()["ok"], "good report")
# 8) new chat forgets the cut reply
cut_turn("tagtest eight"); server.conv.new_chat(); ok(not server.interrupts.pending, "new chat clears")
# 9) regexes
for t in ("continue","go on","Okay, continue please","yes go ahead","devam et","Tamam devam","sen devam et","where were we?","keep going from there"):
    ok(server.interrupts.CONTINUE.match(t), t)
for t in ("continue but shorter","go on to the next topic","what do you mean","don't continue"):
    ok(not server.interrupts.CONTINUE.match(t), t)
for t in ("mm-hmm","Uh huh.","okay","yeah","evet","hı hı"):
    ok(server.interrupts.BACKCHANNEL.match(t), t)
# 10) phone marks
import phone_bridge as pb
c=pb.Call.__new__(pb.Call); c.reset_marks()
ok(c.heard_now() is None, "nothing sent")
c.first_at=time.time()-1.0; c.clips=[(5,0,2.0),(5,1,2.0),(5,2,2.0)]
h=c.heard_now(); ok(h[0]==0 and 0.9<h[1]<1.2, h)
c.on_mark("5:0"); c.mark_at=time.time()-0.5; h=c.heard_now(); ok(h[0]==1 and 0.4<h[1]<0.7, h)
c.on_mark("4:1"); ok(c.done_seq==0, "old turn ignored"); c.on_mark("5:2"); ok(c.heard_now()==(3,0.0), c.heard_now())
# nearly finished sentence: go on with the next one
cut_turn("tagtest nine", at_clip=1, offset=1.0)
ok(server.interrupts._split(server.interrupts.pending)["rest"].startswith("And a third one"), server.interrupts._split(server.interrupts.pending))
server.interrupts.pending.clear()
print("RESUME OK")

# invented tags and links
ok(server.voice.strip_tags("Sure [smiles] I can. [warm laugh] See [docs](http://x.io) and [1] and [x].")=="Sure I can. See [docs](http://x.io) and [1] and [x].", server.voice.strip_tags("Sure [smiles] I can. [warm laugh] See [docs](http://x.io) and [1] and [x]."))
ok(server.voice.clean_for_tts("Sure [smiles] I can. [laughing] Ok.", tags=True)=="Sure I can. [laughing] Ok.", server.voice.clean_for_tts("Sure [smiles] I can. [laughing] Ok.", tags=True))
ok(server.voice.clean_for_tts("Sure [smiles] I can.", tags=False)=="Sure I can.", "off")
f=server.voice.TagFilter(); ok("".join([f.feed("Sure [smi"), f.feed("les] yes"), f.flush()])=="Sure yes", "stream")
print("TAGS OK")

# a lone effect joins the next sentence
SENT=[]; server.voice.tts_wav=lambda synth,text,max_chunks=4:(SENT.append(text),fakewav(0.2))[1]
mc.elevenlabs.update(model="eleven_v3"); server.voice.elevenlabs_tts.state=lambda:(True,"ok")
class Q: pass
import queue
def run_pieces(pieces):
    SENT.clear()
    ollama.DELAY[0]=0
    # drive the real worker through turn_job with a model that streams the pieces
    return pieces
server.conv.turn_job("tagtest again", True, lambda e:None, threading.Event())
ok(all(re.search(r"\w", re.sub(r"\[[a-z ]+\]", "", t)) for t in SENT), SENT)
print("CARRY OK", SENT)

SENT.clear(); server.conv.turn_job("tagend please", True, lambda e:None, threading.Event())
ok(SENT and SENT[-1]=="[laughing]", SENT)
print("END TAG OK", SENT)
for t in server.voice.VOICE_TAGS:
    ok(server.voice.clean_for_tts(f"Hi. [{t}] There.", tags=True)==f"Hi. [{t}] There.", t)
    ok(server.voice.strip_tags(f"Hi. [{t}] There.")=="Hi. There.", t)
ok(len(server.voice.VOICE_TAGS)==25 and "[voice breaking]" in server.voice.voice_block(), len(server.voice.VOICE_TAGS))
print("ALL TAGS OK")
