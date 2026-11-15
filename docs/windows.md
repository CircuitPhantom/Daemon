# Daemon on Windows

Status: **work in progress**. Daemon is developed on Linux; Windows support is added in steps. This page lists exactly what works.

| Tier | What | Status |
|---|---|---|
| 0 | Server inside WSL2 | Works (below) |
| 1 | Native Windows server | In progress |
| 2 | Native Windows laptop agent (wake word, speakers, media keys, volume, clipboard, apps, screenshot) | Planned |
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
