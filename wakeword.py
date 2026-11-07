"""Wake word on this computer's microphone: say "hey daemon, what's the time?" without opening the web UI.

Two engines (config.yaml -> wake.engine):
  whisper       Default. Every short utterance is transcribed with the server's Whisper model and checked
                for the wake phrase. Works with any phrase ("hey daemon"), but uses more CPU while people talk.
  openwakeword  Light, always-on detector (pip install openwakeword). Only pretrained phrases such as
                "hey jarvis", or a custom .onnx model you trained (see the openWakeWord docs).

Needs: pip install sounddevice  (and the portaudio package: sudo pacman -S portaudio)
Replies play with pw-play, paplay or aplay. The conversation goes into the active chat, so the web UI
shows it too.
"""
import io
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
import wave

import numpy as np

import model_config

SR = 16000
FRAME = 1280                  # 80 ms, the frame size openWakeWord expects
PRE_ROLL = 6                  # frames kept from before speech started
END_SILENCE = 0.9             # seconds of silence that end an utterance
MAX_UTTERANCE = 15            # seconds
COMMAND_WAIT = 6              # seconds to start speaking after "hey daemon" + beep


class Segmenter:
    """Energy based voice activity detection with an adaptive noise floor."""

    def __init__(self, level=0.010, mult=3.2, min_speech=0.0):
        self.level, self.mult, self.min_speech = level, mult, min_speech   # min volume, times the noise floor, seconds of speech before it counts
        self.floor = 0.004
        self.pre, self.rec, self.loud, self.silence = [], None, 0, 0.0

    def threshold(self):
        return max(self.level, self.floor * self.mult)

    def feed(self, frame):
        """Returns a finished utterance (np.ndarray) or None."""
        r = float(np.sqrt(np.mean(frame * frame)))
        dt = len(frame) / SR
        if self.rec is None:
            self.pre.append(frame)
            if len(self.pre) > PRE_ROLL:
                self.pre.pop(0)
            if r > self.threshold():
                self.loud += dt if self.min_speech else 1
                if self.loud >= (self.min_speech or 2):
                    self.rec, self.silence, self.loud = list(self.pre), 0.0, 0
                    self.pre = []
            else:
                self.loud = 0
                self.floor = 0.97 * self.floor + 0.03 * r
            return None
        self.rec.append(frame)
        self.silence = 0.0 if r > self.threshold() else self.silence + dt
        if self.silence >= END_SILENCE or len(self.rec) * dt >= MAX_UTTERANCE:
            audio = np.concatenate(self.rec)
            self.rec = None
            return audio if len(audio) > SR * 0.35 else None
        return None

    @property
    def speaking(self):
        return self.rec is not None

    def reset(self):
        self.pre, self.rec, self.loud, self.silence = [], None, 0, 0.0


def wav_bytes(samples, rate=SR):
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def beep():
    t = np.arange(int(SR * 0.12)) / SR
    tone = 0.25 * np.sin(2 * np.pi * 880 * t) * np.hanning(len(t))
    return wav_bytes(tone)


def player_cmd():
    for cmd in (["pw-play"], ["paplay"], ["aplay", "-q"]):
        if shutil.which(cmd[0]):
            return cmd
    return None


def play(data):
    cmd = player_cmd()
    if not cmd:
        print("[wake] no audio player found (install pipewire, pulseaudio-utils or alsa-utils)")
        return
    with tempfile.NamedTemporaryFile(suffix=".wav") as f:
        f.write(data)
        f.flush()
        try:
            subprocess.run(cmd + [f.name], timeout=120, stdin=subprocess.DEVNULL, capture_output=True)
        except Exception as e:
            print("[wake] playback failed:", e)


def find_wake(text, phrase, aliases):
    """Returns the command after the wake word, '' if only the wake word was said, or None if not said."""
    names = {w for w in re.findall(r"[a-zçğıöşü]+", (phrase.split()[-1] if phrase.split() else "").lower())}
    names |= {a.strip().lower() for a in aliases.split(",") if a.strip()}
    if not names:
        return None
    m = re.search(r"\b(" + "|".join(map(re.escape, sorted(names, key=len, reverse=True))) + r")\b", text, re.I)
    if not m or len(re.findall(r"\w+", text[:m.start()])) > 3:     # the name must come near the start
        return None
    return text[m.end():].strip(" ,.!?:;-—")


