# TASK_LOG_REFACTOR.md — Backend Audio Capture Refactor

> This file is the single source of truth for the autonomous build agent.
> `[ ]` = pending | `[x]` = done | `[!]` = blocked
>
> **Context**: Read `ARCHITECTURE_REFACTOR.md` for full design details.
> **Scope**: Move audio capture from browser (getUserMedia) to backend (PulseAudio + ffmpeg).
> **Constraint**: The existing AudioPipeline, reasoning engine, and WebSocket control channel must remain unchanged. Only the audio source changes.

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
- [ ] In `AudioRecorder`, implement `start()` method that launches ffmpeg as an async subprocess:
  - Build the ffmpeg command: `-f pulse -i <mic> -f pulse -i <monitor> -filter_complex '[0:a]volume=<vol>[mic];[1:a][mic]amix=inputs=2:duration=longest:normalize=0' -ar 16000 -ac 1 -f s16le pipe:1`
  - If monitor source is unavailable, fall back to mic-only: `-f pulse -i <mic> -ar 16000 -ac 1 -f s16le pipe:1`
  - Store the `asyncio.subprocess.Process` reference
  - Set `self._is_recording = True`
- [ ] Implement `stop()` method:
  - Send SIGINT to ffmpeg process (graceful shutdown)
  - Wait up to 5 seconds for process to exit, then SIGKILL if needed
  - Set `self._is_recording = False`
  - Return recording stats (duration, chunks processed)
- [ ] Implement `is_recording` property and `recording_stats` property
- [ ] Write tests: `tests/test_recorder_subprocess.py` — mock asyncio.create_subprocess_exec, verify correct ffmpeg command is built for various configs (with/without monitor, custom mic volume, custom sources). Verify stop sends SIGINT. Verify fallback to mic-only when monitor is missing.

### 1.3 Pipeline Integration — Reader Loop
- [ ] In `AudioRecorder`, implement `_reader_loop()` — an async task that:
  - Reads chunks from `self._process.stdout` (4096 bytes at a time, matching existing chunk size)
  - Calls `self._pipeline.process_audio_chunk(chunk)` for each chunk
  - Handles EOF (ffmpeg stopped) and errors
  - Updates stats counters (chunks read, bytes read, duration)
- [ ] In `start()`, create the reader loop as an `asyncio.Task` stored in `self._reader_task`
- [ ] In `stop()`, cancel the reader task after ffmpeg exits, then call `self._pipeline.reset()` to flush
- [ ] Write tests: `tests/test_recorder_integration.py` — create a mock subprocess with fake PCM data on stdout, verify chunks are forwarded to a mock pipeline. Test EOF handling. Test error during read.

### 1.4 Optional WAV File Saving
- [ ] Add `save_to_file` parameter to `start()` — when provided, use ffmpeg tee muxer or a second output to write a WAV file alongside piping to stdout
- [ ] The ffmpeg command becomes: `ffmpeg ... -f s16le pipe:1 -ar 16000 -ac 1 -c:a pcm_s16le <file_path>` (two outputs)
- [ ] Create recordings directory structure: `<recordings_dir>/<YYYYMMDD>/meeting_<timestamp>/`
- [ ] Write a JSON metadata sidecar file (same format as record_audio.sh): title, timestamp, audio_file, created_at, source
- [ ] Write tests: verify ffmpeg command includes file output when `save_to_file=True`. Verify directory creation. Verify metadata JSON structure.

---

## Phase 2 — REST API Endpoints

### 2.1 Configuration Updates
- [ ] Add new fields to `Settings` in `backend/config.py`:
  - `audio_capture_mode: str = "backend"` (values: "backend", "browser", "both")
  - `recordings_dir: str = "./recordings"`
  - `mic_volume: float = 2.0`
  - `default_mic_source: str = ""` (empty = auto-detect)
  - `default_monitor_source: str = ""` (empty = auto-detect)
  - `save_recordings: bool = True`
