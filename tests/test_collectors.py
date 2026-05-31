from __future__ import annotations

import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from ambient_ai.collectors import (
    AppWindowCollector,
    BrowserCollector,
    SystemCollector,
    TerminalHistoryCollector,
    _clean_history_line,
    _parse_ss_port,
    _parse_ss_process,
    _parse_endpoint_port,
    _parse_wmctrl,
    copy_sqlite_database,
    is_low_signal_url,
    parse_status_files,
    parse_window_title,
    redact_command,
    sanitize_browser_url,
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
    with closing(sqlite3.connect(db_path)) as conn:
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
        conn.commit()


def _make_chrome_history(profile_dir: Path, rows: list[tuple[str, str, int]]) -> None:
    """Create a minimal Chrome History database with rows of (url, title, last_visit_time_us)."""
    db_path = profile_dir / "History"
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            "CREATE TABLE urls "
            "(id INTEGER PRIMARY KEY, url TEXT, title TEXT, last_visit_time INTEGER)"
        )
        for i, (url, title, last_visit_time) in enumerate(rows, 1):
            conn.execute(
                "INSERT INTO urls (id, url, title, last_visit_time) VALUES (?, ?, ?, ?)",
                (i, url, title, last_visit_time),
            )
        conn.commit()


class TestBrowserCollector:
    def test_collect_returns_list(self):
        events = BrowserCollector().collect()
        assert isinstance(events, list)

    def test_events_have_url(self):
        for event in BrowserCollector().collect():
            assert event.url is not None

    def test_youtube_tagged(self):
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).replace(microsecond=0)
        now_us = int(now.timestamp() * 1_000_000)
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "test.default-release"
            profile.mkdir()
            _make_firefox_places(profile, [
                ("https://www.youtube.com/watch?v=abc123", "Cool Video", now_us),
                ("https://github.com/foo/bar", "GitHub Repo", now_us),
                ("about:preferences", "Settings", now_us),
            ])
            collector = BrowserCollector(since_minutes=5, browser="firefox")
            collector._find_firefox_profile = lambda: profile
            events = collector.collect()

        kinds = {e.kind for e in events}
        assert "youtube_visit" in kinds
        assert "history" in kinds
        urls = {e.url for e in events}
        assert "about:preferences" not in urls
        assert len(events) == 2
        assert events[0].occurred_at == now.isoformat()

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
            collector = BrowserCollector(since_minutes=5, browser="firefox")
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
            collector = BrowserCollector(since_minutes=5, browser="firefox")
            collector._find_firefox_profile = lambda: profile
            events = collector.collect()

        assert len(events) == 1
        assert events[0].url == "https://recent.com"

    def test_no_profile_returns_empty(self):
        collector = BrowserCollector()
        collector._find_firefox_profile = lambda: None
        # _find_chrome_history takes a browser arg; accept any so the test holds
        # regardless of which browser _choose_browser() picks for the environment.
        collector._find_chrome_history = lambda *args, **kwargs: None
        assert collector.collect() == []

    def test_chrome_youtube_tagged(self):
        from datetime import datetime, timezone

        chrome_offset_seconds = 11_644_473_600
        now = datetime.now(timezone.utc).replace(microsecond=0)
        now_us = int((now.timestamp() + chrome_offset_seconds) * 1_000_000)
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "Default"
            profile.mkdir()
            _make_chrome_history(profile, [
                ("https://youtu.be/abc123", "Short Video", now_us),
                ("https://github.com/foo/bar", "GitHub Repo", now_us),
            ])
            collector = BrowserCollector(since_minutes=5, browser="chrome")
            collector._find_firefox_profile = lambda: None
            collector._find_chrome_history = lambda browser=None: profile / "History"
            events = collector.collect()

        kinds = {event.kind for event in events}
        assert kinds == {"youtube_visit", "history"}
        assert events[0].occurred_at == now.isoformat()

    def test_chrome_skips_internal_urls(self):
        from datetime import datetime, timezone

        chrome_offset_seconds = 11_644_473_600
        now_us = int((datetime.now(timezone.utc).timestamp() + chrome_offset_seconds) * 1_000_000)
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "Default"
            profile.mkdir()
            _make_chrome_history(profile, [
                ("chrome://settings", "Settings", now_us),
                ("chrome-extension://abc/options.html", "Extension", now_us),
                ("file:///Users/me/doc.html", "Local Doc", now_us),
            ])
            collector = BrowserCollector(since_minutes=5, browser="chrome")
            collector._find_firefox_profile = lambda: None
            collector._find_chrome_history = lambda browser=None: profile / "History"
            events = collector.collect()

        assert events == []

    def test_chrome_respects_since_window(self):
        from datetime import datetime, timezone

        chrome_offset_seconds = 11_644_473_600
        now_us = int((datetime.now(timezone.utc).timestamp() + chrome_offset_seconds) * 1_000_000)
        old_us = now_us - 3600 * 1_000_000
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "Default"
            profile.mkdir()
            _make_chrome_history(profile, [
                ("https://recent.com", "Recent", now_us),
                ("https://old.com", "Old", old_us),
            ])
            collector = BrowserCollector(since_minutes=5, browser="chrome")
            collector._find_firefox_profile = lambda: None
            collector._find_chrome_history = lambda browser=None: profile / "History"
            events = collector.collect()

        assert len(events) == 1
        assert events[0].url == "https://recent.com"

    def test_redacts_browser_url_query_and_fragment(self):
        rows = [{
            "url": "http://localhost:1455/success?id_token=secret#frag",
            "title": "Auth Callback",
            "occurred_at": "2026-01-01T00:00:00+00:00",
        }]
        events = BrowserCollector()._history_events(rows)
        assert events[0].url == "http://localhost:1455/success"


