from datetime import date
from pathlib import Path

import pytest

from mercurius.backtest.sweep import HoldoutViolation, deflated_sharpe, run_sweep, total_trials
from mercurius.config import load_config
from tests.helpers import minute_bars
from tests.integration.test_backtest_engine import ScriptedStrategy

ROOT = Path(__file__).resolve().parents[2]


def _cfg(tmp_path):
    cfg = load_config(ROOT / "config" / "default.yaml", ROOT / "config" / "backtest.yaml")
    cfg.backtest.trial_log = tmp_path / "trials.jsonl"
    return cfg


def test_sweep_refuses_holdout_bars(tmp_path):
    cfg = _cfg(tmp_path)  # holdout_start = 2026-01-01
    bars = minute_bars("SPY", date(2026, 8, 7), [100.0, 101.0, 102.0])
    with pytest.raises(HoldoutViolation):
        run_sweep(cfg, lambda **kw: ScriptedStrategy(2, 3), {"x": [1]}, bars)


def test_sweep_logs_every_trial(tmp_path):
    cfg = _cfg(tmp_path)
    bars = minute_bars("SPY", date(2025, 8, 7), [100.0, 100.5, 101.0, 101.5, 102.0, 102.5])
    results = run_sweep(
        cfg,
        lambda enter_at, exit_at: ScriptedStrategy(enter_at, exit_at),
        {"enter_at": [1, 2], "exit_at": [4, 5]},
        bars,
    )
    assert len(results) == 4
    assert total_trials(cfg.backtest.trial_log) == 4
    # a second sweep accumulates rather than resets
    run_sweep(
        cfg,
        lambda enter_at, exit_at: ScriptedStrategy(enter_at, exit_at),
        {"enter_at": [1], "exit_at": [4]},
        bars,
    )
    assert total_trials(cfg.backtest.trial_log) == 5


def test_dsr_penalizes_trial_count():
    # same observed sharpe: more trials => lower confidence
    few = deflated_sharpe(1.5, n_obs=252, n_trials=2)
    many = deflated_sharpe(1.5, n_obs=252, n_trials=500)
    assert few > many
    assert 0.0 <= many <= few <= 1.0


def test_dsr_rewards_sample_length():
    short = deflated_sharpe(1.5, n_obs=60, n_trials=50)
    long = deflated_sharpe(1.5, n_obs=750, n_trials=50)
    assert long > short
