"""Daemon settings, stored persistently in config.yaml.

- You can edit config.yaml by hand. Changes apply on the next message, even while the server runs
  (except the stt and tts sections, which need a restart).
- Changes made from the web UI or the terminal are written to the same file with save().
- Other modules keep using these as before:
    model_config.llm["model"], .think, .system_prompt, .available_tools
  New: .notify (timezone and phone call settings used by scheduler.py)
"""
import os
import re
import shutil
import tempfile
import threading
from pathlib import Path

import yaml

import tools

CONFIG_PATH = Path(os.environ.get("DAEMON_CONFIG") or Path(__file__).with_name("config.yaml"))
ENV_PATH = Path(os.environ.get("DAEMON_ENV") or CONFIG_PATH.with_name(".env"))     # secrets: keys, tokens (see _resolve_env)

DEFAULT_PROMPT = """You are an AI assistant running on an Arch Linux based distro. This is just for your info, do not talk about this unless asked to do so.

Rules:
- Give clear, technical and relevant answers.
- Answer the question, without leaving the topic.
- Your answers are spoken aloud. Keep them short (1-3 sentences), plain text only: no markdown, lists, tables or emoji.
- When reporting command output, summarize the key points instead of repeating it.
"""

DEFAULTS = {
    "think": True,                    # show the model's reasoning when it sends it
    "tools": [],                      # enabled tools (keys of tools.available_functions)
    "stt": {"model": "small", "device": "cpu", "compute_type": "int8"},
    "tts": {"voice": "af_sarah", "lang": "en-us"},
    # Scheduled tasks: results come as Signal messages (see "signal" below), optionally a phone call.
    "notify": {
        "base_url": "",               # how your phone reaches the dashboard, e.g. https://mypc.tailnet.ts.net
        "timezone": "Europe/Istanbul",
        # Phone call for [CALL] tasks (twilio_call.py). Leave empty to disable.
        "twilio_sid": "",
        "twilio_token": "",
        "twilio_from": "",            # your Twilio number, e.g. "+15551234567" (keep the quotes)
        "twilio_to": "",              # the phone to ring, e.g. "+905551234567" (keep the quotes)
        "twilio_language": "en-US",   # language of the spoken text, e.g. tr-TR
        "twilio_voice": "alice",
        "twilio_reminders": False,    # also ring for reminders
        "twilio_max_per_hour": 6,     # most phone calls Daemon places in an hour (guards against a runaway task)
        "twilio_ring_seconds": 30,    # how long the phone rings before Daemon gives up
    },
    # Your own names for open_app: "what you say": "command to run". Arguments are allowed.
    "app_aliases": {},                # e.g. {"spotify": "spotify-launcher", "browser": "firefox"}
    # spotify_play finds songs by name with the Spotify Web API (free app at developer.spotify.com/dashboard).
    "spotify": {"client_id": "", "client_secret": ""},
    # Your own names for spotify_play: "what you say": Spotify link or URI (Share > Copy link). No login needed.
    "spotify_aliases": {},            # e.g. {"my favorites": "https://open.spotify.com/playlist/...", "liked songs": "spotify:collection:tracks"}
    # Wake word on this computer's microphone (see wakeword.py). Replies play on this computer's speakers.
    "wake": {
        "enabled": False,
        "engine": "whisper",          # whisper: any phrase, more CPU | openwakeword: pretrained model, light
        "phrase": "hey daemon",       # whisper engine: what to say
        "aliases": "daemon, demon, damon, damian, diamond",   # other ways Whisper may write the name
        "oww_model": "hey_jarvis",    # openwakeword engine: model name or path to a .onnx file
        "input_device": "",           # empty = default microphone (see: python -m sounddevice)
        "followup_seconds": 6,        # after a reply, listen this long for a follow-up without the wake word
    },
    # Chat over Signal through signal-cli (see signal_bot.py). Needs: enabled, account, allowed.
    "signal": {
        "enabled": False,
        "account": "",                # the number signal-cli is registered with, e.g. "+15551234567"
        "allowed": "",                # who may talk to Daemon, comma separated: your number or Signal UUID
        "cli": "signal-cli",
        "max_age": 600,               # ignore messages older than this many seconds (sent while Daemon was off)
        "data_dir": "",               # where signal-cli keeps its files; empty = ~/.local/share/signal-cli
    },
    # Phone calls you can talk in (see phone_bridge.py). Needs the notify.twilio_* settings and a public address.
    "phone": {
        "enabled": False,
        "public_url": "",             # https address Twilio can reach, e.g. "https://mypc.tailnet.ts.net:8443"
        "port": 8001,                 # local port of the bridge; expose only this one, not the dashboard
        "max_minutes": 10,            # a call hangs up after this long
        "silence_seconds": 30,        # ...or after this long without anyone talking
        "speech_level": 0.020,        # how loud counts as you talking (0.01 = very sensitive, 0.03-0.05 = only clear speech)
        "noise_mult": 4.0,            # ...and at least this many times the line noise. Raise it if the line is noisy
        "min_speech_ms": 120,         # speech must last this long to count (short clicks and noise are ignored)
        "barge_ms": 500,              # how long you must talk over the reply to interrupt it
    },
    # The model: any cloud API that speaks the OpenAI format (see llm.py)
    "llm": {
        "base_url": "https://api.anthropic.com/v1",   # Groq: https://api.groq.com/openai/v1, NVIDIA: https://integrate.api.nvidia.com/v1
        "api_key": "",                # keep config.yaml private
        "model": "claude-sonnet-5-5",
        "timeout": 60,                # seconds to wait for the cloud
    },
    # ElevenLabs voice instead of the local Kokoro voice, with automatic fallback (see elevenlabs_tts.py)
    "elevenlabs": {
        "enabled": False,
        "api_key": "",                # elevenlabs.io > Developers > API Keys. Keep config.yaml private
        "voice_id": "",               # empty = the first voice of your account
        "model": "eleven_flash_v2_5", # fast and cheap (0.5 credit per character); eleven_multilingual_v2 = 1 credit
        "language": "",               # e.g. "tr"; empty = detected from the text
        "local_only": False,          # the dashboard switch: always use the local voice
        "fallback": True,             # when ElevenLabs fails or the credits run out use the local voice
        "monthly_chars": 0,           # your own cap of characters per month (0 = only ElevenLabs' own limit)
        "audio_tags_use": "normal",   # how often the model uses them: "rare", "normal" or "lively"
        "audio_tags": False,          # true = the model may write [laughing], [sighing]... and ElevenLabs acts them out. Needs a model that
                                      # understands them (eleven_v3; maybe newer ones). Always on for models with "v3" in the name
    },
    # Speech-to-text in the cloud (Groq, OpenAI...), local Whisper as fallback (see cloud_stt.py)
    "stt_cloud": {
        "enabled": False,
        "base_url": "https://api.groq.com/openai/v1",
        "api_key": "",                # Groq: console.groq.com > API Keys. Keep config.yaml private
        "model": "whisper-large-v3-turbo",
        "language": "",               # "tr", "en"... empty = detected
        "timeout": 20,                # seconds
    },
    # Laptop agent (daemon-agent.py): when Daemon runs on a server, the laptop does the microphone/wake word and the
    # desktop tools. Turn it on with: python satellite_setup.py
    "satellite": {
        "enabled": False,             # true on the SERVER. The server's own microphone/wake word is then not used
        "token": "",                  # secret shared with the agent (written by satellite_setup.py)
        "tools": ["system_info", "media_control", "volume", "clipboard_read", "clipboard_write", "open_url", "open_app", "spotify_open",
                  "screen_grab"],              # screen_input (mouse/keyboard) is not here on purpose: add it yourself and start the agent with --allow screen_input
    },
    # Looking after itself (routines.py, monitor.py): alerts on Signal, a weekly memory check, extras in the morning plan
    "care": {
        "watchdog": True,             # tell me on Signal when something is wrong (disk, backup, Tailscale, laptop agent, old page)
        "watch_minutes": 5,           # how often to look
        "disk_free_percent": 10,      # alert below this much free disk
        "backup_max_hours": 36,       # alert when the newest backup in ~/daemon-backups is older (only if that folder exists)
        "laptop_grace_minutes": 10,   # the laptop agent may be offline this long before it counts as a problem
        "alert_repeat_hours": 6,      # an unsolved problem is repeated after this many hours
        "memory_review": True,        # weekly Signal message about duplicate or very old memories
        "memory_review_day": 6,       # 0 = Monday ... 6 = Sunday
        "memory_review_time": "10:00",
        "briefing_extras": True,      # the morning plan also lists today's reminders and what you saved in the inbox yesterday
        "briefing_city": "",          # a city name adds the weather to the morning plan (wttr.in), empty = no weather
    },
    # Web search for the web_search tool (see search.py)
    "search": {
        "provider": "auto",           # auto = Brave if brave_key is set, else SearXNG if searxng_url is set, else DuckDuckGo. Or: brave / searxng / ddg
        "brave_key": "",              # free key (about 2000 searches a month): brave.com/search/api
        "searxng_url": "",            # your own SearXNG, e.g. http://127.0.0.1:8080
        "results": 5,                 # results given to the model (1-10)
        "region": "",                 # DuckDuckGo region, e.g. tr-tr or us-en
    },
    # Background jobs: "/job research X" runs in the background and the result comes to you on Signal (see jobs.py)
    "jobs": {
        "enabled": True,
        "max_running": 2,             # at the same time; more wait in line
        "timeout_minutes": 15,        # a job that takes longer is stopped
        "max_steps": 14,              # model calls per job
        "tools": ["web_search", "fetch_url", "read_file", "list_directory", "search_files", "search_text", "system_info",
                  "get_time", "calculate", "calendar_list", "inbox_search", "inbox_recent", "inbox_add"],
                                      # jobs never ask for approval, so tools in security.confirm_tools are left out even if listed
    },
    # The model using your mouse and keyboard through the laptop agent (see tools.computer). Off until you turn it on in two places:
    # the `computer` tool in Settings > Tools, and `--allow screen_input` when starting daemon-agent.py
    "computer": {
        "max_actions": 30,            # per turn; the first action asks for your OK for the whole turn
        "settle_seconds": 0.8,        # wait after an action before the new screenshot
        "approval_delay": 1.5,        # seconds to wait after you approve, before the first action (time to let go of the mouse)
        "blocked_keys": ["ctrl+alt+delete", "ctrl+alt+backspace", "super+l"],   # key combinations the model may not press
        "coords": "auto",             # how the model gives positions: pixels, 1000 (a 0-1000 grid: Nemotron VL, Qwen3-VL, GLM-V,
                                      # UI-TARS are trained that way) or auto (1000 for those models, pixels for the rest)
    },
    # Photos and files sent from the dashboard and Signal (see uploads.py)
    "uploads": {
        "enabled": True,
        "dir": "",                    # empty = ~/Documents/Daemon/uploads
        "max_mb": 20,                 # per file
        "max_chars": 12000,           # of a file's text given to the model
        "vision": "auto",             # auto / true / false: the model can look at photos (auto: Gemini and other known vision models)
    },
    # Free Microsoft Edge neural voice, after ElevenLabs and before the local one (see edge_voice.py)
    "edge_tts": {
        "enabled": False,
        "voice": "en-US-AriaNeural",
        "rate": "+0%",
        "pitch": "+0Hz",
        "primary": False,             # true = Edge before ElevenLabs (dashboard: Voice engine)
        "fallback": True,             # false = stay silent instead of switching to the local voice
    },
    # PIN lock for the dashboard (see auth.py). Set the PIN in Settings or with set_pin.py.
    "auth": {
        "enabled": False,             # false = no PIN asked. If you are ever locked out, set this to false here
        "pin_hash": "",               # written by set_pin.py / the dashboard
        "secret": "",                 # signs the login cookie; changes with the PIN
    },
    # Calendar (calendar.json, edited in the dashboard or by the model; see agenda.py)
    "calendar": {
        "briefing": False,            # every day at briefing_time: Signal message with the plan of the day
        "briefing_time": "08:00",     # HH:MM in notify.timezone
        "briefing_call": True,        # ...and ring you so the plan is read aloud (needs notify.twilio_*)
        "briefing_skip_empty": True,  # stay quiet on days with nothing planned
    },
    # Your OK before risky tools run, and the log of every tool call (see toolguard.py)
    "security": {
        "confirm": True,              # ask before the confirm_tools run (dashboard buttons, or "yes"/"no" on Signal)
        "confirm_tools": ["execute_command", "write_file", "send_file", "screenshot"],
        "confirm_seconds": 90,        # no answer in time = not run
    },
    # Persistent memory for chats (memory.json). Scheduled tasks never use it.
    "memory": {
        "enabled": True,              # add saved notes to the system prompt of chats
        "auto_save": True,            # let the model save/forget notes with tools
    },
}

