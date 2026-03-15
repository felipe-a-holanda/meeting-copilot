"""Tests for POST /api/recording/start, POST /api/recording/stop,
GET /api/recording/status endpoints (Task 2.3).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.audio.recorder import DependencyStatus, RecordingStats
from backend.main import app
from backend.storage.session import SessionData, SessionInfo
from backend.ws.protocol import TranscriptSegment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dep_ok() -> DependencyStatus:
    return DependencyStatus(pactl_available=True, ffmpeg_available=True)


def _make_dep_bad(errors: list[str] | None = None) -> DependencyStatus:
    return DependencyStatus(
        pactl_available=False,
        ffmpeg_available=False,
        errors=errors or ["pactl not found", "ffmpeg not found"],
    )


def _make_session_info(session_id: str = "sess-001", title: str = "Test Meeting") -> SessionInfo:
    return SessionInfo(
        id=session_id,
        title=title,
        created_at=1700000000.0,
        updated_at=1700000000.0,
        segment_count=0,
    )


def _make_session_data(session_id: str = "sess-001", segments: list | None = None) -> SessionData:
    return SessionData(
        id=session_id,
        title="Test Meeting",
        created_at=1700000000.0,
        updated_at=1700000000.0,
        summary="",
        action_items=[],
        segments=segments or [],
    )


def _make_stop_stats(duration: float = 42.5, file_path: str | None = None) -> RecordingStats:
    return RecordingStats(
        duration_seconds=duration,
        chunks_processed=100,
        bytes_read=409600,
        is_recording=False,
        file_path=file_path,
        audio_files=[],
    )


def _make_mock_recorder(
    is_recording: bool = False,
    mic_source: str = "alsa_input.mic",
    monitor_source: str = "alsa_output.monitor",
) -> MagicMock:
    """Return a MagicMock that behaves like AudioRecorder."""
    recorder = MagicMock()
    recorder.is_recording = is_recording
    recorder._mic_source = mic_source
    recorder._monitor_source = monitor_source
    recorder.start = AsyncMock()
    recorder.stop = AsyncMock(return_value=_make_stop_stats())
    recorder.recording_stats = RecordingStats(
        duration_seconds=0.0, chunks_processed=0, bytes_read=0, is_recording=is_recording
    )
    return recorder


@pytest.fixture
def client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# POST /api/recording/start — success
# ---------------------------------------------------------------------------


class TestStartRecordingSuccess:
    @pytest.mark.asyncio
    async def test_returns_200_with_session_id(self, client):
        session = _make_session_info()
        mock_recorder = _make_mock_recorder(is_recording=False)

        with (
            patch("backend.main.audio_recorder", mock_recorder),
            patch("backend.main.AudioRecorder.check_dependencies", AsyncMock(return_value=_make_dep_ok())),
            patch("backend.main.session_store.create_session", AsyncMock(return_value=session)),
        ):
            async with client as c:
                resp = await c.post("/api/recording/start", json={})

        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"] == "sess-001"
        assert body["status"] == "recording"

    @pytest.mark.asyncio
    async def test_returns_mic_and_monitor_source(self, client):
        session = _make_session_info()
        mock_recorder = _make_mock_recorder(
            is_recording=False,
            mic_source="my_mic",
            monitor_source="my_monitor",
        )

        with (
            patch("backend.main.audio_recorder", mock_recorder),
            patch("backend.main.AudioRecorder.check_dependencies", AsyncMock(return_value=_make_dep_ok())),
            patch("backend.main.session_store.create_session", AsyncMock(return_value=session)),
        ):
            async with client as c:
                resp = await c.post("/api/recording/start", json={})

        body = resp.json()
        assert body["mic_source"] == "my_mic"
        assert body["monitor_source"] == "my_monitor"

    @pytest.mark.asyncio
    async def test_passes_title_to_create_session(self, client):
        session = _make_session_info(title="Standup")
        create_mock = AsyncMock(return_value=session)
        mock_recorder = _make_mock_recorder(is_recording=False)

        with (
            patch("backend.main.audio_recorder", mock_recorder),
            patch("backend.main.AudioRecorder.check_dependencies", AsyncMock(return_value=_make_dep_ok())),
            patch("backend.main.session_store.create_session", create_mock),
        ):
            async with client as c:
                resp = await c.post("/api/recording/start", json={"title": "Standup"})

        assert resp.status_code == 200
        create_mock.assert_awaited_once_with(title="Standup")

    @pytest.mark.asyncio
    async def test_passes_sources_and_volume_to_recorder(self, client):
        session = _make_session_info()
        mock_recorder = _make_mock_recorder(is_recording=False)

        with (
            patch("backend.main.audio_recorder", mock_recorder),
            patch("backend.main.AudioRecorder.check_dependencies", AsyncMock(return_value=_make_dep_ok())),
            patch("backend.main.session_store.create_session", AsyncMock(return_value=session)),
        ):
            async with client as c:
                resp = await c.post(
                    "/api/recording/start",
                    json={
                        "mic_source": "custom_mic",
                        "monitor_source": "custom_monitor",
                        "mic_volume": 3.0,
                    },
                )

        assert resp.status_code == 200
        call_kwargs = mock_recorder.start.call_args.kwargs
        assert call_kwargs["mic_source"] == "custom_mic"
        assert call_kwargs["monitor_source"] == "custom_monitor"
        assert call_kwargs["mic_volume"] == 3.0


# ---------------------------------------------------------------------------
# POST /api/recording/start — error paths
# ---------------------------------------------------------------------------


class TestStartRecordingErrors:
    @pytest.mark.asyncio
    async def test_409_when_already_recording(self, client):
        mock_recorder = _make_mock_recorder(is_recording=True)

        with patch("backend.main.audio_recorder", mock_recorder):
            async with client as c:
                resp = await c.post("/api/recording/start", json={})

        assert resp.status_code == 409
        assert "already" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_503_when_dependencies_missing(self, client):
        mock_recorder = _make_mock_recorder(is_recording=False)

        with (
            patch("backend.main.audio_recorder", mock_recorder),
            patch(
                "backend.main.AudioRecorder.check_dependencies",
                AsyncMock(return_value=_make_dep_bad(["pactl not found", "ffmpeg not found"])),
            ),
        ):
            async with client as c:
                resp = await c.post("/api/recording/start", json={})

        assert resp.status_code == 503
        detail = resp.json()["detail"]
        assert detail["error"] == "dependencies_missing"
        assert "pactl" in detail["message"]

    @pytest.mark.asyncio
    async def test_503_when_recorder_start_raises(self, client):
        session = _make_session_info()
        mock_recorder = _make_mock_recorder(is_recording=False)
        mock_recorder.start = AsyncMock(side_effect=RuntimeError("No microphone source available"))

        with (
            patch("backend.main.audio_recorder", mock_recorder),
            patch("backend.main.AudioRecorder.check_dependencies", AsyncMock(return_value=_make_dep_ok())),
            patch("backend.main.session_store.create_session", AsyncMock(return_value=session)),
        ):
            async with client as c:
                resp = await c.post("/api/recording/start", json={})

        assert resp.status_code == 503
        detail = resp.json()["detail"]
        assert detail["error"] == "recorder_start_failed"
        assert "microphone" in detail["message"]


# ---------------------------------------------------------------------------
# POST /api/recording/stop — success
# ---------------------------------------------------------------------------


class TestStopRecordingSuccess:
    @pytest.mark.asyncio
    async def test_returns_200_with_duration(self, client):
        stats = _make_stop_stats(duration=42.5)
        session_data = _make_session_data(segments=[])
        mock_recorder = _make_mock_recorder(is_recording=True)
        mock_recorder.stop = AsyncMock(return_value=stats)

        import backend.main as main_module
        original_session_id = main_module._active_session_id
        main_module._active_session_id = "sess-001"

        try:
            with (
                patch("backend.main.audio_recorder", mock_recorder),
                patch("backend.main.session_store.save_state", AsyncMock()),
                patch("backend.main.session_store.load_session", AsyncMock(return_value=session_data)),
            ):
                async with client as c:
                    resp = await c.post("/api/recording/stop")
        finally:
            main_module._active_session_id = original_session_id

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "stopped"
        assert body["duration_seconds"] == pytest.approx(42.5)

    @pytest.mark.asyncio
    async def test_returns_session_id_and_segments_count(self, client):
        seg = TranscriptSegment(
            speaker="Me", text="hello", timestamp_start=0.0, timestamp_end=1.0,
        )
        stats = _make_stop_stats()
        session_data = _make_session_data(segments=[seg, seg])
        mock_recorder = _make_mock_recorder(is_recording=True)
        mock_recorder.stop = AsyncMock(return_value=stats)

        import backend.main as main_module
        original_session_id = main_module._active_session_id
        main_module._active_session_id = "sess-001"

        try:
            with (
                patch("backend.main.audio_recorder", mock_recorder),
                patch("backend.main.session_store.save_state", AsyncMock()),
                patch("backend.main.session_store.load_session", AsyncMock(return_value=session_data)),
            ):
                async with client as c:
                    resp = await c.post("/api/recording/stop")
        finally:
            main_module._active_session_id = original_session_id

        body = resp.json()
        assert body["session_id"] == "sess-001"
        assert body["segments_count"] == 2

    @pytest.mark.asyncio
    async def test_returns_file_path_when_saving(self, client):
        stats = _make_stop_stats(file_path="/recordings/20260314/meeting_123")
        session_data = _make_session_data()
        mock_recorder = _make_mock_recorder(is_recording=True)
        mock_recorder.stop = AsyncMock(return_value=stats)

        import backend.main as main_module
        original_session_id = main_module._active_session_id
        main_module._active_session_id = "sess-001"

        try:
            with (
                patch("backend.main.audio_recorder", mock_recorder),
                patch("backend.main.session_store.save_state", AsyncMock()),
                patch("backend.main.session_store.load_session", AsyncMock(return_value=session_data)),
            ):
                async with client as c:
                    resp = await c.post("/api/recording/stop")
        finally:
            main_module._active_session_id = original_session_id

        body = resp.json()
        assert body["file_path"] == "/recordings/20260314/meeting_123"


# ---------------------------------------------------------------------------
# POST /api/recording/stop — error paths
# ---------------------------------------------------------------------------


class TestStopRecordingErrors:
    @pytest.mark.asyncio
    async def test_409_when_not_recording(self, client):
        mock_recorder = _make_mock_recorder(is_recording=False)

        with patch("backend.main.audio_recorder", mock_recorder):
            async with client as c:
                resp = await c.post("/api/recording/stop")

        assert resp.status_code == 409
        assert "not" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# GET /api/recording/status — idle
# ---------------------------------------------------------------------------


class TestRecordingStatusIdle:
    @pytest.mark.asyncio
    async def test_returns_idle_when_not_recording(self, client):
        mock_recorder = _make_mock_recorder(is_recording=False)

        with patch("backend.main.audio_recorder", mock_recorder):
            async with client as c:
                resp = await c.get("/api/recording/status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["is_recording"] is False
        assert body["status"] == "idle"
        assert body["duration_seconds"] == 0.0
        assert body["chunks_processed"] == 0
        assert body["segments_emitted"] == 0
        assert body["session_id"] is None


# ---------------------------------------------------------------------------
# GET /api/recording/status — active
# ---------------------------------------------------------------------------


class TestRecordingStatusActive:
    @pytest.mark.asyncio
    async def test_returns_recording_when_active(self, client):
        active_stats = RecordingStats(
            duration_seconds=15.0,
            chunks_processed=30,
            bytes_read=122880,
            is_recording=True,
        )
        session_data = _make_session_data(segments=[])
        mock_recorder = _make_mock_recorder(is_recording=True)
        mock_recorder.recording_stats = active_stats

        import backend.main as main_module
        original_session_id = main_module._active_session_id
        main_module._active_session_id = "sess-active"

        try:
            with (
                patch("backend.main.audio_recorder", mock_recorder),
                patch("backend.main.session_store.load_session", AsyncMock(return_value=session_data)),
            ):
                async with client as c:
                    resp = await c.get("/api/recording/status")
        finally:
            main_module._active_session_id = original_session_id

        assert resp.status_code == 200
        body = resp.json()
        assert body["is_recording"] is True
        assert body["status"] == "recording"
        assert body["session_id"] == "sess-active"
        assert body["duration_seconds"] == pytest.approx(15.0)
        assert body["chunks_processed"] == 30

    @pytest.mark.asyncio
    async def test_segments_emitted_count(self, client):
        segs = [
            TranscriptSegment(
                speaker="Me", text="word",
                timestamp_start=float(i), timestamp_end=float(i + 1),
            )
            for i in range(5)
        ]
        active_stats = RecordingStats(
            duration_seconds=5.0, chunks_processed=10, bytes_read=0, is_recording=True
        )
        session_data = _make_session_data(segments=segs)
        mock_recorder = _make_mock_recorder(is_recording=True)
        mock_recorder.recording_stats = active_stats

        import backend.main as main_module
        original_session_id = main_module._active_session_id
        main_module._active_session_id = "sess-active"

        try:
            with (
                patch("backend.main.audio_recorder", mock_recorder),
                patch("backend.main.session_store.load_session", AsyncMock(return_value=session_data)),
            ):
                async with client as c:
                    resp = await c.get("/api/recording/status")
        finally:
            main_module._active_session_id = original_session_id

        body = resp.json()
        assert body["segments_emitted"] == 5
