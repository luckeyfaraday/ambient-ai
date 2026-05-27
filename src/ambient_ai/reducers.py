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
    refs = [
        {
            "id": row["id"],
            "source": row["source"],
            "kind": row["kind"],
            "title": row["title"],
            "url": row["url"],
            "artifact_ref": row["artifact_ref"],
            "occurred_at": row["occurred_at"],
        }
        for row in items
    ]
    by_source: dict[str, list[dict[str, object]]] = {}
    for ref in refs:
        by_source.setdefault(ref["source"], []).append(ref)
    hot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "event_count": len(rows),
        "unique_event_count": len(items),
        "duplicate_count": duplicate_count,
        "by_source": by_source,
        "recent_refs": refs,
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
    ]
    by_source = hot.get("by_source", {})
    if by_source:
        for source, refs in by_source.items():
            lines.append(f"## {source} ({len(refs)})")
            lines.append("")
            for ref in refs:
                line = f"- [{ref['kind']}] {ref['title']}"
                if ref["url"]:
                    line += f" <{ref['url']}>"
                if ref["artifact_ref"]:
                    line += f" (artifact: `{ref['artifact_ref']}`)"
                lines.append(line)
            lines.append("")
    else:
        lines.append("No events.")
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
