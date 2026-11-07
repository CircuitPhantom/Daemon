#!/usr/bin/env bash
# Packs everything that is *yours* (settings, calendar, chats, memory, logins) into one archive, to move Daemon
# to another computer or to keep a backup. The code itself is not needed in it, copy the project folder separately.
#
#   ./backup.sh                          settings, tasks, calendar, memory, reminders, chats, Spotify login
#   ./backup.sh --with-signal            ...and the Signal account (signal-cli data), so Signal works on the new computer
#   ./backup.sh --with-signal --stop     same, and stop the Daemon service first (needed so Signal data is not changing)
#   ./backup.sh --out /path/file.tar.gz  where to write it (default: ~/daemon-backup-DATE.tar.gz)
#   ./backup.sh --project DIR            back up the Daemon folder DIR instead of the one this script is in
#   ./backup.sh --with-files             ...and the Daemon folder (~/Documents/Daemon: files you sent, notes it wrote)
#   ./backup.sh --dir DIR --keep 14      write DIR/daemon-backup-DATE.tar.gz and keep only the newest 14 there
#   ./backup.sh --install-timer          daily automatic backup (systemd user timer): ~/daemon-backups, newest 14 kept,
#                                        with the Daemon folder, without the Signal account (it is in use while running)
#   ./backup.sh --remove-timer           turn the daily backup off
#
# The archive holds your API keys and the Signal login: it is created private (mode 600). Move it with scp or a USB
# stick, never through a chat or cloud storage, and delete it when you are done.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIGNAL_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/signal-cli"
OUT=""
DIR=""
KEEP=0
WITH_SIGNAL=0; STOP=0; WITH_FILES=0
FILES_DIR="${DAEMON_FILES:-$HOME/Documents/Daemon}"

while (($#)); do
  case "$1" in
    --with-signal) WITH_SIGNAL=1 ;;
    --stop) STOP=1 ;;
    --project) shift; HERE="$(cd "${1:?--project needs a folder}" && pwd)" ;;
    --out) shift; OUT="${1:?--out needs a file name}" ;;
    --dir) shift; DIR="${1:?--dir needs a folder}" ;;
    --keep) shift; KEEP="${1:?--keep needs a number}"; [[ "$KEEP" =~ ^[0-9]+$ ]] || { echo "--keep needs a number" >&2; exit 2; } ;;
    --with-files) WITH_FILES=1 ;;
    --install-timer) INSTALL_TIMER=1 ;;
    --remove-timer) REMOVE_TIMER=1 ;;
    -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
if [[ -n "${REMOVE_TIMER:-}" ]]; then
  systemctl --user disable --now daemon-backup.timer 2>/dev/null || true
  rm -f "$UNIT_DIR/daemon-backup.timer" "$UNIT_DIR/daemon-backup.service"
  systemctl --user daemon-reload
  echo "Daily backup is off (old backups stay in ~/daemon-backups)."
  exit 0
fi
if [[ -n "${INSTALL_TIMER:-}" ]]; then
  mkdir -p "$UNIT_DIR"
  cat > "$UNIT_DIR/daemon-backup.service" <<UNIT
[Unit]
Description=Daemon daily backup

[Service]
Type=oneshot
Nice=10
IOSchedulingClass=idle
ExecStart=/usr/bin/env bash "$HERE/backup.sh" --project "$HERE" --dir "$HOME/daemon-backups" --keep 14 --with-files
UNIT
  cat > "$UNIT_DIR/daemon-backup.timer" <<UNIT
[Unit]
Description=Daemon daily backup

[Timer]
OnCalendar=*-*-* 04:17
RandomizedDelaySec=10min
Persistent=true

[Install]
WantedBy=timers.target
UNIT
  systemctl --user daemon-reload
  systemctl --user enable --now daemon-backup.timer
  echo "Daily backup is on: every night around 04:17 into ~/daemon-backups (the newest 14 are kept)."
  echo "  run one now:   systemctl --user start daemon-backup"
  echo "  last result:   journalctl --user -u daemon-backup -n 20"
  echo "  next run:      systemctl --user list-timers daemon-backup.timer"
  echo "Tip: loginctl enable-linger \$USER  lets it run while you are logged out."
  exit 0
