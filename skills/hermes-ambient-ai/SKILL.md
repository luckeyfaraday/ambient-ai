---
name: hermes-ambient-ai
description: "Use Ambient AI context artifacts from a Hermes session or schedule to decide action, no-action, blocked, or handoff outcomes."
---

# Hermes Ambient AI Skill

Use this skill when a Hermes session is asked to consume Ambient AI context or when a scheduled Hermes run reads an Ambient handoff file.

## Inputs

- `context/hermes-handoff.md`: current Ambient handoff prompt.
- `context/hot.json`: compact machine-readable context.
- `context/recent.md`: human-readable recent context.
- `context/learning/preferences.md`: explicit preferences and standing policy.
- `context/learning/trigger-outcomes.jsonl`: append-only outcome history.
- `prompts/agent_work_contract.md`: contract for work handed to another external agent.

## Decision Policy

1. Read the handoff and referenced context files.
2. Decide whether useful, safe, timely work exists.
3. No-op silently when value is unclear or no action is warranted.
4. Act only on reversible local research, analysis, notes, tiny tests, prototypes, and drafts.
5. Ask before external side effects, spending, deleting, committing, deploying, messaging, publishing, credential changes, or large downloads.
6. Notify the user only for useful completed work, meaningful blockers, or required approval.
7. Append learning outcomes only from explicit feedback or clear outcomes. Do not overfit from one event.

## Outputs

- `no_action`: no report.
- `done`: concise result with evidence.
- `blocked`: smallest required approval or missing fact.
- `handoff`: bounded task for another external agent/tool, using `prompts/agent_work_contract.md`.

When feedback or an outcome is clear, append a short entry to `context/learning/trigger-outcomes.jsonl` or update `context/learning/preferences.md` if the feedback is stable policy.
