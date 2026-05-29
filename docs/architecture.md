# Ambient AI Architecture

Ambient AI is a local context substrate plus an agent-agnostic consumption surface. It continuously captures cheap activity signals, stores raw metadata locally, reduces that metadata into compact, diff-aware context, and exposes it over the Model Context Protocol (and as Markdown/JSON files) for any agent runtime to decide whether proactive work is useful.

## The Layer

Models are layer one; agents (models + tools + loops that act when invoked) are layer two. Ambient AI is the layer that lets agents act *without* being invoked: a continuous, compacted awareness substrate. It is deliberately vendor-neutral and local-first — it works with any agent and belongs to none, and raw metadata stays on the machine.

## Data Flow

1. Collectors capture cheap events: browser/video history, app/window titles, repo activity, terminal history (secret-redacted), and system state. Placeholder collectors exist for voice and Athena.
2. Events are appended to SQLite at `data/ambient.sqlite3`.
3. Reducers deterministically dedupe repeated events, collapse references, compute a diff vs. the previous cycle and time-gap sessions, and write compact outputs under `context/`.
4. Ambient exposes context two ways: an **MCP server** (`ambient://` resources + `record_outcome`/`refresh` tools) and rendered files (`hot.json`, `recent.md`, `hermes-handoff.md`).
5. Any MCP-capable agent (Claude Code, Hermes, Codex, ...) reads the context, applies policy, acts safely, asks only when required, and writes structured outcomes back via the `record_outcome` tool. Those outcomes seed a per-user learning loop.

## Compaction vs. Interpretation

Reducers perform only *structural* compaction — dedupe, set-diff across cycles, time-gap sessionization, grouping by source. They never score importance, infer intent, or select "candidate work"; that is *semantic* judgment and belongs to the consuming agent. See `docs/hermes-boundary.md`.

## Scope

- Zero-dependency standard-library Python for the capture core; the MCP server is an optional `[mcp]` extra.
- SQLite event log.
- Real collectors for Git, browser history (Firefox + Chromium family), active window, terminal history, and system state, plus placeholder classes for video, voice, and Athena.
- Deterministic, diff-aware reducers before any handoff.
- Local secret scanner (provider token catalog + entropy sweep) for terminal history.
- MCP server exposing context resources and write-back tools; Markdown handoff template and reusable agent work contract.
- Structured outcome log for explicit preferences and trigger outcomes.
- Smoke check that verifies event ingestion, reduction, and prompt rendering.

## Non-Goals

- No full-screen LLM streaming.
- No external network calls in the capture/reduce loop; the MCP server uses local stdio transport.
- No heavy dependencies in the core (MCP SDK is an opt-in extra).
- No autonomous commits, deployments, messages, purchases, destructive operations, or large downloads.
- No Ambient-owned importance/confidence scoring or intent inference. Agents make those judgments.
- No embedded agent runtime. Ambient is a context substrate and contract, not the reasoner.

## Local Files

- `context/hot.json`: compact machine-readable current context (`by_source`, `sessions`, `diff`, `recent_refs`).
- `context/recent.md`: compact human-readable recent context with a "Since last cycle" section.
- `context/learning/preferences.md`: explicit preferences and policy notes.
- `context/learning/trigger-outcomes.jsonl`: append-only structured outcome history.
- `data/prev-snapshot.json`: previous-cycle fingerprint snapshot for diffing.
- `prompts/hermes_handoff.md.tmpl`: Markdown handoff template.
- `prompts/agent_work_contract.md`: contract for external agents.
- `skills/hermes-ambient-ai/SKILL.md`: a reference consumer contract (Hermes is one consumer among many).

## Daemon Loop

The `daemon` command runs collectors, appends events, reduces context, and renders the handoff. It is intentionally local and deterministic: no network calls, no LLM calls, and no direct control over external agent runtimes.

Use `daemon --once --repo /path/to/repo` for one cycle or `daemon --interval 300 --repo /path/to/repo` for a long-running local loop. If `--repo` is omitted, the daemon collects the current working directory's Git repo.

Collector controls:

- `--collectors repo,system` runs only the named collectors.
- `--disable-collector terminal` disables a named collector and may be repeated.
- `AMBIENT_AI_COLLECTORS` and `AMBIENT_AI_DISABLE_COLLECTORS` provide the same controls for unattended runs.
