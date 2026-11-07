# Security

Daemon lets a language model run commands, read files and (optionally) control the mouse and keyboard. Read the *Security notes* in the README before exposing it to anything but yourself.

**Report a vulnerability privately** through GitHub's "Report a vulnerability" button (Security tab) instead of a public issue. Please include what you found, how to reproduce it and which setup it affects.

Never post your `config.yaml`, `.env`, `spotify_token.json`, signal-cli data or a backup archive anywhere. If one of them leaked, rotate the keys (LLM provider, Twilio, Spotify, ElevenLabs), run `satellite_setup.py --new` and re-register the Signal number.
