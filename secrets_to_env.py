#!/usr/bin/env python3
"""Moves the keys, tokens, secrets, phone numbers and account ids of config.yaml into .env and leaves ${NAME} behind.

  python secrets_to_env.py            show what would move
  python secrets_to_env.py --apply    do it (config.yaml is saved as config.yaml.before-env first)

llm.api_key becomes  api_key: ${DAEMON_LLM_API_KEY}  and  DAEMON_LLM_API_KEY=... goes into .env (mode 600).
Moved: every key / token / secret / password, notify.twilio_sid / twilio_from / twilio_to (phone numbers), spotify.client_id,
signal.account and signal.allowed.
The auth section (PIN hash, cookie secret) stays where it is: Daemon writes it itself.
"""
import os
import re
import shutil
import sys
from pathlib import Path

import model_config as mc



def find(lines):
    """[(line index, section, field, value text)] for the secret fields that still hold a value."""
    out, section = [], ""
    for i, ln in enumerate(lines):
        m = re.match(r"^([A-Za-z_][\w]*):\s*(#.*)?$", ln)
        if m:
            section = m.group(1)
            continue
        if re.match(r"^\S", ln):
            section = ""
            continue
        m = re.match(r"^(  )([A-Za-z_]\w*):[ \t]+(.+?)\s*$", ln)
        if section and m and mc.is_private_field(section, m.group(2)):
            val = m.group(3)
            if val[:1] in "\"'" and len(val) >= 2 and val[-1] == val[0]:
                val = val[1:-1]
            if val and "${" not in val and val not in ("''", '""', "null", "~"):
                out.append((i, section, m.group(2), val))
    return out


def main():
    apply = "--apply" in sys.argv
    path = mc.CONFIG_PATH
    lines = path.read_text(encoding="utf-8").splitlines()
    found = find(lines)
    if not found:
        print("nothing to move: no key or token with a value in", path.name)
        return 0
    env_text = mc.ENV_PATH.read_text(encoding="utf-8") if mc.ENV_PATH.exists() else ""
    have = mc._parse_env(env_text)
    add = []
    for i, section, field, val in found:
        name = f"DAEMON_{section}_{field}".upper()
        print(f"  {section}.{field}  ->  ${{{name}}}" + ("   (already in .env, kept)" if name in have else ""))
        if name not in have:
            add.append(f'{name}="{val}"' if re.search(r"[\s#\"']", val) else f"{name}={val}")
        lines[i] = re.sub(r":[ \t]+.+$", f": ${{{name}}}", lines[i])
    if not apply:
        print(f"\n{len(found)} value(s) would move to {mc.ENV_PATH}. Run again with --apply.")
        return 0
    shutil.copy2(path, path.with_name(path.name + ".before-env"))
    if add:
        mc.atomic_write(mc.ENV_PATH, (env_text.rstrip("\n") + "\n" if env_text.strip() else "# Daemon secrets. Keep this file private (chmod 600).\n") + "\n".join(add) + "\n")
    os.chmod(mc.ENV_PATH, 0o600)
    mc.atomic_write(path, "\n".join(lines) + "\n")
    print(f"\nmoved {len(found)} value(s). Old config.yaml: {path.name}.before-env (delete it when everything works: it still holds the keys).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