# ── Runtime values (other modules read and modify these) ──
think = DEFAULTS["think"]
system_prompt = {"role": "system", "content": DEFAULT_PROMPT.strip()}   # same dict, updated in place
available_tools = []                                                    # same list, updated in place
stt = dict(DEFAULTS["stt"])
tts = dict(DEFAULTS["tts"])
notify = dict(DEFAULTS["notify"])
memory = dict(DEFAULTS["memory"])
wake = dict(DEFAULTS["wake"])
signal_cfg = dict(DEFAULTS["signal"])
phone_cfg = dict(DEFAULTS["phone"])
calendar_cfg = dict(DEFAULTS["calendar"])
auth_cfg = dict(DEFAULTS["auth"])
elevenlabs = dict(DEFAULTS["elevenlabs"])
stt_cloud = dict(DEFAULTS["stt_cloud"])
edge_tts = dict(DEFAULTS["edge_tts"])
uploads = dict(DEFAULTS["uploads"])
care = dict(DEFAULTS["care"])
search = dict(DEFAULTS["search"])
jobs = {**DEFAULTS["jobs"], "tools": list(DEFAULTS["jobs"]["tools"])}
computer = {**DEFAULTS["computer"], "blocked_keys": list(DEFAULTS["computer"]["blocked_keys"])}
security = {**DEFAULTS["security"], "confirm_tools": list(DEFAULTS["security"]["confirm_tools"])}
satellite = {**DEFAULTS["satellite"], "tools": list(DEFAULTS["satellite"]["tools"])}
llm = dict(DEFAULTS["llm"])

