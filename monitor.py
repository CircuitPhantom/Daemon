"""What Daemon knows about its own health: the /status (status) report, the problems the watchdog alerts on,
and the check that the dashboard page and the server belong together.

Used by routines.py (alerts), conversation.py (Signal /status) and the /api/health endpoint.
"""
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import model_config

# Bump this number in BOTH places when the page and the server must be updated together:
# here, and in index.html (<meta name="daemon-ui" content="...">). A page or server file that did not get copied
# shows up as a mismatch in /api/health, in doctor.py, in the log at startup and as a banner on the page.
UI_VERSION = 3
STARTED = time.time()
HERE = Path(__file__).resolve().parent
_seen = {"laptop": 0.0}                # when the laptop agent was last connected


def ui_file_version(path=None):
    """The number written in index.html, or None when the file has none (an old index.html)."""
    try:
        text = (path or HERE / "index.html").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r'<meta\s+name="daemon-ui"\s+content="(\d+)"', text)
    return int(m.group(1)) if m else None


def health():
    ui = ui_file_version()
    return {"ok": True, "ui": UI_VERSION, "ui_file": ui, "ui_match": ui == UI_VERSION,
            "uptime": int(time.time() - STARTED)}


def _cmd(cmd, timeout=6):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return 1, str(e)


def backup_dir():
    return Path(os.environ.get("DAEMON_BACKUP_DIR") or "~/daemon-backups").expanduser()


def newest_backup():
    """Age of the newest backup in hours, or None when there is no backup folder / no backup yet."""
    d = backup_dir()
    try:
        files = [p for p in d.iterdir() if p.is_file()]
    except OSError:
        return None
    if not files:
        return None
    return (time.time() - max(p.stat().st_mtime for p in files)) / 3600


def _mem_available_percent():
    try:
        info = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, _, v = line.partition(":")
            info[k] = int(v.split()[0])
        return 100.0 * info["MemAvailable"] / info["MemTotal"]
    except Exception:
        return None


def checks():
    """Every check as {key, ok, text, alert}. `alert` False = shown in /status but never sent as an alert."""
    import llm
    import signal_bot
    import satellite
    care = model_config.care
    out = []

    def add(key, ok, text, alert=True):
        out.append({"key": key, "ok": bool(ok), "text": text, "alert": alert})

    du = shutil.disk_usage(Path.home())
    free = 100.0 * du.free / du.total
    add("disk", free >= care["disk_free_percent"], f"disk: {free:.0f}% free ({du.free / 1e9:.1f} GB)")
    mem = _mem_available_percent()
    if mem is not None:
        add("memory", mem >= 6, f"memory: {mem:.0f}% available")
    try:
        load = os.getloadavg()[0] / (os.cpu_count() or 1)
        add("load", True, f"load: {load:.1f} per core", alert=False)
    except OSError:
        pass

    st = llm.status()
    failing = st["last_error_ago"] is not None and (st["last_ok_ago"] is None or st["last_error_ago"] < st["last_ok_ago"])
    add("llm", st["configured"] and not failing,
        f"model {st['model']} ({st['name']}): " + ("not set up" if not st["configured"] else f"last request failed: {st['last_error']}" if failing else "ok"),
        alert=False)
    if signal_bot.bot.enabled():
        add("signal", signal_bot.bot.running(), "Signal: " + ("running" if signal_bot.bot.running() else "NOT running"), alert=False)

    if satellite.enabled():
        h = satellite.hub.status()
        now = time.time()
        if h["connected"]:
            _seen["laptop"] = now
        gone = now - _seen["laptop"] if _seen["laptop"] else 0
        grace = care["laptop_grace_minutes"] * 60
        add("laptop", h["connected"] or not _seen["laptop"] or gone < grace,
            f"laptop agent: {'connected (' + h['name'] + ')' if h['connected'] else 'offline'}")

    age = newest_backup()
    if age is not None:
        add("backup", age <= care["backup_max_hours"], f"last backup: {age:.0f} h ago" if age >= 1 else "last backup: under an hour ago")
    elif _cmd(["systemctl", "--user", "is-enabled", "daemon-backup.timer"])[0] == 0:       # the daily backup is set up but nothing came out of it
        add("backup", False, "the daily backup is on, but ~/daemon-backups has no backup yet (check: journalctl --user -u daemon-backup)")

    if shutil.which("tailscale"):
        code, _ = _cmd(["tailscale", "status"])
        add("tailscale", code == 0, "Tailscale: " + ("connected" if code == 0 else "NOT connected"))

    h = health()
    if not h["ui_match"]:
        add("ui", False, f"index.html is out of date (page {h['ui_file']}, server {h['ui']}): copy the new index.html")
    return out


def problems():
    return [c for c in checks() if not c["ok"] and c["alert"]]


def report():
    """The /status text."""
    import conversation as conv
    lines = []
    for c in checks():
        lines.append(("✅ " if c["ok"] else "⚠️ ") + c["text"])
    up = int(time.time() - STARTED)
    d, rest = divmod(up, 86400)
    head = f"Daemon up {d} d {rest // 3600} h {rest % 3600 // 60} min"
    try:
        head += f" · {len(conv.rem.list_items())} reminder(s) · {len(conv.sched.list_tasks())} task(s)"
    except Exception:
        pass
    return head + "\n" + "\n".join(lines)
