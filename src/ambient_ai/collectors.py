from __future__ import annotations

from datetime import datetime, timezone

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


class RepoCollector(Collector):
    source = "repo"


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

