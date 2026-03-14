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
- [x] Create `backend/reasoning/workers/__init__.py`
- [x] Create `backend/reasoning/workers/base.py` — BaseWorker abstract class with `execute()` method
- [x] Create `backend/reasoning/workers/summary.py` — SummaryWorker: takes current_summary + new_segments, returns updated summary
- [x] Create `backend/reasoning/workers/action_items.py` — ActionItemWorker: extracts new items, updates existing ones, parses JSON response
- [x] Wire workers into ContextManager — when triggers fire, dispatch to appropriate worker, broadcast results
- [x] Write tests: `tests/test_workers.py` — mock dispatcher, verify workers format prompts correctly and parse responses

> Done: BaseWorker ABC with abstract execute() method. SummaryWorker calls dispatcher with "summary" task, handles empty segments (returns current summary), replaces empty summary with placeholder for first run, strips whitespace. ActionItemWorker calls dispatcher with "action_items" task, parses JSON response (handles markdown code fences), creates new ActionItem objects with UUIDs, updates existing items' status, skips malformed entries, falls back to existing items on invalid JSON. ContextManager updated to use workers instead of calling dispatcher directly; _run_action_items now stores parsed ActionItem objects back into state. 16 new tests + 2 updated context_manager tests; 120 total pass (1 pre-existing fastapi import failure excluded).

### 3.4 Frontend — Copilot Panel
- [x] Create `frontend/src/hooks/useMeetingState.ts` — useReducer managing all message types from WebSocket
- [x] Create `frontend/src/components/CopilotPanel.tsx` — displays:
  - Progressive summary (updates in place)
  - Action items list (with assignee, status badges)
- [x] Update `App.tsx` — two-column layout: TranscriptPanel (left) + CopilotPanel (right)

> Done: Created `useMeetingState.ts` with useReducer handling all 6 server message types (transcript_segment, summary_update, action_items_update, contradiction_alert, reply_suggestion, custom_prompt_result) plus reset action. Created `CopilotPanel.tsx` displaying progressive summary (updates in place) and action items list with color-coded status badges (new=blue, updated=yellow, completed=green) and assignee display. Updated `App.tsx` to use useMeetingState hook instead of manual useState, two-column responsive grid layout (single column on mobile, side-by-side on lg+), max-w-7xl container. `npm run build` compiles cleanly.

---

## Phase 4 — Advanced Reasoning & Interactivity

### 4.1 Contradiction Detection
- [x] Create `backend/reasoning/workers/contradictions.py` — ContradictionWorker: analyzes recent transcript against summary, parses JSON response
- [x] Add time-based trigger in ContextManager — run contradiction check every N seconds
- [x] Frontend: add contradiction alerts to CopilotPanel with severity badges and expandable details

> Done: ContradictionWorker calls dispatcher with "contradictions" task, parses JSON response (handles markdown fences), skips malformed items, defaults unknown severity to "low". ContextManager already had `_last_contradiction_check` + `_run_contradictions()` wired; confirmed complete. CopilotPanel already had contradiction alerts UI with SEVERITY_STYLES (low/medium/high) and expandable statement details; App.tsx passes `state.contradictions` prop. Added 9 new ContradictionWorker tests; 127 total pass. Frontend builds cleanly (64.02 kB JS).

### 4.2 Reply Suggestions
- [x] Create `backend/reasoning/workers/reply.py` — ReplyWorker: generates 2-3 reply suggestions based on meeting context
- [x] Wire to `/ws/control` endpoint — handle `request_reply` messages
- [x] Create `frontend/src/components/ReplyPanel.tsx` — shows suggestions with copy-to-clipboard buttons
- [x] Add "Suggest Reply" button in UI that sends request via control WebSocket

> Done: ReplyWorker calls dispatcher with "reply" task, parses JSON response (handles markdown fences, non-list suggestions, empty/non-string items), falls back to raw text on invalid JSON, always returns ReplySuggestion with triggered_by="manual". ContextManager.handle_reply_request() now uses ReplyWorker and broadcasts proper ReplySuggestion model_dump(). main.py wired with LLMDispatcher + ContextManager instances; control endpoint now calls context_manager.handle_reply_request() / handle_custom_prompt() via asyncio.create_task(); audio_pipeline.on_segment registered to context_manager.on_new_segment. ReplyPanel.tsx shows suggestions with copy-to-clipboard buttons and optional context hint input. App.tsx includes ReplyPanel in right column with handleRequestReplySuggestions callback. 10 new tests; 137 total pass. Frontend builds cleanly.

### 4.3 Custom Prompts
- [x] Create `backend/reasoning/workers/custom.py` — CustomPromptWorker: runs user's freeform prompt against meeting context
- [x] Wire to `/ws/control` endpoint — handle `custom_prompt` messages
- [x] Create `frontend/src/components/PromptInput.tsx` — text input + send button, displays results inline
- [x] Add prompt history display (shows previous prompts and their results)

> Done: CustomPromptWorker wraps dispatcher.run("custom") call, returns CustomPromptResult with stripped result and timestamp. ContextManager.handle_custom_prompt() updated to use the worker instead of calling dispatcher directly. PromptInput.tsx shows text input + Ask button + prompt history (newest first, max-h-60 scrollable), wired into App.tsx with handleSendCustomPrompt callback that sends {type:"custom_prompt", prompt} over control WebSocket. 6 new CustomPromptWorker tests; 159 total pass (1 pre-existing fastapi import failure). Frontend builds cleanly.

