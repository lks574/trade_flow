from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from trade_flow.safety.gate import ExecutionEnvironment


@dataclass(frozen=True)
class RuntimeConfig:
    environment: ExecutionEnvironment
    dry_run: bool
    allow_real_orders: bool
    release_approved: bool
    allowed_account_hashes: frozenset[str]
    kill_switch_path: Path


def load_runtime_config(path: str | Path) -> RuntimeConfig:
    with Path(path).open("rb") as file:
        raw = tomllib.load(file)
    try:
        environment = ExecutionEnvironment(str(raw.get("environment", "")))
    except ValueError as exc:
        raise ValueError("runtime environment must be paper or production") from exc
    boolean_fields = ("dry_run", "allow_real_orders", "release_approved")
    for field in boolean_fields:
        if not isinstance(raw.get(field), bool):
            raise ValueError(f"runtime {field} must be a boolean")
    allowlist = raw.get("allowed_account_hashes")
    if not isinstance(allowlist, list) or any(not isinstance(item, str) for item in allowlist):
        raise ValueError("runtime allowed_account_hashes must be a string array")
    kill_switch_path = raw.get("kill_switch_path")
    if not isinstance(kill_switch_path, str) or not kill_switch_path:
        raise ValueError("runtime kill_switch_path must be a path")
    return RuntimeConfig(
        environment=environment,
        dry_run=raw["dry_run"],
        allow_real_orders=raw["allow_real_orders"],
        release_approved=raw["release_approved"],
        allowed_account_hashes=frozenset(allowlist),
        kill_switch_path=Path(kill_switch_path),
    )


def kill_switch_active(config: RuntimeConfig, *, project_root: Path) -> bool:
    path = config.kill_switch_path
    resolved = path if path.is_absolute() else project_root / path
    return resolved.exists()
