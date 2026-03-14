# Meeting Copilot — Real-Time AI Reasoning for Meetings

## Project Overview

A real-time meeting copilot that transcribes, diarizes, summarizes, extracts action items, detects contradictions, and suggests replies — all while the meeting is happening. Built with a local-first approach (Whisper + Ollama), with optional API fallback for heavier reasoning tasks.

### Core Requirements

- **Real-time transcription** with speaker diarization (who said what)
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
│  │ Capture  │  │ Transcript   │  │ - Summary              ││
│  │ (WebAudio│  │ Panel        │  │ - Action Items         ││
│  │  API)    │  │ (per-speaker)│  │ - Contradictions       ││
│  └────┬─────┘  └──────▲───────┘  │ - Reply Suggestions    ││
│       │               │          │ - Custom Prompt Input   ││
│       │ audio chunks  │ segments └────────────▲────────────┘│
│       │ (WebSocket)   │ (WebSocket)           │ (WebSocket) │
└───────┼───────────────┼───────────────────────┼─────────────┘
        │               │                       │
        ▼               │                       │
┌───────────────────────┴───────────────────────┴─────────────┐
│                     BACKEND (FastAPI)                        │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              WebSocket Gateway                       │    │
│  │  - Receives audio chunks from frontend               │    │
│  │  - Broadcasts transcription segments to frontend     │    │
│  │  - Broadcasts reasoning outputs to frontend          │    │
│  └──────────┬──────────────────────────────┬────────────┘    │
│             │                              │                 │
│             ▼                              ▼                 │
│  ┌──────────────────────┐    ┌──────────────────────────┐   │
│  │  AUDIO PIPELINE      │    │  REASONING ENGINE         │   │
│  │                      │    │                            │   │
│  │  WhisperLiveKit      │    │  Context Manager           │   │
│  │  ├─ faster-whisper   │───▶│  ├─ Accumulates segments   │   │
│  │  ├─ VAD (Silero)     │    │  ├─ Maintains meeting state│   │
│  │  └─ Diarization      │    │  └─ Triggers LLM tasks     │   │
│  │     (pyannote)       │    │                            │   │
│  │                      │    │  LLM Dispatcher             │   │
│  │  Output:             │    │  ├─ Ollama (local)          │   │
│  │  {speaker, text,     │    │  └─ Claude API (fallback)   │   │
│  │   timestamp, lang}   │    │                            │   │
│  └──────────────────────┘    │  Task Workers:              │   │
│                              │  ├─ SummaryWorker           │   │
│                              │  ├─ ActionItemWorker        │   │
│                              │  ├─ ContradictionWorker     │   │
│                              │  ├─ ReplyWorker             │   │
│                              │  └─ CustomPromptWorker      │   │
│                              └──────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
        │                              │
        ▼                              ▼
┌────────────────┐          ┌────────────────────┐
│  faster-whisper│          │  Ollama (local)     │
│  (local model) │          │  └─ llama3.1:8b     │
│  └─ large-v3  │          │  └─ llama3.1:70b    │
└────────────────┘          │  OR                 │
                            │  Claude API         │
                            │  (remote fallback)  │
                            └────────────────────┘
```

### Data Flow

1. **Frontend** captures audio via WebAudio API → sends PCM chunks over WebSocket
2. **Audio Pipeline** receives chunks → runs VAD → transcribes with Whisper → diarizes
3. **Audio Pipeline** emits `TranscriptSegment` events to **Context Manager**
4. **Context Manager** appends to meeting state → evaluates trigger conditions → dispatches LLM tasks
5. **Task Workers** run LLM inference (local or API) → emit results back through WebSocket
6. **Frontend** receives and renders all outputs in real-time

---

## Directory Structure

```
meeting-copilot/
├── README.md
├── pyproject.toml
├── docker-compose.yml              # Ollama + app (optional)
│
├── backend/
│   ├── main.py                     # FastAPI app entry point
│   ├── config.py                   # Settings (models, thresholds, API keys)
│   │
│   ├── audio/
│   │   ├── __init__.py
│   │   ├── pipeline.py             # WhisperLiveKit integration
│   │   ├── vad.py                  # Voice Activity Detection (Silero)
│   │   ├── transcriber.py          # faster-whisper streaming wrapper
│   │   └── diarizer.py             # pyannote speaker diarization
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
│       └── session.py              # Meeting session persistence (SQLite)
│
├── frontend/
│   ├── package.json
│   ├── src/
│   │   ├── App.tsx
│   │   ├── hooks/
│   │   │   ├── useAudioCapture.ts  # WebAudio API + PCM encoding
│   │   │   ├── useWebSocket.ts     # WS connection + reconnection
│   │   │   └── useMeetingState.ts  # Frontend state management
│   │   ├── components/
│   │   │   ├── TranscriptPanel.tsx  # Live transcript with speaker labels
│   │   │   ├── CopilotPanel.tsx    # Summary + actions + alerts
│   │   │   ├── ReplyPanel.tsx      # Reply suggestions
│   │   │   ├── PromptInput.tsx     # Custom prompt input
│   │   │   └── AudioControls.tsx   # Start/stop/settings
│   │   └── types/
│   │       └── messages.ts         # Shared message type definitions
│   │
│   └── tailwind.config.js
│
└── scripts/
    ├── setup.sh                    # Install dependencies + download models
    └── download_models.sh          # Pre-download Whisper + pyannote models
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
    context_hint: Optional[str] = None  # Optional user hint

