import asyncio
import json
import logging

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
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
