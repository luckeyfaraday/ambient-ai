# Ambient AI Architecture

Ambient AI is a local context substrate plus agent handoff contract. It continuously captures cheap activity signals, stores raw metadata locally, reduces that metadata into compact context files, and lets Hermes or another agent decide whether any proactive work is useful.

## Data Flow

1. Collectors capture cheap events: browser tabs, video titles and transcript references, app/window titles, repo activity, voice transcript references, Athena sessions, selected text, and terminal failures.
2. Events are appended to SQLite at `data/ambient.sqlite3`.
3. Reducers deterministically dedupe repeated events, collapse references, and write compact outputs under `context/`.
4. The Hermes cron bridge renders `context/hermes-cron.md` every 5 minutes.
5. Hermes reads the context, applies policy, acts safely, asks only when required, and writes outcome history or preference updates.

## MVP Scope

- Standard-library Python only.
- SQLite event log.
- Placeholder collector classes for browser, video, app, repo, voice, and Athena.
- Deterministic reducers before any LLM handoff.
- Hermes prompt template and reusable agent work contract.
- Learning files for explicit preferences and trigger outcomes.
- Smoke check that verifies event ingestion, reduction, and prompt rendering.

## Non-Goals

- No full-screen LLM streaming.
- No external network calls in the scaffold.
- No heavy dependencies.
- No autonomous commits, deployments, messages, purchases, destructive operations, or large downloads.
- No Ambient-owned importance/confidence scoring. Agents make those judgments.

## Local Files

- `context/hot.json`: compact machine-readable current context.
- `context/recent.md`: compact human-readable recent context.
- `context/learning/preferences.md`: explicit preferences and policy notes.
- `context/learning/trigger-outcomes.jsonl`: append-only outcome history.
- `prompts/hermes_cron.md.tmpl`: Hermes cron bridge template.
- `prompts/agent_work_contract.md`: contract for spawned agents.

