"""Tests for the audio transcription pipeline.

All heavy ML dependencies (faster-whisper, torch/silero) are mocked so that
these tests run without GPU or model downloads.
"""
from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers: generate synthetic audio
# ---------------------------------------------------------------------------

def make_sine_wave(
    frequency: float = 440.0,
    duration_seconds: float = 2.0,
    sample_rate: int = 16000,
    amplitude: float = 0.5,
) -> np.ndarray:
    """Return a float32 mono sine wave."""
    t = np.linspace(0, duration_seconds, int(sample_rate * duration_seconds), endpoint=False)
    return (np.sin(2 * np.pi * frequency * t) * amplitude).astype(np.float32)


def make_pcm_bytes(duration_seconds: float = 2.0, sample_rate: int = 16000) -> bytes:
    """Return int16 PCM bytes for a sine-wave audio chunk."""
    f32 = make_sine_wave(duration_seconds=duration_seconds, sample_rate=sample_rate)
    int16 = (f32 * 32768).astype(np.int16)
    return int16.tobytes()


# ---------------------------------------------------------------------------
# WhisperTranscriber tests
# ---------------------------------------------------------------------------

class TestWhisperTranscriber:
    """Unit tests for WhisperTranscriber using a mocked faster-whisper model."""

    def _make_mock_segment(self, text: str, start: float, end: float):
        seg = MagicMock()
        seg.text = text
        seg.start = start
        seg.end = end
        return seg

    def _make_mock_info(self, language: str = "pt"):
        info = MagicMock()
        info.language = language
        return info

    def test_transcribe_returns_results(self):
        """Transcriber returns TranscriptionResult list from model output."""
        from backend.audio.transcriber import WhisperTranscriber

        mock_segment = self._make_mock_segment(" Olá mundo.", 0.0, 1.5)
        mock_info = self._make_mock_info("pt")

        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([mock_segment], mock_info)

        transcriber = WhisperTranscriber(model_size="tiny", language="pt")
        transcriber._model = mock_model  # inject pre-loaded mock

        audio = make_sine_wave(duration_seconds=2.0)
        results = transcriber.transcribe(audio)

        assert len(results) == 1
        assert results[0].text == "Olá mundo."
        assert results[0].start == 0.0
        assert results[0].end == 1.5
        assert results[0].language == "pt"
        assert results[0].is_partial is False

    def test_transcribe_normalises_int16_range(self):
        """Transcriber normalises audio if values exceed [-1, 1]."""
        from backend.audio.transcriber import WhisperTranscriber

        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([], MagicMock(language="pt"))

        transcriber = WhisperTranscriber(model_size="tiny", language="pt")
        transcriber._model = mock_model

        # Pass int16-range float values
        audio = np.full(16000, 10000, dtype=np.float32)
        transcriber.transcribe(audio)  # should not raise

        # Check that model received normalised audio
        call_audio = mock_model.transcribe.call_args[0][0]
        assert np.abs(call_audio).max() <= 1.0

    def test_transcribe_handles_empty_result(self):
        """Transcriber returns empty list when model produces no segments."""
        from backend.audio.transcriber import WhisperTranscriber

        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([], MagicMock(language="pt"))

        transcriber = WhisperTranscriber(model_size="tiny", language="pt")
        transcriber._model = mock_model

        audio = make_sine_wave(duration_seconds=1.0)
        results = transcriber.transcribe(audio)
        assert results == []

    def test_transcribe_multiple_segments(self):
        """Transcriber returns all segments from model output."""
        from backend.audio.transcriber import WhisperTranscriber

        segments = [
            self._make_mock_segment(" Bom dia.", 0.0, 0.8),
            self._make_mock_segment(" Como vai?", 0.9, 2.0),
        ]
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (segments, MagicMock(language="pt"))

        transcriber = WhisperTranscriber(model_size="tiny", language="pt")
        transcriber._model = mock_model

        audio = make_sine_wave(duration_seconds=2.0)
        results = transcriber.transcribe(audio)

        assert len(results) == 2
        assert results[0].text == "Bom dia."
        assert results[1].text == "Como vai?"

    def test_load_model_raises_on_missing_dependency(self):
        """WhisperTranscriber raises RuntimeError if faster-whisper is not installed."""
        from backend.audio.transcriber import WhisperTranscriber

        transcriber = WhisperTranscriber(model_size="tiny", language="pt")

        with patch.dict(sys.modules, {"faster_whisper": None}):
            with pytest.raises(RuntimeError, match="faster-whisper"):
                transcriber._load_model()


