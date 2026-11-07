"""Safety for the model's tools: a log of every tool call, and your approval before the risky ones run.

config.yaml:
  security:
    confirm: true                                            # ask before the tools below run
    confirm_tools: [execute_command, write_file, send_file, screenshot]
    confirm_seconds: 90                                      # no answer in time = the tool is not run

How you are asked:
  * the request came from the dashboard: Approve / Deny buttons right in the chat,
  * from Signal, a phone call or the wake word: a Signal message (answer "yes" or "no"), and a banner on the dashboard.
Controlling the mouse and keyboard (computer) always asks, once per turn, as long as security.confirm is on.
Scheduled tasks never ask: you chose their tools when you made the task. They are logged like everything else.

Every tool call is written to tool_log.jsonl next to config.yaml (override: DAEMON_TOOL_LOG; the newest 2000 are kept)
and shown in Settings > Security.
"""
import contextvars
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

import model_config

# The turn a tool call belongs to: {"source": web | signal | phone | voice, "emit": fn or None}. Unset = a scheduled task.
current = contextvars.ContextVar("daemon_turn", default=None)

# Tools that can be put behind an approval (the switch list in Settings > Security)
CHOICES = ["execute_command", "write_file", "send_file", "send_message", "call_me", "clipboard_write", "open_app",
           "open_url", "screenshot", "calendar_delete", "inbox_delete", "spotify_play"]
ALWAYS_ASK = {"computer"}              # asked even when it is not in confirm_tools (while security.confirm is on)
MAX_LOG = 2000
YES = re.compile(r"^\W*(yes|y|yep|ok|okay|approve|allow|go)\W*(?:\s+([0-9a-f]{6}))?\W*$", re.I)
NO = re.compile(r"^\W*(no|n|nope|deny|stop|cancel)\W*(?:\s+([0-9a-f]{6}))?\W*$", re.I)

_lock = threading.Lock()
_log_lock = threading.Lock()
_pending = {}                       # id -> request
ask_signal = {"send": None}         # set by server.py: fn(text) -> (ok, info)
version = [0]                       # bumped when the list of open requests changes (the dashboard polls it)


def cfg():
    return model_config.security


def log_path():
    return Path(os.environ.get("DAEMON_TOOL_LOG") or model_config.CONFIG_PATH.with_name("tool_log.jsonl"))


def summary(name, args, n=300):
    """Arguments as one short line (for the log, the dashboard and the Signal question)."""
    if not isinstance(args, dict):
        return str(args)[:n]
    if name == "execute_command" and "cmnd" in args:
        s = str(args["cmnd"])
    elif name == "computer":
        a = args.get("action", "")
        detail = {"click": f"click at ({args.get('x')}, {args.get('y')})", "double_click": f"double-click at ({args.get('x')}, {args.get('y')})",
                  "right_click": f"right-click at ({args.get('x')}, {args.get('y')})", "type": f"type {str(args.get('text', ''))[:60]!r}",
                  "key": f"press {args.get('keys', '')}", "scroll": f"scroll {args.get('amount', '')}"}.get(a, a)
        s = (f"goal: {args.get('goal') or '(none given)'}; " if args.get("goal") else "") + detail
    elif name == "write_file":
        c = str(args.get("content", ""))
        s = f"{args.get('file', '')} ({len(c)} characters): {c[:80]}"
    else:
        s = ", ".join(f"{k}={v!r}" if not isinstance(v, str) else f"{k}={v}" for k, v in args.items())
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


# ── approval ──
def needs_approval(name):
    c = cfg()
    return bool(c["confirm"] and (name in c["confirm_tools"] or name in ALWAYS_ASK))


