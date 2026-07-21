from datetime import date

from trade_flow.validation import build_validation_windows


def test_walk_forward_windows_exclude_latest_holdout() -> None:
    sessions = [date(year, month, 1) for year in range(2010, 2027) for month in range(1, 13)]

    windows = build_validation_windows(
        sessions,
        train_years=5,
        validation_years=1,
        holdout_years=2,
    )

    assert windows[0].train_start == date(2010, 1, 1)
    assert windows[0].validation_start == date(2015, 1, 1)
    assert all(window.validation_end < date(2024, 12, 1) for window in windows)
    assert windows[-1].validation_end < date(2024, 12, 1)