class TestSanitizeBrowserUrl:
    def test_strips_query_and_fragment(self):
        assert sanitize_browser_url("https://example.com/a?token=secret#x") == "https://example.com/a"

    def test_keeps_plain_url(self):
        assert sanitize_browser_url("https://example.com/a") == "https://example.com/a"

    def test_chrome_history_copy_includes_wal_sidecars(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "Default" / "History"
            source.parent.mkdir()
            source.write_text("db")
            Path(f"{source}-wal").write_text("wal")
            Path(f"{source}-shm").write_text("shm")

            destination = root / "copy" / "History"
            copy_sqlite_database(source, destination)

            assert destination.read_text() == "db"
            assert Path(f"{destination}-wal").read_text() == "wal"
            assert Path(f"{destination}-shm").read_text() == "shm"


class TestBrowserDetection:
    def test_family_from_desktop(self):
        cases = {
            "firefox.desktop": "firefox",
            "org.mozilla.firefox.desktop": "firefox",
            "librewolf.desktop": "firefox",
            "google-chrome.desktop": "chrome",
            "chromium.desktop": "chromium",
            "microsoft-edge.desktop": "edge",
            "brave-browser.desktop": "brave",
            "vivaldi-stable.desktop": "vivaldi",
            "opera.desktop": "opera",
            "": None,
            "konqueror.desktop": None,
        }
        for desktop, expected in cases.items():
            assert BrowserCollector._family_from_desktop(desktop) == expected

    def test_collect_honors_browser_override(self):
        collector = BrowserCollector(browser="chrome")
        collector._detect_default_browser = lambda: "firefox"
        collector._collect_firefox = lambda: ["firefox-event"]
        collector._collect_chrome = lambda browser="chrome": [f"{browser}-event"]
        assert collector.collect() == ["chrome-event"]

    def test_collect_passes_chromium_browser_to_history_lookup(self):
        collector = BrowserCollector(browser="brave")
        collector._collect_chrome = lambda browser="chrome": [f"{browser}-event"]
        assert collector.collect() == ["brave-event"]

    def test_choose_browser_prefers_default_over_recency(self):
        collector = BrowserCollector()
        collector._detect_default_browser = lambda: "chrome"
        collector._detect_by_recency = lambda: "firefox"
        assert collector._choose_browser() == "chrome"

    def test_choose_browser_falls_back_to_recency(self):
        collector = BrowserCollector()
        collector._detect_default_browser = lambda: None
        collector._detect_by_recency = lambda: "firefox"
        assert collector._choose_browser() == "firefox"

    def test_detect_by_recency_picks_more_recently_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            firefox_profile = root / "ff"
            firefox_profile.mkdir()
            (firefox_profile / "places.sqlite").write_text("ff")
            chrome_history = root / "chrome-History"
            chrome_history.write_text("cr")

            collector = BrowserCollector()
            collector._find_firefox_profile = lambda: firefox_profile
            collector._find_chrome_history_with_browser = lambda: (
                "chrome",
                chrome_history,
            )

            os.utime(firefox_profile / "places.sqlite", (1000, 1000))
            os.utime(chrome_history, (2000, 2000))
            assert collector._detect_by_recency() == "chrome"

            os.utime(firefox_profile / "places.sqlite", (3000, 3000))
            assert collector._detect_by_recency() == "firefox"

    def test_detect_by_recency_none_when_no_browsers(self):
        collector = BrowserCollector()
        collector._find_firefox_profile = lambda: None
        collector._find_chrome_history_with_browser = lambda: None
        assert collector._detect_by_recency() is None

    def test_find_chrome_history_restricts_to_requested_browser(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chrome_history = root / "chrome" / "Default" / "History"
            brave_history = root / "brave" / "Default" / "History"
            chrome_history.parent.mkdir(parents=True)
            brave_history.parent.mkdir(parents=True)
            chrome_history.write_text("chrome")
            brave_history.write_text("brave")
            os.utime(chrome_history, (3000, 3000))
            os.utime(brave_history, (1000, 1000))

            collector = BrowserCollector()
            collector._chrome_roots_with_browser = lambda browser=None: {
                "chrome": [("chrome", chrome_history.parent.parent)],
                "brave": [("brave", brave_history.parent.parent)],
                None: [
                    ("chrome", chrome_history.parent.parent),
                    ("brave", brave_history.parent.parent),
                ],
            }[browser]

            assert collector._find_chrome_history("brave") == brave_history
            assert collector._find_chrome_history("chrome") == chrome_history
            assert collector._find_chrome_history() == chrome_history

    def test_find_chrome_history_supports_direct_history_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = root / "History"
            history.write_text("opera")

            collector = BrowserCollector()
            collector._chrome_roots_with_browser = lambda browser=None: [("opera", root)]

            assert collector._find_chrome_history("opera") == history

    def test_detect_by_recency_returns_most_recent_chromium_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            brave_history = root / "brave" / "Default" / "History"
            edge_history = root / "edge" / "Default" / "History"
            brave_history.parent.mkdir(parents=True)
            edge_history.parent.mkdir(parents=True)
            brave_history.write_text("brave")
            edge_history.write_text("edge")
            os.utime(brave_history, (3000, 3000))
            os.utime(edge_history, (1000, 1000))

            collector = BrowserCollector()
            collector._find_firefox_profile = lambda: None
            collector._chrome_roots_with_browser = lambda browser=None: [
                ("brave", brave_history.parent.parent),
                ("edge", edge_history.parent.parent),
            ]

            assert collector._detect_by_recency() == "brave"

    def test_chrome_roots_includes_common_chromium_family_paths(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            local_app_data = home / "AppData" / "Local"
            app_data = home / "AppData" / "Roaming"
            expected_roots = [
                home / ".config" / "google-chrome",
                home / ".config" / "microsoft-edge",
                home / ".config" / "BraveSoftware" / "Brave-Browser",
                home / ".config" / "vivaldi",
                home / ".config" / "opera",
                local_app_data / "Google" / "Chrome" / "User Data",
                local_app_data / "Microsoft" / "Edge" / "User Data",
                local_app_data / "BraveSoftware" / "Brave-Browser" / "User Data",
                local_app_data / "Vivaldi" / "User Data",
                app_data / "Opera Software" / "Opera Stable",
            ]
            for path in expected_roots:
                path.mkdir(parents=True)
            monkeypatch.setattr(Path, "home", lambda: home)
            monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
            monkeypatch.setenv("APPDATA", str(app_data))

            collector = BrowserCollector()

            assert (
                home / ".config" / "google-chrome"
                in collector._chrome_roots("chrome")
            )
            assert (
                home / ".config" / "microsoft-edge"
                in collector._chrome_roots("edge")
            )
            assert (
                home / ".config" / "BraveSoftware" / "Brave-Browser"
                in collector._chrome_roots("brave")
            )
            assert home / ".config" / "vivaldi" in collector._chrome_roots("vivaldi")
            assert (
                app_data / "Opera Software" / "Opera Stable"
                in collector._chrome_roots("opera")
            )


class TestLowSignalUrl:
    def test_auth_hosts_are_noise(self):
        assert is_low_signal_url("https://accounts.google.com/o/oauth2/auth?foo=bar")
        assert is_low_signal_url("https://login.microsoftonline.com/common/oauth2/authorize")
        assert is_low_signal_url("https://oauth2.googleapis.com/token")

    def test_oauth_path_segments_are_noise(self):
        assert is_low_signal_url("https://github.com/login/oauth/authorize")
        assert is_low_signal_url("https://auth.example.com/sso/start")

    def test_content_urls_are_kept(self):
        assert not is_low_signal_url("https://github.com/foo/bar")
        assert not is_low_signal_url("https://news.ycombinator.com/item?id=123")
        assert not is_low_signal_url("https://youtu.be/abc123")

    def test_search_queries_are_kept(self):
        # SERPs carry user intent in the query string; Hermes decides, not Ambient.
        assert not is_low_signal_url("https://www.google.com/search?q=react+suspense")
        assert not is_low_signal_url("https://duckduckgo.com/?q=sqlite+wal")

    def test_login_substring_is_not_dropped(self):
        # 'login' as a path segment alone is not auth plumbing (e.g. a repo named login).
        assert not is_low_signal_url("https://github.com/acme/login-service")

    def test_sso_content_on_normal_hosts_is_kept(self):
        assert not is_low_signal_url("https://github.com/acme/sso")
        assert not is_low_signal_url("https://docs.example.com/oauth/setup")

    def test_filters_through_collect(self):
        from datetime import datetime, timezone

        now_us = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "test.default"
            profile.mkdir()
            _make_firefox_places(profile, [
                ("https://accounts.google.com/o/oauth2/auth", "Sign in", now_us),
                ("https://github.com/foo/bar", "Real Page", now_us),
            ])
            collector = BrowserCollector(since_minutes=5, browser="firefox")
            collector._find_firefox_profile = lambda: profile
            events = collector.collect()

        urls = {e.url for e in events}
        assert urls == {"https://github.com/foo/bar"}


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
        collector._active_window_id = lambda: "0x03"
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
        collector._active_window_id = lambda: "0x02"
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

    def test_redacts_secret_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            hist = Path(tmp) / ".bash_history"
            hist.write_text(
                "OPENAI_API_KEY=sk-test curl example.com\n"
                "deploy --token abc123 --password hunter2\n"
                "curl -H 'Authorization: Bearer secret-token' https://example.com\n"
            )
            collector = TerminalHistoryCollector(tail_lines=10)
            collector._find_history_file = lambda: hist
            titles = [event.title for event in collector.collect()]

        assert titles == [
            "OPENAI_API_KEY=[REDACTED] curl example.com",
            "deploy --token [REDACTED] --password [REDACTED]",
            "curl -H 'Authorization: Bearer [REDACTED]' https://example.com",
        ]


class TestRedactCommand:
    def test_redacts_env_and_flags(self):
        assert redact_command("TOKEN=abc cmd --api-key xyz") == "TOKEN=[REDACTED] cmd --api-key [REDACTED]"


class TestParseSsPort:
    def test_extracts_port(self):
        line = "LISTEN 0      4096  127.0.0.1:11434  0.0.0.0:*"
        assert _parse_ss_port(line) == 11434

    def test_returns_none_on_junk(self):
        assert _parse_ss_port("no ports here") is None


class TestParseEndpointPort:
    def test_extracts_ipv4_port(self):
        assert _parse_endpoint_port("127.0.0.1:5173") == 5173

    def test_extracts_ipv6_port(self):
        assert _parse_endpoint_port("[::]:3000") == 3000

    def test_returns_none_on_junk(self):
        assert _parse_endpoint_port("*:*") is None


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

    def test_listening_ports_keeps_repeated_service_names(self):
        collector = SystemCollector()
        output = (
            "LISTEN 0 511 127.0.0.1:3000 0.0.0.0:* users:((\"node\",pid=1,fd=1))\n"
            "LISTEN 0 511 127.0.0.1:3001 0.0.0.0:* users:((\"node\",pid=2,fd=1))\n"
        )
        collector._run_ss = lambda: output
        services = collector._listening_ports()
        assert [service["port"] for service in services] == [3000, 3001]

    def test_windows_listening_ports(self, monkeypatch):
        class Result:
            returncode = 0
            stdout = (
                "  TCP    127.0.0.1:5173    0.0.0.0:0    LISTENING    42\n"
                "  TCP    [::]:3000         [::]:0       LISTENING    43\n"
            )

        monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: Result())
        services = SystemCollector()._listening_ports_windows()
        assert services == [
            {"name": "vite", "type": "listener", "port": 5173, "pid": "42"},
            {"name": "dev-server", "type": "listener", "port": 3000, "pid": "43"},
        ]
