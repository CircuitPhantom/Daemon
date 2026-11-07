"""Daemon as an app on your phone: the web app manifest, a tiny service worker and the icons.

What it gives you (Android Chrome, the page opened over HTTPS - see below):
  * "Install app" in the browser menu: Daemon gets its own icon and window.
  * Daemon appears in the phone's Share menu. Share a link, text, photo or file from any app and it lands in the inbox
    (the same inbox as /inbox on Signal). The service worker below receives the share and hands it to /api/inbox.

HTTPS is required by the browser for all of this. With Tailscale:   tailscale serve --bg --https=443 http://127.0.0.1:8000
and open  https://<machine>.<tailnet>.ts.net  on the phone (a plain http://100.x.x.x address cannot be installed).
iOS has no share targets: use a Shortcut that POSTs to /api/sat/inbox with the laptop agent token (see server.py).
"""
import json
import struct
import zlib

THEME = "#18181b"
ACCENT = (74, 124, 243)
_icons = {}


def manifest():
    return {
        "name": "Daemon", "short_name": "Daemon", "description": "Your voice and chat assistant",
        "start_url": "/", "scope": "/", "display": "standalone", "orientation": "any",
        "background_color": THEME, "theme_color": THEME,
        "icons": [{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
                  {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
                  {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}],
        "share_target": {
            "action": "/share", "method": "POST", "enctype": "multipart/form-data",
            "params": {"title": "title", "text": "text", "url": "url",
                       "files": [{"name": "files", "accept": ["image/*", "video/*", "audio/*", "text/*", "application/*"]}]},
        },
    }


def manifest_json():
    return json.dumps(manifest(), indent=1)


SW = r"""// Daemon service worker: receives what you share to Daemon and saves it in the inbox. No caching.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));

function b64(buf) {
  const bytes = new Uint8Array(buf);
  let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

async function handleShare(req) {
  try {
    const fd = await req.formData();
    const files = [];
    for (const f of fd.getAll('files')) {
      if (f && f.size) files.push({ name: f.name || 'shared', data: b64(await f.arrayBuffer()) });
    }
    const title = String(fd.get('title') || '').trim(), text = String(fd.get('text') || '').trim(), url = String(fd.get('url') || '').trim();
    const parts = [title && title !== text ? title : '', text, url && !text.includes(url) ? url : ''].filter(Boolean);
    const r = await fetch('/api/inbox', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
                                          body: JSON.stringify({ text: parts.join('\n'), files, tags: ['shared'] }) });
    return Response.redirect('/?shared=' + (r.ok ? 'ok' : r.status === 401 ? 'locked' : 'fail'), 303);
  } catch (err) {
    return Response.redirect('/?shared=fail', 303);
  }
}

self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  if (e.request.method === 'POST' && u.pathname === '/share') e.respondWith(handleShare(e.request));
});
"""

SHARE_FALLBACK = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Daemon</title><style>body{margin:0;min-height:100dvh;display:flex;align-items:center;justify-content:center;background:#0e0e11;color:#e8e8ec;
font:15px system-ui,sans-serif;padding:24px;text-align:center}a{color:#7aa2ff}</style></head><body><div>
<p>The share helper is not active yet.</p><p><a href="/">Open Daemon</a> once, then share again.</p></div></body></html>"""


def _png(size, rgb_at):
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            row += bytes(rgb_at(x, y))
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(kind, data):
        c = struct.pack(">I", len(data)) + kind + data
        return c + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def icon_png(size):
    """A dark square with a blue ring and a dot: simple, readable at any size. Cached."""
    size = 512 if size >= 512 else 192
    if size in _icons:
        return _icons[size]
    bg, c = (24, 24, 27), size / 2

    def px(x, y):
        d = ((x + 0.5 - c) ** 2 + (y + 0.5 - c) ** 2) ** 0.5 / size
        if 0.27 <= d <= 0.35:                                     # the ring
            return ACCENT
        if d <= 0.11:                                             # the dot
            return (232, 232, 236)
        return bg
    _icons[size] = _png(size, px)
    return _icons[size]
