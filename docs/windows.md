# Daemon on Windows

Daemon on this fork is for **Windows 10/11 only**. It was tested by the author on one machine (Windows 11, Turkish Q keyboard, two screens, PowerShell 5.1, Python 3.13), with the server and the desktop tools on the same PC. This page lists what works, what does not and what is still untested.

| Part | What | Status |
|---|---|---|
| Server | dashboard, chat, tools, Signal, phone calls, background task | Works (tested, checklist below) |
| Desktop tools | wake word, speakers, media keys, volume, clipboard, apps, screenshot | Work (tested through a local server); the separate agent task is untested |
| Computer control | mouse + keyboard through `SendInput` | Works (tested on one PC with two screens) |

## What is special about Windows
- Text files, config, chat and memory JSON are always read and written as UTF-8 (Turkish letters survive the Windows ANSI code page).
- Atomic file saves retry when antivirus, backup or an editor holds the file for a moment.
- `doctor.py` and the other command-line tools switch the console to UTF-8 and enable colours.
- `.gitattributes` keeps `tests/` on LF line endings and the PowerShell scripts on CRLF.
- Some Linux code paths are still in the source (they keep the code testable in a Linux sandbox) but are not tested or documented here.

## Run the tests
```powershell
.\setup.ps1                 # or just: winget install Gyan.FFmpeg OpenJS.NodeJS.LTS, then pip install -r requirements.txt
python tests\run.py          # all tests; or: python tests\run.py twindesk
```
CI runs the same on `windows-latest` (Python 3.10 and 3.12) and parse-checks every `.ps1` file.

## Server
Needs Windows 10 1809+ or 11 and PowerShell 5.1 (already there). In a normal (not administrator) PowerShell, in the project folder:
```powershell
.\setup.ps1                  # winget programs, venv, pip packages, web libraries (-Models loads the speech models now)
.\venv\Scripts\python.exe doctor.py
python serve.py              # run it in this window, or:
.\install-service.ps1        # run it in the background from log on (Task Scheduler task "Daemon")
```
If PowerShell refuses to run scripts: `powershell -ExecutionPolicy Bypass -File .\setup.ps1`. Open `http://127.0.0.1:8000`.

**What works:** dashboard, chat, memory, scheduler and reminders, files and web tools, `execute_command`, `system_info`, Signal, Twilio phone calls, speech-to-text and the voices, backups (`.\backup.ps1`, a `.tar.gz`).
**Not in the server (laptop agent / computer control):** media keys, volume, clipboard, opening apps and links, screenshots and the wake word belong to the laptop agent (laptop agent below); the `computer` tool is described below.

**Good to know:**
- **Shell:** `execute_command` runs Windows PowerShell (`powershell.exe`, 5.1). The model is told so in its system prompt. Commands written for bash will fail.
- **Background task, not a service:** a Windows service runs in session 0 and cannot reach your desktop. `install-service.ps1` registers a task at log on for your user (restarts after a crash, 5 times, 1 minute apart). It runs `pythonw.exe serve.py`; everything it prints goes to `logs\daemon.log`. Stop/start: `Stop-ScheduledTask -TaskName Daemon` / `Start-ScheduledTask -TaskName Daemon`. Remove: `.\install-service.ps1 -Remove`. NSSM would also restart it after a crash but needs an extra download and runs outside your desktop session, so it is not used.
- **Search in files** uses `grep` when found, otherwise a built-in Python search (slower on big folders).
- **Time zone:** the `tzdata` package is installed for you; set `notify.timezone` (e.g. `Europe/Istanbul`) in `config.yaml`.
- **File permissions:** `.env` and backups are not "mode 600". `backup.ps1` limits the archive to your user with `icacls`; keep the project folder inside your user profile.
- **Signal:** `signal-cli` needs Java 21+ and is not on winget: download the release zip from github.com/AsamK/signal-cli/releases, unzip it and add its `bin` folder to PATH (the program is `signal-cli.bat`). Its data folder is assumed to be `%USERPROFILE%\.local\share\signal-cli`; if yours differs set `signal.data_dir` in `config.yaml`.
- **Tailscale:** `tailscale` works the same (`tailscale serve`, `tailscale funnel`); use an administrator PowerShell if it asks for it. Windows Firewall only asks when Daemon listens on a non-loopback address; the default is `127.0.0.1`.

