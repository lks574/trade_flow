from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from trade_flow.data import DailyBar, build_market_data_snapshot
from trade_flow.domain.config import load_config
from trade_flow.strategy import signal


def _history(symbol: str, *, slope: str, volume: int = 1000) -> list[DailyBar]:
    start = date(2025, 1, 1)
    increment = Decimal(slope)
    bars = []
    for index in range(201):
        close = Decimal(100) + increment * Decimal(index)
        bars.append(
            DailyBar(
                symbol=symbol,
                session_date=start + timedelta(days=index),
                open=close,
                high=close + Decimal(1),
                low=close - Decimal(1),
                close=close,
                split_adjusted_open=close,
                split_adjusted_high=close + Decimal(1),
                split_adjusted_low=close - Decimal(1),
                split_adjusted_close=close,
                volume=volume,
                cash_dividend=Decimal(0),
                source="fixture",
                fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
    return bars


def test_signal_ranks_and_allocates_sleeves_deterministically() -> None:
    config = load_config("configs/strategy.toml").strategy
    bars = [
        *_history("MAIN1", slope="0.50", volume=5000),
        *_history("MAIN2", slope="0.30", volume=4000),
        *_history("MAIN3", slope="0.20", volume=3000),
        *_history("MAIN4", slope="0.15", volume=2000),
        *_history("MAIN5", slope="0.10", volume=1000),
        *_history("MAIN6", slope="0.05", volume=500),
        *_history("HIGH1", slope="0.40"),
        *_history("HIGH2", slope="0.25"),
        *_history("HIGH3", slope="0.08"),
    ]
    sessions = sorted({bar.session_date for bar in bars})
    snapshot = build_market_data_snapshot(
        bars,
        as_of=sessions[-1],
        expected_sessions=sessions,
        expected_symbols={bar.symbol for bar in bars},
    )

    result = signal(
        snapshot,
        config,
        main_symbols={f"MAIN{index}" for index in range(1, 7)},
        high_volatility_symbols={f"HIGH{index}" for index in range(1, 4)},
    )

    assert tuple(result.target_weights) == (
        "HIGH1",
        "HIGH2",
        "MAIN1",
        "MAIN2",
        "MAIN3",
        "MAIN4",
        "MAIN5",
    )
    main_weights = [
        weight for symbol, weight in result.target_weights.items() if symbol.startswith("MAIN")
    ]
    assert all(weight == Decimal("0.176") for weight in main_weights)
    assert result.target_weights["HIGH1"] == result.target_weights["HIGH2"] == Decimal("0.05")
    assert result.cash_weight == Decimal("0.02")


def test_signal_keeps_unallocated_weight_in_cash() -> None:
    config = load_config("configs/strategy.toml").strategy
    bars = _history("ONLY", slope="0.10")
    sessions = [bar.session_date for bar in bars]
    snapshot = build_market_data_snapshot(
        bars,
        as_of=sessions[-1],
        expected_sessions=sessions,
        expected_symbols=["ONLY"],
    )

    result = signal(snapshot, config, main_symbols=["ONLY"])

    assert result.target_weights == {"ONLY": Decimal("0.176")}
    assert result.cash_weight == Decimal("0.824")


def test_select_ranked_hysteresis_retains_held_within_buffer() -> None:
    from trade_flow.strategy.signal import _select_ranked

    ranked = ["A", "B", "C", "D", "E", "F"]

    # hysteresis=0: 단순 상위 count.
    assert _select_ranked(ranked, frozenset({"E"}), 3, 0) == ["A", "B", "C"]

    # 보유 E가 상위 (3+2)=5 이내이면 유지하고 남은 자리를 신규 상위로 채운다.
    assert _select_ranked(ranked, frozenset({"E"}), 3, 2) == ["E", "A", "B"]

    # 보유 F가 버퍼(top-5) 밖이면 유지하지 않는다.
    assert _select_ranked(ranked, frozenset({"F"}), 3, 2) == ["A", "B", "C"]

    # 보유 종목이 없으면 hysteresis와 무관하게 상위 count.
    assert _select_ranked(ranked, frozenset(), 3, 2) == ["A", "B", "C"]


def test_signal_selection_hysteresis_retains_held_symbol_within_buffer() -> None:
    from dataclasses import replace

    base = load_config("configs/strategy.toml").strategy
    bars = [
        *_history("MAIN1", slope="0.50"),
        *_history("MAIN2", slope="0.30"),
        *_history("MAIN3", slope="0.20"),
        *_history("MAIN4", slope="0.15"),
        *_history("MAIN5", slope="0.10"),
        *_history("MAIN6", slope="0.05"),
    ]
    sessions = sorted({bar.session_date for bar in bars})
    snapshot = build_market_data_snapshot(
        bars, as_of=sessions[-1], expected_sessions=sessions,
        expected_symbols={bar.symbol for bar in bars},
    )
    main = {f"MAIN{index}" for index in range(1, 7)}

    # 기본(hysteresis=0): 상위 5 = MAIN1..5, MAIN6(rank6) 제외.
    default_res = signal(snapshot, base, main_symbols=main)
    assert "MAIN6" not in default_res.target_weights
    assert "MAIN5" in default_res.target_weights

    # hysteresis=2(top-7) + MAIN6 보유: MAIN6 유지, 최하위 신규 MAIN5가 밀려남.
    hyst = replace(base, selection_hysteresis=2)
    hyst_res = signal(snapshot, hyst, main_symbols=main, held_symbols=frozenset({"MAIN6"}))
    assert "MAIN6" in hyst_res.target_weights
    assert "MAIN5" not in hyst_res.target_weights
