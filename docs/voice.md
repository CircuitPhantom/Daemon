# Voice and wake word

## Speech to text (what you say)
- **Local Whisper** (default): faster-whisper in the server. `stt: {model: small, device: cpu, compute_type: int8}`. Use `base` for speed or `medium`/`large-v3` for accuracy; `device: cuda` and `compute_type: float16` only with an NVIDIA GPU. The language is detected automatically.
- **Cloud**: `stt_cloud` (Groq `whisper-large-v3-turbo` or any OpenAI-compatible transcription API) is tried first when enabled, with local Whisper as fallback. Faster on weak hardware; your audio leaves the machine.
- With the [laptop agent](laptop-agent.md), transcription happens on the laptop and only text is sent.

## Text to speech (what Daemon says)
Order of engines: ElevenLabs (if enabled) > Edge (if enabled) > local Kokoro. A failing engine falls back to the next one (`fallback: true`).

| Engine | Setup | Notes |
|---|---|---|
| **Kokoro** (local) | `tts: {voice: af_sarah, lang: en-us}` | Free, offline, CPU. English and several other languages, **no Turkish** |
| **Edge** | `edge_tts: {enabled: true, voice: en-US-AriaNeural}` | Free Microsoft neural voices in many languages (e.g. `tr-TR-EmelNeural`). Needs internet. Set `primary: true` to use it before ElevenLabs |
| **ElevenLabs** | `elevenlabs: {enabled: true}` + `DAEMON_ELEVENLABS_API_KEY` | Best quality, paid per character. `monthly_chars` sets your own cap |

Choose the engine in the dashboard under Settings > Voice. Restart the server after changing `stt`/`tts`.

## Wake word ("hey daemon")
Settings > Voice > Wake word, or in `config.yaml`:
```yaml
wake:
  enabled: true
  engine: whisper          # whisper: any phrase, more CPU | openwakeword: pretrained models, light
  phrase: hey daemon
  input_device: ""         # empty = default microphone; list names: python -m sounddevice
  followup_seconds: 6      # after a reply, keep listening this long without the wake word
```
- Needs `sounddevice` and the portaudio system package.
- `whisper` engine: every short utterance is transcribed and checked for the phrase. Works with any phrase, uses more CPU while people talk, and sends all speech to the server when the laptop agent is used.
- `openwakeword` engine: `pip install openwakeword`, `oww_model: hey_jarvis` (or a path to your own `.onnx`). Light and runs entirely on the microphone's machine.
- If Whisper writes the name differently ("demon", "damian"), add those to `wake.aliases`.
- Replies play through the computer's speakers (`pw-play`, `paplay` or `aplay`) and the whole conversation also shows up in the dashboard chat.
- When Daemon runs on a server, the microphone is the laptop's: see [Laptop agent](laptop-agent.md).
