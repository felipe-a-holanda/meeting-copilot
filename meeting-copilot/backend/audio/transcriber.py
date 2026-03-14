"""faster-whisper wrapper for streaming transcription."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Generator

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class TranscriptionResult:
    """A single transcription result from Whisper."""
    text: str
    start: float
    end: float
    language: str
    is_partial: bool = False


class WhisperTranscriber:
    """Wraps faster-whisper for transcribing PCM audio chunks."""

    def __init__(self, model_size: str = "large-v3-turbo", language: str = "pt"):
        self.model_size = model_size
        self.language = language or None  # None = auto-detect
        self._model = None

    def _load_model(self):
        """Lazy-load the Whisper model on first use."""
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel
            logger.info("Loading Whisper model: %s", self.model_size)
            self._model = WhisperModel(
                self.model_size,
                device="auto",
                compute_type="int8",
            )
            logger.info("Whisper model loaded.")
        except ImportError as exc:
            raise RuntimeError(
                "faster-whisper is not installed. "
                "Run: pip install faster-whisper"
            ) from exc

    def transcribe(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
    ) -> list[TranscriptionResult]:
        """Transcribe a numpy float32 audio array.

        Args:
            audio: float32 numpy array, mono, at ``sample_rate`` Hz.
            sample_rate: Audio sample rate (Whisper expects 16 kHz).

        Returns:
            List of TranscriptionResult objects.
        """
        self._load_model()

        # Ensure float32 mono
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)

        # Normalise if int16-range values were passed in
        if np.abs(audio).max() > 1.0:
            audio = audio / 32768.0

        segments, info = self._model.transcribe(
            audio,
            language=self.language,
            beam_size=5,
            vad_filter=False,  # VAD handled externally
        )

        results: list[TranscriptionResult] = []
        detected_lang = info.language if info else (self.language or "")
        for seg in segments:
            results.append(
                TranscriptionResult(
                    text=seg.text.strip(),
                    start=seg.start,
                    end=seg.end,
                    language=detected_lang,
                )
            )
        return results