- [ ] Update `.env.example` with the new variables documented
- [ ] Write tests: verify Settings loads new fields from env vars with correct defaults

### 2.2 Device Discovery Endpoint
- [ ] Add `GET /api/audio/devices` endpoint to `main.py`:
  - Calls `AudioRecorder.list_devices()` and `AudioRecorder.get_defaults()`
  - Returns JSON with sources, sinks, and defaults
  - Returns 503 if pactl is not available (with clear error message)
- [ ] Write tests: mock AudioRecorder.list_devices, verify endpoint response shape

### 2.3 Recording Control Endpoints
- [ ] Instantiate `AudioRecorder` in `main.py` (wired to the existing `audio_pipeline`)
- [ ] Add `POST /api/recording/start` endpoint:
  - Accepts optional body: `title`, `mic_source`, `monitor_source`, `mic_volume`, `save_file`
  - Creates a new session via `session_store.create_session()`
  - Calls `recorder.start()` with the provided or default parameters
  - Returns session_id, status, and active device names
  - Returns 409 if already recording
  - Returns 503 if dependencies (pactl/ffmpeg) are missing
- [ ] Add `POST /api/recording/stop` endpoint:
  - Calls `recorder.stop()`
  - Returns session_id, duration, segments count, file path
  - Returns 409 if not currently recording
- [ ] Add `GET /api/recording/status` endpoint:
  - Returns is_recording, session_id, duration, chunks/segments counts
  - Returns status "idle" when not recording
- [ ] Write tests: `tests/test_recording_endpoints.py` — test start/stop/status lifecycle with mocked AudioRecorder. Test error cases: start while already recording, stop when not recording, missing dependencies.

### 2.4 Wire Segments to Session Storage
- [ ] When recording starts, wire `context_manager.on_new_segment` to also call `session_store.save_segment()` for the active session
- [ ] When recording stops, save final meeting state (summary, action items) to session
- [ ] Write tests: verify segments are persisted during a recording session

---

## Phase 3 — Frontend Updates

### 3.1 New Types and API Client
- [ ] Add new TypeScript interfaces to `frontend/src/types/messages.ts`:
  - `AudioDevice { name: string; description: string }`
  - `DeviceListResponse { sources: AudioDevice[]; sinks: AudioDevice[]; defaults: { source: string; sink: string; monitor: string } }`
  - `RecordingStartRequest { title?: string; mic_source?: string; monitor_source?: string; mic_volume?: number; save_file?: boolean }`
  - `RecordingStartResponse { session_id: string; status: string; mic_source: string; monitor_source: string }`
  - `RecordingStopResponse { session_id: string; status: string; duration_seconds: number; segments_count: number; file_path?: string }`
  - `RecordingStatusResponse { is_recording: boolean; session_id?: string; duration_seconds: number; chunks_processed: number; segments_emitted: number }`
- [ ] Verify `npm run build` compiles with no errors

### 3.2 Rewrite useAudioCapture Hook
- [ ] Rewrite `frontend/src/hooks/useAudioCapture.ts`:
  - Remove `getUserMedia`, `AudioContext`, `ScriptProcessor`, and WebSocket audio sending logic
  - Replace with REST API calls to `/api/recording/start`, `/api/recording/stop`, `/api/recording/status`
  - Expose: `start(options)`, `stop()`, `isRecording`, `status`, `devices`
  - Add `fetchDevices()` that calls `GET /api/audio/devices`
  - Add a polling interval (every 2s) for recording status while active
- [ ] Verify `npm run build` compiles with no errors

### 3.3 Device Picker Component
- [ ] Create `frontend/src/components/DevicePicker.tsx`:
  - Dropdown for microphone source (populated from `/api/audio/devices`)
  - Dropdown for system audio source (monitor sources)
  - Shows default selections
  - "Refresh devices" button
  - Slider or input for mic volume boost (default 2.0)
- [ ] Verify `npm run build` compiles with no errors

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
