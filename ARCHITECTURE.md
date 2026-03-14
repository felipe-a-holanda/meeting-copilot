# Meeting Copilot — Real-Time AI Reasoning for Meetings

## Project Overview

A real-time meeting copilot that transcribes, attributes speakers, summarizes, extracts action items, detects contradictions, and suggests replies — all while the meeting is happening. Built with a local-first approach (Whisper + Ollama), with optional API fallback for heavier reasoning tasks.

### Core Requirements

- **Real-time transcription** with per-stream speaker labels (Me / Them)
- **Progressive summarization** that condenses as the meeting progresses
- **Action item / decision extraction** updated live
- **Contextual alerts** (contradictions, topic drift, unresolved questions)
- **Interactive copilot** — reply suggestions, custom prompts against meeting context
- **Local-first**: transcription and basic reasoning run locally; LLM API optional for advanced reasoning
- **Privacy**: no audio or transcript leaves the machine unless explicitly configured

---

## Architecture

### High-Level Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                        FRONTEND (React)                     │
│                                                             │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────────────┐│
│  │ Audio    │  │ Live         │  │ Copilot Panel          ││
│  │ Controls │  │ Transcript   │  │ - Summary              ││
│  │ (REST    │  │ Panel        │  │ - Action Items         ││
│  │  API)    │  │ (per-speaker)│  │ - Contradictions       ││
│  └────┬─────┘  └──────▲───────┘  │ - Reply Suggestions    ││
│       │               │          │ - Custom Prompt Input   ││
│       │ REST calls    │ segments └────────────▲────────────┘│
│       │               │ (WebSocket)           │ (WebSocket) │
└───────┼───────────────┼───────────────────────┼─────────────┘
        │               │                       │
        ▼               │                       │
