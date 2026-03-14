"""Tests for SpeakerDiarizer and AudioPipeline diarization integration.

All heavy ML dependencies (pyannote, torch) are mocked so that
these tests run without GPU or model downloads.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_sine_wave(duration_seconds: float = 2.0, sample_rate: int = 16000) -> np.ndarray:
    t = np.linspace(0, duration_seconds, int(sample_rate * duration_seconds), endpoint=False)
    return (np.sin(2 * np.pi * 440 * t) * 0.5).astype(np.float32)


def make_pcm_bytes(duration_seconds: float = 2.0, sample_rate: int = 16000) -> bytes:
    f32 = make_sine_wave(duration_seconds=duration_seconds, sample_rate=sample_rate)
    return (f32 * 32768).astype(np.int16).tobytes()


@dataclass
class _MockSegment:
    start: float
    end: float


def _make_mock_annotation(tracks: list[tuple[float, float, str]]) -> MagicMock:
    """Build a mock pyannote Annotation with given (start, end, speaker) tracks."""
    annotation = MagicMock()
    annotation.itertracks.return_value = [
        (_MockSegment(start, end), None, speaker)
        for start, end, speaker in tracks
    ]
    return annotation


def _make_mock_pipeline(annotation: MagicMock) -> MagicMock:
    pipeline = MagicMock()
    pipeline.return_value = annotation
    return pipeline


def _make_mock_torch(audio_f32: np.ndarray | None = None):
    mock_torch = MagicMock()
    mock_tensor = MagicMock()
    mock_tensor.unsqueeze.return_value = mock_tensor
    mock_torch.from_numpy.return_value = mock_tensor
    return mock_torch


# ---------------------------------------------------------------------------
# SpeakerDiarizer unit tests
# ---------------------------------------------------------------------------

class TestSpeakerDiarizer:

    def test_diarize_returns_results(self):
        """diarize() returns DiarizationResult list from mock pyannote output."""
        from backend.audio.diarizer import SpeakerDiarizer

        annotation = _make_mock_annotation([
            (0.0, 2.0, "SPEAKER_00"),
            (2.1, 4.0, "SPEAKER_01"),
        ])
        mock_pipeline = _make_mock_pipeline(annotation)

        diarizer = SpeakerDiarizer(hf_token="fake-token")
        diarizer._pipeline = mock_pipeline  # inject pre-loaded mock

        audio = make_sine_wave(duration_seconds=4.0)

        with patch.dict(sys.modules, {"torch": _make_mock_torch()}):
            results = diarizer.diarize(audio, sample_rate=16000)

        assert len(results) == 2
        assert results[0].speaker == "SPEAKER_00"
        assert results[0].start == 0.0
        assert results[0].end == 2.0
        assert results[1].speaker == "SPEAKER_01"
        assert results[1].start == 2.1

    def test_diarize_empty_annotation(self):
        """diarize() returns empty list when no speakers detected."""
        from backend.audio.diarizer import SpeakerDiarizer

        annotation = _make_mock_annotation([])
        diarizer = SpeakerDiarizer()
        diarizer._pipeline = _make_mock_pipeline(annotation)

        audio = make_sine_wave(duration_seconds=2.0)
        with patch.dict(sys.modules, {"torch": _make_mock_torch()}):
            results = diarizer.diarize(audio, sample_rate=16000)

        assert results == []

    def test_diarize_sorted_by_start(self):
        """diarize() results are sorted by start time."""
        from backend.audio.diarizer import SpeakerDiarizer

        annotation = _make_mock_annotation([
            (3.0, 5.0, "SPEAKER_01"),
            (0.0, 2.0, "SPEAKER_00"),
        ])
        diarizer = SpeakerDiarizer()
        diarizer._pipeline = _make_mock_pipeline(annotation)

        audio = make_sine_wave(duration_seconds=5.0)
        with patch.dict(sys.modules, {"torch": _make_mock_torch()}):
            results = diarizer.diarize(audio, sample_rate=16000)

        assert results[0].start < results[1].start

    def test_get_speaker_at_returns_correct_speaker(self):
        """get_speaker_at() returns speaker for a timestamp within their segment."""
        from backend.audio.diarizer import SpeakerDiarizer, DiarizationResult

        diarizer = SpeakerDiarizer()
        results = [
            DiarizationResult(speaker="SPEAKER_00", start=0.0, end=2.0),
            DiarizationResult(speaker="SPEAKER_01", start=2.1, end=4.0),
        ]

        assert diarizer.get_speaker_at(results, 1.0) == "SPEAKER_00"
        assert diarizer.get_speaker_at(results, 3.0) == "SPEAKER_01"

    def test_get_speaker_at_gap_returns_fallback(self):
        """get_speaker_at() returns fallback when timestamp falls in a gap."""
        from backend.audio.diarizer import SpeakerDiarizer, DiarizationResult

        diarizer = SpeakerDiarizer()
        results = [
            DiarizationResult(speaker="SPEAKER_00", start=0.0, end=2.0),
            DiarizationResult(speaker="SPEAKER_01", start=2.5, end=4.0),
        ]

        assert diarizer.get_speaker_at(results, 2.2) == "Speaker"
        assert diarizer.get_speaker_at(results, 2.2, fallback="Unknown") == "Unknown"

    def test_get_speaker_at_empty_results_returns_fallback(self):
        """get_speaker_at() returns fallback when no results available."""
        from backend.audio.diarizer import SpeakerDiarizer

        diarizer = SpeakerDiarizer()
        assert diarizer.get_speaker_at([], 1.0) == "Speaker"

    def test_load_raises_on_missing_pyannote(self):
        """SpeakerDiarizer raises RuntimeError if pyannote.audio is not installed."""
        from backend.audio.diarizer import SpeakerDiarizer

        diarizer = SpeakerDiarizer()
        with patch.dict(sys.modules, {"pyannote.audio": None, "pyannote": None}):
            with pytest.raises(RuntimeError, match="pyannote.audio"):
                diarizer._load()

    def test_diarize_raises_on_missing_torch(self):
        """diarize() raises RuntimeError if torch is not installed."""
        from backend.audio.diarizer import SpeakerDiarizer

        annotation = _make_mock_annotation([])
        diarizer = SpeakerDiarizer()
        diarizer._pipeline = _make_mock_pipeline(annotation)

        audio = make_sine_wave(duration_seconds=1.0)
        with patch.dict(sys.modules, {"torch": None}):
            with pytest.raises(RuntimeError, match="torch"):
                diarizer.diarize(audio)

    def test_diarize_result_dataclass_fields(self):
        """DiarizationResult has speaker, start, end fields."""
        from backend.audio.diarizer import DiarizationResult

        r = DiarizationResult(speaker="SPEAKER_00", start=0.5, end=2.5)
        assert r.speaker == "SPEAKER_00"
        assert r.start == 0.5
        assert r.end == 2.5


# ---------------------------------------------------------------------------
# AudioPipeline speaker_label tests
# ---------------------------------------------------------------------------

class TestAudioPipelineSpeakerLabel:

    def _make_config(self):
        cfg = MagicMock()
        cfg.whisper_model = "tiny"
        cfg.language = "pt"
        return cfg

    def _setup_pipeline(self, pipeline, transcript_text="Hello", start=0.0, end=1.5):
        from backend.audio.transcriber import TranscriptionResult
        pipeline._vad.is_speech = MagicMock(return_value=True)
        pipeline._transcriber.transcribe = MagicMock(return_value=[
            TranscriptionResult(text=transcript_text, start=start, end=end, language="pt")
        ])

    @pytest.mark.asyncio
    async def test_default_speaker_label_is_speaker(self):
        """Without speaker_label arg, segments get 'Speaker'."""
        from backend.audio.pipeline import AudioPipeline

        pipeline = AudioPipeline(self._make_config())
        self._setup_pipeline(pipeline)

        received = []

        async def callback(seg):
            received.append(seg)

        pipeline.on_segment(callback)
        await pipeline.process_audio_chunk(make_pcm_bytes(duration_seconds=2.0))

        assert len(received) == 1
        assert received[0].speaker == "Speaker"

    @pytest.mark.asyncio
    async def test_speaker_label_me_forwarded(self):
        """speaker_label='Me' is forwarded to TranscriptSegment."""
        from backend.audio.pipeline import AudioPipeline

        pipeline = AudioPipeline(self._make_config())
        self._setup_pipeline(pipeline)

        received = []

        async def callback(seg):
            received.append(seg)

        pipeline.on_segment(callback)
        await pipeline.process_audio_chunk(make_pcm_bytes(duration_seconds=2.0), speaker_label="Me")

        assert len(received) == 1
        assert received[0].speaker == "Me"

    @pytest.mark.asyncio
    async def test_speaker_label_them_forwarded(self):
        """speaker_label='Them' is forwarded to TranscriptSegment."""
        from backend.audio.pipeline import AudioPipeline

        pipeline = AudioPipeline(self._make_config())
        self._setup_pipeline(pipeline)

        received = []

        async def callback(seg):
            received.append(seg)

        pipeline.on_segment(callback)
        await pipeline.process_audio_chunk(make_pcm_bytes(duration_seconds=2.0), speaker_label="Them")

        assert len(received) == 1
        assert received[0].speaker == "Them"

    @pytest.mark.asyncio
    async def test_no_diarizer_instantiated(self):
        """AudioPipeline no longer instantiates a SpeakerDiarizer."""
        from backend.audio.pipeline import AudioPipeline

        pipeline = AudioPipeline(self._make_config())
        assert not hasattr(pipeline, "_diarizer")

    @pytest.mark.asyncio
    async def test_multiple_segments_all_get_same_label(self):
        """All transcript segments in a buffer get the same speaker_label."""
        from backend.audio.pipeline import AudioPipeline
        from backend.audio.transcriber import TranscriptionResult

        pipeline = AudioPipeline(self._make_config())
        pipeline._vad.is_speech = MagicMock(return_value=True)
        pipeline._transcriber.transcribe = MagicMock(return_value=[
            TranscriptionResult(text="First sentence", start=0.0, end=1.0, language="pt"),
            TranscriptionResult(text="Second sentence", start=2.0, end=3.0, language="pt"),
        ])

        received = []

        async def callback(seg):
            received.append(seg)

        pipeline.on_segment(callback)
        await pipeline.process_audio_chunk(make_pcm_bytes(duration_seconds=4.0), speaker_label="Them")

        assert len(received) == 2
        assert received[0].speaker == "Them"
        assert received[1].speaker == "Them"

    @pytest.mark.asyncio
    async def test_set_diarization_enabled_not_present(self):
        """set_diarization_enabled() method has been removed."""
        from backend.audio.pipeline import AudioPipeline

        pipeline = AudioPipeline(self._make_config())
        assert not hasattr(pipeline, "set_diarization_enabled")
