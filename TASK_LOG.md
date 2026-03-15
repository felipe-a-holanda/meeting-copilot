# TASK_LOG_REFACTOR.md — Backend Audio Capture Refactor

> This file is the single source of truth for the autonomous build agent.
> `[ ]` = pending | `[x]` = done | `[!]` = blocked
>
> **Context**: Read `ARCHITECTURE_REFACTOR.md` for full design details.
> **Scope**: Move audio capture from browser (getUserMedia) to backend (PulseAudio + ffmpeg). Drop pyannote diarization in favour of stream-based speaker labels ("Me" / "Them").
> **Constraint**: The reasoning engine and WebSocket control channel must remain unchanged. Only the audio source and speaker attribution method change.

---

## Phase 1 — Backend Audio Recorder

### 1.1 PulseAudio Device Discovery
- [x] Create `backend/audio/recorder.py` with an `AudioRecorder` class
- [x] Implement `list_devices()` — run `pactl list sources short` and `pactl list sinks short` via `asyncio.create_subprocess_exec`, parse output into structured dicts
- [x] Implement `get_defaults()` — run `pactl get-default-source` and `pactl get-default-sink`, derive monitor source name as `<default_sink>.monitor`
- [x] Implement `check_dependencies()` — verify `pactl` and `ffmpeg` are available on PATH, return clear error messages if not
- [x] Write tests: `tests/test_recorder_devices.py` — mock subprocess calls to pactl, verify parsing of device lists and defaults. Test edge cases: no monitor source found, empty device list, pactl not installed
  > Created `AudioRecorder` with dataclasses (`AudioDevice`, `DeviceDefaults`, `DeviceList`, `DependencyStatus`), async `_run_pactl` helper, `_parse_device_list`, `list_devices`, `get_defaults`, `check_dependencies`. 17 tests all passing.

### 1.2 ffmpeg Recording Subprocess
- [x] In `AudioRecorder`, implement `start()` method that launches ffmpeg as an async subprocess:
  - Build the ffmpeg command: `-f pulse -i <mic> -f pulse -i <monitor> -filter_complex '[0:a]volume=<vol>[mic];[1:a][mic]amix=inputs=2:duration=longest:normalize=0' -ar 16000 -ac 1 -f s16le pipe:1`
  - If monitor source is unavailable, fall back to mic-only: `-f pulse -i <mic> -ar 16000 -ac 1 -f s16le pipe:1`
  - Store the `asyncio.subprocess.Process` reference
  - Set `self._is_recording = True`
- [x] Implement `stop()` method:
  - Send SIGINT to ffmpeg process (graceful shutdown)
  - Wait up to 5 seconds for process to exit, then SIGKILL if needed
  - Set `self._is_recording = False`
  - Return recording stats (duration, chunks processed)
- [x] Implement `is_recording` property and `recording_stats` property
- [x] Write tests: `tests/test_recorder_subprocess.py` — mock asyncio.create_subprocess_exec, verify correct ffmpeg command is built for various configs (with/without monitor, custom mic volume, custom sources). Verify stop sends SIGINT. Verify fallback to mic-only when monitor is missing.
  > Added `RecordingStats` dataclass, `_build_ffmpeg_cmd`, `_build_ffmpeg_cmd_mic_only`, `start()`, `stop()`, and `recording_stats` property. `start()` uses `None` sentinel to distinguish "auto-detect" from explicit `""` (mic-only). `stop()` sends SIGINT, waits 5 s, then SIGKILL. 21 tests all passing.

### 1.3 Pipeline Integration — Reader Loop
- [x] In `AudioRecorder`, implement `_reader_loop()` — an async task that:
  - Reads chunks from `self._process.stdout` (4096 bytes at a time, matching existing chunk size)
  - Calls `self._pipeline.process_audio_chunk(chunk)` for each chunk
  - Handles EOF (ffmpeg stopped) and errors
  - Updates stats counters (chunks read, bytes read, duration)
- [x] In `start()`, create the reader loop as an `asyncio.Task` stored in `self._reader_task`
- [x] In `stop()`, cancel the reader task after ffmpeg exits, then call `self._pipeline.reset()` to flush
- [x] Write tests: `tests/test_recorder_integration.py` — create a mock subprocess with fake PCM data on stdout, verify chunks are forwarded to a mock pipeline. Test EOF handling. Test error during read.
  > `_reader_loop` reads CHUNK_SIZE bytes, forwards each to `pipeline.process_audio_chunk`, handles EOF cleanly and logs errors without crashing. `start()` stores the task in `_reader_task`. `stop()` cancels the task and calls `pipeline.reset()`. 9 tests all passing.