READ_ONLY = ["read_file", "list_directory", "search_files", "search_text", "fetch_url", "web_search",
             "system_info", "get_time", "calculate", "calendar_list", "inbox_search", "inbox_recent"]
DEFAULT_PROFILES = {
    "Off": [],
    "Read only": READ_ONLY,
    "Assistant": READ_ONLY + ["remind_me", "list_reminders", "cancel_reminder", "send_message", "call_me", "calendar_add",
                                  "calendar_update", "calendar_delete", "write_file", "send_file", "inbox_add", "inbox_search", "inbox_recent",
                                  "inbox_delete", "start_job"],
    "Desktop": READ_ONLY + ["remind_me", "list_reminders", "cancel_reminder", "media_control", "volume",
                            "clipboard_read", "clipboard_write", "open_url", "open_app", "spotify_play", "spotify_devices",
                            "spotify_transfer"],
    "Full": None,                     # None = every tool
}
app_aliases = {}                      # name -> command, used by open_app
spotify = dict(DEFAULTS["spotify"])
spotify_aliases = {}                  # name -> Spotify link or URI, used by spotify_play
tool_profiles = {}                    # name -> list of tool names, see DEFAULT_PROFILES

_lock = threading.RLock()
_mtime = None
_broken = False          # the last read of config.yaml failed (invalid YAML)

