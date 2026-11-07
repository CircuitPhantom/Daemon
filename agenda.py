"""Calendar: events on a day, either all day or at a time. Stored in calendar.json next to config.yaml.

You edit it in the dashboard (Calendar button) and the model can read and change it with the
calendar_* tools. Optionally Daemon also

  * calls you every morning at a time you choose and tells you the plan of the day (calendar.briefing),
  * sends a Signal message before an event that has "remind me N minutes before".

The module is named agenda because a file called calendar.py would hide Python's own calendar module.
"""
import calendar as pycal
import json
import os
import re
import secrets
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import model_config

MAX_EVENTS = 5000
LATE_BRIEFING = timedelta(hours=3)        # a morning call is skipped if Daemon was off for longer than this
REMIND_WINDOW = timedelta(minutes=5)      # an event reminder is still sent this long after its time
WEEKDAYS = {"monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "wednesday": 2, "wed": 2, "thursday": 3, "thu": 3,
            "friday": 4, "fri": 4, "saturday": 5, "sat": 5, "sunday": 6, "sun": 6,
            "pazartesi": 0, "salı": 1, "çarşamba": 2, "perşembe": 3, "cuma": 4, "cumartesi": 5, "pazar": 6}
ALL_DAY = {"", "all day", "allday", "all-day", "tüm gün", "tum gun", "tüm gün boyu", "none", "null"}


class CalendarError(ValueError):
    """A problem with what was asked (shown to the person or the model as it is)."""


def _tz():
    import scheduler                                      # notify.timezone, not the server's own clock zone
    return scheduler.get_tz()


def today(tz=None):
    return datetime.now(tz or _tz()).date()


def parse_date(text, ref=None):
    """ISO date, 31.10.2026, today / tomorrow / yesterday, a weekday name (this week or the next one), 'in 3 days'."""
    ref = ref or today()
    t = " ".join(str(text or "").strip().lower().split())
    if not t:
        raise CalendarError("a date is needed, for example 2026-11-02, tomorrow or friday")
    if t in ("today", "bugün", "bugun"):
        return ref
    if t in ("tomorrow", "yarın", "yarin"):
        return ref + timedelta(days=1)
    if t in ("yesterday", "dün", "dun"):
        return ref - timedelta(days=1)
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", t) or None
    try:
        if m:
            return date(int(m[1]), int(m[2]), int(m[3]))
        m = re.fullmatch(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", t)
        if m:
            return date(int(m[3]), int(m[2]), int(m[1]))
        m = re.fullmatch(r"(\d{1,2})[./](\d{1,2})", t)
        if m:                                              # day.month without a year: the next time it comes
            d = date(ref.year, int(m[2]), int(m[1]))
            return d if d >= ref else date(ref.year + 1, int(m[2]), int(m[1]))
    except ValueError:
        raise CalendarError(f"{text!r} is not a real date") from None
    m = re.fullmatch(r"in (\d{1,4}) days?", t)
    if m:
        return ref + timedelta(days=int(m[1]))
    t2 = re.sub(r"^(next|this|coming|gelecek|önümüzdeki)\s+", "", t)
    if t2 in WEEKDAYS:
        return ref + timedelta(days=(WEEKDAYS[t2] - ref.weekday()) % 7)
    raise CalendarError(f"could not understand the date {text!r}; use 2026-11-02, tomorrow or a weekday")


def parse_time(text):
    """'HH:MM' from 15:30, 9, 9.30, 9am, 9:30 pm. None for all day / empty."""
    t = str(text or "").strip().lower()
    if t in ALL_DAY:
        return None
    m = re.fullmatch(r"(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?", t)
    if not m:
        raise CalendarError(f"could not understand the time {text!r}; use 15:30 or 3:30pm, or leave it empty for all day")
    h, mi, ap = int(m[1]), int(m[2] or 0), (m[3] or "")[:1]
    if ap:
        if not 1 <= h <= 12:
            raise CalendarError(f"{text!r} is not a valid time")
        h = h % 12 + (12 if ap == "p" else 0)
    if h > 23 or mi > 59:
        raise CalendarError(f"{text!r} is not a valid time")
    return f"{h:02d}:{mi:02d}"


def say_time(hhmm):
    """15:30 -> 3:30 PM, 10:00 -> 10 AM (reads better aloud)."""
    h, m = int(hhmm[:2]), int(hhmm[3:])
    ap = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12} {ap}" if m == 0 else f"{h12}:{m:02d} {ap}"