### 1.4 Optional WAV File Saving
- [x] Add `save_to_file` parameter to `start()` — when provided, add a second `-c:a pcm_s16le <file_path>` output to each ffmpeg process
- [x] Save two separate WAV files: `meeting_<timestamp>_mic.wav` and `meeting_<timestamp>_monitor.wav` (one per stream — **do not mix**)
- [x] Create recordings directory structure: `<recordings_dir>/<YYYYMMDD>/meeting_<timestamp>/`
- [x] Write a JSON metadata sidecar file: title, timestamp, audio files, created_at, source
- [x] Write tests: verify ffmpeg commands include file outputs when `save_to_file=True`. Verify directory creation. Verify metadata JSON structure.
  > `_build_ffmpeg_cmd` accepts `mic_file_path` + `monitor_file_path` and adds `-map 0:a`/`-map 1:a` outputs; `_build_ffmpeg_cmd_mic_only` accepts `mic_file_path`. `_make_recording_path` returns `(meeting_dir, mic_wav, monitor_wav)`. `_write_metadata` takes `audio_files: list[str]`. `RecordingStats` has `file_path` (meeting dir) and `audio_files` (list of WAV paths). Fixed reader-loop hang in all test mocks (`stdout.read = AsyncMock(return_value=b"")`). 32 tests all passing; all 47 prior tests still passing.

---

## Phase 1B — Dual-Stream Speaker Labels (Drop Diarization)

> **Why**: mic = local user ("Me"), system monitor = remote participants ("Them").
> Keeping streams separate gives 100% accurate speaker attribution for zero ML cost.
> pyannote diarization is expensive (~400 ms/chunk), requires a HuggingFace token,
> and downloads ~500 MB of models — all unnecessary for the primary use case.

### 1B.1 Update AudioPipeline — Add speaker_label, Remove Diarization
- [x] Add `speaker_label: str = "Speaker"` parameter to `AudioPipeline.process_audio_chunk()`
- [x] In `_process_buffer()`, replace the diarization lookup block with `speaker = speaker_label` passed from the caller
- [x] Remove the `SpeakerDiarizer` import and `self._diarizer` field
- [x] Remove `set_diarization_enabled()` method
- [x] Remove the diarization block in `_process_buffer()` entirely
- [x] Write/update tests: verify `speaker_label` is forwarded to `TranscriptSegment`. Verify no diarizer is instantiated.
  > Removed diarizer import, `self._diarizer` field, and `set_diarization_enabled()` from `pipeline.py`. Added `speaker_label: str = "Speaker"` to `process_audio_chunk()`, `reset()`, and `_process_buffer()` — label passes straight through to each `TranscriptSegment`. Replaced `TestAudioPipelineDiarization` in `test_diarizer.py` with `TestAudioPipelineSpeakerLabel` (6 tests: default label, "Me", "Them", no diarizer attribute, multi-segment, no method). All 244 passing tests still pass; 3 pre-existing failures unchanged.

### 1B.2 Refactor AudioRecorder — Two Separate ffmpeg Processes
- [x] Replace the single `amix` ffmpeg command with two separate ffmpeg processes:
  - Mic process: `-f pulse -i <mic_source> -ar 16000 -ac 1 -f s16le pipe:1`
  - Monitor process: `-f pulse -i <monitor_source> -ar 16000 -ac 1 -f s16le pipe:1`
- [x] Add separate state fields: `_mic_process`, `_monitor_process`, `_mic_reader_task`, `_monitor_reader_task`
- [x] Mic reader loop calls `pipeline.process_audio_chunk(chunk, speaker_label="Me")`
- [x] Monitor reader loop calls `pipeline.process_audio_chunk(chunk, speaker_label="Them")`
- [x] If no monitor source is available, start mic-only — all chunks get `speaker_label="Me"`
- [x] Update `stop()` to shut down both processes and cancel both reader tasks
- [x] Remove `_build_ffmpeg_cmd` (the amix version) — keep `_build_ffmpeg_cmd_mic_only` as the template for both streams, renamed to `_build_stream_cmd`
- [x] Write tests: verify two ffmpeg processes are started, each with correct source. Verify mic chunks get "Me" and monitor chunks get "Them". Verify stop() shuts down both.
  > Replaced single amix ffmpeg process with two separate processes (`_mic_process` / `_monitor_process`). Removed `_build_ffmpeg_cmd` (amix), renamed `_build_ffmpeg_cmd_mic_only` → `_build_stream_cmd` (used for both streams). Added `_stop_process()` helper. Reader loop now parameterised with `(process, speaker_label)`. Updated all 4 recorder test files; added `test_recorder_dual_stream.py` with 20 dual-stream-specific tests. 78 new/updated tests all pass; 3 pre-existing failures unchanged.