_HEADER = (
    "# Daemon settings. You can edit this by hand; the server reloads it on the next message.\n"
    "# tools: enabled tools (execute_command, read_file, fetch_url)\n"
    "# memory: persistent notes for chats (enabled, auto_save). Tasks never use them.\n"
    "# search: web search (provider, brave_key, searxng_url, results, region). jobs: background jobs started with /job (max_running, timeout_minutes, tools). computer: mouse and keyboard control through the laptop agent (max_actions, blocked_keys).\n"
    "# llm: the cloud model (base_url, api_key, model; Anthropic, Groq, NVIDIA...). elevenlabs: cloud voice with fallback to the local one (api_key, voice_id, local_only...). edge_tts: free Edge voice (enabled, voice, rate, pitch, fallback). uploads: photos and files sent from the dashboard and Signal (enabled, dir, max_mb, max_chars, vision). security: ask before risky tools (confirm, confirm_tools, confirm_seconds). care: Signal alerts when something breaks, weekly memory check, morning plan extras (watchdog, memory_review, briefing_extras, briefing_city...). stt_cloud: speech-to-text in the cloud with local fallback (api_key, base_url, model). satellite: laptop agent for the microphone and desktop tools (satellite_setup.py). auth: PIN lock for the dashboard (enabled: false turns it off). calendar: daily plan call (briefing, briefing_time). wake: wake word on this computer's microphone. signal: chat over Signal (signal_bot.py). tool_profiles: named tool sets for the web UI.\n"
    "# app_aliases: names for open_app, e.g. spotify: spotify-launcher\n"
    "# spotify / spotify_aliases: for the spotify_play tool (client_id + client_secret from developer.spotify.com, and your own names for links)\n"
    "# Restart the server after changing stt/tts.\n"
    "# notify: timezone, dashboard address and phone call (Twilio) settings. Keep this file private. Keys and tokens can live in .env instead: write api_key: ${NAME} here, NAME=value in .env.\n"
    "# Note: when a setting changes from the web UI the file is rewritten, so your own comments are lost.\n\n"
)


class _Dumper(yaml.SafeDumper):
    pass


def _str_repr(dumper, data):
    if "\n" in data:                                   # write multi-line text as a | block
        data = "\n".join(l.rstrip() for l in data.split("\n"))   # trailing spaces break the | style
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_Dumper.add_representer(str, _str_repr)


def _stat():
    out = []
    for p in (CONFIG_PATH, ENV_PATH):
        try:
            out.append(p.stat().st_mtime_ns)
        except OSError:
            out.append(None)
    return tuple(out)


# ── secrets in .env ──
# .env (next to config.yaml; DAEMON_ENV picks another file) holds lines like  NAME=value  (quotes, "export NAME=..." and # comments
# are fine). Two ways to use it:
#   1. in config.yaml write  api_key: ${NAME}  (or ${NAME:-default}) in any value
#   2. leave a key / token / secret / password field (or a phone number / account id: notify.twilio_sid, twilio_from, twilio_to,
#      spotify.client_id, signal.account, signal.allowed) empty and set  DAEMON_<SECTION>_<FIELD>  (llm.api_key = DAEMON_LLM_API_KEY,
#      search.brave_key = DAEMON_SEARCH_BRAVE_KEY, notify.twilio_to = DAEMON_NOTIFY_TWILIO_TO ...)
# Settings changed in the dashboard are written back with the ${NAME} (or the empty value) kept, so a key from .env never lands in
# config.yaml. A real environment variable beats the same name in .env. `python secrets_to_env.py` moves the keys of an existing
# config.yaml into .env.
_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
_SECRET_FIELD = re.compile(r"(key|token|secret|password)", re.I)
# private values that are not called key / token: phone numbers, account ids (kept out of config.yaml the same way)
_PRIVATE_FIELDS = {("notify", "twilio_sid"), ("notify", "twilio_from"), ("notify", "twilio_to"), ("spotify", "client_id"),
                   ("signal", "account"), ("signal", "allowed")}


def is_private_field(section, field):
    """True for the settings that belong in .env: keys, tokens, secrets, passwords, phone numbers, client / account ids."""
    return section not in ("auth", "system_prompt", "tool_profiles") and (bool(_SECRET_FIELD.search(field)) or (section, field) in _PRIVATE_FIELDS)
_env_set = {}            # names that came from .env (so a changed .env replaces them, a real environment variable is never touched)
_env_refs = {}           # path in config -> (text as written in config.yaml, text after substitution)
_env_missing = set()


def _parse_env(text):
    out = {}
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("export "):
            s = s[7:].lstrip()
        name, eq, val = s.partition("=")
        name, val = name.strip(), val.strip()
        if not eq or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            continue
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
            if s.split("=", 1)[1].strip()[0] == '"':
                val = val.replace("\\n", "\n")
        else:
            val = re.sub(r"\s+#.*$", "", val)
        out[name] = val
    return out


