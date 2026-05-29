"""Structured append-only outcome log.

This is the seed corn for Ambient AI's only compounding asset: a per-user
record of what consuming agents decided and how it landed. Ambient does not
interpret these records — it just stores them durably and hands them back so
agents (and, later, reducers shaping handoffs) can learn signal from noise.

Records are newline-delimited JSON appended to
``context/learning/trigger-outcomes.jsonl``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from .paths import AmbientPaths

# Canonical decisions, mirroring prompts/agent_work_contract.md. Other values
# are allowed (we store, we don't judge) but these are the expected vocabulary.
DECISIONS = ("no_action", "done", "blocked", "handoff")


@dataclass(frozen=True)
class Outcome:
    decision: str
    summary: str = ""
    agent: str = "unknown"
    evidence: list[str] = field(default_factory=list)
    event_ids: list[int] = field(default_factory=list)
    recorded_at: str = ""

    def normalized(self) -> "Outcome":
        return Outcome(
            decision=self.decision,
            summary=self.summary.strip(),
            agent=self.agent or "unknown",
            evidence=list(self.evidence),
            event_ids=list(self.event_ids),
            recorded_at=self.recorded_at or datetime.now(timezone.utc).isoformat(),
        )


def append_outcome(paths: AmbientPaths, outcome: Outcome) -> Outcome:
    """Append one outcome record; returns the normalized record written."""
    paths.ensure()
    record = outcome.normalized()
    log_path = paths.learning_dir / "trigger-outcomes.jsonl"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(record), sort_keys=True) + "\n")
    return record


def read_outcomes(paths: AmbientPaths, limit: int | None = None) -> list[dict[str, Any]]:
    """Read outcome records most-recent-first. Skips malformed lines."""
    log_path = paths.learning_dir / "trigger-outcomes.jsonl"
    if not log_path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    records.reverse()
    if limit is not None:
        return records[:limit]
    return records
