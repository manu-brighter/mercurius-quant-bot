from pathlib import Path

from mercurius.config import load_config
from mercurius.strategies.registry import build_strategies

ROOT = Path(__file__).resolve().parents[2]


def _cfg():
    return load_config(ROOT / "config" / "default.yaml")


def test_builds_one_instance_per_symbol():
    strategies = build_strategies(_cfg())
    ids = sorted(s.strategy_id for s in strategies)
    assert ids == ["noise_bands_QQQ", "noise_bands_SPY", "orb_QQQ", "orb_SPY"]
    by_id = {s.strategy_id: s for s in strategies}
    assert by_id["noise_bands_SPY"].symbol == "SPY"
    assert by_id["orb_QQQ"].symbol == "QQQ"


def test_only_filter_accepts_family_and_instance():
    assert {s.strategy_id for s in build_strategies(_cfg(), only="orb")} == {
        "orb_QQQ",
        "orb_SPY",
    }
    assert [s.strategy_id for s in build_strategies(_cfg(), only="orb_QQQ")] == ["orb_QQQ"]


def test_disabled_family_excluded():
    cfg = _cfg()
    cfg.strategies.noise_bands.enabled = False
    ids = {s.strategy_id for s in build_strategies(cfg)}
    assert ids == {"orb_QQQ", "orb_SPY"}


def test_pilot_overlay_scales_risk():
    cfg = load_config(ROOT / "config" / "default.yaml", ROOT / "config" / "pilot.yaml")
    assert str(cfg.capital_usd) == "300"
    assert cfg.risk.max_trades_per_day == 2
    assert cfg.risk.max_concurrent_positions == 1
    # untouched risk keys inherit from default
    assert cfg.risk.equity_poll_seconds == 20