fi

if [[ -z "$OUT" ]]; then
  OUT="${DIR:-$HOME}/daemon-backup-$(date +%Y%m%d-%H%M%S).tar.gz"
fi

for v in DAEMON_CONFIG DAEMON_CHATS DAEMON_MEMORY DAEMON_REMINDERS DAEMON_CALENDAR DAEMON_INBOX DAEMON_TOOL_LOG; do
  [[ -n "${!v:-}" ]] && echo "warning: $v is set ($(printf %s "${!v}")): files outside the project folder are not included"
done

if systemctl --user is-active --quiet daemon.service 2>/dev/null; then
  if ((STOP)); then
    systemctl --user stop daemon.service
    echo "Stopped the daemon service (start it again with: systemctl --user start daemon). On the new computer start only one copy."
  elif ((WITH_SIGNAL)); then
    echo "The daemon service is running and uses the Signal data. Stop it first or add --stop:" >&2
    echo "  systemctl --user stop daemon" >&2
    exit 1
  fi
fi

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/project"

copied=()
for f in config.yaml .env tasks.yaml calendar.json memory.json reminders.json inbox.json tool_log.jsonl spotify_token.json tts_usage.json; do
  [[ -f "$HERE/$f" ]] && cp -a "$HERE/$f" "$STAGE/project/" && copied+=("$f")
done
for d in chats runs static/lib; do
  if [[ -d "$HERE/$d" ]]; then
    mkdir -p "$STAGE/project/$(dirname "$d")"
    cp -a "$HERE/$d" "$STAGE/project/$d"
    copied+=("$d/")
  fi
done

# exact package versions of this machine, for a repeatable install
for cand in "${VIRTUAL_ENV:-}" "$HERE/venv" "$HERE/.venv"; do
  if [[ -n "$cand" && -x "$cand/bin/python" ]]; then
    "$cand/bin/python" -m pip freeze > "$STAGE/project/requirements.lock" 2>/dev/null && copied+=("requirements.lock") || true
    break
  fi
done

if ((WITH_FILES)); then
  if [[ -d "$FILES_DIR" ]]; then
    cp -a "$FILES_DIR" "$STAGE/daemon-files"
    copied+=("Daemon folder ($FILES_DIR)")
  else
    echo "note: no Daemon folder at $FILES_DIR, skipped"
  fi
fi

if ((WITH_SIGNAL)); then
  if [[ -d "$SIGNAL_DIR" ]]; then
    cp -a "$SIGNAL_DIR" "$STAGE/signal-cli"
    rm -rf "$STAGE/signal-cli/attachments" "$STAGE/signal-cli/avatars" "$STAGE/signal-cli/stickers"
    copied+=("signal-cli account")
  else
    echo "warning: no Signal data in $SIGNAL_DIR, skipped" >&2
  fi
fi

{
  echo "Daemon backup"
  echo "date:     $(date -Is)"
  echo "host:     $(hostname)"
  echo "python:   $(python3 --version 2>&1)"
  echo "signal:   $(command -v signal-cli >/dev/null && signal-cli --version 2>&1 | head -1 || echo not installed)"
  echo "contents: ${copied[*]}"
} > "$STAGE/MANIFEST.txt"

umask 077
mkdir -p "$(dirname "$OUT")"
tar -C "$STAGE" -czf "$OUT" .
chmod 600 "$OUT"

if ((KEEP)) && [[ -n "$DIR" ]]; then                  # rotation: only the newest KEEP backups in DIR
  mapfile -t old < <(ls -1t "$DIR"/daemon-backup-*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)))
  ((${#old[@]})) && rm -f -- "${old[@]}" && echo "Removed ${#old[@]} old backup(s) from $DIR"
fi

echo
echo "Wrote $OUT ($(du -h "$OUT" | cut -f1))"
echo "Contains: ${copied[*]}"
((WITH_SIGNAL)) || echo "Signal account not included (add --with-signal if the new computer should keep the same Signal login)."
if ((WITH_SIGNAL)); then secrets="API keys and the Signal login"; else secrets="API keys"; fi
echo "It holds secrets ($secrets): copy it with scp or a USB stick and delete it afterwards."