┌───────────────────────┴───────────────────────┴─────────────┐
│                     BACKEND (FastAPI)                        │
│                                                             │
│  ┌──────────────────────────────────────────────────┐       │
│  │  Audio Capture (dual mode)                        │       │
│  │                                                   │       │
│  │  Mode A: Backend (primary)                        │       │
│  │  ┌─────────────────────────────────────────────┐ │       │
│  │  │ AudioRecorder (ffmpeg + PulseAudio)          │ │       │
│  │  │  ├─ mic source                               │ │       │
│  │  │  └─ sink.monitor (system audio)              │ │       │
│  │  │  → REST: /api/recording/start|stop|status    │ │       │
│  │  └─────────────────────────────────────────────┘ │       │
│  │                                                   │       │
│  │  Mode B: Browser (fallback)                       │       │
│  │  ┌─────────────────────────────────────────────┐ │       │
│  │  │ WebSocket /ws/audio ← browser getUserMedia   │ │       │
│  │  │ (mic only, no system audio)                  │ │       │
│  │  └─────────────────────────────────────────────┘ │       │
│  └───────────────────────┬──────────────────────────┘       │
│                          ▼                                   │
│  ┌──────────────────────────────────┐                       │
│  │     AudioPipeline                 │                       │
│  │  VAD (Silero) → Whisper (per-stream)│                     │
│  └──────────────┬───────────────────┘                       │
│                 ▼                                            │
│  ┌──────────────────────────────────┐                       │
│  │     ContextManager                │                       │
│  │  MeetingState accumulation        │                       │
│  │  + Trigger-based LLM workers      │                       │
│  └──────────────┬───────────────────┘                       │
│                 ▼                                            │
│  ┌──────────────────────────────────┐                       │
│  │     LLM Dispatcher                │                       │
│  │  Ollama (local) │ Claude API      │                       │
│  └──────────────────────────────────┘                       │
│                                                             │
│  ┌──────────────────────────────────┐                       │
│  │     Storage (SQLite)              │                       │
│  │  Sessions, segments, state        │                       │
│  └──────────────────────────────────┘                       │
└─────────────────────────────────────────────────────────────┘
```

### Audio Capture Modes

The system supports two audio capture modes, configured via `audio_capture_mode`:

| Mode | Source | Captures System Audio | Requires |
|------|--------|-----------------------|----------|
| `backend` (primary) | PulseAudio via ffmpeg | Yes (mic + system) | Linux, PulseAudio, ffmpeg |
| `browser` (fallback) | `getUserMedia()` via WebSocket | No (mic only) | Modern browser |

**Backend mode** is preferred because it captures both the user's microphone and system audio (the other side of the meeting from Zoom, Meet, Teams, etc.) using PulseAudio monitor sources.

**Browser mode** is kept for backward compatibility and environments where PulseAudio is unavailable.

---

## Directory Structure

```
meeting-copilot/
├── README.md
├── pyproject.toml
├── docker-compose.yml
│
├── backend/
│   ├── main.py                     # FastAPI app entry point + all routes
│   ├── config.py                   # Settings (models, thresholds, API keys, audio capture)
│   ├── cli.py                      # Standalone CLI for testing pipeline against audio files
│   │
│   ├── audio/
│   │   ├── __init__.py
│   │   ├── pipeline.py             # AudioPipeline: VAD → Whisper (per-stream) → segments
│   │   ├── vad.py                  # Voice Activity Detection (Silero)
│   │   ├── transcriber.py          # faster-whisper wrapper
│   │   ├── recorder.py             # AudioRecorder: two ffmpeg processes (mic + monitor)
│   │   └── file_processor.py       # Batch processing of uploaded audio files
│   │
│   ├── reasoning/
│   │   ├── __init__.py
│   │   ├── context_manager.py      # Meeting state accumulator + trigger logic
│   │   ├── dispatcher.py           # Routes tasks to Ollama or Claude API
│   │   ├── prompts.py              # All LLM prompt templates
│   │   └── workers/
│   │       ├── __init__.py
│   │       ├── base.py             # BaseWorker abstract class
│   │       ├── summary.py          # Progressive summarization
│   │       ├── action_items.py     # Decision & action extraction
│   │       ├── contradictions.py   # Contradiction detection
│   │       ├── reply.py            # Reply suggestion generation
│   │       └── custom.py           # User-defined prompt execution
│   │
│   ├── ws/
│   │   ├── __init__.py
│   │   ├── gateway.py              # WebSocket connection manager
│   │   └── protocol.py             # Message types and serialization
│   │
│   └── storage/
│       ├── __init__.py
│       └── session.py              # Session persistence (SQLite via aiosqlite)
│
├── frontend/
│   ├── package.json
│   ├── src/
│   │   ├── App.tsx                 # Root component, WebSocket connections, state
│   │   ├── hooks/
│   │   │   ├── useAudioCapture.ts  # Browser mic capture (getUserMedia + PCM)
│   │   │   ├── useWebSocket.ts     # WS connection with auto-reconnect
│   │   │   └── useMeetingState.ts  # Reducer-based meeting state management
│   │   ├── components/
│   │   │   ├── AudioControls.tsx   # Start/stop recording, connection status
│   │   │   ├── TranscriptPanel.tsx # Live transcript with speaker labels
│   │   │   ├── CopilotPanel.tsx    # Summary + actions + alerts
│   │   │   ├── ReplyPanel.tsx      # Reply suggestions
│   │   │   ├── PromptInput.tsx     # Custom prompt input
│   │   │   ├── SessionSidebar.tsx  # Past sessions list
│   │   │   ├── SettingsPanel.tsx   # Settings overlay
│   │   │   ├── DebugPanel.tsx      # Live debug overlay (WS stats, chunks)
│   │   │   └── ErrorToast.tsx      # Toast notification system
│   │   ├── types/
│   │   │   └── messages.ts         # TS interfaces mirroring backend protocol
│   │   └── utils/
│   │       └── speakerColors.ts    # Speaker → color mapping
│   │
│   └── tailwind.config.js
│
└── scripts/
    ├── setup.sh                    # Install deps + download models
    └── download_models.sh          # Pre-download Whisper models
```

---

## Core Data Models

### WebSocket Protocol Messages

```python
# backend/ws/protocol.py
from pydantic import BaseModel
from typing import Literal, Optional
from datetime import datetime

# === Audio Pipeline → Frontend ===

class TranscriptSegment(BaseModel):
    """A single transcribed segment with speaker info."""
    type: Literal["transcript_segment"] = "transcript_segment"
    speaker: str                    # "Speaker 1", "Speaker 2", etc.
    text: str
    timestamp_start: float          # seconds from meeting start
    timestamp_end: float
    language: str = "pt"
    is_partial: bool = False        # True if segment is still being transcribed

