#!/usr/bin/env python3
"""Starts the Daemon server with its output going to a log file (used by install-service.ps1 on Windows, handy anywhere).

  python serve.py                                  127.0.0.1:8000, log in logs/daemon.log
  python serve.py --port 8001 --host 127.0.0.1 --log logs/daemon.log
  pythonw serve.py                                 no console window at all (the log file is the only output)

install-service.ps1 starts the server through this file (Task Scheduler, at log on)."""
import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import platform_support
redirect_output = platform_support.redirect_output


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
