from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

_US_EASTERN = ZoneInfo("America/New_York")


def within_us_market_hours(now: datetime) -> bool:
    """미국 정규장(평일 09:30~16:00 ET) 여부. tz-aware datetime 필요.

    미국 공휴일은 반영하지 않는다(브로커가 장종료로 fail-closed). SafetyContext의
    within_execution_window 입력으로 쓰며, KIS 장종료 거부에 앞선 예방적 게이트다.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    eastern = now.astimezone(_US_EASTERN)
    if eastern.weekday() >= 5:  # 토(5)·일(6)
        return False
    open_time = eastern.replace(hour=9, minute=30, second=0, microsecond=0)
    close_time = eastern.replace(hour=16, minute=0, second=0, microsecond=0)
    return open_time <= eastern <= close_time


@dataclass(frozen=True)
class Notification:
    subject: str
    body: str
    severity: str


class NavHistory:
    """일별 확정 NAV 기록(JSON 파일). daily_return(전 거래일 확정 NAV 대비) 계산에 쓴다.

    일일손실 한도(§0.2) 판정의 입력. 파일은 data/ 등 gitignore 경로에 둔다.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def _load(self) -> dict[str, str]:
        try:
            data = json.loads(self._path.read_text())
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def last_before(self, on: date) -> tuple[date, Decimal] | None:
        """on 이전(미포함) 가장 최근 기록. 재실행 시 당일 값에 영향받지 않도록 미포함."""
        records = self._load()
        prior = [
            (date.fromisoformat(day), Decimal(value))
            for day, value in records.items()
            if date.fromisoformat(day) < on
        ]
        if not prior:
            return None
        return max(prior, key=lambda item: item[0])

    def daily_return(self, current_nav: Decimal, *, on: date) -> Decimal:
        previous = self.last_before(on)
        if previous is None or previous[1] <= 0:
            return Decimal(0)
        return current_nav / previous[1] - Decimal(1)

    def record(self, on: date, nav: Decimal) -> None:
        records = self._load()
        records[on.isoformat()] = format(nav, "f")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(dict(sorted(records.items())), indent=2))


@dataclass(frozen=True)
class DeliveryResult:
    delivered: bool
    provider_message_id: str | None
    error_code: str | None


class Notifier(Protocol):
    def send(self, notification: Notification) -> DeliveryResult: ...


class LogNotifier:
    """가장 단순한 Notifier 구현(§3.7): 표준출력 + 선택적 로그 파일에 append.

    슬랙/이메일 등은 이 프로토콜을 구현해 교체한다. 운영 상태·실행 요약·경보에 쓴다.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path else None

    def send(self, notification: Notification) -> DeliveryResult:
        from datetime import UTC, datetime

        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        line = f"{stamp} [{notification.severity}] {notification.subject} — {notification.body}"
        print(line)
        if self._path is not None:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
            except OSError as error:
                return DeliveryResult(
                    delivered=False, provider_message_id=None, error_code=str(error)
                )
        return DeliveryResult(delivered=True, provider_message_id=None, error_code=None)