# === Reasoning Engine → Frontend ===

class SummaryUpdate(BaseModel):
    type: Literal["summary_update"] = "summary_update"
    summary: str                    # Full progressive summary (replaces previous)
    covered_until: float            # Timestamp coverage

class ActionItem(BaseModel):
    id: str
    description: str
    assignee: Optional[str] = None  # Speaker name if identifiable
    source_timestamp: float
    status: Literal["new", "updated", "completed"] = "new"

class ActionItemsUpdate(BaseModel):
    type: Literal["action_items_update"] = "action_items_update"
    items: list[ActionItem]

class ContradictionAlert(BaseModel):
    type: Literal["contradiction_alert"] = "contradiction_alert"
    description: str
    statement_a: str
    statement_a_timestamp: float
    statement_b: str
    statement_b_timestamp: float
    severity: Literal["low", "medium", "high"]

class ReplySuggestion(BaseModel):
    type: Literal["reply_suggestion"] = "reply_suggestion"
    suggestions: list[str]          # 2-3 suggested replies
    context: str                    # What triggered the suggestion
    triggered_by: Literal["auto", "manual"]

class CustomPromptResult(BaseModel):
    type: Literal["custom_prompt_result"] = "custom_prompt_result"
    prompt: str                     # Original user prompt
    result: str                     # LLM response
    timestamp: float

# === Frontend → Backend ===

class RequestReplySuggestion(BaseModel):
    type: Literal["request_reply"] = "request_reply"
    context_hint: Optional[str] = None

class CustomPromptRequest(BaseModel):
    type: Literal["custom_prompt"] = "custom_prompt"
    prompt: str
```

### Meeting State (Context Manager)

```python
# backend/reasoning/context_manager.py
from dataclasses import dataclass, field
from collections import deque

@dataclass
class MeetingState:
    """Accumulated state of the meeting, fed to LLM workers."""
    session_id: str
    start_time: float

    segments: list[TranscriptSegment] = field(default_factory=list)
    speakers: set[str] = field(default_factory=set)
    current_summary: str = ""
    action_items: list[ActionItem] = field(default_factory=list)
    recent_window: deque = field(default_factory=lambda: deque(maxlen=50))

    segments_since_last_summary: int = 0
    segments_since_last_action_scan: int = 0

    def add_segment(self, segment: TranscriptSegment):
        self.segments.append(segment)
        self.recent_window.append(segment)
        self.speakers.add(segment.speaker)
        self.segments_since_last_summary += 1
        self.segments_since_last_action_scan += 1

    def get_transcript_text(self, last_n: int = None) -> str:
        source = list(self.recent_window) if last_n else self.segments
        if last_n:
            source = source[-last_n:]
        return "\n".join(
            f"[{s.speaker} @ {s.timestamp_start:.0f}s]: {s.text}"
            for s in source
        )

    def get_full_context(self) -> str:
        parts = []
        if self.current_summary:
            parts.append(f"## Summary So Far\n{self.current_summary}")
        if self.action_items:
            items_text = "\n".join(f"- {a.description} (assigned: {a.assignee or 'TBD'})" for a in self.action_items)
            parts.append(f"## Action Items\n{items_text}")
        parts.append(f"## Recent Transcript\n{self.get_transcript_text(last_n=30)}")
        return "\n\n".join(parts)
```

---

## Audio Capture

### Backend Capture: AudioRecorder

The primary audio capture method. Uses PulseAudio + ffmpeg to capture both microphone and system audio on the server side.

**Location**: `backend/audio/recorder.py`

**Responsibilities**:
1. Discover PulseAudio devices via `pactl`
2. Launch ffmpeg subprocess capturing mic + system monitor, pipe PCM to stdout
3. Feed PCM chunks to `AudioPipeline.process_audio_chunk()` in an asyncio loop
4. Stop recording (SIGINT to ffmpeg, graceful shutdown)
5. Optionally save mixed audio to a WAV file

```python
class AudioRecorder:
    """Captures mic + system audio via PulseAudio/ffmpeg and feeds the pipeline."""

    def __init__(self, pipeline: AudioPipeline, config: Settings): ...
    async def list_devices(self) -> dict: ...
    async def start(
        self,
        mic_source: str | None = None,
        monitor_source: str | None = None,
        save_to_file: Path | None = None,
        mic_volume: float = 2.0,
    ) -> None: ...
    async def stop(self) -> dict: ...
    @property
    def is_recording(self) -> bool: ...