### 1B.3 Delete diarizer.py
- [x] Delete `backend/audio/diarizer.py`
- [x] Remove `SpeakerDiarizer` import from any file that still references it
- [x] Verify no remaining references with `grep -r "diarizer\|SpeakerDiarizer\|pyannote" backend/`
  > Deleted `backend/audio/diarizer.py`. Removed `TestSpeakerDiarizer` class and its pyannote helpers from `test_diarizer.py` (the `TestAudioPipelineSpeakerLabel` class was kept). No import-level references remain; only comments in `recorder.py` and `config.py` mention pyannote in passing (cleaned up in 1B.4/1B.5). 253 tests pass, 3 pre-existing failures unchanged.

### 1B.4 Remove Diarization Config and Dependency
- [x] In `backend/config.py`, remove `enable_diarization: bool = True` and `hf_token: str = ""`
- [x] In `pyproject.toml`, remove `pyannote.audio>=3.1` from dependencies
- [x] Run `pip install -e .` (or equivalent) to verify install succeeds without pyannote
- [x] Run `pytest` — all existing tests must still pass
  > Removed `enable_diarization` and `hf_token` from `config.py`. Removed `pyannote.audio>=3.1` from `pyproject.toml`. Cleaned `.env` and `.env.example` of diarization vars (they caused pydantic validation errors). Removed stale `cfg.enable_diarization = False` from `test_transcriber.py`. 286 tests pass (up from 244 — the prior 14 failures + 28 errors were all caused by the old env vars being rejected by pydantic).

### 1B.5 Update ARCHITECTURE.md
- [x] Update the Audio Capture section: replace "VAD → Whisper → Diarize" with "VAD → Whisper (per-stream)"
- [x] Update the ffmpeg command example to show two separate processes instead of amix
- [x] Add a note under Known Considerations replacing the diarization tradeoff with the dual-stream tradeoff (cannot distinguish multiple remote speakers)
- [x] Remove pyannote from the Python Dependencies list
  > Updated diagram label, ffmpeg example, pipeline docstring, data-flow step, config block, directory structure, Known Considerations item 2, project overview, and dependency list. All references to pyannote and diarization removed or updated throughout ARCHITECTURE.md.

---

## Phase 2 — REST API Endpoints

### 2.1 Configuration Updates
- [x] Add new fields to `Settings` in `backend/config.py`:
  - `audio_capture_mode: str = "backend"` (values: "backend", "browser", "both")
  - `recordings_dir: str = "./recordings"`
  - `mic_volume: float = 2.0`
  - `default_mic_source: str = ""` (empty = auto-detect)
  - `default_monitor_source: str = ""` (empty = auto-detect)
  - `save_recordings: bool = True`
- [x] Update `.env.example` with the new variables documented
- [x] Write tests: verify Settings loads new fields from env vars with correct defaults
  > Added 6 new fields to `Settings` in `config.py` under a new "Audio Capture" section. Updated `.env.example` with documented `AUDIO_CAPTURE_MODE`, `RECORDINGS_DIR`, `MIC_VOLUME`, `DEFAULT_MIC_SOURCE`, `DEFAULT_MONITOR_SOURCE`, `SAVE_RECORDINGS`. Created `tests/test_config_settings.py` with 17 tests (defaults + env overrides + existing fields unchanged). 270 tests pass, 1 pre-existing failure unchanged.

### 2.2 Device Discovery Endpoint
- [x] Add `GET /api/audio/devices` endpoint to `main.py`:
  - Calls `AudioRecorder.list_devices()` and `AudioRecorder.get_defaults()`
  - Returns JSON with sources, sinks, and defaults
  - Returns 503 if pactl is not available (with clear error message)
- [x] Write tests: mock AudioRecorder.list_devices, verify endpoint response shape
  > Added `GET /api/audio/devices` to `main.py`. Instantiated `audio_recorder = AudioRecorder(pipeline=audio_pipeline, recordings_dir=settings.recordings_dir)` at module level. Endpoint checks `check_dependencies()` for 503 when pactl is missing, and catches `RuntimeError` from `list_devices()` for 503. Created `tests/test_devices_endpoint.py` with 9 tests (success path: 200 + response shape, empty list; error paths: pactl missing, list_devices raises). All 9 tests pass.

