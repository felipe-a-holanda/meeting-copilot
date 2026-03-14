"""Tests for GET /sessions/{id}/export endpoint."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.storage.session import SessionData
from backend.ws.protocol import ActionItem, TranscriptSegment


def _make_session(
    title: str = "Sprint Review",
    summary: str = "Team discussed progress.",
    segments: list | None = None,
    action_items: list | None = None,
) -> SessionData:
    return SessionData(
        id="abc123",
        title=title,
        created_at=1710000000.0,  # 2024-03-09 in UTC
        updated_at=1710003600.0,
        summary=summary,
        action_items=action_items or [],
        segments=segments or [],
    )


def _make_segment(speaker: str, text: str, start: float = 0.0, end: float = 1.0) -> TranscriptSegment:
    return TranscriptSegment(speaker=speaker, text=text, timestamp_start=start, timestamp_end=end)


def _make_action_item(description: str, assignee: str | None = None, status: str = "new") -> ActionItem:
    return ActionItem(
        id="item-1",
        description=description,
        assignee=assignee,
        source_timestamp=10.0,
        status=status,
    )


@pytest.fixture
def client():
    """Create TestClient with mocked startup event (no real DB)."""
    with patch("backend.main.session_store.init_db", new_callable=AsyncMock):
        from backend.main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


class TestExportMarkdown:
    def test_default_format_is_markdown(self, client):
        session = _make_session()
        with patch("backend.main.session_store.load_session", new_callable=AsyncMock, return_value=session):
            resp = client.get("/sessions/abc123/export")
        assert resp.status_code == 200
        assert "text/markdown" in resp.headers["content-type"]

    def test_explicit_markdown_format(self, client):
        session = _make_session()
        with patch("backend.main.session_store.load_session", new_callable=AsyncMock, return_value=session):
            resp = client.get("/sessions/abc123/export?format=markdown")
        assert resp.status_code == 200

    def test_markdown_contains_title(self, client):
        session = _make_session(title="Q1 Planning")
        with patch("backend.main.session_store.load_session", new_callable=AsyncMock, return_value=session):
            body = client.get("/sessions/abc123/export").text
        assert "# Q1 Planning" in body

    def test_markdown_contains_summary(self, client):
        session = _make_session(summary="We agreed on the roadmap.")
        with patch("backend.main.session_store.load_session", new_callable=AsyncMock, return_value=session):
            body = client.get("/sessions/abc123/export").text
        assert "We agreed on the roadmap." in body

    def test_markdown_placeholder_when_no_summary(self, client):
        session = _make_session(summary="")
        with patch("backend.main.session_store.load_session", new_callable=AsyncMock, return_value=session):
            body = client.get("/sessions/abc123/export").text
        assert "_No summary available._" in body

    def test_markdown_contains_action_items(self, client):
        items = [_make_action_item("Write docs", assignee="Alice", status="new")]
        session = _make_session(action_items=items)
        with patch("backend.main.session_store.load_session", new_callable=AsyncMock, return_value=session):
            body = client.get("/sessions/abc123/export").text
        assert "Write docs" in body
        assert "Alice" in body
        assert "[ ]" in body

    def test_markdown_completed_item_uses_checked_box(self, client):
        items = [_make_action_item("Deploy app", status="completed")]
        session = _make_session(action_items=items)
        with patch("backend.main.session_store.load_session", new_callable=AsyncMock, return_value=session):
            body = client.get("/sessions/abc123/export").text
        assert "[x]" in body

    def test_markdown_placeholder_when_no_action_items(self, client):
        session = _make_session(action_items=[])
        with patch("backend.main.session_store.load_session", new_callable=AsyncMock, return_value=session):
            body = client.get("/sessions/abc123/export").text
        assert "_No action items recorded._" in body

    def test_markdown_contains_transcript_segments(self, client):
        segs = [
            _make_segment("Alice", "Hello everyone", start=0.0, end=2.0),
            _make_segment("Bob", "Good morning", start=2.0, end=4.0),
        ]
        session = _make_session(segments=segs)
        with patch("backend.main.session_store.load_session", new_callable=AsyncMock, return_value=session):
            body = client.get("/sessions/abc123/export").text
        assert "**Alice**" in body
        assert "Hello everyone" in body
        assert "**Bob**" in body
        assert "Good morning" in body

    def test_markdown_timestamp_format_minutes_seconds(self, client):
        segs = [_make_segment("Alice", "Hi", start=75.0, end=77.0)]  # 1:15
        session = _make_session(segments=segs)
        with patch("backend.main.session_store.load_session", new_callable=AsyncMock, return_value=session):
            body = client.get("/sessions/abc123/export").text
        assert "[01:15]" in body

    def test_markdown_timestamp_includes_hours(self, client):
        segs = [_make_segment("Alice", "Hi", start=3661.0, end=3663.0)]  # 1:01:01
        session = _make_session(segments=segs)
        with patch("backend.main.session_store.load_session", new_callable=AsyncMock, return_value=session):
            body = client.get("/sessions/abc123/export").text
        assert "[01:01:01]" in body

    def test_markdown_placeholder_when_no_segments(self, client):
        session = _make_session(segments=[])
        with patch("backend.main.session_store.load_session", new_callable=AsyncMock, return_value=session):
            body = client.get("/sessions/abc123/export").text
        assert "_No transcript available._" in body


class TestExportJSON:
    def test_json_format(self, client):
        session = _make_session()
        with patch("backend.main.session_store.load_session", new_callable=AsyncMock, return_value=session):
            resp = client.get("/sessions/abc123/export?format=json")
        assert resp.status_code == 200
        assert "application/json" in resp.headers["content-type"]

    def test_json_contains_all_fields(self, client):
        items = [_make_action_item("Deploy", assignee="Alice")]
        segs = [_make_segment("Alice", "Let's deploy")]
        session = _make_session(title="Deploy Meeting", summary="Deployment plan", action_items=items, segments=segs)
        with patch("backend.main.session_store.load_session", new_callable=AsyncMock, return_value=session):
            resp = client.get("/sessions/abc123/export?format=json")
        data = resp.json()
        assert data["id"] == "abc123"
        assert data["title"] == "Deploy Meeting"
        assert data["summary"] == "Deployment plan"
        assert len(data["action_items"]) == 1
        assert data["action_items"][0]["assignee"] == "Alice"
        assert len(data["segments"]) == 1
        assert data["segments"][0]["speaker"] == "Alice"

    def test_json_is_valid_json(self, client):
        session = _make_session()
        with patch("backend.main.session_store.load_session", new_callable=AsyncMock, return_value=session):
            resp = client.get("/sessions/abc123/export?format=json")
        # Should not raise
        parsed = json.loads(resp.text)
        assert isinstance(parsed, dict)


class TestExportErrors:
    def test_404_for_unknown_session(self, client):
        with patch("backend.main.session_store.load_session", new_callable=AsyncMock, return_value=None):
            resp = client.get("/sessions/unknown/export")
        assert resp.status_code == 404

    def test_422_for_invalid_format(self, client):
        session = _make_session()
        with patch("backend.main.session_store.load_session", new_callable=AsyncMock, return_value=session):
            resp = client.get("/sessions/abc123/export?format=pdf")
        assert resp.status_code == 422