def check(name, args, cancel=None):
    """Called right before a tool runs. Returns (allowed, how): how is auto / task / approved, or why it was refused."""
    ctx = current.get()
    if not needs_approval(name):
        return True, "auto"
    if name == "computer" and isinstance(args, dict) and str(args.get("action", "")).strip().lower() in ("shortcuts", "zoom"):
        return True, "auto"                              # only reads the key bindings
    if ctx is None:
        return True, "task"                              # scheduled task: its tools were chosen when it was made
    if name == "computer" and "computer" in ctx.get("grants", ()):
        return True, "approved earlier this turn"
    rid = secrets.token_hex(3)
    req = {"id": rid, "tool": name, "args": summary(name, args), "source": ctx.get("source", "web"), "at": time.time(),
           "timeout": int(cfg()["confirm_seconds"]), "event": threading.Event(), "answer": None}
    with _lock:
        _pending[rid] = req
        version[0] += 1
    emit = ctx.get("emit") if ctx.get("source") == "web" else None
    try:
        if emit:
            emit({"type": "approve", "id": rid, "tool": name, "args": req["args"], "timeout": req["timeout"]})
        elif ask_signal["send"]:
            what = (f"⚠️ Daemon wants to control your mouse and keyboard for this turn (up to {model_config.computer['max_actions']} actions):\n"
                    if name == "computer" else f"⚠️ Daemon wants to use {name}:\n")
            ok, info = ask_signal["send"](f"{what}{req['args']}\n\n"
                                          f"Reply yes or no (within {req['timeout']} s). You can also answer on the dashboard.")
            if not ok:
                print("[approve] could not ask on Signal:", info)
        print(f"[approve] waiting for your OK: {name} ({req['args'][:80]})")
        end = time.monotonic() + req["timeout"]
        while not req["event"].wait(0.25):
            if cancel is not None and cancel.is_set():
                req["answer"] = (False, "the reply was stopped")
                break
            if time.monotonic() > end:
                req["answer"] = (False, f"no answer within {req['timeout']} s")
                break
    finally:
        with _lock:
            _pending.pop(rid, None)
            version[0] += 1
    ok, why = req["answer"] or (False, "no answer")
    if emit:
        try:
            emit({"type": "approved", "id": rid, "ok": ok})
        except Exception:
            pass
    if ok and name == "computer":
        ctx.setdefault("grants", set()).add("computer")                 # one OK covers the whole turn
        ctx["computer_approved_at"] = time.time()                       # the computer tool waits a moment (hands off the mouse)
    print(f"[approve] {name}: {'approved' if ok else 'refused (' + why + ')'}")
    return ok, ("approved" if ok else why)


def answer(rid, ok, how="dashboard"):
    """Your answer to one request. False when there is no such open request."""
    with _lock:
        req = _pending.get(rid)
        if not req or req["answer"] is not None:
            return False
        req["answer"] = (bool(ok), f"you said no ({how})")
    req["event"].set()
    return True


def answer_text(text):
    """A Signal message that answers an open request ("yes", "no", "yes a1b2c3"). Returns a reply, or None if it is not one."""
    m = YES.match(text or "") or NO.match(text or "")
    if not m:
        return None
    with _lock:
        open_ = sorted((r for r in _pending.values() if r["answer"] is None), key=lambda r: r["at"])
    if not open_:
        return None
    rid = m.group(2)
    req = next((r for r in open_ if r["id"] == rid), None) if rid else open_[-1]
    if req is None:
        return "No open request with that id."
    ok = bool(YES.match(text))
    answer(req["id"], ok, "Signal")
    return ("OK, running " if ok else "OK, not running ") + req["tool"] + "."


def open_requests():
    now = time.time()
    with _lock:
        return [{"id": r["id"], "tool": r["tool"], "args": r["args"], "source": r["source"],
                 "left": max(0, int(r["at"] + r["timeout"] - now))} for r in _pending.values() if r["answer"] is None]


# ── the log ──
def record(name, args, out, how, secs, source=None):
    if source is None:
        ctx = current.get()
        source = ctx.get("source", "web") if ctx else "task"
    entry = {"ts": round(time.time(), 1), "source": source, "tool": name, "args": summary(name, args),
             "result": " ".join(str(out).split())[:300], "decision": how, "secs": round(secs, 2)}
    try:
        p = log_path()
        with _log_lock:
            p.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            if p.stat().st_size > 1_500_000:            # keep the newest MAX_LOG lines
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()[-MAX_LOG:]
                model_config.atomic_write(p, "\n".join(lines) + "\n")
    except Exception as e:
        print("[toollog] could not write:", e)


def recent(limit=100):
    try:
        lines = log_path().read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return []
    out = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
        if len(out) >= limit:
            break
    return out


def run(name, fn, args, call, cancel=None):
    """agent.py runs every tool through this: approval if needed, then the tool, then a log line."""
    t0 = time.monotonic()
    ok, how = check(name, args, cancel)
    if not ok:
        out = f"Not run: the user did not approve it ({how}). Do not try again unless they ask."
        record(name, args, out, "refused: " + how, time.monotonic() - t0)
        return out
    out = call(fn, args)
    record(name, args, out, how, time.monotonic() - t0)
    return out
