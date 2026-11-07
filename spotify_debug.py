#!/usr/bin/env python3
"""Finds out why Spotify does not start a song on a device. Run it on the server, next to server.py:

  venv/bin/python spotify_debug.py "Mi A3"

Open Spotify on that device first. It tries every way of starting a well-known song (play, album + offset, queue + skip),
shows Spotify's answer and what the device is really doing after each, and stops at the first one that works.
"""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import model_config
import tools as T

TRACK = "spotify:track:4cOdK2wGLETKBW3PvgPWqT"          # Rick Astley - Never Gonna Give You Up (in every market)


def cfg():
    return {**model_config.spotify, "aliases": {}, "token_file": str(model_config.spotify_token_path())}


def call(c, method, path, body=None):
    tok = T._spotify_user_token(c)
    if not tok:
        sys.exit("No Spotify login: run spotify_login.py first.")
    data = json.dumps(body).encode() if body is not None else (b"" if method in ("PUT", "POST") else None)
    req = urllib.request.Request(T.SPOTIFY_API + path, data=data, method=method, headers={
        "Authorization": "Bearer " + tok, "Content-Type": "application/json", "User-Agent": "daemon/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read(100_000).decode("utf-8", "replace")
            return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        raw = e.read(2000).decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw


def state(c, dev_id):
    st, d = call(c, "GET", "/me/player")
    if not isinstance(d, dict) or not d:
        return "no player state (Spotify has no active session)"
    dv = d.get("device") or {}
    item = (d.get("item") or {}).get("name") or "nothing"
    return f"{'PLAYING' if d.get('is_playing') else 'not playing'}: {item} on {dv.get('name')} (device id match: {dv.get('id') == dev_id})"


def main():
    c = cfg()
    want = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    st, me = call(c, "GET", "/me")
    print("account:", me if st == 200 else f"HTTP {st} {me}")
    st, d = call(c, "GET", "/me/player/devices")
    devs = d.get("devices", []) if isinstance(d, dict) else []
    print("devices:")
    for x in devs:
        print("  ", json.dumps(x))
    dev = T._match_device(devs, want) if want else (devs[0] if devs else None)
    if not dev:
        sys.exit("No matching device. Open Spotify on it and run again with its name.")
    if dev.get("is_restricted"):
        print("\n!! This device says is_restricted=true: it does not accept any Web API commands. Nothing can start music on it remotely.")
    did = urllib.parse.quote(dev["id"])
    print(f"\nusing: {dev['name']} ({dev.get('type')}), now: {state(c, dev['id'])}")
    st, tr = call(c, "GET", "/tracks/" + TRACK.split(":")[-1] + "?market=from_token")
    album = ((tr.get("album") or {}).get("uri")) if isinstance(tr, dict) else None
    print("track check:", "playable" if isinstance(tr, dict) and tr.get("is_playable", True) else f"HTTP {st} {tr}", "| album:", album)

    steps = [("A. transfer, then play uris", [("PUT", "/me/player", {"device_ids": [dev["id"]], "play": False}),
                                             ("PUT", f"/me/player/play?device_id={did}", {"uris": [TRACK]})]),
             ("B. play with album + offset", [("PUT", f"/me/player/play?device_id={did}",
                                               {"context_uri": album, "offset": {"uri": TRACK}})] if album else []),
             ("C. queue + skip", [("POST", f"/me/player/queue?uri={urllib.parse.quote(TRACK)}&device_id={did}", None),
                                  ("POST", f"/me/player/next?device_id={did}", None)]),
             ("D. play without device_id", [("PUT", "/me/player/play", {"uris": [TRACK]})])]
    for name, calls in steps:
        if not calls:
            continue
        print(f"\n== {name}")
        for method, path, body in calls:
            st, resp = call(c, method, path, body)
            print(f"   {method} {path.split('?')[0]} -> HTTP {st}", resp if resp else "")
            time.sleep(0.8)
        time.sleep(4)
        s = state(c, dev["id"])
        print("   result:", s)
        if s.startswith("PLAYING") and "Never Gonna" in s:
            print(f"\n>>> '{name}' works on this device.")
            call(c, "PUT", "/me/player/pause")
            return
    print("\nNothing started music. Paste this whole output.")


if __name__ == "__main__":
    main()
