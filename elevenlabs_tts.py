"""ElevenLabs voice with automatic fallback to the local Kokoro voice.

Settings live in config.yaml (keep the file private, it holds the key):

  elevenlabs:
    enabled: true
    api_key: "sk_..."            # elevenlabs.io > Developers > API Keys
    voice_id: ""                 # empty = the first voice of your account; copy an ID from "My Voices" to choose
    model: eleven_flash_v2_5     # cheap and fast (0.5 credit per character). eleven_multilingual_v2 = 1 credit
    language: ""                 # e.g. "tr" to force Turkish; empty = detected from the text
    local_only: false            # the dashboard switch: true = always use the local voice
    fallback: true               # on errors or when your credits run out use the local voice (false = stay silent)
    monthly_chars: 0             # your own limit of characters per month, 0 = only ElevenLabs' own limit

When ElevenLabs cannot be used (credits used up, wrong key, no internet, too many requests) Daemon uses the local
voice for a while and then tries again by itself. When the credits run out you also get a Signal message.
"""
import io
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from datetime import datetime
from pathlib import Path

import audio_fx
import model_config

BASE = "https://api.elevenlabs.io"          # tests point this at a local fake
RATE = 24000                                 # pcm_24000: raw 16-bit mono, allowed on every plan
TIMEOUT = 20
COOLDOWN = {"quota": 3600, "rate": 30, "network": 60, "key": 600, "text": 0}   # "text": this sentence was refused, the voice itself is fine
_lock = threading.RLock()
_s = {"down_until": 0.0, "reason": "", "kind": "", "key": "", "quota": None, "quota_at": 0.0,
      "voice": None, "notified": False, "last_error": "", "last_ok": 0.0}


def _cfg():
    return model_config.elevenlabs


def _usage_path():
    return Path(os.environ.get("DAEMON_TTS_USAGE") or model_config.CONFIG_PATH.with_name("tts_usage.json"))


def reset():
    """Forget errors and cached values (used by tests and when the key changes)."""
    with _lock:
        _s.update(down_until=0.0, reason="", kind="", quota=None, quota_at=0.0, voice=None, notified=False, last_error="")


# ── how many characters were sent this month (for monthly_chars) ──
def month_chars():
    try:
        d = json.loads(_usage_path().read_text(encoding="utf-8"))
        return int(d["chars"]) if d.get("month") == datetime.now().strftime("%Y-%m") else 0
    except Exception:
        return 0


def _add_chars(n):
    try:
        with _lock:                                        # two voices at once (phone + page) must not lose a count
            model_config.atomic_write(_usage_path(), json.dumps({"month": datetime.now().strftime("%Y-%m"),
                                                                 "chars": month_chars() + n}))
    except Exception as e:
        print("[elevenlabs] could not save usage:", e)


# ── HTTP ──
class ApiError(Exception):
    def __init__(self, status, code, message):
        super().__init__(f"{status} {code}: {message}")
        self.status, self.code, self.message = status, code, message


