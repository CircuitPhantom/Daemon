#!/usr/bin/env bash
# Puts the new files on the server in one go, and checks that it still works. Run it on the LAPTOP, in the folder
# where you downloaded the new files.
#
#   bash deploy.sh                      first time: asks nothing, uses --host/--dir below and remembers them
#   bash deploy.sh --host user@server-name --dir '~/daemon'
#   bash deploy.sh --dry-run            only show what would change
#   bash deploy.sh --rollback           put back the files of the last deploy and restart
#   options: --no-restart  --force (copy files that look the same, too)  --agent DIR | --agent none  -y (do not ask)
#            --include-older (also copy files that are older than the server's copy; normally they are skipped)
#
# What it does:
#   1. compares every .py / .html / .sh / requirements file here with the server (checksums), lists what is new or changed,
#      and skips a file that is OLDER than the server's copy (an old download lying in this folder) unless you say so
#   2. keeps the old versions on the server (~/daemon-backups/deploy/DATE) so --rollback works
#   3. copies only the changed files (config.yaml is never touched), checks the Python files for syntax errors
#   4. restarts the service and waits for /api/health; when the server does not come back it puts the old files back
#   5. does the same for the laptop agent files if the agent runs from a folder here (daemon-agent service)
# One password prompt only (the ssh connection is shared). Files named like "name(1).py" (a browser's copy) are skipped.
set -uo pipefail

CONF="${XDG_CONFIG_HOME:-$HOME/.config}/daemon-deploy.conf"
HOST=""; RDIR=""; AGENT=""; DRY=0; ROLLBACK=0; RESTART=1; FORCE=0; YES=0; OLDER=0
[[ -f "$CONF" ]] && source "$CONF"
while (($#)); do
  case "$1" in
    --host) shift; HOST="${1:?--host needs user@address}" ;;
    --dir) shift; RDIR="${1:?--dir needs the project folder on the server}" ;;
    --agent) shift; AGENT="${1:?--agent needs a folder or none}" ;;
    --dry-run) DRY=1 ;;
    --rollback) ROLLBACK=1 ;;
    --no-restart) RESTART=0 ;;
    --force) FORCE=1 ;;
    -y|--yes) YES=1 ;;
    --include-older) OLDER=1 ;;
    -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done
RDIR="${RDIR:-~/daemon}"
[[ -n "$HOST" ]] || { echo "give the server with --host user@address (it is remembered afterwards)" >&2; exit 2; }
PORT="${DAEMON_PORT:-8000}"

