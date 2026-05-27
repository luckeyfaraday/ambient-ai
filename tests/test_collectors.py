from __future__ import annotations

from ambient_ai.collectors import AppWindowCollector, parse_status_files, sample_events


class TestParseStatusFiles:
    def test_empty(self):
        assert parse_status_files("") == []

    def test_modified_file(self):
        assert parse_status_files(" M src/foo.py") == ["src/foo.py"]

    def test_added_file(self):
        assert parse_status_files("A  new_file.py") == ["new_file.py"]

    def test_renamed_file_takes_destination(self):
        assert parse_status_files("R  old.py -> new.py") == ["new.py"]

    def test_multiple_files(self):
        status = " M a.py\n M b.py\n?? c.py"
        result = parse_status_files(status)
        assert result == ["a.py", "b.py", "c.py"]

    def test_blank_lines_skipped(self):
        assert parse_status_files("\n M a.py\n\n") == ["a.py"]


class TestSampleEvents:
    def test_returns_four_events(self):
        events = sample_events()
        assert len(events) == 4

    def test_sources_are_diverse(self):
        sources = {e.source for e in sample_events()}
        assert sources == {"video", "browser", "repo", "athena"}

    def test_all_have_occurred_at(self):
        for event in sample_events():
            assert event.occurred_at is not None


class TestAppWindowCollector:
    def test_collect_returns_list(self):
        events = AppWindowCollector().collect()
        assert isinstance(events, list)

    def test_events_have_correct_shape(self):
        for event in AppWindowCollector().collect():
            assert event.source == "app"
            assert event.kind == "active_window"
            assert event.title
