from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from pathlib import Path

from .collectors import (
    AppWindowCollector,
    BrowserCollector,
    Collector,
    RepoCollector,
    TerminalHistoryCollector,
)
from .events import EventStore
from .paths import AmbientPaths
from .reducers import reduce_context
from .renderer import write_hermes_prompt


def default_collectors(repo_path: Path | None = None) -> list[Collector]:
    return [
        RepoCollector(repo_path),
        AppWindowCollector(),
        BrowserCollector(),
        TerminalHistoryCollector(),
    ]


def run_once(
    paths: AmbientPaths,
    collectors: Iterable[Collector] | None = None,
    repo_path: Path | None = None,
) -> int:
    paths.ensure()
    store = EventStore(paths.db_path)
    store.init()
    events = []
    for collector in collectors or default_collectors(repo_path):
        events.extend(collector.collect())
    inserted = store.add_events(events)
    store.expire()
    reduce_context(paths)
    write_hermes_prompt(paths)
    return inserted


def run_daemon(
    paths: AmbientPaths,
    interval_seconds: float,
    iterations: int | None = None,
    repo_path: Path | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    total_inserted = 0
    completed = 0
    while iterations is None or completed < iterations:
        total_inserted += run_once(paths, repo_path=repo_path)
        completed += 1
        if iterations is not None and completed >= iterations:
            break
        sleep(interval_seconds)
    return total_inserted
