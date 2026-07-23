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


class EnvironmentMismatchError(RuntimeError):
    """KIS 자격증명(mock/real)과 런타임(paper/production)이 결합 규칙을 위반."""


_ENVIRONMENT_BINDING: dict[str, ExecutionEnvironment] = {
    "mock": ExecutionEnvironment.PAPER,
    "real": ExecutionEnvironment.PRODUCTION,
}


def validate_environment_binding(
    credential_environment: str, runtime_environment: ExecutionEnvironment
) -> None:
    """자격증명↔런타임 강제 매핑: mock↔paper, real↔production (교차리뷰 C-1).

    real 자격증명이 paper 런타임으로 실행되면 production 전용 3중 게이트
    (allow_real_orders/release_approved/allowlist)를 우회한 채 실주문 경로에
    도달할 수 있다. 불일치는 어떤 주문·취소도 하기 전에 치명 오류로 종료한다.
    """
    expected = _ENVIRONMENT_BINDING.get(credential_environment)
    if expected is None:
        raise EnvironmentMismatchError(
            f"unknown credential environment: {credential_environment!r}"
        )
    if expected is not runtime_environment:
        raise EnvironmentMismatchError(
            f"KIS credential '{credential_environment}' requires runtime "
            f"'{expected}', but runtime.toml says '{runtime_environment}'. "
            "실주문은 environment=production + 3중 게이트 승인으로만 가능하다."
        )
