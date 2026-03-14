import asyncio
import datetime
import json
import logging

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from backend.audio.pipeline import AudioPipeline
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


@app.on_event("startup")
async def _startup() -> None:
    await session_store.init_db()

dispatcher = LLMDispatcher(settings)


async def _broadcast_to_clients(data: dict) -> None:
    """Broadcast a dict payload as JSON to all connected control clients."""
    await control_manager.broadcast(json.dumps(data))


context_manager = ContextManager(
    dispatcher=dispatcher,
    broadcast_fn=_broadcast_to_clients,
)

# Wire audio pipeline → context manager
audio_pipeline.on_segment(context_manager.on_new_segment)


class CreateSessionRequest(BaseModel):
    title: str = ""


class SettingsUpdate(BaseModel):
    enable_diarization: bool | None = None
    whisper_model_size: str | None = None
    use_claude_api_fallback: bool | None = None


# Runtime-overridable settings (supplement the env-based Settings)
_runtime_settings: dict = {}


@app.get("/settings")
async def get_settings() -> dict:
    return {
        "enable_diarization": _runtime_settings.get(
            "enable_diarization", settings.enable_diarization
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


@app.websocket("/ws/audio")
async def ws_audio(websocket: WebSocket) -> None:
    """Receives raw PCM audio bytes from the browser."""
    await audio_manager.connect(websocket)
    logger.info("Audio WebSocket connected")
    try:
        while True:
            data = await websocket.receive_bytes()
            logger.debug("Received %d audio bytes", len(data))
            await audio_pipeline.process_audio_chunk(data)
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
    except WebSocketDisconnect:
        logger.info("Control WebSocket disconnected")
    finally:
        control_manager.disconnect(websocket)
