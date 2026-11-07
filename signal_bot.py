"""Two-way chat over Signal, through signal-cli in JSON-RPC mode.

Daemon starts `signal-cli -a ACCOUNT jsonRpc` itself and keeps it running, no extra service.
Messages from you go to the active chat (the same one the dashboard shows), the reply comes
back on Signal. Task results and reminders are sent to you here too.

config.yaml:
  signal:
    enabled: true
    account: "+15551234567"        the number signal-cli is registered with (the bot)
    allowed: "+905551112233"       who may talk to Daemon: your number (or Signal UUID), comma separated
    cli: signal-cli                path of the program
    max_age: 600                   seconds; older messages (sent while Daemon was off) are ignored
    data_dir: ""                   where signal-cli keeps its files (attachments are read from <data_dir>/attachments).
                                   Empty = ~/.local/share/signal-cli

Voice messages you send are turned into text with the same speech-to-text as the dashboard (uses PyAV, which faster-whisper already installs) and answered
like a typed message.

Only the senders in `allowed` are answered, everyone else is ignored silently.
Messages you send can use every tool the chat can, so keep that list short.
"""
import base64
import collections
import os
import json
import queue
import re
import shutil
import subprocess
import threading
import time

import model_config

MAX_SEND = 50 * 1048576       # biggest file sent to you
CHUNK = 1800                 # Signal accepts long texts, but short pieces read better
NOTICE_TTL = 3 * 3600        # a reply within this time after a task message refers to that message


def _plus(v):
    s = re.sub(r"[\s\-()]", "", str(v or ""))
    return s if not s or s.startswith("+") else "+" + s


def _norm(v):
    """Phone numbers get a leading +, anything else (a Signal UUID) is lower-cased."""
    s = str(v or "").strip()
    if re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", s):
        return s.lower()
    if re.fullmatch(r"\+?[\d\s\-()]{6,}", s):
        return _plus(s)
    return s.lower()


def _cfg():
    s = model_config.signal_cfg
    allowed = [_norm(x) for x in re.split(r"[,;\s]+", str(s.get("allowed") or "")) if x]
    try:
        max_age = int(s.get("max_age"))
    except (TypeError, ValueError):
        max_age = 600
    return {
        "enabled": bool(s.get("enabled")),
        "data_dir": str(s.get("data_dir") or "").strip(),
        "account": _plus(s.get("account")),
        "cli": str(s.get("cli") or "signal-cli").strip(),
        "allowed": allowed,
        "max_age": max(30, max_age),
    }


def plain(text):
    """Signal shows markdown characters as they are; remove the common ones."""
    t = str(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t, flags=re.S)
    t = re.sub(r"^#{1,6}\s*", "", t, flags=re.M)
    return t.strip()


def chunks(text, size=CHUNK):
    out, cur = [], ""
    for para in str(text).split("\n"):
        while len(para) > size:
            cut = para.rfind(" ", 0, size)
            cut = cut if cut > size // 2 else size
            if cur:
                out.append(cur)
                cur = ""
            out.append(para[:cut])
            para = para[cut:].lstrip()
        if len(cur) + len(para) + 1 > size and cur:
            out.append(cur)
            cur = ""
        cur = f"{cur}\n{para}" if cur else para
    if cur.strip():
        out.append(cur)
    return [c for c in out if c.strip()]


