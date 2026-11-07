"""Inbox: a searchable archive of things you throw at Daemon (notes, links, photos, files).

Fill it from Signal with `/inbox <text>` (attach a photo or file to the same message to keep it too), from the dashboard
(Inbox section in the settings drawer), or by asking the model ("save this link to my inbox"). Ask later:
"what was that article about X?" (inbox_search) or send `/find X` on Signal.

Stored in inbox.json next to the server (override: DAEMON_INBOX). Files themselves live in the uploads folder (uploads.py).
Links get a short excerpt of the page fetched in the background (only public addresses).
"""
import json
import os
import re
import secrets
import threading
import time
import unicodedata
from pathlib import Path


PATH = Path(os.environ.get("DAEMON_INBOX") or Path(__file__).with_name("inbox.json"))
MAX_ITEMS = 3000
MAX_TEXT = 4000
_lock = threading.RLock()
_URL = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
_TAG = re.compile(r"(?<![\w#])#([\w-]{2,30})", re.U)


def _read():
    try:
        d = json.loads(PATH.read_text(encoding="utf-8"))
        return [x for x in d if isinstance(x, dict) and x.get("id")]
    except (FileNotFoundError, ValueError):
        return []


def _write(items):
    import model_config
    model_config.atomic_write(PATH, json.dumps(items, ensure_ascii=False, indent=1))


def norm(s):
    """Lowercase without accents (also Turkish ı/İ/ş/ğ...) so that 'sarki' finds 'şarkı'."""
    s = str(s or "").replace("İ", "i").replace("ı", "i").lower()
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def _words(s):
    return [w for w in re.split(r"[^0-9a-z]+", norm(s)) if len(w) > 1 or w.isdigit()]


def _stem(w):
    return w[:5] if len(w) > 5 else w            # crude prefix match: "makaleyi" ~ "makale"


def add(text="", recs=None, tags=None, src=""):
    """Saves one item. `recs` are the records made by uploads.process(). Returns the item."""
    import uploads
    text = " ".join(str(text or "").split()) if "\n" not in str(text or "") else str(text).strip()
    text = text[:MAX_TEXT]
    files = [uploads.public(r) for r in recs or []]
    if not text and not files:
        raise ValueError("nothing to save")
    urls = _URL.findall(text)
    found = _TAG.findall(text)
    tag_list = list(dict.fromkeys([norm(t).strip("#, ") for t in list(tags or []) + found]))[:8]
    tag_list = [t for t in tag_list if t]
    excerpt = " ".join(" ".join(r.get("text") or "" for r in recs or []).split())[:2000]
    kind = "photo" if files and all(f["kind"] == "image" for f in files) else "file" if files else \
        "link" if urls and len(text) < len(urls[0]) + 200 else "note"
    item = {"id": secrets.token_hex(3), "ts": int(time.time()), "kind": kind, "text": text, "tags": tag_list,
            "files": files, "excerpt": excerpt, "src": src}
    if urls:
        item["url"] = urls[0]
    with _lock:
        items = _read()
        items.append(item)
        if len(items) > MAX_ITEMS:
            items = items[-MAX_ITEMS:]
        _write(items)
    if urls:
        threading.Thread(target=_enrich, args=(item["id"], urls[0]), daemon=True, name="inbox-enrich").start()
    return item


def _enrich(item_id, url):
    """Fetches the page once and keeps a title and a short excerpt, so the link can be found by what it says."""
    try:
        import tools
        out = tools.fetch_url(url)
        if not isinstance(out, str) or out.startswith("Error"):
            return
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        title = lines[0][:140] if lines else ""
        excerpt = " ".join(" ".join(lines[1:]).split())[:1500]
    except Exception:
        return
    with _lock:
        items = _read()
        for x in items:
            if x["id"] == item_id:
                x["title"], x["excerpt"] = title, excerpt or x.get("excerpt", "")
                _write(items)
                return


