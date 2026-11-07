import os, sys, tempfile, importlib
sys.path[:0]=["stubs","."]
d=tempfile.mkdtemp()
os.environ["DAEMON_CONFIG"]=d+"/config.yaml"
for k in list(os.environ):
    if k.startswith("DAEMON_LLM") or k in ("MY_KEY","BRAVE","DAEMON_SEARCH_BRAVE_KEY"): del os.environ[k]
open(d+"/.env","w").write('# secrets\nMY_KEY="sk-abc 123"\nexport BRAVE=bv-1 # note\nDAEMON_SEARCH_BRAVE_KEY=auto-brave\nUNUSED=1\n')
os.chmod(d+"/.env",0o644)
open(d+"/config.yaml","w").write("llm:\n  base_url: https://x/v1\n  api_key: ${MY_KEY}\n  model: ${MODEL:-m1}\nsearch:\n  brave_key: ''\n  results: 3\nelevenlabs:\n  api_key: ${NOPE}\nnotify:\n  twilio_token: tt-plain\n")
def ok(c,m=""):
    if not c: print("FAIL",m); sys.exit(1)
import model_config as mc
ok(mc.llm["api_key"]=="sk-abc 123" and mc.llm["model"]=="m1", mc.llm)
ok(mc.search["brave_key"]=="auto-brave" and mc.search["results"]==3, mc.search)
ok(os.environ["BRAVE"]=="bv-1", "export + inline comment")
ok(mc.elevenlabs["api_key"]=="", "missing var -> empty")
es=mc.env_status(); ok(es["missing"]==["NOPE"] and es["refs"]>=2 and es["auto"]==1, es)
# saving keeps references, never writes the key
mc.search["results"]=4; mc.save()
t=open(d+"/config.yaml").read()
ok("sk-abc" not in t and "auto-brave" not in t and "${MY_KEY}" in t and "${MODEL:-m1}" in t and "${NOPE}" in t, t[:600])
ok("tt-plain" in t, "plain values stay")
# a value changed in the dashboard is written as given
mc.llm["api_key"]="new-key"; mc.save(); t=open(d+"/config.yaml").read(); ok("new-key" in t and "${MY_KEY}" not in t, "changed")
# reload after .env change
open(d+"/config.yaml","w").write("llm:\n  api_key: ${MY_KEY}\n")
import time; time.sleep(0.01)
open(d+"/.env","w").write("MY_KEY=second\n"); mc.reload_if_changed(); ok(mc.llm["api_key"]=="second", mc.llm["api_key"])
ok("UNUSED" not in os.environ and "DAEMON_SEARCH_BRAVE_KEY" not in os.environ, "removed names leave the environment")
# real environment wins
os.environ["MY_KEY"]="real"; open(d+"/.env","w").write("MY_KEY=fromfile\n"); mc.load(); ok(mc.llm["api_key"]=="real", "real env wins")
del os.environ["MY_KEY"]
# migration script
open(d+"/config.yaml","w").write("llm:\n  base_url: u\n  api_key: sk-secret\nnotify:\n  twilio_token: 'tok 1'\n  twilio_to: '+905551234567'\n  twilio_language: tr-TR\nspotify:\n  client_id: abc123\n  client_secret: ''\nsignal:\n  account: '+15551234567'\n  cli: signal-cli\nauth:\n  secret: keepme\n")
os.remove(d+"/.env")
import secrets_to_env as s
sys.argv=["x"]; s.main(); ok("sk-secret" in open(d+"/config.yaml").read(), "dry run changes nothing")
sys.argv=["x","--apply"]; s.main()
c=open(d+"/config.yaml").read(); e=open(d+"/.env").read()
ok("api_key: ${DAEMON_LLM_API_KEY}" in c and "keepme" in c and "twilio_token: ${DAEMON_NOTIFY_TWILIO_TOKEN}" in c and "sk-secret" not in c, c)
ok("DAEMON_LLM_API_KEY=sk-secret" in e and 'DAEMON_NOTIFY_TWILIO_TOKEN="tok 1"' in e and oct(os.stat(d+"/.env").st_mode)[-3:]=="600", e)
ok("twilio_to: ${DAEMON_NOTIFY_TWILIO_TO}" in c and "client_id: ${DAEMON_SPOTIFY_CLIENT_ID}" in c and "account: ${DAEMON_SIGNAL_ACCOUNT}" in c and "twilio_language: tr-TR" in c and "cli: signal-cli" in c, c)
ok('DAEMON_NOTIFY_TWILIO_TO="+905551234567"' in e or "DAEMON_NOTIFY_TWILIO_TO=+905551234567" in e, e)
mc.load(); ok(mc.notify["twilio_to"]=="+905551234567" and mc.spotify["client_id"]=="abc123" and mc.signal_cfg["account"]=="+15551234567", (mc.notify["twilio_to"], mc.spotify["client_id"]))
mc.save(); t=open(d+"/config.yaml").read(); ok("905551234567" not in t and "abc123" not in t and "${DAEMON_NOTIFY_TWILIO_TO}" in t, t)
ok(mc.llm["api_key"]=="sk-secret" and mc.notify["twilio_token"]=="tok 1", (mc.llm["api_key"], mc.notify.get("twilio_token")))
print("ENV OK")