class CustomPromptRequest(BaseModel):
    type: Literal["custom_prompt"] = "custom_prompt"
    prompt: str                     # User's custom prompt
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
    
    # Raw transcript segments (full history)
    segments: list[TranscriptSegment] = field(default_factory=list)
    
    # Identified speakers
    speakers: set[str] = field(default_factory=set)
    
    # Current progressive summary
    current_summary: str = ""
    
    # Running action items
    action_items: list[ActionItem] = field(default_factory=list)
    
    # Recent segments window (for contradiction detection, reply suggestions)
    recent_window: deque = field(default_factory=lambda: deque(maxlen=50))
    
    # Counters for trigger logic
    segments_since_last_summary: int = 0
    segments_since_last_action_scan: int = 0

    def add_segment(self, segment: TranscriptSegment):
        self.segments.append(segment)
        self.recent_window.append(segment)
        self.speakers.add(segment.speaker)
        self.segments_since_last_summary += 1
        self.segments_since_last_action_scan += 1

    def get_transcript_text(self, last_n: int = None) -> str:
        """Returns formatted transcript for LLM context."""
        source = list(self.recent_window) if last_n else self.segments
        if last_n:
            source = source[-last_n:]
        return "\n".join(
            f"[{s.speaker} @ {s.timestamp_start:.0f}s]: {s.text}"
            for s in source
        )

    def get_full_context(self) -> str:
        """Returns complete context string for LLM prompts."""
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

### 1. Audio Pipeline (WhisperLiveKit Integration)

```python
# backend/audio/pipeline.py
import asyncio
from whisperlivekit import WhisperLiveKit, TranscriptionConfig

class AudioPipeline:
    """Wraps WhisperLiveKit for streaming transcription + diarization."""
    
    def __init__(self, config):
        self.config = config
        self.kit = WhisperLiveKit(
            model_size=config.whisper_model,       # "large-v3"
            backend="faster-whisper",
            language=config.language,               # "pt" or None for auto
            diarization=config.enable_diarization,  # True
        )
        self._segment_callback = None
    
    def on_segment(self, callback):
        """Register callback for new transcript segments."""
        self._segment_callback = callback
    
    async def process_audio_chunk(self, chunk: bytes):
        """Feed raw PCM audio data into the pipeline."""
        results = await self.kit.process(chunk)
        for result in results:
            if self._segment_callback and not result.is_partial:
                segment = TranscriptSegment(
                    speaker=result.speaker or "Unknown",
                    text=result.text,
                    timestamp_start=result.start,
                    timestamp_end=result.end,
                    language=result.language or self.config.language,
                    is_partial=result.is_partial,
                )
                await self._segment_callback(segment)
```

### 2. Context Manager (Trigger Logic)

