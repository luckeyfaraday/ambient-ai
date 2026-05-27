from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))


def run(args: list[str], root: Path) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env["AMBIENT_AI_HOME"] = str(root)
    subprocess.run([sys.executable, "-m", "ambient_ai", *args], cwd=REPO_ROOT, env=env, check=True)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ambient-ai-smoke-") as tmp:
        root = Path(tmp)
        prompts = root / "prompts"
        prompts.mkdir()
        (prompts / "hermes_handoff.md.tmpl").write_text(
            (REPO_ROOT / "prompts" / "hermes_handoff.md.tmpl").read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        run(["init"], root)
        run(["ingest-sample"], root)
        run(["collect-repo", "--repo", str(REPO_ROOT)], root)
        run(["reduce"], root)
        run(["render-hermes"], root)

        expected = [
            root / "data" / "ambient.sqlite3",
            root / "context" / "hot.json",
            root / "context" / "recent.md",
            root / "context" / "hermes-handoff.md",
            root / "context" / "learning" / "preferences.md",
            root / "context" / "learning" / "trigger-outcomes.jsonl",
        ]
        missing = [path for path in expected if not path.exists()]
        if missing:
            raise AssertionError(f"Missing expected files: {missing}")

        hot = json.loads((root / "context" / "hot.json").read_text(encoding="utf-8"))
        assert hot["event_count"] >= 5, f"Expected at least 5 events, got {hot['event_count']}"
        assert hot["unique_event_count"] >= 5
        assert "candidate_threads" not in hot
        assert len(hot["recent_refs"]) > 0
        assert any(ref["kind"] == "git_state" for ref in hot["recent_refs"])

        prompt = (root / "context" / "hermes-handoff.md").read_text(encoding="utf-8")
        assert (REPO_ROOT / "skills" / "hermes-ambient-ai" / "SKILL.md").exists()
        assert "hermes-ambient-ai" in prompt
        assert "external agent runtime" in prompt
        assert "Do not ask the user what to do by default" in prompt
        assert "No-op silently" in prompt
        assert "large downloads" in prompt

        run(["ingest-sample"], root)
        run(["reduce"], root)
        hot2 = json.loads((root / "context" / "hot.json").read_text(encoding="utf-8"))
        assert hot2["event_count"] == hot["event_count"], (
            f"Duplicate ingest should not grow event count: {hot2['event_count']} != {hot['event_count']}"
        )

        run(["daemon", "--once", "--repo", str(REPO_ROOT)], root)
        daemon_hot = json.loads((root / "context" / "hot.json").read_text(encoding="utf-8"))
        assert daemon_hot["event_count"] >= hot2["event_count"]

    from ambient_ai.collectors import AppWindowCollector  # noqa: E402
    window_events = AppWindowCollector().collect()
    assert isinstance(window_events, list)
    for ev in window_events:
        assert ev.source == "app"
        assert ev.kind == "active_window"
        assert ev.title

    with tempfile.TemporaryDirectory(prefix="ambient-ai-legacy-db-") as tmp:
        root = Path(tmp)
        db_path = root / "data" / "ambient.sqlite3"
        db_path.parent.mkdir()
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                CREATE TABLE events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    occurred_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT,
                    artifact_ref TEXT,
                    metadata_json TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute("CREATE INDEX idx_events_fingerprint ON events(fingerprint)")
            for title in ("Old duplicate", "New duplicate"):
                conn.execute(
                    """
                    INSERT INTO events
                        (occurred_at, source, kind, title, url, artifact_ref, metadata_json, fingerprint)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "2026-05-27T00:00:00+00:00",
                        "browser",
                        "tab",
                        title,
                        "https://example.com/model",
                        None,
                        "{}",
                        "browser|tab|duplicate|https://example.com/model",
                    ),
                )

        run(["init"], root)
        with sqlite3.connect(db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            assert count == 1, f"Legacy duplicate migration kept {count} rows"
            index_unique = conn.execute(
                "SELECT [unique] FROM pragma_index_list('events') WHERE name = 'idx_events_fingerprint'"
            ).fetchone()
            assert index_unique is not None and index_unique[0] == 1

    print("Ambient AI smoke check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