```

**ffmpeg commands** — two separate processes, one per stream:

```bash
# Mic process (speaker_label="Me")
ffmpeg -f pulse -i <mic_source> -ar 16000 -ac 1 -f s16le pipe:1

# Monitor process (speaker_label="Them")
ffmpeg -f pulse -i <monitor_source> -ar 16000 -ac 1 -f s16le pipe:1
```

Each process pipes raw int16 PCM to stdout. The mic reader calls
`pipeline.process_audio_chunk(chunk, speaker_label="Me")` and the monitor
reader calls `pipeline.process_audio_chunk(chunk, speaker_label="Them")`.
Speaker attribution is exact — no ML required.

### Browser Capture (Fallback)

The frontend hook `useAudioCapture.ts` uses `navigator.mediaDevices.getUserMedia()` to capture microphone audio, converts float32 to int16 PCM via `ScriptProcessorNode`, and streams binary chunks over the `/ws/audio` WebSocket.

Limitations: mic only (no system audio), depends on browser tab staying open.

---

## REST API Endpoints

### Recording Control (backend capture mode)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/audio/devices` | List PulseAudio sources and sinks |
| `POST` | `/api/recording/start` | Start recording (creates session, launches ffmpeg) |
| `POST` | `/api/recording/stop` | Stop recording (flushes pipeline, finalizes session) |
| `GET` | `/api/recording/status` | Current recording state |

### Sessions

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/sessions` | Create a new session |
| `GET` | `/sessions` | List all sessions |
| `GET` | `/sessions/{id}` | Get session details |
| `GET` | `/sessions/{id}/export` | Export session (markdown/JSON) |
| `POST` | `/sessions/{id}/upload-audio` | Upload audio file for batch processing |

### Other

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/debug` | Debug info (WS stats, chunk counts) |
| `GET` | `/settings` | Get current settings |
| `POST` | `/settings` | Update settings |

### WebSocket Endpoints

| Path | Direction | Format | Description |
|------|-----------|--------|-------------|
| `/ws/audio` | Client → Server | Binary (int16 PCM) | Browser audio streaming (fallback mode) |
| `/ws/control` | Bidirectional | JSON | Transcript/insights broadcast + user commands |

---

## LLM Prompt Templates

```python
# backend/reasoning/prompts.py

PROGRESSIVE_SUMMARY = """You are a meeting assistant. You maintain a running summary of a meeting.

Current summary (what has been discussed so far):
{current_summary}

New transcript segments since last update:
{new_segments}

Update the summary to incorporate the new information. Rules:
- Keep the summary concise (max 300 words)
- Preserve key decisions and important points from the existing summary
- Add new topics, decisions, and important statements
- Use bullet points grouped by topic
- Note who said what when relevant
- Write in the same language as the transcript
- If the meeting language is Portuguese, write the summary in Portuguese

Updated summary:"""

ACTION_ITEMS = """You are a meeting assistant that extracts action items and decisions.

Meeting context:
{full_context}

Recent transcript:
{recent_transcript}

Existing action items:
{existing_items}

Extract any NEW action items or decisions from the recent transcript. For each:
- description: What needs to be done or what was decided
- assignee: Who is responsible (use speaker label if clear, "TBD" if not)
- type: "action" or "decision"

Also check if any existing items should be marked as "completed" or "updated".

Respond in JSON format:
{{
  "new_items": [
    {{"description": "...", "assignee": "...", "type": "action"}}
  ],
  "updated_items": [
    {{"id": "...", "status": "completed", "note": "..."}}
  ]
}}"""

CONTRADICTION_DETECTION = """You are a meeting analyst detecting contradictions and inconsistencies.

Meeting summary so far:
{current_summary}

Recent transcript (last 2 minutes):
{recent_transcript}

Identify any contradictions where a speaker says something that conflicts with:
1. Something they said earlier
2. Something another speaker said
3. A decision that was already made

Only flag CLEAR contradictions, not minor clarifications or evolving discussions.

If contradictions found, respond in JSON:
{{
  "contradictions": [
    {{
      "description": "Brief description of the contradiction",
      "statement_a": "Earlier statement",
      "statement_b": "Contradicting statement",
      "severity": "low|medium|high"
    }}
  ]
}}

If no contradictions, respond: {{"contradictions": []}}"""

REPLY_SUGGESTION = """You are a meeting copilot helping the user participate more effectively.

Meeting context:
{full_context}

The user wants help responding to the current discussion.
{context_hint}

Generate 2-3 short reply suggestions the user could say. Consider:
- What was just discussed
- Any open questions that need answering
- Opportunities to clarify or add value
- The overall tone of the meeting

Respond in JSON:
{{
  "suggestions": [
    "Suggestion 1 — direct and concise",
    "Suggestion 2 — alternative angle",
    "Suggestion 3 — diplomatic/cautious option"
  ],
  "context": "Brief note on what triggered these suggestions"
}}"""

CUSTOM_PROMPT_TEMPLATE = """You are a meeting copilot with full context of the ongoing meeting.

Meeting context:
{full_context}

The user asks: {user_prompt}

Respond helpfully based on the meeting context. Be concise and actionable."""
```

