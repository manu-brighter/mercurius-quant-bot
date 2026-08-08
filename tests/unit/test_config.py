from decimal import Decimal
from pathlib import Path

from mercurius.config import load_config

ROOT = Path(__file__).resolve().parents[2]


def test_default_config_loads():
    cfg = load_config(ROOT / "config" / "default.yaml")
    assert cfg.capital_usd == Decimal("2000")
    assert cfg.strategies.noise_bands.lookback_days == 14
    assert cfg.data.feed == "iex"
    assert cfg.risk.max_daily_loss_usd == Decimal("40")


def test_yaml_merge_later_wins(tmp_path):
    override = tmp_path / "override.yaml"
    override.write_text("risk:\n  max_trades_per_day: 1\n")
    cfg = load_config(ROOT / "config" / "default.yaml", override)
    assert cfg.risk.max_trades_per_day == 1
    # untouched keys survive the merge
    assert cfg.risk.max_concurrent_positions == 2


def test_secrets_never_in_yaml():
    cfg = load_config(ROOT / "config" / "default.yaml")
    # secrets default empty unless env provides them; repr must not leak
    assert "SecretStr" in repr(type(cfg.secrets.alpaca_api_key))


def test_backtest_overlay():
    cfg = load_config(ROOT / "config" / "default.yaml", ROOT / "config" / "backtest.yaml")
    assert cfg.backtest.slippage_bps == Decimal("1.5")
    assert cfg.backtest.end.startswith("2025")
