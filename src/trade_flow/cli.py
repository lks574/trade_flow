from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from trade_flow.db import initialize_database
from trade_flow.domain.config import load_config
from trade_flow.domain.manifest import ExecutionManifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trade-flow")
    subparsers = parser.add_subparsers(dest="command", required=True)

    show_config = subparsers.add_parser("show-config")
    show_config.add_argument("--config", type=Path, required=True)

    init_db = subparsers.add_parser("init-db")
    init_db.add_argument("--db", type=Path, required=True)

    manifest = subparsers.add_parser("manifest")
    manifest.add_argument("--config", type=Path, required=True)
    manifest.add_argument("--data-hash", required=True)
    manifest.add_argument("--universe-hash", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "show-config":
        config = load_config(args.config)
        print(
            json.dumps(
                {"config": config.canonical_mapping(), "config_hash": config.config_hash},
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "init-db":
        path = initialize_database(args.db)
        print(path)
        return 0
    if args.command == "manifest":
        config = load_config(args.config)
        manifest = ExecutionManifest.create(
            config=config,
            data_hash=args.data_hash,
            universe_hash=args.universe_hash,
        )
        print(manifest.to_json())
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
