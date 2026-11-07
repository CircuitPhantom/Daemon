"""Dashboard API for settings: model, tools and profiles, voices, cloud model, PIN lock, small preferences, Signal and
phone status, and the tool approvals / tool log (Settings > Security)."""
import re

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import auth
import conversation as conv
import edge_voice
import elevenlabs_tts
import llm
import model_config
import phone_bridge
import scheduler
import signal_bot
import toolguard
import tools
import twilio_call
import uploads
import voice

router = APIRouter()


def _bad_request(e):
    raise HTTPException(status_code=400, detail=str(e))


class SettingsIn(BaseModel):
    model: str | None = None
    think: bool | None = None
    tools: dict[str, bool] | None = None
    memory: dict[str, bool] | None = None
    profile: str | None = None
    wake: dict | None = None
    system_prompt: str | None = None
    reset_prompt: bool | None = None


def tool_descriptions():
    d = {}
    for n, fn in tools.available_functions.items():
        doc = (fn.__doc__ or "").strip().splitlines()
        d[n] = doc[0].strip() if doc else ""
    return d


@router.get("/api/settings")
def get_settings():
    model_config.reload_if_changed()      # pick up manual edits to config.yaml
    active = {getattr(t, "__name__", str(t)) for t in model_config.available_tools}
    return {
        "model": model_config.llm["model"],
        "think": bool(model_config.think),
        "tools": {n: (n in active) for n in tools.available_functions},
        "tool_desc": tool_descriptions(),
        "system_prompt": model_config.system_prompt["content"].strip(),
        "memory": dict(model_config.memory),
        "profiles": {k: list(v) for k, v in model_config.tool_profiles.items()},
        "wake": dict(model_config.wake),
        "wake_status": conv.wake_state(),
    }


@router.post("/api/settings")
def set_settings(s: SettingsIn):
    if s.model and s.model.strip():
        model_config.llm["model"] = s.model.strip()
    if s.think is not None:
        model_config.think = s.think
    if s.tools is not None:
        model_config.available_tools[:] = [
            tools.available_functions[n]
            for n, on in s.tools.items()
            if on and n in tools.available_functions
        ]
    if s.reset_prompt:
        model_config.system_prompt["content"] = model_config.DEFAULT_PROMPT.strip()
    elif s.system_prompt is not None and s.system_prompt.strip():
        model_config.system_prompt["content"] = s.system_prompt.strip()
    if s.profile is not None:
        if s.profile not in model_config.tool_profiles:
            raise HTTPException(status_code=404, detail="profile not found")
        names = model_config.tool_profiles[s.profile]
        model_config.available_tools[:] = [tools.available_functions[n] for n in names if n in tools.available_functions]
    if s.memory is not None:
        for k in ("enabled", "auto_save"):
            if isinstance(s.memory.get(k), bool):
                model_config.memory[k] = s.memory[k]
    restart_wake = False
    if s.wake is not None:
        for k, default in model_config.DEFAULTS["wake"].items():
            if k not in s.wake:
                continue
            v = s.wake[k]
            if isinstance(default, bool):
                ok = isinstance(v, bool)
            elif isinstance(default, int):
                ok = isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 60
            else:
                ok = isinstance(v, str)
                v = v.strip() if ok else v
            if not ok:
                raise HTTPException(status_code=400, detail=f"bad value for wake.{k}")
            if k == "engine" and v not in ("whisper", "openwakeword"):
                raise HTTPException(status_code=400, detail="wake.engine must be whisper or openwakeword")
            if model_config.wake[k] != v:
                model_config.wake[k] = v
                restart_wake = True
    model_config.save()                   # persist changes to config.yaml
    if restart_wake:
        conv.apply_wake()
    return get_settings()


class ProfileIn(BaseModel):
    tools: list[str]


@router.put("/api/profiles/{name}")
def save_profile(name: str, body: ProfileIn):
    name = name.strip()[:40]
    if not name:
        _bad_request("name is empty")
    model_config.tool_profiles[name] = [t for t in dict.fromkeys(body.tools) if t in tools.available_functions]
    model_config.save()
    return {"profiles": model_config.tool_profiles}


@router.delete("/api/profiles/{name}")
def delete_profile(name: str):
    if model_config.tool_profiles.pop(name, None) is None:
        raise HTTPException(status_code=404, detail="profile not found")
    model_config.save()
    return {"profiles": model_config.tool_profiles}


