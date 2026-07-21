from datetime import date, timedelta
from decimal import Decimal

from trade_flow.backtest import EquityPoint
from trade_flow.risk import RegimeState
from trade_flow.validation import EventWindow, analyze_event_windows


def test_event_study_reports_drawdown_recovery_and_regime_activation() -> None:
    start = date(2020, 3, 1)
    values = [Decimal("100"), Decimal("80"), Decimal("90"), Decimal("105")]
    curve = tuple(
        EquityPoint(start + timedelta(days=index), value, value, Decimal(0))
        for index, value in enumerate(values)
    )
    states = {
        start + timedelta(days=1): RegimeState(start + timedelta(days=1), True, True, 0, ("vix",))
    }

    result = analyze_event_windows(
        curve,
        states,
        (EventWindow("shock", start, start + timedelta(days=3)),),
    )[0]

    assert result.maximum_drawdown == -0.2
    assert result.recovery_sessions == 3
    assert result.regime_active_sessions == 1
