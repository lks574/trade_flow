from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ValidationWindow:
    train_start: date
    train_end: date
    validation_start: date
    validation_end: date


def _anniversary(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, day=28)


def build_validation_windows(
    sessions: list[date],
    *,
    train_years: int,
    validation_years: int,
    holdout_years: int,
) -> tuple[ValidationWindow, ...]:
    ordered = sorted(set(sessions))
    if not ordered or min(train_years, validation_years, holdout_years) <= 0:
        raise ValueError("sessions and positive window lengths are required")
    holdout_start_target = _anniversary(ordered[-1], -holdout_years)
    pre_holdout = [session for session in ordered if session < holdout_start_target]
    if not pre_holdout:
        return ()
    windows: list[ValidationWindow] = []
    train_start = ordered[0]
    while True:
        validation_start_target = _anniversary(train_start, train_years)
        validation_end_target = _anniversary(validation_start_target, validation_years)
        train_sessions = [session for session in pre_holdout if session < validation_start_target]
        validation_sessions = [
            session
            for session in pre_holdout
            if validation_start_target <= session < validation_end_target
        ]
        if not train_sessions or not validation_sessions:
            break
        windows.append(
            ValidationWindow(
                train_start=train_sessions[0],
                train_end=train_sessions[-1],
                validation_start=validation_sessions[0],
                validation_end=validation_sessions[-1],
            )
        )
        train_start = _anniversary(train_start, validation_years)
    return tuple(windows)
