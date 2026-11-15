"""Small cross-platform helpers (stdlib only). Linux behaviour is unchanged; Windows gets the same results.

Later steps add the per-OS tool layer (media, volume, clipboard, ...) here and in platform_windows.py / platform_linux.py."""
import os
import sys
import time

IS_WINDOWS = sys.platform == "win32"
NO_WINDOW = 0x08000000 if IS_WINDOWS else 0          # subprocess creationflags: no console window flashing up (0 elsewhere)


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


# ── per-OS backend (platform_linux.py / platform_windows.py, loaded on first use) ──
def human(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024


def backend():
    if IS_WINDOWS:
        import platform_windows as b
    else:
        import platform_linux as b
    return b


def start_shell(cmnd):
    """Starts a shell command with stdout and stderr in one pipe, in its own process group. Linux: sh; Windows: PowerShell."""
    return backend().start_shell(cmnd)


def kill_tree(proc):
    """Kills the process and everything it started."""
    backend().kill_tree(proc)


def system_info():
    """Report lines for the system_info tool (uptime, load, memory, disks, temperature, battery, busiest processes)."""
    return backend().system_info()


def mem_available_percent():
    """Free memory in percent, or None when unknown."""
    return backend().mem_available_percent()


def service_state(name):
    """'active' / 'inactive' / 'not installed' for the background job called `name` ('daemon', 'daemon-agent'), or '' when unknown."""
    return backend().service_state(name)


def backup_scheduled():
    """True when the daily backup job is installed (systemd timer on Linux, scheduled task on Windows)."""
    return backend().backup_scheduled()


def shell_hint():
    """One line for the model about the shell execute_command uses on this computer ('' on Linux, where it is the usual sh)."""
    return backend().SHELL_HINT