### 2.3 Recording Control Endpoints
- [x] Instantiate `AudioRecorder` in `main.py` (wired to the existing `audio_pipeline`)
- [x] Add `POST /api/recording/start` endpoint:
  - Accepts optional body: `title`, `mic_source`, `monitor_source`, `mic_volume`, `save_file`
  - Creates a new session via `session_store.create_session()`
  - Calls `recorder.start()` with the provided or default parameters
  - Returns session_id, status, and active device names
  - Returns 409 if already recording
  - Returns 503 if dependencies (pactl/ffmpeg) are missing
- [x] Add `POST /api/recording/stop` endpoint:
  - Calls `recorder.stop()`
  - Returns session_id, duration, segments count, file path
  - Returns 409 if not currently recording
- [x] Add `GET /api/recording/status` endpoint:
  - Returns is_recording, session_id, duration, chunks/segments counts
  - Returns status "idle" when not recording
- [x] Write tests: `tests/test_recording_endpoints.py` — test start/stop/status lifecycle with mocked AudioRecorder. Test error cases: start while already recording, stop when not recording, missing dependencies.
  > Added `RecordingStartRequest` Pydantic model and `_active_session_id` module-level var to `main.py`. Implemented all 3 endpoints. `start` creates a session then launches recorder; `stop` retrieves segment count from session store. Status endpoint returns "idle" shape or "recording" shape with live stats. 14 new tests all pass; 326 total, 0 failures.

### 2.4 Wire Segments to Session Storage
- [x] When recording starts, wire `context_manager.on_new_segment` to also call `session_store.save_segment()` for the active session
- [x] When recording stops, save final meeting state (summary, action items) to session
- [x] Write tests: verify segments are persisted during a recording session
  > Introduced `_segment_handler` in `main.py` — a wrapper that calls `context_manager.on_new_segment` AND `session_store.save_segment(_active_session_id, seg)` when a session is active. Registered this as the `audio_pipeline` segment callback. In `stop_recording()`, added `session_store.save_state(session_id, summary, action_items)` before loading final count. Created `tests/test_segment_persistence.py` with 7 tests (segment saved when active, not saved when idle, correct segment forwarded, save_state called on stop, save_state skipped when no session, segment count in stop response). 333 tests total, 0 failures.

---

## Phase 3 — Frontend Updates

### 3.1 New Types and API Client
- [x] Add new TypeScript interfaces to `frontend/src/types/messages.ts`:
  - `AudioDevice { name: string; description: string }`
  - `DeviceListResponse { sources: AudioDevice[]; sinks: AudioDevice[]; defaults: { source: string; sink: string; monitor: string } }`
  - `RecordingStartRequest { title?: string; mic_source?: string; monitor_source?: string; mic_volume?: number; save_file?: boolean }`
  - `RecordingStartResponse { session_id: string; status: string; mic_source: string; monitor_source: string }`
  - `RecordingStopResponse { session_id: string; status: string; duration_seconds: number; segments_count: number; file_path?: string }`
  - `RecordingStatusResponse { is_recording: boolean; session_id?: string; duration_seconds: number; chunks_processed: number; segments_emitted: number }`
- [x] Verify `npm run build` compiles with no errors
  > Added 6 new interfaces to `messages.ts` under a new "Audio Device / Recording API types" section. `npm run build` succeeds with no TypeScript errors. Backend tests unchanged at 333 passing.

### 3.2 Rewrite useAudioCapture Hook
- [x] Rewrite `frontend/src/hooks/useAudioCapture.ts`:
  - Remove `getUserMedia`, `AudioContext`, `ScriptProcessor`, and WebSocket audio sending logic
  - Replace with REST API calls to `/api/recording/start`, `/api/recording/stop`, `/api/recording/status`
  - Expose: `start(options)`, `stop()`, `isRecording`, `status`, `devices`
  - Add `fetchDevices()` that calls `GET /api/audio/devices`
  - Add a polling interval (every 2s) for recording status while active
- [x] Verify `npm run build` compiles with no errors
  > Rewrote `useAudioCapture.ts`: removed all getUserMedia/AudioContext/ScriptProcessor logic. New hook uses fetch() to call REST endpoints, polls status every 2 s while recording, exposes `start(options?)`, `stop()`, `isRecording`, `status`, `devices`, `fetchDevices`. Updated `App.tsx` to use new interface: removed audio WebSocket, removed `onAudioChunk` callback, renamed `isCapturing` → `isRecording`. Build compiles clean.

