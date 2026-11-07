"""Things Daemon does on its own, quietly, without a task: the watchdog (Signal alert when something is wrong),
the weekly memory check, and the extras in the morning plan.

Settings: config.yaml -> care (Settings > Automation in the dashboard). The state (what was alerted when, the last memory
check) is kept in care_state.json next to config.yaml (override: DAEMON_CARE_STATE).
"""
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import model_config

OLD_DAYS = 180
SIMILAR = 0.6                        # share of words two memories have in common before they count as "similar"
_lock = threading.RLock()


def _state_path():
    return Path(os.environ.get("DAEMON_CARE_STATE") or model_config.CONFIG_PATH.with_name("care_state.json"))


def _load():
    try:
        d = json.loads(_state_path().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(d):
    try:
        model_config.atomic_write(_state_path(), json.dumps(d, indent=1))
    except Exception as e:
        print("[care] could not save state:", e)


def _send(text):
    import scheduler
    try:
        return scheduler.send_message(text)
    except Exception as e:
        return False, str(e)


# ── the watchdog ──
def watch_once(now=None):
    """One look at everything. Sends an alert for each new or long-standing problem and a note when one is solved.
    Returns the list of alerts sent (for tests)."""
    import monitor
    now = now or time.time()
    care = model_config.care
    sent = []
    with _lock:
        st = _load()
        open_ = st.setdefault("open", {})              # key -> {"since", "alerted"}
        bad = {c["key"]: c for c in monitor.problems()}
        for key, c in bad.items():
            o = open_.setdefault(key, {"since": now, "alerted": 0})
            if not o["alerted"] or now - o["alerted"] >= care["alert_repeat_hours"] * 3600:
                ok, info = _send("⚠️ Daemon: " + c["text"])
                if ok:
                    o["alerted"] = now
                    sent.append(c["text"])
                else:
                    print("[care] alert not sent:", info)
        for key in [k for k in open_ if k not in bad]:
            o = open_.pop(key)
            if o.get("alerted"):
                ok, _ = _send(f"✅ Daemon: {key} is fine again.")
                if ok:
                    sent.append(f"{key} fine again")
        _save(st)
    return sent


# ── the weekly memory check ──
def _words(s):
    return set(re.findall(r"\w{3,}", s.lower()))


def memory_report():
    """Text about memories that look doubled or very old. Empty when there is nothing to say."""
    import memstore
    items = memstore.items()
    lines = []
    seen = set()
    for i, a in enumerate(items):
        wa = _words(a["text"])
        for b in items[i + 1:]:
            wb = _words(b["text"])
            if wa and wb and len(wa & wb) / len(wa | wb) >= SIMILAR and (a["id"], b["id"]) not in seen:
                seen.add((a["id"], b["id"]))
                lines.append(f"Similar: [{a['id']}] {a['text'][:90]}\n         [{b['id']}] {b['text'][:90]}")
    cutoff = time.time() - OLD_DAYS * 86400
    old = [x for x in items if x.get("created", time.time()) < cutoff]
    for x in old[:6]:
        lines.append(f"Old ({int((time.time() - x['created']) / 86400)} days): [{x['id']}] {x['text'][:100]}")
    if len(items) >= memstore.MAX_ITEMS * 0.9:
        lines.append(f"The memory is nearly full ({len(items)} of {memstore.MAX_ITEMS}).")
    if not lines:
        return ""
    return "🧠 Memory check\n" + "\n".join(lines[:12]) + "\n\nRemove one with: /forget <id>   (list everything: /memory)"


def review_once(now=None):
    """Sends the weekly memory check when it is due. Returns the text sent, or ''."""
    care = model_config.care
    if not care["memory_review"]:
        return ""
    import scheduler
    now = now or datetime.now(scheduler.get_tz())
    hh, mm = (int(x) for x in care["memory_review_time"].split(":"))
    due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    key = now.date().isoformat()
    if now.weekday() != care["memory_review_day"] or not (due <= now < due + timedelta(hours=6)):
        return ""
    with _lock:
        st = _load()
        if st.get("memory_review") == key:
            return ""
        st["memory_review"] = key                       # marked first: a failure must not repeat all day
        _save(st)
    text = memory_report()
    if text:
        ok, info = _send(text)
        if not ok:
            print("[care] memory check not sent:", info)
    return text


# ── the morning plan: extras ──
def weather(city):
    """One line from wttr.in, or ''."""
    if not city:
        return ""
    try:
        url = "https://wttr.in/" + urllib.parse.quote(city) + "?format=%25l:+%25C+%25t,+wind+%25w&m"
        req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
        with urllib.request.urlopen(req, timeout=6) as r:
            text = r.read(400).decode("utf-8", "replace").strip()
        return text if text and "<" not in text and len(text) < 200 else ""
    except Exception:
        return ""


def briefing_extras(day):
    """(text, has_items): lines for under the day's plan: weather, reminders of that day, the inbox of the last day."""
    care = model_config.care
    if not care["briefing_extras"]:
        return "", False
    import conversation as conv
    import inbox
    import scheduler
    tz = scheduler.get_tz()
    parts = []
    w = weather(care["briefing_city"])
    if w:
        parts.append("🌤 " + w)
    try:
        rs = [r for r in conv.rem.list_items() if datetime.fromtimestamp(r["due"], tz).date() == day]
        if rs:
            parts.append("⏰ Reminders:\n" + "\n".join(
                f"  {datetime.fromtimestamp(r['due'], tz).strftime('%H:%M')} {r['text']}" for r in rs[:8]))
    except Exception as e:
        print("[care] reminders for the plan:", e)
    try:
        new = [x for x in inbox.items() if x["ts"] > time.time() - 86400]
        if new:
            parts.append(f"📥 Saved to the inbox since yesterday: {len(new)}\n" + "\n".join("  " + inbox.line(x) for x in new[:3]))
    except Exception as e:
        print("[care] inbox for the plan:", e)
    return "\n".join(parts), len(parts) > (1 if w else 0)      # (text, is there more than the weather)


# ── the loop ──
class Care:
    def __init__(self):
        self._stop = threading.Event()
        self._thread = None
        self._last_watch = 0.0

    def start(self):
        if self._thread:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="care", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread = None

    def _loop(self):
        self._stop.wait(45)                               # let Signal and the rest start first
        while not self._stop.is_set():
            try:
                model_config.reload_if_changed()
                care = model_config.care
                if care["watchdog"] and time.time() - self._last_watch >= care["watch_minutes"] * 60:
                    self._last_watch = time.time()
                    watch_once()
                review_once()
            except Exception as e:
                print("[care] failed:", type(e).__name__, e)
            self._stop.wait(30)


care = Care()
