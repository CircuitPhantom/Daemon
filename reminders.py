"""One-off reminders ("remind me in 10 minutes to ...").

Stored in reminders.json (override with DAEMON_REMINDERS). When one is due, it is sent to you on Signal
(and as a phone call if notify.twilio_reminders is on) and as a desktop notification if notify-send exists.
No model is involved when a reminder fires, so it is cheap and reliable. Created by the remind_me tool.
"""
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import model_config
import scheduler
import twilio_call

PATH = Path(os.environ.get("DAEMON_REMINDERS") or Path(__file__).with_name("reminders.json"))
MAX_PENDING = 50
MAX_AHEAD = 366 * 86400
LATE_AFTER = 120            # seconds after the due time a reminder is marked as late
GIVE_UP = 86400             # overdue reminders older than this are dropped without sending
TRIES = 3

_UNITS = {"s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
          "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
          "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
          "d": 86400, "day": 86400, "days": 86400}
_DUR = re.compile(r"(\d+(?:\.\d+)?)\s*([a-z]+)")
_TIME = re.compile(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?\b")
_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def parse_when(text, now):
    """'in 10 minutes', '18:30', 'tomorrow 9am', 'friday 20:00', '2026-11-02 08:00' -> aware datetime."""
    s = " ".join(str(text).lower().replace(",", " ").split())
    if not s:
        raise ValueError("when is empty")

    body = s[3:].strip() if s.startswith("in ") else s
    pairs = _DUR.findall(body)
    if pairs and _DUR.sub("", body).strip() == "" and all(u in _UNITS for _, u in pairs):
        secs = sum(float(n) * _UNITS[u] for n, u in pairs)
        return now + timedelta(seconds=secs)

    day, weekday = None, False
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", s)
    if m:
        day = datetime(int(m[1]), int(m[2]), int(m[3]), tzinfo=now.tzinfo).date()
        s = s.replace(m[0], " ")
    elif "tomorrow" in s:
        day, s = (now + timedelta(days=1)).date(), s.replace("tomorrow", " ")
    elif "today" in s:
        day, s = now.date(), s.replace("today", " ")
    else:
        for i, name in enumerate(_DAYS):
            if re.search(rf"\b{name}\b", s):
                day, weekday = (now + timedelta(days=(i - now.weekday()) % 7)).date(), True
                s = re.sub(rf"\b{name}\b", " ", s)
                break

    s = re.sub(r"\b(at|on)\b", " ", s)
    m = _TIME.search(s)
    if not m:
        raise ValueError("could not understand the time")
    hour, minute, ap = int(m[1]), int(m[2] or 0), m[3]
    if ap:
        if not 1 <= hour <= 12:
            raise ValueError("bad hour")
        hour = hour % 12 + (12 if ap == "pm" else 0)
    if hour > 23 or minute > 59:
        raise ValueError("bad time")
    rest = (s[:m.start()] + " " + s[m.end():]).strip()
    if rest:
        raise ValueError(f'did not understand "{rest}"')

    base = day or now.date()
    t = datetime(base.year, base.month, base.day, hour, minute, tzinfo=now.tzinfo)
    if day is None and t <= now:
        t += timedelta(days=1)          # a bare time that already passed means tomorrow
    elif weekday and t <= now:
        t += timedelta(days=7)          # "friday 9:00" on a Friday after 9: next Friday
    return t


class Reminders:
    def __init__(self):
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None

    # ── storage ──
    def _read(self):
        try:
            d = json.loads(PATH.read_text(encoding="utf-8"))
            return [x for x in d if isinstance(x, dict) and "due" in x and x.get("text")]
        except (FileNotFoundError, ValueError):
            return []

    def _write(self, items):
        model_config.atomic_write(PATH, json.dumps(items, ensure_ascii=False, indent=1))

    # ── API used by the tools ──
    def add(self, text, when):
        text = " ".join(str(text).split())[:300]
        if not text:
            raise ValueError("the reminder text is empty")
        tz = scheduler.get_tz()
        now = datetime.now(tz)
        due = parse_when(when, now)
        if due <= now + timedelta(seconds=5):
            raise ValueError("that time is in the past")
        if (due - now).total_seconds() > MAX_AHEAD:
            raise ValueError("that is more than a year away")
        with self._lock:
            items = self._read()
            if len(items) >= MAX_PENDING:
                raise ValueError("too many pending reminders")
            items.append({"id": secrets.token_hex(3), "text": text, "due": due.timestamp(), "tries": 0})
            self._write(items)
        return due

    def list_items(self):
        with self._lock:
            return sorted(self._read(), key=lambda x: x["due"])

    def delete(self, item_id):
        with self._lock:
            items = self._read()
            rest = [x for x in items if x["id"] != item_id]
            if len(rest) == len(items):
                raise KeyError(item_id)
            self._write(rest)

    def cancel(self, words):
        w = {x for x in re.findall(r"\w+", words.lower()) if len(x) > 2 and x not in ("the", "and", "for", "reminder", "remind")}
        with self._lock:
            items = self._read()
            if not w and len(items) == 1:
                w = set(re.findall(r"\w+", items[0]["text"].lower()))      # "cancel the reminder" with only one pending
            best, score = None, 0
            for x in items:
                s = len(w & set(re.findall(r"\w+", x["text"].lower())))
                if s > score:
                    best, score = x, s
            if not best or score * 2 < min(len(w), 4):      # enough of the words must match: never cancel a random one
                return None
            self._write([x for x in items if x["id"] != best["id"]])
            return best

    # ── delivery ──
    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True, name="reminders")
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.wait(5):
            try:
                self.fire_due()
            except Exception as e:
                print("[reminders] error:", e)

    def fire_due(self, now=None):
        now = now or time.time()
        with self._lock:
            items = self._read()
            due = [x for x in items if x["due"] <= now]
            if not due:
                return 0
            keep = [x for x in items if x["due"] > now]
            for x in due:
                if now - x["due"] > GIVE_UP:
                    print(f"[reminders] dropped an old reminder: {x['text']}")
                    continue
                if not self._deliver(x, now) and x["tries"] + 1 < TRIES:
                    x["tries"] += 1
                    x["due"] = now + 60          # try again in a minute
                    keep.append(x)
            self._write(keep)
        return len(due)

    @staticmethod
    def _deliver(x, now):
        tz = scheduler.get_tz()
        late = now - x["due"] > LATE_AFTER
        text = "⏰ Reminder: " + x["text"]
        if late:
            text += f"\n(was due {datetime.fromtimestamp(x['due'], tz).strftime('%a %H:%M')})"
        ok = False
        if scheduler.channels_configured():
            sent, info = scheduler.send_message(text)
            ok = ok or sent
            if not sent:
                print("[reminders] message failed:", info)
        if not late and twilio_call.reminders_enabled():
            rang, info = twilio_call.place_call("Reminder. " + x["text"])
            ok = ok or rang
            if not rang:
                print("[reminders] phone call failed:", info)
        if shutil.which("notify-send"):
            try:
                subprocess.run(["notify-send", "-u", "critical", "Daemon reminder", x["text"]],
                               timeout=5, stdin=subprocess.DEVNULL, capture_output=True)
                ok = True
            except Exception:
                pass
        print(f"[reminders] {'sent' if ok else 'NOT delivered'}: {x['text']}")
        return ok
