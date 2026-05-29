from __future__ import annotations

import sys
import time
from collections.abc import Callable, Iterable
from pathlib import Path

from .collectors import (
    AppWindowCollector,
    BrowserCollector,
    Collector,
    RepoCollector,
    SystemCollector,
    TerminalHistoryCollector,
)
from .events import EventStore
from .paths import AmbientPaths
from .reducers import reduce_context
from .renderer import write_hermes_prompt


COLLECTOR_NAMES = ("repo", "app", "browser", "terminal", "system")


def default_collector_names() -> list[str]:
    if sys.platform.startswith("linux"):
        return list(COLLECTOR_NAMES)
    if sys.platform == "darwin":
        return ["repo", "browser", "terminal"]
    if sys.platform == "win32":
        return ["repo", "app", "browser", "system"]
    return ["repo", "browser"]


def build_collectors(
    repo_path: Path | None = None,
    enabled: Iterable[str] | None = None,
    disabled: Iterable[str] | None = None,
) -> list[Collector]:
    enabled_names = normalize_collector_names(enabled) if enabled else default_collector_names()
    disabled_names = set(normalize_collector_names(disabled) if disabled else [])
    collectors: list[Collector] = []
    for name in enabled_names:
        if name in disabled_names:
            continue
        if name == "repo":
            collectors.append(RepoCollector(repo_path))
        elif name == "app":
            collectors.append(AppWindowCollector())
        elif name == "browser":
            collectors.append(BrowserCollector())
        elif name == "terminal":
            collectors.append(TerminalHistoryCollector())
        elif name == "system":
            collectors.append(SystemCollector())
        else:
            raise ValueError(f"Unknown collector: {name}")
    return collectors


def normalize_collector_names(names: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for item in names:
        for name in item.split(","):
            clean = name.strip().lower()
            if clean:
                normalized.append(clean)
    unknown = sorted(set(normalized) - set(COLLECTOR_NAMES))
    if unknown:
        raise ValueError(f"Unknown collector(s): {', '.join(unknown)}")
    return normalized


def default_collectors(repo_path: Path | None = None) -> list[Collector]:
    return build_collectors(repo_path)


def run_once(
    paths: AmbientPaths,
    collectors: Iterable[Collector] | None = None,
    repo_path: Path | None = None,
    enabled_collectors: Iterable[str] | None = None,
    disabled_collectors: Iterable[str] | None = None,
) -> int:
    paths.ensure()
    store = EventStore(paths.db_path)
    store.init()
    events = []
    selected_collectors = (
        collectors
        if collectors is not None
        else build_collectors(
            repo_path,
            enabled=enabled_collectors,
            disabled=disabled_collectors,
        )
    )
    for collector in selected_collectors:
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
    enabled_collectors: Iterable[str] | None = None,
    disabled_collectors: Iterable[str] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    total_inserted = 0
    completed = 0
    while iterations is None or completed < iterations:
        total_inserted += run_once(
            paths,
            repo_path=repo_path,
            enabled_collectors=enabled_collectors,
            disabled_collectors=disabled_collectors,
        )
        completed += 1
        if iterations is not None and completed >= iterations:
            break
        sleep(interval_seconds)
    return total_inserted
