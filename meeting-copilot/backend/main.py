import asyncio
import datetime
import json
import logging

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
import tempfile
from pathlib import Path

from backend.audio.pipeline import AudioPipeline
from backend.audio.file_processor import FileAudioProcessor
from backend.audio.recorder import AudioRecorder
from backend.config import Settings
from backend.reasoning.context_manager import ContextManager
from backend.reasoning.dispatcher import LLMDispatcher
from backend.storage.session import SessionStore
from backend.ws.gateway import ConnectionManager
from backend.ws.protocol import CustomPromptRequest, RequestReplySuggestion

logger = logging.getLogger(__name__)

settings = Settings()
app = FastAPI(title="Meeting Copilot", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

audio_manager = ConnectionManager()
control_manager = ConnectionManager()
audio_pipeline = AudioPipeline(settings)
session_store = SessionStore(db_path=settings.db_path)
file_processor = FileAudioProcessor(settings, session_store)
audio_recorder = AudioRecorder(pipeline=audio_pipeline, recordings_dir=settings.recordings_dir)


@app.on_event("startup")
async def _startup() -> None:
    await session_store.init_db()

dispatcher = LLMDispatcher(settings)


async def _broadcast_to_clients(data: dict) -> None:
    """Broadcast a dict payload as JSON to all connected control clients."""
    await control_manager.broadcast(data)


async def _broadcast_error(message: str, *, context: str | None = None) -> None:
    payload: dict[str, str] = {"type": "error", "message": message}
    if context:
        payload["context"] = context
    await _broadcast_to_clients(payload)


context_manager = ContextManager(
    dispatcher=dispatcher,
    broadcast_fn=_broadcast_to_clients,
)


async def _segment_handler(segment) -> None:
    """Forward segment to context manager and persist to the active session."""
    await context_manager.on_new_segment(segment)
    if _active_session_id:
        await session_store.save_segment(_active_session_id, segment)


# Wire audio pipeline → context manager + session persistence
audio_pipeline.on_segment(_segment_handler)


class CreateSessionRequest(BaseModel):
    title: str = ""


class SettingsUpdate(BaseModel):
    enable_diarization: bool | None = None
    whisper_model_size: str | None = None
    use_claude_api_fallback: bool | None = None


class RecordingStartRequest(BaseModel):
    title: str = ""
    mic_source: str | None = None
    monitor_source: str | None = None
    mic_volume: float = 2.0
    save_file: bool | None = None  # None = use settings default


# Active recording session tracking (module-level, single recorder instance)
_active_session_id: str | None = None


# Runtime-overridable settings (supplement the env-based Settings)
_runtime_settings: dict = {}


@app.get("/settings")
async def get_settings() -> dict:
    return {
        "audio_capture_mode": _runtime_settings.get(
            "audio_capture_mode", settings.audio_capture_mode
        ),
        "whisper_model_size": _runtime_settings.get(
            "whisper_model_size", settings.whisper_model_size
        ),
        "use_claude_api_fallback": _runtime_settings.get(
            "use_claude_api_fallback", settings.use_claude_api_fallback
        ),
    }


@app.post("/settings")
async def update_settings(body: SettingsUpdate) -> dict:
    if body.enable_diarization is not None:
        _runtime_settings["enable_diarization"] = body.enable_diarization
        audio_pipeline.set_diarization_enabled(body.enable_diarization)
    if body.whisper_model_size is not None:
        _runtime_settings["whisper_model_size"] = body.whisper_model_size
    if body.use_claude_api_fallback is not None:
        _runtime_settings["use_claude_api_fallback"] = body.use_claude_api_fallback
        dispatcher.use_api_fallback = body.use_claude_api_fallback
    return {"status": "ok", **_runtime_settings}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/audio/devices")
async def get_audio_devices() -> dict:
    """Return available PulseAudio sources and sinks with defaults.

    Returns 503 if pactl is not installed or not accessible.
    """
    dep_status = await AudioRecorder.check_dependencies()
    if not dep_status.pactl_available:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "pactl not available",
                "message": dep_status.errors[0] if dep_status.errors else "pactl is not installed",
            },
        )

    try:
        device_list = await audio_recorder.list_devices()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "device_discovery_failed", "message": str(exc)},
        )

    return {
        "sources": [{"name": d.name, "description": d.description} for d in device_list.sources],
        "sinks": [{"name": d.name, "description": d.description} for d in device_list.sinks],
        "defaults": {
            "source": device_list.defaults.source,
            "sink": device_list.defaults.sink,
            "monitor": device_list.defaults.monitor,
        },
    }


