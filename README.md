# Daemon

A self-hosted voice and chat assistant. FastAPI server, web dashboard, phone app (PWA), Signal bot, wake word,
and a set of tools the model can call (shell, files, web search, calendar, Spotify, desktop control...).
The language model is **cloud-hosted and OpenAI-compatible** (Anthropic, Groq, NVIDIA, OpenRouter, Fireworks...); speech-to-text
(faster-whisper) and text-to-speech (Kokoro / Edge / ElevenLabs) run locally or in the cloud as you choose.

> Status: personal project, shared as is. Linux only (developed on Arch + Hyprland, server on Debian).

## Features
- Voice and text chat from the dashboard, the phone (installable PWA, Share menu) and Signal
- Tool calling: `execute_command`, `read_file`, `write_file`, `fetch_url`, `web_search`, `open_app`, `spotify_play`, calendar, reminders, inbox, background jobs...
- Tool profiles (Off / Read only / Assistant / Desktop / Full) and per-tool approval for risky actions
- Optional **laptop agent** (`daemon-agent.py`): the server runs at home, the laptop gives it a microphone, speakers, media keys,
  clipboard, app launching and (opt-in) mouse and keyboard control
- Scheduled tasks, routines, reminders, daily briefing, phone calls through Twilio
- Persistent memory notes, uploads (photos, PDFs), PIN lock for the dashboard
- Secrets in `.env`, settings in `config.yaml`

See [FEATURES.md](FEATURES.md) for details on search, jobs, computer control, the phone app and `.env`.
[MIGRATION.md](MIGRATION.md) describes the server + laptop-agent split.

## Architecture
```
 phone / browser / Signal ──► server (FastAPI, port 8000) ──► cloud LLM (OpenAI-compatible)
                                   │  tools, memory, scheduler, STT/TTS
                                   └──WebSocket + token──► laptop agent (mic, speakers, desktop tools)
```

## Quick start
```bash
git clone https://github.com/CircuitPhantom/Daemon.git daemon && cd daemon
./setup.sh                      # system packages, venv, Python packages (safe to run again)
cp config.example.yaml config.yaml
cp .env.example .env && chmod 600 .env
$EDITOR .env                    # at least DAEMON_LLM_API_KEY; set llm.base_url and llm.model in config.yaml
./install-service.sh            # optional: systemd user service
# or by hand:
.venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port 8000
```
Open <http://127.0.0.1:8000>. `python doctor.py` checks the setup. `python set_pin.py` sets a dashboard PIN.

For the phone: `tailscale serve --bg --https=443 http://127.0.0.1:8000`, then open the HTTPS address and "Install app".

## Configuration
- `config.yaml` holds settings; the server reloads it on the next message. `config.example.yaml` lists every option with its default.
- `.env` holds secrets. In `config.yaml` write `api_key: ${DAEMON_LLM_API_KEY}` or leave key, token, secret, password, phone number
  and account fields empty; they are filled from `DAEMON_<SECTION>_<FIELD>`. A real environment variable beats `.env`.
- `python secrets_to_env.py` (dry run) / `--apply` moves the secrets of an existing `config.yaml` into `.env`.
- Neither file is ever committed (see `.gitignore`).

## Security notes
Daemon can run commands and control your desktop on behalf of a language model. Treat it accordingly.
- Bind to `127.0.0.1` (the default) and reach it through Tailscale or a reverse proxy with TLS. Do not expose port 8000 to the internet. Set a PIN.
- Risky tools (`execute_command`, `write_file`, `computer`...) ask for your approval (`security.confirm_tools`); scheduled tasks and
  background jobs never get them.
- Computer control needs two switches: the tool enabled on the server and `--allow screen_input` on the laptop agent.
  `touch ~/.daemon-stop` on the laptop is an emergency brake.
- Your prompts and tool results go to the LLM provider you configure. Check its data-retention terms.
- Report vulnerabilities privately rather than in a public issue.

## Tests
```bash
python3 -m pip install -r requirements.txt
tests/run.sh              # all tests, in a scratch copy
tests/run.sh tjobs tllm   # some of them
```
The tests use stubs for the speech and LLM libraries, so no models, network or API keys are needed.

## License
MIT, see [LICENSE](LICENSE).
