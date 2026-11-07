import os, sys, io, json, time, threading, wave, shutil
sys.path[:0]=["stubs","."]
os.environ.update(DAEMON_CONFIG="cfg25.yaml", DAEMON_CHATS="chats25", DAEMON_MEMORY="m25.json", DAEMON_REMINDERS="r25.json", DAEMON_CALENDAR="c25.json", DAEMON_TTS_USAGE="u25.json")
for f in ("cfg25.yaml",): 
    if os.path.exists(f): os.remove(f)
shutil.rmtree("chats25", ignore_errors=True)
import server, ollama, uvicorn, http.client
def fakewav(secs=2.0):
    b=io.BytesIO()
    with wave.open(b,"wb") as w: w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(b"\0\0"*int(24000*secs))
    return b.getvalue()
def slow_tts(synth,text,max_chunks=4):
    time.sleep(0.3); return fakewav()
server.voice.tts_wav=slow_tts
cfg=uvicorn.Config(server.app, host="127.0.0.1", port=8811, log_level="warning"); srv=uvicorn.Server(cfg)
threading.Thread(target=srv.run, daemon=True).start(); time.sleep(1.5)
def stream(text, stop_after_audio=None):
    c=http.client.HTTPConnection("127.0.0.1",8811,timeout=30)
    c.request("POST","/api/say/stream",body=json.dumps({"text":text,"speak":True}),headers={"Content-Type":"application/json"})
    r=c.getresponse(); evs=[]; buf=b""
    while True:
        ch=r.readline()
        if not ch: break
        if not ch.strip(): continue
        ev=json.loads(ch); evs.append(ev)
        if stop_after_audio is not None and ev["type"]=="audio" and ev["seq"]==stop_after_audio:
            c.sock.close(); c.close(); return evs
    return evs
evs=stream("verylong one", stop_after_audio=2)
turn=[e for e in evs if e["type"]=="user"][0]["turn"]
c=http.client.HTTPConnection("127.0.0.1",8811); c.request("POST","/api/heard",body=json.dumps({"turn":turn,"seq":1,"offset":1.0}),headers={"Content-Type":"application/json"}); print("heard:", c.getresponse().read())
n=len(ollama.SEEN)
evs=stream("continue")
done=[e for e in evs if e["type"]=="done"][0]
print("model calls:", len(ollama.SEEN)-n, "| reply:", done["reply"][:90])
print("pending after:", bool(server.interrupts.pending))
# the reply was fully sent, then Stop pressed while it still played (the case from the dashboard)
server.interrupts.pending.clear()
evs=stream("tagtest full")
turn=[e for e in evs if e["type"]=="user"][0]["turn"]
assert not server.interrupts.pending, "nothing pending yet"
c=http.client.HTTPConnection("127.0.0.1",8811); c.request("POST","/api/heard",body=json.dumps({"turn":turn,"seq":0,"offset":1.9}),headers={"Content-Type":"application/json"}); c.getresponse().read()
assert server.interrupts.pending and server.interrupts.pending["turn"]==turn, server.interrupts.pending
n=len(ollama.SEEN); evs=stream("continue"); done=[e for e in evs if e["type"]=="done"][0]
print("after full send -> calls:", len(ollama.SEEN)-n, "| reply:", done["reply"][:60])
assert len(ollama.SEEN)==n and done["reply"].startswith("Now the second"), done
# a report that says everything was heard makes nothing pending
evs=stream("tagtest full2"); turn=[e for e in evs if e["type"]=="user"][0]["turn"]
c=http.client.HTTPConnection("127.0.0.1",8811); c.request("POST","/api/heard",body=json.dumps({"turn":turn,"seq":9,"offset":0}),headers={"Content-Type":"application/json"}); c.getresponse().read()
assert not server.interrupts.pending, server.interrupts.pending
# report for an old turn is ignored
c=http.client.HTTPConnection("127.0.0.1",8811); c.request("POST","/api/heard",body=json.dumps({"turn":turn-1,"seq":0,"offset":0.5}),headers={"Content-Type":"application/json"}); c.getresponse().read()
assert not server.interrupts.pending, "old turn"
print("HTTP RESUME OK")
