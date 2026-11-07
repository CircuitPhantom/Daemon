"""Phone calls you can talk in: Twilio Media Streams <-> Whisper, the model and Kokoro.

Daemon rings you (a [CALL] task) or you ring your Twilio number. Once you pick up, what you say is
transcribed with the same Whisper model as the web UI, answered by the active chat (tools work),
and the reply is spoken with Kokoro. Talking over the reply interrupts it.

This runs as its own small web app on its own port (phone.port, default 8001) and serves nothing
but /phone/*. Only that port is meant to be reachable from the internet, never the dashboard:

    tailscale funnel --bg --https=8443 8001       -> https://<machine>.<tailnet>.ts.net:8443
    config.yaml:  phone: {enabled: true, public_url: "https://<machine>.<tailnet>.ts.net:8443"}

To call Daemon yourself, set your Twilio number's "A call comes in" webhook (HTTP POST) to
<public_url>/phone/incoming. Daemon-initiated calls need no webhook.

Safety: the webhook must carry a valid Twilio signature and come from twilio_to; the audio socket
needs a one-time token that only Daemon's own TwiML contains; one call at a time; every call has a
time limit and hangs up after a stretch of silence.
"""
import asyncio
import base64
import hashlib
import hmac
import io
import json
import queue
import re
import secrets
import threading
import time
import types
import wave
from xml.sax.saxutils import escape

import numpy as np
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

import model_config
import wakeword

TOKEN_TTL = 120            # seconds a call token stays valid
BARGE_SECONDS = 0.3        # how long you must talk over the reply to interrupt it
FRAME_MS = 20
BYE = re.compile(r"\b(good ?bye|bye bye|hang up|that'?s all|that is all|görüşürüz|hoşça ?kal)\b", re.I)
NOISE = {"you", "thank you", "thanks for watching", "thanks"}     # what Whisper invents from line noise

# server.py fills these in so this module never imports the server:
#   turn(text, speak, emit, cancel)   one chat turn, same as the web UI
#   transcribe(audio16k)              Whisper
#   speak(text) -> wav bytes or None  Kokoro
backend = types.SimpleNamespace(turn=None, transcribe=None, speak=None, heard=None)

_tokens = {}
_tok_lock = threading.Lock()
_busy = threading.Lock()       # one call at a time
state = {"server": False, "calls": 0, "last": ""}
_current = {"call": None}


# ═══════════════════════════════════════════════════
#  Audio: G.711 mu-law <-> float, resampling (numpy only, audioop is gone in Python 3.13)
# ═══════════════════════════════════════════════════
def mulaw_decode(data):
    u = (~np.frombuffer(data, dtype=np.uint8)).astype(np.int32) & 0xFF
    mag = ((((u & 0x0F) << 3) + 0x84) << ((u >> 4) & 7)) - 0x84
    return (np.where(u & 0x80, -mag, mag) / 32768.0).astype(np.float32)


def mulaw_encode(x):
    pcm = np.clip(np.asarray(x, dtype=np.float64) * 32768.0, -32768, 32767).astype(np.int32)
    sign = np.where(pcm < 0, 0x80, 0)
    biased = np.minimum(np.abs(pcm), 32635) + 0x84
    exp = np.floor(np.log2(biased >> 7)).astype(np.int32)
    mant = (biased >> (exp + 3)) & 0x0F
    return ((~(sign | (exp << 4) | mant)) & 0xFF).astype(np.uint8).tobytes()


def resample(x, src, dst):
    if src == dst or len(x) == 0:
        return x.astype(np.float32)
    if src > dst and src % dst == 0:                # whole-number step down: average, which also low-passes
        k = src // dst
        n = len(x) // k * k
        return x[:n].reshape(-1, k).mean(axis=1).astype(np.float32)
    n = max(1, int(round(len(x) * dst / src)))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


def wav_to_mulaw(wav):
    """PCM16 WAV bytes -> (mu-law bytes at 8 kHz, seconds)."""
    with wave.open(io.BytesIO(wav), "rb") as w:
        rate, ch, raw = w.getframerate(), w.getnchannels(), w.readframes(w.getnframes())
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    x = resample(x, rate, 8000)
    return mulaw_encode(x), len(x) / 8000.0


