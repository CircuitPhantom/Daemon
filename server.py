"""Daemon's web server: the dashboard page, the streaming turn endpoints, the laptop agent link, and the wiring between
the parts. The rest lives in:

  conversation.py   the active chat and one turn of it (typed, spoken, Signal, phone, laptop)
  voice.py          speech-to-text and the spoken reply
  interrupts.py     what you heard when you cut a reply off, and going on from there
  toolguard.py      your OK before risky tools run, and the log of every tool call
  api_settings.py   dashboard API: settings, voices, cloud model, PIN, security
  api_data.py       dashboard API: chats, memory, tasks, calendar, reminders, inbox, files

Run: uvicorn server:app --host 127.0.0.1 --port 8000   (install-service.sh sets that up as a service)
"""
import os
import threading
import time
from contextlib import asynccontextmanager

import numpy as np
from fastapi import Body, FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import agenda
import agent  # noqa: F401  (tests reach it as server.agent)
import api_data
import api_settings
import auth
import conversation as conv
import inbox
import interrupts
import jobs
import model_config
import monitor
import phone_bridge
import pwa
import routines
import satellite
import scheduler
import signal_bot
import toolguard
import tools
import voice
from datetime import datetime

sched, rem = conv.sched, conv.rem


# ── what tools.py reaches through hooks (it never imports the server) ──
def _hook_remind(text, when):
    return scheduler.fmt(rem.add(text, when))


def _hook_list_reminders():
    tz = scheduler.get_tz()
    items = rem.list_items()
    return "\n".join(f'{scheduler.fmt(datetime.fromtimestamp(x["due"], tz))}: {x["text"]}' for x in items) or "No pending reminders"


def _hook_cancel_reminder(words):
    x = rem.cancel(words)
    return f'Cancelled: "{x["text"]}"' if x else "No matching reminder found"


def _hook_start_job(task, title):
    j = jobs.manager.submit(task, source="model", name=title)
    return f"Job {j['id']} started in the background. The user gets the result on their phone when it is done. Tell them briefly what you started."


tools.hooks.update(calendar=agenda.store, remind=_hook_remind, list_reminders=_hook_list_reminders,
                   cancel_reminder=_hook_cancel_reminder, send_message=scheduler.send_message, send_file=conv.send_file,
                   call_me=lambda reason: conv.call_user(reason), start_job=_hook_start_job,
                   computer_cfg=lambda: (model_config.reload_if_changed(), dict(model_config.computer))[1], tz=scheduler.get_tz, vision=conv.model_sees,
                   app_aliases=lambda: (model_config.reload_if_changed(), model_config.app_aliases)[1],
                   spotify=lambda: (model_config.reload_if_changed(),
                                    {**model_config.spotify, "aliases": dict(model_config.spotify_aliases),
                                     "token_file": str(model_config.spotify_token_path())})[1])


def _ask_on_signal(text):
    """How toolguard asks for your OK when the request did not come from the dashboard."""
    if not signal_bot.bot.ready():
        return False, "Signal is not running"
    return signal_bot.bot.send(text)


toolguard.ask_signal["send"] = _ask_on_signal


@asynccontextmanager
async def lifespan(app):
    threading.Thread(target=voice.warm_up_whisper, daemon=True, name="whisper-warmup").start()
    sched.start()
    rem.start()
    conv.apply_wake()
    signal_bot.bot.handler = conv.handle_signal
    signal_bot.bot.audio_handler = conv.signal_voice_to_text
    signal_bot.bot.quick = conv.signal_quick
    signal_bot.bot.start()
    jobs.manager.start()
    routines.care.start()
    if monitor.ui_file_version() != monitor.UI_VERSION:
        print(f"[warn] index.html is out of date (it says {monitor.ui_file_version()}, the server needs {monitor.UI_VERSION}): copy the new index.html")
    phone_bridge.start_server()
    agenda.store.start()
    yield
    jobs.manager.stop()
    routines.care.stop()
    agenda.store.stop()
    phone_bridge.stop_server()
    signal_bot.bot.stop()
    conv.wake.stop()
    rem.stop()
    sched.stop()


app = FastAPI(lifespan=lifespan)
app.add_middleware(auth.AuthMiddleware)
app.include_router(api_settings.router)
app.include_router(api_data.router)

