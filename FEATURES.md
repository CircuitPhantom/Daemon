# Features

## Tools
Everything the model can call. Which ones it gets is set per chat by a **profile** (Settings > Tools): Off, Read only, Assistant,
Desktop, Full (every tool) or your own (`tool_profiles` in `config.yaml`). Tools marked * ask for your approval first
(`security.confirm_tools`) and are never given to scheduled tasks or background jobs.

| Area | Tools |
|---|---|
| Files | `read_file`, `list_directory`, `search_files`, `search_text`, `write_file`*, `send_file`* |
| Shell and system | `execute_command`*, `system_info`, `get_time`, `calculate` |
| Web | `web_search`, `fetch_url` |
| Reminders and phone | `remind_me`, `list_reminders`, `cancel_reminder`, `send_message` (Signal), `call_me` (Twilio call) |
| Calendar | `calendar_list`, `calendar_add`, `calendar_update`, `calendar_delete` |
| Inbox (notes, links, files archive) | `inbox_add`, `inbox_search`, `inbox_recent`, `inbox_delete` |
| Background work | `start_job` |
| Desktop (runs on the laptop agent when connected) | `media_control`, `volume`, `clipboard_read`, `clipboard_write`, `open_url`, `open_app` |
| Spotify | `spotify_play`, `spotify_devices`, `spotify_transfer` |
| Screen | `screenshot`*, `computer` (look, click, type, keys; see section 3) |

`execute_command`, `system_info` and the desktop tools run on the laptop when the agent is connected and allows them
(`satellite.tools`, `--allow`), otherwise on the server. Adding a tool: write a function with type hints and a docstring in
`tools.py`, register it in `available_functions`, and add it to a profile in `model_config.py`.

Details of the larger features follow.

## 1. Web search (`web_search` tool)
Works without any setup (DuckDuckGo, with a second DuckDuckGo endpoint when the first asks for a captcha).
Better: a free Brave key (brave.com/search/api, ~2000 searches/month) or your own SearXNG.

```yaml
search:
  provider: auto        # auto = Brave if brave_key, else SearXNG if searxng_url, else DuckDuckGo. A failing backend hands over to the next
  brave_key: ""
  searxng_url: ""       # e.g. http://127.0.0.1:8080  (settings.yml of SearXNG must allow the json format)
  results: 5
  region: ""            # DuckDuckGo: tr-tr, us-en ...
```
The model can ask for `fresh: day | week | month | year`. Answers are cached for 10 minutes.

## 2. Background jobs
- Signal: `/job compare the three best USB-C hubs under 30 USD` · `/jobs` · `/job <id>` (full result) · `/cancel <id>`
- Dashboard: Tasks drawer > Background jobs.
- The model can start one itself with the `start_job` tool ("research this and tell me later").
- A job has its own tool list (`jobs.tools`: search, read pages, read files, calendar, inbox). It never asks for approval, so
  `execute_command`, `write_file`, `send_file`, `screenshot` and `computer` are never given to it.
- Result: Signal message (long ones come with the full text as a file), `jobs/<id>-name.md` in the Daemon folder, and an inbox item tagged `#job`.

```yaml
jobs:
  enabled: true
  max_running: 2
  timeout_minutes: 15
  max_steps: 14
  tools: [web_search, fetch_url, read_file, ...]
```

## 3. Computer control (`computer` tool) - two switches, both off by default
1. Server: enable the `computer` tool (Settings > Tools, or the Full profile). The model needs vision.
2. Laptop: start the agent with `--allow screen_input` (add it to the service's ExecStart).

Install the helpers on the laptop (Arch): `sudo pacman -S ydotool wtype xdotool` (Wayland: `systemctl --user enable --now ydotool`,
and your user must be allowed to use `/dev/uinput`, see the ydotool wiki). Copy `screeninput.py` next to `tools.py` (deploy.sh does it).

**Check it first:** `python daemon-agent.py --test-input` shows what was found, takes a screenshot and moves the pointer to the middle of
the screen; it compares the real pointer position with the expected one (Hyprland and X11). If it says OFF BY n px, send me the output.

Safety:
- the first action of a turn asks for your OK (dashboard buttons or `yes`/`no` on Signal); that OK covers the rest of that turn only
- at most `computer.max_actions` (30) actions per turn; `blocked_keys` (ctrl+alt+delete, super+l ...) are refused
- text is never typed into a window that looks like a password / authentication prompt
- emergency brake: `touch ~/.daemon-stop` on the laptop refuses all mouse/keyboard actions until you delete the file
- not available to scheduled tasks or background jobs
- the screenshot is of the focused monitor only, with a labelled pixel grid
- a yellow ring marks the pointer (where the last click went); `action=zoom` (x, y) sends a 4x enlarged piece with a fine grid in the same coordinates
- `computer.coords`: `auto` (default) | `pixels` | `1000`. Models trained on a 0-1000 grid (Nemotron VL, Qwen3-VL, GLM-V, UI-TARS) get
  that grid (auto picks it from the model name); the server turns it into pixels

Shortcuts: `computer action=shortcuts` gives the model your key bindings (live from `hyprctl binds`, so your dotfiles' own binds), plus
anything you write in `~/.daemon-shortcuts.txt` on the laptop (e.g. `super+d: app launcher`, app-specific tips).

## 4. Phone app + Share menu (Android Chrome)
The browser only allows installing and sharing over HTTPS. With Tailscale:
```bash
tailscale serve --bg --https=443 http://127.0.0.1:8000
```
Open `https://<machine>.<tailnet>.ts.net` on the phone > menu > Install app. After that, "Daemon" is in the Share menu: share a link,
text, photo or file from any app and it lands in the inbox (tag `#shared`).
iOS has no share targets: make a Shortcut that POSTs `{"text": "..."}` to `/api/sat/inbox` with `Authorization: Bearer <satellite token>`.

## 5. Secrets in `.env` instead of config.yaml
Put keys and tokens in a `.env` file next to `config.yaml` (`chmod 600 .env`; `.env.example` shows the format). Two ways to use it:
- in `config.yaml`: `api_key: ${DAEMON_LLM_API_KEY}` (also `${NAME:-default}`, in any value)
- or leave a key / token / secret / password field empty: it is filled from `DAEMON_<SECTION>_<FIELD>`
  (`llm.api_key` = `DAEMON_LLM_API_KEY`, `search.brave_key` = `DAEMON_SEARCH_BRAVE_KEY`, `notify.twilio_token` = `DAEMON_NOTIFY_TWILIO_TOKEN` ...)
- the same goes for the phone numbers and account ids: `notify.twilio_sid`, `twilio_from`, `twilio_to`, `spotify.client_id`,
  `signal.account`, `signal.allowed`

When a setting is changed in the dashboard the file is rewritten with the `${NAME}` kept, so a key from `.env` never ends up in
`config.yaml`. A real environment variable (for example from a systemd `Environment=`) beats the same name in `.env`. Editing `.env`
takes effect on the next message, like config.yaml. The backup includes `.env`; `deploy.sh` never touches it. `doctor.py` reports
missing names.

Move the keys you already have: `python secrets_to_env.py` (dry run), then `python secrets_to_env.py --apply`
(config.yaml is kept as `config.yaml.before-env`; delete it once everything works, it still holds the keys). The `auth` section
(PIN hash, cookie secret) stays in config.yaml: Daemon writes it itself.
