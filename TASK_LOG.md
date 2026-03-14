# TASK_LOG.md — Meeting Copilot Build Progress

> This file is the single source of truth for the autonomous build agent.
> `[ ]` = pending | `[x]` = done | `[!]` = blocked

---

## Phase 1 — Project Skeleton & Audio Pipeline

### 1.1 Project Setup
- [x] Create directory structure: `meeting-copilot/backend/`, `frontend/`, `scripts/`
- [x] Create `pyproject.toml` with all Python dependencies
- [x] Create `backend/__init__.py` files for all packages
- [x] Create `backend/config.py` with `Settings` class (Pydantic BaseSettings, all config fields from ARCHITECTURE.md)
- [x] Create `.env.example` with all environment variables documented

> Done: Created full directory tree (backend/, audio/, reasoning/, reasoning/workers/, ws/, storage/, frontend/, scripts/, tests/). pyproject.toml includes all deps + dev extras. All __init__.py files in place. Settings class verified working with pydantic-settings. .env.example documents all 15 config vars with comments.

### 1.2 WebSocket Protocol
- [x] Create `backend/ws/protocol.py` with all Pydantic message models (TranscriptSegment, SummaryUpdate, ActionItemsUpdate, ContradictionAlert, ReplySuggestion, CustomPromptResult, RequestReplySuggestion, CustomPromptRequest)
- [x] Create `backend/ws/gateway.py` with ConnectionManager class (connect, disconnect, broadcast)
- [x] Write tests: `tests/test_protocol.py` — verify all models serialize/deserialize correctly

> Done: All 8 message models implemented with Literal type discriminators. ConnectionManager handles connect/disconnect/broadcast with dead-connection cleanup. 25 tests pass covering serialization, JSON round-trips, default values, and validation errors.

### 1.3 FastAPI Skeleton
- [x] Create `backend/main.py` with FastAPI app, both WebSocket endpoints (`/ws/audio`, `/ws/control`), and CORS middleware
- [x] Verify server starts: `uvicorn backend.main:app --reload` runs without errors
- [x] Create a simple health check endpoint `GET /health` that returns `{"status": "ok"}`

> Done: Created backend/main.py with FastAPI app, CORS middleware (allow_origins=["*"]), /health returning {"status":"ok"}, /ws/audio receiving raw PCM bytes, /ws/control parsing RequestReplySuggestion and CustomPromptRequest messages. Server starts cleanly with uvicorn and health check confirmed via curl.