def load_env():
    """Reads .env into os.environ (real environment variables win). Safe to call again after the file changed."""
    try:
        text = ENV_PATH.read_text(encoding="utf-8")
        if ENV_PATH.stat().st_mode & 0o077:
            print(f"[config] {ENV_PATH.name} can be read by other users: run chmod 600 {ENV_PATH}")
    except OSError:
        text = ""
    new = _parse_env(text)
    for name in list(_env_set):
        if name not in new and os.environ.get(name) == _env_set[name]:
            del os.environ[name]
        if name not in new:
            _env_set.pop(name, None)
    for name, val in new.items():
        if name in os.environ and os.environ[name] != _env_set.get(name):
            continue                                   # the real environment wins
        os.environ[name] = val
        _env_set[name] = val
    return len(new)


def _expand(value, path):
    if isinstance(value, dict):
        return {k: _expand(v, path + (k,)) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v, path + (i,)) for i, v in enumerate(value)]
    if isinstance(value, str) and "${" in value:
        def sub(m):
            got = os.environ.get(m.group(1))
            if got is None:
                if m.group(2) is not None:
                    return m.group(2)
                _env_missing.add(m.group(1))
                return ""
            return got
        out = _ENV_REF.sub(sub, value)
        _env_refs[path] = (value, out)
        return out
    return value


def _resolve_env(raw):
    """config.yaml as read -> with ${NAME} replaced and empty secret fields filled from DAEMON_<SECTION>_<FIELD>."""
    _env_refs.clear()
    _env_missing.clear()
    out = {k: (v if k in ("system_prompt", "tool_profiles") else _expand(v, (k,))) for k, v in raw.items()}
    for section, fields in DEFAULTS.items():
        if section == "auth" or not isinstance(fields, dict):
            continue
        for field, default in fields.items():
            if not isinstance(default, str) or not is_private_field(section, field):
                continue
            val = os.environ.get(f"DAEMON_{section}_{field}".upper())
            sect = out.get(section)
            if val and (sect is None or isinstance(sect, dict)) and not (sect or {}).get(field):
                out.setdefault(section, {})[field] = val
                _env_refs[(section, field)] = ("", val)
    for name in sorted(_env_missing):
        print(f"[config] config.yaml uses ${{{name}}} but {name} is not set (add it to {ENV_PATH.name})")
    return out


def _restore_env(data):
    """Settings about to be written: values that came from .env go back as they were written (${NAME} or empty)."""
    for path, (written, expanded) in _env_refs.items():
        node = data
        for key in path[:-1]:
            try:
                node = node[key]
            except (KeyError, IndexError, TypeError):
                node = None
                break
        if node is None:
            continue
        try:
            if node[path[-1]] == expanded:
                node[path[-1]] = written
        except (KeyError, IndexError, TypeError):
            pass
    return data


def env_status():
    """For doctor.py: (.env found, names in it, ${NAME} missing, fields filled by DAEMON_<SECTION>_<FIELD>)."""
    return {"found": ENV_PATH.exists(), "names": len(_env_set), "missing": sorted(_env_missing),
            "refs": sum(1 for w, _e in _env_refs.values() if w), "auto": sum(1 for w, _e in _env_refs.values() if not w)}


def _clean(text):
    # trailing spaces break YAML's | block style
    return "\n".join(l.rstrip() for l in str(text).strip().splitlines()) + "\n"