```python
# backend/reasoning/context_manager.py
import asyncio
from .dispatcher import LLMDispatcher

class ContextManager:
    """Manages meeting state and triggers reasoning tasks."""
    
    # Trigger thresholds
    SUMMARY_EVERY_N_SEGMENTS = 10       # Summarize every 10 new segments
    ACTION_SCAN_EVERY_N_SEGMENTS = 5    # Scan for actions every 5 segments
    CONTRADICTION_CHECK_SECONDS = 120   # Check contradictions every 2 minutes
    
    def __init__(self, dispatcher: LLMDispatcher, broadcast_fn):
        self.state = MeetingState(session_id="", start_time=0)
        self.dispatcher = dispatcher
        self.broadcast = broadcast_fn   # async fn to send WS messages
        self._running_tasks: set[asyncio.Task] = set()
    
    async def on_new_segment(self, segment: TranscriptSegment):
        """Called by AudioPipeline when a new segment is finalized."""
        self.state.add_segment(segment)
        
        # Broadcast raw transcript to frontend
        await self.broadcast(segment.model_dump())
        
        # Check triggers (non-blocking — fire and forget)
        if self.state.segments_since_last_summary >= self.SUMMARY_EVERY_N_SEGMENTS:
            self._fire_task(self._run_summary())
            self.state.segments_since_last_summary = 0
        
        if self.state.segments_since_last_action_scan >= self.ACTION_SCAN_EVERY_N_SEGMENTS:
            self._fire_task(self._run_action_items())
            self.state.segments_since_last_action_scan = 0
        
        # Contradiction detection runs on a time-based trigger (see _contradiction_loop)
    
    async def handle_custom_prompt(self, prompt: str):
        """Handle user's custom prompt against meeting context."""
        result = await self.dispatcher.run(
            "custom",
            full_context=self.state.get_full_context(),
            user_prompt=prompt,
        )
        await self.broadcast(CustomPromptResult(
            prompt=prompt,
            result=result,
            timestamp=self.state.segments[-1].timestamp_end if self.state.segments else 0,
        ).model_dump())
    
    async def handle_reply_request(self, context_hint: str = ""):
        """Generate reply suggestions on demand."""
        result = await self.dispatcher.run(
            "reply",
            full_context=self.state.get_full_context(),
            context_hint=context_hint or "No specific context provided.",
        )
        await self.broadcast(result)  # ReplySuggestion
    
    def _fire_task(self, coro):
        task = asyncio.create_task(coro)
        self._running_tasks.add(task)
        task.add_done_callback(self._running_tasks.discard)
    
    async def _run_summary(self):
        new_segments = self.state.get_transcript_text(
            last_n=self.SUMMARY_EVERY_N_SEGMENTS
        )
        result = await self.dispatcher.run(
            "summary",
            current_summary=self.state.current_summary,
            new_segments=new_segments,
        )
        self.state.current_summary = result
        await self.broadcast(SummaryUpdate(
            summary=result,
            covered_until=self.state.segments[-1].timestamp_end,
        ).model_dump())
    
    async def _run_action_items(self):
        result = await self.dispatcher.run(
            "action_items",
            full_context=self.state.get_full_context(),
            recent_transcript=self.state.get_transcript_text(last_n=10),
            existing_items=str(self.state.action_items),
        )
        # Parse and update self.state.action_items
        await self.broadcast(ActionItemsUpdate(items=self.state.action_items).model_dump())
```

### 3. LLM Dispatcher (Ollama + API Fallback)

```python
# backend/reasoning/dispatcher.py
import httpx
import anthropic
from .prompts import (
    PROGRESSIVE_SUMMARY, ACTION_ITEMS, 
    CONTRADICTION_DETECTION, REPLY_SUGGESTION, CUSTOM_PROMPT_TEMPLATE
)

PROMPT_MAP = {
    "summary": PROGRESSIVE_SUMMARY,
    "action_items": ACTION_ITEMS,
    "contradictions": CONTRADICTION_DETECTION,
    "reply": REPLY_SUGGESTION,
    "custom": CUSTOM_PROMPT_TEMPLATE,
}

# Tasks that need higher-quality reasoning → prefer API if available
HEAVY_TASKS = {"contradictions", "reply", "custom"}

class LLMDispatcher:
    """Routes LLM tasks to Ollama (local) or Claude API (remote)."""
    
    def __init__(self, config):
        self.ollama_url = config.ollama_url          # http://localhost:11434
        self.ollama_model = config.ollama_model       # llama3.1:8b
        self.ollama_heavy_model = config.ollama_heavy_model  # llama3.1:70b (optional)
        self.use_api_fallback = config.use_api_fallback
        self.anthropic_client = anthropic.AsyncAnthropic() if self.use_api_fallback else None
    
    async def run(self, task_name: str, **kwargs) -> str:
        """Run a reasoning task. Routes to best available backend."""
        prompt_template = PROMPT_MAP[task_name]
        prompt = prompt_template.format(**kwargs)
        
        # Heavy tasks: try API first if enabled, fallback to local
        if task_name in HEAVY_TASKS and self.use_api_fallback:
            try:
                return await self._call_claude(prompt)
            except Exception:
                pass  # Fallback to local
        
        return await self._call_ollama(prompt, heavy=task_name in HEAVY_TASKS)
    
    async def _call_ollama(self, prompt: str, heavy: bool = False) -> str:
        model = self.ollama_heavy_model if heavy else self.ollama_model
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.3, "num_predict": 1024},
                },
            )
            return response.json()["response"]
    
    async def _call_claude(self, prompt: str) -> str:
        response = await self.anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
```

