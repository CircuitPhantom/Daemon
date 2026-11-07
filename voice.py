"""The voice: speech-to-text (Whisper or the cloud), the spoken reply (ElevenLabs, Edge or the local Kokoro voice), and the
small text tools around them (voice effects in square brackets, cutting streamed text into sentences).

Used by conversation.py (every turn), the phone bridge, the wake word listener and the laptop agent's endpoints.
"""
import io
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import wave

import numpy as np
from faster_whisper import WhisperModel
from pykokoro import GenerationConfig, KokoroSynthesizer, SynthesisConfig

import cloud_stt
import edge_voice
import elevenlabs_tts
import model_config

# Settings (stt/tts) come from config.yaml (see model_config.py); changing them needs a restart
stt = WhisperModel(
    model_config.stt["model"],
    device=model_config.stt["device"],
    compute_type=model_config.stt["compute_type"],
)
stt_lock = threading.Lock()
config = SynthesisConfig(
    voice=model_config.tts["voice"],
    generation=GenerationConfig(lang=model_config.tts["lang"]),
)
os.makedirs("sound", exist_ok=True)


def warm_up_whisper():
    """The first transcription loads the voice-activity model and is slow: do it now instead of during the first call."""
    try:
        with stt_lock:
            list(stt.transcribe(np.zeros(16000, dtype=np.float32), vad_filter=True)[0])
    except Exception as e:
        print("[stt] warm-up skipped:", e)



def voice_block():
    """Told to the model on spoken turns, so what it writes fits how it will sound."""
    b = ("When you speak, write the way a person talks: natural sentences, numbers and symbols the way you would say them, "
         "no URLs read out. If the user interrupts you, you will be told what they heard and what they did not.")
    if voice_tags_on():
        level = str(model_config.elevenlabs.get("audio_tags_use") or "normal").lower()
        freq = {"rare": "Use them rarely, only for a clear moment (one every several sentences).",
                "lively": "Use them freely: almost every reply that is not purely factual should have one or two, and a casual or emotional "
                          "reply can have one every sentence or two."}.get(level,
                "Use them naturally: whenever the mood of what you say calls for one (something funny, relief, surprise, hesitation, "
                "empathy, a thoughtful pause), usually one or two per casual or emotional reply. Skip them for plain facts, short "
                "answers and tool results.")
        b += (" Your voice acts out effects written in square brackets. " +
              " ".join(f"{k}: " + ", ".join(f"[{t}]" for t in v) + "." for k, v in VOICE_TAG_GROUPS.items()) + " " + freq +
              " Put the tag right where the effect should happen, inside the text, never explain it, and never write one that is "
              "not in the list. Examples: \"Ha, that is a good one. [laughing] Okay, so here is what I would do.\", "
              "\"[sighing] Yeah, that sounds exhausting.\", \"Hmm, [pause] let me think about it.\", "
              "\"[whispering] Between us, that is a bad idea.\"")
    return b


# Voice effects the model may write in square brackets. ElevenLabs acts them out (v3 style models); every other voice drops them.
VOICE_TAG_GROUPS = {          # the effects Eleven v3 documents; add more here and they work everywhere (prompt, cleaning, display)
    "Emotion": ("weak", "angry", "bored", "menacing", "playful", "tired", "excited"),
    "Vocalizations": ("clears throat", "coughing", "chuckling", "sighing", "sniffling", "yawning", "laughing", "sharp exhale",
                      "scoffing", "humming", "panting", "gasping"),
    "Delivery": ("whispering", "singing", "slowly", "softly", "pause", "voice breaking"),
}
VOICE_TAGS = tuple(t for g in VOICE_TAG_GROUPS.values() for t in g)
_KNOWN_RE = re.compile(r"\[(?:" + "|".join(re.escape(t) for t in VOICE_TAGS) + r")\]", re.I)
# any invented effect such as [smiles] or [warm laugh] (a few lowercase words, not a markdown link) is dropped as well
_TAG_RE = re.compile(r"[ \t]*\[[A-Za-z][A-Za-z' -]{1,30}\](?!\()")
TAG_RE = _TAG_RE


