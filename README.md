# Ambient AI

Ambient AI is a local context substrate for proactive agent work. It is not the LLM decision-maker and it is not just a context packet sender.

The MVP captures cheap activity metadata, stores it locally, reduces it into compact context files, and renders an external agent handoff. Hermes or another agent reads that context, decides whether useful autonomous work exists, acts within policy, and stays silent when there is nothing worth doing.

## Product Boundary

- Ambient AI maintains context, policy, lifecycle, learning files, and handoff contracts.
- Agents such as Hermes, Codex, Claude Code, and OpenCode perform reasoning, importance judgment, and action choice.
- Ambient AI monitors constantly but reasons sparingly.
- Raw metadata stays local by default. Reducers dedupe and summarize before anything is handed to an agent.

## MVP Contents

- `src/ambient_ai/`: Python package for event ingestion, SQLite storage, reducers, template rendering, and CLI commands.
- `prompts/hermes_handoff.md.tmpl`: Hermes-readable handoff prompt.
- `prompts/agent_work_contract.md`: reusable external-agent work contract.
- `context/`: generated local context files such as `hot.json`, `recent.md`, and `learning/preferences.md`.
- `docs/architecture.md`: architecture and MVP scope.
- `docs/model-video-scenario.md`: example open-source model video workflow.
- `tests/smoke.py`: smoke check for context generation and prompt rendering.

## Run The Smoke Check

```bash
python3 tests/smoke.py
```

The smoke check creates a temporary Ambient workspace, ingests sample events, runs reducers, renders the Hermes handoff, and verifies the expected context files exist.

## Local CLI

From this repo:

```bash
PYTHONPATH=src python3 -m ambient_ai init
PYTHONPATH=src python3 -m ambient_ai ingest-sample
PYTHONPATH=src python3 -m ambient_ai collect-repo
PYTHONPATH=src python3 -m ambient_ai reduce
PYTHONPATH=src python3 -m ambient_ai render-hermes
PYTHONPATH=src python3 -m ambient_ai daemon --once
```

Set `AMBIENT_AI_HOME=/path/to/workspace` to write context and data somewhere other than the current directory.

`collect-repo` captures local Git branch, head, dirty state, and changed-file references. `daemon --once` runs one collection/reduction/handoff cycle; omit `--once` to keep looping.

## Hermes Handoff

Refresh Ambient artifacts on a schedule:

```bash
*/5 * * * * cd /path/to/ambient-ai && PYTHONPATH=src python3 -m ambient_ai render-hermes --output context/hermes-handoff.md
```

Hermes should read `context/hermes-handoff.md`, inspect referenced context files, and only notify the user for useful completed work, meaningful blockers, or required approval.
