# Signal

With Signal set up you can chat with Daemon from your phone, send it photos, voice messages and files, and it can message you: reminders, task results, alerts, the morning plan. Only the numbers in `signal.allowed` are answered.

## What you need
- **A phone number for the bot** that can receive one SMS or voice call for registration. It is a Signal account of its own: *not* your personal Signal account, and not a "linked device" of it. A cheap prepaid SIM, a VoIP/Twilio number, or a spare number works.
- **Your own number** (the one you will write from), in international format.
- On the Daemon machine: **Java** and **signal-cli**.

> A number can only be a Signal account in one place. If you register your personal number for the bot, your phone's Signal stops working. Use a separate number for the bot.

## Install signal-cli
- Debian/Ubuntu: `sudo apt install default-jre-headless`, then download signal-cli from <https://github.com/AsamK/signal-cli/releases>, unpack it and put `bin/signal-cli` in your `PATH` (for example `/usr/local/bin`).
- Check: `signal-cli --version`.

## Register the bot number
```bash
signal-cli -a +15551234567 register
```
If Signal answers with a captcha error, open <https://signalcaptchas.org/registration/generate.html>, solve it, copy the `signalcaptcha://...` link (right-click "Open Signal" > copy link) and run:
```bash
signal-cli -a +15551234567 register --captcha 'signalcaptcha://...'
```
You get a code by SMS (add `--voice` for a call). Verify:
```bash
signal-cli -a +15551234567 verify 123-456
signal-cli listAccounts                      # the number should be listed
```
Too many attempts give a 429 rate limit; wait a while.

## Turn it on
`config.yaml`:
```yaml
signal:
  enabled: true
  account: "+15551234567"      # the bot's number (or DAEMON_SIGNAL_ACCOUNT in .env)
  allowed: "+15551112233"     # who may talk to Daemon: your number, comma separated (or DAEMON_SIGNAL_ALLOWED)
```
Keep the quotes around numbers. Restart Daemon (`systemctl --user restart daemon`), then message the bot number from your own Signal. Daemon starts and supervises `signal-cli jsonRpc` itself, no extra service.

`doctor.py` checks signal-cli, the account and the allowed list.

## What you can send
Plain messages go to the active chat, the same one the dashboard shows. Photos, PDFs and voice messages work too (voice is transcribed). Commands:
```
/new                 start a new chat
/inbox <text>        save a note or link (attach a photo or file to keep it too); alone: latest items
/find <words>        search the inbox
/screen              picture of the laptop screen (asks for your OK first)
/job <what to do>    long background task; result comes back here (/jobs, /job <id>, /cancel <id>)
/status              health of the server, laptop agent, backup, Tailscale
/memory, /forget <id>  what Daemon remembers; remove one
/help
```
"yes" / "no" answers a tool that waits for your approval.

## Safety
- Messages from allowed numbers can use every tool your chat can, including `execute_command` if it is enabled (it still asks for approval). Keep `allowed` short and protect your phone.
- Everyone else is ignored silently.
- Messages older than `signal.max_age` seconds (default 600), sent while Daemon was off, are ignored.

## Moving the bot to another computer
Copy `~/.local/share/signal-cli` (`./backup.sh --with-signal` does it) and stop signal-cli on the old machine. Running one account in two places breaks the session keys ("untrusted identity" errors). See [MIGRATION.md](../MIGRATION.md).

## Problems
| Symptom | Cause |
|---|---|
| No reply | The sender is not in `allowed`; `signal.enabled` is false; Daemon not restarted; check `journalctl --user -u daemon` |
| `signal-cli not found` | Not in the `PATH` of the service. Set `signal.cli` to the full path |
| `decryption error` / `untrusted identity` | The account runs in two places, or the data was copied while signal-cli was running |
| Registration fails with 429 / captcha | Wait, solve a fresh captcha |