@app.post("/api/recording/start", status_code=200)
async def start_recording(body: RecordingStartRequest) -> dict:
    """Start backend audio capture and create a new session.

    Returns 409 if already recording.
    Returns 503 if pactl/ffmpeg are not available.
    """
    global _active_session_id

    if audio_recorder.is_recording:
        raise HTTPException(status_code=409, detail="Recording is already in progress")

    dep_status = await AudioRecorder.check_dependencies()
    if not dep_status.all_available:
        missing = ", ".join(dep_status.errors)
        raise HTTPException(
            status_code=503,
            detail={"error": "dependencies_missing", "message": missing},
        )

    # Create a new session before starting recorder
    session_info = await session_store.create_session(title=body.title)

    save_file = body.save_file if body.save_file is not None else settings.save_recordings
    try:
        await audio_recorder.start(
            mic_source=body.mic_source,
            monitor_source=body.monitor_source,
            mic_volume=body.mic_volume,
            save_to_file=save_file,
            title=body.title or session_info.title,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail={"error": "recorder_start_failed", "message": str(exc)})

    _active_session_id = session_info.id

    return {
        "session_id": session_info.id,
        "status": "recording",
        "mic_source": audio_recorder._mic_source,
        "monitor_source": audio_recorder._monitor_source,
    }


@app.post("/api/recording/stop", status_code=200)
async def stop_recording() -> dict:
    """Stop the active backend audio capture.

    Returns 409 if not currently recording.
    """
    global _active_session_id

    if not audio_recorder.is_recording:
        raise HTTPException(status_code=409, detail="Not currently recording")

    session_id = _active_session_id
    stats = await audio_recorder.stop()
    _active_session_id = None

    # Persist final summary and action items for the session
    if session_id:
        await session_store.save_state(
            session_id,
            context_manager.state.current_summary,
            context_manager.state.action_items,
        )

    # Count persisted segments for the session
    segments_count = 0
    if session_id:
        session_data = await session_store.load_session(session_id)
        if session_data is not None:
            segments_count = len(session_data.segments)

    return {
        "session_id": session_id,
        "status": "stopped",
        "duration_seconds": stats.duration_seconds,
        "segments_count": segments_count,
        "file_path": stats.file_path,
    }


@app.get("/api/recording/status")
async def recording_status() -> dict:
    """Return current recording state.

    Returns status "idle" when not recording, "recording" when active.
    """
    if not audio_recorder.is_recording:
        return {
            "is_recording": False,
            "session_id": None,
            "status": "idle",
            "duration_seconds": 0.0,
            "chunks_processed": 0,
            "segments_emitted": 0,
        }

    stats = audio_recorder.recording_stats

    # Count persisted segments for the active session
    segments_emitted = 0
    if _active_session_id:
        session_data = await session_store.load_session(_active_session_id)
        if session_data is not None:
            segments_emitted = len(session_data.segments)

    return {
        "is_recording": True,
        "session_id": _active_session_id,
        "status": "recording",
        "duration_seconds": stats.duration_seconds,
        "chunks_processed": stats.chunks_processed,
        "segments_emitted": segments_emitted,
    }


