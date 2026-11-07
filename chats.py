"""Persistent chat history: one JSON file per chat in ./chats/ (override with DAEMON_CHATS).

A chat is {id, title, created, updated, run, seed, log}:
  log   one entry per exchange: {user, reply, thinking, tools, error}
  seed  extra context messages placed before the log (used when a task result is opened as a chat)
  run   the task result the chat was started from, if any (for display only)
Audio is never stored. Scheduled tasks do not use this module.
"""
import json
import os
import re
import secrets
import time
from pathlib import Path

import model_config

CHAT_DIR = Path(os.environ.get("DAEMON_CHATS") or Path(__file__).with_name("chats"))
_ID = re.compile(r"^[\w-]{1,64}$")
MAX_TURNS = 500          # a single chat keeps at most this many exchanges on disk
MAX_TOOL_OUT = 1500


def _path(chat_id):
    if not _ID.match(chat_id or ""):
        raise KeyError(chat_id)
    return CHAT_DIR / f"{chat_id}.json"


def new(title="", seed=None, run=None):
    now = int(time.time())
    return {
        "id": time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2),
        "title": title.strip()[:80],
        "created": now, "updated": now,
        "run": run, "seed": list(seed or []), "log": [],
    }


def save(chat):
    chat["updated"] = int(time.time())
    chat["log"] = chat["log"][-MAX_TURNS:]
    model_config.atomic_write(_path(chat["id"]), json.dumps(chat, ensure_ascii=False))


def load(chat_id):
    p = _path(chat_id)
    try:
        chat = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise KeyError(chat_id)
    except ValueError as e:
        raise KeyError(f"{chat_id}: unreadable ({e})")
    chat.setdefault("seed", [])
    chat.setdefault("log", [])
    chat.setdefault("run", None)
    chat.setdefault("title", "")
    return chat


def delete(chat_id):
    try:
        _path(chat_id).unlink()
    except FileNotFoundError:
        raise KeyError(chat_id)


def rename(chat_id, title):
    chat = load(chat_id)
    chat["title"] = title.strip()[:80] or chat["title"]
    save(chat)
    return chat


def listing(limit=100):
    """Newest first. Reads only the newest `limit` files."""
    if not CHAT_DIR.exists():
        return []
    files = sorted(CHAT_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime_ns, reverse=True)[:limit]
    out = []
    for p in files:
        try:
            c = load(p.stem)
        except KeyError:
            continue
        out.append({"id": c["id"], "title": c["title"] or "Untitled", "updated": c["updated"],
                    "turns": len(c["log"]), "task": bool(c.get("run"))})
    return sorted(out, key=lambda c: c["updated"], reverse=True)


def latest():
    items = listing(1)
    return load(items[0]["id"]) if items else None


def make_title(text):
    t = " ".join(str(text).split())
    return t if len(t) <= 48 else t[:47].rstrip() + "…"


def add_turn(chat, user, reply, thinking, used, error=False, files=None, out_files=None):
    chat["log"].append({
        "user": user, "reply": reply, "thinking": thinking, "error": bool(error),
        "tools": [{"name": t["name"], "args": t["args"], "output": str(t["output"])[:MAX_TOOL_OUT]} for t in used],
    })
    if files:
        chat["log"][-1]["files"] = list(files)
    if out_files:
        chat["log"][-1]["out_files"] = list(out_files)
    if not chat["title"]:
        chat["title"] = make_title(user)


def context_messages(chat):
    """Model context rebuilt from a stored chat (without the system message)."""
    msgs = list(chat["seed"])
    for t in chat["log"]:
        if t.get("error") or not t.get("user"):
            continue
        note = "".join(f"\n[Attached earlier: {f['name']}]" for f in t.get("files") or [])
        msgs.append({"role": "user", "content": t["user"] + note})
        if t.get("reply"):
            sent = "".join(f"\n[You sent the user the file: {f['name']}]" for f in t.get("out_files") or [])
            msgs.append({"role": "assistant", "content": t["reply"] + sent})
    return msgs


def _snippet(text, pos, n):
    a, b = max(0, pos - 40), min(len(text), pos + n + 60)
    return ("…" if a else "") + " ".join(text[a:b].split()) + ("…" if b < len(text) else "")


def search(query, limit=50, scan=1000):
    """Chats whose title or messages contain `query` (case-insensitive), newest first."""
    q = " ".join(str(query).lower().split())
    if not q or not CHAT_DIR.exists():
        return []
    files = sorted(CHAT_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime_ns, reverse=True)[:scan]
    out = []
    for p in files:
        try:
            c = load(p.stem)
        except KeyError:
            continue
        snippet, hits = "", 0
        if q in c["title"].lower():
            hits += 1
        for t in c["log"]:
            for text in (t.get("user") or "", t.get("reply") or ""):
                i = text.lower().find(q)
                if i >= 0:
                    hits += 1
                    if not snippet:
                        snippet = _snippet(text, i, len(q))
        if hits:
            out.append({"id": c["id"], "title": c["title"] or "Untitled", "updated": c["updated"],
                        "turns": len(c["log"]), "task": bool(c.get("run")), "snippet": snippet, "hits": hits})
            if len(out) >= limit:
                break
    return sorted(out, key=lambda c: c["updated"], reverse=True)
