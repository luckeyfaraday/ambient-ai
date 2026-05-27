from __future__ import annotations

import argparse
from pathlib import Path

from .collectors import sample_events
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
    subparsers.add_parser("reduce")
    render = subparsers.add_parser("render-hermes")
    render.add_argument("--output", type=Path, default=None)
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
    if args.command == "reduce":
        hot = reduce_context(paths)
        print(f"Reduced {hot['event_count']} events into {paths.context_dir}")
        return 0
    if args.command == "render-hermes":
        output = write_hermes_prompt(paths, args.output)
        print(f"Rendered Hermes handoff to {output}")
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


if __name__ == "__main__":
    raise SystemExit(main())
