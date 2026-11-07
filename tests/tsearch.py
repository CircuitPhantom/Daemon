import os, sys, json, time
sys.path[:0]=["stubs","."]
os.environ.update(DAEMON_CONFIG="cfg41.yaml", DAEMON_CHATS="chats41", DAEMON_MEMORY="mem41.json", DAEMON_REMINDERS="rem41.json")
for f in ("cfg41.yaml","mem41.json","rem41.json"):
    if os.path.exists(f): os.remove(f)
def ok(c,m=""):
    if not c: print("FAIL",m); sys.exit(1)
import model_config as mc; ok(mc.load())
import search, tools, requests

DDG_HTML = '''<div class="result"><a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa&amp;rut=x">Example &amp; <b>A</b></a>
<a class="result__snippet" href="x">First <b>snippet</b> here</a></div>
<div class="result"><a rel="nofollow" class="result__a" href="https://example.org/b">Second</a><a class="result__snippet" href="x">Second snippet</a></div>'''
DDG_LITE = '''<tr><td><a rel="nofollow" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Flite.example%2F1" class='result-link'>Lite one</a></td></tr>
<tr><td class='result-snippet'>Lite <b>snippet</b></td></tr>'''
CAPTCHA = '<html><body><div class="anomaly-modal">anomaly detected</div></body></html>'
CALLS = []
class R:
    def __init__(self, text="", status=200, js=None, headers=None):
        self.text, self.status_code, self._js = text, status, js
    def json(self):
        if self._js is None: raise ValueError("no json")
        return self._js
    def raise_for_status(self):
        if self.status_code >= 400: raise requests.HTTPError(str(self.status_code))
MODE = {"ddg": "ok", "brave": "ok", "searx": "ok"}
def fake_post(url, data=None, **kw):
    CALLS.append(("POST", url, dict(data or {})))
    if "html.duckduckgo" in url:
        return R(CAPTCHA if MODE["ddg"] in ("captcha", "dead") else DDG_HTML)
    if "lite.duckduckgo" in url:
        if MODE["ddg"] == "dead": raise requests.ConnectionError("no route")
        return R(DDG_LITE)
    raise AssertionError(url)
def fake_get(url, params=None, headers=None, **kw):
    CALLS.append(("GET", url, dict(params or {}), dict(headers or {})))
    if "brave.com" in url:
        if MODE["brave"] == "401": return R(status=401)
        return R(js={"web": {"results": [{"title": "Brave <b>One</b>", "url": "https://b.example/1", "description": "d1", "age": "2 days ago"}]}})
    if "searx" in url or "127.0.0.1:8080" in url:
        if MODE["searx"] == "html": return R(text="<html>", js=None)
        return R(js={"results": [{"title": "Searx One", "url": "https://s.example/1", "content": "c1", "publishedDate": "2026-11-01"}]})
    raise AssertionError(url)
requests.post, requests.get = fake_post, fake_get

# defaults: DuckDuckGo
ok(mc.search["provider"]=="auto" and mc.search["results"]==5, mc.search)
res, name = search.search("test one"); ok(name=="duckduckgo" and len(res)==2 and res[0]["url"]=="https://example.com/a" and res[0]["title"]=="Example & A" and res[0]["snippet"]=="First snippet here", res)
n=len(CALLS); search.search("TEST one"); ok(len(CALLS)==n, "cached (case-insensitive)")
ok(search.status()["backends"]==["duckduckgo"], search.status())
# freshness / region
search.search("fresh q", fresh="week"); ok(CALLS[-1][2].get("df")=="w", CALLS[-1])
mc.search["region"]="tr-tr"; search.search("region q"); ok(CALLS[-1][2].get("kl")=="tr-tr", CALLS[-1]); mc.search["region"]=""
# captcha -> lite
MODE["ddg"]="captcha"; res,name=search.search("lite q"); ok(res[0]["title"]=="Lite one" and res[0]["url"]=="https://lite.example/1" and res[0]["snippet"]=="Lite snippet", res)
# everything dead -> error text
MODE["ddg"]="dead"
try: search.search("dead q"); ok(False,"should raise")
except search.SearchError as e: ok("duckduckgo" in str(e), e)
out=tools.web_search("dead q 2"); ok(out.startswith("Error: search failed"), out)
MODE["ddg"]="ok"
# Brave with key, freshness, header
mc.search.update(brave_key="BK", searxng_url="http://127.0.0.1:8080")
ok(search.status()["backends"]==["brave","searxng","duckduckgo"], search.status())
res,name=search.search("brave q", 3, "day"); ok(name=="brave" and res[0]["title"]=="Brave One" and res[0]["date"]=="2 days ago", res)
g=[c for c in CALLS if c[0]=="GET" and "brave" in c[1]][-1]; ok(g[2]["count"]==3 and g[2]["freshness"]=="pd" and g[3]["X-Subscription-Token"]=="BK", g)
# brave refused -> searxng
MODE["brave"]="401"; res,name=search.search("brave q2"); ok(name=="searxng" and res[0]["date"]=="2026-11-01", (name,res))
g=[c for c in CALLS if c[0]=="GET" and "8080" in c[1]][-1]; ok(g[2]["format"]=="json", g)
# searxng without json -> duckduckgo
MODE["searx"]="html"; res,name=search.search("brave q3"); ok(name=="duckduckgo", name)
MODE["brave"]=MODE["searx"]="ok"
# forced provider
mc.search["provider"]="searxng"; ok(search.status()["backends"][0]=="searxng", search.status()); res,name=search.search("forced q"); ok(name=="searxng", name)
mc.search["provider"]="auto"; mc.search.update(brave_key="", searxng_url="")
# the tool
out=tools.web_search("tool q", 1); ok(out.startswith("1. Example & A\n   https://example.com/a") and "2. " not in out and "untrusted" in out, out)
out=tools.web_search("tool q", "abc"); ok("2. Second" in out, out)       # a bad count falls back to 5
out=tools.web_search("tool q", 99); ok("2. Second" in out, "count is clamped")
ok(tools.web_search.__doc__ and "fresh" in tools.web_search.__doc__, "doc")
import llm; sc=llm.tool_schema(tools.web_search)["function"]; ok(sc["parameters"]["required"]==["query"] and sc["parameters"]["properties"]["count"]["type"]=="integer", sc)
# config validation
open("cfg41.yaml","w").write("search:\n  provider: nonsense\n  results: 99\n  brave_key: abc\n"); mc.load(); ok(mc.search["provider"]=="auto" and mc.search["results"]==5 and mc.search["brave_key"]=="abc", mc.search)
mc.save(); ok("search:" in open("cfg41.yaml").read(), "saved")
print("SEARCH OK")