---

## Key Implementation Details

### 1. Audio Pipeline

```python
# backend/audio/pipeline.py
class AudioPipeline:
    """VAD → Whisper (per-stream) pipeline. Accepts raw int16 PCM bytes."""

    def __init__(self, config): ...
    def on_segment(self, callback): ...
    async def process_audio_chunk(self, chunk: bytes, speaker_label: str = "Speaker"):
        """Feed raw PCM audio data. Buffers until 1s of audio, then:
        1. Run Silero VAD — discard if no speech
        2. Transcribe via faster-whisper
        3. Emit TranscriptSegment with the provided speaker_label
        """
```

### 2. Context Manager (Trigger Logic)

Accumulates `MeetingState` and fires LLM workers based on thresholds:

| Worker | Trigger | Task |
|--------|---------|------|
| SummaryWorker | Every 10 segments | Progressive summarization |
| ActionItemWorker | Every 5 segments | Extract/update action items |
| ContradictionWorker | Every 120 seconds | Detect contradictions |
| ReplyWorker | On-demand (user request) | Generate reply suggestions |
| CustomPromptWorker | On-demand (user request) | Execute custom prompt |

Workers run as fire-and-forget `asyncio.Task`s — they don't block the audio pipeline.

### 3. LLM Dispatcher (Ollama + API Fallback)

Routes reasoning tasks to the best available backend:

- **Light tasks** (summary, action items): Ollama local model (e.g., `llama3.1:8b`)
- **Heavy tasks** (contradictions, reply, custom): Claude API if enabled, else Ollama heavy model (e.g., `llama3.1:70b`)

```python
class LLMDispatcher:
    async def run(self, task_name: str, **kwargs) -> str:
        prompt = PROMPT_MAP[task_name].format(**kwargs)
        if task_name in HEAVY_TASKS and self.use_api_fallback:
            try:
                return await self._call_claude(prompt)
            except Exception:
                pass  # Fallback to local
        return await self._call_ollama(prompt, heavy=task_name in HEAVY_TASKS)
```

### 4. WebSocket Gateway

```python
class ConnectionManager:
    """Manages WebSocket connections and JSON broadcasting."""
    async def connect(self, websocket: WebSocket): ...
    def disconnect(self, websocket: WebSocket): ...
    async def broadcast(self, message: dict): ...
```

### 5. Storage (SQLite)

```python
class SessionStore:
    """aiosqlite-backed persistence. Tables: sessions, segments, meeting_state."""
    async def create_session(self, title: str) -> str: ...
    async def save_segment(self, session_id: str, segment: TranscriptSegment): ...
    async def save_state(self, session_id: str, state: MeetingState): ...
    async def load_session(self, session_id: str) -> dict: ...
    async def list_sessions(self) -> list: ...
```

