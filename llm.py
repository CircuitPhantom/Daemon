"""The model: any OpenAI-compatible cloud API (Anthropic, Groq, NVIDIA, Cerebras, OpenRouter, Gemini ...).

Settings live in config.yaml (keep the file private, it holds the key):

  llm:
    base_url: https://api.groq.com/openai/v1  # Anthropic: https://api.anthropic.com/v1  NVIDIA: https://integrate.api.nvidia.com/v1
    api_key: "gsk_..."
    model: llama-3.3-70b-versatile
    timeout: 60                               # seconds to wait for the cloud

`client` in conversation.py is a Client: agent.py calls chat() on it. There is no local model: when the cloud fails, the error
is shown (and a key or quota problem is also sent to you on Signal once).
"""
import inspect
import json
import re
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

import model_config

_lock = threading.RLock()
_s = {"notified": False, "last_ok": 0.0, "last_error": "", "last_error_at": 0.0}


class AttrDict(dict):
    """A dict that also reads like a response object (res.message.content)."""
    def __getattr__(self, k):
        try:
            v = self[k]
        except KeyError:
            raise AttributeError(k) from None
        return v


class LLMError(Exception):
    def __init__(self, status, code, message, retry_after=0):
        super().__init__(f"{status} {code}: {message}")
        self.status, self.code, self.message, self.retry_after = status, code, message, retry_after


def _cfg():
    return model_config.llm


# ───────────────────────── tools as JSON schema ─────────────────────────
_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object"}


def _doc(fn):
    doc = inspect.getdoc(fn) or ""
    head, _, rest = doc.partition("Args:")
    args, cur = {}, None
    for line in rest.split("Returns:")[0].splitlines():
        m = re.match(r"^\s*(\w+)\s*:\s*(.*)$", line)
        if m and (cur is None or len(line) - len(line.lstrip()) <= 6):
            cur = m[1]
            args[cur] = m[2].strip()
        elif cur and line.strip():
            args[cur] += " " + line.strip()
    return " ".join(head.split()), args


