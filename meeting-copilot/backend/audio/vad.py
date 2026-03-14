"""Silero VAD wrapper for voice activity detection."""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

# Silero VAD expects 16 kHz or 8 kHz input.
_SAMPLE_RATE = 16000
# Minimum number of samples for a chunk (Silero requires multiples of 512 at 16 kHz)
_CHUNK_SAMPLES = 512


@dataclass
class SpeechSegment:
    """A detected speech segment with start/end sample offsets."""
    start_sample: int
    end_sample: int

    def duration_samples(self) -> int:
        return self.end_sample - self.start_sample


class SileroVAD:
    """Thin wrapper around the Silero VAD model from torch.hub."""

    # Speech probability threshold
    THRESHOLD: float = 0.5

    def __init__(self):
        self._model = None
        self._get_speech_timestamps = None

    def _load(self):
        if self._model is not None:
            return
        try:
            import torch
            model, utils = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                force_reload=False,
                onnx=False,
                verbose=False,
            )
            self._model = model
            self._get_speech_timestamps = utils[0]  # get_speech_timestamps
            logger.info("Silero VAD loaded.")
        except ImportError as exc:
            raise RuntimeError(
                "torch is not installed. Run: pip install torch"
            ) from exc

    def is_speech(self, audio: np.ndarray, sample_rate: int = _SAMPLE_RATE) -> bool:
        """Return True if the audio chunk contains speech.

        Args:
            audio: float32 numpy array, mono.
            sample_rate: Must be 16000 or 8000.
        """
        self._load()
        import torch

        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        if np.abs(audio).max() > 1.0:
            audio = audio / 32768.0

        tensor = torch.from_numpy(audio)
        # Process in chunks if longer than expected
        # Silero model accepts any length but works best chunk-by-chunk
        speech_timestamps = self._get_speech_timestamps(
            tensor,
            self._model,
            threshold=self.THRESHOLD,
            sampling_rate=sample_rate,
            return_seconds=False,
        )
        return len(speech_timestamps) > 0

    def get_speech_segments(
        self, audio: np.ndarray, sample_rate: int = _SAMPLE_RATE
    ) -> list[SpeechSegment]:
        """Return list of speech segments detected in the audio.

        Args:
            audio: float32 numpy array, mono.
            sample_rate: Must be 16000 or 8000.
        """
        self._load()
        import torch

        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        if np.abs(audio).max() > 1.0:
            audio = audio / 32768.0

        tensor = torch.from_numpy(audio)
        raw = self._get_speech_timestamps(
            tensor,
            self._model,
            threshold=self.THRESHOLD,
            sampling_rate=sample_rate,
            return_seconds=False,
        )
        return [SpeechSegment(start_sample=s["start"], end_sample=s["end"]) for s in raw]