@router.get("/api/wake")
def wake_status():
    return conv.wake_state()



@router.post("/api/notify/test")
def notify_test():
    link = scheduler.run_link("test")
    text = "Daemon · test message\nIf you can read this, notifications work."
    ok, info = scheduler.send_message(text)
    return {"ok": ok, "info": info, "link": bool(link)}


@router.post("/api/notify/test-call")
def notify_test_call():
    if not twilio_call.configured():
        return {"ok": False, "info": "not configured: set notify.twilio_sid, twilio_token, twilio_from in config.yaml"}
    if phone_bridge.available():
        ok, info = twilio_call.place_talk_call("Daemon test call. Say something and I will answer.")
    else:
        ok, info = twilio_call.place_call("Daemon test call. If you can hear this, phone calls work.")
    return {"ok": ok, "info": info, "conversation": phone_bridge.available()}


@router.get("/api/phone")
def phone_status():
    c = phone_bridge._cfg()
    return {"enabled": c["enabled"], "listening": phone_bridge.state["server"],
            "available": phone_bridge.available(), "calls": phone_bridge.state["calls"],
            "last_call": phone_bridge.state["last"], "public_url": c["url"],
            "incoming_webhook": c["url"] + "/phone/incoming" if c["url"] else ""}


# ---------- the model ----------
@router.get("/api/llm")
def llm_status():
    model_config.reload_if_changed()
    return llm.status()


@router.post("/api/llm/test")
def llm_test():
    """Sends one tiny request to the model to check the key, address and model name."""
    model_config.reload_if_changed()
    return llm.test()


# ---------- voice (ElevenLabs / local) ----------
@router.get("/api/tts")
def tts_status():
    model_config.reload_if_changed()
    return {**elevenlabs_tts.status(), "edge": edge_voice.status()}


@router.post("/api/tts")
def tts_set(body: dict = Body(...)):
    """The dashboard: {local_only: bool} and/or {edge_first: bool} and/or {edge_voice: "en-US-AriaNeural"}."""
    if not any(k in body for k in ("local_only", "edge_first", "edge_voice")):
        raise HTTPException(status_code=400, detail="nothing to change")
    if "local_only" in body:
        if not isinstance(body["local_only"], bool):
            raise HTTPException(status_code=400, detail="local_only must be true or false")
        model_config.elevenlabs["local_only"] = body["local_only"]
    if "edge_first" in body:
        if not isinstance(body["edge_first"], bool):
            raise HTTPException(status_code=400, detail="edge_first must be true or false")
        model_config.edge_tts["primary"] = body["edge_first"]
        if body["edge_first"]:
            model_config.edge_tts["enabled"] = True
    if "edge_voice" in body:
        v = body["edge_voice"]
        if not isinstance(v, str) or not re.fullmatch(r"[A-Za-z]{2,3}-[A-Za-z0-9-]{2,30}Neural", v.strip()):
            raise HTTPException(status_code=400, detail="edge_voice must look like en-US-AriaNeural")
        model_config.edge_tts["voice"] = v.strip()
    edge_voice.reset()
    model_config.save()
    return {**elevenlabs_tts.status(), "edge": edge_voice.status()}


@router.post("/api/tts/test")
def tts_test(engine: str = ""):
    """Speaks one sentence to check the key, voice and model. ?engine=edge tests the Edge voice, else ElevenLabs."""
    model_config.reload_if_changed()
    return edge_voice.test() if engine == "edge" else elevenlabs_tts.test()


# ---------- PIN lock ----------
def _client(request):
    return request.client.host if request.client else "?"


def _secure(request):
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


def _authed(request):
    return (not auth.active()) or auth.valid_token(request.cookies.get(auth.COOKIE, ""))


@router.get("/api/auth/status")
def auth_status(request: Request):
    return {"enabled": auth.active(), "has_pin": bool(auth.cfg()["pin_hash"]), "authed": _authed(request)}


def _check_pin_or_fail(request, pin):
    who = _client(request)
    wait = auth.locked_for(who)
    if wait:
        raise HTTPException(status_code=429, detail=f"too many wrong PINs, try again in {wait} s")
    if not auth.check_pin(str(pin or ""), auth.cfg()["pin_hash"]):
        auth.failed(who)
        raise HTTPException(status_code=403, detail="Wrong PIN")
    auth.succeeded(who)


