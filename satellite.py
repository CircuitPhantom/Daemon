"""Laptop agent link, server side.

When Daemon runs on a home server, daemon-agent.py runs on your laptop. It
  * listens to the laptop microphone for the wake word and sends what you say here,
  * plays the replies on the laptop speakers,
  * keeps one WebSocket open (/ws/satellite) so the model can use the laptop's desktop tools
    (media, volume, clipboard, links, apps, Spotify). Which tools go there: config.yaml -> satellite.tools

Turn it on with `python satellite_setup.py` (writes satellite.enabled and a token into config.yaml).
If the laptop is off, those tools answer "laptop is offline" and everything else keeps working.
"""
import asyncio
import concurrent.futures
import hmac
import itertools
import threading
import time

import model_config

CALL_TIMEOUT = 60
_ids = itertools.count(1)


def enabled():
    model_config.reload_if_changed()
    return bool(model_config.satellite["enabled"] and model_config.satellite["token"])


def token_ok(token):
    t = model_config.satellite["token"]
    return bool(t and token and hmac.compare_digest(str(token), t))


def bearer(headers):
    """Token from an 'Authorization: Bearer ...' header (any mapping with .get)."""
    h = headers.get("authorization") or headers.get("Authorization") or ""
    return h[7:].strip() if h.lower().startswith("bearer ") else ""


class Hub:
    def __init__(self):
        self.ws = None
        self.loop = None
        self.name = ""
        self.tools = []
        self.desktop = ""
        self.since = 0.0
        self.pending = {}
        self.lock = threading.Lock()

    @property
    def connected(self):
        return self.ws is not None

    def status(self):
        return {"enabled": enabled(), "connected": self.connected, "name": self.name, "tools": self.tools,
                "since": self.since, "remote_tools": list(model_config.satellite["tools"])}

    # ── used by the model's tools (worker threads) ──
    def call(self, name, args, timeout=CALL_TIMEOUT):
        ws, loop = self.ws, self.loop
        if ws is None or loop is None:
            return "Error: the laptop is offline (start daemon-agent.py on it)"
        fut = concurrent.futures.Future()
        cid = next(_ids)
        with self.lock:
            self.pending[cid] = fut
        try:
            asyncio.run_coroutine_threadsafe(ws.send_json({"type": "call", "id": cid, "tool": name, "args": args}), loop)
            return fut.result(timeout)
        except concurrent.futures.TimeoutError:
            return f"Error: the laptop did not answer within {timeout} s"
        except Exception as e:
            return f"Error: the laptop connection failed ({e})"
        finally:
            with self.lock:
                self.pending.pop(cid, None)

    # ── the WebSocket endpoint (event loop) ──
    async def serve(self, ws):
        if not enabled() or not token_ok(bearer(ws.headers) or ws.query_params.get("token")):
            await ws.close(code=1008)
            return
        await ws.accept()
        old = self.ws
        if old is not None:                                   # a newer connection replaces the old one
            try:
                await old.close(code=1000)
            except Exception:
                pass
        self.ws, self.loop, self.since = ws, asyncio.get_running_loop(), time.time()
        try:
            while True:
                msg = await ws.receive_json()
                t = msg.get("type")
                if t == "hello":
                    self.name = str(msg.get("name") or "laptop")[:40]
                    self.tools = [str(x) for x in (msg.get("tools") or [])][:40]
                    self.desktop = str(msg.get("desktop") or "")[:80]
                    print(f"[satellite] {self.name} connected")
                elif t == "result":
                    with self.lock:
                        fut = self.pending.get(msg.get("id"))
                    if fut and not fut.done():
                        fut.set_result(str(msg.get("output", ""))[:12000])
        except Exception:
            pass
        finally:
            if self.ws is ws:
                self.ws, self.name, self.tools, self.desktop = None, "", [], ""
                print("[satellite] laptop disconnected")
                with self.lock:
                    for f in self.pending.values():
                        if not f.done():
                            f.set_result("Error: the laptop disconnected before it finished")


hub = Hub()
