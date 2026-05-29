from __future__ import annotations

import json

import pytest

from ambient_ai.collectors import sample_events
from ambient_ai.mcp_server import (
    build_server,
    diff_resource,
    hot_resource,
    outcomes_resource,
    preferences_resource,
    record_outcome_tool,
    recent_resource,
    refresh_tool,
    sessions_resource,
)


class TestResources:
    def test_hot_resource_is_json(self, paths, store):
        store.add_events(sample_events())
        data = json.loads(hot_resource(paths))
        assert data["event_count"] == 4
        assert "diff" in data and "sessions" in data

    def test_hot_resource_generates_when_missing(self, paths, store):
        # No prior reduce; resource should produce valid context on demand.
        data = json.loads(hot_resource(paths))
        assert data["event_count"] == 0

    def test_recent_resource_is_markdown(self, paths, store):
        store.add_events(sample_events())
        text = recent_resource(paths)
        assert text.startswith("# Ambient Recent Context")

    def test_sessions_resource_is_list(self, paths, store):
        store.add_events(sample_events())
        assert isinstance(json.loads(sessions_resource(paths)), list)

    def test_diff_resource_first_cycle(self, paths, store):
        store.add_events(sample_events())
        diff = json.loads(diff_resource(paths))
        assert diff["is_first_cycle"] is True

    def test_preferences_resource_seeds_defaults(self, paths, store):
        text = preferences_resource(paths)
        assert "Ambient Learning Preferences" in text

    def test_serving_does_not_advance_diff_snapshot(self, paths, store):
        store.add_events(sample_events())
        # Multiple reads must not consume the diff (no snapshot side effects).
        hot_resource(paths)
        diff = json.loads(diff_resource(paths))
        assert diff["is_first_cycle"] is True


class TestTools:
    def test_record_outcome_appends(self, paths, store):
        result = record_outcome_tool(paths, decision="done", summary="x", agent="hermes")
        assert result["recorded"] is True
        assert result["decision"] == "done"
        records = json.loads(outcomes_resource(paths))
        assert records[0]["summary"] == "x"

    def test_refresh_runs_cycle(self, paths, store):
        result = refresh_tool(paths, repo=None)
        assert "inserted" in result
        assert "new_since_last" in result


class TestBuildServer:
    def test_build_server_constructs(self, paths, store):
        pytest.importorskip("mcp")
        server = build_server(paths)
        assert server is not None
