from __future__ import annotations

import json
import tomllib
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Any


class UniverseConfigError(ValueError):
    """Raised when a universe cannot be interpreted deterministically."""


class UniverseGrade(StrEnum):
    A = "A"
    B = "B"
    C = "C"


@dataclass(frozen=True)
class SymbolMapping:
    symbol: str
    provider_symbol: str
    broker_symbol: str
    valid_from: date
    valid_to: date | None
    source: str
    tradable: bool = True

    def __post_init__(self) -> None:
        if not self.symbol or not self.provider_symbol or not self.broker_symbol:
            raise UniverseConfigError("symbol mappings cannot be empty")
        if not self.source:
            raise UniverseConfigError("symbol mapping source is required")
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise UniverseConfigError("valid_to cannot precede valid_from")

    def active_on(self, session_date: date) -> bool:
        return self.valid_from <= session_date and (
            self.valid_to is None or session_date <= self.valid_to
        )


@dataclass(frozen=True)
class UniverseSpec:
    grade: UniverseGrade
    description: str
    symbols: tuple[SymbolMapping, ...]

    def active_symbols(self, session_date: date) -> tuple[SymbolMapping, ...]:
        return tuple(
            mapping
            for mapping in self.symbols
            if mapping.tradable and mapping.active_on(session_date)
        )

    @property
    def universe_hash(self) -> str:
        payload = []
        for mapping in self.symbols:
            item = asdict(mapping)
            item["valid_from"] = mapping.valid_from.isoformat()
            item["valid_to"] = mapping.valid_to.isoformat() if mapping.valid_to else None
            payload.append(item)
        canonical = json.dumps(
            {"grade": self.grade.value, "description": self.description, "symbols": payload},
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return sha256(canonical.encode("utf-8")).hexdigest()


def _date(value: object, field: str) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise UniverseConfigError(f"{field} must be an ISO date") from exc
    raise UniverseConfigError(f"{field} must be a date")


def _symbol_mapping(raw: Mapping[str, Any], index: int) -> SymbolMapping:
    prefix = f"symbols[{index}]"
    symbol = str(raw.get("symbol", "")).strip().upper()
    tradable = raw.get("tradable", True)
    if not isinstance(tradable, bool):
        raise UniverseConfigError(f"{prefix}.tradable must be a boolean")
    return SymbolMapping(
        symbol=symbol,
        provider_symbol=str(raw.get("provider_symbol", symbol)).strip(),
        broker_symbol=str(raw.get("broker_symbol", symbol)).strip(),
        valid_from=_date(raw.get("valid_from", "1900-01-01"), f"{prefix}.valid_from"),
        valid_to=(_date(raw["valid_to"], f"{prefix}.valid_to") if raw.get("valid_to") else None),
        source=str(raw.get("source", "")).strip(),
        tradable=tradable,
    )


def _reject_overlapping_ranges(symbols: tuple[SymbolMapping, ...]) -> None:
    by_symbol: dict[str, list[SymbolMapping]] = {}
    for mapping in symbols:
        by_symbol.setdefault(mapping.symbol, []).append(mapping)
    for symbol, mappings in by_symbol.items():
        ordered = sorted(mappings, key=lambda item: item.valid_from)
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if previous.valid_to is None or current.valid_from <= previous.valid_to:
                raise UniverseConfigError(f"overlapping validity ranges for {symbol}")


def load_universe(path: str | Path) -> UniverseSpec:
    with Path(path).open("rb") as file:
        raw = tomllib.load(file)
    try:
        grade = UniverseGrade(str(raw.get("grade", "")))
    except ValueError as exc:
        raise UniverseConfigError("grade must be A, B, or C") from exc
    symbol_rows = raw.get("symbols", [])
    if not isinstance(symbol_rows, list):
        raise UniverseConfigError("symbols must be an array of tables")
    symbols = tuple(_symbol_mapping(row, index) for index, row in enumerate(symbol_rows))
    keys = [(mapping.symbol, mapping.valid_from) for mapping in symbols]
    if len(keys) != len(set(keys)):
        raise UniverseConfigError("symbol and valid_from mappings must be unique")
    _reject_overlapping_ranges(symbols)
    return UniverseSpec(
        grade=grade,
        description=str(raw.get("description", "")).strip(),
        symbols=tuple(sorted(symbols, key=lambda item: (item.symbol, item.valid_from))),
    )
