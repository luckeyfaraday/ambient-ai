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

    def test_by_source_grouping(self, paths, store):
        store.add_events(sample_events())
        hot = reduce_context(paths)
        by_source = hot["by_source"]
        assert "video" in by_source
        assert "browser" in by_source
        assert "repo" in by_source
        assert "athena" in by_source
        assert len(by_source["video"]) == 1
        assert by_source["video"][0]["kind"] == "youtube_watch"

    def test_empty_db_produces_zero_events(self, paths, store):
        hot = reduce_context(paths)
        assert hot["event_count"] == 0
        assert hot["recent_refs"] == []
        assert hot["by_source"] == {}

    def test_writes_context_files(self, paths, store):
        store.add_events(sample_events())
        reduce_context(paths)
        assert (paths.context_dir / "hot.json").exists()
        assert (paths.context_dir / "recent.md").exists()
        hot = json.loads((paths.context_dir / "hot.json").read_text())
        assert hot["event_count"] == 4
        assert "by_source" in hot

    def test_recent_md_grouped_by_source(self, paths, store):
        store.add_events(sample_events())
        reduce_context(paths)
        md = (paths.context_dir / "recent.md").read_text()
        assert "## video" in md
        assert "## browser" in md
        assert "[youtube_watch]" in md

    def test_creates_learning_files(self, paths, store):
        reduce_context(paths)
        assert (paths.learning_dir / "preferences.md").exists()
        assert (paths.learning_dir / "trigger-outcomes.jsonl").exists()