class WakeListener:
    def __init__(self, transcribe, run_turn):
        """transcribe(audio, prompt) -> text; run_turn(text, emit, cancel) runs a spoken turn."""
        self.transcribe = transcribe
        self.run_turn = run_turn
        self._thread = None
        self._stop = threading.Event()
        self.state = {"running": False, "error": "", "engine": "", "heard": "", "command": "", "at": 0}

    # ── control ──
    def start(self):
        self.stop()
        self._stop = threading.Event()
        self.state.update(running=True, error="", engine=model_config.wake["engine"])
        self._thread = threading.Thread(target=self._main, daemon=True, name="wakeword")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=3)
        self._thread = None
        self.state["running"] = False

    def apply_config(self):
        if model_config.wake["enabled"]:
            self.start()
        else:
            self.stop()

    def status(self):
        return dict(self.state)

    # ── main loop ──
    def _main(self):
        try:
            import sounddevice as sd
        except Exception as e:
            self._fail(f"sounddevice is missing: pip install sounddevice (and sudo pacman -S portaudio). {e}")
            return
        cfg = dict(model_config.wake)
        detector = None
        if cfg["engine"] == "openwakeword":
            try:
                detector = self._load_oww(cfg["oww_model"])
            except Exception as e:
                self._fail(f"openWakeWord could not start: {e}")
                return
        q = queue.Queue(maxsize=400)

        def callback(indata, frames, t, status):
            try:
                q.put_nowait(indata[:, 0].copy())
            except queue.Full:
                pass

        dev = cfg["input_device"] or None
        if dev and dev.isdigit():
            dev = int(dev)
        try:
            stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32", blocksize=FRAME,
                                    device=dev, callback=callback)
            stream.start()
        except Exception as e:
            self._fail(f"could not open the microphone: {e}")
            return
        print(f"[wake] listening ({cfg['engine']}: {cfg['phrase'] if detector is None else cfg['oww_model']})")
        try:
            self._loop(q, cfg, detector)
        except Exception as e:
            self._fail(f"stopped: {e}")
        finally:
            stream.stop()
            stream.close()
            self.state["running"] = False

    def _fail(self, msg):
        print("[wake]", msg)
        self.state.update(running=False, error=msg)

    @staticmethod
    def _load_oww(name):
        from openwakeword.model import Model
        if not name.endswith(".onnx"):
            try:
                import openwakeword.utils
                openwakeword.utils.download_models([name])
            except Exception as e:
                print("[wake] model download skipped:", e)
        return Model(wakeword_models=[name], inference_framework="onnx")

    def _frames(self, q, timeout=0.2):
        try:
            return q.get(timeout=timeout)
        except queue.Empty:
            return None

    @staticmethod
    def _drain(q):
        while True:
            try:
                q.get_nowait()
            except queue.Empty:
                return

    def _listen_once(self, q, seg, wait):
        """Records one utterance that starts within `wait` seconds. Returns audio or None."""
        seg.reset()
        heard = 0.0                                   # measured in audio time, not wall-clock time
        while not self._stop.is_set():
            f = self._frames(q)
            if f is None:
                continue
            heard += len(f) / SR
            audio = seg.feed(f)
            if audio is not None:
                return audio
            if not seg.speaking and heard > wait:
                return None
        return None

    def _loop(self, q, cfg, detector):
        seg = Segmenter()
        prompt = cfg["phrase"].strip().capitalize() + "." if cfg["phrase"].strip() else None
        while not self._stop.is_set():
            f = self._frames(q)
            if f is None:
                continue
            command = None
            if detector is not None:
                scores = detector.predict((f * 32767).astype(np.int16))
                if max(scores.values(), default=0) < 0.5:
                    continue
                detector.reset()
                command = ""
            else:
                audio = seg.feed(f)
                if audio is None:
                    continue
                text = self.transcribe(audio, prompt)
                command = find_wake(text, cfg["phrase"], cfg["aliases"])
                if command is None:
                    continue
                self.state.update(heard=text, at=time.time())
            if not command:                                   # only the wake word: beep, then listen
                play(beep())
                self._drain(q)
                audio = self._listen_once(q, seg, COMMAND_WAIT)
                if audio is None:
                    continue
                command = self.transcribe(audio, None)
            while command and not self._stop.is_set():
                print("[wake] command:", command)
                self.state.update(command=command, at=time.time())
                self._speak_turn(command)
                self._drain(q)                                # do not hear our own reply
                if not cfg["followup_seconds"]:
                    break
                audio = self._listen_once(q, seg, cfg["followup_seconds"])
                command = self.transcribe(audio, None) if audio is not None else ""
            seg.reset()
            if detector is not None:
                detector.reset()

    def _speak_turn(self, text):
        audio_q = queue.Queue()

        def player():
            while True:
                data = audio_q.get()
                if data is None:
                    return
                play(data)

        t = threading.Thread(target=player, daemon=True)
        t.start()

        def emit(ev):
            if ev.get("type") == "audio" and ev.get("audio"):
                import base64
                audio_q.put(base64.b64decode(ev["audio"]))

        try:
            self.run_turn(text, emit, threading.Event())
        except Exception as e:
            print("[wake] turn failed:", e)
        finally:
            audio_q.put(None)
            t.join(timeout=300)
