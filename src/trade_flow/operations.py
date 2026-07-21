from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Notification:
    subject: str
    body: str
    severity: str


@dataclass(frozen=True)
class DeliveryResult:
    delivered: bool
    provider_message_id: str | None
    error_code: str | None


class Notifier(Protocol):
    def send(self, notification: Notification) -> DeliveryResult: ...
