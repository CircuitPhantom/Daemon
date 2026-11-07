#!/usr/bin/env python3
"""Run on the SERVER once: turns on the laptop agent link and prints the command for the laptop.

  python satellite_setup.py            enable (keeps the token if there is one)
  python satellite_setup.py --new      make a new token (the laptop must be given the new one)
  python satellite_setup.py --off      disable (the server uses its own microphone/tools again)
"""
import secrets
import sys

import model_config

c = model_config.satellite
if "--off" in sys.argv:
    c["enabled"] = False
    model_config.save()
    print("Laptop agent link is off. This computer uses its own microphone and desktop tools again.")
    sys.exit(0)
if "--new" in sys.argv or len(c["token"]) < 16:
    c["token"] = secrets.token_urlsafe(32)
c["enabled"] = True
model_config.save()
print("Laptop agent link is on (config.yaml -> satellite). Restart the server: systemctl --user restart daemon")
print()
print("On the laptop run (use your server's Tailscale name):")
print(f"  python daemon-agent.py --server http://SERVER:8000 --token {c['token']}")
print("or put them in ~/.config/daemon-agent.json:")
print('  {"server": "http://SERVER:8000", "token": "%s"}' % c["token"])
print()
print("The token is a password for your laptop: do not share it.")
