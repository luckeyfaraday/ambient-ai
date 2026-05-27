# Ambient AI Architecture

Ambient AI is a local context substrate plus agent handoff contract. It continuously captures cheap activity signals, stores raw metadata locally, reduces that metadata into compact context files, and exposes handoff artifacts for Hermes or another agent to decide whether any proactive work is useful.

## Data Flow

1. Collectors capture cheap events: browser tabs, video titles and transcript references, app/window titles, repo activity, voice transcript references, Athena sessions, selected text, and terminal failures.
2. Events are appended to SQLite at `data/ambient.sqlite3`.
3. Reducers deterministically dedupe repeated events, collapse references, and write compact outputs under `context/`.
4. Ambient AI renders `context/hermes-handoff.md` as a compact external-runtime handoff.
5. Hermes or another peer harness may read the handoff, apply policy, act safely, ask only when required, and write outcome history or preference updates.

## MVP Scope

- Standard-library Python only.
- SQLite event log.
- Real local Git collector plus placeholder classes for browser, video, app, voice, and Athena.
- Deterministic reducers before any LLM handoff.
- Hermes handoff template and reusable agent work contract.
- Learning files for explicit preferences and trigger outcomes.
- Smoke check that verifies event ingestion, reduction, and prompt rendering.

## Non-Goals

- No full-screen LLM streaming.
- No external network calls in the scaffold.
- No heavy dependencies.
- No autonomous commits, deployments, messages, purchases, destructive operations, or large downloads.
- No Ambient-owned importance/confidence scoring. Agents make those judgments.
- No embedded Hermes runtime. Hermes integration is a handoff contract and optional skill for a separate harness.

## Local Files

- `context/hot.json`: compact machine-readable current context.
- `context/recent.md`: compact human-readable recent context.
- `context/learning/preferences.md`: explicit preferences and policy notes.
- `context/learning/trigger-outcomes.jsonl`: append-only outcome history.
- `prompts/hermes_handoff.md.tmpl`: Hermes handoff template.
- `prompts/agent_work_contract.md`: contract for external agents.
- `skills/hermes-ambient-ai/SKILL.md`: Hermes consumer contract for Ambient handoff artifacts.

## Daemon Loop

The `daemon` command runs collectors, appends events, reduces context, and renders the Hermes handoff. It is intentionally local and deterministic: no network calls, no LLM calls, and no direct control over external agent runtimes.

Use `daemon --once --repo /path/to/repo` for one cycle or `daemon --interval 300 --repo /path/to/repo` for a long-running local loop. If `--repo` is omitted, the daemon collects the current working directory's Git repo.