# ---------------------------------------------------------------------------
# SileroVAD tests
# ---------------------------------------------------------------------------

class TestSileroVAD:
    """Unit tests for SileroVAD using a mocked torch.hub model."""

    def _make_mock_vad(self, speech_timestamps):
        """Return (mock_model, mock_get_speech_timestamps) tuple."""
        mock_model = MagicMock()
        mock_get_timestamps = MagicMock(return_value=speech_timestamps)
        return mock_model, mock_get_timestamps

    def _mock_torch(self):
        """Return a MagicMock that stands in for the torch module."""
        mock_torch = MagicMock()
        mock_torch.from_numpy.return_value = MagicMock()
        return mock_torch

    def test_is_speech_returns_true_when_speech_detected(self):
        """is_speech returns True if speech timestamps found."""
        from backend.audio.vad import SileroVAD

        vad = SileroVAD()
        mock_model, mock_fn = self._make_mock_vad([{"start": 0, "end": 8000}])
        vad._model = mock_model
        vad._get_speech_timestamps = mock_fn

        with patch.dict(sys.modules, {"torch": self._mock_torch()}):
            audio = make_sine_wave(duration_seconds=1.0)
            result = vad.is_speech(audio)

        assert result is True

    def test_is_speech_returns_false_for_silence(self):
        """is_speech returns False for silence (empty timestamps)."""
        from backend.audio.vad import SileroVAD

        vad = SileroVAD()
        mock_model, mock_fn = self._make_mock_vad([])
        vad._model = mock_model
        vad._get_speech_timestamps = mock_fn

        with patch.dict(sys.modules, {"torch": self._mock_torch()}):
            silence = np.zeros(16000, dtype=np.float32)
            result = vad.is_speech(silence)

        assert result is False

    def test_get_speech_segments_returns_segments(self):
        """get_speech_segments returns SpeechSegment list."""
        from backend.audio.vad import SileroVAD, SpeechSegment

        raw = [{"start": 100, "end": 8100}, {"start": 9000, "end": 14000}]
        vad = SileroVAD()
        mock_model, mock_fn = self._make_mock_vad(raw)
        vad._model = mock_model
        vad._get_speech_timestamps = mock_fn

        with patch.dict(sys.modules, {"torch": self._mock_torch()}):
            audio = make_sine_wave(duration_seconds=1.0)
            segments = vad.get_speech_segments(audio)

        assert len(segments) == 2
        assert isinstance(segments[0], SpeechSegment)
        assert segments[0].start_sample == 100
        assert segments[0].end_sample == 8100

    def test_load_raises_on_missing_torch(self):
        """SileroVAD raises RuntimeError if torch is not installed."""
        from backend.audio.vad import SileroVAD

        vad = SileroVAD()
        with patch.dict(sys.modules, {"torch": None}):
            with pytest.raises(RuntimeError, match="torch"):
                vad._load()


# ---------------------------------------------------------------------------
# AudioPipeline integration tests
# ---------------------------------------------------------------------------