def _apply(data):
    """Applies the values from the file. Keys missing from the file fall back to defaults."""
    global think

    t = data.get("think", DEFAULTS["think"])
    think = t if isinstance(t, bool) else DEFAULTS["think"]

    p = data.get("system_prompt")
    system_prompt["content"] = p.strip() if isinstance(p, str) and p.strip() else DEFAULT_PROMPT.strip()

    names = data.get("tools", DEFAULTS["tools"])
    funcs = []
    for n in (names if isinstance(names, list) else []):
        n = tools.canonical(n)
        fn = tools.available_functions.get(n)
        if fn:
            funcs.append(fn)
        else:
            print(f"[config] unknown tool skipped: {n}")
    available_tools[:] = funcs

    for key, target in (("stt", stt), ("tts", tts)):
        v = data.get(key) if isinstance(data.get(key), dict) else {}
        for k, default in DEFAULTS[key].items():
            x = v.get(k, default)
            target[k] = x if isinstance(x, str) and x.strip() else default

    v = data.get("notify") if isinstance(data.get("notify"), dict) else {}
    for k, default in DEFAULTS["notify"].items():
        x = v.get(k, default)
        if isinstance(default, bool):
            notify[k] = x if isinstance(x, bool) else default
            continue
        if isinstance(default, int):
            notify[k] = x if isinstance(x, int) and not isinstance(x, bool) and 1 <= x <= 3600 else default
            continue
        ok = isinstance(x, (str, int)) and not isinstance(x, bool)
        notify[k] = str(x).strip() if ok else default
    if not notify["twilio_to"] and v.get("callmebot_phone"):      # older config: reuse the phone number
        notify["twilio_to"] = str(v["callmebot_phone"]).strip()

    v = data.get("spotify") if isinstance(data.get("spotify"), dict) else {}
    for k, default in DEFAULTS["spotify"].items():
        x = v.get(k, default)
        spotify[k] = str(x).strip() if isinstance(x, (str, int)) and not isinstance(x, bool) else default

    v = data.get("spotify_aliases")
    spotify_aliases.clear()
    if isinstance(v, dict):
        for k, link in v.items():
            if isinstance(k, (str, int)) and isinstance(link, str) and link.strip():
                spotify_aliases[str(k).strip().lower()] = link.strip()

    v = data.get("app_aliases")
    app_aliases.clear()
    if isinstance(v, dict):
        for k, cmd in v.items():
            if isinstance(k, (str, int)) and isinstance(cmd, str) and cmd.strip():
                app_aliases[str(k).strip().lower()] = cmd.strip()

    v = data.get("wake") if isinstance(data.get("wake"), dict) else {}
    for k, default in DEFAULTS["wake"].items():
        x = v.get(k, default)
        if isinstance(default, bool):
            wake[k] = x if isinstance(x, bool) else default
        elif isinstance(default, int):
            wake[k] = x if isinstance(x, int) and not isinstance(x, bool) and 0 <= x <= 60 else default
        else:
            wake[k] = str(x).strip() if isinstance(x, (str, int)) and not isinstance(x, bool) else default

    v = data.get("signal") if isinstance(data.get("signal"), dict) else {}
    for k, default in DEFAULTS["signal"].items():
        x = v.get(k, default)
        if isinstance(default, bool):
            signal_cfg[k] = x if isinstance(x, bool) else default
        elif isinstance(default, int):
            signal_cfg[k] = x if isinstance(x, int) and not isinstance(x, bool) and 30 <= x <= 86400 else default
        else:
            signal_cfg[k] = str(x).strip() if isinstance(x, (str, int)) and not isinstance(x, bool) else default

    v = data.get("phone") if isinstance(data.get("phone"), dict) else {}
    for k, default in DEFAULTS["phone"].items():
        x = v.get(k, default)
        if isinstance(default, bool):
            phone_cfg[k] = x if isinstance(x, bool) else default
        elif isinstance(default, float):
            phone_cfg[k] = float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and 0.001 <= x <= 100 else default
        elif isinstance(default, int):
            phone_cfg[k] = x if isinstance(x, int) and not isinstance(x, bool) and 1 <= x <= 65535 else default
        else:
            phone_cfg[k] = str(x).strip() if isinstance(x, (str, int)) and not isinstance(x, bool) else default

    v = data.get("llm") if isinstance(data.get("llm"), dict) else {}
    for k, default in DEFAULTS["llm"].items():
        x = v.get(k, default)
        if isinstance(default, bool):
            llm[k] = x if isinstance(x, bool) else default
        elif isinstance(default, int):
            llm[k] = x if isinstance(x, int) and not isinstance(x, bool) and 5 <= x <= 600 else default
        else:
            llm[k] = str(x).strip() if isinstance(x, (str, int)) and not isinstance(x, bool) else default

    v = data.get("elevenlabs") if isinstance(data.get("elevenlabs"), dict) else {}
    for k, default in DEFAULTS["elevenlabs"].items():
        x = v.get(k, default)
        if isinstance(default, bool):
            elevenlabs[k] = x if isinstance(x, bool) else default
        elif isinstance(default, int):
            elevenlabs[k] = x if isinstance(x, int) and not isinstance(x, bool) and 0 <= x <= 100_000_000 else default
        else:
            elevenlabs[k] = str(x).strip() if isinstance(x, (str, int)) and not isinstance(x, bool) else default
    if not elevenlabs["model"]:
        elevenlabs["model"] = DEFAULTS["elevenlabs"]["model"]

    v = data.get("edge_tts") if isinstance(data.get("edge_tts"), dict) else {}
    for k, default in DEFAULTS["edge_tts"].items():
        x = v.get(k, default)
        if isinstance(default, bool):
            edge_tts[k] = x if isinstance(x, bool) else default
        else:
            edge_tts[k] = str(x).strip() if isinstance(x, (str, int)) and not isinstance(x, bool) else default
            if not edge_tts[k]:
                edge_tts[k] = default

    v = data.get("care") if isinstance(data.get("care"), dict) else {}
    for k, default in DEFAULTS["care"].items():
        x = v.get(k, default)
        if isinstance(default, bool):
            care[k] = x if isinstance(x, bool) else default
        elif isinstance(default, int):
            hi = 6 if k == "memory_review_day" else 100 if k == "disk_free_percent" else 100_000
            care[k] = x if isinstance(x, int) and not isinstance(x, bool) and (0 if k == "memory_review_day" else 1) <= x <= hi else default
        elif k.endswith("_time"):
            care[k] = x if isinstance(x, str) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", x.strip()) else default
        else:
            care[k] = str(x).strip()[:60] if isinstance(x, (str, int, float)) and not isinstance(x, bool) else default

    v = data.get("search") if isinstance(data.get("search"), dict) else {}
    for k, default in DEFAULTS["search"].items():
        x = v.get(k, default)
        if isinstance(default, int):
            search[k] = x if isinstance(x, int) and not isinstance(x, bool) and 1 <= x <= 10 else default
        else:
            search[k] = str(x).strip() if isinstance(x, (str, int)) and not isinstance(x, bool) else default
    if search["provider"] not in ("auto", "brave", "searxng", "ddg"):
        search["provider"] = "auto"

    v = data.get("jobs") if isinstance(data.get("jobs"), dict) else {}
    for k, default in DEFAULTS["jobs"].items():
        x = v.get(k, default)
        if isinstance(default, bool):
            jobs[k] = x if isinstance(x, bool) else default
        elif isinstance(default, list):
            jobs[k] = [tools.canonical(str(t)) for t in x if str(t).strip()] if isinstance(x, list) else list(default)
        else:
            hi = {"max_running": 6, "timeout_minutes": 240, "max_steps": 60}[k]
            jobs[k] = x if isinstance(x, int) and not isinstance(x, bool) and 1 <= x <= hi else default

    v = data.get("computer") if isinstance(data.get("computer"), dict) else {}
    x = v.get("max_actions")
    computer["max_actions"] = x if isinstance(x, int) and not isinstance(x, bool) and 1 <= x <= 200 else DEFAULTS["computer"]["max_actions"]
    x = v.get("settle_seconds")
    computer["settle_seconds"] = float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and 0 <= x <= 10 else DEFAULTS["computer"]["settle_seconds"]
    x = v.get("blocked_keys")
    computer["blocked_keys"] = ([str(k).strip().lower().replace(" ", "") for k in x if str(k).strip()] if isinstance(x, list)
                                else list(DEFAULTS["computer"]["blocked_keys"]))
    x = v.get("approval_delay")
    computer["approval_delay"] = float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and 0 <= x <= 10 else DEFAULTS["computer"]["approval_delay"]
    x = str(v.get("coords", "auto")).strip().lower()
    computer["coords"] = x if x in ("auto", "pixels", "1000") else "auto"

    v = data.get("uploads") if isinstance(data.get("uploads"), dict) else {}
    for k, default in DEFAULTS["uploads"].items():
        x = v.get(k, default)
        if isinstance(default, bool):
            uploads[k] = x if isinstance(x, bool) else default
        elif isinstance(default, int):
            uploads[k] = x if isinstance(x, int) and not isinstance(x, bool) and 1 <= x <= 1_000_000 else default
        else:
            uploads[k] = str(x).strip() if isinstance(x, (str, int, float, bool)) else default

    v = data.get("security") if isinstance(data.get("security"), dict) else {}
    security["confirm"] = v["confirm"] if isinstance(v.get("confirm"), bool) else DEFAULTS["security"]["confirm"]
    t = v.get("confirm_tools")
    security["confirm_tools"] = ([tools.canonical(str(x)) for x in t if str(x).strip()] if isinstance(t, list)
                                 else list(DEFAULTS["security"]["confirm_tools"]))
    x = v.get("confirm_seconds")
    security["confirm_seconds"] = x if isinstance(x, int) and not isinstance(x, bool) and 15 <= x <= 600 else DEFAULTS["security"]["confirm_seconds"]

    v = data.get("stt_cloud") if isinstance(data.get("stt_cloud"), dict) else {}
    for k, default in DEFAULTS["stt_cloud"].items():
        x = v.get(k, default)
        if isinstance(default, bool):
            stt_cloud[k] = x if isinstance(x, bool) else default
        elif isinstance(default, int):
            stt_cloud[k] = x if isinstance(x, int) and not isinstance(x, bool) and 3 <= x <= 120 else default
        else:
            stt_cloud[k] = str(x).strip() if isinstance(x, (str, int)) and not isinstance(x, bool) else default
    if not stt_cloud["model"]:
        stt_cloud["model"] = DEFAULTS["stt_cloud"]["model"]

    v = data.get("satellite") if isinstance(data.get("satellite"), dict) else {}
    satellite["enabled"] = v.get("enabled") if isinstance(v.get("enabled"), bool) else False
    satellite["token"] = v["token"].strip() if isinstance(v.get("token"), str) else ""
    t = v.get("tools")
    satellite["tools"] = ([str(x).strip() for x in t if str(x).strip()] if isinstance(t, list)
                          else list(DEFAULTS["satellite"]["tools"]))
    if satellite["enabled"] and len(satellite["token"]) < 16:
        print("[config] satellite.enabled is true but satellite.token is missing or short: run python satellite_setup.py")

    v = data.get("auth") if isinstance(data.get("auth"), dict) else {}
    for k, default in DEFAULTS["auth"].items():
        x = v.get(k, default)
        auth_cfg[k] = (x if isinstance(x, bool) else default) if isinstance(default, bool) else (x.strip() if isinstance(x, str) else default)
    if auth_cfg["enabled"] and not auth_cfg["pin_hash"]:
        print("[config] auth.enabled is true but there is no PIN yet: the dashboard stays open. Run: python set_pin.py")

    v = data.get("calendar") if isinstance(data.get("calendar"), dict) else {}
    for k, default in DEFAULTS["calendar"].items():
        x = v.get(k, default)
        if isinstance(default, bool):
            calendar_cfg[k] = x if isinstance(x, bool) else default
        else:
            ok = isinstance(x, str) and re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", x.strip())
            calendar_cfg[k] = "{:02d}:{}".format(int(x.strip().split(":")[0]), x.strip().split(":")[1]) if ok else default

    v = data.get("tool_profiles")
    if not isinstance(v, dict) or not v:
        v = {n: (list(tools.available_functions) if t is None else t) for n, t in DEFAULT_PROFILES.items()}
    seen = data.get("tools_seen")
    if isinstance(seen, list):
        seen = {tools.canonical(x) for x in seen}
    elif data.get("tool_profiles"):                   # written before tools_seen existed: these tools came later
        seen = set(tools.available_functions) - {"send_file", "inbox_add", "inbox_search", "inbox_recent", "inbox_delete"}
    else:
        seen = set(tools.available_functions)
    new_tools = [n for n in tools.available_functions if n not in seen]
    tool_profiles.clear()
    for name, lst in v.items():
        if isinstance(name, str) and name.strip() and isinstance(lst, list):
            name = name.strip()[:40]
            lst = [t for t in dict.fromkeys(tools.canonical(x) for x in lst) if t in tools.available_functions]
            if name in DEFAULT_PROFILES:                  # a built-in profile also gets the tools added since the last save
                want = list(tools.available_functions) if DEFAULT_PROFILES[name] is None else DEFAULT_PROFILES[name]
                lst += [t for t in new_tools if t in want and t not in lst]
            if DEFAULT_PROFILES.get(name, []) is None:    # "Full" always means every tool
                lst = list(tools.available_functions)
            tool_profiles[name] = lst

    v = data.get("memory") if isinstance(data.get("memory"), dict) else {}
    for k, default in DEFAULTS["memory"].items():
        x = v.get(k, default)
        memory[k] = x if isinstance(x, bool) else default