---

## Data Flow

### Backend Capture Mode (primary)

1. User clicks **Start** in frontend → `POST /api/recording/start`
2. Backend creates session, launches ffmpeg subprocess (mic + system monitor)
3. ffmpeg streams mixed PCM to stdout → backend reads in asyncio loop
4. `AudioPipeline.process_audio_chunk()` receives PCM chunks
5. Pipeline: VAD → Whisper → emits `TranscriptSegment` (speaker label from stream)
6. `ContextManager` accumulates segments → triggers LLM workers
7. WebSocket `/ws/control` broadcasts transcripts + insights to frontend
8. User clicks **Stop** → `POST /api/recording/stop` → ffmpeg stops → pipeline flushes

### Browser Capture Mode (fallback)

1. Frontend calls `getUserMedia()` → captures mic audio
2. `ScriptProcessorNode` converts float32 → int16 PCM
3. Binary chunks sent over WebSocket `/ws/audio`
4. Backend `AudioPipeline.process_audio_chunk()` receives chunks
5. Steps 5-7 same as above

---

## Configuration

```python
# backend/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Audio Pipeline
    whisper_model: str = "large-v3-turbo"
    language: str = "pt"

    # Audio Capture (backend mode)
    audio_capture_mode: str = "backend"     # "backend" | "browser" | "both"
    recordings_dir: str = "./recordings"
    mic_volume: float = 2.0
    default_mic_source: str = ""            # Empty = auto-detect via pactl
    default_monitor_source: str = ""        # Empty = auto-detect via pactl
    save_recordings: bool = True

    # LLM - Local
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    ollama_heavy_model: str = "llama3.1:70b"

    # LLM - API Fallback
    use_api_fallback: bool = False
    anthropic_api_key: str = ""

    # Reasoning Triggers
    summary_every_n_segments: int = 10
    action_scan_every_n_segments: int = 5
    contradiction_check_seconds: int = 120

    # Server
    ws_host: str = "0.0.0.0"
    ws_port: int = 8000

    class Config:
        env_file = ".env"
```

---

## Setup & Dependencies

### System Dependencies

- **Python 3.11+**
- **ffmpeg** — audio processing and backend capture
- **PulseAudio** (`pactl` from `pulseaudio-utils` or `pipewire-pulse`) — for backend audio capture
- **Node.js 18+** — frontend build
- **Ollama** — local LLM inference

### Python Dependencies (pyproject.toml)

```toml
[project]
name = "meeting-copilot"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
    "websockets>=12.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "httpx>=0.27",
    "faster-whisper>=1.0",
    "silero-vad>=4.0",
    "anthropic>=0.40",
    "aiosqlite>=0.20",
]
```

---

## Known Considerations & Tradeoffs

1. **Whisper latency vs accuracy**: `large-v3` gives best accuracy but adds ~2-3s latency. `large-v3-turbo` is the current default for a good balance. For faster response, use `medium` or `small`.

2. **Dual-stream speaker attribution**: mic stream is always "Me", monitor stream is always "Them". This gives 100% accurate two-party labelling at zero ML cost, but cannot distinguish individual remote speakers in a multi-person call (all remote audio is labelled "Them"). For meetings with multiple distinct remote speakers, a future optional diarization pass on the monitor stream could be added.

3. **LLM context window growth**: As meetings get longer (1h+), the full transcript exceeds context windows. The progressive summary pattern mitigates this — the LLM sees summary + recent_window, not the full transcript.

4. **Ollama concurrency**: Running multiple LLM tasks simultaneously on a single GPU causes queuing. The trigger thresholds should be tuned to avoid overwhelming the inference server.

5. **Reply suggestions sensitivity**: Auto-generating replies needs careful tuning to avoid being distracting. Start with manual-only (user clicks "suggest reply") before enabling auto-trigger.

6. **Portuguese language support**: Whisper `large-v3` handles Portuguese well. For LLM reasoning, ensure Ollama model handles PT (Llama 3.1 does). Include language instruction in all prompts.

7. **Backend audio capture is Linux-only**: PulseAudio/PipeWire is Linux-specific. macOS would need BlackHole, Windows would need VB-Cable. Browser fallback mode works cross-platform.
