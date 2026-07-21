from datetime import date

import pytest

from trade_flow.data.universe import UniverseConfigError, UniverseGrade, load_universe


def test_point_in_time_universe_and_hash(tmp_path) -> None:
    path = tmp_path / "universe.toml"
    path.write_text(
        """
grade = "B"
description = "public membership history"

[[symbols]]
symbol = "AAA"
provider_symbol = "AAA"
broker_symbol = "AAA"
valid_from = 2020-01-01
valid_to = 2021-12-31
source = "fixture"

[[symbols]]
symbol = "BBB"
valid_from = 2022-01-01
source = "fixture"
""",
        encoding="utf-8",
    )

    universe = load_universe(path)

    assert universe.grade is UniverseGrade.B
    assert [item.symbol for item in universe.active_symbols(date(2021, 1, 1))] == ["AAA"]
    assert [item.symbol for item in universe.active_symbols(date(2022, 1, 1))] == ["BBB"]
    assert universe.universe_hash == load_universe(path).universe_hash


def test_universe_rejects_overlapping_identity_key(tmp_path) -> None:
    path = tmp_path / "universe.toml"
    path.write_text(
        """
grade = "B"
[[symbols]]
symbol = "AAA"
valid_from = 2020-01-01
source = "one"
[[symbols]]
symbol = "AAA"
valid_from = 2020-01-01
source = "two"
""",
        encoding="utf-8",
    )

    with pytest.raises(UniverseConfigError, match="must be unique"):
        load_universe(path)


def test_universe_rejects_overlapping_ranges(tmp_path) -> None:
    path = tmp_path / "universe.toml"
    path.write_text(
        """
grade = "B"
[[symbols]]
symbol = "AAA"
valid_from = 2020-01-01
valid_to = 2022-01-01
source = "one"
[[symbols]]
symbol = "AAA"
valid_from = 2021-01-01
source = "two"
""",
        encoding="utf-8",
    )

    with pytest.raises(UniverseConfigError, match="overlapping"):
        load_universe(path)
