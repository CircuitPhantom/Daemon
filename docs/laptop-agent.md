# Laptop agent

## Do I need it?
Daemon is one server process. It can run in two layouts:

| Layout | When | What to do |
|---|---|---|
| **One computer** | Daemon runs on the computer you sit at | Nothing. The server uses this computer's microphone, speakers, clipboard and apps directly. You do not need the agent. |
| **Server + laptop agent** | Daemon runs on an always-on machine (home server, Raspberry Pi, VPS) and you want your laptop to be its microphone, speakers and hands | Install the agent on the laptop (this page). |

Computer control (mouse and keyboard) on a one-computer layout needs no agent either: set `DAEMON_ALLOW_INPUT=1` for the server (for the systemd service: `systemctl --user edit daemon` and add `[Service]` / `Environment=DAEMON_ALLOW_INPUT=1`).

## What the agent does
`daemon-agent.py` runs on the laptop and keeps a WebSocket open to the server. Through it:
- **Wake word and voice.** It listens to the laptop's microphone, transcribes speech *on the laptop* with Whisper, sends the text to the server, and plays the spoken reply on the laptop's speakers.
- **Desktop tools.** When the model calls `media_control`, `volume`, `clipboard_read`, `clipboard_write`, `open_url`, `open_app`, `system_info` or Spotify playback, the call runs on the laptop. If the laptop is off, the model is told "the laptop is offline" and everything else keeps working.
- **Opt-in power tools.** `execute_command` (shell on the laptop) and `screen_input` (mouse and keyboard, the `computer` tool) only run when you start the agent with `--allow ...` *and* the server lists them. Both sides must agree.

## Setup
You need the Daemon repository on the laptop (a plain `git clone` is fine) and the server already running.

**1. On the server**: turn the link on and get a token.
```bash
cd ~/daemon
venv/bin/python satellite_setup.py       # writes satellite.enabled + a random token to config.yaml, prints the laptop command
systemctl --user restart daemon
```
The token is a password for your laptop. Do not share it. `satellite_setup.py --new` makes a new one, `--off` turns the link off.

**2. On the laptop**: install and start the agent as a service.
```bash
cd ~/daemon                               # the clone on the laptop
./setup-agent.sh --server https://NAME.tailnet.ts.net --token TOKEN
```
- `--server` is the address you open the dashboard with (see [Remote access](remote-access.md)). Inside one LAN, `http://192.168.x.x:8000` works if the server listens on it (`--host 0.0.0.0`; only do that on a network you trust).
- The script installs system packages (portaudio, playerctl, wl-clipboard/xclip), makes `agent-venv/`, writes `~/.config/daemon-agent.json` (mode 600), tests the connection and starts the user service `daemon-agent`.
- Options: `--device "mic name"` (list names with `python -m sounddevice`), `--no-service`, `--no-system`, `--allow <tool>` (below), `--remove` (uninstall the service).

**3. Check.** In the dashboard: **Settings > Voice > Wake word** should say "Laptop agent connected". Then say "hey daemon, what time is it" or ask in the dashboard to "pause the music".
Logs: `journalctl --user -u daemon-agent -f`.

## Choosing what the model may do on the laptop
Two lists have to agree:

1. **Server, `config.yaml`** — `satellite.tools`: which tools are *sent* to the laptop. Default: `system_info, media_control, volume, clipboard_read, clipboard_write, open_url, open_app, spotify_open, screen_grab`.
2. **Laptop** — `--allow`: which extra tools the agent is *willing* to run. Default: none beyond the safe ones above.

| I want | Server `satellite.tools` | Laptop |
|---|---|---|
| Shell commands on the laptop | add `execute_command` | `./setup-agent.sh --allow execute_command`, then `systemctl --user restart daemon-agent` |
| Computer control | add `screen_input` | `./setup-agent.sh --allow screen_input`, then restart; also enable the `computer` tool in Settings > Tools |

Without an entry in `satellite.tools`, `execute_command` runs on the **server**. The tool has a `where` argument, so the model can pick `server` or `laptop` for a single call.

## Computer control: what to know before you turn it on
Details are in [FEATURES.md](../FEATURES.md#3-computer-control-computer-tool---two-switches-both-off-by-default). In short:
- Needs a vision-capable model. It sees a screenshot of the focused monitor with a coordinate grid.
- Linux only: Wayland (Hyprland tested) uses `ydotool` and `wtype`, X11 uses `xdotool`. Install them (`sudo pacman -S ydotool wtype xdotool`) and make sure your user can use `/dev/uinput` (ydotool wiki).
- Test before trusting it: `venv/bin/python daemon-agent.py --test-input` takes a screenshot and moves the pointer to the middle of the screen.
- The first action of each turn asks for your approval; at most `computer.max_actions` actions per turn; some key combos are blocked; typing into password prompts is refused.
- Emergency brake: `touch ~/.daemon-stop` on the laptop. Delete the file to allow input again.

## Running the agent by hand
```bash
agent-venv/bin/python daemon-agent.py --server https://NAME.tailnet.ts.net --token TOKEN
```
Useful flags: `--no-wake` (desktop tools only, no microphone), `--stt-model base --stt-device cuda --stt-compute float16` (choose the local Whisper), `--server-stt` (let the server transcribe instead), `--allow <tool>`. Settings can also live in `~/.config/daemon-agent.json`:
```json
{"server": "https://NAME.tailnet.ts.net", "token": "...", "device": "", "allow": ["screen_input"],
 "stt_model": "small", "stt_device": "cpu", "stt_compute": "int8"}
```

## Problems
| Symptom | Likely cause |
|---|---|
| Setup says "could not use the server" | Wrong address or token, or `satellite_setup.py` was not run / the server not restarted |
| "Laptop agent connected" never shows | The service is not running: `systemctl --user status daemon-agent`; the laptop is not on the same tailnet |
| Wake word never triggers | Wrong microphone: set `--device`. Whisper engine needs the phrase in `wake.aliases` too |
| `open_app` does nothing or opens the wrong thing | Add a name in `app_aliases` (config.yaml), e.g. `browser: firefox` |
| Agent started before the desktop at boot and apps fail | Update; the agent now fills in the Wayland/DBus environment itself. Restart the service after logging in |
| `Error: ... is not allowed on this laptop` | Start the agent with `--allow <tool>` |

More in [Troubleshooting](troubleshooting.md).
