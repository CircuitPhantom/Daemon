# Phone calls (Twilio)

Two separate features, both through [Twilio](https://www.twilio.com):

1. **Daemon calls you** and reads a message aloud: "call me when the build is done", the morning plan, urgent task results. Simple, needs no public address.
2. **You talk with Daemon on a call** (it answers, or it rings you and you talk). Needs a public HTTPS address for Twilio's webhook.

Calls cost money (Twilio number rental plus per-minute rates). A safety limit (`notify.twilio_max_per_hour`, default 6) stops runaway costs. A Twilio **trial** account can only call numbers you have verified in the Twilio console.

## Set up outgoing calls
1. Create a Twilio account, buy a voice-capable phone number (or use the trial number).
2. From the Twilio console dashboard copy the **Account SID** and **Auth Token**.
3. In `.env`:
   ```
   DAEMON_NOTIFY_TWILIO_SID=AC...
   DAEMON_NOTIFY_TWILIO_TOKEN=...
   DAEMON_NOTIFY_TWILIO_FROM=+15551234567     # your Twilio number
   DAEMON_NOTIFY_TWILIO_TO=+905551112233      # your own phone
   ```
   Optional in `config.yaml` under `notify:`: `twilio_language` (e.g. `tr-TR`), `twilio_voice`, `twilio_ring_seconds`, `twilio_reminders` (also ring for reminders).
4. Enable the `call_me` tool (Settings > Tools, *Assistant* profile has it) and say "call me". Or use it from [scheduled tasks](tasks.md): a task whose answer ends with `[CALL]` rings you.

## Talk on the phone
Pickup flow: Twilio streams your voice to a small web app of Daemon (its own port, only `/phone/*`); speech is transcribed with Whisper, answered by the active chat (tools work), and spoken with Kokoro. Talking over the reply interrupts it.

1. Complete the steps above, plus a public HTTPS address for port 8001 only. With Tailscale:
   ```bash
   sudo tailscale funnel --bg --https=8443 8001
   ```
   gives `https://NAME.tailnet.ts.net:8443`. (Funnel must be allowed for your tailnet in the Tailscale admin console.)
2. `config.yaml`:
   ```yaml
   phone:
     enabled: true
     public_url: "https://NAME.tailnet.ts.net:8443"
   ```
   and restart Daemon. `python-multipart` must be installed (it is in `requirements.txt`).
3. To **call Daemon yourself**: in the Twilio console open the number > Voice Configuration > **A call comes in** > Webhook, HTTP POST: `https://NAME.tailnet.ts.net:8443/phone/incoming`. Calls started by Daemon need no webhook.

Safety built in: the webhook needs a valid Twilio signature and must come from `twilio_to` (your number); the audio socket needs a one-time token; one call at a time; every call has a time limit (`phone.max_minutes`) and hangs up after silence (`phone.silence_seconds`). Never expose the dashboard port (8000) to the internet.

If it hears too little or too much, tune `phone.speech_level`, `noise_mult`, `min_speech_ms` and `barge_ms` (comments in `config.example.yaml`; the dashboard has sliders under Connections).