### 1.4 Audio Pipeline — Transcription
- [x] Create `backend/audio/__init__.py`
- [x] Create `backend/audio/transcriber.py` — wrapper around faster-whisper that accepts PCM audio chunks and yields text segments with timestamps
- [x] Create `backend/audio/vad.py` — Silero VAD wrapper that detects speech segments in audio chunks
- [x] Create `backend/audio/pipeline.py` — AudioPipeline class that combines VAD + transcriber, accepts raw audio bytes, emits TranscriptSegment events via callback
- [x] Write tests: `tests/test_transcriber.py` — feed a synthetic audio chunk (generate a sine wave with numpy), verify it processes without crashing (output text content doesn't matter for synthetic audio)
- [x] Integration test: WebSocket audio endpoint receives bytes and the pipeline processes them

> Done: WhisperTranscriber wraps faster-whisper with lazy model loading (import on first use). SileroVAD wraps torch.hub silero-vad with lazy load and fallback if torch unavailable. AudioPipeline accumulates int16 PCM bytes until MIN_CHUNK_SAMPLES (1s), gates on VAD, transcribes, emits TranscriptSegment via async callback. main.py wired up with audio_pipeline instance that receives bytes from /ws/audio. 17 new tests pass (all mocked — no model downloads needed); 42 total pass.

### 1.5 Frontend — Audio Capture
- [x] Initialize React app: `npx create-react-app frontend --template typescript`
- [x] Install Tailwind CSS
- [x] Create `frontend/src/types/messages.ts` — TypeScript interfaces matching all backend protocol models
- [x] Create `frontend/src/hooks/useAudioCapture.ts` — WebAudio API capture, PCM encoding, WebSocket send
- [x] Create `frontend/src/hooks/useWebSocket.ts` — generic WebSocket hook with auto-reconnection
- [x] Create `frontend/src/components/AudioControls.tsx` — Start/Stop recording buttons
- [x] Create `frontend/src/components/TranscriptPanel.tsx` — displays live transcript segments as they arrive
- [x] Create `frontend/src/App.tsx` — layout with AudioControls + TranscriptPanel
- [x] Verify: `npm run build` compiles successfully with no errors

> Done: Initialized CRA TypeScript app in meeting-copilot/frontend/. Installed Tailwind CSS v3 (v4 lacks CLI binary, v3 works with create-react-app via PostCSS). Configured tailwind.config.js content paths and prepended @tailwind directives to index.css. Created types/messages.ts with all 9 interfaces matching backend/ws/protocol.py exact field names (timestamp_start/timestamp_end, is_partial, etc.). Created useWebSocket.ts with exponential backoff reconnection, useAudioCapture.ts with ScriptProcessorNode at 16kHz + Float32→Int16 PCM conversion. Created AudioControls.tsx and TranscriptPanel.tsx components. App.tsx wires everything together. `npm run build` compiles successfully: 62.89 kB JS + 2.65 kB CSS gzipped.

---

## Phase 2 — Diarization & Context Manager

### 2.1 Speaker Diarization
- [x] Create `backend/audio/diarizer.py` — pyannote wrapper that takes audio segments and returns speaker labels
- [x] Integrate diarizer into `AudioPipeline` — each TranscriptSegment now includes a speaker label
- [x] Handle diarization being optional (config flag `enable_diarization`) — if disabled, all segments get speaker="Speaker"
- [x] Write tests: `tests/test_diarizer.py` — mock pyannote pipeline, verify speaker labels are assigned

> Done: SpeakerDiarizer wraps pyannote.audio Pipeline with lazy load (imports on first diarize() call). Returns sorted DiarizationResult list; get_speaker_at() finds speaker by timestamp mid-point. AudioPipeline initialises _diarizer only when enable_diarization=True; diarization RuntimeErrors fall back gracefully to "Speaker". 14 new tests pass (all mocked — no model downloads); 56 total pass.

### 2.2 Context Manager
- [x] Create `backend/reasoning/__init__.py`
- [x] Create `backend/reasoning/context_manager.py` — MeetingState dataclass + ContextManager class with:
  - `on_new_segment()` — adds segment to state, checks triggers
  - `get_transcript_text()` — formatted transcript for LLM
  - `get_full_context()` — summary + action items + recent transcript
  - Trigger logic: configurable thresholds for summary/action/contradiction tasks
- [x] Write tests: `tests/test_context_manager.py` — add segments, verify trigger conditions fire at correct thresholds

> Done: MeetingState dataclass tracks segments, speakers, summary, action items, recent_window (deque), and trigger counters. ContextManager fires background tasks (_fire_task) at configurable thresholds: summary every N segments, action scan every M segments. handle_custom_prompt() and handle_reply_request() dispatch on demand. 25 tests pass covering state accumulation, trigger firing/not-firing at boundaries, dispatcher calls, broadcast payloads, and custom/reply handlers.

### 2.3 Frontend — Speaker Labels
- [x] Update `TranscriptPanel.tsx` — show speaker name with distinct color per speaker
- [x] Create color mapping utility: assign consistent colors to speaker IDs

> Done: Created `frontend/src/utils/speakerColors.ts` with a 12-color palette and a Map-based assignment that gives each unique speaker a consistent color. Updated `TranscriptPanel.tsx` to import `getSpeakerColor()` and apply it via inline style instead of the hardcoded `text-blue-400` class. `npm run build` compiles cleanly.

---

## Phase 3 — LLM Reasoning

### 3.1 Prompt Templates
- [x] Create `backend/reasoning/prompts.py` — all prompt templates from ARCHITECTURE.md (PROGRESSIVE_SUMMARY, ACTION_ITEMS, CONTRADICTION_DETECTION, REPLY_SUGGESTION, CUSTOM_PROMPT_TEMPLATE)

> Done: Created prompts.py with all 5 prompt templates matching ARCHITECTURE.md exactly, using double-brace escaping for JSON format strings. Added PROMPT_MAP dict mapping task names to templates for dispatcher lookup. All templates verified to format correctly with their expected variables. 81 existing tests still pass.

### 3.2 LLM Dispatcher
- [x] Create `backend/reasoning/dispatcher.py` — LLMDispatcher class with:
  - `_call_ollama()` — async HTTP call to Ollama API
  - `_call_claude()` — async call via Anthropic SDK
  - `run()` — routes task to appropriate backend based on task type and config
  - Proper error handling: timeout, connection refused, model not found
- [x] Write tests: `tests/test_dispatcher.py` — mock HTTP responses, verify routing logic

> Done: LLMDispatcher routes tasks to Ollama (light model for summary/action_items, heavy model for contradictions/reply/custom) with Claude API fallback. Heavy tasks try API first when enabled; light tasks fall back to API if Ollama fails. Anthropic SDK imported lazily (handles missing module). Fixed PROMPT_MAP keys to use "reply"/"custom" matching context_manager expectations. 24 tests pass covering routing, fallback chains, HTTP calls, prompt formatting, and init edge cases. 105 total tests pass.

### 3.3 Reasoning Workers
- [ ] Create `backend/reasoning/workers/__init__.py`
- [ ] Create `backend/reasoning/workers/base.py` — BaseWorker abstract class with `execute()` method
- [ ] Create `backend/reasoning/workers/summary.py` — SummaryWorker: takes current_summary + new_segments, returns updated summary
- [ ] Create `backend/reasoning/workers/action_items.py` — ActionItemWorker: extracts new items, updates existing ones, parses JSON response
- [ ] Wire workers into ContextManager — when triggers fire, dispatch to appropriate worker, broadcast results
- [ ] Write tests: `tests/test_workers.py` — mock dispatcher, verify workers format prompts correctly and parse responses

### 3.4 Frontend — Copilot Panel
- [ ] Create `frontend/src/hooks/useMeetingState.ts` — useReducer managing all message types from WebSocket
- [ ] Create `frontend/src/components/CopilotPanel.tsx` — displays:
  - Progressive summary (updates in place)
  - Action items list (with assignee, status badges)
- [ ] Update `App.tsx` — two-column layout: TranscriptPanel (left) + CopilotPanel (right)

---

## Phase 4 — Advanced Reasoning & Interactivity

### 4.1 Contradiction Detection
- [ ] Create `backend/reasoning/workers/contradictions.py` — ContradictionWorker: analyzes recent transcript against summary, parses JSON response
- [ ] Add time-based trigger in ContextManager — run contradiction check every N seconds
- [ ] Frontend: add contradiction alerts to CopilotPanel with severity badges and expandable details

### 4.2 Reply Suggestions
- [ ] Create `backend/reasoning/workers/reply.py` — ReplyWorker: generates 2-3 reply suggestions based on meeting context
- [ ] Wire to `/ws/control` endpoint — handle `request_reply` messages
- [ ] Create `frontend/src/components/ReplyPanel.tsx` — shows suggestions with copy-to-clipboard buttons
- [ ] Add "Suggest Reply" button in UI that sends request via control WebSocket

### 4.3 Custom Prompts
- [ ] Create `backend/reasoning/workers/custom.py` — CustomPromptWorker: runs user's freeform prompt against meeting context
- [ ] Wire to `/ws/control` endpoint — handle `custom_prompt` messages
- [ ] Create `frontend/src/components/PromptInput.tsx` — text input + send button, displays results inline
- [ ] Add prompt history display (shows previous prompts and their results)

---

## Phase 5 — Persistence, Polish & Packaging

### 5.1 Session Storage
- [ ] Create `backend/storage/__init__.py`
- [ ] Create `backend/storage/session.py` — SQLite via aiosqlite:
  - `create_session()` — new meeting session
  - `save_segment()` — persist transcript segment
  - `save_state()` — persist summary + action items
  - `load_session()` — restore full meeting state
  - `list_sessions()` — list past meetings
- [ ] Add REST endpoints: `GET /sessions`, `GET /sessions/{id}`, `POST /sessions`
- [ ] Write tests: `tests/test_storage.py` — CRUD operations on SQLite

### 5.2 Meeting Export
- [ ] Add export endpoint: `GET /sessions/{id}/export?format=markdown`
- [ ] Generate markdown export: meeting title, date, summary, action items, full transcript with speaker labels
- [ ] Add JSON export format option

### 5.3 Frontend Polish
- [ ] Add settings panel: toggle diarization, select Whisper model size, toggle API fallback
- [ ] Add session list sidebar: browse and load past meetings
- [ ] Add responsive layout (mobile-friendly)
- [ ] Add dark mode support via Tailwind
- [ ] Connection status indicator (WebSocket connected/disconnected/reconnecting)

### 5.4 Error Handling & Resilience
- [ ] Backend: graceful WebSocket disconnection handling
- [ ] Backend: Ollama connection failure → log warning, skip reasoning tasks (don't crash)
- [ ] Backend: API rate limit handling with exponential backoff
- [ ] Frontend: WebSocket auto-reconnection with exponential backoff
- [ ] Frontend: error toast notifications for failures

### 5.5 Packaging
- [ ] Create `Dockerfile` for backend
- [ ] Create `docker-compose.yml` — backend + Ollama (GPU passthrough)
- [ ] Create `scripts/setup.sh` — automated setup (venv, deps, model downloads)
- [ ] Update `README.md` — installation, configuration, usage instructions