### 3.3 Device Picker Component
- [x] Create `frontend/src/components/DevicePicker.tsx`:
  - Dropdown for microphone source (populated from `/api/audio/devices`)
  - Dropdown for system audio source (monitor sources)
  - Shows default selections
  - "Refresh devices" button
  - Slider or input for mic volume boost (default 2.0)
- [x] Verify `npm run build` compiles with no errors
  > Created `DevicePicker` component with mic source dropdown (all PulseAudio sources), system audio dropdown (`.monitor` sources only), mic volume range slider (0.5–5.0x, default 2.0), and a "Refresh" button. Auto-selects defaults from `DeviceListResponse.defaults` on mount via `useEffect`. All props typed against existing `AudioDevice`/`DeviceListResponse` interfaces. `npm run build` compiles with no errors.

### 3.4 Update AudioControls Component
- [ ] Modify `frontend/src/components/AudioControls.tsx`:
  - Replace browser audio capture UI with backend recording controls
  - Integrate DevicePicker component
  - Add "Meeting title" text input
  - Start button calls `POST /api/recording/start` with selected devices and title
  - Stop button calls `POST /api/recording/stop`
  - Show recording duration (from status polling)
  - Show recording indicator (pulsing red dot when recording)
  - Handle errors: show toast when pactl/ffmpeg unavailable, when already recording, etc.
- [ ] Verify `npm run build` compiles with no errors

### 3.5 Remove Audio WebSocket from App.tsx
- [ ] In `App.tsx`, conditionally connect the audio WebSocket based on capture mode:
  - If backend mode: do not open `/ws/audio`, only open `/ws/control` for receiving transcripts and insights
  - If browser mode (legacy): keep current behavior
  - Read mode from a config or from `GET /settings` response
- [ ] Verify `npm run build` compiles with no errors

---

## Phase 4 — Integration & Polish

### 4.1 End-to-End Integration Test
- [ ] Create `tests/test_e2e_recording.py`:
  - Mock ffmpeg subprocess to produce known PCM audio data
  - Start recording via REST API
  - Verify chunks flow through pipeline
  - Verify transcript segments are emitted and stored in session
  - Stop recording via REST API
  - Verify session has segments and status is correct
- [ ] Run all existing tests to ensure nothing is broken (`pytest`)

### 4.2 Update Setup Script
- [ ] Update `scripts/setup.sh` to check for `pactl` and `ffmpeg` at the start
- [ ] Add instructions for installing `pulseaudio-utils` and `ffmpeg` if missing
- [ ] Add a test command that runs `pactl list sources short` and shows available devices
- [ ] Verify the script runs without errors on a fresh checkout

### 4.3 Debug Endpoint Updates
- [ ] Update `GET /debug` to include recording state:
  - `is_recording`, `active_session_id`, `recording_duration`
  - `audio_capture_mode` (backend/browser/both)
  - `mic_source`, `monitor_source` (when recording)
  - `ffmpeg_pid` (when recording)
- [ ] Write tests: verify debug output includes recording info

### 4.4 Settings Endpoint Updates
- [ ] Update `GET /settings` and `POST /settings` to include new audio capture fields:
  - `audio_capture_mode`
  - `mic_volume`
  - `save_recordings`
- [ ] Update frontend `SettingsPanel.tsx` to show/edit these new settings
- [ ] Verify `npm run build` compiles with no errors

### 4.5 Error Handling & Edge Cases
- [ ] Handle ffmpeg crashing mid-recording: detect process exit, broadcast error to frontend, set recording state to idle
- [ ] Handle PulseAudio device disappearing mid-recording (e.g., headphones unplugged): log warning, attempt to continue with remaining device
- [ ] Handle concurrent start requests: return 409 Conflict
- [ ] Handle server restart while recording: on startup, detect orphaned ffmpeg processes and clean up
- [ ] Write tests for each error scenario

### 4.6 Update Documentation
- [ ] Update `README.md` with new system requirements (pactl, ffmpeg)
- [ ] Add a "Backend Audio Capture" section explaining:
  - How it works (PulseAudio monitor sources)
  - How to select audio devices
  - How to fall back to browser-only mode
  - Troubleshooting: "no monitor source found", "ffmpeg not installed"
- [ ] Update `docs/system-audio-capture-options.md` to note that Option C is now implemented