say()  { printf '\033[1m%s\033[0m\n' "$*"; }
ok()   { printf ' \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf ' \033[33m!\033[0m %s\n' "$*" >&2; }
die()  { printf ' \033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }

SOCK="/tmp/daemon-deploy-$$.sock"
SSH=(ssh -o ControlMaster=auto -o "ControlPath=$SOCK" -o ControlPersist=120 -o ConnectTimeout=10 "$HOST")
SCP=(scp -q -o "ControlPath=$SOCK" -o ControlMaster=auto -o ControlPersist=120)
cleanup() { ssh -O exit -o "ControlPath=$SOCK" "$HOST" 2>/dev/null; rm -f "$SOCK"; }
trap cleanup EXIT

remote() { "${SSH[@]}" "$@"; }
mkdir -p "$(dirname "$CONF")"
printf 'HOST=%q\nRDIR=%q\nAGENT=%q\n' "$HOST" "$RDIR" "$AGENT" > "$CONF"

say "Connecting to $HOST ($RDIR)"
remote "cd $RDIR && test -f server.py" || die "cannot reach $HOST or $RDIR/server.py does not exist (check --host / --dir)"

# ── how the service is restarted and checked ──
restart_and_check() {
  remote "systemctl --user restart daemon" || { warn "could not restart the service"; return 1; }
  local i out
  for i in $(seq 1 30); do
    out="$(remote "curl -fsS --max-time 3 http://127.0.0.1:$PORT/api/health" 2>/dev/null)" && break
    sleep 1
  done
  [[ -n "${out:-}" ]] || return 1
  echo "$out" | grep -q '"ok":true' || return 1
  if echo "$out" | grep -q '"ui_match":false'; then warn "the server is up, but index.html does not match it: $out"; fi
  ok "the server answers: $out"
  return 0
}

# ── --rollback ──
if ((ROLLBACK)); then
  last="$(remote "ls -1d ~/daemon-backups/deploy/*/ 2>/dev/null | tail -1")"
  [[ -n "$last" ]] || die "no deploy backup on the server"
  say "Putting back $last"
  remote "cd $RDIR && cp -a ${last}files/. . && if [ -f ${last}new.txt ]; then xargs -r rm -f < ${last}new.txt; fi" || die "restore failed"
  restart_and_check && ok "rolled back" || die "restored, but the server does not answer: journalctl --user -u daemon -n 40"
  exit 0
fi

# ── what is here, what is there ──
shopt -s nullglob
FILES=()
for f in *.py *.html *.sh requirements*.txt MIGRATION.md; do
  [[ -f "$f" ]] || continue
  [[ "$f" =~ ^[A-Za-z0-9._-]+$ ]] || { warn "skipping $f (odd name: a browser copy like \"name(1).py\"? delete or rename it)"; continue; }
  FILES+=("$f")
done
((${#FILES[@]})) || die "no files here. Run this in the folder with the downloaded files."
[[ -f server.py || -f index.html ]] || warn "no server.py or index.html here: only some files will be compared"

remote_sums="$(remote "cd $RDIR && sha256sum -- ${FILES[*]} 2>/dev/null")"
remote_times="$(remote "cd $RDIR && stat -c '%Y %n' -- ${FILES[*]} 2>/dev/null")"
declare -A RS RT
while read -r h n; do RS["$n"]="$h"; done <<<"$remote_sums"
while read -r t n; do RT["$n"]="$t"; done <<<"$remote_times"
NEW=(); CHANGED=(); OLDFILES=(); SAME=0
for f in "${FILES[@]}"; do
  h="$(sha256sum -- "$f" | cut -d' ' -f1)"
  if [[ -z "${RS[$f]:-}" ]]; then NEW+=("$f")
  elif [[ "${RS[$f]}" != "$h" || $FORCE == 1 ]]; then
    if [[ "${RS[$f]}" != "$h" && $OLDER == 0 && -n "${RT[$f]:-}" && "$(stat -c %Y -- "$f")" -lt "${RT[$f]}" ]]; then OLDFILES+=("$f")
    else CHANGED+=("$f"); fi
  else SAME=$((SAME + 1)); fi
done
echo
say "On the server: ${#NEW[@]} new, ${#CHANGED[@]} changed, $SAME the same"
((${#NEW[@]})) && printf '   new      %s\n' "${NEW[@]}"
((${#CHANGED[@]})) && printf '   changed  %s\n' "${CHANGED[@]}"
if ((${#OLDFILES[@]})); then
  warn "skipped, older than the server's copy (an old download? use --include-older to copy anyway):"
  printf '   old      %s\n' "${OLDFILES[@]}" >&2
fi
TODO=("${NEW[@]}" "${CHANGED[@]}")
if ((${#TODO[@]} && !DRY && !YES)); then
  read -r -p "Copy ${#TODO[@]} file(s) and restart the server? [Y/n] " a
  [[ -z "$a" || "$a" =~ ^[Yy] ]] || die "cancelled"
fi

deploy_server() {
  ((${#TODO[@]})) || { ok "the server already has everything"; return 0; }
  ((DRY)) && { echo "   (dry run: nothing copied)"; return 0; }
  local stamp bk
  stamp="$(date +%Y%m%d-%H%M%S)"; bk="~/daemon-backups/deploy/$stamp"
  remote "mkdir -p $bk/files && cd $RDIR && for f in ${CHANGED[*]:-}; do cp -a -- \"\$f\" $bk/files/; done; printf '%s\n' ${NEW[*]:-} > $bk/new.txt" \
    || die "could not make the backup of the old files on the server"
  ok "old versions kept in $bk"
  "${SCP[@]}" "${TODO[@]}" "$HOST:$RDIR/" || die "copy failed"
  ok "copied ${#TODO[@]} file(s)"
  local pys=(); for f in "${TODO[@]}"; do [[ "$f" == *.py ]] && pys+=("$f"); done
  if ((${#pys[@]})); then
    if ! remote "cd $RDIR && PY=\$(ls venv/bin/python .venv/bin/python 2>/dev/null | head -1); PY=\${PY:-python3}; \$PY -m py_compile ${pys[*]}"; then
      warn "a Python file has a syntax error: putting the old files back"
      remote "cd $RDIR && cp -a $bk/files/. . 2>/dev/null; xargs -r rm -f < $bk/new.txt"
      die "nothing was changed on the server"
    fi
    ok "Python files compile"
  fi
  if ((RESTART)); then
    if restart_and_check; then
      ok "done"
    else
      warn "the server did not come back: putting the old files back"
      remote "cd $RDIR && cp -a $bk/files/. . 2>/dev/null; xargs -r rm -f < $bk/new.txt"
      restart_and_check && warn "the old version runs again" || warn "still not answering"
      remote "journalctl --user -u daemon -n 25 --no-pager" || true
      die "deploy failed (rolled back)"
    fi
  else
    warn "not restarted (--no-restart): systemctl --user restart daemon"
  fi
}
deploy_server

# ── the laptop agent ──
if [[ "$AGENT" != "none" ]]; then
  if [[ -z "$AGENT" ]] && command -v systemctl >/dev/null; then
    AGENT="$(systemctl --user cat daemon-agent.service 2>/dev/null | sed -n 's/^WorkingDirectory=//p' | head -1)"
  fi
  if [[ -n "$AGENT" && -d "$AGENT" && "$(cd "$AGENT" && pwd)" != "$(pwd)" ]]; then
    echo
    say "Laptop agent ($AGENT)"
    ch=()
    for f in daemon-agent.py tools.py wakeword.py screeninput.py requirements-agent.txt; do
      [[ -f "$f" ]] || continue
      cmp -s "$f" "$AGENT/$f" || ch+=("$f")
    done
    if ((${#ch[@]} == 0)); then ok "up to date"
    elif ((DRY)); then printf '   would update  %s\n' "${ch[@]}"
    else
      cp -a "${ch[@]}" "$AGENT/" && ok "updated: ${ch[*]}"
      if systemctl --user is-enabled daemon-agent.service >/dev/null 2>&1; then
        systemctl --user restart daemon-agent.service && ok "agent restarted" || warn "could not restart the agent"
      else
        warn "restart the agent yourself (it does not run as the daemon-agent service)"
      fi
    fi
  elif [[ -n "$AGENT" && -d "$AGENT" ]]; then            # the agent runs from this very folder: its files are already in place
    for f in "${TODO[@]}"; do
      case "$f" in daemon-agent.py|tools.py|wakeword.py|screeninput.py) restart_agent=1 ;; esac
    done
    if ((${restart_agent:-0} && !DRY)); then
      echo
      say "Laptop agent ($AGENT, this folder)"
      if systemctl --user is-enabled daemon-agent.service >/dev/null 2>&1; then
        systemctl --user restart daemon-agent.service && ok "agent restarted" || warn "could not restart the agent"
      else
        warn "agent files changed: restart the agent yourself (it does not run as the daemon-agent service)"
      fi
    fi
  elif ((${#TODO[@]})) && [[ -z "$AGENT" ]]; then
    echo
    echo "   (laptop agent folder not found: pass --agent DIR once, e.g. --agent ~/daemon-agent; or --agent none)"
  fi
fi
echo
ok "finished. Undo with: bash deploy.sh --rollback"