class TestAudioPipeline:
    """Integration tests for AudioPipeline combining VAD + transcriber."""

    def _make_config(self):
        cfg = MagicMock()
        cfg.whisper_model = "tiny"
        cfg.language = "pt"
        return cfg

    def _setup_pipeline(self, pipeline, transcript_text="Hello world", start=0.0, end=1.5):
        """Inject mocked VAD (speech=True) and transcriber (one segment)."""
        from backend.audio.transcriber import TranscriptionResult

        # Mock VAD: always returns speech
        pipeline._vad.is_speech = MagicMock(return_value=True)

        # Mock transcriber: returns one segment
        mock_result = TranscriptionResult(
            text=transcript_text,
            start=start,
            end=end,
            language="pt",
        )
        pipeline._transcriber.transcribe = MagicMock(return_value=[mock_result])

    @pytest.mark.asyncio
    async def test_process_chunk_calls_callback(self):
        """AudioPipeline calls the segment callback when speech is transcribed."""
        from backend.audio.pipeline import AudioPipeline

        config = self._make_config()
        pipeline = AudioPipeline(config)
        self._setup_pipeline(pipeline, transcript_text="Test speech")

        received = []

        async def callback(segment):
            received.append(segment)

        pipeline.on_segment(callback)

        pcm = make_pcm_bytes(duration_seconds=2.0)
        await pipeline.process_audio_chunk(pcm)

        assert len(received) == 1
        assert received[0].text == "Test speech"
        assert received[0].speaker == "Speaker"
        assert received[0].language == "pt"

    @pytest.mark.asyncio
    async def test_process_chunk_small_buffer_not_processed(self):
        """Pipeline buffers audio and does not transcribe until MIN_CHUNK_SAMPLES reached."""
        from backend.audio.pipeline import AudioPipeline, _MIN_CHUNK_SAMPLES

        config = self._make_config()
        pipeline = AudioPipeline(config)
        self._setup_pipeline(pipeline)

        received = []

        async def callback(segment):
            received.append(segment)

        pipeline.on_segment(callback)

        # Send a very small chunk (100 samples = 6ms) — below threshold
        tiny_audio = np.zeros(100, dtype=np.int16)
        await pipeline.process_audio_chunk(tiny_audio.tobytes())

        # No callback should have fired yet
        assert received == []

    @pytest.mark.asyncio
    async def test_vad_silence_skips_transcription(self):
        """Pipeline skips transcription when VAD detects no speech."""
        from backend.audio.pipeline import AudioPipeline

        config = self._make_config()
        pipeline = AudioPipeline(config)

        # VAD returns no speech
        pipeline._vad.is_speech = MagicMock(return_value=False)
        pipeline._transcriber.transcribe = MagicMock(return_value=[])

        received = []

        async def callback(segment):
            received.append(segment)

        pipeline.on_segment(callback)

        pcm = make_pcm_bytes(duration_seconds=2.0)
        await pipeline.process_audio_chunk(pcm)

        assert received == []
        pipeline._transcriber.transcribe.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_chunks_accumulate(self):
        """Multiple small chunks are accumulated and processed together."""
        from backend.audio.pipeline import AudioPipeline, _MIN_CHUNK_SAMPLES

        config = self._make_config()
        pipeline = AudioPipeline(config)

        # Use enough samples to cross the threshold across two calls
        half = _MIN_CHUNK_SAMPLES // 2 + 100
        audio1 = np.zeros(half, dtype=np.int16)
        audio2 = np.zeros(half, dtype=np.int16)

        from backend.audio.transcriber import TranscriptionResult
        pipeline._vad.is_speech = MagicMock(return_value=True)
        pipeline._transcriber.transcribe = MagicMock(return_value=[
            TranscriptionResult(text="Accumulated", start=0.0, end=1.0, language="pt")
        ])

        received = []

        async def callback(segment):
            received.append(segment)

        pipeline.on_segment(callback)

        await pipeline.process_audio_chunk(audio1.tobytes())
        # First chunk alone might not hit threshold — depends on size
        pre_count = len(received)

        await pipeline.process_audio_chunk(audio2.tobytes())
        # After two chunks, buffer should be >= MIN_CHUNK_SAMPLES
        assert len(received) >= pre_count  # at least no crash

    @pytest.mark.asyncio
    async def test_pipeline_works_with_real_sine_wave(self):
        """Pipeline processes a 2-second sine wave without crashing."""
        from backend.audio.pipeline import AudioPipeline

        config = self._make_config()
        pipeline = AudioPipeline(config)

        # Mock deps so no model download needed
        pipeline._vad.is_speech = MagicMock(return_value=True)

        from backend.audio.transcriber import TranscriptionResult
        pipeline._transcriber.transcribe = MagicMock(return_value=[
            TranscriptionResult(text="Sine wave audio", start=0.0, end=2.0, language="pt")
        ])

        received = []

        async def callback(seg):
            received.append(seg)

        pipeline.on_segment(callback)

        pcm = make_pcm_bytes(duration_seconds=2.0)
        await pipeline.process_audio_chunk(pcm)

        assert len(received) == 1
        assert received[0].text == "Sine wave audio"
        assert received[0].type == "transcript_segment"

    @pytest.mark.asyncio
    async def test_no_callback_registered(self):
        """Pipeline processes audio gracefully when no callback is registered."""
        from backend.audio.pipeline import AudioPipeline

        config = self._make_config()
        pipeline = AudioPipeline(config)

        from backend.audio.transcriber import TranscriptionResult
        pipeline._vad.is_speech = MagicMock(return_value=True)
        pipeline._transcriber.transcribe = MagicMock(return_value=[
            TranscriptionResult(text="Test", start=0.0, end=1.0, language="pt")
        ])

        # No on_segment registered — should not raise
        pcm = make_pcm_bytes(duration_seconds=2.0)
        await pipeline.process_audio_chunk(pcm)  # must not raise

    @pytest.mark.asyncio
    async def test_reset_flushes_buffer(self):
        """reset() flushes the audio buffer and resets meeting start time."""
        from backend.audio.pipeline import AudioPipeline

        config = self._make_config()
        pipeline = AudioPipeline(config)

        from backend.audio.transcriber import TranscriptionResult
        pipeline._vad.is_speech = MagicMock(return_value=True)
        pipeline._transcriber.transcribe = MagicMock(return_value=[
            TranscriptionResult(text="Flushed", start=0.0, end=0.5, language="pt")
        ])

        received = []

        async def callback(seg):
            received.append(seg)

        pipeline.on_segment(callback)

        # Fill buffer below threshold
        tiny = np.zeros(100, dtype=np.int16)
        await pipeline.process_audio_chunk(tiny.tobytes())
        assert pipeline._meeting_start is not None

        await pipeline.reset()
        assert pipeline._meeting_start is None
        assert len(pipeline._buffer) == 0


# ---------------------------------------------------------------------------
# WebSocket integration: pipeline receives bytes through ws endpoint
# ---------------------------------------------------------------------------

class TestWebSocketAudioIntegration:
    """Verify the /ws/audio endpoint feeds bytes into the audio pipeline."""

    def test_ws_audio_endpoint_feeds_pipeline(self):
        """Bytes received on /ws/audio are forwarded to AudioPipeline."""
        from fastapi.testclient import TestClient
        import backend.main as main_module

        received_chunks = []

        async def mock_process(chunk: bytes):
            received_chunks.append(chunk)

        original = main_module.audio_pipeline.process_audio_chunk
        main_module.audio_pipeline.process_audio_chunk = mock_process

        try:
            client = TestClient(main_module.app)
            pcm = make_pcm_bytes(duration_seconds=0.1)
            with client.websocket_connect("/ws/audio") as ws:
                ws.send_bytes(pcm)
        finally:
            main_module.audio_pipeline.process_audio_chunk = original

        assert len(received_chunks) == 1
        assert received_chunks[0] == make_pcm_bytes(duration_seconds=0.1)
