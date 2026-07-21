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
