"""Speech-to-text in the cloud (Groq, OpenAI or any /audio/transcriptions API), with automatic fallback to the local Whisper.

Useful when the computer running Daemon is slow at Whisper (phone calls, dashboard voice). config.yaml:

  stt_cloud:
    enabled: true
    base_url: https://api.groq.com/openai/v1     # Groq has a free tier; OpenAI: https://api.openai.com/v1
    api_key: "gsk_..."
    model: whisper-large-v3-turbo                 # OpenAI: whisper-1 or gpt-4o-mini-transcribe
    language: ""                                  # e.g. "tr" or "en"; empty = detected (a fixed language is faster and safer for short phrases)
    timeout: 20

If the cloud fails (key, limit, network) the local Whisper (stt.model) is used for a while, then the cloud is tried again.
"""
import io
import json
import threading
import time
import urllib.error
import urllib.request
import uuid
import wave

import numpy as np

import model_config

COOLDOWN = {"key": 600, "rate": 30, "network": 30}
_lock = threading.Lock()
_s = {"down_until": 0.0, "reason": "", "last_ok": 0.0}


def usable():
    c = model_config.stt_cloud
    if not (c["enabled"] and c["api_key"] and c["base_url"]):
        return False
    with _lock:
        return _s["down_until"] <= time.time()


def reset():
    with _lock:
        _s.update(down_until=0.0, reason="")


def status():
    c = model_config.stt_cloud
    with _lock:
        left = max(0, int(_s["down_until"] - time.time()))
        return {"enabled": c["enabled"], "configured": bool(c["api_key"]), "model": c["model"],
                "active": c["enabled"] and bool(c["api_key"]) and not left, "why": _s["reason"], "retry_in": left}


def wav(audio, rate=16000):
    pcm = (np.clip(np.asarray(audio, dtype=np.float32), -1, 1) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def _multipart(fields, filename, data):
    b = uuid.uuid4().hex
    out = io.BytesIO()
    for k, v in fields.items():
        out.write(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    out.write(f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: audio/wav\r\n\r\n'.encode())
    out.write(data + f"\r\n--{b}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={b}"


def _classify(e):
    if isinstance(e, urllib.error.HTTPError):
        if e.code in (401, 403, 404):
            return "key", f"the speech-to-text service refused the key or model ({e.code})"
        if e.code == 429:
            return "rate", "speech-to-text rate limit"
        return "network", f"speech-to-text error {e.code}"
    return "network", f"{type(e).__name__}: {e}"


def transcribe(audio, prompt=None, lang=""):
    """Text of a float32 16 kHz array. Raises on any problem (the caller then uses the local Whisper)."""
    c = model_config.stt_cloud
    fields = {"model": c["model"], "response_format": "json", "temperature": "0"}
    language = lang or c["language"]
    if language:
        fields["language"] = language
    if prompt:
        fields["prompt"] = prompt[:200]
    body, ctype = _multipart(fields, "speech.wav", wav(audio))
    req = urllib.request.Request(c["base_url"].rstrip("/") + "/audio/transcriptions", data=body, method="POST", headers={
        "Authorization": "Bearer " + c["api_key"], "Content-Type": ctype, "User-Agent": "daemon/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=c["timeout"]) as r:
            text = str(json.loads(r.read()).get("text", "")).strip()
    except Exception as e:
        kind, reason = _classify(e)
        with _lock:
            _s.update(down_until=time.time() + COOLDOWN[kind], reason=reason)
        print(f"[stt-cloud] using the local Whisper for now: {reason}")
        raise
    with _lock:
        _s.update(last_ok=time.time(), reason="")
    return text
