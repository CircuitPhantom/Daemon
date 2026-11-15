#!/usr/bin/env python3
"""Starts the Daemon server with its output going to a log file (used by install-service.ps1 on Windows, handy anywhere).

  python serve.py                                  127.0.0.1:8000, log in logs/daemon.log
  python serve.py --port 8001 --host 127.0.0.1 --log logs/daemon.log
  pythonw serve.py                                 no console window at all (the log file is the only output)

On Linux the systemd service runs uvicorn directly; this file is not needed there."""
import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAX_LOG = 5 * 1024 * 1024


def redirect_output(path):
    """stdout/stderr (also of child processes) go to the file. A big old log is kept once as .1."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.exists() and path.stat().st_size > MAX_LOG:
            os.replace(path, path.with_name(path.name + ".1"))
    except OSError:
        pass
    f = open(path, "a", encoding="utf-8", errors="replace", buffering=1)
    try:
        os.dup2(f.fileno(), 1)
        os.dup2(f.fileno(), 2)
    except OSError:
        pass
    sys.stdout = sys.stderr = f
    return f


def main():
    ap = argparse.ArgumentParser(description="Daemon server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=int(os.environ.get("DAEMON_PORT", 8000)))
    ap.add_argument("--log", default="", help="write output to this file instead of the console")
    a = ap.parse_args()
    os.chdir(HERE)
    sys.path.insert(0, str(HERE))
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    if a.log:
        redirect_output(a.log if os.path.isabs(a.log) else HERE / a.log)
    import uvicorn
    uvicorn.run("server:app", host=a.host, port=a.port, log_level="info", use_colors=False)


if __name__ == "__main__":
    main()