@router.post("/api/auth/login")
def auth_login(request: Request, body: dict = Body(...)):
    if not auth.active():
        return {"ok": True}
    _check_pin_or_fail(request, body.get("pin"))
    r = JSONResponse({"ok": True})
    r.headers["set-cookie"] = auth.cookie_header(auth.make_token(), _secure(request))
    return r


@router.post("/api/auth/logout")
def auth_logout():
    r = JSONResponse({"ok": True})
    r.headers["set-cookie"] = auth.clear_cookie_header()
    return r


@router.post("/api/auth/pin")
def auth_set_pin(request: Request, body: dict = Body(...)):
    """Sets (or changes) the PIN and turns the lock on. Changing needs the current PIN."""
    if auth.active():
        _check_pin_or_fail(request, body.get("current"))
    try:
        auth.set_pin(body.get("pin"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    r = JSONResponse({"ok": True, "enabled": True})
    r.headers["set-cookie"] = auth.cookie_header(auth.make_token(), _secure(request))     # this browser stays logged in
    return r


@router.post("/api/auth/disable")
def auth_disable(request: Request, body: dict = Body(...)):
    if auth.active():
        _check_pin_or_fail(request, body.get("current"))
        auth.disable()
    return {"ok": True, "enabled": False}


class PrefsIn(BaseModel):
    uploads: dict | None = None
    elevenlabs: dict | None = None
    phone: dict | None = None


def _num(v, lo, hi, kind=float):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise HTTPException(status_code=400, detail="a number is needed")
    return kind(min(hi, max(lo, v)))


def prefs_view():
    model_config.reload_if_changed()
    e, u, p = model_config.elevenlabs, model_config.uploads, model_config.phone_cfg
    return {
        "uploads": {"enabled": bool(u["enabled"]), "vision": (lambda v: v if v in ("auto", "true", "false") else "auto")(str(u["vision"]).lower()),
                    "max_mb": int(u["max_mb"]), "dir": uploads.base_dir().as_posix()},
        "elevenlabs": {"audio_tags": bool(e["audio_tags"]), "audio_tags_use": str(e["audio_tags_use"] or "normal").lower(),
                       "model": e["model"], "configured": bool(e["api_key"]), "effects_active": bool(voice.voice_tags_on())},
        "phone": {"enabled": bool(p["enabled"]), "speech_level": float(p["speech_level"]), "noise_mult": float(p["noise_mult"]),
                  "min_speech_ms": int(p["min_speech_ms"]), "barge_ms": int(p["barge_ms"])},
    }


@router.get("/api/prefs")
def get_prefs():
    return prefs_view()


@router.post("/api/prefs")
def set_prefs(body: PrefsIn):
    """Small settings that used to need a hand edit of config.yaml. Only the keys you send change."""
    u, e, p = body.uploads or {}, body.elevenlabs or {}, body.phone or {}
    with conv.lock:
        model_config.reload_if_changed()
        if "enabled" in u:
            model_config.uploads["enabled"] = bool(u["enabled"])
        if "vision" in u:
            if str(u["vision"]).lower() not in ("auto", "true", "false"):
                raise HTTPException(status_code=400, detail="vision must be auto, true or false")
            model_config.uploads["vision"] = str(u["vision"]).lower()
        if "max_mb" in u:
            model_config.uploads["max_mb"] = _num(u["max_mb"], 1, 200, int)
        if "audio_tags" in e:
            model_config.elevenlabs["audio_tags"] = bool(e["audio_tags"])
        if "audio_tags_use" in e:
            if str(e["audio_tags_use"]).lower() not in ("rare", "normal", "lively"):
                raise HTTPException(status_code=400, detail="audio_tags_use must be rare, normal or lively")
            model_config.elevenlabs["audio_tags_use"] = str(e["audio_tags_use"]).lower()
        for k, lo, hi, kind in (("speech_level", 0.005, 0.1, float), ("noise_mult", 1, 10, float),
                                ("min_speech_ms", 40, 800, int), ("barge_ms", 150, 2000, int)):
            if k in p:
                model_config.phone_cfg[k] = _num(p[k], lo, hi, kind)
        model_config.save()
    return prefs_view()


@router.get("/api/signal")
def signal_status():
    return signal_bot.bot.status()


# ---------- tool approvals and the tool log (toolguard.py) ----------
@router.get("/api/security")
def security_get():
    model_config.reload_if_changed()
    c = model_config.security
    names = [t for t in toolguard.CHOICES if t in tools.available_functions]
    return {"confirm": c["confirm"], "confirm_tools": list(c["confirm_tools"]), "confirm_seconds": c["confirm_seconds"],
            "choices": names, "desc": {n: (tools.available_functions[n].__doc__ or "").strip().split("\n")[0] for n in names}}


@router.post("/api/security")
def security_set(body: dict = Body(...)):
    c = model_config.security
    if "confirm" in body:
        if not isinstance(body["confirm"], bool):
            _bad_request("confirm must be true or false")
        c["confirm"] = body["confirm"]
    if "confirm_tools" in body:
        t = body["confirm_tools"]
        if not isinstance(t, list) or any(not isinstance(x, str) or x not in tools.available_functions for x in t):
            _bad_request("confirm_tools must be a list of tool names")
        c["confirm_tools"] = list(dict.fromkeys(t))
    if "confirm_seconds" in body:
        s = body["confirm_seconds"]
        if not isinstance(s, int) or isinstance(s, bool) or not 15 <= s <= 600:
            _bad_request("confirm_seconds must be 15 to 600")
        c["confirm_seconds"] = s
    model_config.save()
    return security_get()


@router.get("/api/approvals")
def approvals_list():
    return {"approvals": toolguard.open_requests(), "version": toolguard.version[0]}


@router.post("/api/approvals/{rid}")
def approvals_answer(rid: str, body: dict = Body(...)):
    if not isinstance(body.get("ok"), bool):
        _bad_request("ok must be true or false")
    if not toolguard.answer(rid, body["ok"]):
        raise HTTPException(status_code=404, detail="this request is no longer open")
    return {"ok": True}


@router.get("/api/toollog")
def tool_log(limit: int = 100):
    return {"items": toolguard.recent(max(1, min(500, limit)))}


# ---------- looking after itself: alerts, memory check, morning plan extras (care, routines.py, monitor.py) ----------
def care_view():
    import monitor
    model_config.reload_if_changed()
    return {"care": dict(model_config.care), "checks": monitor.checks(), "health": monitor.health()}


@router.get("/api/care")
def care_get():
    return care_view()


@router.post("/api/care")
def care_set(body: dict = Body(...)):
    c = model_config.care
    limits = {"watch_minutes": (1, 1440), "disk_free_percent": (1, 90), "backup_max_hours": (1, 24 * 60),
              "laptop_grace_minutes": (1, 1440), "alert_repeat_hours": (1, 24 * 14), "memory_review_day": (0, 6)}
    with conv.lock:
        for k, v in body.items():
            if k not in c:
                _bad_request(f"unknown setting: {k}")
            if isinstance(model_config.DEFAULTS["care"][k], bool):
                if not isinstance(v, bool):
                    _bad_request(f"{k} must be true or false")
                c[k] = v
            elif k in limits:
                lo, hi = limits[k]
                if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
                    _bad_request(f"{k} must be a whole number from {lo} to {hi}")
                c[k] = v
            elif k.endswith("_time"):
                if not isinstance(v, str) or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v.strip()):
                    _bad_request(f"{k} must look like 10:00")
                c[k] = v.strip()
            else:
                c[k] = str(v).strip()[:60]
        model_config.save()
    return care_view()


@router.post("/api/care/run")
def care_run(body: dict = Body(...)):
    """Try it now: {"what": "alert"} sends a test alert, {"what": "memory"} the memory check, {"what": "briefing"} the plan."""
    import agenda
    import routines
    what = body.get("what")
    if what == "alert":
        ok, info = scheduler.send_message("✅ Daemon test alert: this is how a problem would reach you.")
        return {"ok": ok, "info": "sent" if ok else info}
    if what == "memory":
        text = routines.memory_report()
        if not text:
            return {"ok": True, "info": "nothing to report: no doubled or very old memories"}
        ok, info = scheduler.send_message(text)
        return {"ok": ok, "info": "sent" if ok else info}
    if what == "briefing":
        r = agenda.store.brief(manual=True)
        return {"ok": bool(r["message"]), "info": r["info"]}
    _bad_request("what must be alert, memory or briefing")
