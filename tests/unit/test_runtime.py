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
