"""One-time Spotify login, so spotify_play can find YOUR playlists (a plain search only sees public ones).

Run it on the computer where Daemon runs, from the webserver folder, with the venv active:

    python spotify_login.py

It prints a link. Open it, press "Agree", and the browser lands on a page of this computer
("Login saved"). Needs spotify.client_id and spotify.client_secret in config.yaml, and this exact
Redirect URI in your app's settings on developer.spotify.com/dashboard:

    http://127.0.0.1:8888/callback

Only read access to your playlists is requested. The login is kept in spotify_token.json next to
config.yaml (private file). Delete that file to log out.
"""
import base64
import http.server
import json
import secrets
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

import model_config

PORT = 8888
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
SCOPE = "playlist-read-private playlist-read-collaborative user-read-playback-state user-modify-playback-state"


def redirect_uri(port=PORT):
    return f"http://127.0.0.1:{port}/callback"


def build_auth_url(client_id, state, port=PORT):
    q = urllib.parse.urlencode({
        "client_id": client_id, "response_type": "code", "redirect_uri": redirect_uri(port),
        "scope": SCOPE, "state": state,
    })
    return f"{AUTH_URL}?{q}"


def exchange(code, client_id, client_secret, port=PORT):
    """Trades the one-time code for tokens. Returns the token response."""
    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    data = urllib.parse.urlencode({"grant_type": "authorization_code", "code": code,
                                   "redirect_uri": redirect_uri(port)}).encode()
    req = urllib.request.Request(TOKEN_URL, data=data, headers={"Authorization": "Basic " + auth})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def save_token(tokens, path):
    if not tokens.get("refresh_token"):
        raise ValueError("Spotify sent no refresh token")
    model_config.atomic_write(path, json.dumps({"refresh_token": tokens["refresh_token"],
                                                "scope": tokens.get("scope", "")}))


def login(port=PORT, open_browser=True, timeout=300):
    cfg = model_config.spotify
    if not cfg.get("client_id") or not cfg.get("client_secret"):
        print("Set spotify.client_id and spotify.client_secret in config.yaml first.")
        return False
    state = secrets.token_urlsafe(16)
    result = {}
    done = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(u.query)
            if u.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            if q.get("state", [""])[0] != state:             # not from our link: ignore it, keep waiting
                self.send_response(400)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Wrong state, start again.")
                return
            if "error" in q:
                msg, code = "Spotify said: " + q["error"][0], 400
            elif "code" not in q:
                msg, code = "No code received.", 400
            else:
                result["code"] = q["code"][0]
                msg, code = "Login saved. You can close this tab.", 200
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(msg.encode())
            if code != 200:
                result["error"] = msg
            done.set()

    try:
        server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    except OSError as e:
        print(f"Port {port} is busy ({e}).")
        return False
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = build_auth_url(cfg["client_id"], state, port)
    print("Open this link and press Agree:\n\n" + url + "\n")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        if not done.wait(timeout):
            print("Timed out, nothing saved.")
            return False
    finally:
        server.shutdown()
    if "code" not in result:
        print(result.get("error", "Login failed."))
        return False
    try:
        tokens = exchange(result["code"], cfg["client_id"], cfg["client_secret"], port)
        path = model_config.spotify_token_path()
        save_token(tokens, path)
    except urllib.error.HTTPError as e:
        print(f"Spotify refused the code (HTTP {e.code}). Check client_secret and the Redirect URI.")
        return False
    except Exception as e:
        print("Could not finish:", e)
        return False
    print(f"Done. Login saved to {path}")
    return True


if __name__ == "__main__":
    sys.exit(0 if login() else 1)
