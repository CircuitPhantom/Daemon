# Moving Daemon to another Windows PC (a home server, the laptop stays as a satellite)

```
 PHONE ──Tailscale──►  SERVER PC (at home, always on)         LAPTOP (only when on)
 Signal / Twilio       Daemon server, cloud LLM, Whisper,     daemon-agent.py
                       voice (ElevenLabs/Kokoro), Signal,       • microphone + "hey daemon"
                       calendar, tasks, memory, dashboard       • plays replies on the speakers
                            ▲                                   • media / volume / clipboard / links / apps
                            └──── WebSocket + token ────────────┘
```

- **Runs on the server:** model calls, STT/TTS, Signal, phone calls, calendar, tasks, reminders, memory, dashboard.
- **Runs on the laptop:** wake word, microphone/speakers, and the tools in the `satellite.tools` list (default: `media_control, volume, clipboard_read, clipboard_write, open_url, open_app, spotify_open`).
- **When the laptop is off:** those tools answer "the laptop is offline"; everything else keeps working. Spotify search runs on the server, playback on the laptop.
- `execute_command` runs on the **server** by default. To run it on the laptop, add it to `satellite.tools` on the server and install the agent with `-Allow execute_command` (both sides must allow it).

If you only have one PC, you do not need any of this: see [Getting started](docs/getting-started.md).

## 0. Preparation
- Server PC: Windows 10/11, signed in to Tailscale, stable internet, no sleep (Settings > System > Power). No local LLM needed (cloud API); Whisper and Kokoro run on the CPU.
- Both PCs on the same tailnet. The laptop connects with the address you use for the dashboard on the phone (`https://NAME.tailnet.ts.net`).
- The backup file contains API keys and the Signal login. Move it with a USB stick and delete it after the move.

## 1. Back up on the laptop (stopping Daemon)
```powershell
cd C:\path\to\Daemon
.\backup.ps1 -WithSignal -Stop         # stops the task, writes ~\daemon-backup-DATE.tar.gz
.\install-service.ps1 -Remove          # the laptop is no longer the server (Signal must run in one place only)
```

## 2. Install on the server PC
Copy the project folder (without `venv`, `agent-venv`, `__pycache__`) and the backup file to the server PC, then in PowerShell there:
```powershell
cd C:\path\to\Daemon
.\setup.ps1 -Restore $HOME\daemon-backup-DATE.tar.gz -Models -Service
```
`setup.ps1` installs the programs (winget), the venv, pip packages and `static\lib`, restores the backup and starts the background task. Tailscale (if missing): `winget install Tailscale.Tailscale`, then sign in. Expose the dashboard on the tailnet (the server listens on 127.0.0.1): `tailscale serve --bg 8000` → `https://NAME.tailnet.ts.net`

## 3. Server settings (`config.yaml`)
| Setting | What to do |
|---|---|
| `notify.base_url` | The server's Tailscale address |
| `phone.public_url` | The server's Funnel address (`tailscale funnel --bg --https=8443 8001`); in the **Twilio console** the number's "A call comes in" webhook must be `…/phone/incoming` |
| `stt.device` | `cpu` and `compute_type: int8` without an NVIDIA GPU |
| `llm` | Cloud model only: `base_url`, `api_key`, `model` (see below) |
| `elevenlabs` | Leave it on; Kokoro on the CPU takes over on quota errors or failures |
| `wake.enabled` | `true` (the agent reads this setting; the server's own microphone is not used) |

```yaml
llm:
  base_url: https://api.anthropic.com/v1
  api_key: ${DAEMON_LLM_API_KEY}     # the value goes in .env
  model: claude-sonnet-5-5
```
Whisper still runs on the server: without a GPU use `stt: {model: small, device: cpu, compute_type: int8}` (`base` for speed).

Then turn on the satellite link:
```powershell
.\venv\Scripts\python.exe satellite_setup.py      # writes satellite.enabled + token, prints the laptop command
Stop-ScheduledTask Daemon; Start-ScheduledTask Daemon
.\venv\Scripts\python.exe doctor.py               # anything missing?
```
To keep the Tailscale address: leave the old (laptop) node as it is, add the server under a new name, and point the phone/Twilio addresses at the new name.

## 4. Install the agent on the laptop
The Daemon folder is already on the laptop. Copy the new version from the server if it differs, then:
```powershell
cd C:\path\to\Daemon
.\setup-agent.ps1 -Server https://NAME.tailnet.ts.net -Token TOKEN
```
The script creates `agent-venv`, installs the packages, saves the settings (`%APPDATA%\daemon-agent\config.json`), runs a connection test and registers the "Daemon Agent" task (starts at log on, reconnects when the link drops). Microphone name: `-Device "name"` (`python -m sounddevice` lists them). Log: `logs\agent.log`. See [Laptop agent](docs/laptop-agent.md).

## 5. Checklist
1. Dashboard > Settings > Wake word: it should say **"Laptop agent connected (…)"**.
2. "Hey daemon, what time is it?" → the reply plays on the laptop and shows in the dashboard chat.
3. "Pause the music / turn the volume down / open this link" → happens on the laptop.
4. Turn off / sleep the laptop → "pause the music" answers "laptop offline"; calendar, Signal and phone calls keep working.
5. Write to Signal from the phone, and make a test call.

## 6. Good to know
- With wake `engine: whisper` the laptop sends all speech to the server (every sentence, just to look for the wake word). Fine on a home network, but constant traffic and CPU. With `openwakeword` (`pip install openwakeword` in `agent-venv`, `oww_model: hey_jarvis` or similar) the wake word is handled on the laptop and only the command is sent.
- The token is permission to run tools on the laptop. Do not share it. To renew: `satellite_setup.py --new` on the server, then `.\setup-agent.ps1 -Server … -Token NEW` on the laptop.
- Even with the dashboard PIN on, the agent connects with its own token (it does not need the PIN).
- Back to a single computer: `satellite_setup.py --off` on the server, or `.\install-service.ps1` on the laptop (do not forget to turn Signal off on the server).

## 7. signal-cli
The account is the Twilio number's **own primary account**, not a device linked to a phone, so "link" does not apply.

**A) Copy the data (recommended)**
1. `.\backup.ps1 -WithSignal` puts `%USERPROFILE%\.local\share\signal-cli` in the backup; `.\setup.ps1 -Restore` puts it back on the server.
2. Install Java 21+ and `signal-cli` on the server (release zip from github.com/AsamK/signal-cli/releases, add its `bin` folder to PATH). Use the same version as before or newer.
3. Test: `signal-cli listAccounts` should show the account; then message Daemon on Signal.
4. **Do not run signal-cli on the laptop** (the task is already removed). If it runs in two places the session keys diverge and "decryption error / untrusted identity" starts.

**B) Register again (if the data could not be copied)**
1. `signal-cli -a +TWILIO_NO register --captcha 'signalcaptcha://…'` (captcha: https://signalcaptchas.org/registration/generate.html)
2. The verification code arrives by SMS on the Twilio number (read it from the Twilio logs); `signal-cli -a +TWILIO_NO verify CODE`.
3. History is reset. Too many attempts give a 429 rate limit; wait.

## 8. When the move is done
Once everything works on the server, delete the backup files and remove `%USERPROFILE%\.local\share\signal-cli` on the laptop (the laptop must no longer own the Signal account).

**Not tested:** this whole move end to end (server on one Windows PC, agent on another).
