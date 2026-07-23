from trade_flow.safety import (
    ExecutionEnvironment,
    kill_switch_active,
    load_runtime_config,
)


def test_default_runtime_is_paper_dry_run_and_kill_switch_is_file_based(tmp_path) -> None:
    config = load_runtime_config("configs/runtime.example.toml")

    assert config.environment is ExecutionEnvironment.PAPER
    assert config.dry_run
    assert not config.allow_real_orders
    assert not config.release_approved
    assert not kill_switch_active(config, project_root=tmp_path)

    (tmp_path / "STOP_TRADING").touch()
    assert kill_switch_active(config, project_root=tmp_path)


def test_environment_binding_enforces_mock_paper_real_production() -> None:
    """C-1: 자격증명↔런타임 결합 행렬. real+paper 우회 조합은 반드시 차단."""
    import pytest

    from trade_flow.safety import EnvironmentMismatchError, validate_environment_binding

    # 허용 조합
    validate_environment_binding("mock", ExecutionEnvironment.PAPER)
    validate_environment_binding("real", ExecutionEnvironment.PRODUCTION)

    # 우회 조합: real 자격증명이 paper 게이트로 실주문 도달 금지
    with pytest.raises(EnvironmentMismatchError, match="requires runtime"):
        validate_environment_binding("real", ExecutionEnvironment.PAPER)
    # 역방향: mock 자격증명으로 production 감사 기록을 남기는 것도 금지
    with pytest.raises(EnvironmentMismatchError, match="requires runtime"):
        validate_environment_binding("mock", ExecutionEnvironment.PRODUCTION)
    # 알 수 없는 자격증명 환경은 fail-closed
    with pytest.raises(EnvironmentMismatchError, match="unknown"):
        validate_environment_binding("staging", ExecutionEnvironment.PAPER)
