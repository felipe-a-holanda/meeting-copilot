"""SpeakerDiarizer: pyannote.audio wrapper for speaker identification.

Lazy-loads the pyannote pipeline on first use so the server starts quickly
and works even when pyannote is not installed (diarization simply disabled).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class DiarizationResult:
    """Speaker label and time range (in seconds, relative to audio start)."""
    speaker: str
    start: float
    end: float


class SpeakerDiarizer:
    """Wraps pyannote.audio Pipeline for speaker diarization.

    Usage::

        diarizer = SpeakerDiarizer(hf_token="hf_...")
        results = diarizer.diarize(audio_f32, sample_rate=16000)
        speaker = diarizer.get_speaker_at(results, timestamp=1.3)
    """

    _MODEL_ID = "pyannote/speaker-diarization-3.1"

    def __init__(self, hf_token: str = "") -> None:
        self._hf_token = hf_token
        self._pipeline = None  # lazy load

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def diarize(self, audio: np.ndarray, sample_rate: int = 16000) -> list[DiarizationResult]:
        """Run speaker diarization on a float32 mono audio array.

        Args:
            audio: Float32 numpy array, values in [-1, 1], mono.
            sample_rate: Sample rate in Hz (should match pipeline expectation).

        Returns:
            List of DiarizationResult sorted by start time.

        Raises:
            RuntimeError: If pyannote.audio or torch is not installed.
        """
        if self._pipeline is None:
            self._load()

        try:
            import torch
        except ImportError:
            raise RuntimeError(
                "torch is required for speaker diarization. "
                "Install it with: pip install torch"
            )

        waveform = torch.from_numpy(audio).unsqueeze(0)  # (1, samples)
        annotation = self._pipeline({"waveform": waveform, "sample_rate": sample_rate})

        results: list[DiarizationResult] = []
        for segment, _, speaker in annotation.itertracks(yield_label=True):
            results.append(
                DiarizationResult(
                    speaker=speaker,
                    start=float(segment.start),
                    end=float(segment.end),
                )
            )
        return sorted(results, key=lambda r: r.start)

    def get_speaker_at(
        self,
        results: list[DiarizationResult],
        timestamp: float,
        fallback: str = "Speaker",
    ) -> str:
        """Return the speaker label active at *timestamp* (seconds).

        If no diarization result covers the timestamp, returns *fallback*.
        """
        for r in results:
            if r.start <= timestamp <= r.end:
                return r.speaker
        return fallback

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load the pyannote pipeline (downloads model on first run)."""
        try:
            from pyannote.audio import Pipeline  # type: ignore
        except ImportError:
            raise RuntimeError(
                "pyannote.audio is not installed. "
                "Install it with: pip install pyannote.audio"
            )

        logger.info("Loading pyannote diarization model: %s", self._MODEL_ID)
        self._pipeline = Pipeline.from_pretrained(
            self._MODEL_ID,
            use_auth_token=self._hf_token or None,
        )
        logger.info("Diarization model loaded.")
