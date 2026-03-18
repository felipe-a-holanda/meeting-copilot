"""AudioPipeline: combines VAD + Whisper transcription and emits TranscriptSegments."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

import numpy as np

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


class AudioPipelineStats:
    """Counters for pipeline activity, exposed via /debug endpoint."""

    def __init__(self) -> None:
        self.chunks_received: int = 0
        self.bytes_received: int = 0
        self.vad_speech: int = 0
        self.vad_no_speech: int = 0
        self.vad_unavailable: int = 0
        self.transcription_attempts: int = 0
        self.transcription_results: int = 0
        self.transcription_errors: int = 0
        self.segments_emitted: int = 0

    def to_dict(self, pipeline: "AudioPipeline") -> dict:
        return {
            "chunks_received": self.chunks_received,
            "bytes_received": self.bytes_received,
            "vad_speech": self.vad_speech,
            "vad_no_speech": self.vad_no_speech,
            "vad_unavailable": self.vad_unavailable,
            "transcription_attempts": self.transcription_attempts,
            "transcription_results": self.transcription_results,
            "transcription_errors": self.transcription_errors,
            "segments_emitted": self.segments_emitted,
            "whisper_model_loaded": pipeline._transcriber._model is not None,
            "whisper_model_size": pipeline._transcriber.model_size,
        }


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
        self.stats = AudioPipelineStats()

        # Per-speaker rolling audio buffers — one entry per speaker_label so that
        # concurrent mic and monitor streams do not cross-contaminate each other.
        self._buffers: dict[str, np.ndarray] = {}
        self._buffer_start_times: dict[str, float] = {}
        self._meeting_start: float | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def on_segment(self, callback: SegmentCallback) -> None:
        """Register an async callback that receives each finalised TranscriptSegment."""
        self._callback = callback

    async def process_audio_chunk(self, chunk: bytes, speaker_label: str = "Speaker") -> None:
        """Feed a chunk of raw int16 PCM audio into the pipeline.

        Args:
            chunk: Raw PCM bytes — int16, mono, 16 kHz, little-endian.
            speaker_label: Speaker label to assign to all segments from this chunk.
        """
        self.stats.chunks_received += 1
        self.stats.bytes_received += len(chunk)

        if self._meeting_start is None:
            self._meeting_start = time.monotonic()

        # Parse bytes → int16 numpy array
        audio_int16 = np.frombuffer(chunk, dtype=_DTYPE)

        # Use a per-speaker buffer so concurrent mic/monitor streams don't mix
        if speaker_label not in self._buffers:
            self._buffers[speaker_label] = np.array([], dtype=_DTYPE)
            self._buffer_start_times[speaker_label] = 0.0
        self._buffers[speaker_label] = np.concatenate([self._buffers[speaker_label], audio_int16])

        # Only process once we have a meaningful amount of audio
        if len(self._buffers[speaker_label]) < _MIN_CHUNK_SAMPLES:
            return

        await self._process_buffer(speaker_label=speaker_label)

    async def reset(self, speaker_label: str = "Speaker") -> None:
        """Flush all per-speaker buffers and reset pipeline state (e.g. at meeting end)."""
        for label, buf in list(self._buffers.items()):
            if len(buf) > 0:
                await self._process_buffer(force=True, speaker_label=label)
        self._buffers = {}
        self._buffer_start_times = {}
        self._meeting_start = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _elapsed_seconds(self) -> float:
        if self._meeting_start is None:
            return 0.0
        return time.monotonic() - self._meeting_start

    async def _process_buffer(self, force: bool = False, speaker_label: str = "Speaker") -> None:
        """Run VAD + transcription on the accumulated buffer for *speaker_label*."""
        buf = self._buffers.get(speaker_label, np.array([], dtype=_DTYPE))
        audio_int16 = buf.copy()
        self._buffers[speaker_label] = np.array([], dtype=_DTYPE)

        # Convert to float32 for both VAD and Whisper
        audio_f32 = audio_int16.astype(np.float32) / 32768.0

        # VAD gate: skip processing if no speech detected (unless forced)
        if not force:
            try:
                has_speech = self._vad.is_speech(audio_f32)
                if not has_speech:
                    self.stats.vad_no_speech += 1
                    logger.debug("VAD: no speech in chunk, skipping transcription.")
                    return
                else:
                    self.stats.vad_speech += 1
            except RuntimeError:
                # VAD unavailable (torch not installed) — proceed anyway
                self.stats.vad_unavailable += 1
                logger.debug("VAD unavailable, skipping VAD gate.")

        # Compute timestamp for the start of this chunk (per-speaker clock)
        chunk_duration = len(audio_int16) / _SAMPLE_RATE
        chunk_start = self._buffer_start_times.get(speaker_label, 0.0)
        self._buffer_start_times[speaker_label] = chunk_start + chunk_duration

        # Transcribe
        self.stats.transcription_attempts += 1
        try:
            results = self._transcriber.transcribe(audio_f32)
            self.stats.transcription_results += len(results)
        except RuntimeError as exc:
            self.stats.transcription_errors += 1
            logger.warning("Transcription failed: %s", exc)
            return

        if not self._callback:
            return

        for result in results:
            if not result.text:
                continue

            segment = TranscriptSegment(
                speaker=speaker_label,
                text=result.text,
                timestamp_start=chunk_start + result.start,
                timestamp_end=chunk_start + result.end,
                language=result.language or self.config.language,
                is_partial=result.is_partial,
            )
            self.stats.segments_emitted += 1
            try:
                await self._callback(segment)
            except Exception as exc:
                logger.error("Segment callback raised: %s", exc)
