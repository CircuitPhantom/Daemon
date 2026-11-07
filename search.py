"""Web search for the web_search tool.

Backends (config.yaml -> search):
  provider: auto      auto = Brave when brave_key is set, else your SearXNG when searxng_url is set, else DuckDuckGo
                      (no key needed). A backend that fails hands over to the next one. Or force: brave / searxng / ddg
  brave_key: ""       free key at brave.com/search/api (about 2000 searches a month)
  searxng_url: ""     e.g. http://127.0.0.1:8080 (your own SearXNG, with `json` allowed in its formats)
  results: 5          how many results the model gets (1-10)
  region: ""          DuckDuckGo region, e.g. tr-tr, us-en. Empty = no preference

Answers are kept for 10 minutes, so the same question does not hit the search engine twice.
"""
import html as _h
import re
import threading
import time
from urllib.parse import parse_qs, quote, unquote, urlparse

CACHE_SECONDS = 600
TIMEOUT = 12
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
FRESH = {"day": ("pd", "d", "day"), "week": ("pw", "w", "week"), "month": ("pm", "m", "month"), "year": ("py", "y", "year")}

_cache = {}
_lock = threading.Lock()
_last = {"backend": "", "error": ""}


class SearchError(Exception):
    pass


def _cfg():
    import model_config
    return model_config.search


def _strip(s):
    return " ".join(_h.unescape(re.sub(r"<[^>]+>", "", s or "")).split())


def _get(url, **kw):
    import requests
    kw.setdefault("timeout", TIMEOUT)
    kw.setdefault("headers", {"User-Agent": UA})
    r = requests.get(url, **kw)
    if r.status_code == 429:
        raise SearchError("rate limit (429)")
    if r.status_code in (401, 403):
        raise SearchError(f"refused ({r.status_code}): check the key")
    r.raise_for_status()
    return r


# ── backends: each returns a list of {title, url, snippet, date} ──
def brave(query, count, fresh, key):
    params = {"q": query, "count": count}
    if fresh in FRESH:
        params["freshness"] = FRESH[fresh][0]
    r = _get("https://api.search.brave.com/res/v1/web/search", params=params,
             headers={"X-Subscription-Token": key, "Accept": "application/json", "User-Agent": UA})
    out = []
    for x in (r.json().get("web") or {}).get("results", [])[:count]:
        out.append({"title": _strip(x.get("title")), "url": x.get("url", ""), "snippet": _strip(x.get("description")),
                    "date": _strip(x.get("age") or x.get("page_age") or "")})
    return out


def searxng(query, count, fresh, base):
    params = {"q": query, "format": "json"}
    if fresh in FRESH:
        params["time_range"] = FRESH[fresh][2]
    r = _get(base.rstrip("/") + "/search", params=params)
    try:
        items = r.json().get("results", [])
    except ValueError:
        raise SearchError("SearXNG did not answer with JSON (allow `json` in search.formats of its settings.yml)") from None
    return [{"title": _strip(x.get("title")), "url": x.get("url", ""), "snippet": _strip(x.get("content")),
             "date": _strip(x.get("publishedDate") or "")} for x in items[:count]]


def _ddg_link(href):
    href = _h.unescape(href)
    if "uddg=" in href:
        href = unquote(parse_qs(urlparse(href).query).get("uddg", [href])[0])
    elif href.startswith("//"):
        href = "https:" + href
    return href


def _anchors(page, css_class):
    """[(href, inner html)] of the <a> tags that have this class, whatever the order of their attributes."""
    out = []
    for m in re.finditer(r"<a\b([^>]*)>(.*?)</a>", page, re.S):
        attrs = m.group(1)
        if re.search(r"class=['\"][^'\"]*\b" + re.escape(css_class) + r"\b", attrs):
            h = re.search(r"href=['\"]([^'\"]*)['\"]", attrs)
            out.append((h.group(1) if h else "", m.group(2)))
    return out


