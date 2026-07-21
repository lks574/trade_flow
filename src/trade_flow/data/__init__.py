"""Canonical market-data and universe contracts."""

from trade_flow.data.market import (
    DailyBar,
    DataQualityError,
    MarketDataSnapshot,
    QualityIssue,
    QualityReport,
    build_market_data_snapshot,
)
from trade_flow.data.universe import (
    SymbolMapping,
    UniverseGrade,
    UniverseSpec,
    load_universe,
)

__all__ = [
    "DataQualityError",
    "DailyBar",
    "MarketDataSnapshot",
    "QualityIssue",
    "QualityReport",
    "SymbolMapping",
    "UniverseGrade",
    "UniverseSpec",
    "build_market_data_snapshot",
    "load_universe",
]
