# Build Context — Meeting Copilot
> Atualizado automaticamente pelo agente após cada iteração.

## Estado Atual
- **Fase**: 4 — Integration & Polish (in progress)
- **Última tarefa**: 4.1 End-to-End Integration Test
- **Testes passando**: 341 (backend); frontend build clean

## Decisões Técnicas
- `audio_capture_mode` added to `GET /settings` response; `App.tsx` fetches it on mount. Audio WS (`/ws/audio`) is only opened for `browser` or `both` modes — never opened in default `backend` mode.
- `_active_session_id: str | None` module-level var in `main.py` tracks the session tied to the current recording. Cleared on `stop`.
- `is_recording` is a property on `AudioRecorder` — tests must mock the whole `audio_recorder` object (not the property directly) using `patch("backend.main.audio_recorder", mock_recorder)`.
- `segments_emitted` / `segments_count` are read from `session_store.load_session()` at stop/status time (not tracked in a counter), keeping state in one place.
- `RecordingStartRequest.save_file` defaults to `None` meaning "use `settings.save_recordings`".
- `_segment_handler` in `main.py` wraps `context_manager.on_new_segment` + `session_store.save_segment` — registered as the single `audio_pipeline.on_segment` callback. Avoids multi-callback complexity in pipeline.

## Problemas Conhecidos / Armadilhas
- `main.py` still references `settings.enable_diarization` and `audio_pipeline.set_diarization_enabled()` in `get_settings`/`update_settings` — these were removed in Phase 1B but `main.py` wasn't updated. Pre-existing issue; not blocking current tasks.
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