@app.get("/debug")
async def debug_info() -> dict:
    """Live pipeline diagnostics — useful for debugging recording/transcription issues."""
    # Build recording state section
    rec_stats = audio_recorder.recording_stats
    ffmpeg_pids: dict[str, int | None] = {}
    if audio_recorder.is_recording:
        ffmpeg_pids["mic"] = audio_recorder._mic_process.pid if audio_recorder._mic_process else None
        ffmpeg_pids["monitor"] = audio_recorder._monitor_process.pid if audio_recorder._monitor_process else None

    return {
        "pipeline": audio_pipeline.stats.to_dict(audio_pipeline),
        "settings": {
            "whisper_model": settings.whisper_model,
            "language": settings.language,
            "audio_capture_mode": _runtime_settings.get(
                "audio_capture_mode", settings.audio_capture_mode
            ),
            "ollama_url": settings.ollama_url,
            "ollama_model": settings.ollama_model,
        },
        "recording": {
            "is_recording": audio_recorder.is_recording,
            "active_session_id": _active_session_id,
            "recording_duration": rec_stats.duration_seconds,
            "mic_source": audio_recorder._mic_source if audio_recorder.is_recording else None,
            "monitor_source": audio_recorder._monitor_source if audio_recorder.is_recording else None,
            "ffmpeg_pids": ffmpeg_pids if audio_recorder.is_recording else {},
        },
        "connections": {
            "audio": len(audio_manager.active_connections),
            "control": len(control_manager.active_connections),
        },
    }


# --- Session REST endpoints ---

@app.get("/sessions")
async def list_sessions() -> list[dict]:
    sessions = await session_store.list_sessions()
    return [
        {
            "id": s.id,
            "title": s.title,
            "created_at": s.created_at,
            "updated_at": s.updated_at,
            "segment_count": s.segment_count,
        }
        for s in sessions
    ]


@app.post("/sessions", status_code=201)
async def create_session(body: CreateSessionRequest) -> dict:
    info = await session_store.create_session(title=body.title)
    return {
        "id": info.id,
        "title": info.title,
        "created_at": info.created_at,
        "updated_at": info.updated_at,
        "segment_count": 0,
    }


@app.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict:
    data = await session_store.load_session(session_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "id": data.id,
        "title": data.title,
        "created_at": data.created_at,
        "updated_at": data.updated_at,
        "summary": data.summary,
        "action_items": [item.model_dump() for item in data.action_items],
        "segments": [seg.model_dump() for seg in data.segments],
    }


