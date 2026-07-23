from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from trade_flow.backtest import run_backtest
from trade_flow.data import (
    DailyBar,
    SymbolMapping,
    UniverseGrade,
    UniverseSpec,
    build_market_data_snapshot,
)
from trade_flow.domain.config import load_config


def _snapshot():
    start = date(2025, 1, 1)
    bars = []
    for index in range(202):
        session = start + timedelta(days=index)
        close = Decimal(100) + Decimal(index) / Decimal(10)
        open_price = Decimal(150) if index == 201 else close
        bars.append(
            DailyBar(
                symbol="A",
                session_date=session,
                open=open_price,
                high=max(open_price, close) + Decimal(1),
                low=min(open_price, close) - Decimal(1),
                close=close,
                split_adjusted_open=open_price,
                split_adjusted_high=max(open_price, close) + Decimal(1),
                split_adjusted_low=min(open_price, close) - Decimal(1),
                split_adjusted_close=close,
                volume=1000,
                cash_dividend=Decimal(0),
                source="fixture",
                fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
    sessions = [bar.session_date for bar in bars]
    return build_market_data_snapshot(
        bars,
        as_of=sessions[-1],
        expected_sessions=sessions,
        expected_symbols=["A"],
    )


def test_backtest_executes_close_signal_at_next_open_with_costs() -> None:
    config = load_config("configs/strategy.toml")

    result = run_backtest(
        _snapshot(),
        config,
        main_symbols=["A"],
        initial_cash=Decimal("20000000"),
        transaction_cost_bps=15,
    )

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.signal_date < trade.execution_date
    assert trade.price == Decimal(150)
    assert trade.side == "buy"
    assert trade.transaction_cost > 0
    assert trade.realized_pnl is None
    assert result.equity_curve[-1].cash >= 0


def test_backtest_blocks_buys_when_regime_state_missing() -> None:
    # 오버레이 요청(빈 dict)했으나 매매 세션에 레짐 상태가 없으면 fail-closed로 매수 차단.
    config = load_config("configs/strategy.toml")

    result = run_backtest(
        _snapshot(),
        config,
        main_symbols=["A"],
        initial_cash=Decimal("20000000"),
        transaction_cost_bps=15,
        regime_states={},
    )

    assert result.trades == ()


def _uptrend_snapshot(symbols: list[str], n_sessions: int):
    # 상승 추세 + 소폭 진동. 모든 심볼이 적격(close>SMA200)이라 계속 보유되며,
    # 일간 진동이 목표 주식수를 조금씩 흔들어 보유 종목 미세 재조정을 유발한다.
    start = date(2024, 1, 1)
    bars = []
    for s_index, symbol in enumerate(symbols):
        base = Decimal(100 + 20 * s_index)
        prev = base
        for i in range(n_sessions):
            close = base + Decimal(i) / Decimal(2) + Decimal((i % 3) - 1)
            open_price = prev
            hi = max(open_price, close) + Decimal(1)
            lo = min(open_price, close) - Decimal(1)
            bars.append(
                DailyBar(
                    symbol=symbol,
                    session_date=start + timedelta(days=i),
                    open=open_price,
                    high=hi,
                    low=lo,
                    close=close,
                    split_adjusted_open=open_price,
                    split_adjusted_high=hi,
                    split_adjusted_low=lo,
                    split_adjusted_close=close,
                    volume=1000,
                    cash_dividend=Decimal(0),
                    source="fixture",
                    fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
                )
            )
            prev = close
    sessions = sorted({bar.session_date for bar in bars})
    return build_market_data_snapshot(
        bars, as_of=sessions[-1], expected_sessions=sessions, expected_symbols=symbols
    )


def test_rebalance_band_suppresses_within_band_micro_rebalancing() -> None:
    config = load_config("configs/strategy.toml")
    snapshot = _uptrend_snapshot(["A", "B", "C"], 212)

    no_band = run_backtest(snapshot, config, main_symbols=["A", "B", "C"])
    with_band = run_backtest(
        snapshot, config, main_symbols=["A", "B", "C"], rebalance_band=Decimal("0.10")
    )

    # 밴드 없으면 매 세션 미세 재조정이 누적되고, 넉넉한 밴드는 진입 후 재조정을 억제한다.
    assert len(with_band.trades) < len(no_band.trades)
    assert len(with_band.trades) > 0  # 신규 진입은 밴드와 무관하게 체결


def test_backtest_uses_point_in_time_universe_membership() -> None:
    config = load_config("configs/strategy.toml")
    base = _snapshot()
    sessions = sorted({bar.session_date for bar in base.prices})
    second_symbol = tuple(DailyBar(**{**bar.__dict__, "symbol": "B"}) for bar in base.prices)
    snapshot = build_market_data_snapshot(
        [*base.prices, *second_symbol],
        as_of=sessions[-1],
        expected_sessions=sessions,
        expected_symbols=["A", "B"],
    )
    universe = UniverseSpec(
        grade=UniverseGrade.B,
        description="fixture membership history",
        symbols=(
            SymbolMapping("A", "A", "A", sessions[0], sessions[-3], "fixture"),
            SymbolMapping("B", "B", "B", sessions[-2], None, "fixture"),
        ),
    )

    result = run_backtest(
        snapshot,
        config,
        main_symbols=universe,
        initial_cash=Decimal("20000000"),
        transaction_cost_bps=0,
    )

    assert result.trades[0].symbol == "B"
    assert result.trades[0].execution_date == sessions[-1]


def test_rebalance_band_does_not_suppress_risk_reduced_targets() -> None:
    # band 억제는 일반 재조정에만 적용되고, 리스크 정책이 축소한 목표(risk_reduced_symbols)는
    # 밴드 이내여도 반드시 체결되어야 한다(§3.4 리스크 축소 > no-trade band).
    from trade_flow.backtest.engine import Position, _execute_targets

    positions = {
        "A": Position(100, Decimal("100")),
        "B": Position(100, Decimal("100")),
    }
    open_prices = {"A": Decimal("100"), "B": Decimal("100")}
    # nav=20000, 현재 비중 A=B=0.5. 목표 0.48(드리프트 0.02 < band 0.03).
    target_weights = {"A": Decimal("0.48"), "B": Decimal("0.48")}

    cash, trades = _execute_targets(
        signal_date=date(2025, 1, 1),
        execution_date=date(2025, 1, 2),
        target_weights=target_weights,
        open_prices=open_prices,
        cash=Decimal("0"),
        positions=positions,
        cost_rate=Decimal("0"),
        rebalance_band=Decimal("0.03"),
        risk_reduced_symbols=frozenset({"A"}),
    )
    sold = {t.symbol for t in trades if t.side == "sell"}
    # A는 리스크 축소 → 억제 제외 → 매도 체결. B는 일반 드리프트 → band로 억제.
    assert "A" in sold
    assert "B" not in sold


def test_rebalance_band_suppresses_when_not_risk_reduced() -> None:
    # 대조군: 동일 조건에서 risk_reduced가 비어 있으면 둘 다 band로 억제된다.
    from trade_flow.backtest.engine import Position, _execute_targets

    positions = {"A": Position(100, Decimal("100")), "B": Position(100, Decimal("100"))}
    open_prices = {"A": Decimal("100"), "B": Decimal("100")}
    target_weights = {"A": Decimal("0.48"), "B": Decimal("0.48")}
    cash, trades = _execute_targets(
        signal_date=date(2025, 1, 1),
        execution_date=date(2025, 1, 2),
        target_weights=target_weights,
        open_prices=open_prices,
        cash=Decimal("0"),
        positions=positions,
        cost_rate=Decimal("0"),
        rebalance_band=Decimal("0.03"),
        risk_reduced_symbols=frozenset(),
    )
    assert trades == []
