"""Windows backend of platform_support. Everything is imported lazily and guarded, so a missing optional package never crashes a tool."""
import base64
import os
import shutil
import subprocess
import time
from pathlib import Path

from platform_support import human as _human

SHELL_HINT = "Commands run in Windows PowerShell (not bash): use Get-ChildItem, Get-Content, $env:NAME, ';' between commands."

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
_NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
_PS_PRELUDE = "$ProgressPreference='SilentlyContinue';[Console]::OutputEncoding=[Text.Encoding]::UTF8;$OutputEncoding=[Text.Encoding]::UTF8;"


def powershell_argv(cmnd):
    """-EncodedCommand carries any quotes, pipes and non-ASCII text unchanged (no cmd.exe / argv quoting rules in between)."""
    blob = base64.b64encode((_PS_PRELUDE + cmnd).encode("utf-16-le")).decode("ascii")
    exe = shutil.which("powershell") or "powershell.exe"
    return [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", blob]


def start_shell(cmnd):
    return subprocess.Popen(powershell_argv(cmnd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, creationflags=_NEW_GROUP | _NO_WINDOW)


def kill_tree(proc):
    """taskkill /T walks the child processes; Popen.kill() alone would leave them running."""
    try:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=10, creationflags=_NO_WINDOW)
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass


def system_info():
    out = []
    try:
        import psutil
    except ImportError:
        psutil = None
    if psutil:
        try:
            up = time.time() - psutil.boot_time()
            d, h, m = int(up // 86400), int(up % 86400 // 3600), int(up % 3600 // 60)
            out.append(f"Uptime: {d} d {h} h {m} min")
        except Exception:
            pass
        try:
            out.append(f"CPU: {psutil.cpu_percent(interval=0.3):.0f}% busy on {os.cpu_count()} cores")
        except Exception:
            pass
        try:
            vm = psutil.virtual_memory()
            out.append(f"Memory: {_human(vm.total - vm.available)} used of {_human(vm.total)} ({int(vm.percent)}%)")
        except Exception:
            pass
    for mount in dict.fromkeys([os.environ.get("SystemDrive", "C:") + "\\", str(Path.home().anchor or Path.home())]):
        try:
            du = shutil.disk_usage(mount)
            out.append(f"Disk {mount}: {_human(du.used)} used of {_human(du.total)} ({du.used * 100 // du.total}%), {_human(du.free)} free")
        except Exception:
            pass
    if psutil:
        try:
            b = psutil.sensors_battery()
            if b is not None:
                out.append(f"Battery: {b.percent:.0f}% ({'charging' if b.power_plugged else 'discharging'})")
        except Exception:
            pass
        try:
            procs = []
            for p in psutil.process_iter(["name", "memory_percent"]):
                procs.append((p.info.get("memory_percent") or 0, p.info.get("name") or "?"))
            procs.sort(reverse=True)
            out.append("Biggest processes (name, %mem): " + "; ".join(f"{n} {m:.1f}" for m, n in procs[:3]))
        except Exception:
            pass
    else:
        out.append("(install psutil for CPU, memory and battery: pip install psutil)")
    return out


def mem_available_percent():
    try:
        import psutil
        vm = psutil.virtual_memory()
        return 100.0 * vm.available / vm.total
    except Exception:
        return None


def _schtasks(*args):
    try:
        r = subprocess.run(["schtasks", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10, creationflags=_NO_WINDOW)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return 1, str(e)


def _task_name(name):
    return {"daemon": "Daemon", "daemon-agent": "Daemon Agent"}.get(name, name)


def service_state(name):
    """Daemon runs as a Task Scheduler task (install-service.ps1): 'Running' means it is up."""
    code, out = _schtasks("/Query", "/TN", _task_name(name), "/FO", "LIST")
    if code != 0:
        return "not installed"
    for line in out.splitlines():
        k, _, v = line.partition(":")
        if k.strip().lower() in ("status", "durum"):                  # the label is translated on a non-English Windows
            return "active" if v.strip().lower() in ("running", "çalışıyor") else "inactive"
    return "inactive"


def backup_scheduled():
    return _schtasks("/Query", "/TN", "Daemon Backup")[0] == 0
