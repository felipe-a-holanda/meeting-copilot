"""Tests for GET /api/audio/devices endpoint (Task 2.2)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.audio.recorder import AudioDevice, DeviceDefaults, DeviceList, DependencyStatus
from backend.main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_device_list() -> DeviceList:
    return DeviceList(
        sources=[
            AudioDevice(name="alsa_input.pci.analog-stereo", description="alsa_input.pci.analog-stereo"),
            AudioDevice(name="alsa_output.pci.analog-stereo.monitor", description="alsa_output.pci.analog-stereo.monitor"),
        ],
        sinks=[
            AudioDevice(name="alsa_output.pci.analog-stereo", description="alsa_output.pci.analog-stereo"),
        ],
        defaults=DeviceDefaults(
            source="alsa_input.pci.analog-stereo",
            sink="alsa_output.pci.analog-stereo",
            monitor="alsa_output.pci.analog-stereo.monitor",
        ),
    )


@pytest.fixture
def client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


class TestGetAudioDevicesSuccess:
    @pytest.mark.asyncio
    async def test_returns_200_with_device_lists(self, client):
        dep_ok = DependencyStatus(pactl_available=True, ffmpeg_available=True)
        device_list = _make_device_list()

        with (
            patch("backend.main.AudioRecorder.check_dependencies", AsyncMock(return_value=dep_ok)),
            patch("backend.main.audio_recorder.list_devices", AsyncMock(return_value=device_list)),
        ):
            async with client as c:
                resp = await c.get("/api/audio/devices")

        assert resp.status_code == 200
        body = resp.json()
        assert "sources" in body
        assert "sinks" in body
        assert "defaults" in body

    @pytest.mark.asyncio
    async def test_sources_shape(self, client):
        dep_ok = DependencyStatus(pactl_available=True, ffmpeg_available=True)
        device_list = _make_device_list()

        with (
            patch("backend.main.AudioRecorder.check_dependencies", AsyncMock(return_value=dep_ok)),
            patch("backend.main.audio_recorder.list_devices", AsyncMock(return_value=device_list)),
        ):
            async with client as c:
                resp = await c.get("/api/audio/devices")

        sources = resp.json()["sources"]
        assert len(sources) == 2
        assert sources[0]["name"] == "alsa_input.pci.analog-stereo"
        assert sources[0]["description"] == "alsa_input.pci.analog-stereo"

    @pytest.mark.asyncio
    async def test_sinks_shape(self, client):
        dep_ok = DependencyStatus(pactl_available=True, ffmpeg_available=True)
        device_list = _make_device_list()

        with (
            patch("backend.main.AudioRecorder.check_dependencies", AsyncMock(return_value=dep_ok)),
            patch("backend.main.audio_recorder.list_devices", AsyncMock(return_value=device_list)),
        ):
            async with client as c:
                resp = await c.get("/api/audio/devices")

        sinks = resp.json()["sinks"]
        assert len(sinks) == 1
        assert sinks[0]["name"] == "alsa_output.pci.analog-stereo"

    @pytest.mark.asyncio
    async def test_defaults_shape(self, client):
        dep_ok = DependencyStatus(pactl_available=True, ffmpeg_available=True)
        device_list = _make_device_list()

        with (
            patch("backend.main.AudioRecorder.check_dependencies", AsyncMock(return_value=dep_ok)),
            patch("backend.main.audio_recorder.list_devices", AsyncMock(return_value=device_list)),
        ):
            async with client as c:
                resp = await c.get("/api/audio/devices")

        defaults = resp.json()["defaults"]
        assert defaults["source"] == "alsa_input.pci.analog-stereo"
        assert defaults["sink"] == "alsa_output.pci.analog-stereo"
        assert defaults["monitor"] == "alsa_output.pci.analog-stereo.monitor"

    @pytest.mark.asyncio
    async def test_empty_device_lists(self, client):
        dep_ok = DependencyStatus(pactl_available=True, ffmpeg_available=True)
        empty_list = DeviceList(defaults=DeviceDefaults())

        with (
            patch("backend.main.AudioRecorder.check_dependencies", AsyncMock(return_value=dep_ok)),
            patch("backend.main.audio_recorder.list_devices", AsyncMock(return_value=empty_list)),
        ):
            async with client as c:
                resp = await c.get("/api/audio/devices")

        assert resp.status_code == 200
        body = resp.json()
        assert body["sources"] == []
        assert body["sinks"] == []


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestGetAudioDevicesErrors:
    @pytest.mark.asyncio
    async def test_503_when_pactl_missing(self, client):
        dep_bad = DependencyStatus(
            pactl_available=False,
            ffmpeg_available=True,
            errors=["pactl not found. Install pulseaudio-utils: sudo apt install pulseaudio-utils"],
        )

        with patch("backend.main.AudioRecorder.check_dependencies", AsyncMock(return_value=dep_bad)):
            async with client as c:
                resp = await c.get("/api/audio/devices")

        assert resp.status_code == 503
        detail = resp.json()["detail"]
        assert detail["error"] == "pactl not available"
        assert "pactl" in detail["message"]

    @pytest.mark.asyncio
    async def test_503_includes_install_hint(self, client):
        dep_bad = DependencyStatus(
            pactl_available=False,
            ffmpeg_available=True,
            errors=["pactl not found. Install pulseaudio-utils: sudo apt install pulseaudio-utils"],
        )

        with patch("backend.main.AudioRecorder.check_dependencies", AsyncMock(return_value=dep_bad)):
            async with client as c:
                resp = await c.get("/api/audio/devices")

        detail = resp.json()["detail"]
        assert "pulseaudio-utils" in detail["message"]

    @pytest.mark.asyncio
    async def test_503_when_list_devices_raises(self, client):
        dep_ok = DependencyStatus(pactl_available=True, ffmpeg_available=True)

        with (
            patch("backend.main.AudioRecorder.check_dependencies", AsyncMock(return_value=dep_ok)),
            patch(
                "backend.main.audio_recorder.list_devices",
                AsyncMock(side_effect=RuntimeError("pactl list sources short failed: some error")),
            ),
        ):
            async with client as c:
                resp = await c.get("/api/audio/devices")

        assert resp.status_code == 503
        detail = resp.json()["detail"]
        assert detail["error"] == "device_discovery_failed"
        assert "some error" in detail["message"]

    @pytest.mark.asyncio
    async def test_503_no_errors_list_still_gives_fallback_message(self, client):
        dep_bad = DependencyStatus(pactl_available=False, ffmpeg_available=True, errors=[])

        with patch("backend.main.AudioRecorder.check_dependencies", AsyncMock(return_value=dep_bad)):
            async with client as c:
                resp = await c.get("/api/audio/devices")

        assert resp.status_code == 503
        detail = resp.json()["detail"]
        assert "pactl" in detail["message"]