### 4. WebSocket Gateway

```python
# backend/ws/gateway.py
from fastapi import WebSocket
import asyncio
import json

class ConnectionManager:
    """Manages WebSocket connections and message broadcasting."""
    
    def __init__(self):
        self.active_connections: list[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    
    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
    
    async def broadcast(self, message: dict):
        """Send message to all connected clients."""
        data = json.dumps(message, ensure_ascii=False)
        for conn in self.active_connections:
            try:
                await conn.send_text(data)
            except Exception:
                pass  # Connection will be cleaned up
```

### 5. FastAPI Main App

```python
# backend/main.py
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
import asyncio

from .config import Settings
from .audio.pipeline import AudioPipeline
from .reasoning.context_manager import ContextManager
from .reasoning.dispatcher import LLMDispatcher
from .ws.gateway import ConnectionManager

app = FastAPI(title="Meeting Copilot")
settings = Settings()
ws_manager = ConnectionManager()

# Initialize pipeline components
dispatcher = LLMDispatcher(settings)
context_mgr = ContextManager(dispatcher, ws_manager.broadcast)
audio_pipeline = AudioPipeline(settings)
audio_pipeline.on_segment(context_mgr.on_new_segment)

@app.websocket("/ws/audio")
async def audio_websocket(websocket: WebSocket):
    """Receives audio chunks from frontend, sends back all outputs."""
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_bytes()
            await audio_pipeline.process_audio_chunk(data)
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)

@app.websocket("/ws/control")
async def control_websocket(websocket: WebSocket):
    """Receives user commands (custom prompts, reply requests)."""
    await ws_manager.connect(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            if msg["type"] == "custom_prompt":
                await context_mgr.handle_custom_prompt(msg["prompt"])
            elif msg["type"] == "request_reply":
                await context_mgr.handle_reply_request(msg.get("context_hint", ""))
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
```

---

## Frontend Key Components

### Audio Capture Hook

```typescript
// frontend/src/hooks/useAudioCapture.ts
export function useAudioCapture(wsUrl: string) {
  const wsRef = useRef<WebSocket | null>(null);
  const [isRecording, setIsRecording] = useState(false);

  const start = async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ 
      audio: { 
        sampleRate: 16000, 
        channelCount: 1, 
        echoCancellation: true,
        noiseSuppression: true,
      } 
    });

    const audioContext = new AudioContext({ sampleRate: 16000 });
    const source = audioContext.createMediaStreamSource(stream);
    const processor = audioContext.createScriptProcessor(4096, 1, 1);

    wsRef.current = new WebSocket(wsUrl);
    
    processor.onaudioprocess = (e) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        const float32 = e.inputBuffer.getChannelData(0);
        const int16 = new Int16Array(float32.length);
        for (let i = 0; i < float32.length; i++) {
          int16[i] = Math.max(-32768, Math.min(32767, float32[i] * 32768));
        }
        wsRef.current.send(int16.buffer);
      }
    };

    source.connect(processor);
    processor.connect(audioContext.destination);
    setIsRecording(true);
  };

  return { start, stop, isRecording };
}
```

### Meeting State Hook

```typescript
// frontend/src/hooks/useMeetingState.ts
interface MeetingState {
  segments: TranscriptSegment[];
  summary: string;
  actionItems: ActionItem[];
  contradictions: ContradictionAlert[];
  replySuggestions: string[];
}

export function useMeetingState(wsUrl: string) {
  const [state, dispatch] = useReducer(meetingReducer, initialState);
  
  useEffect(() => {
    const ws = new WebSocket(wsUrl);
    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      switch (msg.type) {
        case "transcript_segment":
          dispatch({ type: "ADD_SEGMENT", payload: msg });
          break;
        case "summary_update":
          dispatch({ type: "SET_SUMMARY", payload: msg.summary });
          break;
        case "action_items_update":
          dispatch({ type: "SET_ACTION_ITEMS", payload: msg.items });
          break;
        case "contradiction_alert":
          dispatch({ type: "ADD_CONTRADICTION", payload: msg });
          break;
        case "reply_suggestion":
          dispatch({ type: "SET_REPLIES", payload: msg.suggestions });
          break;
        case "custom_prompt_result":
          dispatch({ type: "ADD_PROMPT_RESULT", payload: msg });
          break;
      }
    };
    return () => ws.close();
  }, [wsUrl]);

  return state;
}
```

---

## Configuration

