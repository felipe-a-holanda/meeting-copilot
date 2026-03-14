import json
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from backend.config import Settings
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


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.websocket("/ws/audio")
async def ws_audio(websocket: WebSocket) -> None:
    """Receives raw PCM audio bytes from the browser."""
    await audio_manager.connect(websocket)
    logger.info("Audio WebSocket connected")
    try:
        while True:
            data = await websocket.receive_bytes()
            # Audio bytes will be forwarded to the audio pipeline in task 1.4
            logger.debug("Received %d audio bytes", len(data))
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
                elif msg_type == "custom_prompt":
                    msg = CustomPromptRequest(**payload)
                    logger.info("Custom prompt received: %s", msg.prompt)
                else:
                    logger.warning("Unknown control message type: %s", msg_type)
            except (json.JSONDecodeError, ValueError) as exc:
                logger.error("Invalid control message: %s", exc)
    except WebSocketDisconnect:
        logger.info("Control WebSocket disconnected")
    finally:
        control_manager.disconnect(websocket)
