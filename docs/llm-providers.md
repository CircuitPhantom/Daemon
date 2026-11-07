# LLM providers

Daemon has no built-in model. It talks to any service that implements the OpenAI **chat completions** API with **tool calling**. Set three values in `config.yaml` (the key in `.env` as `DAEMON_LLM_API_KEY`):

```yaml
llm:
  base_url: https://api.groq.com/openai/v1
  model: llama-3.3-70b-versatile
  timeout: 60
```

| Provider | `base_url` | Notes |
|---|---|---|
| Anthropic | `https://api.anthropic.com/v1` | The default |
| OpenAI | `https://api.openai.com/v1` | |
| Groq | `https://api.groq.com/openai/v1` | Fast, generous free tier; also offers cloud speech-to-text |
| NVIDIA | `https://integrate.api.nvidia.com/v1` | Hosted open models (Nemotron, Llama, ...). Free trial terms differ from paid ones, read them |
| OpenRouter | `https://openrouter.ai/api/v1` | One key, many models |
| Fireworks | `https://api.fireworks.ai/inference/v1` | |
| Together | `https://api.together.xyz/v1` | |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | OpenAI-compatible endpoint |

Check each provider's current model names and prices; they change often.

## Picking a model
- **Tool calling is required.** Without it Daemon can chat but cannot do anything.
- **Vision** is needed to look at photos you send and for computer control (`uploads.vision: auto` guesses from the model name; set `true`/`false` to override).
- Answers are meant to be spoken, so small fast models are often a better fit than the biggest ones. Speed matters more in voice than in chat.
- Computer control works best with models trained for GUI grounding (Qwen3-VL, Nemotron VL, UI-TARS, GLM-V); Daemon switches to a 0-1000 coordinate grid for them (`computer.coords: auto`).
- Tool schemas are kept small on purpose (a test bounds their total size) so weaker models can handle them.

## Privacy
Everything you say to Daemon, its tool results (file contents, command output, web pages, screenshots) and your memory notes are sent to the provider you choose. Providers differ in how long they keep it and whether they train on it. Read the data-retention terms of your provider and plan. Free or trial tiers are often the least private. If this matters, pick a provider with zero data retention, and keep sensitive files out of reach of the tools (the file tools can read what your user can read).

## Local models
`llm.base_url` can in principle point at a local OpenAI-compatible server (llama.cpp, vLLM, Ollama's `/v1`), but this is not tested and small local models are usually poor at tool calling. The speech models (Whisper, Kokoro) do run locally.

## Errors
Quota, key and network errors are shown in the chat, and once on Signal if it is set up. `venv/bin/python doctor.py --online` tests the connection.
