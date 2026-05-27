from __future__ import annotations

import json

from ambient_ai.collectors import sample_events
from ambient_ai.reducers import reduce_context


class TestReduceContext:
    def test_produces_hot_json(self, paths, store):
        store.add_events(sample_events())
        hot = reduce_context(paths)
        assert hot["event_count"] == 4
        assert hot["unique_event_count"] == 4

    def test_empty_db_produces_zero_events(self, paths, store):
        hot = reduce_context(paths)
        assert hot["event_count"] == 0
        assert hot["recent_refs"] == []

    def test_writes_context_files(self, paths, store):
        store.add_events(sample_events())
        reduce_context(paths)
        assert (paths.context_dir / "hot.json").exists()
        assert (paths.context_dir / "recent.md").exists()
        hot = json.loads((paths.context_dir / "hot.json").read_text())
        assert hot["event_count"] == 4

    def test_creates_learning_files(self, paths, store):
        reduce_context(paths)
        assert (paths.learning_dir / "preferences.md").exists()
        assert (paths.learning_dir / "trigger-outcomes.jsonl").exists()