def _request(method, path, body=None, accept="application/json"):
    c = _cfg()
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={
        "xi-api-key": c["api_key"], "Content-Type": "application/json", "Accept": accept, "User-Agent": "daemon/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raw = e.read(4000).decode("utf-8", "replace")
        code, msg = "", raw[:160]
        try:
            d = json.loads(raw).get("detail")
            if isinstance(d, dict):
                code, msg = str(d.get("status") or ""), str(d.get("message") or "")[:160]
            elif isinstance(d, str):
                msg = d[:160]
        except Exception:
            pass
        raise ApiError(e.code, code, msg) from None


def _classify(e):
    """(kind, reason) of an error: quota / key / rate / network."""
    if isinstance(e, ApiError):
        text = (e.code + " " + e.message).lower()
        if "quota" in text or "credit" in text or e.code == "insufficient_credits":
            return "quota", "credits used up"
        if e.status in (401, 403):
            return "key", "ElevenLabs refused the key or voice (" + (e.code or str(e.status)) + ")"
        if e.status == 429:
            return "rate", "too many requests" + (" at once (your plan allows few simultaneous requests)" if "concurrent" in text else "")
        if e.status in (400, 404, 422):
            if e.status == 404 or "model" in text or "voice" in text:
                return "key", "ElevenLabs rejected the voice_id or model (" + (e.message or str(e.status)) + ")"
            return "text", f"ElevenLabs refused one sentence ({e.status}: {e.message or e.code})"
        return "network", f"ElevenLabs error {e.status}" + (f": {e.message}" if e.message else "")
    return "network", f"{type(e).__name__}: {e}"


def _notify(text):
    def go():
        try:
            import scheduler
            scheduler.send_message(text)
        except Exception as e:
            print("[elevenlabs] could not send the notice:", e)
    threading.Thread(target=go, daemon=True).start()


def _go_down(kind, reason):
    if kind == "text":
        print(f"[elevenlabs] {reason}; this sentence uses the next voice")
        with _lock:
            _s["last_error"] = reason
        return
    with _lock:
        _s.update(down_until=time.time() + COOLDOWN[kind], reason=reason, kind=kind, last_error=reason)
        first = not _s["notified"] and kind in ("quota", "key")
        if first:
            _s["notified"] = True
    print(f"[elevenlabs] using the local voice for now: {reason}")
    if first:
        _notify(f"Daemon: ElevenLabs voice stopped ({reason}). Using the local voice until it works again.")


# ── account info ──
def _factor():
    m = _cfg()["model"].lower()
    return 0.5 if ("flash" in m or "turbo" in m) else 1.0


def refresh_quota():
    """Reads used/limit credits of the account (needs a key that may read the user subscription; silently skipped if not)."""
    try:
        d = json.loads(_request("GET", "/v1/user/subscription"))
        q = {"used": int(d["character_count"]), "limit": int(d["character_limit"]),
             "reset": int(d.get("next_character_count_reset_unix") or 0)}
    except Exception as e:
        q = None
        if not isinstance(e, ApiError):
            print("[elevenlabs] could not read the credits:", e)
    with _lock:
        _s["quota"], _s["quota_at"] = q, time.time()
    return q


def _quota_async():
    with _lock:
        if time.time() - _s["quota_at"] < 300:
            return
        _s["quota_at"] = time.time()                 # one refresh at a time
    threading.Thread(target=refresh_quota, daemon=True).start()


def resolve_voice():
    """The voice_id to use: the configured one, else the first voice of the account."""
    c = _cfg()
    if c["voice_id"]:
        return c["voice_id"]
    with _lock:
        if _s["voice"]:
            return _s["voice"]
    d = json.loads(_request("GET", "/v1/voices"))
    voices = d.get("voices") or []
    pick = next((v for v in voices if v.get("category") == "premade"), voices[0] if voices else None)
    if not pick:
        raise ApiError(404, "no_voice", "this account has no voices; set elevenlabs.voice_id")
    print(f"[elevenlabs] no voice_id set, using {pick.get('name')} ({pick['voice_id']})")
    with _lock:
        _s["voice"] = pick["voice_id"]
    return pick["voice_id"]


# ── decide and speak ──
def state():
    """Why ElevenLabs is (not) used right now: (usable, text)."""
    c = _cfg()
    if not c["enabled"]:
        return False, "off"
    if not c["api_key"]:
        return False, "no api_key in config.yaml"
    if c["local_only"]:
        return False, "local voice only (switch)"
    with _lock:
        if _s["key"] != c["api_key"]:                # a new key: forget old errors
            _s["key"] = c["api_key"]
            _s.update(down_until=0.0, reason="", kind="", quota=None, quota_at=0.0, voice=None, notified=False)
        if _s["down_until"] > time.time():
            return False, _s["reason"]
    if c["monthly_chars"] and month_chars() >= c["monthly_chars"]:
        return False, f"monthly_chars limit reached ({c['monthly_chars']})"
    return True, "ok"


def speak(text):
    """WAV bytes of `text` from ElevenLabs, or None when the local voice should be used instead."""
    ok, why = state()
    if not ok:
        return None
    c = _cfg()
    n = len(text)
    if c["monthly_chars"] and month_chars() + n > c["monthly_chars"]:
        return None
    with _lock:
        q = _s["quota"]
    if q and q["limit"] and q["used"] + n * _factor() > q["limit"]:
        _go_down("quota", "credits used up")
        return None
    try:
        try:
            data = _synth(text)
        except Exception as e:
            transient = (isinstance(e, ApiError) and (e.status >= 500 or e.status == 429)) or \
                (not isinstance(e, ApiError) and "timed out" not in str(e).lower())
            if not transient:
                raise
            time.sleep(0.4)                          # one quick retry: a single hiccup should not switch the voice
            data = _synth(text)
    except Exception as e:
        kind, reason = _classify(e)
        _go_down(kind, reason)
        return None
    _add_chars(n)
    with _lock:
        _s["last_ok"] = time.time()
        _s["notified"] = False
        if _s["kind"]:
            _s.update(kind="", reason="")
    _quota_async()
    return data


def _synth(text):
    c = _cfg()
    body = {"text": text, "model_id": c["model"]}
    if c["language"]:
        body["language_code"] = c["language"]
    path = f"/v1/text-to-speech/{urllib.parse.quote(resolve_voice())}?output_format=pcm_{RATE}"
    pcm = _request("POST", path, body, accept="audio/pcm")
    if len(pcm) < 200:
        raise ApiError(502, "empty", "ElevenLabs returned no audio")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(audio_fx.clean_pcm(pcm, RATE))
    return buf.getvalue()


def test(text="Hello, this is a test of the ElevenLabs voice."):
    """Tries once, ignoring the switch and any cooldown. Returns {ok, info}."""
    c = _cfg()
    if not c["api_key"]:
        return {"ok": False, "info": "set elevenlabs.api_key in config.yaml"}
    t0 = time.time()
    try:
        data = _synth(text)
    except Exception as e:
        kind, reason = _classify(e)
        return {"ok": False, "info": reason + (f": {e.message}" if isinstance(e, ApiError) and e.message else "")}
    with _lock:
        _s.update(down_until=0.0, reason="", kind="", notified=False)
        v = _s["voice"] or c["voice_id"]
    refresh_quota()
    return {"ok": True, "info": f"{len(data) // 1024} KB in {time.time() - t0:.1f} s (voice {v}, model {c['model']})"}


def status():
    c = _cfg()
    usable, why = state()
    if c["enabled"] and c["api_key"]:
        _quota_async()
    with _lock:
        q = dict(_s["quota"]) if _s["quota"] else None
        down = max(0, int(_s["down_until"] - time.time()))
    return {"enabled": c["enabled"], "configured": bool(c["api_key"]), "local_only": c["local_only"],
            "fallback": c["fallback"], "active": usable, "why": why, "retry_in": down, "model": c["model"],
            "month_chars": month_chars(), "monthly_chars": c["monthly_chars"], "quota": q}
