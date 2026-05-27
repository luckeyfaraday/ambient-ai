from __future__ import annotations

import json

from ambient_ai.collectors import sample_events
from ambient_ai.reducers import candidate_threads, reduce_context


class TestCandidateThreads:
    def _make_row(self, source: str, kind: str, title: str, row_id: int = 1) -> dict:
        return {"id": row_id, "source": source, "kind": kind, "title": title}

    def test_video_model_produces_thread(self):
        rows = [self._make_row("video", "youtube_watch", "Model X overview")]
        threads = candidate_threads(rows)
        assert len(threads) == 1
        assert threads[0]["id"] == "local-model-viability"

    def test_browser_model_produces_thread(self):
        rows = [self._make_row("browser", "tab", "Model Y GitHub")]
        threads = candidate_threads(rows)
        assert len(threads) == 1

    def test_no_model_keyword_no_thread(self):
        rows = [self._make_row("video", "youtube_watch", "Cooking pasta")]
        assert candidate_threads(rows) == []

    def test_non_video_browser_source_no_thread(self):
        rows = [self._make_row("repo", "git_state", "Model X repo")]
        assert candidate_threads(rows) == []

    def test_empty_rows(self):
        assert candidate_threads([]) == []

    def test_evidence_event_ids_capped_at_six(self):
        rows = [
            self._make_row("video", "youtube_watch", f"Model {i}", row_id=i)
            for i in range(10)
        ]
        threads = candidate_threads(rows)
        assert len(threads[0]["evidence_event_ids"]) <= 6


class TestReduceContext:
    def test_produces_hot_json(self, paths, store):
        store.add_events(sample_events())
        hot = reduce_context(paths)
        assert hot["event_count"] == 4
        assert hot["unique_event_count"] == 4

    def test_empty_db_produces_zero_events(self, paths, store):
        hot = reduce_context(paths)
        assert hot["event_count"] == 0
        assert hot["candidate_threads"] == []
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
