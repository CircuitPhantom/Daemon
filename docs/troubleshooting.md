# Troubleshooting

Start with `.\venv\Scripts\python.exe doctor.py` (add `--online` to test the model). Then the logs:
```powershell
Get-Content logs\daemon.log -Wait -Tail 30      # server (the background task writes here)
Get-Content logs\agent.log -Wait -Tail 30       # laptop agent
```
Run `python serve.py` in a window to see the output live. If PowerShell refuses to run a script: `powershell -ExecutionPolicy Bypass -File .\setup.ps1`.

| Symptom | Cause and fix |
|---|---|
| `doctor.py`: package missing | `.\venv\Scripts\pip install -r requirements.txt`. Phone calls need `python-multipart` |
| Dashboard is blank or unstyled, or the 3D sphere is missing | `static\lib\` was not downloaded: run `.\setup.ps1` again (needs internet) |
| First start is very slow | The speech models download once (a few hundred MB). `.\setup.ps1 -Models` does it ahead of time |
| `ffmpeg not found` | `winget install Gyan.FFmpeg`, then open a new PowerShell (PATH is read at start) |
| Letters like `Ã§` or `?` in the console | Use Windows Terminal or `chcp 65001`; the files themselves are always UTF-8 |
| Chat shows an HTTP 401 / 403 | Wrong or missing API key. `.env` must contain `DAEMON_LLM_API_KEY`, or `llm.api_key` in `config.yaml`. A real environment variable beats `.env` |
| Chat shows a 404 / "model not found" | `llm.model` is not a model name that provider knows; check `llm.base_url` |
| HTTP 429 | Rate limit or quota of your provider |
| It answers but never uses tools | The model does not support tool calling, or the tools are off: Settings > Tools > pick a profile |
| "Permission needed" buttons never appear on Signal | Answer with `yes` / `no`; with no answer in `security.confirm_seconds` (90) the tool is not run |
| Settings I changed are gone | The file is rewritten when a setting changes in the dashboard, comments are lost. Keep your notes elsewhere |
| Locked out by the PIN | Set `auth.enabled: false` in `config.yaml`, or run `python set_pin.py` |
| `.env` values are ignored | Needs `NAME=value` lines (no spaces around `=`) in the file next to `config.yaml`. In `config.yaml` leave the field empty or write `${NAME}` |
| No sound | Check the default playback device in Windows; replies are played with the Windows sound API |
| Microphone not found | `python -m sounddevice` lists devices; set `wake.input_device` (or the agent's `--device`); allow desktop apps in Settings > Privacy > Microphone |
| Wake word never fires | See [Voice](voice.md): engine, aliases, microphone |
| Port 8000 busy | Another program uses it. `.\install-service.ps1 -Port 8010` uses another port |
| The task is `Ready` but the dashboard does not answer | Read `logs\daemon.log`; run `python serve.py` in a window to see the error |
| The task does not start after reboot | It starts when *you* log on (it needs your desktop for audio and apps): `Get-ScheduledTask Daemon` and `Get-ScheduledTaskInfo Daemon` show the last result |
| `open_app` fails | Add the real program in `app_aliases` (e.g. `vscode: C:\Users\you\AppData\Local\Programs\Microsoft VS Code\Code.exe`); an alias copied from another computer is ignored |
| `Error: the laptop is offline` | `satellite.enabled` is true in `config.yaml` but no agent runs. On a one-computer setup set it to false (`python satellite_setup.py --off`) |
| `pykokoro` speaks nothing / mentions espeak | Run `.\setup.ps1 -Models` and read the error |

More on Windows specifics (shell, background task, limits): [Daemon on Windows](windows.md). Still stuck? Open an issue with the output of `doctor.py` and the relevant log lines. Remove keys, tokens and phone numbers first.