def _ddg_html(query, count, fresh, region):
    import requests
    data = {"q": query}
    if region:
        data["kl"] = region
    if fresh in FRESH:
        data["df"] = FRESH[fresh][1]
    r = requests.post("https://html.duckduckgo.com/html/", data=data, headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    if "anomaly" in r.text[:6000] and "result__a" not in r.text:
        raise SearchError("DuckDuckGo asks for a captcha (too many searches)")
    links = _anchors(r.text, "result__a")
    snips = [t for _h, t in _anchors(r.text, "result__snippet")]
    return [{"title": _strip(t), "url": _ddg_link(h), "snippet": _strip(snips[i]) if i < len(snips) else "", "date": ""}
            for i, (h, t) in enumerate(links[:count]) if h]


def _ddg_lite(query, count, fresh, region):
    import requests
    data = {"q": query}
    if region:
        data["kl"] = region
    if fresh in FRESH:
        data["df"] = FRESH[fresh][1]
    r = requests.post("https://lite.duckduckgo.com/lite/", data=data, headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    links = _anchors(r.text, "result-link")
    snips = re.findall(r"<td[^>]+class=['\"]result-snippet['\"][^>]*>(.*?)</td>", r.text, re.S)
    return [{"title": _strip(t), "url": _ddg_link(h), "snippet": _strip(snips[i]) if i < len(snips) else "", "date": ""}
            for i, (h, t) in enumerate(links[:count]) if h]


def ddg(query, count, fresh, region):
    err = ""
    for fn in (_ddg_html, _ddg_lite):
        try:
            out = fn(query, count, fresh, region)
            if out:
                return out
        except SearchError as e:
            err = str(e)
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
    if err:
        raise SearchError(err)
    return []


# ── choosing a backend ──
def backends(c=None):
    """The backends to try, in order: [(name, fn(query, count, fresh))]."""
    c = c or _cfg()
    chain = {
        "brave": ("brave", lambda q, n, f: brave(q, n, f, c["brave_key"])) if c["brave_key"] else None,
        "searxng": ("searxng", lambda q, n, f: searxng(q, n, f, c["searxng_url"])) if c["searxng_url"] else None,
        "ddg": ("duckduckgo", lambda q, n, f: ddg(q, n, f, c["region"])),
    }
    want = c["provider"]
    order = ["brave", "searxng", "ddg"]
    if want in order:
        order.remove(want)
        order.insert(0, want)
    return [chain[k] for k in order if chain[k]]


def search(query, count=None, fresh=""):
    """Returns (results, backend_name). Raises SearchError with every backend's reason when all fail."""
    c = _cfg()
    count = max(1, min(int(count or c["results"]), 10))
    fresh = fresh if fresh in FRESH else ""
    key = (query.strip().lower(), count, fresh)
    now = time.time()
    with _lock:
        for k in [k for k, v in _cache.items() if now - v[0] > CACHE_SECONDS]:
            del _cache[k]
        if key in _cache:
            return _cache[key][1], _cache[key][2]
    errors = []
    for name, fn in backends(c):
        try:
            res = fn(query, count, fresh)
        except SearchError as e:
            errors.append(f"{name}: {e}")
            continue
        except Exception as e:
            errors.append(f"{name}: {type(e).__name__}: {e}")
            continue
        if res or name == "duckduckgo":
            with _lock:
                _cache[key] = (now, res, name)
                _last.update(backend=name, error="")
            return res, name
        errors.append(f"{name}: no results")
    with _lock:
        _last["error"] = "; ".join(errors)[:300]
    raise SearchError("; ".join(errors) or "no search backend")


def format_results(results):
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r['title']}\n   {r['url']}" + (f"  ({r['date']})" if r.get("date") else "") +
                     (f"\n   {r['snippet'][:300]}" if r.get("snippet") else ""))
    return "\n".join(lines)


def status():
    c = _cfg()
    with _lock:
        return {"provider": c["provider"], "backends": [n for n, _ in backends(c)], "last_backend": _last["backend"],
                "last_error": _last["error"], "cached": len(_cache)}
