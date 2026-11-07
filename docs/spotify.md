# Spotify

"Play Creep by Radiohead", "play my favorites playlist", "play it on my phone". The `spotify_play`, `spotify_devices` and `spotify_transfer` tools do this. Enable them in **Settings > Tools** (the *Desktop* and *Full* profiles include them).

## Three levels, set up only as far as you need
| Level | You get | Needs |
|---|---|---|
| 1. Nothing | Links and your own **aliases** play on this computer. Any other request opens Spotify's search page without playing | The Spotify desktop app, installed and logged in |
| 2. App keys | Search by name ("play Creep") in Spotify's public catalog | A free Spotify developer app: `client_id` + `client_secret` |
| 3. Login | Your own playlists, and playback on **other devices** (phone, speaker) | Level 2, plus a one-time login with `spotify_login.py`, and **Spotify Premium** for device control |

"This computer" means the Spotify **desktop app** on the machine that runs the tools (the laptop, when the agent is connected). Install it first: Arch `spotify-launcher` (or the AUR/flatpak package), Debian/Ubuntu the snap or flatpak. Log in once in the app.

## Level 1: aliases (no account needed)
In `config.yaml`:
```yaml
spotify_aliases:
  my favorites: https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M
  liked songs: spotify:collection:tracks
```
In Spotify: right-click a playlist/album/track > Share > Copy link. Say "play my favorites" and it plays.

## Level 2: app keys
1. Go to <https://developer.spotify.com/dashboard> and log in with your Spotify account.
2. **Create app**. Name and description can be anything. Under **Redirect URIs** add exactly:
   ```
   http://127.0.0.1:8888/callback
   ```
   (`127.0.0.1`, not `localhost`; Spotify rejects `localhost`.) Under "Which API/SDKs are you planning to use?" tick **Web API**. Save.
3. Open the app's **Settings**. Copy the **Client ID**, then **View client secret** and copy it.
4. Put them in `.env`:
   ```
   DAEMON_SPOTIFY_CLIENT_ID=...
   DAEMON_SPOTIFY_CLIENT_SECRET=...
   ```
   (or `spotify.client_id` / `spotify.client_secret` in `config.yaml`). The server picks them up on the next message.

## Level 3: log in as yourself
Run this once **on the computer that runs the Daemon server** (not the laptop agent), in the project folder:
```bash
venv/bin/python spotify_login.py
```
It prints a link (and tries to open it). Open it in a browser, press **Agree**. The browser is sent back to `http://127.0.0.1:8888/callback`, which the script is listening on, and shows "Login saved". The refresh token is stored in `spotify_token.json` next to `config.yaml`. Delete that file to log out.

**The server has no screen or browser** (a headless Debian box)? The callback must reach the script, so forward the port from the machine where you have a browser:
```bash
ssh -L 8888:127.0.0.1:8888 you@server          # leave this open
# on the server:  venv/bin/python spotify_login.py
# open the printed link in the browser on your own computer
```

Permissions requested: read your private/collaborative playlists, read and change playback state. Nothing else.

## Using it
- "Play Radiohead Creep" / "play the album OK Computer" / "play my Gym playlist" (own playlists need level 3).
- "What Spotify devices are online?" / "play jazz on my phone" / "move the music to the kitchen speaker". Open Spotify once on that device so it shows up. Needs level 3 and Premium.
- With the [laptop agent](laptop-agent.md): searching happens on the server, the playing happens on the laptop (`spotify_open` is one of the agent's tools).

## Problems
| Message | Meaning |
|---|---|
| `Spotify login expired (HTTP 400): run spotify_login.py again` | The refresh token was revoked or the app keys changed. Run the login again |
| `log in to Spotify once with spotify_login.py` | Level 3 is missing for what you asked (devices, own playlists) |
| `Spotify Premium is needed to control devices` | Spotify only allows remote control for Premium accounts |
| `that device is not available` | Open Spotify on the target device first; check with "list Spotify devices" |
| `Spotify refused the code (HTTP 400)` during login | Wrong client secret, or the Redirect URI in the dashboard is not exactly `http://127.0.0.1:8888/callback` |
| `Port 8888 is busy` | Another program uses it. Stop it, then run the login again |
| It opens the search page but does not play | Level 2 is missing, or the desktop app is not installed/logged in |
| A device never starts the song | `venv/bin/python spotify_debug.py "device name"` tries every way to start a song and shows Spotify's answers |
