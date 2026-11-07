"""Phone calls through Twilio (https://www.twilio.com).

Stage 1: Daemon rings your phone and reads a short message aloud. No public URL is needed,
the spoken text travels inside the API request (inline TwiML).

Settings live in config.yaml under notify:
  twilio_sid, twilio_token   Account SID and Auth Token (keep config.yaml private)
  twilio_from                your Twilio number, e.g. "+15551234567"
  twilio_to                  the phone to ring, e.g. "+905551234567"
  twilio_language            language of the spoken text, default en-US
  twilio_voice               Twilio voice, default alice
  twilio_ring_seconds        how long it rings before giving up, default 30
  twilio_max_per_hour        safety limit against runaway costs, default 6
  twilio_reminders           also ring for reminders, default false
"""
import base64
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from xml.sax.saxutils import escape

import model_config

API = "https://api.twilio.com"          # tests point this at a local fake
SPOKEN_CHARS = 380
_lock = threading.Lock()
_recent = []                            # monotonic times of recent calls

# Twilio error codes people commonly hit, with what to do about them
HINTS = {
    20003: "wrong Account SID or Auth Token",
    21205: "twilio_to is not a valid phone number",
    21210: "twilio_from is not a number on this Twilio account",
    21211: "twilio_to is not a valid phone number",
    21215: "calls to this country are off: Console > Voice > Geo Permissions, enable it",
    21216: "calls to this country are off: Console > Voice > Geo Permissions, enable it",
    21217: "twilio_to is not a valid phone number",
    21219: "trial account: verify this number first (Console > Phone Numbers > Verified Caller IDs)",
    21608: "trial account: verify this number first (Console > Phone Numbers > Verified Caller IDs)",
    21614: "twilio_to is not a mobile or landline number",
}


def _cfg():
    n = model_config.notify
    return {
        "sid": str(n.get("twilio_sid") or "").strip(),
        "token": str(n.get("twilio_token") or "").strip(),
        "from": _plus(n.get("twilio_from")),
        "to": _plus(n.get("twilio_to")),
        "lang": str(n.get("twilio_language") or "en-US").strip(),
        "voice": str(n.get("twilio_voice") or "alice").strip(),
        "ring": _int(n.get("twilio_ring_seconds"), 30, 5, 60),
        "max_per_hour": _int(n.get("twilio_max_per_hour"), 6, 1, 60),
    }


def _int(v, default, lo, hi):
    try:
        v = int(v)
    except (TypeError, ValueError):
        return default
    return min(hi, max(lo, v))


def _plus(v):
    s = re.sub(r"[\s\-()]", "", str(v or ""))
    return s if not s or s.startswith("+") else "+" + s


def configured():
    c = _cfg()
    return bool(c["sid"] and c["token"] and c["from"] and c["to"])


def reminders_enabled():
    return bool(model_config.notify.get("twilio_reminders")) and configured()


def spoken_text(text, limit=SPOKEN_CHARS):
    """Plain, short text that sounds fine on the phone: no markdown, links or emoji."""
    t = re.sub(r"```.*?```", " code omitted ", str(text), flags=re.S)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"[*_#`>|~]+", "", t)
    t = re.sub(r"[^\w\s.,!?;:'\"()%/+\-]", " ", t)       # emoji and symbols
    t = " ".join(t.split())
    if len(t) > limit:
        cut = t.rfind(" ", 0, limit)
        t = t[: cut if cut > limit // 2 else limit].rstrip(" ,;:") + "..."
    return t


def build_twiml(text, lang="en-US", voice="alice"):
    """Waits a second (the first words get lost when you pick up), reads the text, pauses, and reads it once more."""
    q = lambda s: escape(s, {'"': "&quot;"})
    say = f'<Say language="{q(lang)}" voice="{q(voice)}">{escape(text)}</Say>'
    return f'<Response><Pause length="1"/>{say}<Pause length="2"/>{say}</Response>'


def _error_text(code, body):
    try:
        d = json.loads(body)
    except Exception:
        return None
    c = d.get("code")
    msg = str(d.get("message") or "")[:160]
    hint = HINTS.get(c)
    return f"Twilio {c}: {hint}" if hint else (f"Twilio {c}: {msg}" if c else msg or None)


def _allow():
    """At most twilio_max_per_hour calls per hour."""
    limit = _cfg()["max_per_hour"]
    now = time.monotonic()
    with _lock:
        _recent[:] = [t for t in _recent if now - t < 3600]
        if len(_recent) >= limit:
            return False
        _recent.append(now)
        return True


def place_call(text, lang=None, voice=None):
    """Rings the phone and reads `text`. Returns (ok, info). Never raises."""
    c = _cfg()
    say = spoken_text(text)
    if not say:
        return False, "nothing to say"
    return place_twiml(build_twiml(say, lang or c["lang"], voice or c["voice"]))


def place_talk_call(greeting, notice=""):
    """Rings the phone and starts a conversation (phone_bridge.py). Reads `greeting` first.

    Falls back to a plain spoken call when the bridge is not available.
    """
    import phone_bridge
    if not phone_bridge.available():
        return place_call(greeting)
    return place_twiml(phone_bridge.stream_twiml(spoken_text(greeting, 700), notice))


def place_twiml(twiml):
    """Rings the phone and runs `twiml` when it is picked up. Returns (ok, info). Never raises."""
    c = _cfg()
    if not (c["sid"] and c["token"] and c["from"] and c["to"]):
        return False, ("not configured (set notify.twilio_sid, twilio_token, twilio_from "
                       "and twilio_to in config.yaml)")
    if not _allow():
        return False, f"limit reached ({c['max_per_hour']} calls per hour, notify.twilio_max_per_hour)"
    data = urllib.parse.urlencode({
        "To": c["to"], "From": c["from"], "Twiml": twiml, "Timeout": c["ring"],
    }).encode()
    url = f"{API}/2010-04-01/Accounts/{urllib.parse.quote(c['sid'])}/Calls.json"
    auth = base64.b64encode(f"{c['sid']}:{c['token']}".encode()).decode()
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": "Basic " + auth, "User-Agent": "daemon/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read(20000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = e.read(5000).decode("utf-8", "replace")
        return False, _error_text(e.code, body) or f"HTTP {e.code}"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e).replace(c['token'], '***')}"
    try:
        sid = json.loads(body).get("sid", "")
    except Exception:
        sid = ""
    return True, f"calling {c['to']}" + (f" ({sid})" if sid else "")


def call_text(task_name, reply, tail=""):
    """What is said when a task wants your attention."""
    parts = ["Daemon.", f"{task_name}.", spoken_text(reply, 300)]
    if tail:
        parts.append(tail)
    return " ".join(p for p in parts if p)
