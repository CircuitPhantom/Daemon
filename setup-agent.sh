#!/usr/bin/env bash
# Sets up the Daemon laptop agent (wake word + desktop commands for a Daemon that runs on a server).
# Run it on the LAPTOP, inside a folder that has daemon-agent.py, tools.py and wakeword.py (the Daemon folder works).
#
#   ./setup-agent.sh --server https://NAME.tailnet.ts.net --token TOKEN     install, save the settings, start the service
#   ./setup-agent.sh --remove                                                stop and remove the service
#   options: --no-system (skip pacman/apt)  --no-service  --device "mic name"  -y
#
# The server address is the one you open the dashboard with. The token comes from `python satellite_setup.py` on the server.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
SERVER=""; TOKEN=""; DEVICE=""; SYSTEM=1; SERVICE=1; YES=0; REMOVE=0
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
CONF="${XDG_CONFIG_HOME:-$HOME/.config}/daemon-agent.json"

while (($#)); do
  case "$1" in
    --server) shift; SERVER="${1:?--server needs an address}" ;;
    --token) shift; TOKEN="${1:?--token needs the token}" ;;
    --device) shift; DEVICE="${1:-}" ;;
    --no-system) SYSTEM=0 ;;
    --no-service) SERVICE=0 ;;
    --remove) REMOVE=1 ;;
    -y|--yes) YES=1 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done
say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
warn() { printf '\033[33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
ask()  { ((YES)) && return 0; read -r -p "$1 [Y/n] " a; [[ -z "$a" || "$a" =~ ^[Yy] ]]; }

if ((REMOVE)); then
  systemctl --user disable --now daemon-agent.service 2>/dev/null || true
  rm -f "$UNIT_DIR/daemon-agent.service"; systemctl --user daemon-reload
  echo "Removed the agent service (settings stay in $CONF)"; exit 0
fi
for f in daemon-agent.py tools.py wakeword.py; do [[ -f "$f" ]] || die "$f is missing in $HERE (copy it from the Daemon folder)"; done

if ((SYSTEM)); then
  say "System packages"
  if command -v pacman >/dev/null; then
    PKGS=(python python-pip portaudio playerctl wl-clipboard xclip)
    missing=(); for p in "${PKGS[@]}"; do pacman -Qq "$p" >/dev/null 2>&1 || missing+=("$p"); done
    if ((${#missing[@]})); then echo "Missing: ${missing[*]}"; ask "Install them with sudo pacman?" && sudo pacman -S --needed --noconfirm "${missing[@]}" || warn "skipped"; else echo "all there"; fi
  elif command -v apt-get >/dev/null; then
    PKGS=(python3 python3-venv python3-pip libportaudio2 playerctl wl-clipboard xclip)
    missing=(); for p in "${PKGS[@]}"; do dpkg -s "$p" >/dev/null 2>&1 || missing+=("$p"); done
    if ((${#missing[@]})); then echo "Missing: ${missing[*]}"; ask "Install them with sudo apt?" && { sudo apt-get update && sudo apt-get install -y "${missing[@]}"; } || warn "skipped"; else echo "all there"; fi
  else warn "unknown package manager: install python 3, portaudio, playerctl and wl-clipboard or xclip by hand"; fi
fi

say "Python environment"
PY=""
for v in venv .venv agent-venv; do   # an existing Daemon environment already has what the agent needs
  if [[ -x "$v/bin/python" ]] && "$v/bin/python" -c "import numpy, websockets, sounddevice" 2>/dev/null; then PY="$HERE/$v/bin/python"; break; fi
done
if [[ -z "$PY" ]]; then
  [[ -d agent-venv ]] || python3 -m venv agent-venv
  agent-venv/bin/pip install --quiet --upgrade pip
  agent-venv/bin/pip install --quiet -r requirements-agent.txt
  PY="$HERE/agent-venv/bin/python"
fi
echo "using $PY"

if [[ -n "$SERVER" || -n "$TOKEN" ]]; then
  [[ -n "$SERVER" && -n "$TOKEN" ]] || die "give both --server and --token"
  mkdir -p "$(dirname "$CONF")"; umask 077
  "$PY" - "$CONF" "$SERVER" "$TOKEN" "$DEVICE" <<'PYEOF'
import json, sys
conf, server, token, device = sys.argv[1:5]
try: d = json.load(open(conf))
except Exception: d = {}
d.update(server=server, token=token)
if device: d["device"] = device
json.dump(d, open(conf, "w"), indent=1)
PYEOF
  chmod 600 "$CONF"; echo "saved $CONF"
fi
[[ -f "$CONF" ]] || die "no settings yet: run again with --server and --token"

say "Connection test"
if "$PY" - <<'PYEOF'
import json, os, sys, urllib.request
c = json.load(open(os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "daemon-agent.json")))
req = urllib.request.Request(c["server"].rstrip("/") + "/api/sat/config", headers={"Authorization": "Bearer " + c["token"], "User-Agent": "daemon-agent/1.0"})
try:
    urllib.request.urlopen(req, timeout=10); print("server answered, token accepted")
except Exception as e:
    print("could not use the server:", e); sys.exit(1)
PYEOF
then :; else warn "the agent will keep retrying; check the address, the token and that satellite is enabled on the server (python satellite_setup.py)"; fi

if ((SERVICE)); then
  say "Service"
  mkdir -p "$UNIT_DIR"
  cat > "$UNIT_DIR/daemon-agent.service" <<UNIT
[Unit]
Description=Daemon laptop agent (wake word + desktop commands)
After=network-online.target pipewire.service pipewire-pulse.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$HERE
Environment=PYTHONUNBUFFERED=1
ExecStart="$PY" "$HERE/daemon-agent.py"
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
UNIT
  systemctl --user daemon-reload
  systemctl --user enable --now daemon-agent.service
  sleep 2; systemctl --user --no-pager --lines=5 status daemon-agent.service || true
  echo; echo "Logs: journalctl --user -u daemon-agent -f"
else
  echo "Start by hand:  $PY daemon-agent.py"
fi