def items(limit=None, tag="", kind=""):
    """Newest first."""
    with _lock:
        out = _read()
    t = norm(tag).strip("#")
    if t:
        out = [x for x in out if t in x.get("tags", [])]
    if kind:
        out = [x for x in out if x.get("kind") == kind]
    out.sort(key=lambda x: x["ts"], reverse=True)
    return out[:limit] if limit else out


def get(item_id):
    with _lock:
        return next((x for x in _read() if x["id"] == item_id), None)


def delete(item_id):
    with _lock:
        items = _read()
        keep = [x for x in items if x["id"] != item_id]
        if len(keep) == len(items):
            return False
        _write(keep)
        return True


def clear():
    with _lock:
        _write([])


def search(query, limit=8):
    """Items matching the words of `query`, best first. Every word has to match somewhere (prefix match)."""
    q = [_stem(w) for w in _words(query)]
    if not q:
        return items(limit)
    hits = []
    with _lock:
        pool = _read()
    for x in pool:
        fields = [(3, x.get("title", "")), (3, x.get("text", "")), (3, " ".join(x.get("tags", []))),
                  (3, " ".join(f.get("name", "") for f in x.get("files", []))), (1, x.get("excerpt", "")), (1, x.get("url", ""))]
        toks = [(w, _words(t)) for w, t in fields]
        score = 0
        for qw in q:
            best = max((w for w, ws in toks if any(t.startswith(qw) for t in ws)), default=0)
            if not best:
                score = 0
                break
            score += best
        if score:
            hits.append((score, x["ts"], x))
    hits.sort(key=lambda h: (h[0], h[1]), reverse=True)
    return [h[2] for h in hits[:limit]]


def public(x):
    """What the dashboard and the model see (no server paths)."""
    return {k: x.get(k) for k in ("id", "ts", "kind", "text", "title", "url", "tags", "files", "excerpt", "src") if x.get(k) not in (None, "")}


def line(x, long=False):
    when = time.strftime("%Y-%m-%d", time.localtime(x["ts"]))
    bits = [f"[{x['id']}] {when} {x['kind']}"]
    if x.get("title"):
        bits.append(x["title"])
    if x.get("text"):
        bits.append(x["text"][:300 if long else 140])
    if x.get("files"):
        bits.append("files: " + ", ".join(f["name"] for f in x["files"]))
    if x.get("tags"):
        bits.append(" ".join("#" + t for t in x["tags"]))
    s = " · ".join(bits)
    if long and x.get("excerpt"):
        s += "\n    " + x["excerpt"][:300]
    return s


# ---- tools the model can call ----
def tool_add(text: str, tags: str = "") -> str:
    """Save a note, idea or link to the user's inbox archive so it can be found later

    Args:
        text: What to save (the note, or the link with a few words about it)
        tags: Optional tags separated by spaces or commas, e.g. "robot ideas"
    """
    try:
        x = add(text, tags=[t for t in re.split(r"[\s,#]+", tags or "") if t], src="model")
    except ValueError as e:
        return f"Not saved: {e}"
    return f"Saved to the inbox ({x['id']})."


def tool_search(query: str) -> str:
    """Search the user's inbox archive (saved notes, links, photos and files) by words

    Args:
        query: A few words about what to find, e.g. "article about batteries"
    """
    r = search(query, 6)
    return "\n".join(line(x, True) for x in r) if r else "Nothing in the inbox matches that."


def tool_recent(count: int = 8) -> str:
    """List the newest items in the user's inbox archive

    Args:
        count: How many items (1-20)
    """
    try:
        n = max(1, min(20, int(count)))
    except (TypeError, ValueError):
        n = 8
    r = items(n)
    return "\n".join(line(x) for x in r) if r else "The inbox is empty."


def tool_delete(id: str) -> str:
    """Delete one item from the user's inbox archive

    Args:
        id: The item id shown in brackets, e.g. a1b2c3
    """
    return "Deleted." if delete(str(id).strip().strip("[]")) else "No inbox item with that id."
