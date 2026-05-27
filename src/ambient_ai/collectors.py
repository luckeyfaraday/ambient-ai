from __future__ import annotations

import sqlite3
import subprocess
from hashlib import sha1
from datetime import datetime, timezone
from pathlib import Path

from .events import AmbientEvent


class Collector:
    source = "unknown"

    def collect(self) -> list[AmbientEvent]:
        return []


_SKIP_SCHEMES = ("about:", "moz-extension:", "chrome:", "chrome-extension:", "file:")


class BrowserCollector(Collector):
    source = "browser"

    def __init__(self, since_minutes: int = 10):
        self.since_minutes = since_minutes

    def collect(self) -> list[AmbientEvent]:
        events: list[AmbientEvent] = []
        events.extend(self._collect_firefox())
        return events

    def _collect_firefox(self) -> list[AmbientEvent]:
        profile = self._find_firefox_profile()
        if not profile:
            return []
        db_path = profile / "places.sqlite"
        if not db_path.exists():
            return []
        cutoff_us = int(
            (datetime.now(timezone.utc).timestamp() - self.since_minutes * 60)
            * 1_000_000
        )
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT p.url, p.title, v.visit_date
                FROM moz_historyvisits v
                JOIN moz_places p ON v.place_id = p.id
                WHERE v.visit_date > ?
                ORDER BY v.visit_date DESC
                LIMIT 50
                """,
                (cutoff_us,),
            ).fetchall()
            conn.close()
        except (sqlite3.Error, OSError):
            return []
        now = datetime.now(timezone.utc).isoformat()
        events: list[AmbientEvent] = []
        for row in rows:
            url = row["url"] or ""
            title = row["title"] or ""
            if not title or not url:
                continue
            if any(url.startswith(s) for s in _SKIP_SCHEMES):
                continue
            is_youtube = "youtube.com/watch" in url or "youtu.be/" in url
            events.append(
                AmbientEvent(
                    source=self.source,
                    kind="youtube_visit" if is_youtube else "history",
                    title=title,
                    url=url,
                    occurred_at=now,
                )
            )
        return events

    def _find_firefox_profile(self) -> Path | None:
        firefox_dir = Path.home() / ".mozilla" / "firefox"
        if not firefox_dir.exists():
            return None
        candidates = [
            p for p in firefox_dir.glob("*.default*")
            if (p / "places.sqlite").exists()
        ]
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        best = None
        best_mtime = 0.0
        for p in candidates:
            mtime = (p / "places.sqlite").stat().st_mtime
            if mtime > best_mtime:
                best_mtime = mtime
                best = p
        return best


class VideoCollector(Collector):
    source = "video"


_TITLE_NOISE = {"desktop", "nemo-desktop", "panel", "plank", "tint2"}

_KNOWN_APPS: dict[str, str] = {
    "mozilla firefox": "firefox",
    "firefox": "firefox",
    "google chrome": "chrome",
    "chromium": "chromium",
    "visual studio code": "vscode",
    "code - oss": "vscode",
    "sublime text": "sublime",
    "gnome terminal": "gnome-terminal",
    "konsole": "konsole",
    "alacritty": "alacritty",
    "kitty": "kitty",
    "wezterm": "wezterm",
    "nautilus": "nautilus",
    "nemo": "nemo",
    "thunar": "thunar",
    "discord": "discord",
    "slack": "slack",
    "obsidian": "obsidian",
    "pocket": "pocket",
}


def parse_window_title(raw: str) -> dict[str, str | None]:
    for sep in (" — ", " - ", " – "):
        if sep in raw:
            parts = raw.rsplit(sep, 1)
            content = parts[0].strip()
            suffix = parts[1].strip()
            app = _KNOWN_APPS.get(suffix.lower())
            if app:
                return {"title": content, "app": app, "raw": raw}
    return {"title": raw.strip(), "app": None, "raw": raw}


class AppWindowCollector(Collector):
    source = "app"

    def collect(self) -> list[AmbientEvent]:
        windows = self._list_windows()
        active_wid = self._xdotool(["getactivewindow"])
        now = datetime.now(timezone.utc).isoformat()
        events: list[AmbientEvent] = []
        for wid, raw_title in windows:
            if raw_title.lower() in _TITLE_NOISE or len(raw_title) < 3:
                continue
            parsed = parse_window_title(raw_title)
            meta: dict[str, object] = {}
            if parsed["app"]:
                meta["app"] = parsed["app"]
            if wid == active_wid:
                meta["active"] = True
            events.append(
                AmbientEvent(
                    source=self.source,
                    kind="window",
                    title=parsed["title"],
                    metadata=meta,
                    occurred_at=now,
                )
            )
        return events

    def _list_windows(self) -> list[tuple[str, str]]:
        output = self._run_cmd(["wmctrl", "-l"])
        if output is not None:
            return _parse_wmctrl(output)
        title = self._xdotool(["getactivewindow", "getwindowname"])
        if title:
            wid = self._xdotool(["getactivewindow"]) or "0"
            return [(wid, title)]
        return []

    def _xdotool(self, args: list[str]) -> str | None:
        return self._run_cmd(["xdotool", *args])

    def _run_cmd(self, args: list[str]) -> str | None:
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None


def _parse_wmctrl(output: str) -> list[tuple[str, str]]:
    windows: list[tuple[str, str]] = []
    for line in output.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        wid = parts[0]
        title = parts[3]
        windows.append((wid, title))
    return windows


class RepoCollector(Collector):
    source = "repo"

    def __init__(self, repo_path: Path | None = None):
        self.repo_path = (repo_path or Path.cwd()).resolve()

    def collect(self) -> list[AmbientEvent]:
        root = self._git(["rev-parse", "--show-toplevel"])
        if root is None:
            return []

        repo_root = Path(root)
        branch = self._git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root) or "unknown"
        head = self._git(["rev-parse", "--short", "HEAD"], cwd=repo_root)
        status = self._git(["status", "--porcelain"], cwd=repo_root) or ""
        latest = self._git(["log", "-1", "--pretty=format:%h %s"], cwd=repo_root)
        changed_files = parse_status_files(status)
        status_digest = sha1(status.encode("utf-8")).hexdigest()[:12] if status else "clean"
        state = "dirty" if changed_files else "clean"
        now = datetime.now(timezone.utc).isoformat()
        repo_name = repo_root.name

        events = [
            AmbientEvent(
                source=self.source,
                kind="git_state",
                title=f"{repo_name} repo {state} on {branch} ({len(changed_files)} files, {status_digest})",
                metadata={
                    "repo": repo_name,
                    "branch": branch,
                    "head": head,
                    "dirty": bool(changed_files),
                    "status_digest": status_digest,
                    "changed_file_count": len(changed_files),
                    "changed_files": changed_files[:25],
                },
                occurred_at=now,
            )
        ]
        if latest:
            events.append(
                AmbientEvent(
                    source=self.source,
                    kind="git_commit",
                    title=f"{repo_name} latest commit {latest}",
                    metadata={"repo": repo_name, "branch": branch, "head": head},
                    occurred_at=now,
                )
            )
        return events

    def _git(self, args: list[str], cwd: Path | None = None) -> str | None:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=cwd or self.repo_path,
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip()


class VoiceCollector(Collector):
    source = "voice"


class AthenaCollector(Collector):
    source = "athena"


def sample_events() -> list[AmbientEvent]:
    now = datetime.now(timezone.utc).isoformat()
    return [
        AmbientEvent(
            source="video",
            kind="youtube_watch",
            title="Open model X: local inference and hardware requirements",
            url="https://www.youtube.com/watch?v=example-model-x",
            artifact_ref="artifacts/transcripts/example-model-x.txt",
            metadata={"channel": "Local AI Lab", "duration_seconds": 1210},
            occurred_at=now,
        ),
        AmbientEvent(
            source="browser",
            kind="tab",
            title="Model X GitHub repository",
            url="https://github.com/example/model-x",
            metadata={"window_title": "Model X - GitHub"},
            occurred_at=now,
        ),
        AmbientEvent(
            source="repo",
            kind="git_activity",
            title="ambient-ai scaffold created",
            metadata={"branch": "main", "dirty": True},
            occurred_at=now,
        ),
        AmbientEvent(
            source="athena",
            kind="session",
            title="Ambient AI project bootstrap",
            artifact_ref=".context-workspace/hermes/session-recall.md",
            metadata={"agent": "Codex"},
            occurred_at=now,
        ),
    ]


def parse_status_files(status: str) -> list[str]:
    files: list[str] = []
    for line in status.splitlines():
        if not line:
            continue
        path = line[3:] if len(line) > 3 else line
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        files.append(path)
    return files
