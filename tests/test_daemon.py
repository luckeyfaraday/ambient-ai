from __future__ import annotations

import pytest

from ambient_ai.collectors import Collector
from ambient_ai.daemon import (
    build_collectors,
    default_collector_names,
    normalize_collector_names,
    run_once,
)
from ambient_ai.events import AmbientEvent


class StaticCollector(Collector):
    source = "static"

    def collect(self) -> list[AmbientEvent]:
        return [AmbientEvent(source=self.source, kind="unit", title="static event")]


class TestCollectorControls:
    def test_normalizes_comma_separated_names(self):
        assert normalize_collector_names(["repo, terminal", "system"]) == [
            "repo",
            "terminal",
            "system",
        ]

    def test_rejects_unknown_collectors(self):
        with pytest.raises(ValueError, match="Unknown collector"):
            normalize_collector_names(["repo,unknown"])

    def test_build_collectors_honors_enabled_list(self, tmp_path):
        collectors = build_collectors(repo_path=tmp_path, enabled=["repo"])
        assert [collector.source for collector in collectors] == ["repo"]

    def test_build_collectors_honors_disabled_list(self, tmp_path):
        collectors = build_collectors(repo_path=tmp_path, disabled=["terminal", "browser"])
        sources = [collector.source for collector in collectors]
        assert "terminal" not in sources
        assert "browser" not in sources
        assert "repo" in sources

    def test_default_collectors_are_platform_aware(self, monkeypatch):
        monkeypatch.setattr("sys.platform", "win32")
        assert default_collector_names() == ["repo", "app", "browser", "system"]

        monkeypatch.setattr("sys.platform", "linux")
        assert default_collector_names() == ["repo", "app", "browser", "terminal", "system"]

    def test_run_once_accepts_explicit_empty_collector_list(self, paths):
        inserted = run_once(paths, collectors=[])
        assert inserted == 0

    def test_run_once_accepts_injected_collectors(self, paths):
        inserted = run_once(paths, collectors=[StaticCollector()])
        assert inserted == 1
