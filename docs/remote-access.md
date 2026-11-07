# Remote access and the phone app

By default Daemon listens on `127.0.0.1:8000`: only the computer it runs on can open it. To use it from your phone or from another computer **do not** open the port to the internet. Use [Tailscale](https://tailscale.com) (a private network between your own devices; free for personal use).

## 1. Tailscale on the Daemon machine and your phone
1. Install Tailscale on the Daemon machine (<https://tailscale.com/download>) and run `sudo tailscale up`. Install the Tailscale app on your phone and log in with the same account.
2. In the Tailscale admin console > **DNS**: make sure **MagicDNS** is on and **HTTPS Certificates** is enabled (needed for the next step and for installing the app).

## 2. Publish the dashboard inside your tailnet
```bash
sudo tailscale serve --bg --https=443 http://127.0.0.1:8000
tailscale serve status
```
Now `https://NAME.tailnet.ts.net` opens the dashboard on every device of your tailnet, and only on those. (`NAME` is the machine name shown by `tailscale status`.) Turn it off with `sudo tailscale serve reset`.

**Set a PIN** (`venv/bin/python set_pin.py`) so a lost or shared device cannot use your assistant.

## 3. Install it as an app on Android
Open the address in Chrome > menu > **Install app** (the option only appears over HTTPS, which is why step 2 is needed). Daemon then has its own icon and window, and shows up in the **Share menu**: share a link, text, photo or file from any app and it lands in your inbox (tag `#shared`). On iPhone, use Safari > Share > Add to Home Screen; the Share-menu integration is Android/Chrome only.

## What else uses the address
- The [laptop agent](laptop-agent.md) connects to it (`--server https://NAME.tailnet.ts.net`).
- `notify.base_url` in `config.yaml`: the address put in links that Daemon sends you (Signal messages that open the dashboard).
- [Phone calls](phone-calls.md) need a *public* address for a separate port (Tailscale Funnel). That is the only thing that should be exposed, never the dashboard.

## Without Tailscale
Any reverse proxy with TLS and authentication in front of `127.0.0.1:8000` works (Caddy, nginx), but then the PIN is the only protection. Daemon can run commands for a language model, so prefer a private network.
