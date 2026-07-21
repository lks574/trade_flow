from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from trade_flow.domain.config import AppConfig


@dataclass(frozen=True)
class ExecutionManifest:
    phase: str
    strategy_version: str
    config_hash: str
    data_hash: str
    universe_hash: str
    created_at: str

    @classmethod
    def create(
        cls,
        config: AppConfig,
        data_hash: str,
        universe_hash: str,
        phase: str = "phase1",
        now: datetime | None = None,
    ) -> ExecutionManifest:
        created = now or datetime.now(UTC)
        return cls(
            phase=phase,
            strategy_version=config.strategy_version,
            config_hash=config.config_hash,
            data_hash=_require_hash(data_hash, "data_hash"),
            universe_hash=_require_hash(universe_hash, "universe_hash"),
            created_at=created.astimezone(UTC).isoformat(),
        )

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=True, indent=2, sort_keys=True)


def _require_hash(value: str, field: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized
