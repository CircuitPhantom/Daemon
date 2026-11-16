# Daemon

[![tests](https://github.com/CircuitPhantom/Daemon/actions/workflows/tests.yml/badge.svg?branch=windows)](https://github.com/CircuitPhantom/Daemon/actions/workflows/tests.yml?query=branch%3Awindows)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**A self-hosted voice and chat assistant that can actually do things.** Talk or type to it from a browser, your phone or Signal;
it answers with a cloud language model of your choice and uses tools on your behalf: run commands, read and write files, search the web,
manage a calendar and reminders, play Spotify, call you on the phone, and (opt-in) use your desktop with mouse and keyboard.

**Website:** https://circuitphantom.github.io/Daemon/

> Looking for Linux? Use the [`main` branch](https://github.com/CircuitPhantom/Daemon). This is the Windows branch.

> Status: personal project, shared as is. This fork is **Windows 10/11 only** (tested on Windows 11, PowerShell 5.1, Python 3.13): see [docs/windows.md](docs/windows.md) for what is tested and its limits. Some Linux code paths are still in the source but are neither tested nor documented here.

## Features
- **Voice and text chat** from the web dashboard, an installable phone app (PWA with Share-menu support) and Signal
- **Tool calling**: shell, files, web search, calendar, reminders, inbox, background jobs, Spotify, media keys, clipboard, apps, screenshots, [computer control](FEATURES.md#3-computer-control-computer-tool---two-switches-both-off-by-default)
- **Safe by default**: tool profiles (Off / Read only / Assistant / Desktop / Full), approval for risky actions, PIN for the dashboard, secrets kept in `.env`
- **Laptop agent** (`daemon-agent.py`): Daemon runs on an always-on machine at home, the laptop lends it a microphone, speakers and hands
- **Automation**: cron-style scheduled tasks, routines, daily briefing, phone calls through Twilio
- **Voice**: wake word ("hey daemon"), local Whisper or cloud speech-to-text, Kokoro / Edge / ElevenLabs voices
- **Memory** notes, photo and PDF uploads, any OpenAI-compatible provider (Anthropic, OpenAI, Groq, NVIDIA, OpenRouter, Fireworks...)

## How it fits together
```
 phone / browser / Signal ──► server (FastAPI, port 8000) ──► cloud LLM (OpenAI-compatible)
                                   │  tools, memory, scheduler, STT/TTS
                                   └──WebSocket + token──► laptop agent (mic, speakers, desktop tools)
```
One computer is enough. The laptop agent is only needed when the server runs somewhere else.

## Requirements
Windows 10/11 (PowerShell 5.1, already there), Python 3.10+, an API key of an LLM provider that supports tool calling, and about 2 GB of disk and 2-4 GB of RAM for the
speech models (CPU only, no GPU needed). Microphone, phone, Signal, Twilio and Spotify are all optional.

## Quick start
In a normal (not administrator) PowerShell:
```powershell
git clone -b windows https://github.com/CircuitPhantom/Daemon.git
cd Daemon
.\setup.ps1                                 # winget programs, venv, Python packages, dashboard libraries
Copy-Item config.example.yaml config.yaml ; Copy-Item .env.example .env
notepad .env ; notepad config.yaml          # DAEMON_LLM_API_KEY in .env; llm.base_url and llm.model in config.yaml
.\venv\Scripts\python.exe doctor.py        # what is missing?
.\install-service.ps1                       # run in the background from log on (or: python serve.py)
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
| [Daemon on Windows](docs/windows.md) | What is tested, limits, background task, manual checklists |
| [FEATURES.md](FEATURES.md) | All tools, web search, jobs, computer control, `.env` |
| [MIGRATION.md](MIGRATION.md) | Moving Daemon to a home server |

## Configuration
- `config.yaml` holds settings; the server reloads it on the next message. `config.example.yaml` lists every option with its default.
- `.env` holds secrets. In `config.yaml` write `api_key: ${DAEMON_LLM_API_KEY}` or leave key, token, secret, password, phone number
  and account fields empty; they are filled from `DAEMON_<SECTION>_<FIELD>`. A real environment variable beats `.env`.
- `python secrets_to_env.py` (dry run) / `--apply` moves the secrets of an existing `config.yaml` into `.env`.
- Neither file is ever committed (see `.gitignore`).

## Security
Daemon can run commands and control your desktop on behalf of a language model. Treat it accordingly.
- Listen on `127.0.0.1` (the default) and reach it through Tailscale or a reverse proxy with TLS. Never expose port 8000 to the internet. Set a PIN.
- Risky tools (`execute_command`, `write_file`, `send_file`, `screenshot` by default) ask for your approval (`security.confirm_tools`), and `computer` asks before the first action of each turn; scheduled tasks and
  background jobs never get them.
- Computer control needs two switches: the tool enabled on the server and `-Allow screen_input` on the laptop agent (or `DAEMON_ALLOW_INPUT=1` when the server runs on the same PC).
  Creating the file `$HOME\.daemon-stop` is an emergency brake.
- Your prompts and tool results go to the LLM provider you configure. Check its data-retention terms ([details](docs/llm-providers.md#privacy)).
- Report vulnerabilities privately, see [SECURITY.md](SECURITY.md).

## Tests
```powershell
pip install -r requirements.txt
python tests\run.py              # all tests, in a scratch copy
python tests\run.py tjobs tllm   # some of them (add -v to see the output of failures)
```
The tests use stubs for the speech and LLM libraries, so no models, network or API keys are needed. They do need `node` and `ffmpeg` on the PATH.

## Third-party software and services
Nothing third-party is bundled in this repository. Dependencies are installed by `pip` / `setup.ps1` under their own licenses:
FastAPI, Uvicorn, Pydantic, PyYAML, Requests, NumPy, Pillow, pypdf (permissive licenses), faster-whisper and the Whisper models (MIT),
pykokoro and the Kokoro voice model (Apache 2.0). On Windows also psutil (BSD-3-Clause), tzdata (Apache 2.0), pycaw and comtypes (MIT) and the pywinrt packages `winrt-*` (MIT) for the laptop agent. The dashboard libraries three.js (MIT), marked (MIT) and highlight.js (BSD-3-Clause)
are downloaded from jsDelivr by `setup.ps1`. The dashboard uses your system fonts and loads nothing from third-party servers at runtime.

Optional online services follow their own terms, which you accept by enabling them: your LLM provider, ElevenLabs, Groq, Twilio, Spotify
(Web API), Brave Search. Two features rely on unofficial access and may break or be restricted by the provider at any time:
the free Edge voice (`edge-tts`, Microsoft's online voices) and the DuckDuckGo fallback of `web_search`. Use a Brave key or your own SearXNG
for search if you want a supported path. The favicon is the "alien monster" emoji from Noto Emoji (Google; Apache 2.0 / SIL OFL 1.1). Spotify and other names are trademarks of their owners; this project is not affiliated with them.

## License
MIT, see [LICENSE](LICENSE). Contributions: [CONTRIBUTING.md](CONTRIBUTING.md).
