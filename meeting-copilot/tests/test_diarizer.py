"""Tests for AudioPipeline speaker_label integration.

SpeakerDiarizer and pyannote.audio have been removed.
Speaker attribution is now done via stream-based labels ("Me" / "Them").
"""
from __future__ import annotations

from unittest.mock import MagicMock

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
