# Daemon on Windows

Status: **work in progress**. Daemon is developed on Linux; Windows support is added in steps. This page lists exactly what works.

| Tier | What | Status |
|---|---|---|
| 0 | Server inside WSL2 | Works (below) |
| 1 | Native Windows server | Written, waiting for your test (below) |
| 2 | Native Windows laptop agent (wake word, speakers, media keys, volume, clipboard, apps, screenshot) | Written, waiting for your test (below) |
| 3 | Windows computer control (mouse + keyboard) | Planned, needs real-hardware testing |

## Tier 0: WSL2 (works today)
The server runs unchanged inside WSL2 (Ubuntu). Follow [Getting started](getting-started.md) in the WSL2 terminal.
```powershell
wsl --install -d Ubuntu          # once, in an admin PowerShell, then reboot
```
Open the dashboard from Windows at `http://localhost:8000` (WSL2 forwards localhost).
Limits: no microphone, speakers, clipboard, apps or desktop control of Windows from inside WSL2. For those use the native agent (tier 2).

## What changed for Windows so far
- Text files, config, chat and memory JSON are always read and written as UTF-8 (Turkish letters survive the Windows ANSI code page).
- Atomic file saves retry when antivirus, backup or an editor holds the file for a moment.
- The Linux-only "`.env` can be read by other users" warning is skipped (Windows has no mode bits).
- `doctor.py` and the other command-line tools switch the console to UTF-8 and enable colours.
- `.gitattributes` keeps `*.sh` and `tests/` on LF line endings in a Windows checkout.
- `python tests/run.py` runs the test suite without bash. The `windows` CI job is informational until tier 1 is complete.

## Run the tests on Windows
```powershell
winget install Gyan.FFmpeg OpenJS.NodeJS.LTS
py -3.12 -m venv venv ; .\venv\Scripts\Activate.ps1
pip install fastapi "uvicorn[standard]" pydantic python-multipart pyyaml requests numpy pillow pypdf httpx
python tests\run.py
```
Tests that still assume Linux commands will fail until tier 1/2; the list is expected to shrink with each step.

## Tier 1: native Windows server
Needs Windows 10 1809+ or 11 and PowerShell 5.1 (already there). In a normal (not administrator) PowerShell, in the project folder:
```powershell
.\setup.ps1                  # winget programs, venv, pip packages, web libraries (-Models loads the speech models now)
.\venv\Scripts\python.exe doctor.py
python serve.py              # run it in this window, or:
.\install-service.ps1        # run it in the background from log on (Task Scheduler task "Daemon")
```
If PowerShell refuses to run scripts: `powershell -ExecutionPolicy Bypass -File .\setup.ps1`. Open `http://127.0.0.1:8000`.

**What works:** dashboard, chat, memory, scheduler and reminders, files and web tools, `execute_command`, `system_info`, Signal, Twilio phone calls, speech-to-text and the voices, backups (`.\backup.ps1`, same archive format as `backup.sh`, so a Linux backup restores on Windows and back).
**Not in the server (tier 2/3):** media keys, volume, clipboard, opening apps and links, screenshots and the wake word belong to the laptop agent (tier 2 below); the `computer` tool is tier 3. `doctor.py` skips the Linux desktop-tool checks.