### Manual test checklist (server)
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

**Tested** on the machine above (items 1-12; `setup.ps1`, `install-service.ps1`, `backup.ps1`). Not tested: other Windows versions, Windows 10, other keyboard layouts. Parse-check the PowerShell scripts if you change them:
```powershell
foreach ($f in 'setup','install-service','backup') { $e=$null; [System.Management.Automation.Language.Parser]::ParseFile("$PWD\$f.ps1",[ref]$null,[ref]$e) | Out-Null; "$f : $($e.Count) errors" }
```

## Laptop agent
The agent is the small program that gives a Daemon on another computer (a home server) ears and hands on this PC: wake word, spoken replies, media keys, volume, clipboard, links, apps, screenshots, Spotify. Read [Laptop agent](laptop-agent.md) first; this section is what differs on Windows. On the **server**, run `python satellite_setup.py` and copy the token.
```powershell
.\setup-agent.ps1 -Server https://NAME.tailnet.ts.net -Token TOKEN     # venv, packages, settings, Task Scheduler task "Daemon Agent"
.\agent-venv\Scripts\python.exe daemon-agent.py --probe               # what works on this desktop? (changes nothing)
```
Options: `-Device "mic name"` (names: `python -m sounddevice`), `-Allow execute_command,screen_input`, `-NoService` (start by hand), `-Print`, `-Remove`.
The settings (with the token) are in `%APPDATA%\daemon-agent\config.json`, readable by your user only. The task runs `pythonw.exe daemon-agent.py` at log on and writes `logs\agent.log`. It is a task of your user, not a service, for the same reason as the server.

