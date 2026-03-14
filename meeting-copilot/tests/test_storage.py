"""Tests for SessionStore — CRUD operations on SQLite via aiosqlite."""

import pytest
import pytest_asyncio

from backend.storage.session import SessionStore
from backend.ws.protocol import ActionItem, TranscriptSegment


def _make_segment(speaker: str = "Alice", text: str = "Hello", start: float = 0.0, end: float = 1.0) -> TranscriptSegment:
    return TranscriptSegment(
        speaker=speaker,
        text=text,
        timestamp_start=start,
        timestamp_end=end,
    )


@pytest_asyncio.fixture
async def store(tmp_path):
    """Create a fresh in-memory-style store using a temp file per test."""
    db_path = str(tmp_path / "test_meetings.db")
    s = SessionStore(db_path=db_path)
    await s.init_db()
    return s


class TestCreateSession:
    @pytest.mark.asyncio
    async def test_creates_session_with_auto_title(self, store):
        info = await store.create_session()
        assert info.id
        assert info.title.startswith("Meeting ")
        assert info.created_at > 0
        assert info.segment_count == 0

    @pytest.mark.asyncio
    async def test_creates_session_with_custom_title(self, store):
        info = await store.create_session(title="Q1 Planning")
        assert info.title == "Q1 Planning"

    @pytest.mark.asyncio
    async def test_each_session_has_unique_id(self, store):
        a = await store.create_session()
        b = await store.create_session()
        assert a.id != b.id


class TestSaveSegment:
    @pytest.mark.asyncio
    async def test_save_segment_persists(self, store):
        session = await store.create_session()
        seg = _make_segment()
        await store.save_segment(session.id, seg)

        loaded = await store.load_session(session.id)
        assert loaded is not None
        assert len(loaded.segments) == 1
        assert loaded.segments[0].speaker == "Alice"
        assert loaded.segments[0].text == "Hello"

    @pytest.mark.asyncio
    async def test_multiple_segments_ordered_by_timestamp(self, store):
        session = await store.create_session()
        await store.save_segment(session.id, _make_segment(text="Second", start=5.0, end=6.0))
        await store.save_segment(session.id, _make_segment(text="First", start=0.0, end=1.0))

        loaded = await store.load_session(session.id)
        assert loaded is not None
        assert loaded.segments[0].text == "First"
        assert loaded.segments[1].text == "Second"

    @pytest.mark.asyncio
    async def test_segment_count_in_list(self, store):
        session = await store.create_session()
        await store.save_segment(session.id, _make_segment(start=0.0, end=1.0))
        await store.save_segment(session.id, _make_segment(start=1.0, end=2.0))

        sessions = await store.list_sessions()
        match = next(s for s in sessions if s.id == session.id)
        assert match.segment_count == 2


class TestSaveState:
    @pytest.mark.asyncio
    async def test_save_and_load_summary(self, store):
        session = await store.create_session()
        await store.save_state(session.id, summary="Team discussed roadmap.", action_items=[])

        loaded = await store.load_session(session.id)
        assert loaded is not None
        assert loaded.summary == "Team discussed roadmap."

    @pytest.mark.asyncio
    async def test_save_and_load_action_items(self, store):
        session = await store.create_session()
        items = [
            ActionItem(id="abc", description="Write tests", assignee="Bob", source_timestamp=10.0, status="new"),
            ActionItem(id="def", description="Deploy app", source_timestamp=20.0),
        ]
        await store.save_state(session.id, summary="", action_items=items)

        loaded = await store.load_session(session.id)
        assert loaded is not None
        assert len(loaded.action_items) == 2
        assert loaded.action_items[0].id == "abc"
        assert loaded.action_items[0].assignee == "Bob"
        assert loaded.action_items[1].description == "Deploy app"

    @pytest.mark.asyncio
    async def test_save_state_overwrites_previous(self, store):
        session = await store.create_session()
        await store.save_state(session.id, summary="Old summary", action_items=[])
        await store.save_state(session.id, summary="New summary", action_items=[])

        loaded = await store.load_session(session.id)
        assert loaded is not None
        assert loaded.summary == "New summary"


class TestLoadSession:
    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_id(self, store):
        result = await store.load_session("nonexistent-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_loads_session_with_no_segments(self, store):
        session = await store.create_session(title="Empty Meeting")
        loaded = await store.load_session(session.id)
        assert loaded is not None
        assert loaded.title == "Empty Meeting"
        assert loaded.segments == []
        assert loaded.summary == ""
        assert loaded.action_items == []

    @pytest.mark.asyncio
    async def test_loads_complete_session(self, store):
        session = await store.create_session(title="Full Meeting")
        await store.save_segment(session.id, _make_segment(speaker="Alice", text="Hello"))
        await store.save_segment(session.id, _make_segment(speaker="Bob", text="Hi", start=2.0, end=3.0))
        items = [ActionItem(id="x1", description="Follow up", source_timestamp=1.0)]
        await store.save_state(session.id, summary="Good discussion", action_items=items)

        loaded = await store.load_session(session.id)
        assert loaded is not None
        assert loaded.title == "Full Meeting"
        assert len(loaded.segments) == 2
        assert loaded.summary == "Good discussion"
        assert len(loaded.action_items) == 1
        assert loaded.action_items[0].description == "Follow up"


class TestListSessions:
    @pytest.mark.asyncio
    async def test_empty_list_initially(self, store):
        sessions = await store.list_sessions()
        assert sessions == []

    @pytest.mark.asyncio
    async def test_lists_multiple_sessions(self, store):
        await store.create_session(title="Meeting A")
        await store.create_session(title="Meeting B")
        sessions = await store.list_sessions()
        assert len(sessions) == 2

    @pytest.mark.asyncio
    async def test_ordered_by_most_recent_first(self, store):
        a = await store.create_session(title="First")
        await store.save_segment(a.id, _make_segment())  # updates updated_at for a
        b = await store.create_session(title="Second")

        sessions = await store.list_sessions()
        # b is more recent (created after a's last update)
        assert sessions[0].title == "Second"
