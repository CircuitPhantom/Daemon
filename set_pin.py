#!/usr/bin/env python3
"""Sets the dashboard PIN from the terminal and turns the PIN lock on.

  python set_pin.py            ask for a new PIN
  python set_pin.py --off      turn the lock off (same as auth.enabled: false in config.yaml)

Run it in the folder with config.yaml (or set DAEMON_CONFIG). Restart is not needed, the server notices.
"""
import getpass
import sys

import auth

if "--off" in sys.argv:
    auth.disable()
    print("PIN lock is off.")
    sys.exit(0)
try:
    a = getpass.getpass(f"New PIN ({auth.MIN_PIN}+ characters): ")
    if a != getpass.getpass("Again: "):
        sys.exit("The two PINs differ, nothing changed.")
    auth.set_pin(a)
except ValueError as e:
    sys.exit(f"Error: {e}")
print("PIN lock is on. Everyone has to log in again.")
