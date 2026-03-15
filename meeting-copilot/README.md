# Meeting Copilot

Real-time AI assistant for meetings. Captures audio from your microphone and system audio (remote participants), transcribes speech with automatic speaker labels, and runs LLM reasoning to produce live summaries, action items, contradiction alerts, and reply suggestions.

## Features

- Real-time transcription via faster-whisper
- Automatic speaker labels: **Me** (microphone) / **Them** (system audio) — no diarization models needed
- Progressive summarization, action item extraction, contradiction detection
- Reply suggestions and custom prompts via Ollama (local) or Claude API
- Session persistence — browse and export past meetings
- React frontend with dark mode, mobile layout, WebSocket status indicators

## System Requirements

- Python 3.11+
- Node 18+ (for frontend)
- [Ollama](https://ollama.com) running locally (for LLM inference)
- **`pactl`** — PulseAudio utilities (`pulseaudio-utils` on Ubuntu/Debian, `pipewire-pulse` on Arch)
- **`ffmpeg`** — audio capture

### Install system dependencies

```bash
# Ubuntu / Debian
sudo apt install pulseaudio-utils ffmpeg

# Arch Linux
sudo pacman -S pipewire-pulse ffmpeg

# Fedora
sudo dnf install pulseaudio-utils ffmpeg
```

Verify both are available:
```bash
pactl list sources short   # shows PulseAudio sources including monitor sources
ffmpeg -version
```

## Quick Start (Local)

```bash
# 1. Clone the repo and enter the project directory
cd meeting-copilot

# 2. Run setup (creates venv, installs deps, copies .env, checks system deps)
bash scripts/setup.sh

# 3. Edit .env — set ANTHROPIC_API_KEY if you want Claude API fallback
nano .env

# 4. Start backend
source .venv/bin/activate
uvicorn backend.main:app --reload

# 5. Start frontend (separate terminal)
cd frontend && npm start
```

Open http://localhost:3000 in your browser. Click **Start Recording** — the backend will capture your microphone and system audio automatically.

## Backend Audio Capture

### How it works

Meeting Copilot uses **PulseAudio monitor sources** to capture both sides of a call simultaneously:

- **Mic stream** → your microphone (`pactl get-default-source`) → labeled **"Me"**
- **Monitor stream** → `<default_sink>.monitor`, capturing all audio playing through your speakers → labeled **"Them"**

Two separate `ffmpeg` processes run in parallel, each streaming 16 kHz mono PCM to the backend pipeline. The pipeline assigns speaker labels based on which stream a chunk came from — no ML diarization required.

> **Note:** Monitor sources are built into PulseAudio/PipeWire — no virtual audio cable installation is needed.

### Selecting audio devices

By default, the app uses the PulseAudio default source and sink. To override:

1. Open the UI and click the device picker (microphone icon near the Start button)
2. Select your preferred microphone from the **Mic Source** dropdown
3. Select your preferred monitor source from the **System Audio** dropdown
4. Adjust **Mic Volume** if your voice is too quiet in transcripts (default 2.0×)

Or set defaults in `.env`:
```
DEFAULT_MIC_SOURCE=alsa_input.pci-0000_00_1f.3.analog-stereo
DEFAULT_MONITOR_SOURCE=alsa_output.pci-0000_00_1f.3.analog-stereo.monitor
MIC_VOLUME=2.0
```

### Falling back to browser-only mode

If you are on macOS or Windows, or prefer to capture audio in the browser:

1. Set `AUDIO_CAPTURE_MODE=browser` in `.env`
2. The frontend will use `getUserMedia` and stream audio over `/ws/audio`
3. All audio will be labeled **"Speaker"** (no mic/monitor separation)

To capture both browser audio and backend audio simultaneously: `AUDIO_CAPTURE_MODE=both`

### Troubleshooting

**"No monitor source found"**
```bash
pactl list sources short | grep monitor
```
If empty, your system may be using ALSA directly. Install `pulseaudio` or `pipewire-pulse`.

**"ffmpeg not installed"**
```bash
which ffmpeg || sudo apt install ffmpeg
```

**"pactl not installed"**
```bash
which pactl || sudo apt install pulseaudio-utils
```

**Poor transcription of remote participants**
Increase monitor volume or lower mic volume boost: set `MIC_VOLUME=1.0` in `.env`.

**Recording starts but no segments appear**
Check that Whisper can run: `python -c "from faster_whisper import WhisperModel; print('ok')"`. If it fails, reinstall with `pip install faster-whisper`.

## Docker

```bash
# Build and start backend + Ollama
cp .env.example .env
# Edit .env as needed
docker-compose up --build
```

For NVIDIA GPU passthrough, uncomment the `deploy.resources` section in `docker-compose.yml`.

After containers start, pull the Ollama model:
```bash
docker-compose exec ollama ollama pull llama3.1:8b
```

> **Note:** Docker mode does not have access to the host PulseAudio server by default. Set `AUDIO_CAPTURE_MODE=browser` in `.env` when running via Docker, or pass through the PulseAudio socket with `-v /run/user/1000/pulse:/run/user/1000/pulse`.

## Configuration

All settings are in `.env`. Copy `.env.example` to `.env` to start.

| Variable | Default | Description |
|---|---|---|
| `WHISPER_MODEL` | `large-v3-turbo` | Whisper model size: `tiny`, `base`, `small`, `medium`, `large-v2`, `large-v3`, `large-v3-turbo` |
| `LANGUAGE` | `pt` | Transcription language (ISO 639-1). Leave blank for auto-detect. |
| `AUDIO_CAPTURE_MODE` | `backend` | Audio source: `backend` (PulseAudio/ffmpeg), `browser` (getUserMedia), `both` |
| `RECORDINGS_DIR` | `./recordings` | Directory for WAV file output |
| `MIC_VOLUME` | `2.0` | Microphone volume boost multiplier |
| `DEFAULT_MIC_SOURCE` | _(auto)_ | PulseAudio source name for microphone (empty = use default) |
| `DEFAULT_MONITOR_SOURCE` | _(auto)_ | PulseAudio monitor source name (empty = derive from default sink) |
| `SAVE_RECORDINGS` | `true` | Save WAV files for each recording session |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `llama3.1:8b` | Model for routine tasks |
| `OLLAMA_HEAVY_MODEL` | `llama3.1:70b` | Model for complex reasoning (falls back to `OLLAMA_MODEL`) |
| `USE_API_FALLBACK` | `false` | Use Claude API when Ollama fails |
| `ANTHROPIC_API_KEY` | — | Required when `USE_API_FALLBACK=true` |
| `SUMMARY_EVERY_N_SEGMENTS` | `10` | Trigger summary update every N transcript segments |
| `ACTION_SCAN_EVERY_N_SEGMENTS` | `5` | Trigger action item scan every N segments |
| `CONTRADICTION_CHECK_SECONDS` | `120` | Contradiction detection interval (seconds) |
| `DB_PATH` | `meetings.db` | SQLite database path |
| `WS_HOST` | `0.0.0.0` | WebSocket server host |
| `WS_PORT` | `8000` | WebSocket server port |

## API Reference

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/sessions` | List all sessions |
| `POST` | `/sessions` | Create a new session |
| `GET` | `/sessions/{id}` | Load a session |
| `GET` | `/sessions/{id}/export?format=markdown` | Export session as Markdown |
| `GET` | `/sessions/{id}/export?format=json` | Export session as JSON |
| `GET` | `/settings` | Get current runtime settings |
| `POST` | `/settings` | Update runtime settings |
| `GET` | `/api/audio/devices` | List PulseAudio sources and sinks |
| `POST` | `/api/recording/start` | Start backend recording |
| `POST` | `/api/recording/stop` | Stop backend recording |
| `GET` | `/api/recording/status` | Current recording status |
| `GET` | `/debug` | Internal state dump |
| `WS` | `/ws/audio` | Stream raw PCM audio (browser mode only) |
| `WS` | `/ws/control` | Send control messages, receive reasoning results |

## WebSocket Protocol

**Audio stream** (`/ws/audio`): Used in `browser` or `both` capture modes. Send raw PCM bytes — 16 kHz, 16-bit, mono, little-endian.

**Control messages** (send to `/ws/control`):
```json
{ "type": "request_reply", "context_hint": "optional hint" }
{ "type": "custom_prompt", "prompt": "What decisions were made?" }
```

**Server messages** (received on `/ws/control`):
```json
{ "type": "transcript_segment", "text": "...", "speaker": "Me", "timestamp_start": 0.0, "timestamp_end": 2.5, "is_partial": false }
{ "type": "summary_update", "summary": "..." }
{ "type": "action_items_update", "items": [{ "id": "...", "description": "...", "assignee": null, "status": "new" }] }
{ "type": "contradiction_alert", "statement_a": "...", "statement_b": "...", "severity": "medium", "explanation": "..." }
{ "type": "reply_suggestion", "suggestions": ["...", "..."], "triggered_by": "manual" }
{ "type": "custom_prompt_result", "prompt": "...", "result": "...", "timestamp": 1234567890.0 }
{ "type": "recording_error", "message": "ffmpeg process crashed" }
```

## Development

```bash
# Run all backend tests
source .venv/bin/activate
pytest

# Run frontend dev server with hot reload
cd frontend && npm start

# Build frontend for production
cd frontend && npm run build
```

## Architecture

See [ARCHITECTURE.md](../ARCHITECTURE.md) for the full system design, data models, and prompt templates.