def load():
    """Reads config.yaml. Creates it with defaults if missing. Keeps current settings if it is invalid."""
    global _mtime, _broken
    with _lock:
        load_env()
        try:
            raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
            if not isinstance(raw, dict):
                raise ValueError("the top level of the file must be a mapping")
            raw = _resolve_env(raw)
        except FileNotFoundError:
            _apply(_resolve_env({}))
            save()
            return True
        except Exception as e:
            print(f"[config] could not read {CONFIG_PATH.name}, keeping current settings: {e}")
            _mtime = _stat()          # do not re-read the broken file on every message
            _broken = True
            return False
        _broken = False
        _apply(raw)
        _mtime = _stat()
        return True


def spotify_token_path():
    """Where spotify_login.py keeps the login that lets spotify_play see your own playlists."""
    return CONFIG_PATH.with_name("spotify_token.json")


def reload_if_changed():
    """Reloads the file if it was edited by hand. Returns True if it changed."""
    with _lock:
        if _stat() != _mtime:
            ok = load()
            if ok:
                print(f"[config] {CONFIG_PATH.name} reloaded")
            return ok
    return False


def dump_yaml(data):
    """YAML text with readable multi-line strings (shared with scheduler.py)."""
    return yaml.dump(
        data, Dumper=_Dumper, sort_keys=False, allow_unicode=True,
        default_flow_style=False, width=1000,
    )


