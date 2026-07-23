from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol
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


class TelegramNotifier:
    """텔레그램 Bot API sendMessage 기반 외부 알림 채널(§3.7, §8 미결 7번).

    자격증명은 KIS와 같은 .env 패턴: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.
    전송 실패는 예외 대신 DeliveryResult(delivered=False)로 반환하며, 오류 문자열에
    토큰이 노출되지 않도록 마스킹한다. 실행 흐름을 막지 않는 best-effort 채널이다.
    """

    _SEVERITY_ICONS = {"critical": "🚨", "error": "❌", "warning": "⚠️", "info": "ℹ️"}
    _API_BASE = "https://api.telegram.org"

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        *,
        session: Any = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._token = bot_token
        self._chat_id = chat_id
        self._session = session
        self._timeout = timeout_seconds

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> TelegramNotifier | None:
        """TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID가 둘 다 있으면 생성, 아니면 None."""
        source = os.environ if env is None else env
        token = source.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = source.get("TELEGRAM_CHAT_ID", "").strip()
        if not token or not chat_id:
            return None
        return cls(token, chat_id)

    def _get_session(self) -> Any:
        if self._session is None:
            import requests  # 지연 import (live extra)

            self._session = requests.Session()
        return self._session

    def _redact(self, text: str) -> str:
        return text.replace(self._token, "***") if self._token else text

    def send(self, notification: Notification) -> DeliveryResult:
        icon = self._SEVERITY_ICONS.get(notification.severity, "ℹ️")
        text = f"{icon} [{notification.severity}] {notification.subject}\n{notification.body}"
        url = f"{self._API_BASE}/bot{self._token}/sendMessage"
        try:
            response = self._get_session().post(
                url,
                json={"chat_id": self._chat_id, "text": text},
                timeout=self._timeout,
            )
            payload = response.json()
        except Exception as error:  # noqa: BLE001 - 알림 실패는 실행을 막지 않는다
            return DeliveryResult(
                delivered=False,
                provider_message_id=None,
                error_code=self._redact(f"{type(error).__name__}: {error}"),
            )
        if not payload.get("ok"):
            description = payload.get("description", f"http {response.status_code}")
            return DeliveryResult(
                delivered=False, provider_message_id=None, error_code=self._redact(str(description))
            )
        message_id = payload.get("result", {}).get("message_id")
        return DeliveryResult(
            delivered=True,
            provider_message_id=None if message_id is None else str(message_id),
            error_code=None,
        )


class FanoutNotifier:
    """여러 Notifier에 순차 발송하고 실패를 집계한다.

    delivered는 전부 성공일 때만 True. 부분 실패의 error_code를 모아 반환해
    호출부가 실패를 인지할 수 있게 한다(전송 실패 무시 금지 — 리뷰 M4).
    """

    def __init__(self, *notifiers: Notifier) -> None:
        if not notifiers:
            raise ValueError("FanoutNotifier requires at least one notifier")
        self._notifiers = notifiers

    def send(self, notification: Notification) -> DeliveryResult:
        results = [notifier.send(notification) for notifier in self._notifiers]
        failures = [r.error_code or "unknown" for r in results if not r.delivered]
        if failures:
            return DeliveryResult(
                delivered=False, provider_message_id=None, error_code="; ".join(failures)
            )
        message_id = next((r.provider_message_id for r in results if r.provider_message_id), None)
        return DeliveryResult(delivered=True, provider_message_id=message_id, error_code=None)
