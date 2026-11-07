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

The tool list and the larger features are in [FEATURES.md](FEATURES.md); setup guides are in [docs/](docs/).

## Architecture
```
 phone / browser / Signal ──► server (FastAPI, port 8000) ──► cloud LLM (OpenAI-compatible)
                                   │  tools, memory, scheduler, STT/TTS
                                   └──WebSocket + token──► laptop agent (mic, speakers, desktop tools)
```

## Quick start
```bash
git clone https://github.com/CircuitPhantom/daemon.git && cd daemon
./setup.sh                                  # system packages, venv, Python packages, dashboard libraries
cp config.example.yaml config.yaml
cp .env.example .env && chmod 600 .env
$EDITOR .env config.yaml                    # DAEMON_LLM_API_KEY in .env; llm.base_url and llm.model in config.yaml
venv/bin/python doctor.py                   # what is missing?
./install-service.sh                        # run in the background (or: venv/bin/python -m uvicorn server:app --port 8000)
```
Open <http://127.0.0.1:8000>. The full walk-through is in [docs/getting-started.md](docs/getting-started.md).

## Documentation
| | |
|---|---|
| [Getting started](docs/getting-started.md) | Requirements, install, first chat, where files live, updating |
| [LLM providers](docs/llm-providers.md) | Base URLs, picking a model, privacy |
| [Voice and wake word](docs/voice.md) | Speech-to-text, text-to-speech engines, "hey daemon" |
| [Remote access and phone app](docs/remote-access.md) | Tailscale, HTTPS, installing the PWA |
| [Laptop agent](docs/laptop-agent.md) | Server + laptop layout, desktop tools, computer control |
| [Signal](docs/signal.md) | Registering the bot number, commands |
| [Phone calls](docs/phone-calls.md) | Twilio: Daemon calls you, you call Daemon |
| [Spotify](docs/spotify.md) | App keys, one-time login, devices |
| [Scheduled tasks](docs/tasks.md) | Cron tasks, background jobs, reminders |
| [Troubleshooting](docs/troubleshooting.md) | Common errors |
| [FEATURES.md](FEATURES.md) | All tools, web search, jobs, computer control, `.env` |
| [MIGRATION.md](MIGRATION.md) | Moving Daemon to a home server |

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

## Third-party software and services
Nothing third-party is bundled in this repository. Dependencies are installed by `pip` / `setup.sh` under their own licenses:
FastAPI, Uvicorn, Pydantic, PyYAML, Requests, NumPy, Pillow, pypdf (permissive licenses), faster-whisper and the Whisper models (MIT),
pykokoro and the Kokoro voice model (Apache 2.0). The dashboard libraries three.js (MIT), marked (MIT) and highlight.js (BSD-3-Clause)
are downloaded from jsDelivr by `setup.sh`. The dashboard uses your system fonts and loads nothing from third-party servers at runtime.

Optional online services follow their own terms, which you accept by enabling them: your LLM provider, ElevenLabs, Groq, Twilio, Spotify
(Web API), Brave Search. Two features rely on unofficial access and may break or be restricted by the provider at any time:
the free Edge voice (`edge-tts`, Microsoft's online voices) and the DuckDuckGo fallback of `web_search`. Use a Brave key or your own SearXNG
for search if you want a supported path. Spotify and other names are trademarks of their owners; this project is not affiliated with them.

## License
MIT, see [LICENSE](LICENSE). Contributions: [CONTRIBUTING.md](CONTRIBUTING.md). Security reports: [SECURITY.md](SECURITY.md).