def atomic_write(path, text):
    """Writes the file atomically; the new file is private (mode 600)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def save():
    """Writes the current settings to config.yaml (atomically)."""
    global _mtime, _broken
    with _lock:
        if _broken and CONFIG_PATH.exists():     # your hand edit had an error: keep it instead of overwriting it
            keep = CONFIG_PATH.with_name(CONFIG_PATH.name + ".broken")
            shutil.copy2(CONFIG_PATH, keep)
            print(f"[config] {CONFIG_PATH.name} had an error and is being rewritten; your version is saved as {keep.name}")
            _broken = False
        name_of = {fn: n for n, fn in tools.available_functions.items()}
        data = {
            "think": bool(think),
            "system_prompt": _clean(system_prompt["content"]),
            "tools": [name_of[f] for f in available_tools if f in name_of],
            "stt": dict(stt),
            "tts": dict(tts),
            "notify": dict(notify),
            "memory": dict(memory),
            "app_aliases": dict(app_aliases),
            "spotify": dict(spotify),
            "spotify_aliases": dict(spotify_aliases),
            "wake": dict(wake),
            "signal": dict(signal_cfg),
            "phone": dict(phone_cfg),
            "calendar": dict(calendar_cfg),
            "auth": dict(auth_cfg),
            "elevenlabs": dict(elevenlabs),
            "stt_cloud": dict(stt_cloud),
            "edge_tts": dict(edge_tts),
            "uploads": dict(uploads),
            "care": dict(care),
            "search": dict(search),
            "jobs": {**jobs, "tools": list(jobs["tools"])},
            "computer": {**computer, "blocked_keys": list(computer["blocked_keys"])},
            "security": {**security, "confirm_tools": list(security["confirm_tools"])},
            "satellite": {**satellite, "tools": list(satellite["tools"])},
            "llm": dict(llm),
            "tool_profiles": {k: list(v) for k, v in tool_profiles.items()},
            "tools_seen": list(tools.available_functions),
        }
        atomic_write(CONFIG_PATH, _HEADER + dump_yaml(_restore_env(data)))
        _mtime = _stat()


load()