def _short(t, n):
    t = " ".join(t.split())
    if len(t) <= n:
        return t
    cut = t.rfind(" ", 0, n)
    return t[: cut if cut > n // 2 else n].rstrip(" ,;:.") + "…"


def tool_schema(fn, compact=True):
    """OpenAI-style tool definition from a python function (type hints + the "Args:" part of its docstring)."""
    desc, args = _doc(fn)
    props, required = {}, []
    for name, p in inspect.signature(fn).parameters.items():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        t = _TYPES.get(p.annotation, "string")
        d = {"type": t}
        if t == "array":
            d["items"] = {"type": "string"}
        if args.get(name):
            d["description"] = _short(args[name], 90 if compact else 400)
        props[name] = d
        if p.default is inspect.Parameter.empty:
            required.append(name)
    return {"type": "function", "function": {
        "name": fn.__name__, "description": _short(desc, 160 if compact else 800),
        "parameters": {"type": "object", "properties": props, "required": required}}}


# ───────────────────────── messages ─────────────────────────
def _get(o, k, d=None):
    return o.get(k, d) if isinstance(o, dict) else getattr(o, k, d)


SKIP_SIG = {"google": {"thought_signature": "skip_thought_signature_validator"}}


def _is_google():
    return "googleapis" in _cfg()["base_url"]


def to_openai_messages(messages, google=False):
    """Daemon's history (tool calls as objects, tool results with tool_name) -> OpenAI messages with call ids."""
    out, pending, n = [], [], 0

    def unanswered():                                       # a call without a result (stopped reply, trimmed history)
        for cid, _ in pending:
            out.append({"role": "tool", "tool_call_id": cid, "content": "Not run."})
        pending.clear()

    for m in messages:
        role, content = _get(m, "role"), _get(m, "content") or ""
        if role != "tool":
            unanswered()
        if role == "assistant":
            item = {"role": "assistant", "content": content}
            calls = []
            for tc in _get(m, "tool_calls") or []:
                fn = _get(tc, "function")
                name, args = _get(fn, "name"), _get(fn, "arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args or "{}")
                    except ValueError:
                        args = {}
                n += 1
                pending.append((f"call_{n}", name))
                call = {"id": f"call_{n}", "type": "function",
                        "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}
                extra = _get(tc, "extra_content")            # Gemini: its "thought signature" must be sent back with the call
                if extra:
                    call["extra_content"] = extra
                elif google:                                 # a call made by another model: Gemini accepts this placeholder
                    call["extra_content"] = SKIP_SIG
                calls.append(call)
            if calls:
                item["tool_calls"] = calls
            out.append(item)
        elif role == "tool":
            name = _get(m, "tool_name")
            i = next((i for i, (_, nm) in enumerate(pending) if nm == name or not name), None)
            if i is None:                                   # a result without its call (history was trimmed)
                out.append({"role": "user", "content": "Tool result: " + content})
            else:
                out.append({"role": "tool", "tool_call_id": pending.pop(i)[0], "content": content})
        else:
            imgs = _get(m, "images") if role == "user" else None
            if imgs:
                parts = [{"type": "text", "text": content or "(photo)"}]
                for b in imgs:
                    b = b.decode() if isinstance(b, (bytes, bytearray)) else str(b)
                    parts.append({"type": "image_url", "image_url": {"url": f"data:{_b64_mime(b)};base64,{b}"}})
                out.append({"role": role, "content": parts})
            else:
                out.append({"role": role, "content": content})
    unanswered()
    return out


def _b64_mime(b64):
    return ("image/png" if b64.startswith("iVBOR") else "image/gif" if b64.startswith("R0lGO") else
            "image/webp" if b64.startswith("UklGR") else "image/jpeg")


def without_images(messages):
    """The same history for a model that cannot look at pictures."""
    out = []
    for m in messages:
        if isinstance(m, dict) and m.get("images"):
            m = {k: v for k, v in m.items() if k != "images"}
            m["content"] = (m.get("content") or "") + "\n[The photo itself cannot be shown to this model.]"
        out.append(m)
    return out


class ThinkSplit:
    """Splits <think>...</think> out of streamed text (some models write their reasoning inline)."""
    def __init__(self):
        self.inside, self.buf = False, ""

    def feed(self, text):
        self.buf += text
        content = thinking = ""
        while self.buf:
            tag = "</think>" if self.inside else "<think>"
            i = self.buf.find(tag)
            if i >= 0:
                piece, self.buf = self.buf[:i], self.buf[i + len(tag):]
                if self.inside:
                    thinking += piece
                else:
                    content += piece
                self.inside = not self.inside
                continue
            keep = next((k for k in range(min(len(tag) - 1, len(self.buf)), 0, -1) if tag.startswith(self.buf[-k:])), 0)
            piece, self.buf = self.buf[: len(self.buf) - keep], self.buf[len(self.buf) - keep:]
            if self.inside:
                thinking += piece
            else:
                content += piece
            break
        return content, thinking

    def flush(self):
        t, self.buf = self.buf, ""
        return ("", t) if self.inside else (t, "")


def _msg(content="", thinking="", tool_calls=None):
    return AttrDict(message=AttrDict(role="assistant", content=content, thinking=thinking, tool_calls=tool_calls))


def _calls(raw):
    out = []
    for c in raw or []:
        fn = c.get("function") or {}
        args = fn.get("arguments") or "{}"
        try:
            args = json.loads(args) if isinstance(args, str) else args
        except ValueError:
            args = {}
        item = AttrDict(function=AttrDict(name=fn.get("name") or "", arguments=args if isinstance(args, dict) else {}))
        if c.get("extra_content"):
            item["extra_content"] = c["extra_content"]
        out.append(item)
    return out


# ───────────────────────── the cloud client ─────────────────────────
class OpenAIClient:
    def _request(self, path, body=None, stream=False):
        c = _cfg()
        req = urllib.request.Request(
            c["base_url"].rstrip("/") + path, data=json.dumps(body).encode() if body is not None else None,
            method="POST" if body is not None else "GET",
            headers={"Authorization": "Bearer " + c["api_key"], "Content-Type": "application/json",
                     "Accept": "text/event-stream" if stream else "application/json", "User-Agent": "daemon/1.0"})
        try:
            return urllib.request.urlopen(req, timeout=c["timeout"])
        except urllib.error.HTTPError as e:
            raw = e.read(4000).decode("utf-8", "replace")
            code, msg = "", raw[:200]
            try:
                j = json.loads(raw)
                j = j[0] if isinstance(j, list) and j else j
                err = j.get("error") if isinstance(j, dict) else None
                if isinstance(err, dict):
                    code, msg = str(err.get("status") or err.get("code") or err.get("type") or ""), str(err.get("message") or "")[:300]
                elif isinstance(err, str):
                    msg = err[:300]
            except Exception:
                pass
            try:
                ra = float(e.headers.get("retry-after") or 0)
            except (TypeError, ValueError):
                ra = 0
            raise LLMError(e.code, code, msg, ra) from None

    def chat(self, model, messages, tools=None, stream=False, **_ignored):
        c = _cfg()
        body = {"model": c["model"], "messages": to_openai_messages(messages, _is_google()), "stream": bool(stream)}
        if tools:
            body["tools"] = [tool_schema(f) for f in tools]
        for attempt in (1, 2):
            try:
                resp = self._request("/chat/completions", body, stream)
                break
            except LLMError as e:
                if e.code == "tool_use_failed" and attempt == 1:       # the model wrote a broken tool call: ask again once
                    continue
                raise
        return self._stream(resp, _ignored.get("think")) if stream else self._whole(resp, _ignored.get("think"))

    def _whole(self, resp, think):
        with resp:
            d = json.loads(resp.read())
        m = d["choices"][0]["message"]
        content, thinking = ThinkSplit().feed(m.get("content") or "")
        reasoning = m.get("reasoning") or m.get("reasoning_content") or ""
        return _msg(content.strip() if not _calls(m.get("tool_calls")) else content, thinking or (reasoning if think else ""),
                    _calls(m.get("tool_calls")) or None)

    def _stream(self, resp, think):
        split, acc = ThinkSplit(), {}
        try:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    ch = json.loads(data)
                except ValueError:
                    continue
                if ch.get("error"):
                    raise LLMError(500, "stream", str(ch["error"])[:200])
                delta = (ch.get("choices") or [{}])[0].get("delta") or {}
                reasoning = delta.get("reasoning") or delta.get("reasoning_content") or ""
                content, thinking = split.feed(delta.get("content") or "")
                thinking += reasoning if think else ""
                if content or thinking:
                    yield _msg(content, thinking)
                for tc in delta.get("tool_calls") or []:
                    a = acc.setdefault(tc.get("index", 0), {"function": {"name": "", "arguments": ""}})
                    f = tc.get("function") or {}
                    a["function"]["name"] += f.get("name") or ""
                    a["function"]["arguments"] += f.get("arguments") or ""
                    if tc.get("extra_content"):
                        a["extra_content"] = tc["extra_content"]
            content, thinking = split.flush()
            if content or thinking:
                yield _msg(content, thinking)
            if acc:
                yield _msg(tool_calls=_calls([acc[i] for i in sorted(acc)]))
        finally:
            resp.close()

    def list(self):
        d = json.loads(self._request("/models").read())
        return AttrDict(models=[AttrDict(model=m["id"]) for m in d.get("data", [])])


CLOUD = OpenAIClient()


# ───────────────────────── the client the rest of Daemon uses ─────────────────────────
def name():
    host = urlparse(_cfg()["base_url"]).hostname or "cloud"
    for key, label in (("anthropic", "Anthropic"), ("groq", "Groq"), ("nvidia", "NVIDIA"), ("cerebras", "Cerebras"),
                       ("openrouter", "OpenRouter"), ("mistral", "Mistral"), ("google", "Gemini")):
        if key in host:
            return label
    return host


def configured():
    c = _cfg()
    return bool(c["api_key"] and c["base_url"] and c["model"])


def _notify(text):
    def go():
        try:
            import scheduler
            scheduler.send_message(text)
        except Exception as e:
            print("[llm] could not send the notice:", e)
    threading.Thread(target=go, daemon=True).start()


def _failed(e):
    """Remembers the last error (shown in the dashboard). A refused key or a used-up quota is also sent to you once."""
    kind = "network"
    if isinstance(e, LLMError):
        text = (e.code + " " + e.message).lower()
        if e.status == 413 or "too large" in text:
            kind, reason = "request", "request too large for the limit: " + e.message[:120]
        elif e.code == "tool_use_failed":
            kind, reason = "request", "the model wrote a broken tool call"
        elif e.status in (401, 403):
            kind, reason = "key", f"the API refused the key ({e.code or e.status})"
        elif e.status in (404, 422) or e.code in ("model_not_found", "model_decommissioned"):
            kind, reason = "key", f"model or address rejected ({e.message[:80] or e.status})"
        elif e.status == 429:
            if any(w in text for w in ("per day", "tpd", "rpd", "daily", "quota")):
                kind, reason = "quota", "daily limit used up"
            else:
                kind, reason = "rate", "rate limit, too many requests"
        else:
            reason = f"cloud error {e.status}"
    else:
        reason = f"{type(e).__name__}: {str(e)[:80]}"
    with _lock:
        _s.update(last_error=reason, last_error_at=time.time())
        first = not _s["notified"] and kind in ("quota", "key")
        if first:
            _s["notified"] = True
    print(f"[llm] {reason}")
    if first:
        _notify(f"Daemon: the model stopped ({reason}).")


def _describe(e):
    if isinstance(e, LLMError):
        return f"{e.status} {e.code}: {e.message}".replace(" : ", " ").strip() + (f" (retry after {int(e.retry_after)} s)" if e.retry_after else "")
    return f"{type(e).__name__}: {e}"


def _watched(gen):
    """A cloud stream that records an error in the middle of the reply."""
    try:
        yield from gen
    except Exception as e:
        _failed(e)
        raise


def _sees_images():
    import uploads
    return uploads.model_sees(_cfg()["model"], _is_google())


class Client:
    """What agent.py talks to: chat() and list() of the configured cloud model."""

    def list(self):
        return CLOUD.list()

    def chat(self, model=None, messages=None, tools=None, think=None, stream=False, **_ignored):
        if not configured():
            raise RuntimeError("the model is not set up: fill llm.base_url, llm.api_key and llm.model in config.yaml")
        msgs = messages
        if any(isinstance(m, dict) and m.get("images") for m in msgs or []) and not _sees_images():
            msgs = without_images(msgs)
        try:
            r = CLOUD.chat(None, msgs, tools=tools, stream=stream, think=think)
        except Exception as e:
            _failed(e)
            raise RuntimeError(f"{name()} error: {_describe(e)}") from None
        with _lock:
            _s.update(last_ok=time.time(), notified=False)
        return _watched(r) if stream else r


def test():
    """One tiny request. Returns {ok, info}."""
    c = _cfg()
    if not configured():
        return {"ok": False, "info": "set llm.base_url, llm.api_key and llm.model in config.yaml"}
    t0 = time.time()
    try:
        r = CLOUD.chat(None, [{"role": "user", "content": "Reply with the single word: OK"}])
    except Exception as e:
        _failed(e)
        return {"ok": False, "info": (f"{e.status} {e.code}: {e.message}" if isinstance(e, LLMError) else f"{type(e).__name__}: {e}")[:200]}
    with _lock:
        _s.update(last_ok=time.time(), notified=False)
    return {"ok": True, "info": f"{name()} {c['model']} answered \"{r.message.content.strip()[:40]}\" in {time.time() - t0:.1f} s"}


def status():
    c = _cfg()
    with _lock:
        now = time.time()
        return {"configured": configured(), "model": c["model"], "name": name(),
                "last_ok_ago": int(now - _s["last_ok"]) if _s["last_ok"] else None,
                "last_error": _s["last_error"], "last_error_ago": int(now - _s["last_error_at"]) if _s["last_error_at"] else None}
