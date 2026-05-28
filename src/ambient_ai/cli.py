from __future__ import annotations

import argparse
import os
from pathlib import Path

from .collectors import RepoCollector, sample_events
from .daemon import COLLECTOR_NAMES, normalize_collector_names, run_daemon, run_once
from .events import EventStore
from .paths import AmbientPaths
from .reducers import reduce_context
from .renderer import write_hermes_prompt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ambient-ai")
    parser.add_argument("--root", type=Path, default=None, help="Ambient AI workspace root.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init")
    subparsers.add_parser("ingest-sample")
    collect_repo = subparsers.add_parser("collect-repo")
    collect_repo.add_argument("--repo", type=Path, default=Path.cwd(), help="Git repository to inspect.")
    subparsers.add_parser("reduce")
    render = subparsers.add_parser("render-hermes")
    render.add_argument("--output", type=Path, default=None)
    daemon = subparsers.add_parser("daemon")
    daemon.add_argument("--interval", type=float, default=300.0, help="Seconds between collection cycles.")
    daemon.add_argument("--iterations", type=int, default=None, help="Stop after this many cycles.")
    daemon.add_argument("--once", action="store_true", help="Run one collection cycle and exit.")
    daemon.add_argument(
        "--repo",
        type=Path,
        default=None,
        help="Git repository to collect. Defaults to the current working directory.",
    )
    daemon.add_argument(
        "--collectors",
        default=os.environ.get("AMBIENT_AI_COLLECTORS"),
        help=(
            "Comma-separated collectors to run. Choices: "
            f"{', '.join(COLLECTOR_NAMES)}. Defaults to all."
        ),
    )
    daemon.add_argument(
        "--disable-collector",
        action="append",
        default=[],
        choices=COLLECTOR_NAMES,
        help="Disable a collector by name. May be repeated.",
    )
    expire = subparsers.add_parser("expire")
    expire.add_argument("--days", type=int, default=7, help="Remove events older than this many days.")
    subparsers.add_parser("smoke")
    args = parser.parse_args(argv)

    paths = AmbientPaths.from_env(args.root)
    store = EventStore(paths.db_path)

    if args.command == "init":
        paths.ensure()
        store.init()
        reduce_context(paths)
        print(f"Initialized Ambient AI at {paths.root}")
        return 0
    if args.command == "ingest-sample":
        paths.ensure()
        store.init()
        count = store.add_events(sample_events())
        print(f"Ingested {count} sample events")
        return 0
    if args.command == "collect-repo":
        paths.ensure()
        store.init()
        count = store.add_events(RepoCollector(args.repo).collect())
        print(f"Collected {count} repo events")
        return 0
    if args.command == "reduce":
        hot = reduce_context(paths)
        print(f"Reduced {hot['event_count']} events into {paths.context_dir}")
        return 0
    if args.command == "render-hermes":
        output = write_hermes_prompt(paths, args.output)
        print(f"Rendered Hermes handoff to {output}")
        return 0
    if args.command == "daemon":
        try:
            enabled_collectors = parse_collectors(args.collectors)
            disabled_collectors = [
                *parse_collectors(os.environ.get("AMBIENT_AI_DISABLE_COLLECTORS")),
                *args.disable_collector,
            ]
        except ValueError as exc:
            parser.error(str(exc))
        if args.once:
            inserted = run_once(
                paths,
                repo_path=args.repo,
                enabled_collectors=enabled_collectors,
                disabled_collectors=disabled_collectors,
            )
        else:
            inserted = run_daemon(
                paths,
                interval_seconds=args.interval,
                iterations=args.iterations,
                repo_path=args.repo,
                enabled_collectors=enabled_collectors,
                disabled_collectors=disabled_collectors,
            )
        print(f"Daemon collected {inserted} new events")
        return 0
    if args.command == "expire":
        store.init()
        removed = store.expire(max_age_days=args.days)
        print(f"Expired {removed} events older than {args.days} days")
        return 0
    if args.command == "smoke":
        paths.ensure()
        store.init()
        store.add_events(sample_events())
        reduce_context(paths)
        output = write_hermes_prompt(paths)
        print(f"Smoke OK: {output}")
        return 0
    raise AssertionError(args.command)


def parse_collectors(value: str | None) -> list[str]:
    if not value:
        return []
    return normalize_collector_names([value])


if __name__ == "__main__":
    raise SystemExit(main())