def strip_tags(t):
    """Text without the voice effects (what is shown on screen and what non-ElevenLabs voices read)."""
    return _TAG_RE.sub("", t).lstrip(" \t") if _TAG_RE.match(t) else _TAG_RE.sub("", t)


def voice_tags_on():
    """True when the first voice in line is ElevenLabs with a model that can act the effects out."""
    c = model_config.elevenlabs
    if not (c["audio_tags"] or "v3" in c["model"].lower()):
        return False
    if model_config.edge_tts["primary"] and edge_voice.state()[0]:
        return False
    return elevenlabs_tts.state()[0]


def clean_for_tts(t: str, tags=None) -> str:
    keep = voice_tags_on() if tags is None else tags
    marks = []
    if keep:
        def mark(m):
            tag = m.group(0).strip().lower()
            if not _KNOWN_RE.fullmatch(tag):
                return " "                                   # an effect the voice does not know: drop it
            marks.append(tag)
            return f" TAGMARK{len(marks) - 1}X "
        t = _TAG_RE.sub(mark, t)
    else:
        t = _TAG_RE.sub(" ", t)
    t = _clean_for_tts(t)
    return re.sub(r"TAGMARK(\d+)X", lambda m: marks[int(m.group(1))], t).strip() if marks else t


def _clean_for_tts(t: str) -> str:
    t = re.sub(r"```.*?```", " code block ", t, flags=re.S)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    t = re.sub(r"[*_#`>|~]+", "", t)
    t = re.sub(r"[^\w\s.,!?;:'\"()%/+\-]", "", t)
    return re.sub(r"[ \t]+", " ", t).strip()


def split_for_tts(text, max_chars=160):
    parts = []
    for s in re.split(r"(?<=[.!?:;])\s+|\n+", text):
        s = s.strip()
        while len(s) > max_chars:
            cut = s.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            parts.append(s[:cut])
            s = s[cut:].strip()
        if s:
            parts.append(s)
    chunks, cur = [], ""
    for p in parts:
        if cur and len(cur) + len(p) + 1 > max_chars:
            chunks.append(cur)
            cur = p
        else:
            cur = f"{cur} {p}".strip()
    if cur:
        chunks.append(cur)
    return chunks


