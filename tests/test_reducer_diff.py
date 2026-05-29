from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ambient_ai.events import AmbientEvent
from ambient_ai.reducers import reduce_context, sessionize


def _event(title: str, occurred_at: str, source: str = "browser") -> AmbientEvent:
    return AmbientEvent(source=source, kind="history", title=title, url=f"https://x/{title}", occurred_at=occurred_at)


class TestDiff:
    def test_first_cycle_flagged(self, paths, store):
        store.add_events([_event("a", _now())])
        hot = reduce_context(paths)
        assert hot["diff"]["is_first_cycle"] is True
        assert hot["diff"]["since"] is None

    def test_new_events_detected_second_cycle(self, paths, store):
        store.add_events([_event("a", _now())])
        reduce_context(paths)  # establishes snapshot
        store.add_events([_event("b", _now())])
        hot = reduce_context(paths)
        assert hot["diff"]["is_first_cycle"] is False
        assert hot["diff"]["new_count"] == 1
        assert hot["diff"]["new"][0]["title"] == "b"

    def test_gone_events_detected(self, paths, store):
        # Two events far in the past so expire() does not interfere here.
        store.add_events([_event("a", _now()), _event("b", _now())])
        reduce_context(paths)
        # Simulate "a" aging out by deleting it from the store directly.
        with store.connect() as conn:
            conn.execute("DELETE FROM events WHERE title = 'a'")
        hot = reduce_context(paths)
        gone_titles = [ref["title"] for ref in hot["diff"]["gone"]]
        assert "a" in gone_titles
        assert hot["diff"]["gone_count"] == 1

    def test_no_change_yields_empty_diff(self, paths, store):
        store.add_events([_event("a", _now())])
        reduce_context(paths)
        hot = reduce_context(paths)
        assert hot["diff"]["new_count"] == 0
        assert hot["diff"]["gone_count"] == 0

    def test_candidate_threads_never_present(self, paths, store):
        # Boundary guard: Ambient must not interpret/score.
        store.add_events([_event("a", _now())])
        hot = reduce_context(paths)
        assert "candidate_threads" not in hot


class TestSessionize:
    def test_single_session_within_gap(self):
        base = datetime(2026, 5, 29, 12, 0, tzinfo=timezone.utc)
        refs = [
            {"id": 1, "source": "browser", "occurred_at": base.isoformat()},
            {"id": 2, "source": "repo", "occurred_at": (base + timedelta(minutes=5)).isoformat()},
        ]
        sessions = sessionize(refs)
        assert len(sessions) == 1
        assert sessions[0]["event_count"] == 2
        assert sessions[0]["sources"] == ["browser", "repo"]

    def test_gap_splits_sessions(self):
        base = datetime(2026, 5, 29, 12, 0, tzinfo=timezone.utc)
        refs = [
            {"id": 1, "source": "browser", "occurred_at": base.isoformat()},
            {"id": 2, "source": "browser", "occurred_at": (base + timedelta(hours=2)).isoformat()},
        ]
        sessions = sessionize(refs)
        assert len(sessions) == 2
        assert [s["event_count"] for s in sessions] == [1, 1]

    def test_unparseable_timestamps_skipped(self):
        refs = [{"id": 1, "source": "browser", "occurred_at": "not-a-date"}]
        assert sessionize(refs) == []


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
