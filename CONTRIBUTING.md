# Contributing

Issues and pull requests are welcome.

- **Tests:** every feature has a plain script in `tests/` (`ok(condition, message)` helper, stubs for the LLM and speech libraries). Run `tests/run.sh` (needs python3, node and ffmpeg); add a `tests/t<name>.py` for what you change. CI runs the same on Python 3.10 and 3.12.
- **Adding a tool:** write a function in `tools.py` (type hints + a docstring with an `Args:` section: that is what the model sees), register it in `available_functions`, add it to a profile in `model_config.py`, and mention it in the table in `FEATURES.md`. Keep docstrings short: a test bounds the total size of the tool schemas.
- **Risky tools** (anything that writes, sends, or controls the machine) go in `security.confirm_tools` and must not be available to scheduled tasks or background jobs.
- **Settings:** a new option goes in `DEFAULTS` in `model_config.py`, with a comment; regenerate `config.example.yaml` from the defaults. Secrets must work through `.env` (`DAEMON_<SECTION>_<FIELD>`).
- **Language:** code, comments and UI text in English.
