# Getting started

This gets Daemon running on one Windows or Linux computer, with the dashboard in your browser. Commands are given for Windows (PowerShell) first, then Linux. Everything else (phone, Signal, laptop agent...) is optional and can be added later.

## What you need
- **Windows 10/11** (PowerShell 5.1 is enough), or **Linux** with a desktop session (Arch + Hyprland, Debian/Ubuntu). The server part also runs headless on Linux.
- **Python 3.10+**. `setup.sh` creates a virtual environment, so nothing is installed system-wide.
- **A cloud LLM account** and its API key. Daemon has no built-in model. Any provider that speaks the OpenAI chat format and supports tool calling works, see [LLM providers](llm-providers.md).
- About **2 GB of disk and 2-4 GB of RAM** for the speech models (faster-whisper `small` on the CPU, Kokoro voice). A GPU is not needed. They download on first use.
- Optional: a microphone and speakers (voice), a phone, a Tailscale account (reach it from the phone).

## 1. Install
**Windows** (normal PowerShell; details, limits and the checklist: [Daemon on Windows](windows.md)):
```powershell
git clone https://github.com/CircuitPhantom/Daemon.git
cd Daemon
.\setup.ps1
```
`setup.ps1` installs the programs it needs with `winget` (ffmpeg and others, it asks first), creates `venv\`, installs `requirements.txt` and downloads the dashboard libraries. Options: `-NoSystem`, `-Models`, `-Service`, `-Yes`. If PowerShell refuses to run scripts: `powershell -ExecutionPolicy Bypass -File .\setup.ps1`.

**Linux:**
```bash
git clone https://github.com/CircuitPhantom/Daemon.git
cd Daemon
./setup.sh
```
`setup.sh` offers to install system packages with `sudo` (portaudio, playerctl, wl-clipboard, java for Signal), creates `venv/`, installs `requirements.txt`, and downloads the dashboard's JavaScript libraries to `static/lib/`. It asks before each step and is safe to run again. Options: `--no-system` (skip packages), `--models` (download the speech models now instead of on first start), `--service` (also install the background service), `-y` (no questions).

## 2. Configure
```powershell
Copy-Item config.example.yaml config.yaml ; Copy-Item .env.example .env        # Windows
```
```bash
cp config.example.yaml config.yaml ; cp .env.example .env && chmod 600 .env     # Linux
```
Open `.env` and put your key in it:
```
DAEMON_LLM_API_KEY=your-key-here
```
Open `config.yaml` and set the provider and model:
```yaml
llm:
  base_url: https://api.groq.com/openai/v1     # your provider's OpenAI-compatible address
  model: llama-3.3-70b-versatile                # a model that supports tool calling
```
Everything else can stay at its default. Settings can also be changed in the dashboard (Settings); the file is then rewritten. See [Configuration](../README.md#configuration) for how `.env` and `config.yaml` work together.

## 3. Check
```powershell
.\venv\Scripts\python.exe doctor.py            # Windows (Linux: venv/bin/python doctor.py)
.\venv\Scripts\python.exe doctor.py --online   # also tests the model (uses a few tokens)
```
Local checks: Python, packages, files, tools, permissions.
Every line is a tick, a warning or a cross with a hint. Fix the crosses first.

## 4. Run
**Windows:** `.\install-service.ps1` runs Daemon in the background from every log on (a Task Scheduler task of your user); the log is `logs\daemon.log`. Or in a window: `python serve.py`. Stop / start: `Stop-ScheduledTask -TaskName Daemon` / `Start-ScheduledTask -TaskName Daemon`.

**Linux:**
```bash
./install-service.sh                 # runs Daemon in the background and at every login (systemd user service)
systemctl --user status daemon
journalctl --user -u daemon -f       # the log
```
or in a terminal: `venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port 8000`.

Open <http://127.0.0.1:8000>. The first start downloads the speech models, which can take a few minutes.

## 5. Try it
- Type a message in the dashboard, or press the microphone and talk.
- Turn tools on: **Settings > Tools** and pick a profile. Start with *Read only* or *Assistant*; *Full* includes `execute_command` and desktop control. Risky tools always ask for your approval first.
- Ask: "what time is it", "search the web for ...", "remind me in 10 minutes to ..." (reminders need [Signal](signal.md)).
- Set a PIN: **Settings > Security**, or `venv/bin/python set_pin.py`.

## Where things live
| What | Where |
|---|---|
| Settings | `config.yaml` (private), secrets in `.env` (private) |
| Scheduled tasks and their results | `tasks.yaml`, `runs/` |
| Chats, memory, calendar, reminders, inbox | JSON files next to `config.yaml` |
| Files the model writes, uploads | `~/Documents/Daemon/` |
| Spotify login | `spotify_token.json` |

`./backup.sh` packs all of it into one archive; `./backup.sh --install-timer` makes a daily backup.

## Next steps
- Use it from your phone and anywhere: [Remote access and the phone app](remote-access.md)
- Talk to it away from the browser: [Voice and wake word](voice.md), [Signal](signal.md), [phone calls](phone-calls.md)
- Let it use your desktop: [Laptop agent](laptop-agent.md)
- Music: [Spotify](spotify.md)
- Recurring work: [Scheduled tasks](tasks.md)
- Something broken: [Troubleshooting](troubleshooting.md)

## Updating
`git pull`, then `venv/bin/pip install -r requirements.txt` and `systemctl --user restart daemon` (Windows: `.\venv\Scripts\pip install -r requirements.txt`, then `Stop-ScheduledTask -TaskName Daemon; Start-ScheduledTask -TaskName Daemon`). Your `config.yaml`, `.env` and data are not in the repository and stay untouched.

`deploy.sh` is an optional helper for a two-machine setup: run on a laptop, it copies the changed files of a folder to the server over SSH, checks them, restarts the service and rolls back if the server does not come back (`bash deploy.sh --help`).
