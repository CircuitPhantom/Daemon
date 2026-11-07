"""PIN lock for the dashboard.

Off by default. Turn it on in the dashboard (Settings > PIN lock), with `python set_pin.py`, or by hand in config.yaml:

  auth:
    enabled: true        # false = no PIN asked (use this if you ever lock yourself out)
    pin_hash: ...        # written by set_pin.py / the dashboard, never type a PIN here
    secret: ...          # signs the login cookie; changes whenever the PIN changes (logs everyone out)

When it is on, every page and API of the dashboard needs the login cookie (30 days). The phone call
bridge (phone_bridge.py, its own port) is not affected, Twilio checks its own signature there.
"""
import hashlib
import hmac
import json
import secrets
import threading
import time

import model_config

COOKIE = "daemon_session"
SESSION_SECONDS = 30 * 86400
MIN_PIN, MAX_PIN = 4, 64
_lock = threading.Lock()
_fails = {}                                  # client -> [count, locked_until]
OPEN_PATHS = {"/api/auth/login", "/api/auth/status", "/api/health", "/manifest.webmanifest", "/sw.js", "/icon-192.png", "/icon-512.png"}
TOKEN_PREFIXES = ("/api/sat/", "/ws/satellite")      # the laptop agent: checked with its own token (satellite.py)


def cfg():
    return model_config.auth_cfg


def active():
    """The lock is on only when it is enabled AND a PIN exists (so a half-edited config never locks you out)."""
    model_config.reload_if_changed()
    c = cfg()
    return bool(c["enabled"] and c["pin_hash"] and c["secret"])


# ── PIN hashing ──
def hash_pin(pin):
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pin.encode(), salt=salt, n=2 ** 14, r=8, p=1)
    return "scrypt$" + salt.hex() + "$" + h.hex()


def check_pin(pin, stored):
    try:
        _, salt, h = stored.split("$")
        got = hashlib.scrypt(str(pin).encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1)
        return hmac.compare_digest(got.hex(), h)
    except Exception:
        return False


def valid_pin(pin):
    p = str(pin or "")
    if not MIN_PIN <= len(p) <= MAX_PIN or p != p.strip():
        raise ValueError(f"the PIN needs {MIN_PIN} to {MAX_PIN} characters, without spaces at the ends")
    return p


def set_pin(pin, enable=True):
    """Stores a new PIN (and a new cookie secret, which logs every browser out) and saves config.yaml."""
    p = valid_pin(pin)
    c = cfg()
    c["pin_hash"] = hash_pin(p)
    c["secret"] = secrets.token_hex(32)
    c["enabled"] = bool(enable)
    model_config.save()


def disable():
    cfg()["enabled"] = False
    model_config.save()


# ── cookie ──
def _sign(body):
    return hmac.new(cfg()["secret"].encode(), body.encode(), hashlib.sha256).hexdigest()


def make_token():
    body = f"{int(time.time()) + SESSION_SECONDS}.{secrets.token_hex(8)}"
    return body + "." + _sign(body)


def valid_token(tok):
    try:
        exp, nonce, sig = tok.split(".")
        return int(exp) > time.time() and hmac.compare_digest(sig, _sign(f"{exp}.{nonce}"))
    except Exception:
        return False


def cookie_header(tok, secure):
    return (f"{COOKIE}={tok}; Max-Age={SESSION_SECONDS}; Path=/; HttpOnly; SameSite=Strict" + ("; Secure" if secure else ""))


def clear_cookie_header():
    return f"{COOKIE}=; Max-Age=0; Path=/; HttpOnly; SameSite=Strict"


def token_from(headers):
    """`headers` is a list of (bytes, bytes) as in ASGI."""
    for k, v in headers:
        if k == b"cookie":
            for part in v.decode("latin-1").split(";"):
                name, _, val = part.strip().partition("=")
                if name == COOKIE:
                    return val
    return ""


# ── guessing protection: 5 wrong PINs, then 30 s, 60 s, 120 s ... up to 15 min ──
def locked_for(client):
    with _lock:
        n, until = _fails.get(client, (0, 0))
        return max(0, int(until - time.time() + 0.999))


def failed(client):
    with _lock:
        n, until = _fails.get(client, (0, 0))
        n += 1
        wait = min(900, 30 * 2 ** (n // 5 - 1)) if n >= 5 and n % 5 == 0 else 0
        _fails[client] = (n, time.time() + wait if wait else until)
        if len(_fails) > 500:
            _fails.pop(next(iter(_fails)))


def succeeded(client):
    with _lock:
        _fails.pop(client, None)


# ── the middleware ──
LOGIN_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>Daemon</title>
<style>
:root{color-scheme:dark}*{box-sizing:border-box}
body{margin:0;min-height:100dvh;display:flex;align-items:center;justify-content:center;background:#0e0e11;color:#e8e8ec;font:14px system-ui,sans-serif;padding:16px}
form{width:100%;max-width:300px;display:flex;flex-direction:column;gap:12px}
h1{font-size:15px;margin:0 0 4px;font-weight:600}
input{height:44px;border-radius:8px;border:1px solid #34343c;background:#1a1a20;color:inherit;padding:0 12px;font-size:16px;outline:none}
input:focus{border-color:#4a7cf3}
button{height:44px;border-radius:8px;border:0;background:#4a7cf3;color:#fff;font-size:14px;font-weight:600;cursor:pointer}
button:disabled{opacity:.5}
#e{color:#f87171;font-size:12px;min-height:16px}
</style></head><body>
<form id="f"><h1>Daemon</h1>
<input id="p" type="password" placeholder="PIN" autocomplete="current-password" autofocus>
<div id="e"></div><button id="b" type="submit">Unlock</button></form>
<script>
document.getElementById('f').onsubmit=async ev=>{ev.preventDefault();const b=document.getElementById('b'),e=document.getElementById('e');b.disabled=true;e.textContent='';
try{const r=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pin:document.getElementById('p').value})});
if(r.ok){location.reload();return}let m='Wrong PIN';try{m=(await r.json()).detail||m}catch(_){}e.textContent=m;document.getElementById('p').select()}
catch(_){e.textContent='Cannot reach the server'}b.disabled=false};
</script></body></html>"""


class AuthMiddleware:
    """Pure ASGI (does not buffer streaming replies)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket") or not active():
            return await self.app(scope, receive, send)
        path = scope["path"]
        if path in OPEN_PATHS or path.startswith(TOKEN_PREFIXES) or valid_token(token_from(scope["headers"])):
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            return await send({"type": "websocket.close", "code": 1008})
        if path == "/share":                          # something shared from the phone while the dashboard is locked
            body, status, ctype = b"Locked: open Daemon, enter the PIN, then share again.", 401, b"text/plain; charset=utf-8"
        elif scope["method"] == "GET" and path == "/":
            body, status, ctype = LOGIN_PAGE.encode(), 200, b"text/html; charset=utf-8"
        else:
            body, status, ctype = json.dumps({"detail": "locked: enter the PIN"}).encode(), 401, b"application/json"
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", ctype), (b"content-length", str(len(body)).encode()),
                                (b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": body})
