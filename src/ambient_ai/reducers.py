from __future__ import annotations

import json
from collections import OrderedDict
from datetime import datetime, timezone

from .events import EventStore
from .paths import AmbientPaths

# Mechanical session grouping: events separated by more than this gap start a
# new session. This is a temporal cut, not a semantic one — Ambient groups by
# time, never by meaning. Interpreting *what* a session is about is the
# consuming agent's job (see docs/hermes-boundary.md).
SESSION_GAP_SECONDS = 900  # 15 minutes

_SNAPSHOT_NAME = "prev-snapshot.json"


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
    fingerprint_by_id = {row["id"]: row["fingerprint"] for row in items}
    by_source: dict[str, list[dict[str, object]]] = {}
    for ref in refs:
        by_source.setdefault(ref["source"], []).append(ref)

    generated_at = datetime.now(timezone.utc).isoformat()
    sessions = sessionize(refs)
    diff = compute_diff(paths, refs, fingerprint_by_id, generated_at)

    hot = {
        "generated_at": generated_at,
        "event_count": len(rows),
        "unique_event_count": len(items),
        "duplicate_count": duplicate_count,
        "by_source": by_source,
        "sessions": sessions,
        "diff": diff,
        "recent_refs": refs,
    }

    (paths.context_dir / "hot.json").write_text(json.dumps(hot, indent=2), encoding="utf-8")
    (paths.context_dir / "recent.md").write_text(render_recent_md(hot), encoding="utf-8")
    ensure_learning_files(paths)
    return hot


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def sessionize(
    refs: list[dict[str, object]], gap_seconds: int = SESSION_GAP_SECONDS
) -> list[dict[str, object]]:
    """Group refs into sessions by time gap. Purely temporal, no semantics.

    Refs are ordered chronologically; a gap larger than ``gap_seconds`` between
    consecutive events starts a new session. Sessions reference events by id so
    callers can join back to ``recent_refs`` without duplicating payload.
    """
    timed = [(ref, _parse_ts(ref["occurred_at"])) for ref in refs]
    timed = [(ref, ts) for ref, ts in timed if ts is not None]
    timed.sort(key=lambda pair: pair[1])

    sessions: list[dict[str, object]] = []
    current: list[tuple[dict[str, object], datetime]] = []

    def flush() -> None:
        if not current:
            return
        members = [ref for ref, _ in current]
        sessions.append(
            {
                "id": len(sessions) + 1,
                "started_at": current[0][1].isoformat(),
                "ended_at": current[-1][1].isoformat(),
                "event_count": len(members),
                "sources": sorted({str(ref["source"]) for ref in members}),
                "event_ids": [ref["id"] for ref in members],
            }
        )

    for ref, ts in timed:
        if current and (ts - current[-1][1]).total_seconds() > gap_seconds:
            flush()
            current = []
        current.append((ref, ts))
    flush()
    return sessions


def compute_diff(
    paths: AmbientPaths,
    refs: list[dict[str, object]],
    fingerprint_by_id: dict[int, str],
    generated_at: str,
) -> dict[str, object]:
    """Boundary-safe set difference vs. the previous reduction snapshot.

    Reports which references are new and which are gone since the last cycle so
    consumers don't re-derive novelty (and re-spend tokens) every time. This is
    mechanical state-diffing, not interpretation.
    """
    snapshot_path = paths.data_dir / _SNAPSHOT_NAME
    previous: dict[str, object] = {}
    if snapshot_path.exists():
        try:
            previous = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            previous = {}

    prev_refs: dict[str, dict[str, object]] = previous.get("fingerprints", {}) or {}
    current_refs = {
        fingerprint_by_id[ref["id"]]: ref
        for ref in refs
        if ref["id"] in fingerprint_by_id
    }

    new_refs = [ref for fp, ref in current_refs.items() if fp not in prev_refs]
    gone_refs = [ref for fp, ref in prev_refs.items() if fp not in current_refs]

    diff = {
        "since": previous.get("generated_at"),
        "is_first_cycle": not bool(previous),
        "new_count": len(new_refs),
        "gone_count": len(gone_refs),
        "new": new_refs,
        "gone": gone_refs,
    }

    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(
        json.dumps({"generated_at": generated_at, "fingerprints": current_refs}, indent=2),
        encoding="utf-8",
    )
    return diff


def render_recent_md(hot: dict[str, object]) -> str:
    lines = [
        "# Ambient Recent Context",
        "",
        f"Generated: {hot['generated_at']}",
        f"Events: {hot['event_count']} total, {hot['unique_event_count']} unique, {hot['duplicate_count']} duplicates collapsed",
        "",
    ]

    diff = hot.get("diff", {})
    if isinstance(diff, dict) and not diff.get("is_first_cycle", True):
        lines.append(f"## Since last cycle ({diff.get('since')})")
        lines.append("")
        lines.append(f"- {diff.get('new_count', 0)} new, {diff.get('gone_count', 0)} gone")
        for ref in diff.get("new", []) or []:
            lines.append(f"- new: [{ref['kind']}] {ref['title']}")
        lines.append("")

    sessions = hot.get("sessions", [])
    if sessions:
        lines.append(f"## Sessions ({len(sessions)})")
        lines.append("")
        for session in sessions:
            sources = ", ".join(session.get("sources", []))
            lines.append(
                f"- session {session['id']}: {session['event_count']} events"
                f" [{sources}] {session['started_at']} → {session['ended_at']}"
            )
        lines.append("")

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
