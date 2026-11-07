"""Free Microsoft Edge neural voices (edge-tts package) next to ElevenLabs, with the same automatic fallback to Kokoro.

No key, no account. It is an unofficial service (the same one Edge's "read aloud" uses), so it can change or stop working
without notice: when that happens the next voice (Kokoro) takes over by itself and Edge is tried again later.

config.yaml:

  edge_tts:
    enabled: true
    voice: en-US-AriaNeural     # en-US-AvaNeural, en-US-AndrewNeural, en-US-EmmaNeural, en-GB-SoniaNeural, en-GB-RyanNeural...
                                # list all: edge-tts --list-voices
    rate: "+0%"                 # speed, e.g. "+10%" or "-5%"
    pitch: "+0Hz"
    fallback: true              # when it fails use the next voice (false with nothing else working = stay silent)

Needs:  pip install edge-tts miniaudio      (miniaudio decodes the MP3; ffmpeg works too when it is installed)
The "Local voice only" switch of the dashboard turns this off as well.
"""
import asyncio
import io
import subprocess
import threading
import time
import wave

import audio_fx
import model_config

TIMEOUT = 20
VOICES = ["en-US-AriaNeural", "en-US-AvaNeural", "en-US-EmmaNeural", "en-US-JennyNeural", "en-US-MichelleNeural",
          "en-US-AndrewNeural", "en-US-BrianNeural", "en-US-GuyNeural", "en-US-ChristopherNeural", "en-US-EricNeural",
          "en-GB-SoniaNeural", "en-GB-LibbyNeural", "en-GB-RyanNeural", "en-GB-ThomasNeural",
          "en-AU-NatashaNeural", "en-AU-WilliamNeural", "en-IE-EmilyNeural", "en-IN-NeerjaNeural"]
COOLDOWN = {"network": 60, "error": 300, "missing": 3600}
_lock = threading.RLock()
_s = {"down_until": 0.0, "reason": "", "kind": "", "last_s": 0.0}


def _cfg():
    return model_config.edge_tts


def reset():
    with _lock:
        _s.update(down_until=0.0, reason="", kind="")


class Missing(Exception):
    pass


def _import():
    try:
        import edge_tts
        return edge_tts
    except ImportError:
        raise Missing("the edge-tts package is not installed (pip install edge-tts miniaudio)") from None


def _have_package():
    try:
        _import()
        return True
    except Missing:
        return False


def _go_down(kind, reason):
    with _lock:
        _s.update(down_until=time.time() + COOLDOWN[kind], reason=reason, kind=kind)
    print(f"[edge-tts] not used for now: {reason}")


def state():
    """(usable, why)"""
    c = _cfg()
    if not c["enabled"]:
        return False, "off"
    if model_config.elevenlabs["local_only"]:
        return False, "local voice only (switch)"
    with _lock:
        if _s["down_until"] > time.time():
            return False, _s["reason"]
    return True, "ok"


def _fetch_mp3(text):
    mod = _import()
    c = _cfg()

    async def go():
        com = mod.Communicate(text, c["voice"], rate=c["rate"], pitch=c["pitch"])
        out = bytearray()
        async for ch in com.stream():
            if ch.get("type") == "audio":
                out += ch["data"]
        return bytes(out)

    box = {}

    def run():                                   # own thread and loop: safe even when called from inside a running loop
        try:
            box["v"] = asyncio.run(asyncio.wait_for(go(), TIMEOUT))
        except BaseException as e:
            box["e"] = e

    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(TIMEOUT + 5)
    if th.is_alive():
        raise TimeoutError("timed out")
    if "e" in box:
        raise box["e"]
    return box["v"]


def _decode(mp3, rate=24000):
    """MP3 bytes -> mono PCM16 bytes at `rate`."""
    try:
        import miniaudio
        d = miniaudio.decode(mp3, output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1, sample_rate=rate)
        return bytes(d.samples)
    except ImportError:
        pass
    try:
        p = subprocess.run(["ffmpeg", "-v", "error", "-i", "pipe:0", "-f", "s16le", "-ac", "1", "-ar", str(rate), "pipe:1"],
                           input=mp3, capture_output=True, timeout=20)
    except FileNotFoundError:
        raise Missing("no MP3 decoder: pip install miniaudio (or install ffmpeg)") from None
    if p.returncode or not p.stdout:
        raise RuntimeError("could not decode the audio: " + p.stderr.decode("utf-8", "replace")[:120])
    return p.stdout


def _synth(text):
    mp3 = _fetch_mp3(text)
    if len(mp3) < 200:
        raise RuntimeError("Edge sent no audio")
    rate = 24000
    pcm = _decode(mp3, rate)
    if len(pcm) < 400:
        raise RuntimeError("empty audio")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(audio_fx.clean_pcm(pcm, rate))
    return buf.getvalue()


def _classify(e):
    if isinstance(e, Missing):
        return "missing", str(e)
    if isinstance(e, (TimeoutError, OSError, asyncio.TimeoutError)):
        return "network", "no connection to the Edge voice service"
    return "error", f"{type(e).__name__}: {str(e)[:120]}"


def speak(text):
    """WAV bytes of `text`, or None when the next voice should be used."""
    ok, _ = state()
    if not ok:
        return None
    t0 = time.time()
    try:
        data = _synth(text)
    except Exception as e:
        _go_down(*_classify(e))
        return None
    with _lock:
        _s.update(last_s=time.time() - t0, kind="", reason="")
    return data


def test(text="Hello, this is a test of the Edge voice."):
    """Tries once, ignoring the switch and cooldown. Returns {ok, info}."""
    t0 = time.time()
    try:
        data = _synth(text)
    except Exception as e:
        return {"ok": False, "info": _classify(e)[1]}
    reset()
    return {"ok": True, "info": f"{len(data) // 1024} KB in {time.time() - t0:.1f} s (voice {_cfg()['voice']})"}


def status():
    c = _cfg()
    usable, why = state()
    with _lock:
        down = max(0, int(_s["down_until"] - time.time()))
        last = round(_s["last_s"], 1)
    return {"enabled": c["enabled"], "configured": _have_package(), "active": usable, "why": why, "retry_in": down,
            "voice": c["voice"], "voices": VOICES, "primary": c["primary"], "fallback": c["fallback"], "last_seconds": last}
