# Hermes Boundary

Hermes is the external agent runtime that consumes Ambient AI context. Ambient gathers and compacts; Hermes decides and acts.

## Hermes Responsibilities

- Read context: `context/hermes-handoff.md`, `hot.json`, `recent.md`
- Decide whether useful, safe, timely work exists based on raw events
- Act on reversible local research, notes, drafts, prototypes without bothering the user
- Ask before external side effects, spending, deleting, committing, deploying, messaging, large downloads
- Notify only for useful completed work, meaningful blockers, or required approval
- Write feedback: append outcomes to `context/learning/trigger-outcomes.jsonl`
- Update preferences: write stable policy to `context/learning/preferences.md`
- Recognize patterns in the event stream
- Score importance and confidence
- Hand off bounded tasks to other agents via `prompts/agent_work_contract.md`
- Own its own schedule and cron config

## Ambient AI Responsibilities

- Collect cheap local signals: browser history, active window, git state
- Store events in SQLite with fingerprint dedup
- Reduce: dedupe, compact, write `hot.json` and `recent.md`
- Render handoff: `hermes-handoff.md` from template
- Provide skill contract: `skills/hermes-ambient-ai/SKILL.md`
- Provide learning file paths: `preferences.md`, `trigger-outcomes.jsonl`
- Run the daemon loop: collect → store → reduce → render

## The Line

Ambient does not interpret events, guess user intent, flag patterns, or score importance. If proposed reducer logic interprets rather than compacts, it belongs in Hermes.
