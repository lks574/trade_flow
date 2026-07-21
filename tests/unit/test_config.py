from dataclasses import replace
from decimal import Decimal

import pytest

from trade_flow.domain.config import ConfigError, load_config


def test_load_config_is_deterministic() -> None:
    first = load_config("configs/strategy.toml")
    second = load_config("configs/strategy.toml")

    assert first == second
    assert first.config_hash == second.config_hash
    assert len(first.config_hash) == 64


def test_factor_weights_must_sum_to_one() -> None:
    config = load_config("configs/strategy.toml")

    with pytest.raises(ConfigError, match="sum to 1"):
        replace(
            config.strategy.factor_weights,
            momentum=Decimal("0.60"),
        )


def test_allocations_sum_to_one() -> None:
    config = load_config("configs/strategy.toml")
    strategy = config.strategy

    assert (
        strategy.main_target_weight
        + strategy.high_volatility_total_cap
        + strategy.cash_buffer_weight
        == 1
    )


def test_sentiment_remains_a_shadow_configuration() -> None:
    config = load_config("configs/strategy.toml")

    assert config.sentiment.candidate_limit == 20
    assert config.sentiment.minimum_observation_sessions == 60
    assert config.sentiment.forward_return_horizons == (1, 5, 20)
    assert config.execution.limit_offset_fraction == Decimal("0.003")
    assert config.execution.order_timeout_seconds == 600
    assert config.monitoring.daily_candidate_limit == 3
    assert config.monitoring.weekly_candidate_limit == 5
    assert config.monitoring.hold_rank_limit == 10
    assert config.monitoring.minimum_entry_score == Decimal("0.75")
    assert config.monitoring.daily_event_lookback_days == 3
    assert config.monitoring.weekly_event_lookback_days == 7
