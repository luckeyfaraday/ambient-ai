from __future__ import annotations

import time
from collections.abc import Callable, Iterable

from .collectors import Collector, RepoCollector
from .events import EventStore
from .paths import AmbientPaths
from .reducers import reduce_context
from .renderer import write_hermes_prompt


def default_collectors() -> list[Collector]:
    return [RepoCollector()]


def run_once(paths: AmbientPaths, collectors: Iterable[Collector] | None = None) -> int:
    paths.ensure()
    store = EventStore(paths.db_path)
    store.init()
    events = []
    for collector in collectors or default_collectors():
        events.extend(collector.collect())
    inserted = store.add_events(events)
    reduce_context(paths)
    write_hermes_prompt(paths)
    return inserted


def run_daemon(
    paths: AmbientPaths,
    interval_seconds: float,
    iterations: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    total_inserted = 0
    completed = 0
    while iterations is None or completed < iterations:
        total_inserted += run_once(paths)
        completed += 1
        if iterations is not None and completed >= iterations:
            break
        sleep(interval_seconds)
    return total_inserted
