"""AudioPipeline: combines VAD + Whisper transcription and emits TranscriptSegments."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

import numpy as np

from backend.audio.diarizer import SpeakerDiarizer
from backend.audio.transcriber import WhisperTranscriber
from backend.audio.vad import SileroVAD
from backend.ws.protocol import TranscriptSegment

logger = logging.getLogger(__name__)

# PCM format expected from the frontend
_SAMPLE_RATE = 16000
_CHANNELS = 1
_DTYPE = np.int16  # int16 PCM from browser WebAudio API

# Accumulate at least this many seconds before attempting transcription.
# Whisper performs poorly on very short clips.
_MIN_CHUNK_SECONDS = 1.0
_MIN_CHUNK_SAMPLES = int(_MIN_CHUNK_SECONDS * _SAMPLE_RATE)

SegmentCallback = Callable[[TranscriptSegment], Awaitable[None]]


class AudioPipeline:
    """Accepts raw PCM audio bytes and emits TranscriptSegment events.

    Usage::

        pipeline = AudioPipeline(settings)
        pipeline.on_segment(my_async_callback)

        # In the WebSocket handler:
        await pipeline.process_audio_chunk(raw_bytes)
    """

    def __init__(self, config):
        self.config = config
        self._transcriber = WhisperTranscriber(
            model_size=config.whisper_model,
            language=config.language or None,
        )
        self._vad = SileroVAD()
        self._callback: SegmentCallback | None = None

        # Diarization (optional — disabled if enable_diarization is False)
        if getattr(config, "enable_diarization", False):
            self._diarizer: SpeakerDiarizer | None = SpeakerDiarizer(
                hf_token=getattr(config, "hf_token", "")
            )
        else:
            self._diarizer = None

        # Rolling audio buffer — accumulates bytes until there is enough to transcribe
        self._buffer: np.ndarray = np.array([], dtype=_DTYPE)
        self._buffer_start_time: float = 0.0  # seconds from meeting start
        self._meeting_start: float | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def on_segment(self, callback: SegmentCallback) -> None:
        """Register an async callback that receives each finalised TranscriptSegment."""
        self._callback = callback

    def set_diarization_enabled(self, enabled: bool) -> None:
        """Enable or disable speaker diarization at runtime."""
        if enabled and self._diarizer is None:
            self._diarizer = SpeakerDiarizer(
                hf_token=getattr(self.config, "hf_token", "")
            )
        elif not enabled:
            self._diarizer = None

    async def process_audio_chunk(self, chunk: bytes) -> None:
        """Feed a chunk of raw int16 PCM audio into the pipeline.

        Args:
            chunk: Raw PCM bytes — int16, mono, 16 kHz, little-endian.
        """
        if self._meeting_start is None:
            self._meeting_start = time.monotonic()

        # Parse bytes → int16 numpy array
        audio_int16 = np.frombuffer(chunk, dtype=_DTYPE)
        self._buffer = np.concatenate([self._buffer, audio_int16])

        # Only process once we have a meaningful amount of audio
        if len(self._buffer) < _MIN_CHUNK_SAMPLES:
            return

        await self._process_buffer()

    async def reset(self) -> None:
        """Flush the buffer and reset pipeline state (e.g. at meeting end)."""
        if len(self._buffer) > 0:
            await self._process_buffer(force=True)
        self._buffer = np.array([], dtype=_DTYPE)
        self._meeting_start = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _elapsed_seconds(self) -> float:
        if self._meeting_start is None:
            return 0.0
        return time.monotonic() - self._meeting_start

    async def _process_buffer(self, force: bool = False) -> None:
        """Run VAD + transcription on the accumulated buffer."""
        audio_int16 = self._buffer.copy()
        self._buffer = np.array([], dtype=_DTYPE)

        # Convert to float32 for both VAD and Whisper
        audio_f32 = audio_int16.astype(np.float32) / 32768.0

        # VAD gate: skip processing if no speech detected (unless forced)
        if not force:
            try:
                has_speech = self._vad.is_speech(audio_f32)
                if not has_speech:
                    logger.debug("VAD: no speech in chunk, skipping transcription.")
                    return
            except RuntimeError:
                # VAD unavailable (torch not installed) — proceed anyway
                logger.debug("VAD unavailable, skipping VAD gate.")

        # Compute timestamp for the start of this chunk
        chunk_duration = len(audio_int16) / _SAMPLE_RATE
        chunk_start = self._buffer_start_time
        self._buffer_start_time += chunk_duration

        # Transcribe
        try:
            results = self._transcriber.transcribe(audio_f32)
        except RuntimeError as exc:
            logger.warning("Transcription failed: %s", exc)
            return

        if not self._callback:
            return

        # Diarize (optional) — run once per buffer on the same audio chunk
        diarization: list = []
        if self._diarizer is not None:
            try:
                diarization = self._diarizer.diarize(audio_f32, sample_rate=_SAMPLE_RATE)
            except RuntimeError as exc:
                logger.warning("Diarization failed, falling back to 'Speaker': %s", exc)

        for result in results:
            if not result.text:
                continue

            # Assign speaker label from diarization (mid-point of segment)
            if diarization:
                mid = (result.start + result.end) / 2.0
                speaker = self._diarizer.get_speaker_at(diarization, mid)
            else:
                speaker = "Speaker"

            segment = TranscriptSegment(
                speaker=speaker,
                text=result.text,
                timestamp_start=chunk_start + result.start,
                timestamp_end=chunk_start + result.end,
                language=result.language or self.config.language,
                is_partial=result.is_partial,
            )
            try:
                await self._callback(segment)
            except Exception as exc:
                logger.error("Segment callback raised: %s", exc)
