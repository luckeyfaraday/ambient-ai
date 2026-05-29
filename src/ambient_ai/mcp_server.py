"""Expose Ambient AI as an MCP server.

Genericity is the point: rather than inventing a bespoke contract every agent
must learn, Ambient speaks Model Context Protocol so *any* MCP-capable runtime
(Claude Code, Hermes, Codex, ...) gets ambient context for free. Ambient owns
the proactive/push primitive — continuous, compacted, diff-aware awareness —
on top of MCP's pull transport.

The capture core stays zero-dependency: ``mcp`` is an optional ``[mcp]`` extra
and is imported lazily inside :func:`build_server`. All resource/tool behavior
lives in plain ``paths``-taking functions so it is testable without the SDK.

Resources (read-only context):
  - ``ambient://hot``         compact machine-readable current context
  - ``ambient://recent``      human-readable recent activity
  - ``ambient://sessions``    mechanical time-gap activity sessions
  - ``ambient://diff``        what changed since the previous cycle
  - ``ambient://preferences`` explicit user preferences/policy
  - ``ambient://outcomes``    recent agent decision/outcome history

Tools (the write-back the loop needs):
  - ``record_outcome``  append a structured decision/outcome record
  - ``refresh``         run one collect → reduce → render cycle
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .outcomes import Outcome, append_outcome, read_outcomes
from .paths import AmbientPaths
from .reducers import reduce_context

SERVER_NAME = "ambient-ai"


def _load_hot(paths: AmbientPaths) -> dict[str, Any]:
    """Return the latest reduced context, generating it if absent.

    Reads the already-written ``hot.json`` so that serving context has no side
    effects on the diff snapshot; only an explicit ``refresh`` advances state.
    """
    hot_path = paths.context_dir / "hot.json"
    if hot_path.exists():
        try:
            return json.loads(hot_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return reduce_context(paths)


def hot_resource(paths: AmbientPaths) -> str:
    return json.dumps(_load_hot(paths), indent=2)


def recent_resource(paths: AmbientPaths) -> str:
    recent_path = paths.context_dir / "recent.md"
    if recent_path.exists():
        return recent_path.read_text(encoding="utf-8")
    reduce_context(paths)
    return recent_path.read_text(encoding="utf-8")


def sessions_resource(paths: AmbientPaths) -> str:
    return json.dumps(_load_hot(paths).get("sessions", []), indent=2)


def diff_resource(paths: AmbientPaths) -> str:
    return json.dumps(_load_hot(paths).get("diff", {}), indent=2)


def preferences_resource(paths: AmbientPaths) -> str:
    prefs_path = paths.learning_dir / "preferences.md"
    if not prefs_path.exists():
        reduce_context(paths)  # ensure_learning_files seeds defaults
    return prefs_path.read_text(encoding="utf-8")


def outcomes_resource(paths: AmbientPaths, limit: int = 50) -> str:
    return json.dumps(read_outcomes(paths, limit=limit), indent=2)


def record_outcome_tool(
    paths: AmbientPaths,
    decision: str,
    summary: str = "",
    agent: str = "unknown",
    evidence: list[str] | None = None,
    event_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Append a structured outcome record. Ambient stores; it does not judge."""
    record = append_outcome(
        paths,
        Outcome(
            decision=decision,
            summary=summary,
            agent=agent,
            evidence=evidence or [],
            event_ids=event_ids or [],
        ),
    )
    return {"recorded": True, "decision": record.decision, "recorded_at": record.recorded_at}


def refresh_tool(paths: AmbientPaths, repo: str | None = None) -> dict[str, Any]:
    """Run one collect → reduce → render cycle and report what changed."""
    from .daemon import run_once

    inserted = run_once(paths, repo_path=Path(repo) if repo else None)
    hot = _load_hot(paths)
    diff = hot.get("diff", {})
    return {
        "inserted": inserted,
        "event_count": hot.get("event_count", 0),
        "new_since_last": diff.get("new_count", 0),
        "gone_since_last": diff.get("gone_count", 0),
    }


def build_server(paths: AmbientPaths | None = None):
    """Construct the FastMCP server. Imports the optional ``mcp`` SDK lazily."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - exercised only without extra
        raise RuntimeError(
            "The MCP server requires the optional 'mcp' dependency. "
            "Install it with: pip install 'ambient-ai[mcp]'"
        ) from exc

    resolved = paths or AmbientPaths.from_env()
    resolved.ensure()
    mcp = FastMCP(SERVER_NAME)

    @mcp.resource("ambient://hot", mime_type="application/json")
    def hot() -> str:
        return hot_resource(resolved)

    @mcp.resource("ambient://recent", mime_type="text/markdown")
    def recent() -> str:
        return recent_resource(resolved)

    @mcp.resource("ambient://sessions", mime_type="application/json")
    def sessions() -> str:
        return sessions_resource(resolved)

    @mcp.resource("ambient://diff", mime_type="application/json")
    def diff() -> str:
        return diff_resource(resolved)

    @mcp.resource("ambient://preferences", mime_type="text/markdown")
    def preferences() -> str:
        return preferences_resource(resolved)

    @mcp.resource("ambient://outcomes", mime_type="application/json")
    def outcomes() -> str:
        return outcomes_resource(resolved)

    @mcp.tool()
    def record_outcome(
        decision: str,
        summary: str = "",
        agent: str = "unknown",
        evidence: list[str] | None = None,
        event_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """Record what you decided and how it landed (no_action/done/blocked/handoff)."""
        return record_outcome_tool(resolved, decision, summary, agent, evidence, event_ids)

    @mcp.tool()
    def refresh(repo: str | None = None) -> dict[str, Any]:
        """Run one Ambient capture cycle and report how context changed."""
        return refresh_tool(resolved, repo)

    return mcp


def serve(paths: AmbientPaths | None = None) -> None:
    """Run the MCP server over stdio (the default MCP transport)."""
    build_server(paths).run()
