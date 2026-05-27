from __future__ import annotations

import subprocess
from hashlib import sha1
from datetime import datetime, timezone
from pathlib import Path

from .events import AmbientEvent


class Collector:
    source = "unknown"

    def collect(self) -> list[AmbientEvent]:
        return []


class BrowserCollector(Collector):
    source = "browser"


class VideoCollector(Collector):
    source = "video"


class AppWindowCollector(Collector):
    source = "app"

    def collect(self) -> list[AmbientEvent]:
        title = self._xdotool(["getactivewindow", "getwindowname"])
        if not title:
            return []
        wm_class = self._xdotool(["getactivewindow", "getwindowclassname"])
        now = datetime.now(timezone.utc).isoformat()
        meta: dict[str, object] = {}
        if wm_class:
            meta["wm_class"] = wm_class
        return [
            AmbientEvent(
                source=self.source,
                kind="active_window",
                title=title,
                metadata=meta,
                occurred_at=now,
            )
        ]

    def _xdotool(self, args: list[str]) -> str | None:
        try:
            result = subprocess.run(
                ["xdotool", *args],
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
