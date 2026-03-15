# Build Context — Meeting Copilot
> Atualizado automaticamente pelo agente após cada iteração.

## Estado Atual
- **Fase**: 2 — REST API Endpoints
- **Última tarefa**: 2.3 Recording Control Endpoints
- **Testes passando**: 326

## Decisões Técnicas
- `_active_session_id: str | None` module-level var in `main.py` tracks the session tied to the current recording. Cleared on `stop`.
- `is_recording` is a property on `AudioRecorder` — tests must mock the whole `audio_recorder` object (not the property directly) using `patch("backend.main.audio_recorder", mock_recorder)`.
- `segments_emitted` / `segments_count` are read from `session_store.load_session()` at stop/status time (not tracked in a counter), keeping state in one place.
- `RecordingStartRequest.save_file` defaults to `None` meaning "use `settings.save_recordings`".

## Problemas Conhecidos / Armadilhas
- `main.py` still references `settings.enable_diarization` and `audio_pipeline.set_diarization_enabled()` in `get_settings`/`update_settings` — these were removed in Phase 1B but `main.py` wasn't updated. Pre-existing issue; not blocking current tasks.
- Speaker label "Me"/"Them" requires two ffmpeg processes. If monitor source is unavailable, only mic stream runs (all chunks labeled "Me").

## Arquivos Críticos
- `backend/main.py` — FastAPI app, all REST and WS endpoints
- `backend/audio/recorder.py` — AudioRecorder with dual ffmpeg streams
- `backend/audio/pipeline.py` — AudioPipeline with speaker_label passthrough
- `backend/storage/session.py` — SessionStore (SQLite via aiosqlite)
- `TASK_LOG.md` — ground truth for what to do next
