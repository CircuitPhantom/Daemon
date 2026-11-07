# Scheduled tasks, routines and jobs

## Scheduled tasks
A task is a prompt that Daemon runs on a schedule with its own tool list, and reports on Signal. Examples: a morning news summary, a weekly disk check, "is my website up".

Create them in the dashboard (Tasks drawer) or edit `tasks.yaml` by hand (the server picks changes up automatically):
```yaml
- name: Morning news
  prompt: Search the web for the three most important technology news today and summarize them in 4 sentences.
  cron: "30 7 * * 1-5"          # minute hour day month weekday: 07:30 on weekdays
  tools: [web_search, fetch_url]
  notify: always                 # always | unless_quiet | off
  enabled: true
```
- `cron` is the standard 5-field format (lists, ranges, steps, month/day names, `@daily`, `@hourly`...). Times use `notify.timezone`.
- The result is stored in `runs/` and sent to you on [Signal](signal.md) (long ones as a file).
- If the answer ends with `[CALL]`, Daemon also rings you ([phone calls](phone-calls.md)). `[QUIET]` means "nothing to report, stay silent".
- Tasks never get tools that need your approval (`execute_command`, `write_file`, `computer`...) and never use the chat memory.

## Background jobs
`/job compare the three best USB-C hubs under 30 USD` on Signal (or "research this and tell me later" in chat) starts a longer task in the background. Details in [FEATURES.md](../FEATURES.md#2-background-jobs).

## Reminders and the morning plan
- "Remind me at 18:00 to call mom" > `remind_me`; you get a Signal message at that time.
- **Calendar** events (dashboard or by asking) can send a daily plan at `calendar.briefing_time`, optionally with a phone call that reads it aloud.
- **Care** (`care:` in `config.yaml`, Settings > Automation): Signal alerts when the disk is nearly full, the backup is old, Tailscale or the laptop agent is down, plus a weekly check for duplicate or very old memories.
