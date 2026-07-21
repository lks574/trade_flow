from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from trade_flow.backtest import EquityPoint
from trade_flow.risk import RegimeState


@dataclass(frozen=True)
class EventWindow:
    name: str
    start: date
    end: date


@dataclass(frozen=True)
class EventStudyResult:
    name: str
    start: date
    end: date
    total_return: float
    maximum_drawdown: float
    recovery_sessions: int
    regime_active_sessions: int


def analyze_event_windows(
    equity_curve: tuple[EquityPoint, ...],
    regime_states: Mapping[date, RegimeState],
    windows: tuple[EventWindow, ...],
) -> tuple[EventStudyResult, ...]:
    output: list[EventStudyResult] = []
    for window in windows:
        points = [
            point for point in equity_curve if window.start <= point.session_date <= window.end
        ]
        if len(points) < 2:
            continue
        peak = points[0].nav
        peak_index = 0
        drawdown = Decimal(0)
        recovery = 0
        for index, point in enumerate(points):
            if point.nav >= peak:
                recovery = max(recovery, index - peak_index)
                peak = point.nav
                peak_index = index
            else:
                drawdown = min(drawdown, point.nav / peak - Decimal(1))
                recovery = max(recovery, index - peak_index)
        active_sessions = sum(
            regime_states.get(
                point.session_date,
                RegimeState(point.session_date, False, True, 0, ()),
            ).active
            for point in points
        )
        output.append(
            EventStudyResult(
                name=window.name,
                start=points[0].session_date,
                end=points[-1].session_date,
                total_return=float(points[-1].nav / points[0].nav - Decimal(1)),
                maximum_drawdown=float(drawdown),
                recovery_sessions=recovery,
                regime_active_sessions=active_sessions,
            )
        )
    return tuple(output)
