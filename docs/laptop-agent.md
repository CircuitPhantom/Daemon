# Laptop agent

The agent (`daemon-agent.py`) is a small program for a **second** Windows PC: Daemon runs on one computer (an always-on PC at home) and the agent lends it the ears and hands of another one: wake word, microphone, speakers, media keys, volume, clipboard, links, apps, screenshots, and (opt-in) mouse and keyboard.

## Do I need it?
No, if Daemon runs on the PC you sit at. Then the server runs the desktop tools itself and listens to this PC's microphone (Settings > Wake word). Computer control on a one-computer layout needs no agent either: put `DAEMON_ALLOW_INPUT=1` in `.env` and restart the task.

You need the agent when the server runs somewhere else. Then `satellite.enabled` is true on the server, and the tools in `satellite.tools` run on the laptop; when it is off they answer "the laptop is offline". On a one-computer layout keep `satellite.enabled: false` (`python satellite_setup.py --off`), otherwise the tools wait for an agent that does not exist.

## What the agent does
- Listens to **this** PC's microphone for the wake word (settings come from the server's dashboard: Settings > Wake word).
- Turns your speech into text **here** with Whisper (faster-whisper) and sends only the text to the server, where the model runs. The spoken reply is played here.
- Keeps a WebSocket open to the server so the model can use this PC's media keys, volume, clipboard, links and apps, and take screenshots.
- Reconnects by itself when the link drops.

## Setup
You need the Daemon repository on the laptop (a plain `git clone` is fine) and the server already running.

**1. On the server**: turn the link on and get a token.
```powershell
python satellite_setup.py       # writes satellite.enabled + a random token to config.yaml, prints the laptop command
Stop-ScheduledTask -TaskName Daemon; Start-ScheduledTask -TaskName Daemon
```
The token is a password for your laptop. Do not share it. `satellite_setup.py --new` makes a new one, `--off` turns the link off.

**2. On the laptop** (normal PowerShell, in the clone):
```powershell
.\setup-agent.ps1 -Server https://NAME.tailnet.ts.net -Token TOKEN
```
- `-Server` is the address you open the dashboard with (see [Remote access](remote-access.md)). Inside one LAN, `http://192.168.x.x:8000` works if the server listens on it (`--host 0.0.0.0`; only do that on a network you trust).
- The script makes `agent-venv\` (or reuses a Daemon `venv\`), installs `requirements-agent.txt`, writes `%APPDATA%\daemon-agent\config.json` (readable by your user only), tests the connection and registers the Task Scheduler task **"Daemon Agent"** (at log on, restarts after a crash). A task of your user, not a service: a service cannot reach your desktop.
- Options: `-Device "mic name"` (list names with `python -m sounddevice`), `-NoService` (start by hand), `-Print` (show what would be installed), `-Allow <tool>[,<tool>]` (below), `-Remove` (uninstall the task).

**3. Check.** In the dashboard: **Settings > Voice > Wake word** should say "Laptop agent connected". Then say "hey daemon, what time is it" or ask in the dashboard to "pause the music". `python daemon-agent.py --probe` checks what works on this desktop (changes nothing). Logs: `Get-Content logs\agent.log -Wait -Tail 30`.

## Choosing what the model may do on the laptop
Both sides must agree. The server's `satellite.tools` decides what is sent to the laptop; the agent decides what it accepts.
| You want | Server | Laptop |
|---|---|---|
| Media, volume, clipboard, links, apps, screenshots (default) | nothing to do | nothing to do |
| Shell commands on the laptop | add `execute_command` to `satellite.tools` | `.\setup-agent.ps1 -Allow execute_command` |
| Computer control | add `screen_input` to `satellite.tools`; enable the `computer` tool in Settings > Tools | `.\setup-agent.ps1 -Allow screen_input` |
Restart the task after changing `-Allow`: `Stop-ScheduledTask -TaskName "Daemon Agent"; Start-ScheduledTask -TaskName "Daemon Agent"`.

## Computer control: what to know before you turn it on
Details are in [FEATURES.md](../FEATURES.md#3-computer-control-computer-tool---two-switches-both-off-by-default) and [Windows computer control](windows.md#tier-3-windows-computer-control). In short:
- Needs a vision-capable model. It sees a screenshot of the screen with the window in front, with a coordinate grid.
- Nothing to install (SendInput). Windows of programs running as administrator, UAC prompts and the lock screen cannot be controlled.
- Test before trusting it: `python daemon-agent.py --test-input` takes a screenshot and moves the pointer to the middle of the screen.
- The first action of each turn asks for your approval; at most `computer.max_actions` actions per turn; some key combos are blocked; typing into password prompts is refused.
- Emergency brake: create the file `$HOME\.daemon-stop` (`New-Item $HOME\.daemon-stop`). Delete it to allow input again.

## Running the agent by hand
```powershell
.\agent-venv\Scripts\python.exe daemon-agent.py --server https://NAME.tailnet.ts.net --token TOKEN
```
Useful flags: `--no-wake` (desktop tools only, no microphone), `--stt-model base --stt-device cuda --stt-compute float16` (choose the local Whisper), `--server-stt` (let the server transcribe instead), `--allow <tool>`, `--log <file>`, `--probe`. Settings can also live in `%APPDATA%\daemon-agent\config.json`:
```json
{"server": "https://NAME.tailnet.ts.net", "token": "...", "device": "", "allow": ["screen_input"],
 "stt_model": "small", "stt_device": "cpu", "stt_compute": "int8"}
```

## Problems
| Symptom | Likely cause |
|---|---|
| Setup says "could not use the server" | Wrong address or token, or `satellite_setup.py` was not run / the server not restarted |
| "Laptop agent connected" never shows | The task is not running: `Get-ScheduledTask "Daemon Agent"`; the laptop is not on the same tailnet |
| `Error: the laptop is offline` on a one-computer setup | `satellite.enabled` is true but no agent runs: `python satellite_setup.py --off` |
| Wake word never triggers | Wrong microphone: set `-Device`. Whisper engine needs the phrase in `wake.aliases` too |
| `open_app` does nothing or opens the wrong thing | Add a name in `app_aliases` (config.yaml), e.g. `vscode: C:\...\Code.exe` |
| `Error: ... is not allowed on this laptop` | Allow it with `-Allow <tool>` |
| `media_control` can only toggle, `status` fails | The `winrt-*` packages are missing: `pip install -r requirements-agent.txt`; `--probe` shows `media session` |

More in [Troubleshooting](troubleshooting.md).