**Things that differ from Linux:**
- **Shell:** `execute_command` runs Windows PowerShell (`powershell.exe`, 5.1). The model is told so in its system prompt. Commands written for bash will fail.
- **Background task, not a service:** a Windows service runs in session 0 and cannot reach your desktop. `install-service.ps1` registers a task at log on for your user (restarts after a crash, 5 times, 1 minute apart). It runs `pythonw.exe serve.py`; everything it prints goes to `logs\daemon.log`. Stop/start: `Stop-ScheduledTask -TaskName Daemon` / `Start-ScheduledTask -TaskName Daemon`. Remove: `.\install-service.ps1 -Remove`. NSSM would also restart it after a crash but needs an extra download and runs outside your desktop session, so it is not used.
- **Search in files** uses `grep` when found, otherwise a built-in Python search (slower on big folders).
- **Time zone:** the `tzdata` package is installed for you; set `notify.timezone` (e.g. `Europe/Istanbul`) in `config.yaml` as on Linux.
- **File permissions:** `.env` and backups are not "mode 600". `backup.ps1` limits the archive to your user with `icacls`; keep the project folder inside your user profile.
- **Signal:** `signal-cli` needs Java 21+ and is not on winget: download the release zip from github.com/AsamK/signal-cli/releases, unzip it and add its `bin` folder to PATH (the program is `signal-cli.bat`). Its data folder is assumed to be `%USERPROFILE%\.local\share\signal-cli`; if yours differs set `signal.data_dir` in `config.yaml`.
- **Tailscale:** `tailscale` works the same (`tailscale serve`, `tailscale funnel`); use an administrator PowerShell if it asks for it. Windows Firewall only asks when Daemon listens on a non-loopback address; the default is `127.0.0.1`.
- **`deploy.sh`** (rsync/ssh from the author's laptop to his server) stays Linux/macOS only.

### Manual test checklist (tier 1)
Run in PowerShell in the project folder; send me anything that does not match.
| # | Command | Expect |
|---|---|---|
| 1 | `python tests\run.py` | no `FAIL` (some tests print `skip`; that is on purpose) |
| 2 | `.\venv\Scripts\python.exe doctor.py` | no red lines except what you have not set up (keys, Signal) |
| 3 | `python serve.py` then open `http://127.0.0.1:8000` | dashboard loads; Ctrl+C stops it |
| 4 | In the chat: "run `Get-Date` and `$PSVersionTable.PSVersion`" | the model runs PowerShell and shows the output |
| 5 | In the chat: "run `Write-Output 'çay ğüşöı'`" | the Turkish letters come back unbroken |
| 6 | In the chat: "run `Start-Sleep 60`" | after 20 s: `[stopped: still running ...]`; `Get-Process powershell` shows no leftover |
| 7 | In the chat: "show system info of the server" | uptime, CPU, memory, disk, battery (laptop) lines |
| 8 | In the chat: "search for the word hello in my Documents" | `file:line:text` lines or "No matches found" |
| 9 | `.\install-service.ps1`, reboot or log off/on | `Get-ScheduledTask Daemon` is `Running`, dashboard answers, `logs\daemon.log` has lines |
| 10 | `Stop-ScheduledTask -TaskName Daemon; Get-Process java -ErrorAction SilentlyContinue` | server gone; no `java` left over (only if Signal is on) |
| 11 | `.\backup.ps1 -WithFiles` then `tar -tzf $HOME\daemon-backup-*.tar.gz` | lists `./project/...`, `./MANIFEST.txt` |
| 12 | Add a reminder for 2 minutes from now in the chat | it fires (dashboard / Signal) |

**Untested:** everything above on real Windows. The PowerShell scripts were not run or syntax-checked before delivery; check them first:
```powershell
foreach ($f in 'setup','install-service','backup') { $e=$null; [System.Management.Automation.Language.Parser]::ParseFile("$PWD\$f.ps1",[ref]$null,[ref]$e) | Out-Null; "$f : $($e.Count) errors" }
```

## Tier 2: native Windows laptop agent
The agent is the small program that gives a Daemon on another computer (your Debian server) ears and hands on this PC: wake word, spoken replies, media keys, volume, clipboard, links, apps, screenshots, Spotify. Read [Laptop agent](laptop-agent.md) first; this section is what differs on Windows. On the **server**, run `python satellite_setup.py` as usual and copy the token.
```powershell
.\setup-agent.ps1 -Server https://NAME.tailnet.ts.net -Token TOKEN     # venv, packages, settings, Task Scheduler task "Daemon Agent"
.\agent-venv\Scripts\python.exe daemon-agent.py --probe               # what works on this desktop? (changes nothing)
```
Options: `-Device "mic name"` (names: `python -m sounddevice`), `-Allow execute_command,screen_input`, `-NoService` (start by hand), `-Print`, `-Remove`.
The settings (with the token) are in `%APPDATA%\daemon-agent\config.json`, readable by your user only. The task runs `pythonw.exe daemon-agent.py` at log on and writes `logs\agent.log`. It is a task of your user, not a service, for the same reason as the server.

**How each tool works here** (tool names, arguments and answers are the same as on Linux):
| Tool | Windows implementation | Needs |
|---|---|---|
| `media_control` | Windows media session (what Spotify, browsers and players register); media keys when that is missing | `winrt-*` packages for `status`, real play / pause and `restart` |
| `volume` | the default speaker's endpoint volume (exact percentages, mute) | `pycaw` |
| `clipboard_read/write` | the Windows clipboard, text (Turkish letters and line breaks survive) | nothing |
| `open_url` | your default browser | nothing |
| `open_app` | your `app_aliases`, program on PATH, registered program, Start Menu shortcut, Store app (`Get-StartApps`) | nothing |
| `spotify_play` etc. | the desktop Spotify through its `spotify:` link, then play through the media session | Spotify desktop |
| `screenshot`, `computer` screenshots | all screens, or the screen of the window in front; real pixels (per-monitor DPI aware) | `pillow` |
| wake word replies | played with Windows' own sound API | nothing |

**Limits, honestly:**
- Without the `winrt-*` packages `media_control` can only press media keys: `play` and `pause` both send "play/pause" (a toggle), and `status` / `restart` answer with an error that names the packages. `setup-agent.ps1` installs them; if pip cannot get one for your Python, `--probe` shows `media session` as FAIL.
- Spotify decides what a `spotify:` link does; Windows' media session is used to press play afterwards. If it opens the song but does not play, tell me what `--probe` says for `media session`.
- A normal agent cannot touch windows of programs running **as administrator** (Task Manager, an elevated PowerShell): Windows blocks that (UIPI). Screenshots of them work, clicks and keys do not. Run the agent elevated only if you really need that; I do not recommend it.
- A locked screen, the login screen and UAC prompts (secure desktop) cannot be captured or controlled by any user program.
- Apps in Store form open by their Start Menu name (`Get-StartApps` is asked once every 5 minutes and takes a moment the first time).
- `ensure_session_env` (Wayland / D-Bus variables) is not needed on Windows and is skipped.

### Manual test checklist (tier 2)
On the Windows PC, in the project folder. The server must already have `satellite.enabled` (`python satellite_setup.py`).
| # | Do | Expect |
|---|---|---|
| 1 | `python tests\run.py twindesk` | `ok twindesk` |
| 2 | `.\agent-venv\Scripts\python.exe daemon-agent.py --probe` | all ten lines `OK` (`Store apps` and `Spotify` may be FAIL if you have none); send me every FAIL line |
| 3 | `.\setup-agent.ps1 -Server ... -Token ...` | "server answered, token accepted", task installed, last log lines say `connected to` |
| 4 | Dashboard > Settings > Voice > Wake word | "Laptop agent connected" |
| 5 | Chat: "pause the music" while Spotify or a YouTube video plays | it pauses; "play" resumes; "next song" skips |
| 6 | Chat: "what is playing?" | `Playing: artist - title (app)` |
| 7 | Chat: "volume 30", "turn it up", "mute", "unmute", "what is the volume" | the speaker slider follows; answers `Volume is N%` |
| 8 | Chat: "copy 'çay ğüşöı' to my clipboard", paste in Notepad; copy text with Ctrl+C, ask "what is in my clipboard" | exact text both ways |
| 9 | Chat: "open github.com in my browser" | default browser opens it |
| 10 | Chat: "open notepad", "open calculator", "open <a program you installed>" | each starts; a wrong name answers with `Similar: ...` |
| 11 | Chat: "play Radiohead Creep on Spotify" (needs the Spotify login of the server and Spotify desktop) | Spotify opens it and plays |
| 12 | Chat: "take a screenshot" (with two monitors if you have them) | the picture shows all screens; `window` names the program in front |
| 13 | Say "hey daemon, what time is it" | spoken reply from your speakers |
| 14 | Reboot, log in | `Get-ScheduledTask "Daemon Agent"` is `Running`; `logs\agent.log` has lines; the dashboard shows "connected" again |
| 15 | `Stop-ScheduledTask -TaskName "Daemon Agent"; Get-Process pythonw` | no agent process left |

**Untested:** everything in `win_desktop.py` on real Windows (the logic is covered by mocked tests, the Windows API calls are not). `--probe` and this list are how we find out. `setup-agent.ps1` was not run before delivery; parse-check it first:
```powershell
foreach ($f in 'setup-agent') { $e=$null; [System.Management.Automation.Language.Parser]::ParseFile("$PWD\$f.ps1",[ref]$null,[ref]$e) | Out-Null; "$f : $($e.Count) errors" }
```

## Troubleshooting
- **`ffmpeg not found`:** `winget install Gyan.FFmpeg`, then open a new PowerShell (PATH is read at start).
- **`pykokoro` speaks nothing / mentions espeak:** run `.\setup.ps1 -Models` and send me the error.
- **Letters like `Ã§` or `?` in the console:** use Windows Terminal or `chcp 65001`; the files themselves are always UTF-8.
- **The task is `Ready` but the dashboard does not answer:** read `logs\daemon.log`; run `python serve.py` in a window to see the error.
