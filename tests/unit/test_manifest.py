from datetime import UTC, datetime

from trade_flow.domain.config import load_config
from trade_flow.domain.manifest import ExecutionManifest


def test_manifest_contains_reproducibility_hashes() -> None:
    config = load_config("configs/strategy.toml")
    manifest = ExecutionManifest.create(
        config=config,
        data_hash="DATA",
        universe_hash="UNIVERSE",
        now=datetime(2026, 7, 21, tzinfo=UTC),
    )

    assert manifest.config_hash == config.config_hash
    assert manifest.data_hash == "data"
    assert manifest.universe_hash == "universe"
    assert manifest.created_at == "2026-07-21T00:00:00+00:00"
