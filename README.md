# Ambient AI

Ambient AI is a local-first context engine for proactive AI agents. It captures lightweight activity signals, stores them locally, reduces them into compact context artifacts, and creates handoffs that external agent runtimes can use to decide whether useful work exists.

Use Ambient AI when you want coding agents, research agents, or personal AI assistants to have fresh workspace context without streaming your whole screen into an LLM.

Ambient AI is not the LLM decision-maker. Hermes, Codex, Claude Code, OpenCode, or another external agent reads the generated context, chooses action or no-action, and stays silent when there is nothing useful to do.

## What Ambient AI Does

- Collects local activity metadata from repositories, windows, browser history, terminal history, system state, and other adapters.
- Stores raw events in local SQLite.
- Deduplicates, expires, and reduces events into compact context files.
- Generates `context/hot.json`, `context/recent.md`, and `context/hermes-handoff.md`.
- Provides agent work contracts and a Hermes skill stub for consuming Ambient context.
- Keeps reasoning outside the collector loop to avoid unnecessary LLM calls and token waste.

## Use Cases

- Give a scheduled agent current repo, terminal, browser, and system context.
- Let an external AI agent notice useful local follow-up work without interrupting by default.
- Build a local context layer for proactive coding agents.
- Preserve references to transcripts, logs, browser visits, and workspace artifacts without embedding large content.
- Capture user preferences and feedback for future handoffs.

## Product Boundary

- Ambient AI maintains context, policy, lifecycle, learning files, and handoff contracts.
- Agents such as Hermes, Codex, Claude Code, and OpenCode perform reasoning, importance judgment, and action choice.
- Ambient AI monitors constantly but reasons sparingly.
- Raw metadata stays local by default. Reducers dedupe and summarize before anything is handed to an agent.
- Ambient AI does not commit, deploy, message, spend money, delete files, or take external side effects on its own.

## Core Features

- Local SQLite event log.
- Deterministic reducers for dedupe, grouping, expiry, and compact Markdown/JSON context.
- Repo collector for Git branch, head, dirty state, changed files, and latest commit.
- Browser, window, terminal, and system collectors with daemon controls.
- Terminal command redaction for common token, password, API key, and bearer-token patterns.
- Collector selection with `--collectors`, `--disable-collector`, `AMBIENT_AI_COLLECTORS`, and `AMBIENT_AI_DISABLE_COLLECTORS`.
- Hermes handoff prompt and `hermes-ambient-ai` skill contract.

## MVP Contents

- `src/ambient_ai/`: Python package for event ingestion, SQLite storage, reducers, template rendering, and CLI commands.
- `prompts/hermes_handoff.md.tmpl`: Hermes-readable handoff prompt.
- `prompts/agent_work_contract.md`: reusable external-agent work contract.
- `skills/hermes-ambient-ai/SKILL.md`: Hermes consumer contract.
- `context/`: generated local context files such as `hot.json`, `recent.md`, and `learning/preferences.md`.
- `docs/architecture.md`: architecture and MVP scope.
- `docs/model-video-scenario.md`: example open-source model video workflow.
- `tests/smoke.py`: smoke check for context generation and prompt rendering.

## Generated Context Files

- `context/hot.json`: machine-readable recent context grouped by source.
- `context/recent.md`: human-readable recent activity summary.
- `context/hermes-handoff.md`: handoff prompt for Hermes or another external agent runtime.
- `context/learning/preferences.md`: explicit preferences and policy notes.
- `context/learning/trigger-outcomes.jsonl`: append-only feedback and outcome history.

## Tests

```bash
python3 -m pytest tests/ -v
python3 tests/smoke.py
```

`pytest` runs unit tests for fingerprinting, collectors, reducers, event storage, and migration. The standalone smoke check runs the full CLI pipeline end-to-end in a temp directory.

## Local CLI

From this repo:

```bash
PYTHONPATH=src python3 -m ambient_ai init
PYTHONPATH=src python3 -m ambient_ai ingest-sample
PYTHONPATH=src python3 -m ambient_ai collect-repo
PYTHONPATH=src python3 -m ambient_ai reduce
PYTHONPATH=src python3 -m ambient_ai render-hermes
PYTHONPATH=src python3 -m ambient_ai daemon --once --repo /path/to/repo
PYTHONPATH=src python3 -m ambient_ai daemon --once --collectors repo,system
```

Set `AMBIENT_AI_HOME=/path/to/workspace` to write context and data somewhere other than the current directory.

`collect-repo` captures local Git branch, head, dirty state, and changed-file references. `daemon --once` runs one collection/reduction/handoff cycle; omit `--once` to keep looping. If `--repo` is omitted, the daemon collects the current working directory's Git repo. Use `--collectors repo,system` or repeated `--disable-collector terminal` flags to control what runs.

## Collector Controls

Available daemon collectors:

- `repo`
- `app`
- `browser`
- `terminal`
- `system`

Examples:

```bash
PYTHONPATH=src python3 -m ambient_ai daemon --once --collectors repo
PYTHONPATH=src python3 -m ambient_ai daemon --once --collectors repo,system
PYTHONPATH=src python3 -m ambient_ai daemon --once --disable-collector terminal --disable-collector browser
AMBIENT_AI_COLLECTORS=repo,system PYTHONPATH=src python3 -m ambient_ai daemon --once
AMBIENT_AI_DISABLE_COLLECTORS=terminal,browser PYTHONPATH=src python3 -m ambient_ai daemon --once
```

## Hermes Handoff

Refresh Ambient artifacts on a schedule:

```bash
*/5 * * * * cd /path/to/ambient-ai && PYTHONPATH=src python3 -m ambient_ai render-hermes --output context/hermes-handoff.md
```

Hermes should read `context/hermes-handoff.md`, inspect referenced context files, and only notify the user for useful completed work, meaningful blockers, or required approval.

## Keywords

local AI context engine, proactive AI agents, ambient context, coding agent context, local-first AI assistant, Hermes agent handoff, agent memory substrate, SQLite event log, AI workflow automation, context reduction, LLM context management