# ═══════════════════════════════════════════════════
#  Tokens, signatures, TwiML
# ═══════════════════════════════════════════════════
def _cfg():
    p = model_config.phone_cfg
    try:
        port = int(p.get("port"))
    except (TypeError, ValueError):
        port = 8001
    return {
        "enabled": bool(p.get("enabled")),
        "url": str(p.get("public_url") or "").strip().rstrip("/"),
        "port": port,
        "max_s": 60 * max(1, int(p.get("max_minutes") or 10)),
        "silence_s": max(10, int(p.get("silence_seconds") or 30)),
        "level": float(p.get("speech_level") or 0.02),
        "mult": float(p.get("noise_mult") or 4.0),
        "min_speech": int(p.get("min_speech_ms") or 120) / 1000,
        "barge": int(p.get("barge_ms") or 500) / 1000,
    }


def available():
    """True when a conversation call can be placed: bridge on, public address set, Twilio set up."""
    import twilio_call
    c = _cfg()
    return bool(c["enabled"] and c["url"].startswith("https://") and state["server"] and twilio_call.configured())


def issue_token(greeting="", notice=""):
    tok = secrets.token_urlsafe(24)
    now = time.time()
    with _tok_lock:
        for k in [k for k, v in _tokens.items() if v["exp"] < now]:
            del _tokens[k]
        _tokens[tok] = {"exp": now + TOKEN_TTL, "greeting": greeting, "notice": notice}
    return tok


def take_token(tok):
    """Single use: a token works once."""
    with _tok_lock:
        v = _tokens.pop(str(tok or ""), None)
    return v if v and v["exp"] >= time.time() else None


def stream_twiml(greeting="", notice=""):
    """TwiML that connects the call's audio to /phone/stream."""
    c = _cfg()
    ws = "wss://" + c["url"][len("https://"):] + "/phone/stream"
    tok = issue_token(greeting, notice)
    q = lambda s: escape(s, {'"': "&quot;"})
    return (f'<Response><Connect><Stream url="{q(ws)}">'
            f'<Parameter name="token" value="{q(tok)}"/></Stream></Connect></Response>')


def twilio_signature(url, params, auth_token):
    data = url + "".join(k + str(params[k]) for k in sorted(params))
    mac = hmac.new(auth_token.encode(), data.encode(), hashlib.sha1).digest()
    return base64.b64encode(mac).decode()


def valid_signature(url, params, signature, auth_token):
    if not (signature and auth_token):
        return False
    return hmac.compare_digest(twilio_signature(url, params, auth_token), signature)