```python
# backend/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Audio Pipeline
    whisper_model: str = "large-v3"
    language: str = "pt"                    # Default language (None for auto-detect)
    enable_diarization: bool = True
    
    # LLM - Local
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"       # For summaries, action items
    ollama_heavy_model: str = "llama3.1:70b" # For contradictions, replies (optional)
    
    # LLM - API Fallback
    use_api_fallback: bool = False
    anthropic_api_key: str = ""             # Set via ANTHROPIC_API_KEY env var
    
    # Reasoning Triggers
    summary_every_n_segments: int = 10
    action_scan_every_n_segments: int = 5
    contradiction_check_seconds: int = 120
    
    # WebSocket
    ws_host: str = "0.0.0.0"
    ws_port: int = 8000
    
    class Config:
        env_file = ".env"
```

---

## Setup & Dependencies

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
    "whisperlivekit>=0.3",
    "pyannote.audio>=3.1",
    "silero-vad>=4.0",
    "anthropic>=0.40",
    "aiosqlite>=0.20",
]
```

### Setup Script

```bash
#!/bin/bash
# scripts/setup.sh

echo "=== Meeting Copilot Setup ==="

# 1. Python environment
python -m venv .venv
source .venv/bin/activate
pip install -e .

# 2. Download Whisper model
python -c "from faster_whisper import WhisperModel; WhisperModel('large-v3')"

# 3. Download pyannote diarization model (requires HuggingFace token)
echo "Note: pyannote requires a HuggingFace token. Set HF_TOKEN env var."
python -c "
from pyannote.audio import Pipeline
Pipeline.from_pretrained('pyannote/speaker-diarization-3.1', use_auth_token=True)
"

# 4. Check Ollama
if command -v ollama &> /dev/null; then
    echo "Pulling Ollama models..."
    ollama pull llama3.1:8b
    echo "Optional: ollama pull llama3.1:70b (for heavy reasoning)"
else
    echo "WARNING: Ollama not found. Install from https://ollama.ai"
fi

# 5. Frontend
cd frontend && npm install && cd ..

echo "=== Setup complete. Run with: uvicorn backend.main:app --reload ==="
```

---

## Implementation Phases

### Phase 1 — Audio Pipeline (Week 1)
- [ ] FastAPI skeleton with WebSocket endpoints
- [ ] WhisperLiveKit integration (streaming transcription)
- [ ] Audio capture frontend (WebAudio → WebSocket)
- [ ] Live transcript panel rendering
- **Milestone**: Audio in → live transcript on screen

### Phase 2 — Diarization + Context Manager (Week 2)  
- [ ] pyannote diarization integration
- [ ] Speaker-labeled transcript segments
- [ ] Context Manager with MeetingState accumulation
- [ ] Trigger logic (segment count thresholds)
- **Milestone**: Transcript shows "Speaker 1: ...", "Speaker 2: ..."

### Phase 3 — LLM Reasoning (Week 3)
- [ ] LLM Dispatcher (Ollama integration)
- [ ] Progressive summary worker
- [ ] Action item extraction worker
- [ ] Copilot panel on frontend
- **Milestone**: Summary and action items update live during meeting

### Phase 4 — Advanced Reasoning (Week 4)
- [ ] Contradiction detection worker
- [ ] Reply suggestion worker
- [ ] Custom prompt worker
- [ ] Claude API fallback integration
- **Milestone**: Full copilot functionality

### Phase 5 — Polish & Persistence (Week 5)
- [ ] SQLite session storage (save/load meetings)
- [ ] Meeting export (markdown, JSON)
- [ ] Frontend polish (settings, theme, responsive layout)
- [ ] Error handling and reconnection logic
- **Milestone**: Production-ready for personal use

---

## Known Considerations & Tradeoffs

1. **Whisper latency vs accuracy**: `large-v3` gives best accuracy but adds ~2-3s latency. For faster response, use `medium` or `small` models. Configure per use case.

2. **Diarization accuracy**: pyannote works best with clear audio and distinct speakers. Overlapping speech and phone-quality audio degrade results. Consider making diarization optional.

3. **LLM context window growth**: As meetings get longer (1h+), the full transcript exceeds context windows. The progressive summary pattern mitigates this — the LLM sees summary + recent_window, not the full transcript.

4. **Ollama concurrency**: Running multiple LLM tasks simultaneously on Ollama with a single GPU can cause queuing. The trigger thresholds should be tuned to avoid overwhelming the inference server. Consider a task priority queue.

5. **Reply suggestions sensitivity**: Auto-generating replies needs careful tuning to avoid being distracting. Start with manual-only (user clicks "suggest reply") before enabling auto-trigger.

6. **Portuguese language support**: Whisper `large-v3` handles Portuguese well. For LLM reasoning, ensure Ollama model handles PT (Llama 3.1 does). Include language instruction in all prompts.
