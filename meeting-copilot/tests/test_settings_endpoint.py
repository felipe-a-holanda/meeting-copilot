"""Tests for GET /settings and POST /settings endpoints — Task 4.4."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import patch

import backend.main as main_module
from backend.main import app


@pytest.fixture(autouse=True)
def reset_runtime_settings():
    """Clear _runtime_settings between tests."""
    original = main_module._runtime_settings.copy()
    main_module._runtime_settings.clear()
    yield
    main_module._runtime_settings.clear()
    main_module._runtime_settings.update(original)


@pytest.mark.asyncio
async def test_get_settings_returns_defaults():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["audio_capture_mode"] == "backend"
    assert data["mic_volume"] == 2.0
    assert data["save_recordings"] is True
    assert "whisper_model_size" in data
    assert "use_claude_api_fallback" in data


@pytest.mark.asyncio
async def test_get_settings_all_fields_present():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/settings")
    assert resp.status_code == 200
    keys = set(resp.json().keys())
    assert {"audio_capture_mode", "mic_volume", "save_recordings",
            "whisper_model_size", "use_claude_api_fallback"} <= keys


@pytest.mark.asyncio
async def test_post_settings_audio_capture_mode():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/settings", json={"audio_capture_mode": "browser"})
    assert resp.status_code == 200
    assert resp.json()["audio_capture_mode"] == "browser"


@pytest.mark.asyncio
async def test_post_settings_mic_volume():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/settings", json={"mic_volume": 3.5})
    assert resp.status_code == 200
    assert resp.json()["mic_volume"] == 3.5


@pytest.mark.asyncio
async def test_post_settings_save_recordings():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/settings", json={"save_recordings": False})
    assert resp.status_code == 200
    assert resp.json()["save_recordings"] is False


@pytest.mark.asyncio
async def test_post_settings_persisted_in_get():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/settings", json={
            "audio_capture_mode": "both",
            "mic_volume": 1.5,
            "save_recordings": False,
        })
        resp = await client.get("/settings")
    data = resp.json()
    assert data["audio_capture_mode"] == "both"
    assert data["mic_volume"] == 1.5
    assert data["save_recordings"] is False


@pytest.mark.asyncio
async def test_post_settings_whisper_model_size():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/settings", json={"whisper_model_size": "large"})
    assert resp.status_code == 200
    assert resp.json()["whisper_model_size"] == "large"


@pytest.mark.asyncio
async def test_post_settings_use_claude_api_fallback():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/settings", json={"use_claude_api_fallback": True})
    assert resp.status_code == 200
    assert resp.json()["use_claude_api_fallback"] is True


@pytest.mark.asyncio
async def test_post_settings_empty_body_returns_ok():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/settings", json={})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_post_settings_partial_update_preserves_others():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/settings", json={"mic_volume": 4.0})
        await client.post("/settings", json={"save_recordings": False})
        resp = await client.get("/settings")
    data = resp.json()
    assert data["mic_volume"] == 4.0
    assert data["save_recordings"] is False