class SignalBot:
    def __init__(self):
        self.handler = None                 # set by server.py: fn(text, notice) -> reply text
        self.audio_handler = None           # set by server.py: fn(audio bytes) -> text (voice messages)
        self.quick = None                   # set by server.py: fn(text) -> reply or None; answered at once, even while a
                                            # turn is running (e.g. "yes" to a tool that waits for your approval)
        self.error = ""
        self.last_ignored = ""
        self.last_in = 0.0
        self.notice = None                  # (time, text) of the last message Daemon sent on its own
        self._proc = None
        self._sig = None
        self._started = 0.0
        self._retry_at = 0.0
        self._backoff = 3
        self._uuids = set()
        self._pending = {}
        self._seq = 0
        self._lock = threading.RLock()      # starting and stopping the process
        self._wlock = threading.Lock()      # writes to its stdin
        self._inbox = queue.Queue()
        self._stderr = collections.deque(maxlen=15)
        self._stop = threading.Event()
        self._threads = []

    # ── lifecycle ──
    def start(self):
        if self._threads:
            return
        self._stop.clear()
        for fn, name in ((self._supervise, "signal-super"), (self._work, "signal-work")):
            t = threading.Thread(target=fn, daemon=True, name=name)
            t.start()
            self._threads.append(t)

    def stop(self):
        self._stop.set()
        with self._lock:
            self._kill()
        self._inbox.put(None)
        self._threads = []

    def _alive(self):
        p = self._proc
        return p is not None and p.poll() is None

    def running(self):
        return self._alive()

    def enabled(self):
        """True when the settings are complete, whether or not signal-cli is up right now."""
        c = _cfg()
        return bool(c["enabled"] and c["account"] and c["allowed"])

    def ready(self):
        """True when messages can be sent right now."""
        c = _cfg()
        return bool(c["enabled"] and c["account"] and c["allowed"] and self._alive())

    def status(self):
        c = _cfg()
        return {
            "enabled": c["enabled"], "running": self._alive(), "account": c["account"],
            "allowed": len(c["allowed"]), "error": self.error,
            "last_ignored": self.last_ignored, "last_message": self.last_in,
        }

    def _kill(self):
        p, self._proc = self._proc, None
        self._sig = None
        if p is None:
            return
        try:
            p.stdin.close()
        except Exception:
            pass
        try:
            p.terminate()
            p.wait(timeout=5)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
        self._fail_pending("signal-cli stopped")

    def _supervise(self):
        while not self._stop.wait(2):
            try:
                model_config.reload_if_changed()
                self._tick()
            except Exception as e:
                self.error = f"{type(e).__name__}: {e}"

    def _tick(self):
        c = _cfg()
        want = c["enabled"] and c["account"] and c["allowed"]
        sig = (c["account"], c["cli"], tuple(c["allowed"]))
        with self._lock:
            if not want:
                if self._proc is not None:
                    self._kill()
                self.error = "" if not c["enabled"] else "set signal.account and signal.allowed in config.yaml"
                return
            if self._alive():
                if sig != self._sig:            # settings were edited: restart with the new ones
                    self._kill()
                else:
                    return
            elif self._proc is not None:        # it died
                tail = self._stderr[-1] if self._stderr else ""
                self.error = f"signal-cli exited ({self._proc.returncode}){': ' + tail if tail else ''}"
                if time.monotonic() - self._started > 60:
                    self._backoff = 3
                self._proc = None
                self._retry_at = time.monotonic() + self._backoff
                self._backoff = min(self._backoff * 2, 120)
                print("[signal]", self.error)
                return
            if time.monotonic() < self._retry_at:
                return
            if not self._spawn(c):
                self._retry_at = time.monotonic() + self._backoff
                self._backoff = min(self._backoff * 2, 120)
                return
            self._sig = sig

    def _spawn(self, c):
        if not shutil.which(c["cli"]):
            self.error = f"{c['cli']} is not installed (Arch: signal-cli)"
            return False
        try:
            p = subprocess.Popen(
                [c["cli"], "-a", c["account"], "jsonRpc"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
            )
        except Exception as e:
            self.error = f"could not start {c['cli']}: {e}"
            return False
        self._proc, self._started, self.error = p, time.monotonic(), ""
        self._stderr.clear()
        threading.Thread(target=self._read, args=(p,), daemon=True, name="signal-read").start()
        threading.Thread(target=self._drain, args=(p,), daemon=True, name="signal-err").start()
        threading.Thread(target=self._resolve, args=(c["allowed"],), daemon=True, name="signal-ids").start()
        print(f"[signal] started for {c['account']}")
        return True

    # ── talking to signal-cli ──
    def _read(self, p):
        for line in p.stdout:
            self._on_line(line)
        self._fail_pending("signal-cli closed")

    def _drain(self, p):
        for line in p.stderr:
            line = line.strip()
            if line:
                self._stderr.append(line[:200])

    def _on_line(self, line):
        try:
            msg = json.loads(line)
        except ValueError:
            return
        if not isinstance(msg, dict):
            return
        if msg.get("id") is not None and ("result" in msg or "error" in msg):
            slot = self._pending.pop(str(msg["id"]), None)
            if slot:
                slot["msg"] = msg
                slot["ev"].set()
        elif msg.get("method") == "receive":
            params = msg.get("params") or {}
            env = params.get("envelope", params)
            if isinstance(env, dict) and not self._quick(env):
                self._inbox.put(env)

    def _quick(self, env):
        """Handles a message right away, without waiting in line behind a running turn. True when it was handled."""
        dm = env.get("dataMessage")
        if self.quick is None or not isinstance(dm, dict) or dm.get("groupInfo") or not self._allowed(env):
            return False
        text = str(dm.get("message") or "").strip()
        try:
            reply = self.quick(text) if text else None
        except Exception as e:
            print("[signal] quick answer failed:", e)
            return False
        if reply is None:
            return False
        who = env.get("sourceNumber") or env.get("source") or env.get("sourceUuid")
        threading.Thread(target=self.send, args=(reply,), kwargs={"to": who}, daemon=True).start()
        return True

    def _allowed(self, env):
        ids = {_norm(env.get(k)) for k in ("sourceNumber", "source", "sourceUuid") if env.get(k)}
        return bool(ids & (set(_cfg()["allowed"]) | self._uuids))

    def _fail_pending(self, why):
        for slot in list(self._pending.values()):
            slot["msg"] = {"error": {"message": why}}
            slot["ev"].set()
        self._pending.clear()

    def _call(self, method, params, timeout=30):
        p = self._proc
        if p is None or p.poll() is not None:
            raise RuntimeError("signal-cli is not running" + (f" ({self.error})" if self.error else ""))
        with self._wlock:
            self._seq += 1
            rid = f"d{self._seq}"
            slot = {"ev": threading.Event(), "msg": None}
            self._pending[rid] = slot
            p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": rid}) + "\n")
            p.stdin.flush()
        if not slot["ev"].wait(timeout):
            self._pending.pop(rid, None)
            raise TimeoutError(f"{method} timed out")
        msg = slot["msg"] or {}
        if "error" in msg:
            raise RuntimeError(str((msg["error"] or {}).get("message") or msg["error"])[:200])
        return msg.get("result")

    def _resolve(self, allowed):
        """Looks up the Signal UUID of the allowed numbers: senders who hide their number only show a UUID."""
        nums = [a for a in allowed if a.startswith("+")]
        if not nums:
            return
        try:
            res = self._call("getUserStatus", {"recipient": nums}, timeout=30)
        except Exception as e:
            print("[signal] could not look up ids:", e)
            return
        for item in res if isinstance(res, list) else []:
            if isinstance(item, dict) and item.get("uuid"):
                self._uuids.add(str(item["uuid"]).lower())

    # ── sending ──
    def _primary(self):
        allowed = _cfg()["allowed"]
        nums = [a for a in allowed if a.startswith("+")]
        return (nums or allowed or [""])[0]

    def send(self, text, to=None):
        """Sends `text` to `to`, or to you when omitted. Returns (ok, info)."""
        c = _cfg()
        if not c["enabled"]:
            return False, "signal is off (signal.enabled in config.yaml)"
        who = to or self._primary()
        if not who:
            return False, "set signal.allowed in config.yaml"
        if not self._alive():
            return False, "signal is not running" + (f": {self.error}" if self.error else "")
        text = plain(text)
        if not text:
            return False, "empty message"
        try:
            for part in chunks(text):
                res = self._call("send", {"recipient": [who], "message": part})
                bad = [r.get("type") for r in (res or {}).get("results", []) if isinstance(r, dict)
                       and r.get("type") not in (None, "SUCCESS")] if isinstance(res, dict) else []
                if bad:
                    hint = (f" (run: signal-cli -a {c['account']} trust -a {who})"
                            if "IDENTITY" in str(bad[0]) else "")
                    return False, f"{bad[0]}{hint}"
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"
        if to is None:
            self.notice = (time.time(), text)
        return True, "sent"

    def send_file(self, path, caption="", to=None):
        """Sends a file (with an optional caption) to `to`, or to you. Returns (ok, info)."""
        import shutil
        import tempfile
        c = _cfg()
        if not c["enabled"]:
            return False, "signal is off (signal.enabled in config.yaml)"
        who = to or self._primary()
        if not who:
            return False, "set signal.allowed in config.yaml"
        if not self._alive():
            return False, "signal is not running" + (f": {self.error}" if self.error else "")
        if not os.path.isfile(path):
            return False, "file not found"
        if os.path.getsize(path) > MAX_SEND:
            return False, f"file is larger than {MAX_SEND // 1048576} MB"
        tmp = tempfile.mkdtemp(prefix="daemon-send-")      # a clean file name for the receiver (saved uploads carry an id prefix)
        try:
            os.chmod(tmp, 0o700)
            name = os.path.basename(path)
            if re.match(r"^[0-9a-f]{8,}-", name):
                name = name.split("-", 1)[1]
            copy = os.path.join(tmp, name)
            shutil.copyfile(path, copy)
            res = self._call("send", {"recipient": [who], "message": plain(caption)[:CHUNK] if caption else "", "attachment": [copy]}, timeout=120)
            bad = [r.get("type") for r in (res or {}).get("results", []) if isinstance(r, dict)
                   and r.get("type") not in (None, "SUCCESS")] if isinstance(res, dict) else []
            if bad:
                return False, str(bad[0])
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return True, "sent"

    # ── receiving ──
    def _work(self):
        while not self._stop.is_set():
            env = self._inbox.get()
            if env is None:
                return
            try:
                self._handle(env)
            except Exception as e:
                print("[signal] message failed:", e)

    def _att_bytes(self, att):
        """Bytes of one attachment (signal-cli's file on disk, or fetched through the API), or None."""
        if not isinstance(att, dict):
            return None
        aid = str(att.get("id") or "")
        base = _cfg()["data_dir"] or os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "signal-cli")
        for cand in (att.get("file"), os.path.join(base, "attachments", aid)):
            if cand and aid and os.path.isfile(cand):
                with open(cand, "rb") as f:
                    return f.read()
        if aid:                                           # newer signal-cli can hand the file over itself
            try:
                res = self._call("getAttachment", {"id": aid}, timeout=30)
                if isinstance(res, dict) and res.get("data"):
                    return base64.b64decode(res["data"])
            except Exception as e:
                print("[signal] could not fetch an attachment:", e)
        return None

    @staticmethod
    def _is_audio(att):
        return isinstance(att, dict) and str(att.get("contentType") or "").lower().startswith("audio/")

    def _voice_bytes(self, dm):
        """Bytes of the first audio attachment of a message (a voice note), or None."""
        for att in dm.get("attachments") or []:
            if self._is_audio(att):
                return self._att_bytes(att)
        return None

    def _file_list(self, dm):
        """Photos and files sent with a message: [(name, bytes)] and a list of problems."""
        out, problems = [], []
        for i, att in enumerate(dm.get("attachments") or []):
            if not isinstance(att, dict) or self._is_audio(att):
                continue
            ctype = str(att.get("contentType") or "").lower()
            name = str(att.get("filename") or "").strip()
            if not name:
                ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif", "application/pdf": "pdf"}.get(ctype, "bin")
                name = f"signal-{i + 1}.{ext}"
            raw = self._att_bytes(att)
            if raw is None:
                problems.append(name)
            else:
                out.append((name, raw))
        return out, problems

    def _handle(self, env):
        dm = env.get("dataMessage")
        if not isinstance(dm, dict) or dm.get("groupInfo"):
            return
        text = str(dm.get("message") or "").strip()
        has_audio = any(isinstance(a, dict) and str(a.get("contentType") or "").lower().startswith("audio/")
                        for a in dm.get("attachments") or [])
        has_files = any(isinstance(a, dict) and not str(a.get("contentType") or "").lower().startswith("audio/")
                        for a in dm.get("attachments") or [])
        if not text and not has_audio and not has_files:
            return
        c = _cfg()
        if not self._allowed(env):
            ids = {_norm(env.get(k)) for k in ("sourceNumber", "source", "sourceUuid") if env.get(k)}
            self.last_ignored = " / ".join(sorted(ids)) or "unknown sender"
            print(f"[signal] ignored a message from {self.last_ignored} (not in signal.allowed)")
            return
        sent_at = (env.get("timestamp") or dm.get("timestamp") or 0) / 1000
        if sent_at and time.time() - sent_at > c["max_age"]:
            print(f"[signal] ignored an old message ({int(time.time() - sent_at)} s)")
            return
        who = env.get("sourceNumber") or env.get("source") or env.get("sourceUuid")
        self.last_in = time.time()
        files = []
        if has_files:
            files, missing = self._file_list(dm)
            if missing and not files and not text:
                self.send("I could not get the attachment from signal-cli (see signal.data_dir).", to=who)
                return
        if not text and not files:                        # a voice message: turn it into text first
            raw = self._voice_bytes(dm)
            try:
                text = (self.audio_handler(raw) or "").strip() if raw and self.audio_handler else ""
            except Exception as e:
                print("[signal] voice message failed:", e)
                self.send(f"Could not read the voice message: {e}", to=who)
                return
            if not text:
                self.send("I could not understand that voice message." if raw else
                          "I could not get the voice message from signal-cli (see signal.data_dir).", to=who)
                return
            print(f"[signal] voice message: {text[:80]}")
        notice = None
        if self.notice and time.time() - self.notice[0] < NOTICE_TTL:
            notice = " ".join(self.notice[1].split())[:240]
            self.notice = None
        if self.handler is None:
            return
        try:
            reply = self.handler(text, notice, files) if files else self.handler(text, notice)
        except Exception as e:
            reply = f"Error: {e}"
        reply = reply or "(no reply)"
        ok, info = self.send(reply, to=who)
        if not ok:
            print("[signal] could not reply:", info)


bot = SignalBot()
