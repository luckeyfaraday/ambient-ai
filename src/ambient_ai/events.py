from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class AmbientEvent:
    source: str
    kind: str
    title: str
    url: str | None = None
    artifact_ref: str | None = None
    metadata: dict[str, Any] | None = None
    occurred_at: str | None = None

    def normalized(self) -> "AmbientEvent":
        return AmbientEvent(
            source=self.source,
            kind=self.kind,
            title=self.title.strip(),
            url=self.url,
            artifact_ref=self.artifact_ref,
            metadata=self.metadata or {},
            occurred_at=self.occurred_at or datetime.now(timezone.utc).isoformat(),
        )


class EventStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    occurred_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT,
                    artifact_ref TEXT,
                    metadata_json TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_occurred_at ON events(occurred_at)")
            self._ensure_unique_fingerprints(conn)

    def add_event(self, event: AmbientEvent) -> int | None:
        normalized = event.normalized()
        fingerprint = make_fingerprint(normalized)
        with self.connect() as conn:
            return self._insert(conn, normalized, fingerprint)

    def add_events(self, events: Iterable[AmbientEvent]) -> int:
        count = 0
        with self.connect() as conn:
            for event in events:
                normalized = event.normalized()
                fingerprint = make_fingerprint(normalized)
                if self._insert(conn, normalized, fingerprint) is not None:
                    count += 1
        return count

    def _insert(
        self, conn: sqlite3.Connection, event: AmbientEvent, fingerprint: str
    ) -> int | None:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO events
                (occurred_at, source, kind, title, url, artifact_ref, metadata_json, fingerprint)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.occurred_at,
                event.source,
                event.kind,
                event.title,
                event.url,
                event.artifact_ref,
                json.dumps(event.metadata or {}, sort_keys=True),
                fingerprint,
            ),
        )
        if cursor.rowcount > 0:
            return int(cursor.lastrowid)
        return None

    def _ensure_unique_fingerprints(self, conn: sqlite3.Connection) -> None:
        row = conn.execute(
            "SELECT [unique] FROM pragma_index_list('events') WHERE name = 'idx_events_fingerprint'"
        ).fetchone()
        if row is not None and row[0] == 1:
            return
        conn.execute("DROP INDEX IF EXISTS idx_events_fingerprint")
        conn.execute(
            """
            DELETE FROM events
            WHERE id NOT IN (
                SELECT MAX(id)
                FROM events
                GROUP BY fingerprint
            )
            """
        )
        conn.execute("CREATE UNIQUE INDEX idx_events_fingerprint ON events(fingerprint)")

    def expire(self, max_age_days: int = 7) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        with self.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM events WHERE occurred_at < ?", (cutoff.isoformat(),)
            )
            return cursor.rowcount

    def recent(self, limit: int = 100) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(
                conn.execute(
                    "SELECT * FROM events ORDER BY occurred_at DESC, id DESC LIMIT ?",
                    (limit,),
                )
            )


def make_fingerprint(event: AmbientEvent) -> str:
    key = "|".join([event.source, event.kind, event.title.lower(), event.url or ""])
    return key[:512]
