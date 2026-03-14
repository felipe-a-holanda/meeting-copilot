"""Session storage — SQLite via aiosqlite for meeting persistence."""

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

import aiosqlite

from backend.ws.protocol import ActionItem, TranscriptSegment


@dataclass
class SessionInfo:
    """Lightweight session descriptor returned by list_sessions()."""

    id: str
    title: str
    created_at: float
    updated_at: float
    segment_count: int = 0


@dataclass
class SessionData:
    """Full session state returned by load_session()."""

    id: str
    title: str
    created_at: float
    updated_at: float
    summary: str = ""
    action_items: list[ActionItem] = field(default_factory=list)
    segments: list[TranscriptSegment] = field(default_factory=list)


class SessionStore:
    """Async SQLite-backed store for meeting sessions."""

    def __init__(self, db_path: str = "meetings.db") -> None:
        self.db_path = db_path

    async def init_db(self) -> None:
        """Create tables if they don't exist."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id          TEXT PRIMARY KEY,
                    title       TEXT NOT NULL,
                    created_at  REAL NOT NULL,
                    updated_at  REAL NOT NULL
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS segments (
                    id              TEXT PRIMARY KEY,
                    session_id      TEXT NOT NULL REFERENCES sessions(id),
                    speaker         TEXT NOT NULL,
                    text            TEXT NOT NULL,
                    timestamp_start REAL NOT NULL,
                    timestamp_end   REAL NOT NULL,
                    language        TEXT NOT NULL DEFAULT 'pt',
                    is_partial      INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS meeting_state (
                    session_id      TEXT PRIMARY KEY REFERENCES sessions(id),
                    summary         TEXT NOT NULL DEFAULT '',
                    action_items    TEXT NOT NULL DEFAULT '[]',
                    updated_at      REAL NOT NULL
                )
                """
            )
            await db.commit()

    async def create_session(self, title: str = "") -> SessionInfo:
        """Create a new meeting session and return its info."""
        session_id = str(uuid.uuid4())
        now = time.time()
        if not title:
            title = f"Meeting {session_id[:8]}"

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (session_id, title, now, now),
            )
            await db.execute(
                "INSERT INTO meeting_state (session_id, summary, action_items, updated_at) VALUES (?, '', '[]', ?)",
                (session_id, now),
            )
            await db.commit()

        return SessionInfo(
            id=session_id,
            title=title,
            created_at=now,
            updated_at=now,
            segment_count=0,
        )

    async def save_segment(self, session_id: str, segment: TranscriptSegment) -> None:
        """Persist a transcript segment for the given session."""
        seg_id = str(uuid.uuid4())
        now = time.time()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO segments
                    (id, session_id, speaker, text, timestamp_start, timestamp_end, language, is_partial)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    seg_id,
                    session_id,
                    segment.speaker,
                    segment.text,
                    segment.timestamp_start,
                    segment.timestamp_end,
                    segment.language,
                    int(segment.is_partial),
                ),
            )
            await db.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
            await db.commit()

    async def save_state(
        self,
        session_id: str,
        summary: str,
        action_items: list[ActionItem],
    ) -> None:
        """Persist the current summary and action items for a session."""
        now = time.time()
        items_json = json.dumps([item.model_dump() for item in action_items])
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO meeting_state (session_id, summary, action_items, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    summary = excluded.summary,
                    action_items = excluded.action_items,
                    updated_at = excluded.updated_at
                """,
                (session_id, summary, items_json, now),
            )
            await db.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
            await db.commit()

    async def load_session(self, session_id: str) -> Optional[SessionData]:
        """Restore full meeting state for a session. Returns None if not found."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute(
                "SELECT id, title, created_at, updated_at FROM sessions WHERE id = ?",
                (session_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None

            session = SessionData(
                id=row["id"],
                title=row["title"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

            # Load state
            cursor = await db.execute(
                "SELECT summary, action_items FROM meeting_state WHERE session_id = ?",
                (session_id,),
            )
            state_row = await cursor.fetchone()
            if state_row:
                session.summary = state_row["summary"]
                raw_items = json.loads(state_row["action_items"])
                session.action_items = [ActionItem(**item) for item in raw_items]

            # Load segments
            cursor = await db.execute(
                """
                SELECT speaker, text, timestamp_start, timestamp_end, language, is_partial
                FROM segments
                WHERE session_id = ?
                ORDER BY timestamp_start ASC
                """,
                (session_id,),
            )
            rows = await cursor.fetchall()
            session.segments = [
                TranscriptSegment(
                    speaker=r["speaker"],
                    text=r["text"],
                    timestamp_start=r["timestamp_start"],
                    timestamp_end=r["timestamp_end"],
                    language=r["language"],
                    is_partial=bool(r["is_partial"]),
                )
                for r in rows
            ]

        return session

    async def list_sessions(self) -> list[SessionInfo]:
        """Return all sessions ordered by most recent first."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT s.id, s.title, s.created_at, s.updated_at,
                       COUNT(sg.id) AS segment_count
                FROM sessions s
                LEFT JOIN segments sg ON sg.session_id = s.id
                GROUP BY s.id
                ORDER BY s.updated_at DESC
                """
            )
            rows = await cursor.fetchall()
            return [
                SessionInfo(
                    id=r["id"],
                    title=r["title"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                    segment_count=r["segment_count"],
                )
                for r in rows
            ]
