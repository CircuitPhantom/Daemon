"""Small cross-platform helpers (stdlib only). Linux behaviour is unchanged; Windows gets the same results.

Later steps add the per-OS tool layer (media, volume, clipboard, ...) here and in platform_windows.py / platform_linux.py."""
import os
import sys
import time

IS_WINDOWS = sys.platform == "win32"


def setup_console():
    """Makes print() safe for any text (check marks, Turkish letters) on a legacy Windows console. Never raises."""
    os.environ.setdefault("PYTHONUTF8", "1")           # inherited by child Python processes
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass                                        # redirected to something without reconfigure(): leave it
    if IS_WINDOWS:
        os.system("")                                   # switches the console to ANSI colours (doctor.py)


def replace_file(src, dst, tries=8, delay=0.05):
    """os.replace that survives Windows' sharing violations (antivirus, backup or an editor holding the target for a moment)."""
    for i in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if not IS_WINDOWS or i == tries - 1:
                raise
            time.sleep(delay * (i + 1))


def readable_by_others(path):
    """True when other users can read the file (POSIX mode bits). Always False on Windows, where mode bits mean nothing."""
    if IS_WINDOWS:
        return False
    return bool(os.stat(path).st_mode & 0o077)
