from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from trade_flow.data import load_universe
from trade_flow.db import initialize_database
from trade_flow.domain.config import load_config
from trade_flow.domain.manifest import ExecutionManifest
from trade_flow.monitoring import (
    build_daily_monitoring_report,
    build_weekly_discovery_report,
    load_events,
    load_monitoring_snapshot,
    load_positions,
)


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from exc


def _add_monitoring_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--universe", type=Path, required=True)
    parser.add_argument("--high-volatility-universe", type=Path)
    parser.add_argument("--portfolio", type=Path, required=True)
    parser.add_argument("--events", type=Path)
    parser.add_argument("--source", required=True)
    parser.add_argument("--as-of", type=_date, required=True)


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

    monitor_daily = subparsers.add_parser("monitor-daily")
    _add_monitoring_arguments(monitor_daily)

    screen_weekly = subparsers.add_parser("screen-weekly")
    _add_monitoring_arguments(screen_weekly)
    return parser


def _monitoring_inputs(args: argparse.Namespace):
    config = load_config(args.config)
    main_universe = load_universe(args.universe)
    high_universe = (
        load_universe(args.high_volatility_universe)
        if args.high_volatility_universe is not None
        else None
    )
    main_symbols = {item.symbol for item in main_universe.active_symbols(args.as_of)}
    high_symbols = (
        {item.symbol for item in high_universe.active_symbols(args.as_of)}
        if high_universe is not None
        else set()
    )
    positions = load_positions(args.portfolio)
    events = load_events(args.events)
    snapshot = load_monitoring_snapshot(
        args.db,
        symbols=main_symbols | high_symbols | set(positions),
        as_of=args.as_of,
        source=args.source,
        minimum_price_days=config.strategy.minimum_price_days,
    )
    return config, main_symbols, high_symbols, positions, events, snapshot


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
    if args.command in {"monitor-daily", "screen-weekly"}:
        config, main_symbols, high_symbols, positions, events, snapshot = _monitoring_inputs(args)
        if args.command == "monitor-daily":
            report = build_daily_monitoring_report(
                snapshot,
                config,
                positions=positions,
                main_symbols=main_symbols,
                high_volatility_symbols=high_symbols,
                events=events,
            )
        else:
            report = build_weekly_discovery_report(
                snapshot,
                config,
                positions=positions,
                main_symbols=main_symbols,
                high_volatility_symbols=high_symbols,
                events=events,
            )
        print(report.to_json())
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
