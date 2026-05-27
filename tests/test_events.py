from __future__ import annotations

import sqlite3
from pathlib import Path

from ambient_ai.events import AmbientEvent, EventStore


class TestEventStore:
    def test_add_event_returns_rowid(self, store):
        event = AmbientEvent(source="test", kind="unit", title="Hello")
        rowid = store.add_event(event)
        assert rowid is not None and rowid > 0

    def test_duplicate_event_returns_none(self, store):
        event = AmbientEvent(source="test", kind="unit", title="Hello")
        first = store.add_event(event)
        second = store.add_event(event)
        assert first is not None
        assert second is None

    def test_add_events_returns_inserted_count(self, store):
        events = [
            AmbientEvent(source="test", kind="unit", title="A"),
            AmbientEvent(source="test", kind="unit", title="B"),
        ]
        assert store.add_events(events) == 2

    def test_add_events_dedup(self, store):
        events = [
            AmbientEvent(source="test", kind="unit", title="Same"),
            AmbientEvent(source="test", kind="unit", title="Same"),
        ]
        assert store.add_events(events) == 1

    def test_add_events_batch_uses_single_connection(self, store):
        events = [
            AmbientEvent(source="test", kind="unit", title=f"Event {i}")
            for i in range(50)
        ]
        assert store.add_events(events) == 50

    def test_recent_returns_newest_first(self, store):
        store.add_event(AmbientEvent(
            source="test", kind="unit", title="Old", occurred_at="2026-01-01T00:00:00Z",
        ))
        store.add_event(AmbientEvent(
            source="test", kind="unit", title="New", occurred_at="2026-06-01T00:00:00Z",
        ))
        rows = store.recent(limit=2)
        assert rows[0]["title"] == "New"
        assert rows[1]["title"] == "Old"

    def test_recent_respects_limit(self, store):
        for i in range(10):
            store.add_event(AmbientEvent(source="test", kind="unit", title=f"E{i}"))
        assert len(store.recent(limit=3)) == 3


class TestMigrationGate:
    def test_skips_when_already_unique(self, paths):
        store = EventStore(paths.db_path)
        store.init()
        store.init()
        with store.connect() as conn:
            row = conn.execute(
                "SELECT [unique] FROM pragma_index_list('events') "
                "WHERE name = 'idx_events_fingerprint'"
            ).fetchone()
            assert row is not None and row[0] == 1

    def test_migrates_legacy_non_unique_index(self, tmp_path):
        db_path = tmp_path / "data" / "legacy.sqlite3"
        db_path.parent.mkdir(parents=True)
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                CREATE TABLE events (
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
            conn.execute("CREATE INDEX idx_events_fingerprint ON events(fingerprint)")
            for i in range(3):
                conn.execute(
                    "INSERT INTO events "
                    "(occurred_at, source, kind, title, metadata_json, fingerprint) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    ("2026-01-01", "test", "dup", f"Title {i}", "{}", "same-fp"),
                )

        store = EventStore(db_path)
        store.init()

        with store.connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            assert count == 1
            row = conn.execute(
                "SELECT [unique] FROM pragma_index_list('events') "
                "WHERE name = 'idx_events_fingerprint'"
            ).fetchone()
            assert row is not None and row[0] == 1

    def test_migrates_no_index_at_all(self, tmp_path):
        db_path = tmp_path / "data" / "bare.sqlite3"
        db_path.parent.mkdir(parents=True)
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                CREATE TABLE events (
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

        store = EventStore(db_path)
        store.init()

        with store.connect() as conn:
            row = conn.execute(
                "SELECT [unique] FROM pragma_index_list('events') "
                "WHERE name = 'idx_events_fingerprint'"
            ).fetchone()
            assert row is not None and row[0] == 1