def read_wav(path):
    """Converts a PCM16 or float32 WAV into a float32 numpy array."""
    with open(path, "rb") as f:
        b = f.read()
    pos, fmt, data = 12, None, b""
    while pos + 8 <= len(b):
        cid = b[pos:pos + 4]
        size = int.from_bytes(b[pos + 4:pos + 8], "little")
        body = b[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            fmt = (
                int.from_bytes(body[0:2], "little"),    # format tag
                int.from_bytes(body[2:4], "little"),    # channels
                int.from_bytes(body[4:8], "little"),    # sample rate
                int.from_bytes(body[14:16], "little"),  # bits
            )
        elif cid == b"data":
            data = body
            break
        pos += 8 + size + (size & 1)
    if fmt is None:
        raise ValueError("no fmt chunk in the WAV")
    tag, ch, rate, bits = fmt
    if bits == 32 and tag in (3, 0xFFFE):
        data = data[: len(data) // 4 * 4]
        x = np.frombuffer(data, dtype="<f4")
    elif bits == 32:
        data = data[: len(data) // 4 * 4]
        x = np.frombuffer(data, dtype="<i4").astype(np.float32) / 2**31
    elif bits == 16:
        data = data[: len(data) // 2 * 2]
        x = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768
    else:
        raise ValueError(f"unsupported WAV: tag={tag} bits={bits}")
    return x, ch, rate


class LazyKokoro:
    """The local voice, loaded only when it is needed (not at all while ElevenLabs works)."""

    def __init__(self):
        self.synth = None

    def get(self):
        if self.synth is None:
            self.synth = KokoroSynthesizer(config)
            self.synth.__enter__()
        return self.synth

    def close(self):
        if self.synth is not None:
            try:
                self.synth.__exit__(None, None, None)
            except Exception:
                pass
            self.synth = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def tts_wav(synth, text, max_chunks=8):
    """Speaks `text` and returns PCM16 WAV bytes (or None): ElevenLabs when it is on and working, else local Kokoro."""
    limit = max_chunks * 160                                      # only read the beginning of very long replies
    if len(text) > limit:
        cut = max(text.rfind(". ", 0, limit), text.rfind("! ", 0, limit), text.rfind("? ", 0, limit))
        text = text[: cut + 1] if cut > limit // 2 else text[: max(text.rfind(" ", 0, limit), limit // 2)]
    plain = strip_tags(text)
    tags = voice_tags_on()
    if not tags and not re.search(r"\w", plain):
        return None
    for eng in ((edge_voice, elevenlabs_tts) if model_config.edge_tts["primary"] else (elevenlabs_tts, edge_voice)):
        data = eng.speak(text if (eng is elevenlabs_tts and tags) else plain)
        if data:
            return data
    text = plain
    if not re.search(r"\w", text):
        return None
    for c, ready in ((model_config.elevenlabs, bool(model_config.elevenlabs["api_key"])),
                     (model_config.edge_tts, edge_voice._have_package())):
        if c["enabled"] and ready and not model_config.elevenlabs["local_only"] and not c["fallback"]:
            return None                                           # fallback is off: stay silent instead of switching voice
    arrays, ch, rate = [], 1, 24000
    for c in split_for_tts(text)[:max_chunks]:
        fd, p = tempfile.mkstemp(suffix=".wav", dir="sound")
        os.close(fd)
        try:
            synth.get().synthesize_text(
                c, language=model_config.tts["lang"], voice=model_config.tts["voice"]
            ).save_wav(p)
            x, ch, rate = read_wav(p)
            arrays.append(x)
        except Exception as e:
            print("[tts] chunk skipped:", e)
        finally:
            if os.path.exists(p):
                os.remove(p)
    if not arrays:
        return None
    gap = np.zeros(int(rate * ch * 0.12), dtype=np.float32)   # short gap between chunks
    parts = []
    for a in arrays:
        parts += [a, gap]
    pcm = (np.clip(np.concatenate(parts), -1, 1) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(ch)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm.tobytes())
    return buf.getvalue()


def transcribe(audio, prompt=None, lang=""):
    """Speech to text on a float32 16 kHz array: the cloud if stt_cloud is on, else (or if it fails) the local Whisper.
    Shared by the web UI, the phone calls and the wake word listener."""
    t0 = time.time()
    if cloud_stt.usable():
        try:
            text = cloud_stt.transcribe(audio, prompt, lang)
            print(f"[timing] speech-to-text (cloud {model_config.stt_cloud['model']}): {len(audio) / 16000:.1f} s of audio took {time.time() - t0:.1f} s")
            return text
        except Exception:
            pass                                     # cloud_stt already printed why; use the local Whisper
    t0 = time.time()
    with stt_lock:
        segments, _ = stt.transcribe(
            audio, vad_filter=True, language=lang or None,
            condition_on_previous_text=False, initial_prompt=prompt,
        )
        text = " ".join(s.text for s in segments).strip()
    print(f"[timing] speech-to-text: {len(audio) / 16000:.1f} s of audio took {time.time() - t0:.1f} s (stt.model {model_config.stt['model']}, {model_config.stt['device']})")
    return text


def decode_audio_bytes(data, rate=16000):
    """Voice message bytes (aac, m4a, ogg, mp3...) -> mono float32 array. Uses PyAV, which faster-whisper installs
    anyway, so no separate ffmpeg program is needed. Falls back to the ffmpeg program when PyAV fails."""
    try:
        import av
        resampler = av.AudioResampler(format="s16", layout="mono", rate=rate)
        chunks = []
        def frames(x):                                   # old PyAV returns one frame (or None), newer ones a list
            return x if isinstance(x, (list, tuple)) else ([] if x is None else [x])
        with av.open(io.BytesIO(data)) as container:
            for frame in container.decode(audio=0):
                for f in frames(resampler.resample(frame)):
                    chunks.append(f.to_ndarray().reshape(-1))
        for f in frames(resampler.resample(None)):
            chunks.append(f.to_ndarray().reshape(-1))
        if chunks:
            return np.concatenate(chunks).astype(np.float32) / 32768.0
        raise RuntimeError("no audio found")
    except Exception as e:
        err = e
    if not shutil.which("ffmpeg"):
        raise RuntimeError(f"could not decode the audio ({err})")
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", "pipe:0", "-f", "f32le", "-ac", "1", "-ar", str(rate), "pipe:1"],
                       input=data, capture_output=True, timeout=60)
    if p.returncode or not p.stdout:
        raise RuntimeError("could not decode the audio: " + p.stderr.decode("utf-8", "replace")[:120])
    return np.frombuffer(p.stdout, dtype=np.float32)


def phone_speak(text):
    """The reply voice for the phone bridge: PCM16 WAV bytes."""
    with LazyKokoro() as synth:
        return tts_wav(synth, clean_for_tts(text), max_chunks=4)


# ---------- streaming ----------
# The web UI uses these: text appears while the model writes, and each finished sentence is spoken
# right away instead of waiting for the whole reply. One JSON object per line (NDJSON):
#   {"type":"user","text":...}        what was heard / typed
#   {"type":"thinking","text":...}    thinking piece
#   {"type":"delta","text":...}       reply piece
#   {"type":"reset"}                  text so far was a preamble before tool calls, clear it
#   {"type":"tool", name, args, output}
#   {"type":"audio","seq":n,"audio":base64 wav}
#   {"type":"done", reply, thinking, tools, rev}   or   {"type":"error","message":...}
_SENT_END = re.compile(r"[.!?;:](?=\s)|\n")


class SentenceSplitter:
    """Cuts streamed text into speakable pieces (whole sentences, never inside a code block)."""

    def __init__(self, first=20, later=60, hard=220):
        self.buf, self.first, self.later, self.hard, self.n = "", first, later, hard, 0

    def feed(self, text):
        self.buf += text
        out = []
        while self.buf.count("```") % 2 == 0:
            want = self.first if self.n == 0 else self.later
            cut = next((m.end() for m in _SENT_END.finditer(self.buf)
                        if m.end() >= want and self.buf.count("```", 0, m.end()) % 2 == 0), None)
            if cut is None and len(self.buf) > self.hard:
                cut = self.buf.rfind(" ", 0, self.hard) + 1 or self.hard
            if cut is None:
                break
            piece, self.buf = self.buf[:cut], self.buf[cut:]
            if piece.strip():
                out.append(piece.strip())
                self.n += 1
        return out

    def flush(self):
        piece, self.buf = self.buf.strip(), ""
        return [piece] if piece else []

    def reset(self):
        self.buf = ""


class TagFilter:
    """Takes the voice effects out of streamed text (a tag can arrive in two pieces)."""

    def __init__(self):
        self.buf, self.ws = "", ""

    def feed(self, text):
        self.buf += text
        i = self.buf.rfind("[")
        hold = ""
        if i >= 0 and "]" not in self.buf[i:] and len(self.buf) - i <= 16:
            self.buf, hold = self.buf[:i], self.buf[i:]
        out = strip_tags(self.buf)
        self.buf = hold
        res = (self.ws if out and not out[:1].isspace() else "") + out    # spaces wait until we know no tag follows
        body = res.rstrip()
        self.ws = res[len(body):] if body else self.ws + out
        return body

    def flush(self):
        out = strip_tags(self.buf)
        out, self.buf, self.ws = (self.ws + out if out else ""), "", ""
        return out
