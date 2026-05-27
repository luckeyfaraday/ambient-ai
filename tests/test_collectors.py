from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from ambient_ai.collectors import (
    AppWindowCollector,
    BrowserCollector,
    SystemCollector,
    TerminalHistoryCollector,
    _clean_history_line,
    _parse_ss_port,
    _parse_ss_process,
    _parse_wmctrl,
    parse_status_files,
    parse_window_title,
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


class TestParseWindowTitle:
    def test_firefox(self):
        p = parse_window_title("GitHub — Mozilla Firefox")
        assert p["title"] == "GitHub"
        assert p["app"] == "firefox"

    def test_chrome(self):
        p = parse_window_title("Gmail - Google Chrome")
        assert p["title"] == "Gmail"
        assert p["app"] == "chrome"

    def test_vscode(self):
        p = parse_window_title("main.py — ambient-ai — Visual Studio Code")
        assert p["title"] == "main.py — ambient-ai"
        assert p["app"] == "vscode"

    def test_en_dash_separator(self):
        p = parse_window_title("Page Title – Mozilla Firefox")
        assert p["title"] == "Page Title"
        assert p["app"] == "firefox"

    def test_unknown_app(self):
        p = parse_window_title("Some Window - UnknownApp")
        assert p["title"] == "Some Window - UnknownApp"
        assert p["app"] is None

    def test_no_separator(self):
        p = parse_window_title("ATHENA")
        assert p["title"] == "ATHENA"
        assert p["app"] is None

    def test_discord(self):
        p = parse_window_title("#general | Server - Discord")
        assert p["title"] == "#general | Server"
        assert p["app"] == "discord"


class TestParseWmctrl:
    def test_parses_lines(self):
        output = (
            "0x04000001  0 myhost Desktop\n"
            "0x06a00001  0 myhost GitHub — Mozilla Firefox\n"
            "0x02c00003  0 myhost ATHENA"
        )
        windows = _parse_wmctrl(output)
        assert len(windows) == 3
        assert windows[0] == ("0x04000001", "Desktop")
        assert windows[1] == ("0x06a00001", "GitHub — Mozilla Firefox")

    def test_empty_output(self):
        assert _parse_wmctrl("") == []

    def test_short_lines_skipped(self):
        assert _parse_wmctrl("0x01  0 host") == []


class TestAppWindowCollector:
    def test_collect_returns_list(self):
        events = AppWindowCollector().collect()
        assert isinstance(events, list)

    def test_events_have_correct_shape(self):
        for event in AppWindowCollector().collect():
            assert event.source == "app"
            assert event.kind == "window"
            assert event.title

    def test_filters_desktop_noise(self):
        collector = AppWindowCollector()
        collector._list_windows = lambda: [
            ("0x01", "Desktop"),
            ("0x02", "nemo-desktop"),
            ("0x03", "GitHub — Mozilla Firefox"),
        ]
        collector._xdotool = lambda args: "0x03"
        events = collector.collect()
        assert len(events) == 1
        assert events[0].title == "GitHub"
        assert events[0].metadata.get("app") == "firefox"
        assert events[0].metadata.get("active") is True

    def test_marks_active_window(self):
        collector = AppWindowCollector()
        collector._list_windows = lambda: [
            ("0x01", "ATHENA"),
            ("0x02", "Gmail - Google Chrome"),
        ]
        collector._xdotool = lambda args: "0x02"
        events = collector.collect()
        active = [e for e in events if e.metadata.get("active")]
        assert len(active) == 1
        assert active[0].metadata["app"] == "chrome"


class TestCleanHistoryLine:
    def test_plain_command(self):
        assert _clean_history_line("git status") == "git status"

    def test_comment_skipped(self):
        assert _clean_history_line("#1234567890") == ""

    def test_zsh_timestamp_stripped(self):
        assert _clean_history_line(": 1716835200:0;ls -la") == "ls -la"

    def test_empty_line(self):
        assert _clean_history_line("") == ""

    def test_whitespace_stripped(self):
        assert _clean_history_line("  cd /tmp  ") == "cd /tmp"


class TestTerminalHistoryCollector:
    def test_collect_returns_list(self):
        events = TerminalHistoryCollector().collect()
        assert isinstance(events, list)

    def test_events_have_correct_shape(self):
        for event in TerminalHistoryCollector().collect():
            assert event.source == "terminal"
            assert event.kind == "shell_command"
            assert event.title

    def test_reads_from_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            hist = Path(tmp) / ".bash_history"
            hist.write_text("git status\npython3 tests/smoke.py\nls\n")
            collector = TerminalHistoryCollector(tail_lines=10)
            collector._find_history_file = lambda: hist
            events = collector.collect()
            assert len(events) == 3
            assert events[0].title == "git status"

    def test_respects_tail_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            hist = Path(tmp) / ".bash_history"
            hist.write_text("\n".join(f"cmd{i}" for i in range(100)))
            collector = TerminalHistoryCollector(tail_lines=5)
            collector._find_history_file = lambda: hist
            events = collector.collect()
            assert len(events) == 5
            assert events[0].title == "cmd95"

    def test_no_history_returns_empty(self):
        collector = TerminalHistoryCollector()
        collector._find_history_file = lambda: None
        assert collector.collect() == []

    def test_short_commands_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            hist = Path(tmp) / ".bash_history"
            hist.write_text("l\nls -la\na\n")
            collector = TerminalHistoryCollector(tail_lines=10)
            collector._find_history_file = lambda: hist
            events = collector.collect()
            assert len(events) == 1
            assert events[0].title == "ls -la"


class TestParseSsPort:
    def test_extracts_port(self):
        line = "LISTEN 0      4096  127.0.0.1:11434  0.0.0.0:*"
        assert _parse_ss_port(line) == 11434

    def test_returns_none_on_junk(self):
        assert _parse_ss_port("no ports here") is None


class TestParseSsProcess:
    def test_extracts_process_name(self):
        line = 'LISTEN 0  511  127.0.0.1:8080  0.0.0.0:*  users:(("node",pid=68738,fd=21))'
        assert _parse_ss_process(line) == "node"

    def test_returns_empty_on_no_match(self):
        assert _parse_ss_process("LISTEN 0 128 0.0.0.0:22 0.0.0.0:*") == ""


class TestSystemCollector:
    def test_collect_returns_list(self):
        events = SystemCollector().collect()
        assert isinstance(events, list)

    def test_hardware_event_present(self):
        events = SystemCollector().collect()
        hw = [e for e in events if e.kind == "hardware"]
        if hw:
            assert hw[0].source == "system"
            assert "cores" in hw[0].title or "RAM" in hw[0].title

    def test_services_event_shape(self):
        events = SystemCollector().collect()
        svc = [e for e in events if e.kind == "services"]
        if svc:
            assert "services" in svc[0].metadata
            assert isinstance(svc[0].metadata["services"], list)
