# Getting started

This gets Daemon running on one Windows 10/11 computer, with the dashboard in your browser. Everything else (phone, Signal, a second computer as the server...) is optional and can be added later. Windows-specific details, limits and the test checklists are in [Daemon on Windows](windows.md).

## What you need
- **Windows 10 (1809+) or 11**. PowerShell 5.1 is already there; run everything in a normal (not administrator) PowerShell.
- **Python 3.10+** and **git**. `setup.ps1` offers to install what is missing with `winget` and creates a virtual environment, so nothing is installed system-wide.
- **A cloud LLM account** and its API key. Daemon has no built-in model. Any provider that speaks the OpenAI chat format and supports tool calling works, see [LLM providers](llm-providers.md).
- About **2 GB of disk and 2-4 GB of RAM** for the speech models (faster-whisper `small` on the CPU, Kokoro voice). A GPU is not needed. They download on first use.
- Optional: a microphone and speakers (voice), a phone, a Tailscale account (reach it from the phone).

## 1. Install
```powershell
git clone -b windows https://github.com/CircuitPhantom/Daemon.git
cd Daemon
.\setup.ps1
```
`setup.ps1` installs the programs it needs with `winget` (ffmpeg and others; it asks first), creates `venv\`, installs `requirements.txt` and downloads the dashboard's JavaScript libraries to `static\lib\`. It is safe to run again. Options: `-NoSystem` (skip winget), `-Models` (download the speech models now instead of on first start), `-Service` (also install the background task), `-Yes` (no questions), `-Restore <archive>` (restore a backup). If PowerShell refuses to run scripts: `powershell -ExecutionPolicy Bypass -File .\setup.ps1`.

## 2. Configure
```powershell
Copy-Item config.example.yaml config.yaml
Copy-Item .env.example .env
notepad .env
```
Put your key in `.env`:
```
DAEMON_LLM_API_KEY=your-key-here
```
Open `config.yaml` and set the provider and model:
```yaml
llm:
  base_url: https://api.groq.com/openai/v1     # your provider's OpenAI-compatible address
  model: llama-3.3-70b-versatile                # a model that supports tool calling
```
Everything else can stay at its default. Settings can also be changed in the dashboard (Settings); the file is then rewritten. See [Configuration](../README.md#configuration) for how `.env` and `config.yaml` work together. Keep the project folder inside your user profile: `.env` holds your keys.

## 3. Check
```powershell
.\venv\Scripts\python.exe doctor.py            # local checks: Python, packages, files, tools
.\venv\Scripts\python.exe doctor.py --online   # also tests the model (uses a few tokens)
```
Every line is a tick, a warning or a cross with a hint. Fix the crosses first.

## 4. Run
```powershell
.\install-service.ps1                          # runs Daemon in the background from every log on (Task Scheduler task "Daemon")
Get-Content logs\daemon.log -Wait -Tail 30     # the log
```
or in a window: `python serve.py`. Stop / start the task: `Stop-ScheduledTask -TaskName Daemon` / `Start-ScheduledTask -TaskName Daemon`; remove it: `.\install-service.ps1 -Remove`.

Open <http://127.0.0.1:8000>. The first start downloads the speech models, which can take a few minutes.

## 5. Try it
- Type a message in the dashboard, or press the microphone and talk.
- Turn tools on: **Settings > Tools** and pick a profile. Start with *Read only* or *Assistant*; *Full* includes `execute_command` (Windows PowerShell) and desktop control. Risky tools always ask for your approval first.
- Ask: "what time is it", "search the web for ...", "pause the music", "open notepad", "remind me in 10 minutes to ..." (reminders need [Signal](signal.md)).
- Set a PIN: **Settings > Security**, or `python set_pin.py`.

## Where things live
| What | Where |
|---|---|
| Settings | `config.yaml` (private), secrets in `.env` (private) |
| Scheduled tasks and their results | `tasks.yaml`, `runs\` |
| Chats, memory, calendar, reminders, inbox | JSON files next to `config.yaml` |
| Files the model writes, uploads | `%USERPROFILE%\Documents\Daemon\` |
| Spotify login | `spotify_token.json` |
| Logs | `logs\daemon.log`, `logs\agent.log` |

`.\backup.ps1` packs all of it into one archive; `.\backup.ps1 -InstallTimer` makes a daily backup (Task Scheduler).

## Next steps
- Use it from your phone and anywhere: [Remote access and the phone app](remote-access.md)
- Talk to it away from the browser: [Voice and wake word](voice.md), [Signal](signal.md), [phone calls](phone-calls.md)
- Let it use your desktop: [Laptop agent](laptop-agent.md) and [Windows computer control](windows.md#computer-control)
- Music: [Spotify](spotify.md)
- Recurring work: [Scheduled tasks](tasks.md)
- Run it on another PC and use this one as the laptop: [MIGRATION.md](../MIGRATION.md)
- Something broken: [Troubleshooting](troubleshooting.md)

## Updating
`git pull`, then `.\venv\Scripts\pip install -r requirements.txt` and `Stop-ScheduledTask -TaskName Daemon; Start-ScheduledTask -TaskName Daemon`. Your `config.yaml`, `.env` and data are not in the repository and stay untouched.