FREQS = {"daily", "weekly", "monthly", "yearly"}
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def parse_days(v):
    """[0, 2] / "mon,wed" / "monday wednesday" -> [0, 2] (Monday = 0)."""
    if v in (None, ""):
        return []
    items = v if isinstance(v, (list, tuple)) else re.split(r"[,\s]+", str(v).strip().lower())
    out = set()
    for x in items:
        if isinstance(x, int) or (isinstance(x, str) and x.strip().isdigit()):
            n = int(x)
            if not 0 <= n <= 6:
                raise CalendarError("weekdays are 0 (Monday) to 6 (Sunday)")
            out.add(n)
        elif str(x).strip():
            k = str(x).strip().lower()
            if k not in WEEKDAYS:
                raise CalendarError(f"unknown weekday {x!r}")
            out.add(WEEKDAYS[k])
    return sorted(out)


def norm_repeat(r, start=None):
    """The repeat rule as stored: None or {freq, every, days, until}. Accepts None/'none', 'weekdays', 'daily', ... or a dict."""
    if r in (None, "", False) or (isinstance(r, str) and r.strip().lower() in ("none", "no", "never", "off")):
        return None
    if isinstance(r, str):
        k = r.strip().lower()
        r = {"freq": "weekly", "days": [0, 1, 2, 3, 4]} if k in ("weekdays", "weekday") else {"freq": k}
    if not isinstance(r, dict):
        raise CalendarError("repeat must be none, daily, weekdays, weekly, monthly or yearly")
    freq = str(r.get("freq") or "").strip().lower()
    freq = {"day": "daily", "week": "weekly", "month": "monthly", "year": "yearly"}.get(freq, freq)
    if freq not in FREQS:
        raise CalendarError("repeat must be none, daily, weekdays, weekly, monthly or yearly")
    try:
        every = r.get("every", r.get("interval"))
        every = 1 if every in (None, "") else int(every)
    except (TypeError, ValueError):
        raise CalendarError("every must be a number") from None
    if not 1 <= every <= 365:
        raise CalendarError("every must be between 1 and 365")
    days = parse_days(r.get("days")) if freq == "weekly" else []
    until = r.get("until")
    until = parse_date(until).isoformat() if str(until or "").strip() else None
    if until and start and until < start:
        raise CalendarError("the repeat end date is before the first date")
    return {"freq": freq, "every": every, "days": days, "until": until}


def repeat_text(r):
    if not r:
        return ""
    n = r["every"]
    if r["freq"] == "weekly" and r["days"] == [0, 1, 2, 3, 4] and n == 1:
        t = "every weekday"
    elif r["freq"] == "weekly" and r["days"]:
        t = ("every " if n == 1 else f"every {n} weeks on ") + ",".join(DAY_NAMES[d] for d in r["days"])
    else:
        unit = {"daily": "day", "weekly": "week", "monthly": "month", "yearly": "year"}[r["freq"]]
        t = f"every {unit}" if n == 1 else f"every {n} {unit}s"
    return t + (f" until {r['until']}" if r["until"] else "")


