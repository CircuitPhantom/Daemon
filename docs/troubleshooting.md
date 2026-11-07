# Troubleshooting

Start with `venv/bin/python doctor.py` (add `--online` to test the model). Then the log:
```bash
journalctl --user -u daemon -f            # server
journalctl --user -u daemon-agent -f      # laptop agent
```

| Symptom | Cause and fix |
|---|---|
| `doctor.py`: package missing | `venv/bin/pip install -r requirements.txt`. Phone calls need `python-multipart` |
| Dashboard is blank or unstyled, or the 3D sphere is missing | `static/lib/` was not downloaded: run `./setup.sh` again (needs internet) |
| First start is very slow | The speech models download once (a few hundred MB). `./setup.sh --models` does it ahead of time |
| Chat shows an HTTP 401 / 403 | Wrong or missing API key. `.env` must contain `DAEMON_LLM_API_KEY`, or `llm.api_key` in `config.yaml`. A real environment variable beats `.env` |
| Chat shows a 404 / "model not found" | `llm.model` is not a model name that provider knows; check `llm.base_url` |
| HTTP 429 | Rate limit or quota of your provider |
| It answers but never uses tools | The model does not support tool calling, or the tools are off: Settings > Tools > pick a profile |
| "Permission needed" buttons never appear on Signal | Answer with `yes` / `no`; with no answer in `security.confirm_seconds` (90) the tool is not run |
| Settings I changed are gone | The file is rewritten when a setting changes in the dashboard, comments are lost. Keep your notes elsewhere |
| Locked out by the PIN | Set `auth.enabled: false` in `config.yaml`, or run `venv/bin/python set_pin.py` |
| `.env` values are ignored | Needs `NAME=value` lines (no spaces around `=`) in the file next to `config.yaml`. In `config.yaml` leave the field empty or write `${NAME}` |
| No sound | Needs `pw-play`, `paplay` or `aplay`. On a headless server there is no speaker; use the laptop agent |
| Microphone not found | `python -m sounddevice` lists devices; set `wake.input_device` (or the agent's `--device`) |
| Wake word never fires | See [Voice](voice.md): engine, aliases, microphone |
| Port 8000 busy | Another program uses it. `DAEMON_PORT=8010 ./install-service.sh` uses another port |
| Service does not start after reboot | It is a *user* service: `loginctl enable-linger $USER` starts it without logging in, but audio and desktop tools need your session |
| `open_app` fails | Add the real command in `app_aliases` (e.g. `browser: firefox`) |

Still stuck? Open an issue with the output of `doctor.py` and the relevant log lines. Remove keys, tokens and phone numbers first.
