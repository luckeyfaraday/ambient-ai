from __future__ import annotations

import json
from collections import OrderedDict
from datetime import datetime, timezone

from .events import EventStore
from .paths import AmbientPaths


def reduce_context(paths: AmbientPaths, limit: int = 100) -> dict[str, object]:
    paths.ensure()
    store = EventStore(paths.db_path)
    store.init()
    rows = store.recent(limit=limit)
    unique = OrderedDict()
    duplicate_count = 0

    for row in rows:
        key = row["fingerprint"]
        if key in unique:
            duplicate_count += 1
            continue
        unique[key] = row

    items = list(unique.values())
    hot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "event_count": len(rows),
        "unique_event_count": len(items),
        "duplicate_count": duplicate_count,
        "recent_refs": [
            {
                "id": row["id"],
                "source": row["source"],
                "kind": row["kind"],
                "title": row["title"],
                "url": row["url"],
                "artifact_ref": row["artifact_ref"],
                "occurred_at": row["occurred_at"],
            }
            for row in items[:25]
        ],
    }

    (paths.context_dir / "hot.json").write_text(json.dumps(hot, indent=2), encoding="utf-8")
    (paths.context_dir / "recent.md").write_text(render_recent_md(hot), encoding="utf-8")
    ensure_learning_files(paths)
    return hot


def render_recent_md(hot: dict[str, object]) -> str:
    lines = [
        "# Ambient Recent Context",
        "",
        f"Generated: {hot['generated_at']}",
        f"Events: {hot['event_count']} total, {hot['unique_event_count']} unique, {hot['duplicate_count']} duplicates collapsed",
        "",
        "## Recent References",
        "",
    ]
    for ref in hot["recent_refs"]:
        line = f"- [{ref['source']}/{ref['kind']}] {ref['title']}"
        if ref["url"]:
            line += f" <{ref['url']}>"
        if ref["artifact_ref"]:
            line += f" (artifact: `{ref['artifact_ref']}`)"
        lines.append(line)
    lines.append("")
    return "\n".join(lines)


def ensure_learning_files(paths: AmbientPaths) -> None:
    preferences = paths.learning_dir / "preferences.md"
    outcomes = paths.learning_dir / "trigger-outcomes.jsonl"
    if not preferences.exists():
        preferences.write_text(
            "# Ambient Learning Preferences\n\n"
            "- Ask before external side effects, spending, deleting, committing, deploying, messaging, or large downloads.\n"
            "- Do reversible local research, notes, drafts, and tiny prototypes without interrupting the user when useful.\n"
            "- Stay silent when there is no useful completed work, meaningful blocker, or required approval.\n",
            encoding="utf-8",
        )
    outcomes.touch()