**How each tool works here** :
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
- 
### Manual test checklist (laptop agent)
**One computer only (no separate server)?** Then you do not need the agent: the server on this PC runs the desktop tools itself. `setup.ps1` installs the same packages; use checklist items 1, 2, 5-12, and 13 through Settings > Wake word (the server listens to this PC's microphone). Items 3, 4, 14, 15 are for the agent.

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

**Tested:** `--probe` (10/10) and items 5-13 with the server on the same PC. **Not tested:** `setup-agent.ps1`, the "Daemon Agent" task and the agent talking to a separate server (items 3, 4, 14, 15), `-Allow`, Windows 10. Parse-check the script first:
```powershell
foreach ($f in 'setup-agent') { $e=$null; [System.Management.Automation.Language.Parser]::ParseFile("$PWD\$f.ps1",[ref]$null,[ref]$e) | Out-Null; "$f : $($e.Count) errors" }
```

## Computer control
The `computer` tool (the model looks at a screenshot and clicks, types, presses keys, scrolls) works on Windows through `SendInput`; nothing to install. The safety model:
1. **Two switches, both off by default.** The `computer` tool must be enabled on the server (Settings > Tools, vision-capable model), and this PC must allow it: with a laptop agent start it with `-Allow screen_input` (`.\setup-agent.ps1 -Allow screen_input`); with the server on this same PC put `DAEMON_ALLOW_INPUT=1` in `.env` and restart the task.
2. The first action of every turn asks for your approval; scheduled tasks and background jobs never get the tool; at most `computer.max_actions` actions per turn; `ctrl+alt+delete` and `super+l` stay blocked.
3. **Emergency brake:** create the file `$HOME\.daemon-stop` (`New-Item $HOME\.daemon-stop`); while it exists every mouse / keyboard action is refused. `Remove-Item $HOME\.daemon-stop` to allow it again.
4. Text is never typed into a window that looks like a password or authentication prompt (password managers, "Windows Security", "User Account Control", BitLocker, Windows Hello, anything with password / parola / şifre in its title).

**How it works:** the pointer is placed with `SetCursorPos` in real pixels (per-monitor DPI aware, so a 150 % screen and a screen left of or above the main one are exact). Text is typed as Unicode characters, so Turkish Q, English or any other layout gives the same letters (ç ğ ı ö ş ü and emoji included, and the clipboard is left alone). `key` presses virtual keys: a single character key (`a`, `1`, `minus`, `slash` ...) means the key that types that character on the layout of the window in front (so `ctrl+minus` works on Turkish Q too); named keys (`enter`, `f5`, arrows, `super` ...) are the same everywhere. `computer action=shortcuts` lists the standard Windows shortcuts plus your own notes in `~/.daemon-shortcuts.txt`.

**Limits that no program can get around** (the tool answers with an error that says which one applies):
- **Windows of programs running as administrator** (an elevated PowerShell, Task Manager, installers) ignore input from a normal program (UIPI). The agent checks this first and refuses with a clear message instead of clicking into the void. You can click or type there yourself. Running the agent as administrator removes the limit but also gives the model control of everything: not recommended.
- **UAC prompts, the lock screen and the sign-in screen** run on a separate "secure desktop"; they can be neither seen nor controlled.
- Some **games, remote-desktop windows and a few terminals** ignore Unicode typing; use `key` for single letters there.
- Screens with different scaling work, but a screenshot shows one screen at a time (the one with the window in front); say "look at the other screen" so the model uses `text=<screen name>` (`DISPLAY1`, `DISPLAY2` ...).
- `key` with a character the active layout has no key for (for example `|` on some layouts) falls back to the US key position, which may type something else; use `type` for such characters.

### Manual test checklist (computer control)
Open Notepad first and keep it small, so nothing important is under the pointer. Check the brake works before the rest.
| # | Do | Expect |
|---|---|---|
| 1 | `python tests\run.py twininput` | `ok twininput` |
| 2 | `python daemon-agent.py --test-input` | prints `session: windows`, both screens with their positions, then moves the pointer to the middle and to two corners; each line ends `OK` (or `OFF BY n px`: send me the output). With two screens of different scaling this is the important one |
| 3 | Enable the `computer` tool, switch 2 (`DAEMON_ALLOW_INPUT=1` in `.env`, restart the task), chat: "open notepad and type 'çay ğüşöı İi' in it" | approval prompt, Notepad opens, the text appears exactly, with the capital dotted İ |
| 4 | "select all in notepad and copy it, then tell me what is in my clipboard" | `ctrl+a`, `ctrl+c`; the clipboard text matches |
| 5 | "type three lines: one, two, three" | three lines (Enter between them) |
| 6 | "click the File menu in notepad" (then "close it with escape") | the menu opens and closes |
| 7 | "zoom out the browser page with ctrl and minus" in a browser tab | the page zooms out (this checks the Turkish Q minus key) |
| 8 | "scroll down 5 in the browser", then "scroll up" | the page scrolls |
| 9 | "drag the notepad window by its title bar a little to the right" | the window moves |
| 10 | If you have two screens: put Notepad on the second one, "look at the other screen and click in notepad" | the screenshot switches screens and the click lands in Notepad |
| 11 | `New-Item $HOME\.daemon-stop`, then "click anywhere" | `Error: the emergency brake is on`; `Remove-Item $HOME\.daemon-stop` and it works again |
| 12 | Open an elevated PowerShell (right click > Run as administrator), ask to "type hello in the window in front" | `Error: not typed: the window runs as administrator ...` and nothing is typed |
| 13 | Open Windows Security or a window with "password" in its title, ask to type "a" | refused as a password prompt |
| 14 | Ask for `ctrl+alt+delete` | `blocked` |

**Tested:** on one PC with two screens, with the server controlling its own computer (`DAEMON_ALLOW_INPUT=1`). **Not tested:** through a separate agent (`-Allow screen_input`), screens with very different scaling beyond that PC, other keyboard layouts, Windows 10.

## Troubleshooting
- **`ffmpeg not found`:** `winget install Gyan.FFmpeg`, then open a new PowerShell (PATH is read at start).
- **`pykokoro` speaks nothing / mentions espeak:** run `.\setup.ps1 -Models` and send me the error.
- **Letters like `Ã§` or `?` in the console:** use Windows Terminal or `chcp 65001`; the files themselves are always UTF-8.
- **The task is `Ready` but the dashboard does not answer:** read `logs\daemon.log`; run `python serve.py` in a window to see the error.
