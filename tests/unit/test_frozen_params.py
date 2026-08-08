"""Published parameters are frozen. Changing one is a new hypothesis.

This project's pattern is to enforce rules in code rather than rely on
discipline (see `sweep._assert_no_holdout` and the yfinance import guard).
This test is the same idea applied to the parameters we took from published
sources: if a future session tunes one to make a backtest look better, this
goes red instead of the change passing silently.

Legitimately changing one of these is allowed — it is simply not a *tweak*:
update the value here, log it as a new trial in `trials/trials.jsonl`, and add
a dated section to `docs/backtests.md`. The point is that it cannot happen
without someone deciding to do it on purpose.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from mercurius.config import load_config

ROOT = Path(__file__).resolve().parents[2]

WHY = (
    "\n\nThis parameter is frozen at its published value. If you are changing it "
    "to improve a backtest, stop — that is the overfitting path CLAUDE.md "
    "forbids. If the change is deliberate, it is a NEW HYPOTHESIS: update this "
    "test, log a trial in trials/trials.jsonl, and add a dated section to "
    "docs/backtests.md."
)


@pytest.fixture(scope="module")
def cfg():
    return load_config(ROOT / "config" / "default.yaml")


@pytest.fixture(scope="module")
def defaults():
    """Schema defaults, unshadowed by YAML.

    Both layers must be checked: YAML wins at runtime, but a drifted schema
    default silently reaches every config that does not override the key.
    """
    from mercurius.config.schema import StrategiesConfig

    return StrategiesConfig()


def test_noise_bands_lookback_frozen(cfg, defaults):
    """SSRN 4824172 uses a 14-day lookback. Not a tuning knob."""
    assert cfg.strategies.noise_bands.lookback_days == 14, WHY
    assert defaults.noise_bands.lookback_days == 14, WHY
    assert list(cfg.strategies.noise_bands.decision_minutes) == [0, 30], WHY
    assert list(defaults.noise_bands.decision_minutes) == [0, 30], WHY


def test_noise_bands_has_no_fixed_percentage_trail(cfg):
    """The 0.5% trail was our invention and was removed in the fidelity audit.

    The paper trails on max(band, session VWAP). Reintroducing a fixed-percent
    trail would silently re-break fidelity to the source.
    """
    assert not hasattr(cfg.strategies.noise_bands, "trail_stop_pct"), (
        "trail_stop_pct is back in the config" + WHY
    )


@pytest.mark.parametrize("layer", ["yaml", "schema"])
def test_orb_published_parameters_frozen(cfg, defaults, layer):
    orb = cfg.strategies.orb if layer == "yaml" else defaults.orb
    assert orb.range_minutes == 5, WHY
    assert orb.entry_cutoff == "10:30", WHY
    assert orb.target_r_multiple == Decimal("2"), WHY
    assert orb.min_range_atr_frac == Decimal("0.15"), WHY
    assert orb.max_range_atr_frac == Decimal("0.60"), WHY
    assert orb.volume_mult == Decimal("1.5"), WHY


@pytest.mark.parametrize("layer", ["yaml", "schema"])
def test_rsi2_published_parameters_frozen(cfg, defaults, layer):
    """Connors: RSI(2) < 10 in, > 65 out, 200d trend filter, 5d SMA exit."""
    r = cfg.strategies.rsi2 if layer == "yaml" else defaults.rsi2
    assert r.rsi_period == 2, WHY
    assert r.entry_rsi == Decimal("10"), WHY
    assert r.exit_rsi == Decimal("65"), WHY
    assert r.trend_sma == 200, WHY
    assert r.exit_sma == 5, WHY


@pytest.mark.parametrize("layer", ["yaml", "schema"])
def test_ibs_published_parameters_frozen(cfg, defaults, layer):
    i = cfg.strategies.ibs if layer == "yaml" else defaults.ibs
    assert i.entry_ibs == Decimal("0.2"), WHY
    assert i.exit_ibs == Decimal("0.8"), WHY
    assert i.trend_sma == 200, WHY


def test_cost_assumptions_not_loosened():
    """Lowering modeled costs is the cheapest way to fake an edge.

    2.5 bps total is already optimistic: measured p95 IEX-vs-SIP close
    divergence on QQQ is 4.41 bps (see README). Costs may be raised, never
    lowered.
    """
    for overlay in ("backtest.yaml", "swing.yaml"):
        c = load_config(ROOT / "config" / "default.yaml", ROOT / "config" / overlay)
        total = c.backtest.slippage_bps + c.backtest.spread_haircut_bps
        assert c.backtest.slippage_bps >= Decimal("1.5"), f"{overlay}: {WHY}"
        assert c.backtest.spread_haircut_bps >= Decimal("1.0"), f"{overlay}: {WHY}"
        assert total >= Decimal("2.5"), f"{overlay} total cost lowered to {total}{WHY}"


def test_holdout_start_not_moved(cfg):
    """Moving the holdout boundary would quietly hand the sweep fresh data."""
    assert cfg.backtest.holdout_start == "2026-01-01", WHY


def test_scorecard_thresholds_not_relaxed(cfg):
    """The go/no-go bar is pre-registered; it may be raised, never lowered."""
    sc = cfg.scorecard
    assert sc.min_trades >= 150, WHY
    assert sc.min_sessions >= 40, WHY
    assert sc.min_profit_factor >= Decimal("1.2"), WHY
    assert sc.max_drawdown_pct <= Decimal("0.15"), WHY
    assert sc.max_slippage_ratio <= Decimal("1.5"), WHY


def test_paper_mode_is_the_default(cfg):
    """Live trading is a human decision, never an incidental config change."""
    example = (ROOT / ".env.example").read_text()
    assert "MERCURIUS_ALPACA_PAPER=true" in example, WHY
