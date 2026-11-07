import wave, numpy as np
SPOKEN = []
class GenerationConfig:
    def __init__(self,**k): pass
class SynthesisConfig:
    def __init__(self,**k): pass
class _R:
    def __init__(s, t): s.t = t
    def save_wav(s, p):
        with wave.open(p, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(np.zeros(2400, "<i2").tobytes())
class KokoroSynthesizer:
    def __init__(self,*a): pass
    def __enter__(self): return self
    def __exit__(self,*a): pass
    def synthesize_text(self, t, **k): SPOKEN.append(t); return _R(t)
