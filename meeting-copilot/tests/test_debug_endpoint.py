"""Tests for GET /debug endpoint — Task 4.3."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest
from httpx import ASGITransport, AsyncClient

import backend.main as main_module
from backend.audio.recorder import RecordingStats
from backend.main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_recorder(is_recording: bool = False, mic_source: str = "", monitor_source: str = "") -> MagicMock:
    """Return a MagicMock AudioRecorder with sensible defaults."""
    rec = MagicMock()
    type(rec).is_recording = PropertyMock(return_value=is_recording)
    rec._mic_source = mic_source
    rec._monitor_source = monitor_source
    rec._mic_process = None
    rec._monitor_process = None

    duration = 42.0 if is_recording else 0.0
    rec.recording_stats = RecordingStats(
        duration_seconds=duration,
        chunks_processed=100 if is_recording else 0,
        bytes_read=409600 if is_recording else 0,
        is_recording=is_recording,
    )
    return rec


# ---------------------------------------------------------------------------
# Tests — idle state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_debug_idle_has_required_keys():
    """GET /debug returns recording section when idle."""
    mock_recorder = _make_mock_recorder(is_recording=False)
    with patch.object(main_module, "audio_recorder", mock_recorder):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/debug")

    assert resp.status_code == 200
    data = resp.json()
    assert "pipeline" in data
    assert "settings" in data
    assert "recording" in data
    assert "connections" in data


@pytest.mark.asyncio
async def test_debug_idle_recording_section():
    """When idle, recording section shows is_recording=False and no sources/pids."""
    mock_recorder = _make_mock_recorder(is_recording=False)
    with patch.object(main_module, "audio_recorder", mock_recorder), \
         patch.object(main_module, "_active_session_id", None):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/debug")

    rec = resp.json()["recording"]
    assert rec["is_recording"] is False
    assert rec["active_session_id"] is None
    assert rec["recording_duration"] == 0.0
    assert rec["mic_source"] is None
    assert rec["monitor_source"] is None
    assert rec["ffmpeg_pids"] == {}


@pytest.mark.asyncio
async def test_debug_settings_has_audio_capture_mode():
    """Settings section must include audio_capture_mode (replaces removed enable_diarization)."""
    mock_recorder = _make_mock_recorder(is_recording=False)
    with patch.object(main_module, "audio_recorder", mock_recorder):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/debug")

    settings_data = resp.json()["settings"]
    assert "audio_capture_mode" in settings_data
    assert "whisper_model" in settings_data
    assert "language" in settings_data
    assert "ollama_url" in settings_data
    assert "ollama_model" in settings_data
    # enable_diarization must NOT appear (it was removed in Phase 1B)
    assert "enable_diarization" not in settings_data


# ---------------------------------------------------------------------------
# Tests — recording state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_debug_recording_section_when_active():
    """When recording, section shows is_recording=True with sources and duration."""
    mock_recorder = _make_mock_recorder(
        is_recording=True,
        mic_source="alsa_input.usb-001",
        monitor_source="alsa_output.pci.monitor",
    )
    session_id = "sess-debug-001"
    with patch.object(main_module, "audio_recorder", mock_recorder), \
         patch.object(main_module, "_active_session_id", session_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/debug")

    rec = resp.json()["recording"]
    assert rec["is_recording"] is True
    assert rec["active_session_id"] == session_id
    assert rec["recording_duration"] == 42.0
    assert rec["mic_source"] == "alsa_input.usb-001"
    assert rec["monitor_source"] == "alsa_output.pci.monitor"


@pytest.mark.asyncio
async def test_debug_recording_ffmpeg_pids_when_active():
    """When recording with two processes, ffmpeg_pids contains mic and monitor entries."""
    mock_recorder = _make_mock_recorder(is_recording=True, mic_source="mic0", monitor_source="mon0")

    # Simulate two live ffmpeg processes
    mic_proc = MagicMock()
    mic_proc.pid = 12345
    mon_proc = MagicMock()
    mon_proc.pid = 12346
    mock_recorder._mic_process = mic_proc
    mock_recorder._monitor_process = mon_proc

    with patch.object(main_module, "audio_recorder", mock_recorder), \
         patch.object(main_module, "_active_session_id", "sess-abc"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/debug")

    pids = resp.json()["recording"]["ffmpeg_pids"]
    assert pids["mic"] == 12345
    assert pids["monitor"] == 12346


@pytest.mark.asyncio
async def test_debug_recording_ffmpeg_pids_mic_only():
    """When recording mic-only (no monitor process), ffmpeg_pids['monitor'] is None."""
    mock_recorder = _make_mock_recorder(is_recording=True, mic_source="mic0", monitor_source="")

    mic_proc = MagicMock()
    mic_proc.pid = 99999
    mock_recorder._mic_process = mic_proc
    mock_recorder._monitor_process = None  # mic-only mode

    with patch.object(main_module, "audio_recorder", mock_recorder):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/debug")

    pids = resp.json()["recording"]["ffmpeg_pids"]
    assert pids["mic"] == 99999
    assert pids["monitor"] is None


@pytest.mark.asyncio
async def test_debug_recording_duration_nonzero_when_active():
    """recording_duration reflects live stats (nonzero while recording)."""
    mock_recorder = _make_mock_recorder(is_recording=True)
    # Override stats to have a specific duration
    mock_recorder.recording_stats = RecordingStats(
        duration_seconds=123.45,
        chunks_processed=50,
        bytes_read=204800,
        is_recording=True,
    )

    with patch.object(main_module, "audio_recorder", mock_recorder):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/debug")

    assert resp.json()["recording"]["recording_duration"] == pytest.approx(123.45)


# ---------------------------------------------------------------------------
# Tests — connections section still present
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_debug_connections_section_present():
    """connections section with audio/control counts must still be in the response."""
    mock_recorder = _make_mock_recorder(is_recording=False)
    with patch.object(main_module, "audio_recorder", mock_recorder):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/debug")

    conn = resp.json()["connections"]
    assert "audio" in conn
    assert "control" in conn
    assert isinstance(conn["audio"], int)
    assert isinstance(conn["control"], int)
