# Meeting Copilot

Real-time AI assistant for meetings. Captures audio, transcribes speech, identifies speakers, and runs LLM reasoning to produce live summaries, action items, contradiction alerts, and reply suggestions.

## Features

- Real-time transcription via faster-whisper
- Speaker diarization via pyannote.audio
- Progressive summarization, action item extraction, contradiction detection
- Reply suggestions and custom prompts via Ollama (local) or Claude API
- Session persistence — browse and export past meetings
- React frontend with dark mode, mobile layout, WebSocket status indicators

## Requirements

- Python 3.11+
- Node 18+ (for frontend)
- [Ollama](https://ollama.com) running locally (for LLM inference)
- HuggingFace token (for pyannote diarization models)

## Quick Start (Local)

```bash
# 1. Clone the repo and enter the project directory
cd meeting-copilot

# 2. Run setup (creates venv, installs deps, copies .env)
bash scripts/setup.sh

# 3. Edit .env — set HF_TOKEN (required for diarization) and optionally ANTHROPIC_API_KEY
nano .env

# 4. Start backend
source .venv/bin/activate
uvicorn backend.main:app --reload

# 5. Start frontend (separate terminal)
cd frontend && npm start
```

Open http://localhost:3000 in your browser.

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

## Configuration

All settings are in `.env`. Copy `.env.example` to `.env` to start.

| Variable | Default | Description |
|---|---|---|
| `WHISPER_MODEL` | `large-v3` | Whisper model size: `tiny`, `base`, `small`, `medium`, `large-v2`, `large-v3` |
| `LANGUAGE` | `pt` | Transcription language (ISO 639-1). Leave blank for auto-detect. |
| `ENABLE_DIARIZATION` | `true` | Speaker diarization (requires `HF_TOKEN`) |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `llama3.1:8b` | Model for routine tasks |
| `OLLAMA_HEAVY_MODEL` | `llama3.1:70b` | Model for complex reasoning (falls back to `OLLAMA_MODEL`) |
| `USE_API_FALLBACK` | `false` | Use Claude API when Ollama fails |
| `ANTHROPIC_API_KEY` | — | Required when `USE_API_FALLBACK=true` |
| `HF_TOKEN` | — | HuggingFace token for pyannote models |
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
| `WS` | `/ws/audio` | Stream raw PCM audio (16kHz, 16-bit, mono) |
| `WS` | `/ws/control` | Send control messages, receive reasoning results |

## WebSocket Protocol

**Audio stream** (`/ws/audio`): Send raw PCM bytes — 16 kHz, 16-bit, mono, little-endian.

**Control messages** (send to `/ws/control`):
```json
{ "type": "request_reply", "context_hint": "optional hint" }
{ "type": "custom_prompt", "prompt": "What decisions were made?" }
```

**Server messages** (received on `/ws/control`):
```json
{ "type": "transcript_segment", "text": "...", "speaker": "Speaker_0", "timestamp_start": 0.0, "timestamp_end": 2.5, "is_partial": false }
{ "type": "summary_update", "summary": "..." }
{ "type": "action_items_update", "items": [{ "id": "...", "description": "...", "assignee": null, "status": "new" }] }
{ "type": "contradiction_alert", "statement_a": "...", "statement_b": "...", "severity": "medium", "explanation": "..." }
{ "type": "reply_suggestion", "suggestions": ["...", "..."], "triggered_by": "manual" }
{ "type": "custom_prompt_result", "prompt": "...", "result": "...", "timestamp": 1234567890.0 }
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