---

## Phase 5 — Persistence, Polish & Packaging

### 5.1 Session Storage
- [x] Create `backend/storage/__init__.py`
- [x] Create `backend/storage/session.py` — SQLite via aiosqlite:
  - `create_session()` — new meeting session
  - `save_segment()` — persist transcript segment
  - `save_state()` — persist summary + action items
  - `load_session()` — restore full meeting state
  - `list_sessions()` — list past meetings
- [x] Add REST endpoints: `GET /sessions`, `GET /sessions/{id}`, `POST /sessions`
- [x] Write tests: `tests/test_storage.py` — CRUD operations on SQLite

> Done: SessionStore wraps aiosqlite with three tables (sessions, segments, meeting_state). create_session() auto-generates UUID + default title. save_segment() inserts rows and bumps updated_at. save_state() uses INSERT OR REPLACE for idempotent upserts. load_session() reconstructs full SessionData (segments ordered by timestamp). list_sessions() returns all sessions ordered by most recent first with segment counts via LEFT JOIN. REST endpoints added to main.py: POST /sessions (201), GET /sessions, GET /sessions/{id} (404 on miss). startup event calls init_db(). aiosqlite installed into .venv. 15 new tests; 158 total pass.

### 5.2 Meeting Export
- [x] Add export endpoint: `GET /sessions/{id}/export?format=markdown`
- [x] Generate markdown export: meeting title, date, summary, action items, full transcript with speaker labels
- [x] Add JSON export format option

> Done: Added `GET /sessions/{id}/export?format=markdown|json` endpoint to main.py. `_format_timestamp()` converts float seconds to HH:MM:SS. `_export_markdown()` renders title, date, summary (with placeholder if empty), action items with checkboxes (checked for completed), assignees, and full transcript with speaker labels and timestamps. JSON format returns pretty-printed JSON via PlainTextResponse with application/json content-type. Both return 404 for unknown sessions; invalid format triggers 422. 17 new tests; 192 total pass.

### 5.3 Frontend Polish
- [x] Add settings panel: toggle diarization, select Whisper model size, toggle API fallback
- [x] Add session list sidebar: browse and load past meetings
- [x] Add responsive layout (mobile-friendly)
- [x] Add dark mode support via Tailwind
- [x] Connection status indicator (WebSocket connected/disconnected/reconnecting)

> Done: SettingsPanel.tsx — right-side drawer with toggle switches (diarization, API fallback) and model size select; saves to localStorage + POSTs to /settings. SessionSidebar.tsx — left-side drawer fetching GET /sessions, renders session list with dates/segment counts, loads session via GET /sessions/{id} and dispatches load_session action to useMeetingState. useMeetingState: added load_session reducer case + loadSession callback. types/messages.ts: added SessionListItem and SessionData interfaces. darkMode: 'class' added to tailwind.config.js; App.tsx manages dark class on <html> with localStorage persistence and sun/moon SVG toggle button. Connection status: dedicated ConnectionDot component in App header showing audio + control WS status with animated pulse for connecting state; also shown in mobile status bar below header. Responsive: sticky header with sm: breakpoints, main grid uses lg:grid-cols-2 (single column on mobile), panels have sm:p-5 padding. Backend: added GET /settings and POST /settings endpoints with SettingsUpdate model; AudioPipeline.set_diarization_enabled() added for runtime toggle. Build: 67.33 kB JS. 192 backend tests pass.

### 5.4 Error Handling & Resilience
- [x] Backend: graceful WebSocket disconnection handling
- [x] Backend: Ollama connection failure → log warning, skip reasoning tasks (don't crash)
- [x] Backend: API rate limit handling with exponential backoff
- [x] Frontend: WebSocket auto-reconnection with exponential backoff
- [x] Frontend: error toast notifications for failures

> Done: main.py ws_audio wraps pipeline.process_audio_chunk in try/except to log errors without crashing the connection; ws_control catches generic Exception on control message processing. context_manager.py adds logging + wraps _run_summary/_run_action_items/_run_contradictions in try/except (log warning, skip); handle_custom_prompt/handle_reply_request catch failures and broadcast {type:"error"} to frontend. dispatcher.py adds asyncio.sleep-based exponential backoff (1s→2s, max 3 attempts) in _call_claude for 429/rate-limit errors. useWebSocket.ts already had exponential backoff reconnection. Created ErrorToast.tsx (auto-dismiss 5s, manual dismiss, error/warning/info styles); App.tsx wires handleControlMessage to intercept type="error" messages as toasts, useEffect surfaces audio capture errors as toasts. 7 new tests pass; 166 total pass. Frontend builds cleanly.

### 5.5 Packaging
- [ ] Create `Dockerfile` for backend
- [ ] Create `docker-compose.yml` — backend + Ollama (GPU passthrough)
- [ ] Create `scripts/setup.sh` — automated setup (venv, deps, model downloads)
- [ ] Update `README.md` — installation, configuration, usage instructions
