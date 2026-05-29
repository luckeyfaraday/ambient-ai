# Agent Boundary

Hermes is the reference external agent runtime that consumes Ambient AI context, but this boundary applies to *any* consuming agent (Claude Code, Codex, OpenCode, your own harness). Ambient gathers and compacts; the agent decides and acts. Agents consume context over the MCP server (`ambient://` resources) or the rendered files below.

## Consuming-Agent Responsibilities

- Read context: MCP resources `ambient://hot`, `ambient://recent`, `ambient://diff`, `ambient://sessions`, `ambient://preferences` (or the files `context/hermes-handoff.md`, `hot.json`, `recent.md`)
- Decide whether useful, safe, timely work exists based on raw events
- Act on reversible local research, notes, drafts, prototypes without bothering the user
- Ask before external side effects, spending, deleting, committing, deploying, messaging, large downloads
- Notify only for useful completed work, meaningful blockers, or required approval
- Write feedback: call the `record_outcome` MCP tool (or append to `context/learning/trigger-outcomes.jsonl`)
- Update preferences: write stable policy to `context/learning/preferences.md`
- Recognize patterns in the event stream
- Score importance and confidence
- Hand off bounded tasks to other agents via `prompts/agent_work_contract.md`
- Own its own schedule and cron config

## Ambient AI Responsibilities

- Collect cheap local signals: browser/video history, active window, git state, terminal history (secret-redacted), system state
- Store events in SQLite with fingerprint dedup
- Reduce (structural only): dedupe, diff vs. previous cycle, time-gap sessionize, group by source; write `hot.json` and `recent.md`
- Serve context over MCP (`ambient://` resources) and render `hermes-handoff.md`
- Provide write-back tools: `record_outcome`, `refresh`
- Provide skill contract: `skills/hermes-ambient-ai/SKILL.md`
- Provide learning file paths: `preferences.md`, `trigger-outcomes.jsonl`
- Run the daemon loop: collect → store → reduce → render

## The Line: structural compaction vs. semantic interpretation

Ambient performs only **structural compaction** — dedupe, set-diff across cycles, time-gap sessionization, grouping by source. These are mechanical operations over events and timestamps.

Ambient does **not** perform **semantic interpretation** — it does not guess user intent, flag patterns, select "candidate work," or score importance/confidence. That is the consuming agent's job.

If proposed reducer logic interprets rather than compacts, it belongs in the agent, not Ambient. (Diffing and time-gap grouping are compaction; "these events are about project X and worth acting on" is interpretation.)
