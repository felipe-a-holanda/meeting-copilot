"""End-to-end integration tests for the recording pipeline (Task 4.1).

Tests the full flow:
  POST /api/recording/start (REST)
  → ffmpeg mock emits PCM bytes
  → AudioRecorder reader loop forwards chunks to AudioPipeline
  → AudioPipeline (VAD + Whisper mocked) emits TranscriptSegments
  → _segment_handler saves to session store
  POST /api/recording/stop (REST)
  → session contains expected segments

No real ffmpeg, pactl, or Whisper is used.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient

from backend.audio.recorder import DependencyStatus
from backend.audio.transcriber import TranscriptionResult
from backend.main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pcm_bytes(duration_seconds: float = 1.2, sample_rate: int = 16000) -> bytes:
    """Return valid int16 PCM bytes (440 Hz sine wave) exceeding MIN_CHUNK_SAMPLES."""
    t = np.linspace(0, duration_seconds, int(sample_rate * duration_seconds), endpoint=False)
    f32 = (np.sin(2 * np.pi * 440 * t) * 0.5).astype(np.float32)
    return (f32 * 32768).astype(np.int16).tobytes()


def _make_stdout_mock(chunks: list[bytes]):
    """Return an AsyncMock for process.stdout that yields chunks then EOF."""
    side_effects = list(chunks) + [b""]
    mock = AsyncMock()
    mock.read = AsyncMock(side_effect=side_effects)
    return mock


def _make_process_mock(stdout_chunks: list[bytes] | None = None):
    """Return a MagicMock that mimics an asyncio subprocess."""
    proc = MagicMock()
    proc.stdout = _make_stdout_mock(stdout_chunks or [])
    proc.stderr = AsyncMock()
    proc.returncode = 0
    proc.wait = AsyncMock(return_value=0)
    proc.send_signal = MagicMock()
    proc.kill = MagicMock()
    return proc


def _make_dep_ok() -> DependencyStatus:
    return DependencyStatus(pactl_available=True, ffmpeg_available=True)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
async def _init_db_and_reset_state():
    """Ensure DB tables exist and recorder/pipeline state is clean around each test."""
    import backend.main as main_module

    # Guarantee tables exist before tests that use real SQLite
    await main_module.session_store.init_db()

    yield

    # Reset module-level recorder state so tests don't bleed into each other
    recorder = main_module.audio_recorder
    recorder._is_recording = False
    recorder._stopping = False
    recorder._active_stream_count = 0
    recorder._mic_process = None
    recorder._monitor_process = None
    for task in (recorder._mic_reader_task, recorder._monitor_reader_task):
        if task is not None and not task.done():
            task.cancel()
    recorder._mic_reader_task = None
    recorder._monitor_reader_task = None
    recorder._start_time = None
    recorder._chunks_processed = 0
    recorder._bytes_read = 0
    main_module._active_session_id = None

    # Reset pipeline rolling buffer
    main_module.audio_pipeline._buffer = np.array([], dtype=np.int16)
    main_module.audio_pipeline._buffer_start_time = 0.0
    main_module.audio_pipeline._meeting_start = None


@pytest.fixture
def client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# Helpers used inside tests
# ---------------------------------------------------------------------------


async def _wait_for_reader_tasks() -> None:
    """Block until the module-level recorder's reader tasks finish (or 5 s timeout).

    Sets _stopping=True before waiting so that reader-loop EOF detection treats the
    EOF as a controlled end (all chunks delivered) rather than an unexpected crash.
    In production, ffmpeg keeps running until SIGINT; in tests the mock emits all
    data then EOF immediately.
    """
    import backend.main as main_module

    recorder = main_module.audio_recorder
    recorder._stopping = True  # suppress crash detection for expected test EOF
    if recorder._mic_reader_task:
        await asyncio.wait_for(recorder._mic_reader_task, timeout=5.0)
    if recorder._monitor_reader_task:
        await asyncio.wait_for(recorder._monitor_reader_task, timeout=5.0)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEndToEndRecording:
    """Full E2E flow: start → PCM chunks → segments → stop → session."""

    # ------------------------------------------------------------------
    # Chunk forwarding
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_chunks_flow_through_pipeline(self, client):
        """PCM bytes from mock ffmpeg reach process_audio_chunk with speaker_label='Me'."""
        import backend.main as main_module

        pcm = _make_pcm_bytes()  # single large chunk (> MIN_CHUNK_SAMPLES)
        mic_mock = _make_process_mock([pcm])
        monitor_mock = _make_process_mock([])

        captured: list[tuple[bytes, str]] = []

        async def spy(chunk: bytes, speaker_label: str = "Speaker") -> None:
            captured.append((chunk, speaker_label))

        with (
            patch("asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]),
            patch("backend.main.AudioRecorder.check_dependencies", AsyncMock(return_value=_make_dep_ok())),
            patch.object(main_module.audio_pipeline, "process_audio_chunk", spy),
            patch.object(main_module.audio_pipeline, "reset", AsyncMock()),
        ):
            async with client as c:
                resp = await c.post(
                    "/api/recording/start",
                    json={"mic_source": "test_mic", "monitor_source": "test_monitor"},
                )
                assert resp.status_code == 200

                await _wait_for_reader_tasks()

                stop_resp = await c.post("/api/recording/stop")
                assert stop_resp.status_code == 200

        assert len(captured) == 1
        assert captured[0][0] == pcm
        assert captured[0][1] == "Me"

    @pytest.mark.asyncio
    async def test_monitor_chunks_tagged_them(self, client):
        """Chunks from the monitor stream reach the pipeline with speaker_label='Them'."""
        import backend.main as main_module

        pcm = _make_pcm_bytes()
        mic_mock = _make_process_mock([])
        monitor_mock = _make_process_mock([pcm])

        captured: list[tuple[bytes, str]] = []

        async def spy(chunk: bytes, speaker_label: str = "Speaker") -> None:
            captured.append((chunk, speaker_label))

        with (
            patch("asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]),
            patch("backend.main.AudioRecorder.check_dependencies", AsyncMock(return_value=_make_dep_ok())),
            patch.object(main_module.audio_pipeline, "process_audio_chunk", spy),
            patch.object(main_module.audio_pipeline, "reset", AsyncMock()),
        ):
            async with client as c:
                await c.post(
                    "/api/recording/start",
                    json={"mic_source": "test_mic", "monitor_source": "test_monitor"},
                )
                await _wait_for_reader_tasks()
                await c.post("/api/recording/stop")

        assert len(captured) == 1
        assert captured[0][1] == "Them"

    # ------------------------------------------------------------------
    # Session persistence
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_segments_stored_in_session(self, client):
        """Full pipeline flow: PCM → mocked Whisper → segment persisted in SQLite."""
        import backend.main as main_module

        pcm = _make_pcm_bytes()
        mic_mock = _make_process_mock([pcm])
        monitor_mock = _make_process_mock([])

        canned = [TranscriptionResult(text="Hello from mic", start=0.0, end=1.5, language="pt")]

        with (
            patch("asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]),
            patch("backend.main.AudioRecorder.check_dependencies", AsyncMock(return_value=_make_dep_ok())),
            patch.object(main_module.audio_pipeline._vad, "is_speech", MagicMock(return_value=True)),
            patch.object(main_module.audio_pipeline._transcriber, "transcribe", MagicMock(return_value=canned)),
            patch.object(main_module.context_manager, "on_new_segment", AsyncMock()),
        ):
            async with client as c:
                start_resp = await c.post(
                    "/api/recording/start",
                    json={"mic_source": "test_mic", "monitor_source": "test_monitor"},
                )
                assert start_resp.status_code == 200
                session_id = start_resp.json()["session_id"]

                await _wait_for_reader_tasks()

                stop_resp = await c.post("/api/recording/stop")
                assert stop_resp.status_code == 200

        session_data = await main_module.session_store.load_session(session_id)
        assert session_data is not None
        assert len(session_data.segments) >= 1
        assert session_data.segments[0].speaker == "Me"
        assert session_data.segments[0].text == "Hello from mic"

    @pytest.mark.asyncio
    async def test_stop_returns_correct_segment_count(self, client):
        """stop response segments_count matches the number of persisted segments."""
        import backend.main as main_module

        pcm = _make_pcm_bytes()
        mic_mock = _make_process_mock([pcm])
        monitor_mock = _make_process_mock([])

        # One transcription call on the single chunk → 2 result segments
        canned = [
            TranscriptionResult(text="First", start=0.0, end=0.5, language="pt"),
            TranscriptionResult(text="Second", start=0.5, end=1.0, language="pt"),
        ]

        with (
            patch("asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]),
            patch("backend.main.AudioRecorder.check_dependencies", AsyncMock(return_value=_make_dep_ok())),
            patch.object(main_module.audio_pipeline._vad, "is_speech", MagicMock(return_value=True)),
            patch.object(main_module.audio_pipeline._transcriber, "transcribe", MagicMock(return_value=canned)),
            patch.object(main_module.context_manager, "on_new_segment", AsyncMock()),
        ):
            async with client as c:
                await c.post(
                    "/api/recording/start",
                    json={"mic_source": "test_mic", "monitor_source": "test_monitor"},
                )
                await _wait_for_reader_tasks()
                stop_resp = await c.post("/api/recording/stop")

        assert stop_resp.status_code == 200
        body = stop_resp.json()
        assert body["status"] == "stopped"
        assert body["segments_count"] == 2

    # ------------------------------------------------------------------
    # Speaker labels — both streams active
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_mic_and_monitor_produce_different_speaker_labels(self, client):
        """Mic stream emits 'Me' segments; monitor stream emits 'Them' segments."""
        import backend.main as main_module

        pcm = _make_pcm_bytes()
        mic_mock = _make_process_mock([pcm])
        monitor_mock = _make_process_mock([pcm])

        canned = [TranscriptionResult(text="Audio", start=0.0, end=1.0, language="pt")]
        collected: list = []

        async def capture(seg) -> None:
            collected.append(seg)

        with (
            patch("asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]),
            patch("backend.main.AudioRecorder.check_dependencies", AsyncMock(return_value=_make_dep_ok())),
            patch.object(main_module.audio_pipeline._vad, "is_speech", MagicMock(return_value=True)),
            patch.object(main_module.audio_pipeline._transcriber, "transcribe", MagicMock(return_value=canned)),
            patch.object(main_module.context_manager, "on_new_segment", capture),
        ):
            async with client as c:
                await c.post(
                    "/api/recording/start",
                    json={"mic_source": "test_mic", "monitor_source": "test_monitor"},
                )
                await _wait_for_reader_tasks()
                await c.post("/api/recording/stop")

        speakers = {seg.speaker for seg in collected}
        assert "Me" in speakers
        assert "Them" in speakers

    # ------------------------------------------------------------------
    # Lifecycle and state
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_start_stop_clears_recording_state(self, client):
        """After stop, status endpoint returns idle and _active_session_id is None."""
        import backend.main as main_module

        mic_mock = _make_process_mock([])
        monitor_mock = _make_process_mock([])

        with (
            patch("asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]),
            patch("backend.main.AudioRecorder.check_dependencies", AsyncMock(return_value=_make_dep_ok())),
            patch.object(main_module.audio_pipeline, "process_audio_chunk", AsyncMock()),
            patch.object(main_module.audio_pipeline, "reset", AsyncMock()),
            patch.object(main_module.context_manager, "on_new_segment", AsyncMock()),
        ):
            async with client as c:
                await c.post(
                    "/api/recording/start",
                    json={"mic_source": "test_mic", "monitor_source": "test_monitor"},
                )
                await _wait_for_reader_tasks()
                await c.post("/api/recording/stop")

                status_resp = await c.get("/api/recording/status")
                status_body = status_resp.json()

        assert status_body["is_recording"] is False
        assert status_body["status"] == "idle"
        assert main_module._active_session_id is None

    @pytest.mark.asyncio
    async def test_session_title_set_from_start_request(self, client):
        """Session is created with the title passed in the start request."""
        import backend.main as main_module

        mic_mock = _make_process_mock([])
        monitor_mock = _make_process_mock([])

        with (
            patch("asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]),
            patch("backend.main.AudioRecorder.check_dependencies", AsyncMock(return_value=_make_dep_ok())),
            patch.object(main_module.audio_pipeline, "process_audio_chunk", AsyncMock()),
            patch.object(main_module.audio_pipeline, "reset", AsyncMock()),
            patch.object(main_module.context_manager, "on_new_segment", AsyncMock()),
        ):
            async with client as c:
                start_resp = await c.post(
                    "/api/recording/start",
                    json={
                        "title": "Sprint Planning",
                        "mic_source": "test_mic",
                        "monitor_source": "test_monitor",
                    },
                )
                assert start_resp.status_code == 200
                session_id = start_resp.json()["session_id"]

                await _wait_for_reader_tasks()
                await c.post("/api/recording/stop")

        session_data = await main_module.session_store.load_session(session_id)
        assert session_data is not None
        assert session_data.title == "Sprint Planning"

    @pytest.mark.asyncio
    async def test_duplicate_start_returns_409(self, client):
        """A second start request while recording is active returns 409 Conflict."""
        import backend.main as main_module

        mic_mock = _make_process_mock([])
        monitor_mock = _make_process_mock([])

        with (
            patch("asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]),
            patch("backend.main.AudioRecorder.check_dependencies", AsyncMock(return_value=_make_dep_ok())),
            patch.object(main_module.audio_pipeline, "process_audio_chunk", AsyncMock()),
            patch.object(main_module.audio_pipeline, "reset", AsyncMock()),
            patch.object(main_module.context_manager, "on_new_segment", AsyncMock()),
        ):
            async with client as c:
                first = await c.post(
                    "/api/recording/start",
                    json={"mic_source": "test_mic", "monitor_source": "test_monitor"},
                )
                assert first.status_code == 200

                second = await c.post(
                    "/api/recording/start",
                    json={"mic_source": "test_mic", "monitor_source": "test_monitor"},
                )
                assert second.status_code == 409

                await _wait_for_reader_tasks()
                await c.post("/api/recording/stop")
