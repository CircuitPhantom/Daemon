#!/usr/bin/env bash
# Sets Daemon up on a new computer: system packages, Python environment, web libraries, your backup, the service.
# Run it inside the project folder (the one with server.py), as your normal user (it asks for sudo only to install packages).
#
#   ./setup.sh                                  install everything that is missing
#   ./setup.sh --restore ~/daemon-backup.tar.gz also restore settings, calendar, chats, memory and the Signal login
#   ./setup.sh --models                         also download the speech models now (otherwise on first start)
#   ./setup.sh --service                        also install and start the systemd user service
#   ./setup.sh --no-system                      skip the system packages (pacman/apt)
#   ./setup.sh -y                               do not ask questions
#
# On the laptop of a server setup use ./setup-agent.sh instead (see MIGRATION.md).
# Safe to run again: it only adds what is missing.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
SIGNAL_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/signal-cli"
RESTORE=""; MODELS=0; SERVICE=0; SYSTEM=1; YES=0

while (($#)); do
  case "$1" in
    --restore) shift; RESTORE="${1:?--restore needs the backup file}" ;;
    --models) MODELS=1 ;;
    --service) SERVICE=1 ;;
    --no-system) SYSTEM=0 ;;
    -y|--yes) YES=1 ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
warn() { printf '\033[33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
ask()  { ((YES)) && return 0; read -r -p "$1 [Y/n] " a; [[ -z "$a" || "$a" =~ ^[Yy] ]]; }

[[ -f server.py && -f model_config.py ]] || die "run this inside the Daemon project folder (server.py not found here)"

# ── 1. system packages ──
if ((SYSTEM)); then
  say "System packages"
  if command -v pacman >/dev/null; then
    PKGS=(python python-pip portaudio playerctl wl-clipboard xclip curl signal-cli jdk-openjdk)
    missing=(); for p in "${PKGS[@]}"; do pacman -Qq "$p" >/dev/null 2>&1 || missing+=("$p"); done
    if ((${#missing[@]})); then
      echo "Missing: ${missing[*]}"
      if ask "Install them with sudo pacman?"; then sudo pacman -S --needed --noconfirm "${missing[@]}"; else warn "skipped"; fi
    else echo "all there"; fi
    command -v java >/dev/null || warn "java not found: run  sudo archlinux-java set java-XX-openjdk  (see: archlinux-java status)"
  elif command -v apt-get >/dev/null; then
    PKGS=(python3 python3-venv python3-pip libportaudio2 playerctl wl-clipboard xclip curl default-jre-headless)
    missing=(); for p in "${PKGS[@]}"; do dpkg -s "$p" >/dev/null 2>&1 || missing+=("$p"); done
    if ((${#missing[@]})); then
      echo "Missing: ${missing[*]}"
      if ask "Install them with sudo apt?"; then sudo apt-get update && sudo apt-get install -y "${missing[@]}"; else warn "skipped"; fi
    else echo "all there"; fi
    command -v signal-cli >/dev/null || warn "signal-cli is not in apt: download it from github.com/AsamK/signal-cli/releases and put it in your PATH"
  else
    warn "unknown package manager. Install by hand: python 3 + venv, portaudio, playerctl, wl-clipboard or xclip, java, signal-cli"
  fi
  command -v tailscale >/dev/null || warn "Tailscale is not installed (tailscale.com/download). Needed to reach the dashboard from your phone."
fi

# ── 2. Python environment ──
say "Python environment"
if [[ ! -x venv/bin/python ]]; then
  python3 -m venv venv || die "could not create venv (on Debian/Ubuntu: sudo apt install python3-venv)"
fi
REQ=requirements.txt
[[ -f requirements.lock ]] && ask "Use the exact versions from requirements.lock (from your old computer)?" && REQ=requirements.lock
venv/bin/python -m pip install --upgrade pip >/dev/null
venv/bin/python -m pip install -r "$REQ" || die "pip install failed (see above)"
echo "installed from $REQ"

# ── 3. web libraries (3D sphere, markdown, code highlighting) ──
say "Web libraries"
mkdir -p static/lib
fetch() { [[ -s "static/lib/$1" ]] || { curl -fsSL "$2" -o "static/lib/$1" && echo "downloaded $1" || warn "could not download $1 from $2"; }; }
fetch three.min.js         https://cdn.jsdelivr.net/npm/three@0.128.0/build/three.min.js
fetch marked.min.js        https://cdn.jsdelivr.net/npm/marked@16.3.0/lib/marked.umd.min.js
fetch highlight.min.js     https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.10.0/build/highlight.min.js
fetch github-dark.min.css  https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.10.0/build/styles/github-dark.min.css
echo "static/lib: $(ls static/lib | tr '\n' ' ')"

# ── 4. restore the backup ──
if [[ -n "$RESTORE" ]]; then
  say "Restoring $RESTORE"
  [[ -f "$RESTORE" ]] || die "backup file not found: $RESTORE"
  if systemctl --user is-active --quiet daemon.service 2>/dev/null; then
    die "the daemon service is running here: stop it first (systemctl --user stop daemon)"
  fi
  TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
  tar -C "$TMP" -xzf "$RESTORE"
  [[ -f "$TMP/MANIFEST.txt" ]] && sed 's/^/  /' "$TMP/MANIFEST.txt"
  STAMP="$(date +%Y%m%d-%H%M%S)"
  if [[ -d "$TMP/project" ]]; then
    # whatever exists here is kept as *.before-restore, nothing is lost
    for item in "$TMP"/project/* "$TMP"/project/.[!.]*; do
      [[ -e "$item" ]] || continue
      name="$(basename "$item")"
      [[ "$name" == requirements.lock && -f requirements.lock ]] && continue
      if [[ -e "$name" && "$name" != static ]]; then mv "$name" "$name.before-restore-$STAMP"; fi
      if [[ "$name" == static ]]; then mkdir -p static && cp -a "$item/." static/; else cp -a "$item" "./$name"; fi
    done
    chmod 600 config.yaml spotify_token.json 2>/dev/null || true
    echo "settings and data restored (old files, if any, are named *.before-restore-$STAMP)"
  fi
  if [[ -d "$TMP/daemon-files" ]]; then                # the Daemon folder: files you sent, notes it wrote
    FILES_DIR="${DAEMON_FILES:-$HOME/Documents/Daemon}"
    if [[ -d "$FILES_DIR" ]]; then mv "$FILES_DIR" "$FILES_DIR.before-restore-$STAMP"; echo "existing Daemon folder kept as $FILES_DIR.before-restore-$STAMP"; fi
    mkdir -p "$(dirname "$FILES_DIR")"
    cp -a "$TMP/daemon-files" "$FILES_DIR"
    echo "Daemon folder restored to $FILES_DIR"
  fi
  if [[ -d "$TMP/signal-cli" ]]; then
    if [[ -d "$SIGNAL_DIR" ]]; then mv "$SIGNAL_DIR" "$SIGNAL_DIR.before-restore-$STAMP"; echo "existing Signal data kept as $SIGNAL_DIR.before-restore-$STAMP"; fi
    mkdir -p "$(dirname "$SIGNAL_DIR")"
    cp -a "$TMP/signal-cli" "$SIGNAL_DIR"
    chmod -R go-rwx "$SIGNAL_DIR"
    echo "Signal account restored to $SIGNAL_DIR"
    echo "IMPORTANT: the old computer must NOT run Daemon or signal-cli any more, one account can only live in one place."
  fi
fi

# ── 5. models ──
if ((MODELS)); then
  say "Models"
  venv/bin/python - <<'PY' || warn "could not pre-load the speech models (they download on the first start instead)"
import model_config as m
from faster_whisper import WhisperModel
print("speech recognition:", m.stt["model"])
WhisperModel(m.stt["model"], device=m.stt["device"], compute_type=m.stt["compute_type"])
from pykokoro import KokoroSynthesizer, GenerationConfig, SynthesisConfig
print("voice: kokoro")
with KokoroSynthesizer(SynthesisConfig(voice=m.tts["voice"], generation=GenerationConfig(lang=m.tts["lang"]))) as s:
    s.synthesize_text("ok", language=m.tts["lang"], voice=m.tts["voice"])
PY
fi

# ── 6. service ──
if ((SERVICE)); then
  say "Service"
  ./install-service.sh
fi

say "Done"
cat <<TXT
Next:
  ./doctor.py                      check that everything is in place (venv/bin/python doctor.py)
  ./install-service.sh             run Daemon in the background and at login (or: ./setup.sh --service)
  Open http://127.0.0.1:8000       the dashboard
Settings to revisit on a new computer (MIGRATION.md has the details):
  notify.base_url, phone.public_url  new Tailscale address, and the Twilio incoming-call webhook
  wake.input_device                  microphone name can differ
  stt.device                         "cuda" only if this computer has an NVIDIA GPU
TXT
