"""Small clean-up for the voices that come from the cloud (ElevenLabs, Gemini).

Their audio can end on a sample that is not zero (or with a stray last sample). When the player stops there it makes a short
high "tick" at the end of every sentence. A short fade-out and a little silence after it remove that.
"""
import numpy as np


def frames_rms(x, rate, ms=10):
    n = int(rate * ms / 1000)
    k = len(x) // n
    f = x[: k * n].reshape(k, n)
    return np.sqrt(np.mean(f * f, axis=1)), np.mean(np.abs(np.diff(np.sign(f), axis=1)) > 0, axis=1)


def trim_tail_burst(pcm, rate, quiet=0.03, gap_ms=80, max_burst_ms=150):
    """Cuts a short burst of noise that some voices put at the very end, after a pause that follows the speech.

    Returns (pcm, cut_ms). Looks at 10 ms frames: [speech] [pause of at least gap_ms] [sound for at most max_burst_ms] [end].
    Only that shape is cut; speech that simply ends is left alone.
    """
    x = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype="<i2").astype(np.float32)
    rms, _ = frames_rms(x, rate)
    if len(rms) < 40:
        return pcm, 0
    loud = rms > quiet * max(float(np.percentile(rms, 95)), 1.0)
    i = len(loud)
    while i > 0 and not loud[i - 1]:                           # silence at the very end is fine
        i -= 1
    burst = 0
    while i - burst > 0 and loud[i - 1 - burst]:
        burst += 1
    if burst == 0 or burst * 10 > max_burst_ms:
        return pcm, 0
    j = i - burst
    gap = 0
    while j - gap > 0 and not loud[j - 1 - gap]:
        gap += 1
    if gap * 10 < gap_ms or j - gap <= 0 or not loud[: j - gap].any():
        return pcm, 0
    cut = min((j - gap + 3) * int(rate * 0.010), len(x))        # keep 30 ms of the pause
    return pcm[: cut * 2], int((len(x) - cut) * 1000 / rate)


def clean_pcm(pcm, rate, fade_in=0.004, fade_out=0.030, tail=0.080, trim_burst=False):
    """16-bit mono PCM bytes in, 16-bit mono PCM bytes out: odd byte cut, DC offset removed, fades, silent tail."""
    if trim_burst:
        pcm, _ = trim_tail_burst(pcm, rate)
    x = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype="<i2").astype(np.float32)
    if len(x) < int(rate * 0.1):
        return pcm[: len(pcm) // 2 * 2]
    head = x[: int(rate * 0.05)]
    x = x - float(np.mean(head)) if abs(float(np.mean(head))) < 2000 else x          # a constant offset makes the clicks louder
    n_in, n_out = int(rate * fade_in), int(rate * fade_out)
    x[:n_in] *= np.linspace(0.0, 1.0, n_in, dtype=np.float32)
    x[-n_out:] *= np.linspace(1.0, 0.0, n_out, dtype=np.float32)
    x = np.concatenate([x, np.zeros(int(rate * tail), dtype=np.float32)])
    return np.clip(x, -32768, 32767).astype("<i2").tobytes()