# ═══════════════════════════════════════════════════
#  One call
# ═══════════════════════════════════════════════════
class Call:
    def __init__(self, ws, loop, info):
        c = _cfg()
        self.ws, self.loop, self.info = ws, loop, info
        self.sid = ""
        self.max_s, self.silence_s = c["max_s"], c["silence_s"]
        self.vad = wakeword.Segmenter(c["level"], c["mult"], c["min_speech"])
        self.barge_s = c["barge"]
        self.utterances = queue.Queue()
        self.cancel = threading.Event()
        self.speaking_until = 0.0
        self.talk_since = None
        self.notice = info.get("notice") or ""
        self.end_after = False
        self.closed = False
        self.started = time.monotonic()
        self.last_active = time.monotonic()
        self.turn_running = False
        self.reset_marks()

    # -- sending audio to the caller (thread-safe) --
    def _send(self, obj):
        if self.closed:
            return
        fut = asyncio.run_coroutine_threadsafe(self.ws.send_text(json.dumps(obj)), self.loop)
        try:
            fut.result(timeout=10)
        except Exception:
            self.closed = True

    def play_wav(self, wav):
        if not wav or self.closed:
            return
        ulaw, secs = wav_to_mulaw(wav)
        for i in range(0, len(ulaw), 4000):          # 0.5 s per message
            self._send({"event": "media", "streamSid": self.sid,
                        "media": {"payload": base64.b64encode(ulaw[i:i + 4000]).decode()}})
        self.speaking_until = max(self.speaking_until, time.monotonic()) + secs
        self.last_active = time.monotonic()
        return secs

    def say(self, text):
        try:
            self.play_wav(backend.speak(text))
        except Exception as e:
            print("[phone] could not speak:", e)

    def interrupt(self):
        """Stops the reply. Called from the event loop (on_media), so the message is queued, not awaited."""
        self.cancel.when = time.time()                      # the server works out from this what the caller heard
        self.cancel.heard = self.heard_now()
        self.cancel.set()
        if self.cancel.heard and self.clips and backend.heard:   # also when the server had already sent the whole reply
            try:
                backend.heard(self.clips[0][0], *self.cancel.heard)
            except Exception as e:
                print("[phone] could not report the cut:", e)
        self.speaking_until = 0.0
        if not self.closed:
            self.loop.create_task(self.ws.send_text(json.dumps({"event": "clear", "streamSid": self.sid})))

    # -- how far the caller has heard: Twilio sends a "mark" back when the audio before it has played --
    def reset_marks(self):
        self.clips, self.done_seq, self.mark_at, self.first_at = [], -1, None, None

    def on_mark(self, name):
        try:
            turn, seq = (int(x) for x in str(name).split(":"))
        except ValueError:
            return
        if self.clips and turn == self.clips[0][0]:
            self.done_seq, self.mark_at = seq, time.time()

    def heard_now(self):
        """(seq of the clip that was playing, seconds into it), or None when nothing was sent yet."""
        if not getattr(self, "clips", None):
            return None
        nxt = self.done_seq + 1
        started = self.mark_at if self.mark_at is not None else self.first_at
        if nxt > self.clips[-1][1]:
            return (nxt, 0.0)                              # all sent audio was heard
        return (nxt, max(0.0, time.time() - started)) if started else (nxt, 0.0)

    # -- hearing the caller --
    def on_media(self, payload):
        x = resample(mulaw_decode(base64.b64decode(payload)), 8000, 16000)
        utt = self.vad.feed(x)
        now = time.monotonic()
        if self.vad.speaking:
            self.last_active = now
            if now < self.speaking_until:                   # talking over the reply
                self.talk_since = self.talk_since or now
                if now - self.talk_since >= self.barge_s:
                    print("[phone] interrupted")
                    self.interrupt()
                    self.talk_since = None
        else:
            self.talk_since = None
        if utt is not None:
            self.utterances.put(utt)

    # -- the conversation (runs in its own thread) --
    def worker(self):
        greeting = self.info.get("greeting")
        if greeting:
            self.say(greeting)
        while not self.closed:
            try:
                utt = self.utterances.get(timeout=0.5)
            except queue.Empty:
                continue
            if utt is None:
                return
            try:
                self.handle(utt)
            except Exception as e:
                print("[phone] turn failed:", e)

    def handle(self, audio):
        text = (backend.transcribe(audio) or "").strip()
        print("[phone] you:", text)
        if not text or (text.lower().strip(" .!?,") in NOISE and len(audio) < 16000):
            text = ""                                      # noise: the server only goes on with a cut reply, if there is one
        if BYE.search(text):
            self.end_after = True
        if self.notice and text:                           # the first thing you say answers the call's message
            text = f'(Re: "{self.notice}")\n{text}'
            self.notice = ""
        self.cancel = threading.Event()
        cancel = self.cancel
        self.turn_running = True
        self.reset_marks()

        def emit(ev):
            if ev.get("type") == "audio" and ev.get("audio") and not cancel.is_set():
                secs = self.play_wav(base64.b64decode(ev["audio"]))
                if secs and ev.get("seq") is not None:
                    if self.first_at is None:
                        self.first_at = time.time()
                    self.clips.append((ev.get("turn", 0), ev["seq"], secs))
                    self._send({"event": "mark", "streamSid": self.sid, "mark": {"name": f"{ev.get('turn', 0)}:{ev['seq']}"}})

        try:
            backend.turn(text, True, emit, cancel)
        finally:
            self.turn_running = False
            self.last_active = time.monotonic()

    # -- timeouts, run from the async side --
    def over_time(self):
        return time.monotonic() - self.started > self.max_s

    def idle(self):
        now = time.monotonic()
        return (not self.turn_running and now > self.speaking_until
                and now - self.last_active > self.silence_s)

    def finished(self):
        return self.end_after and not self.turn_running and time.monotonic() > self.speaking_until + 0.8


# ═══════════════════════════════════════════════════
#  The web app (own port, only /phone/*)
# ═══════════════════════════════════════════════════
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def _twiml(body, status=200):
    return Response(content=f'<?xml version="1.0" encoding="UTF-8"?>{body}', status_code=status,
                    media_type="text/xml")


