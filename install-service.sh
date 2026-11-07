#!/usr/bin/env bash
# Installs Daemon as a systemd *user* service, so it starts with your session and restarts if it crashes.
# A user service (not a system one) is needed: audio (PipeWire), the clipboard, playerctl and open_app
# all live in your desktop session.
#
#   ./install-service.sh            install (or update) and start
#   ./install-service.sh --print    only show the unit file
#   ./install-service.sh --remove   stop and remove
#
# Put this file next to server.py (the webserver folder) and run it from anywhere, without sudo.
set -euo pipefail

NAME=daemon
PORT="${DAEMON_PORT:-8000}"
WEB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT="$UNIT_DIR/$NAME.service"

die() { echo "error: $*" >&2; exit 1; }

if [[ "${1:-}" == "--remove" ]]; then
  systemctl --user disable --now "$NAME.service" 2>/dev/null || true
  rm -f "$UNIT"
  systemctl --user daemon-reload
  echo "Removed $UNIT"
  exit 0
fi

[[ -f "$WEB_DIR/server.py" ]] || die "server.py not found in $WEB_DIR. Put this script next to server.py."

# The project root holds model_config.py / tools.py (they used to be reached with PYTHONPATH=..)
if [[ -f "$WEB_DIR/model_config.py" ]]; then PROJECT_DIR="$WEB_DIR"
elif [[ -f "$WEB_DIR/../model_config.py" ]]; then PROJECT_DIR="$(cd "$WEB_DIR/.." && pwd)"
else die "model_config.py not found in $WEB_DIR or its parent folder."; fi

# Find the virtualenv: the active one first, then the usual folder names
PY=""
for cand in "${VIRTUAL_ENV:-}" "$WEB_DIR/venv" "$WEB_DIR/.venv" "$PROJECT_DIR/venv" "$PROJECT_DIR/.venv"; do
  if [[ -n "$cand" && -x "$cand/bin/python" ]]; then PY="$cand/bin/python"; break; fi
done
[[ -n "$PY" ]] || die "no virtualenv found. Activate it (source venv/bin/activate) and run this script again."
"$PY" -c "import uvicorn, fastapi" 2>/dev/null || die "uvicorn/fastapi are not installed in $PY"

PYTHONPATH_VALUE="$PROJECT_DIR"
[[ "$PROJECT_DIR" != "$WEB_DIR" ]] && PYTHONPATH_VALUE="$WEB_DIR:$PROJECT_DIR"

read -r -d '' CONTENT <<UNIT || true
[Unit]
Description=Daemon voice assistant (web UI on port $PORT)
After=network-online.target pipewire.service pipewire-pulse.service
Wants=network-online.target
# keep a crash loop from hammering the machine
StartLimitIntervalSec=120
StartLimitBurst=5

[Service]
Type=simple
WorkingDirectory=$WEB_DIR
Environment="PYTHONPATH=$PYTHONPATH_VALUE"
Environment=PYTHONUNBUFFERED=1
ExecStart="$PY" -m uvicorn server:app --host 127.0.0.1 --port $PORT
Restart=on-failure
RestartSec=5
TimeoutStopSec=20

[Install]
WantedBy=default.target
UNIT

if [[ "${1:-}" == "--print" ]]; then
  echo "$CONTENT"
  exit 0
fi

mkdir -p "$UNIT_DIR"
printf '%s\n' "$CONTENT" > "$UNIT"
echo "Wrote $UNIT"

# Desktop tools (open_app, clipboard) need these variables inside the service.
# Most desktops (GNOME, KDE) pass them automatically; this covers the rest for the current session.
vars=()
for v in DISPLAY WAYLAND_DISPLAY XDG_CURRENT_DESKTOP XDG_SESSION_TYPE DBUS_SESSION_BUS_ADDRESS; do
  [[ -n "${!v:-}" ]] && vars+=("$v")
done
if (( ${#vars[@]} )); then
  systemctl --user import-environment "${vars[@]}" || true
fi

systemctl --user daemon-reload
systemctl --user enable "$NAME.service" >/dev/null
systemctl --user restart "$NAME.service"
sleep 2
if systemctl --user is-active --quiet "$NAME.service"; then
  echo "Daemon is running on http://127.0.0.1:$PORT"
else
  echo "The service did not start. Last log lines:"
  journalctl --user -u "$NAME.service" -n 30 --no-pager || true
  exit 1
fi
cat <<TIP

Useful commands:
  journalctl --user -u $NAME -f          live log (what used to print in the terminal)
  systemctl --user restart $NAME         after updating the files
  systemctl --user stop $NAME            stop it
  loginctl enable-linger \$USER           optional: also run while you are logged out
                                         (tasks and reminders work then; desktop tools do not)
TIP
