# Build Context — Meeting Copilot
> Atualizado automaticamente pelo agente após cada iteração.

## Estado Atual
- **Fase**: 4 — Integration & Polish (in progress)
- **Última tarefa**: 4.5 Error Handling & Edge Cases
- **Testes passando**: 372 (backend); frontend build clean

## Decisões Técnicas
- `_stopping: bool` flag on `AudioRecorder` distinguishes graceful `stop()` from unexpected crash. Set to `True` before sending SIGINT so reader-loop `finally` blocks skip crash detection. Also set in E2E test helper before waiting for reader tasks (mock EOF != crash).
- `_active_stream_count: int` tracks running reader loops. When any stream crashes (unexpected EOF), count decrements; only when it hits 0 does `_handle_crash()` fire. This allows single-stream failure to continue with the surviving stream.
- Startup calls `pkill -f "ffmpeg.*-f pulse"` to clean up orphaned processes from previous server runs. Silently ignored if pkill is unavailable or no processes matched.
- `audio_capture_mode` added to `GET /settings` response; `App.tsx` fetches it on mount. Audio WS (`/ws/audio`) is only opened for `browser` or `both` modes — never opened in default `backend` mode.
- `_active_session_id: str | None` module-level var in `main.py` tracks the session tied to the current recording. Cleared on `stop`.
- `is_recording` is a property on `AudioRecorder` — tests must mock the whole `audio_recorder` object (not the property directly) using `patch("backend.main.audio_recorder", mock_recorder)`.
- `segments_emitted` / `segments_count` are read from `session_store.load_session()` at stop/status time (not tracked in a counter), keeping state in one place.
- `RecordingStartRequest.save_file` defaults to `None` meaning "use `settings.save_recordings`".
- `_segment_handler` in `main.py` wraps `context_manager.on_new_segment` + `session_store.save_segment` — registered as the single `audio_pipeline.on_segment` callback. Avoids multi-callback complexity in pipeline.

## Problemas Conhecidos / Armadilhas
- `settings.whisper_model_size` does not exist — the real attribute is `settings.whisper_model`. Same for `settings.use_claude_api_fallback` → `settings.use_api_fallback`. Fixed in 4.4; `GET /settings` was returning wrong values before.
- Speaker label "Me"/"Them" requires two ffmpeg processes. If monitor source is unavailable, only mic stream runs (all chunks labeled "Me").
- E2E tests use `autouse` async fixture to reset module-level `audio_recorder` and `audio_pipeline` state between tests; required because both are singletons in `main.py`.

## Arquivos Críticos
- `backend/main.py` — FastAPI app, all REST and WS endpoints
- `backend/audio/recorder.py` — AudioRecorder with dual ffmpeg streams
- `backend/audio/pipeline.py` — AudioPipeline with speaker_label passthrough
- `backend/storage/session.py` — SessionStore (SQLite via aiosqlite)
- `frontend/src/hooks/useAudioCapture.ts` — REST-based recording hook (no getUserMedia)
- `frontend/src/App.tsx` — audio WS removed; only control WS remains
- `TASK_LOG.md` — ground truth for what to do next