@app.post("/phone/incoming")
async def incoming(request: Request):
    """Twilio calls this when someone rings your Twilio number."""
    import twilio_call
    c, tw = _cfg(), twilio_call._cfg()
    form = {k: str(v) for k, v in (await request.form()).items()}
    url = c["url"] + "/phone/incoming"
    if not (c["enabled"] and tw["token"] and valid_signature(
            url, form, request.headers.get("x-twilio-signature", ""), tw["token"])):
        return _twiml("<Response><Reject/></Response>", 403)
    caller = re.sub(r"[\s\-()]", "", form.get("From", ""))
    if not tw["to"] or caller != tw["to"]:                  # only you
        print("[phone] rejected a call from", caller or "unknown")
        return _twiml("<Response><Reject/></Response>")
    if _busy.locked():
        return _twiml('<Response><Say>Daemon is busy right now.</Say></Response>')
    return _twiml(stream_twiml(greeting="Daemon here. What can I do for you?"))


@app.websocket("/phone/stream")
async def stream(ws: WebSocket):
    await ws.accept()
    loop = asyncio.get_running_loop()
    call = None
    watcher = None
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            ev = msg.get("event")
            if ev == "start":
                start = msg.get("start") or {}
                info = take_token((start.get("customParameters") or {}).get("token"))
                if info is None:
                    print("[phone] stream refused: bad or reused token")
                    await ws.close(code=1008)
                    return
                if not _busy.acquire(blocking=False):
                    await ws.close(code=1013)
                    return
                try:
                    call = Call(ws, loop, info)
                except Exception:
                    _busy.release()                     # never leave the line "busy" forever
                    raise
                _current["call"] = call
                call.sid = start.get("streamSid") or msg.get("streamSid") or ""
                state["calls"] += 1
                state["last"] = time.strftime("%H:%M:%S")
                print("[phone] call connected")
                threading.Thread(target=call.worker, daemon=True, name="phone-worker").start()
                watcher = asyncio.create_task(_watch(call))
            elif ev == "mark" and call is not None:
                call.on_mark((msg.get("mark") or {}).get("name"))
            elif ev == "media" and call is not None:
                track = (msg.get("media") or {}).get("track", "inbound")
                if track == "inbound":
                    call.on_media(msg["media"]["payload"])
            elif ev == "stop":
                break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print("[phone] stream error:", e)
    finally:
        if watcher:
            watcher.cancel()
        if call is not None:
            call.closed = True
            call.cancel.set()
            call.utterances.put(None)
            _current["call"] = None
            _busy.release()
            print("[phone] call ended")


async def _watch(call):
    """Hangs up when time is up, nobody talks, or you said goodbye."""
    try:
        while not call.closed:
            await asyncio.sleep(0.5)
            why = None
            if call.over_time():
                why = "We have reached the time limit. Goodbye."
            elif call.idle():
                why = "I can't hear you anymore, so I'm hanging up. Goodbye."
            elif call.finished():
                why = ""
            if why is None:
                continue
            if why:
                await asyncio.get_running_loop().run_in_executor(None, call.say, why)
                await asyncio.sleep(max(0.0, call.speaking_until - time.monotonic()) + 0.8)
            call.closed = True
            await call.ws.close()
            return
    except Exception as e:
        print("[phone] watcher:", e)


# ═══════════════════════════════════════════════════
#  Own server on its own port, started from server.py
# ═══════════════════════════════════════════════════
_srv = {"server": None, "thread": None}


def start_server():
    c = _cfg()
    if not c["enabled"] or _srv["thread"]:
        return False
    try:
        import websockets          # noqa: F401  uvicorn needs one of these for the audio socket
    except ImportError:
        try:
            import wsproto         # noqa: F401
        except ImportError:
            print("[phone] pip install websockets   (needed for phone calls)")
            return False
    import uvicorn
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=c["port"], log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True, name="phone-server")
    t.start()
    end = time.monotonic() + 8
    while not server.started and t.is_alive() and time.monotonic() < end:
        time.sleep(0.05)
    if not server.started:                       # most often: the port is already in use
        server.should_exit = True
        state["server"] = False
        print(f"[phone] bridge could not start on port {c['port']} (is it in use? change phone.port)")
        return False
    _srv.update(server=server, thread=t)
    state["server"] = True
    print(f"[phone] bridge listening on 127.0.0.1:{c['port']} (public: {c['url'] or 'public_url is not set'})")
    return True


def stop_server():
    srv, t = _srv["server"], _srv["thread"]
    if srv:
        srv.should_exit = True
        if t:
            t.join(timeout=5)
    _srv.update(server=None, thread=None)
    state["server"] = False