def occurs(e, d):
    """Does event `e` (as stored) happen on date `d`?"""
    base = date.fromisoformat(e["date"])
    if d < base:
        return False
    r = e.get("repeat")
    if not r:
        return d == base
    iso = d.isoformat()
    if iso in e.get("skip", ()) or (r["until"] and iso > r["until"]):
        return False
    n = r["every"]
    if r["freq"] == "daily":
        return (d - base).days % n == 0
    if r["freq"] == "weekly":
        weeks = ((d - timedelta(days=d.weekday())) - (base - timedelta(days=base.weekday()))).days // 7
        return d.weekday() in (r["days"] or [base.weekday()]) and weeks % n == 0
    months = (d.year - base.year) * 12 + d.month - base.month
    if r["freq"] == "monthly" and months % n:
        return False
    if r["freq"] == "yearly" and (months % 12 or (months // 12) % n):
        return False
    return d.day == min(base.day, pycal.monthrange(d.year, d.month)[1])


def _sort_key(e):
    return (e["date"], e["start"] is not None, e["start"] or "", e["title"].lower())


class Agenda:
    def __init__(self, path=None):
        self.path = Path(path or os.environ.get("DAEMON_CALENDAR") or model_config.CONFIG_PATH.with_name("calendar.json"))
        self._lock = threading.RLock()
        self._events, self._state, self._mtime = [], {}, None
        self._stop = threading.Event()
        self._thread = None
        self._load()

    # ── storage ──
    def _stat(self):
        try:
            return self.path.stat().st_mtime_ns
        except OSError:
            return None

    def _load(self):
        with self._lock:
            self._mtime = self._stat()
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                data = {}
            except Exception as e:
                print(f"[calendar] could not read {self.path.name}: {e}")
                keep = self.path.with_name(self.path.name + ".broken")
                try:
                    self.path.replace(keep)
                    print(f"[calendar] the damaged file was kept as {keep.name}")
                except OSError:
                    pass
                data = {}
            ev = data.get("events") if isinstance(data, dict) else None
            self._events = [self._fix(e) for e in (ev or []) if self._valid(e)]
            st = data.get("state") if isinstance(data, dict) else None
            self._state = st if isinstance(st, dict) else {}

    @staticmethod
    def _valid(e):
        try:
            return (isinstance(e, dict) and e["id"] and e["title"] and date.fromisoformat(e["date"])
                    and (e.get("start") is None or re.fullmatch(r"\d\d:\d\d", e["start"])))
        except Exception:
            return False

    @staticmethod
    def _fix(e):
        try:
            e["repeat"] = norm_repeat(e.get("repeat"))
        except CalendarError:
            e["repeat"] = None
        sk = e.get("skip")
        e["skip"] = sorted(x for x in sk if isinstance(x, str)) if isinstance(sk, list) else []
        return e

    def _save(self):
        model_config.atomic_write(self.path, json.dumps({"events": self._events, "state": self._state},
                                                        ensure_ascii=False, indent=1))
        self._mtime = self._stat()

    def _fresh(self):
        if self._stat() != self._mtime:
            self._load()

    # ── events ──
    def _clean(self, data, base=None):
        """Validates `data` (a dict with any of title, date, start, end, notes, remind) on top of `base`."""
        e = dict(base or {"title": "", "date": "", "start": None, "end": None, "notes": "", "remind": None,
                          "repeat": None, "skip": []})
        if "title" in data:
            e["title"] = " ".join(str(data["title"] or "").split())[:120]
        if not e["title"]:
            raise CalendarError("the event needs a title")
        if "date" in data:
            e["date"] = parse_date(data["date"]).isoformat()
        if not e["date"]:
            raise CalendarError("the event needs a date")
        if "start" in data:
            e["start"] = parse_time(data["start"])
        if "end" in data:
            e["end"] = parse_time(data["end"])
        if e["start"] is None:
            e["end"] = None                                  # an all-day event has no end time
        elif e["end"] is not None and e["end"] <= e["start"]:
            raise CalendarError("the end time must be after the start time")
        if "notes" in data:
            e["notes"] = str(data["notes"] or "").strip()[:1000]
        if "remind" in data:
            r = data["remind"]
            if r in (None, "", False) or r == 0:
                e["remind"] = None
            else:
                try:
                    r = int(r)
                except (TypeError, ValueError):
                    raise CalendarError("remind must be a number of minutes") from None
                if not 1 <= r <= 10080:
                    raise CalendarError("remind must be between 1 minute and 7 days")
                e["remind"] = r
        if "repeat" in data:
            e["repeat"] = norm_repeat(data["repeat"], e["date"])
        elif e.get("repeat") and e["repeat"]["until"] and e["repeat"]["until"] < e["date"]:
            raise CalendarError("the event is moved past the end of its repeat; change the repeat too")
        if e["remind"] is not None and e["start"] is None:
            e["remind"] = None                               # reminders need a time of day
        return e

    def add(self, data):
        with self._lock:
            self._fresh()
            if len(self._events) >= MAX_EVENTS:
                raise CalendarError(f"the calendar is full ({MAX_EVENTS} events)")
            e = self._clean(data)
            e["id"] = secrets.token_hex(4)
            self._events.append(e)
            self._save()
            return dict(e)

    def update(self, ev_id, patch):
        with self._lock:
            self._fresh()
            for i, e in enumerate(self._events):
                if e["id"] == ev_id:
                    new = self._clean(patch, e)
                    new["id"] = ev_id
                    self._events[i] = new
                    rem = self._state.get("reminded", {})                       # a moved event may be reminded again
                    for k in [k for k in rem if k.startswith(ev_id + ":")]:
                        del rem[k]
                    self._save()
                    return dict(new)
            raise CalendarError(f"no event with id {ev_id}")

    def delete(self, ev_id, only=None):
        """Deletes the event; for a repeating one, `only` (a date) removes just that day."""
        with self._lock:
            self._fresh()
            ev = next((e for e in self._events if e["id"] == ev_id), None)
            if ev and ev.get("repeat") and only:
                d = parse_date(only)
                if not occurs(ev, d):
                    raise CalendarError(f"{ev['title']} does not happen on {d.isoformat()}")
                ev["skip"] = sorted(set(ev["skip"]) | {d.isoformat()})
                self._save()
                return
            n = len(self._events)
            self._events = [e for e in self._events if e["id"] != ev_id]
            if len(self._events) == n:
                raise CalendarError(f"no event with id {ev_id}")
            self._save()

    @staticmethod
    def between_one(e, a, b):
        out, d = [], max(a, date.fromisoformat(e["date"]))
        while d <= b:
            if occurs(e, d):
                out.append({**e, "date": d.isoformat()})
            d += timedelta(days=1)
        return out

    def get(self, ev_id):
        with self._lock:
            self._fresh()
            return next((dict(e) for e in self._events if e["id"] == ev_id), None)

    def between(self, d1, d2):
        """Events from date d1 to d2 (inclusive, ISO strings), in order."""
        with self._lock:
            self._fresh()
            out = []
            a, b = date.fromisoformat(d1), date.fromisoformat(d2)
            for e in self._events:
                if not e["repeat"]:
                    if d1 <= e["date"] <= d2:
                        out.append({**e, "series_date": e["date"]})
                    continue
                d = max(a, date.fromisoformat(e["date"]))
                while d <= b:
                    if occurs(e, d):
                        out.append({**e, "date": d.isoformat(), "series_date": e["date"]})
                    d += timedelta(days=1)
            return sorted(out, key=_sort_key)

    # ── text for the model and for speaking ──
    @staticmethod
    def line(e):
        d = date.fromisoformat(e["date"])
        when = "all day" if e["start"] is None else e["start"] + (f"-{e['end']}" if e["end"] else "")
        extra = ((f" [{repeat_text(e['repeat'])}]") if e.get("repeat") else "") + \
                (f" [remind {e['remind']} min before]" if e["remind"] else "") + (f" - {e['notes']}" if e["notes"] else "")
        return f"{e['id']} | {d.strftime('%a %Y-%m-%d')} | {when} | {e['title']}{extra}"

    def plan_text(self, day, hello=True):
        """The day's plan as a short spoken text."""
        evs = self.between(day.isoformat(), day.isoformat())
        h = datetime.now(_tz()).hour
        parts = [("Good morning." if h < 12 else "Hello.") if hello else ""]
        name = day.strftime("%A %-d %B") if os.name != "nt" else day.strftime("%A %d %B")
        if not evs:
            parts.append(f"You have nothing planned for {name}.")
        else:
            n = len(evs)
            parts.append(f"{name}: you have {n} thing{'s' if n != 1 else ''} planned.")
            for e in evs[:8]:
                if e["start"] is None:
                    parts.append(f"All day: {e['title']}.")
                else:
                    end = f" until {say_time(e['end'])}" if e["end"] else ""
                    parts.append(f"At {say_time(e['start'])}{end}: {e['title']}.")
            if n > 8:
                parts.append(f"And {n - 8} more.")
        nxt = self.between((day + timedelta(days=1)).isoformat(), (day + timedelta(days=1)).isoformat())
        if nxt:
            parts.append(f"Tomorrow you have {len(nxt)} event{'s' if len(nxt) != 1 else ''}.")
        return " ".join(p for p in parts if p)

    # ── background: morning plan and event reminders ──
    def start(self):
        if self._thread:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="calendar")
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread = None

    def _loop(self):
        while not self._stop.wait(20):
            try:
                self.tick()
            except Exception as e:
                print("[calendar] tick failed:", e)

    @staticmethod
    def _rkey(e):
        return f"{e['id']}:{e['date']}:{e['start']}"

    def tick(self, now=None):
        import scheduler
        now = now or datetime.now(scheduler.get_tz())
        cfg = model_config.calendar_cfg
        if cfg.get("briefing"):
            hh, mm = (int(x) for x in cfg["briefing_time"].split(":"))
            due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            day = now.date().isoformat()
            with self._lock:
                self._fresh()
                go = now >= due and now - due < LATE_BRIEFING and self._state.get("briefed") != day
                if go:
                    self._state["briefed"] = day               # marked first, so a failure cannot repeat all morning
                    self._save()
            if go:
                self.brief(now.date(), manual=False)
        self._remind(now)

    def _remind(self, now):
        import scheduler
        due = []
        with self._lock:
            self._fresh()
            sent = self._state.setdefault("reminded", {})
            today = now.date()
            cand = []
            for e in self._events:
                if e.get("remind") and e["start"]:
                    cand += self.between_one(e, today - timedelta(days=1), today + timedelta(days=8))
            for e in cand:
                start = datetime.combine(date.fromisoformat(e["date"]), datetime.strptime(e["start"], "%H:%M").time(),
                                         tzinfo=now.tzinfo)
                if start - timedelta(minutes=e["remind"]) <= now < start + REMIND_WINDOW and self._rkey(e) not in sent:
                    sent[self._rkey(e)] = time.time()
                    due.append((e, start))
            for k in [k for k, t in sent.items() if time.time() - t > 3 * 86400]:
                del sent[k]
            if due:
                self._save()
        for e, start in due:
            mins = round((start - now).total_seconds() / 60)
            when = f"in {mins} min" if mins > 0 else "now"
            ok, info = scheduler.send_message(f"⏰ {e['title']} at {e['start']} ({when})" + (f"\n{e['notes']}" if e["notes"] else ""))
            if not ok:
                print("[calendar] reminder not sent:", info)

    def brief(self, day=None, manual=True):
        """Tells you the plan: a Signal message and, if set up, a phone call you can talk in. Returns a dict."""
        import scheduler
        import twilio_call
        cfg = model_config.calendar_cfg
        day = day or today(scheduler.get_tz())
        evs = self.between(day.isoformat(), day.isoformat())
        out = {"text": self.plan_text(day), "events": len(evs), "message": False, "call": False, "info": ""}
        extras, has_items = "", False
        try:
            import routines
            extras, has_items = routines.briefing_extras(day)
        except Exception as e:
            print("[calendar] extras for the plan failed:", e)
        if not evs and not has_items and cfg.get("briefing_skip_empty") and not manual:
            out["info"] = "nothing planned, skipped"
            return out
        ok, info = scheduler.send_message("📅 " + out["text"] + ("\n\n" + extras if extras else ""))
        out["message"] = ok
        if cfg.get("briefing_call") and twilio_call.configured():
            rang, cinfo = twilio_call.place_talk_call(out["text"] + " Is there anything you want to change?",
                                                      "Plan of the day: " + out["text"][:600])
            out["call"], info = rang, ("" if rang else f"call failed: {cinfo}")
        elif cfg.get("briefing_call"):
            info = "phone calls are not set up (notify.twilio_* in config.yaml)"
        out["info"] = info if not ok or info else "sent"
        print(f"[calendar] plan for {day}: message={out['message']} call={out['call']} {out['info']}")
        return out

    # ── what the model's tools use (plain text in, plain text out) ──
    def tool_list(self, start="today", end=""):
        d1 = parse_date(start)
        d2 = parse_date(end, d1) if str(end).strip() else d1
        if d2 < d1:
            raise CalendarError("the end date is before the start date")
        if (d2 - d1).days > 366:
            raise CalendarError("ask for at most one year at a time")
        evs = self.between(d1.isoformat(), d2.isoformat())
        if not evs:
            return f"No events from {d1.isoformat()} to {d2.isoformat()}."
        return "id | date | time | title\n" + "\n".join(self.line(e) for e in evs[:100]) + \
               (f"\n(and {len(evs) - 100} more)" if len(evs) > 100 else "")

    @staticmethod
    def _rule(repeat, every, until, days):
        return {"freq": repeat, "every": every or 1, "until": until, "days": days}

    def tool_add(self, title, date_, time_="", end_time="", notes="", remind_minutes=0, repeat="", every=1, until="", days=""):
        data = {"title": title, "date": date_, "start": time_, "end": end_time, "notes": notes, "remind": remind_minutes}
        if str(repeat).strip():
            data["repeat"] = repeat if str(repeat).strip().lower() in ("weekdays", "none") else self._rule(repeat, every, until, days)
        e = self.add(data)
        return "Added: " + self.line(e)

    def tool_update(self, ev_id, title="", date_="", time_="", end_time="", notes="", remind_minutes=-1,
                    repeat="", every=1, until="", days=""):
        patch = {}
        if str(title).strip():
            patch["title"] = title
        if str(date_).strip():
            patch["date"] = date_
        if str(time_).strip():
            patch["start"] = time_                        # "all day" makes it an all-day event
        if str(end_time).strip():
            patch["end"] = end_time                       # "none" removes the end time
        if str(notes).strip():
            patch["notes"] = "" if str(notes).strip().lower() == "none" else notes
        if remind_minutes is not None and int(remind_minutes) >= 0:
            patch["remind"] = remind_minutes
        if str(repeat).strip():
            patch["repeat"] = repeat if str(repeat).strip().lower() in ("weekdays", "none") else self._rule(repeat, every, until, days)
        if not patch:
            raise CalendarError("nothing to change")
        return "Updated: " + self.line(self.update(ev_id, patch))

    def tool_delete(self, ev_id, date_=""):
        e = self.get(ev_id)
        if e is None:
            raise CalendarError(f"no event with id {ev_id}")
        only = date_ if str(date_).strip() and e.get("repeat") else None
        self.delete(ev_id, only)
        return ("Removed %s from: " % parse_date(only).isoformat() if only else "Deleted: ") + self.line(e)


store = Agenda()
