"""Linux backend of platform_support. The code here was moved out of tools.py / monitor.py / doctor.py unchanged."""
import os
import shutil
import signal
import subprocess
from pathlib import Path

from platform_support import human as _human

SHELL_HINT = ""


def start_shell(cmnd):
    return subprocess.Popen(cmnd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, start_new_session=True)


def kill_tree(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)       # also kills anything the command started
    except ProcessLookupError:
        pass


def system_info():
    out = []
    try:
        up = float(open("/proc/uptime", encoding="utf-8").read().split()[0])
        d, h, m = int(up // 86400), int(up % 86400 // 3600), int(up % 3600 // 60)
        out.append(f"Uptime: {d} d {h} h {m} min")
    except Exception:
        pass
    try:
        l1, l5, l15 = os.getloadavg()
        out.append(f"Load average: {l1:.2f} {l5:.2f} {l15:.2f} on {os.cpu_count()} cores")
    except Exception:
        pass
    try:
        mem = {k: int(v.split()[0]) * 1024 for k, v in (l.split(":", 1) for l in open("/proc/meminfo", encoding="utf-8"))}
        used = mem["MemTotal"] - mem["MemAvailable"]
        out.append(f"Memory: {_human(used)} used of {_human(mem['MemTotal'])} ({used * 100 // mem['MemTotal']}%)")
        if mem.get("SwapTotal"):
            out.append(f"Swap: {_human(mem['SwapTotal'] - mem['SwapFree'])} used of {_human(mem['SwapTotal'])}")
    except Exception:
        pass
    for mount in dict.fromkeys(["/", str(Path.home())]):
        try:
            du = shutil.disk_usage(mount)
            out.append(f"Disk {mount}: {_human(du.used)} used of {_human(du.total)} ({du.used * 100 // du.total}%), {_human(du.free)} free")
        except Exception:
            pass
    temps = []
    for z in sorted(Path("/sys/class/thermal").glob("thermal_zone*")):
        try:
            temps.append(int((z / "temp").read_text(encoding="utf-8")) / 1000)
        except Exception:
            pass
    if temps:
        out.append(f"Temperature: {max(temps):.0f} °C (hottest sensor)")
    for b in sorted(Path("/sys/class/power_supply").glob("BAT*")):
        try:
            out.append(f"Battery: {(b / 'capacity').read_text(encoding='utf-8').strip()}% ({(b / 'status').read_text(encoding='utf-8').strip()})")
        except Exception:
            pass
    try:
        ps = subprocess.run(["ps", "-eo", "comm,%cpu,%mem", "--sort=-%cpu"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5).stdout.splitlines()[1:4]
        out.append("Busiest processes (name, %CPU, %mem): " + "; ".join(" ".join(l.split()) for l in ps))
    except Exception:
        pass
    return out


def mem_available_percent():
    try:
        info = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition(":")
            info[k] = int(v.split()[0])
        return 100.0 * info["MemAvailable"] / info["MemTotal"]
    except Exception:
        return None


def _systemctl(*args):
    try:
        r = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return 1, str(e)


def service_state(name):
    return _systemctl("is-active", name + ".service")[1]


def backup_scheduled():
    return _systemctl("is-enabled", "daemon-backup.timer")[0] == 0
