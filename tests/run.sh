#!/usr/bin/env bash
# Runs the test scripts in a scratch copy (they write state files next to themselves).
#   tests/run.sh              all tests
#   tests/run.sh tjobs tllm   only these
# Needs: python3 with the requirements installed (the speech / LLM parts are stubbed), node for the PWA service worker test.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
cp "$ROOT"/*.py "$ROOT"/index.html "$WORK"/
cp -a "$HERE"/. "$WORK"/ && rm -f "$WORK/run.sh"
cd "$WORK" || exit 1
tests=("$@"); [[ ${#tests[@]} -eq 0 ]] && mapfile -t tests < <(ls t*.py | sed 's/\.py$//' | sort)
pass=0; fail=()
for t in "${tests[@]}"; do
  out="$(timeout 300 python3 "$t.py" 2>&1)"; rc=$?
  if [[ $rc -eq 0 ]]; then pass=$((pass+1)); echo "ok    $t"; else fail+=("$t"); echo "FAIL  $t: $(echo "$out" | tail -2 | tr '\n' ' ' | cut -c1-160)"; fi
done
echo; echo "$pass passed, ${#fail[@]} failed"
[[ ${#fail[@]} -eq 0 ]]
