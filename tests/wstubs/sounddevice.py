import threading, time, numpy as np
SCRIPT = []          # list of ("silence"|"speech", seconds)
class InputStream:
    def __init__(self, samplerate, channels, dtype, blocksize, device, callback):
        self.cb, self.bs, self.sr = callback, blocksize, samplerate
        self.stop_ev = threading.Event()
    def start(self):
        def run():
            rng = np.random.default_rng(0)
            for kind, secs in SCRIPT:
                n = int(secs * self.sr / self.bs)
                for _ in range(n):
                    if self.stop_ev.is_set(): return
                    amp = 0.1 if kind == "speech" else 0.002
                    x = (rng.standard_normal(self.bs) * amp).astype(np.float32).reshape(-1, 1)
                    self.cb(x, self.bs, None, None)
                    time.sleep(0.002)
            while not self.stop_ev.is_set():
                self.cb(np.zeros((self.bs, 1), np.float32), self.bs, None, None); time.sleep(0.002)
        threading.Thread(target=run, daemon=True).start()
    def stop(self): self.stop_ev.set()
    def close(self): pass
