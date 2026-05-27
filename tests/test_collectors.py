from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from ambient_ai.collectors import (
    AppWindowCollector,
    BrowserCollector,
    parse_status_files,
    sample_events,
)


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


def _make_firefox_places(profile_dir: Path, rows: list[tuple[str, str, int]]) -> None:
    """Create a minimal Firefox places.sqlite with visit rows of (url, title, visit_date_us)."""
    db_path = profile_dir / "places.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE moz_places "
            "(id INTEGER PRIMARY KEY, url TEXT, title TEXT)"
        )
        conn.execute(
            "CREATE TABLE moz_historyvisits "
            "(id INTEGER PRIMARY KEY, place_id INTEGER, visit_date INTEGER)"
        )
        for i, (url, title, visit_date) in enumerate(rows, 1):
            conn.execute(
                "INSERT INTO moz_places (id, url, title) VALUES (?, ?, ?)",
                (i, url, title),
            )
            conn.execute(
                "INSERT INTO moz_historyvisits (place_id, visit_date) VALUES (?, ?)",
                (i, visit_date),
            )


class TestBrowserCollector:
    def test_collect_returns_list(self):
        events = BrowserCollector().collect()
        assert isinstance(events, list)

    def test_events_have_url(self):
        for event in BrowserCollector().collect():
            assert event.url is not None

    def test_youtube_tagged(self):
        from datetime import datetime, timezone

        now_us = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "test.default-release"
            profile.mkdir()
            _make_firefox_places(profile, [
                ("https://www.youtube.com/watch?v=abc123", "Cool Video", now_us),
                ("https://github.com/foo/bar", "GitHub Repo", now_us),
                ("about:preferences", "Settings", now_us),
            ])
            collector = BrowserCollector(since_minutes=5)
            collector._find_firefox_profile = lambda: profile
            events = collector.collect()

        kinds = {e.kind for e in events}
        assert "youtube_visit" in kinds
        assert "history" in kinds
        urls = {e.url for e in events}
        assert "about:preferences" not in urls
        assert len(events) == 2

    def test_skips_internal_urls(self):
        from datetime import datetime, timezone

        now_us = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "test.default"
            profile.mkdir()
            _make_firefox_places(profile, [
                ("moz-extension://foo/bar", "Extension Page", now_us),
                ("chrome://settings", "Chrome Settings", now_us),
                ("file:///home/user/doc.html", "Local File", now_us),
            ])
            collector = BrowserCollector(since_minutes=5)
            collector._find_firefox_profile = lambda: profile
            events = collector.collect()

        assert len(events) == 0

    def test_respects_since_window(self):
        from datetime import datetime, timezone

        now_us = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
        old_us = now_us - 3600 * 1_000_000  # 1 hour ago
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "test.default"
            profile.mkdir()
            _make_firefox_places(profile, [
                ("https://recent.com", "Recent", now_us),
                ("https://old.com", "Old", old_us),
            ])
            collector = BrowserCollector(since_minutes=5)
            collector._find_firefox_profile = lambda: profile
            events = collector.collect()

        assert len(events) == 1
        assert events[0].url == "https://recent.com"

    def test_no_profile_returns_empty(self):
        collector = BrowserCollector()
        collector._find_firefox_profile = lambda: None
        assert collector.collect() == []


class TestAppWindowCollector:
    def test_collect_returns_list(self):
        events = AppWindowCollector().collect()
        assert isinstance(events, list)

    def test_events_have_correct_shape(self):
        for event in AppWindowCollector().collect():
            assert event.source == "app"
            assert event.kind == "active_window"
            assert event.title
