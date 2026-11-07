# Moving Daemon to a home server (the laptop stays as a satellite)

```
 PHONE ──Tailscale──►  SERVER (at home, 24/7)                 LAPTOP (only when on)
 Signal / Twilio       Daemon server, cloud LLM, Whisper,     daemon-agent.py
                       voice (ElevenLabs/Kokoro), Signal,       • microphone + "hey daemon"
                       calendar, tasks, memory, dashboard       • plays replies on the speakers
                            ▲                                   • media / volume / clipboard / links / apps
                            └──── WebSocket + token ────────────┘
```

- **Runs on the server:** model calls, STT/TTS, Signal, phone calls, calendar, tasks, reminders, memory, dashboard.
- **Runs on the laptop:** wake word, microphone/speakers, and the tools in the `satellite.tools` list (default: `media_control, volume, clipboard_read, clipboard_write, open_url, open_app, spotify_open`).
- **When the laptop is off:** those tools answer "the laptop is offline"; everything else keeps working. Spotify search runs on the server, playback on the laptop.
- `execute_command` runs on the **server** by default. To run it on the laptop, add it to `satellite.tools` on the server and start the agent with `--allow execute_command` (both sides must allow it).

## 0. Preparation
- Server: Arch or Debian/Ubuntu, logged in to Tailscale, stable internet. No local LLM (cloud API); Whisper and Kokoro run on the CPU.
- Laptop and server on the same tailnet. The laptop connects with the same address you use for the dashboard on the phone (`https://NAME.tailnet.ts.net`).
- The backup file contains API keys and the Signal login. Delete it after the move.

## 1. Back up on the laptop (stopping Daemon)
```bash
cd ~/Projects/Daemon
./backup.sh --with-signal --stop       # stops the service, writes ~/daemon-backup-DATE.tar.gz
systemctl --user disable daemon        # the laptop is no longer the server (Signal must run in one place only)
```

## 2. Install on the server
```bash
# copy the code (venv, chats etc. come from the backup)
rsync -av --exclude venv --exclude .venv --exclude agent-venv --exclude __pycache__ \
      LAPTOP:~/Projects/Daemon/ ~/daemon/
scp LAPTOP:~/daemon-backup-*.tar.gz ~/

cd ~/daemon
./setup.sh --restore ~/daemon-backup-*.tar.gz --models --service
```
`setup.sh` installs system packages (pacman/apt), the venv, pip packages and `static/lib`, and restores the backup. By hand:
```bash
sudo pacman -S tailscale && sudo systemctl enable --now tailscaled && sudo tailscale up
```
Expose the dashboard on the tailnet (the server binds to 127.0.0.1): `sudo tailscale serve --bg 8000`  → `https://NAME.tailnet.ts.net`

## 3. Server settings (`config.yaml`)
| Setting | What to do |
|---|---|
| `notify.base_url` | The server's Tailscale address |
| `phone.public_url` | The server's Funnel address (`sudo tailscale funnel --bg --https=8443 8001`); in the **Twilio console** the number's "A call comes in" webhook must be `…/phone/incoming` |
| `stt.device` | `cpu` and `compute_type: int8` without an NVIDIA GPU |
| `llm` | Cloud model only: `base_url`, `api_key`, `model` (see below) |
| `elevenlabs` | Leave it on; Kokoro on the CPU takes over on quota errors or failures |
| `wake.enabled` | `true` (the agent reads this setting; the server's own microphone is not used) |

Model settings (no local model; when the cloud fails, the error message is shown):
```yaml
llm:
  base_url: https://api.anthropic.com/v1
  api_key: ${DAEMON_LLM_API_KEY}     # the value goes in .env
  model: claude-sonnet-5-5
```
Whisper (speech to text) still runs on the server: without a GPU use `stt: {model: small, device: cpu, compute_type: int8}` (`base` for speed). Kokoro stays on the CPU as the ElevenLabs fallback.

Then turn on the satellite link:
```bash
venv/bin/python satellite_setup.py        # writes satellite.enabled + token, prints the laptop command
systemctl --user restart daemon
venv/bin/python doctor.py                 # anything missing?
```
To keep the Tailscale address: leave the old (laptop) node as it is, add the server under a new name, and point the phone/Twilio addresses at the new name.

## 4. Install the agent on the laptop
The Daemon folder already exists on the laptop (`daemon-agent.py`, `tools.py`, `wakeword.py` are there). Pull the new version from the server:
```bash
rsync -av SERVER:~/daemon/{daemon-agent.py,tools.py,wakeword.py,setup-agent.sh,requirements-agent.txt} ~/Projects/Daemon/
cd ~/Projects/Daemon
./setup-agent.sh --server https://NAME.tailnet.ts.net --token TOKEN
```
The script installs system packages (portaudio, playerctl, wl-clipboard/xclip), a venv, the settings file (`~/.config/daemon-agent.json`, mode 600), runs a connection test and sets up the `daemon-agent` user service (starts at login, reconnects when the link drops).
If the microphone name differs: `--device "name"` (`python -m sounddevice` lists them). Log: `journalctl --user -u daemon-agent -f`

## 5. Checklist
1. Dashboard > Settings > Wake word: it should say **"Laptop agent connected (…)"**.
2. "Hey daemon, what time is it?" → the reply plays on the laptop and shows in the dashboard chat.
3. "Pause the music / turn the volume down / open this link" → happens on the laptop.
4. Turn off / suspend the laptop → "pause the music" answers "laptop offline"; calendar, Signal and phone calls keep working.
5. Write to Signal from the phone, and make a test call.

## 6. Good to know
- With wake `engine: whisper` the laptop sends all speech to the server (every sentence, just to look for the wake word). Fine on a home network, but it means constant traffic and CPU. With `openwakeword` (`pip install openwakeword` on the laptop, `oww_model: hey_jarvis` or similar) the wake word is handled on the laptop and only the command is sent.
- The token is permission to run commands on the laptop. Do not share it. To renew: `satellite_setup.py --new` on the server, then `setup-agent.sh --server … --token NEW` on the laptop.
- Even with the dashboard PIN on, the agent connects with its own token (it does not need the PIN).
- Back to a single computer: `satellite_setup.py --off` on the server, or `systemctl --user enable --now daemon` on the laptop (do not forget to turn Signal off on the server).

## 7. signal-cli
The account is the Twilio number's **own primary account**, not a device linked to a phone, so "link" does not apply.

**A) Copy the data (recommended)**
1. `backup.sh --with-signal` puts `~/.local/share/signal-cli` in the backup; `setup.sh --restore` puts it back on the server (mode 700).
2. Install `signal-cli` + Java on the server (Arch: `sudo pacman -S signal-cli jdk-openjdk`; Debian: signal-cli from the GitHub release, `default-jre-headless`). Use the same version as before or newer.
3. Test: `signal-cli listAccounts` should show the account; then message Daemon on Signal.
4. **Do not run signal-cli on the laptop** (the service is already off). If it runs in two places the session keys diverge and "decryption error / untrusted identity" starts.

**B) Register again (if the data could not be copied)**
1. `signal-cli -a +TWILIO_NO register --captcha 'signalcaptcha://…'` (captcha: https://signalcaptchas.org/registration/generate.html)
2. The verification code arrives by SMS on the Twilio number (read it from the Twilio logs); `signal-cli -a +TWILIO_NO verify CODE`.
3. History is reset. Too many attempts give a 429 rate limit; wait.

## 8. When the move is done
Once everything works on the server, delete the backup files and remove `~/.local/share/signal-cli` on the laptop (the laptop must no longer own the Signal account).