# Libraries used by index.html: static/lib/{three,marked,highlight}.min.js and github-dark.min.css
os.makedirs("static/lib", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


# ── the phone app: install it, and share to it (pwa.py) ──
@app.get("/manifest.webmanifest")
def pwa_manifest():
    return Response(pwa.manifest_json(), media_type="application/manifest+json", headers={"Cache-Control": "no-cache"})


@app.get("/sw.js")
def pwa_sw():
    return Response(pwa.SW, media_type="text/javascript", headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@app.get("/icon-{size}.png")
def pwa_icon(size: int):
    return Response(pwa.icon_png(size), media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.post("/share")
def pwa_share_fallback():
    """The service worker normally takes a share before it gets here; this answers when it is not active yet."""
    return HTMLResponse(pwa.SHARE_FALLBACK, status_code=200)


@app.get("/")
def index():
    with open("index.html", encoding="utf-8") as f:
        return HTMLResponse(f.read(), headers={"Cache-Control": "no-cache"})     # always check for a newer page


@app.get("/api/health")
def health():
    """Is the server up, and do the server and the page belong together? (also used by deploy.sh)"""
    return monitor.health()


# ---------- turns, streamed to the page ----------
# One JSON object per line (NDJSON):
#   {"type":"user","text":...,"turn":n,"files":[...]}   what was heard / typed / attached
#   {"type":"thinking","text":...}    thinking piece
#   {"type":"delta","text":...}       reply piece
#   {"type":"reset"}                  text so far was a preamble before tool calls, clear it
#   {"type":"tool", name, args, output}
#   {"type":"approve", id, tool, args, timeout} / {"type":"approved", id, ok}   a risky tool waits for your OK
#   {"type":"files","files":[...]}    a file the model sent you (download card)
#   {"type":"audio","seq":n,"turn":n,"audio":base64 wav}
#   {"type":"done", reply, thinking, tools, rev}   or   {"type":"error","message":...}
class SayIn(BaseModel):
    text: str = ""
    speak: bool = True
    files: list[dict] = []            # photos and files: [{"name": "a.jpg", "data": "<base64>"}]


@app.post("/api/say/stream")
def say_stream(body: SayIn):
    text = body.text.strip()
    recs, problems = conv.prepare_files(body.files) if body.files else ([], [])
    print("Typed:", text, f"(+{len(recs)} file(s))" if body.files else "")
    if body.files and not recs and not text:
        msg = "; ".join(problems) or "no file could be used"
        return conv.stream_job(lambda emit, cancel: emit({"type": "error", "message": msg, "rev": conv.rev[0]}))
    return conv.stream_job(lambda emit, cancel: conv.turn_job(text, body.speak, emit, cancel, attachments=recs, problems=problems))


def _float32(data):
    """Raw float32 samples sent by the page or the laptop (a stray odd byte count must not crash the request)."""
    return np.frombuffer(data[: len(data) // 4 * 4], dtype=np.float32).copy()


@app.post("/talk/stream")
def talk_stream(lang: str = "", data: bytes = Body(..., media_type="application/octet-stream")):
    audio_np = _float32(data)
    if audio_np.size < 8000:
        return conv.stream_job(lambda emit, cancel: emit({"type": "done", "user": "", "reply": "", "thinking": "", "tools": [],
                                                          "rev": conv.rev[0]}))
    return conv.stream_job(lambda emit, cancel: conv.turn_job("", True, emit, cancel, audio=audio_np, lang=lang))


@app.post("/api/heard")
def heard(body: dict = Body(...)):
    """The page says how far the voice got when you cut it off: {turn, seq, offset}."""
    try:
        t, q, off = int(body["turn"]), int(body["seq"]), float(body.get("offset") or 0)
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=400, detail="turn, seq and offset are needed")
    interrupts.mark_heard(t, q, off)
    return {"ok": True}


# ---------- phone calls (phone_bridge.py, its own port) ----------
phone_bridge.backend.turn = lambda text, speak, emit, cancel: conv.turn_job(text, speak, emit, cancel, source="phone")
phone_bridge.backend.transcribe = lambda audio: voice.transcribe(audio)
phone_bridge.backend.speak = lambda text: voice.phone_speak(text)
phone_bridge.backend.heard = interrupts.mark_heard


# ---------- laptop agent (daemon-agent.py): microphone + desktop tools live on another computer ----------
tools.remote["call"] = lambda name, args: satellite.hub.call(name, args)
tools.remote["names"] = lambda: set(model_config.satellite["tools"]) if satellite.enabled() else set()


def sat_auth(request: Request):
    if not satellite.enabled() or not satellite.token_ok(satellite.bearer(request.headers)):
        raise HTTPException(status_code=401, detail="bad satellite token")


@app.websocket("/ws/satellite")
async def ws_satellite(ws: WebSocket):
    await satellite.hub.serve(ws)


@app.get("/api/satellite")
def satellite_status():
    return satellite.hub.status()


@app.get("/api/sat/config")
def sat_config(request: Request):
    sat_auth(request)
    return {"wake": dict(model_config.wake), "tools": list(model_config.satellite["tools"])}


@app.post("/api/sat/transcribe")
def sat_transcribe(request: Request, prompt: str = "", lang: str = "", data: bytes = Body(..., media_type="application/octet-stream")):
    sat_auth(request)
    audio_np = _float32(data)
    if audio_np.size < 1600:
        return {"text": ""}
    return {"text": voice.transcribe(audio_np, prompt=prompt or None, lang=lang)}


@app.post("/api/sat/shot")
def sat_shot(request: Request, ext: str = "jpg", data: bytes = Body(..., media_type="application/octet-stream")):
    """A screenshot the laptop agent took (tools.screenshot asks for it): kept in the Daemon folder."""
    sat_auth(request)
    if not data or len(data) > 15_000_000:
        raise HTTPException(status_code=413, detail="empty or too large")
    return {"name": tools._save_shot(data, ext)}


class SatInboxIn(BaseModel):
    text: str
    tags: list[str] = []


@app.post("/api/sat/inbox")
def sat_inbox(request: Request, body: SatInboxIn):
    """Save a note or link in the inbox with the laptop agent token (for an iOS Shortcut, a script or curl):
    curl -H "Authorization: Bearer TOKEN" -H "Content-Type: application/json" -d '{"text":"https://example.com read later"}' http://SERVER:8000/api/sat/inbox"""
    sat_auth(request)
    try:
        x = inbox.add(body.text, None, body.tags, src="shortcut")
    except ValueError:
        raise HTTPException(status_code=400, detail="write something")
    return {"id": x["id"]}


class SatTurnIn(BaseModel):
    text: str


@app.post("/api/sat/turn")
def sat_turn(request: Request, body: SatTurnIn):
    sat_auth(request)
    text = body.text.strip()
    print("Laptop:", text)
    conv.wake.state.update(command=text, at=time.time())
    return conv.stream_job(lambda emit, cancel: conv.turn_job(text, True, emit, cancel, source="voice"))