def _format_timestamp(seconds: float) -> str:
    """Convert float seconds to HH:MM:SS string."""
    total = int(seconds)
    h, remainder = divmod(total, 3600)
    m, s = divmod(remainder, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _export_markdown(data) -> str:
    """Render a SessionData as a Markdown string."""
    date_str = datetime.datetime.fromtimestamp(data.created_at).strftime("%Y-%m-%d %H:%M")
    lines: list[str] = [
        f"# {data.title}",
        f"",
        f"**Date:** {date_str}",
        f"",
    ]

    # Summary
    lines += ["## Summary", ""]
    lines.append(data.summary if data.summary else "_No summary available._")
    lines.append("")

    # Action Items
    lines += ["## Action Items", ""]
    if data.action_items:
        for item in data.action_items:
            checkbox = "[x]" if item.status == "completed" else "[ ]"
            assignee_part = f" — *{item.assignee}*" if item.assignee else ""
            lines.append(f"- {checkbox} {item.description}{assignee_part}")
    else:
        lines.append("_No action items recorded._")
    lines.append("")

    # Transcript
    lines += ["## Transcript", ""]
    if data.segments:
        for seg in data.segments:
            ts = _format_timestamp(seg.timestamp_start)
            lines.append(f"**{seg.speaker}** [{ts}]: {seg.text}")
    else:
        lines.append("_No transcript available._")
    lines.append("")

    return "\n".join(lines)


@app.get("/sessions/{session_id}/export")
async def export_session(
    session_id: str,
    format: str = Query(default="markdown", pattern="^(markdown|json)$"),
) -> PlainTextResponse:
    data = await session_store.load_session(session_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Session not found")

    if format == "json":
        payload = {
            "id": data.id,
            "title": data.title,
            "created_at": data.created_at,
            "updated_at": data.updated_at,
            "summary": data.summary,
            "action_items": [item.model_dump() for item in data.action_items],
            "segments": [seg.model_dump() for seg in data.segments],
        }
        return PlainTextResponse(
            content=json.dumps(payload, indent=2, ensure_ascii=False),
            media_type="application/json",
        )

    # default: markdown
    return PlainTextResponse(
        content=_export_markdown(data),
        media_type="text/markdown; charset=utf-8",
    )


# --- Audio File Processing ---

@app.post("/sessions/{session_id}/upload-audio")
async def upload_audio_file(
    session_id: str,
    file: UploadFile = File(...),
    model: str = Query(default="turbo"),
    language: str = Query(default="pt"),
    enable_diarization: bool = Query(default=False)
) -> dict:
    """Upload and process an audio file for a session."""
    
    # Validate session exists
    session_data = await session_store.load_session(session_id)
    if session_data is None:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Validate file type
    if not file.filename or not file.filename.lower().endswith(('.wav', '.mp3', '.m4a', '.flac')):
        raise HTTPException(status_code=400, detail="Invalid audio file format")
    
    # Save uploaded file temporarily
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix) as tmp_file:
        content = await file.read()
        tmp_file.write(content)
        tmp_file_path = Path(tmp_file.name)
    
    try:
        # Update settings for this processing
        processing_settings = Settings()
        processing_settings.whisper_model = model
        processing_settings.language = language
        processing_settings.enable_diarization = enable_diarization
        
        # Process file asynchronously
        result = await file_processor.process_file(tmp_file_path, session_id)
        
        return {
            "session_id": session_id,
            "filename": file.filename,
            "processing_result": result
        }
        
    finally:
        # Clean up temporary file
        tmp_file_path.unlink(missing_ok=True)


@app.get("/sessions/{session_id}/processing-status")
async def get_processing_status(session_id: str) -> dict:
    """Get processing status for a session (placeholder for future task tracking)."""
    return {
        "session_id": session_id,
        "status": "completed",
        "message": "Processing complete"
    }


@app.websocket("/ws/audio")
async def ws_audio(websocket: WebSocket) -> None:
    """Receives raw PCM audio bytes from the browser."""
    await audio_manager.connect(websocket)
    logger.info("Audio WebSocket connected")
    try:
        while True:
            data = await websocket.receive_bytes()
            logger.debug("Received %d audio bytes", len(data))
            try:
                await audio_pipeline.process_audio_chunk(data)
            except Exception as exc:
                logger.error("Audio pipeline processing error: %s", exc)
                try:
                    await _broadcast_error(
                        "Audio processing error — see backend logs for details",
                        context="audio_pipeline",
                    )
                except Exception as broadcast_exc:  # pragma: no cover - defensive logging
                    logger.error("Failed to broadcast audio error: %s", broadcast_exc)
    except WebSocketDisconnect:
        logger.info("Audio WebSocket disconnected")
    finally:
        audio_manager.disconnect(websocket)


@app.websocket("/ws/control")
async def ws_control(websocket: WebSocket) -> None:
    """Receives control messages (reply requests, custom prompts) from the browser."""
    await control_manager.connect(websocket)
    logger.info("Control WebSocket connected")
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
                msg_type = payload.get("type")
                if msg_type == "request_reply":
                    msg = RequestReplySuggestion(**payload)
                    logger.info("Reply request received: context_hint=%s", msg.context_hint)
                    asyncio.create_task(
                        context_manager.handle_reply_request(msg.context_hint or "")
                    )
                elif msg_type == "custom_prompt":
                    msg = CustomPromptRequest(**payload)
                    logger.info("Custom prompt received: %s", msg.prompt)
                    asyncio.create_task(
                        context_manager.handle_custom_prompt(msg.prompt)
                    )
                else:
                    logger.warning("Unknown control message type: %s", msg_type)
            except (json.JSONDecodeError, ValueError) as exc:
                logger.error("Invalid control message: %s", exc)
            except Exception as exc:
                logger.error("Unexpected error processing control message: %s", exc)
    except WebSocketDisconnect:
        logger.info("Control WebSocket disconnected")
    finally:
        control_manager.disconnect(websocket)
