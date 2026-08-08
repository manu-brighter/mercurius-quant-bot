"""Parameter sweeps with honest accounting.

Rules enforced here, not by discipline:
- The sweep REFUSES to see bars at/after `backtest.holdout_start`. The holdout
  is evaluated once, by a human, via a plain backtest — never by this module.
- Every trial (parameter combination evaluated) is appended to a JSONL log.
  The log is CUMULATIVE across the project's life; the Deflated Sharpe Ratio
  uses the total historical trial count N, not just this run's.

DSR reference: Bailey & López de Prado (2014), "The Deflated Sharpe Ratio".
"""

from __future__ import annotations

import itertools
import json
import logging
import math
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from statistics import NormalDist
from typing import Any

from mercurius.backtest.engine import run_backtest
from mercurius.backtest.metrics import daily_returns, sharpe
from mercurius.config.schema import AppConfig
from mercurius.core.models import Bar
from mercurius.strategies.base import Strategy

log = logging.getLogger(__name__)
_N = NormalDist()


class HoldoutViolation(RuntimeError):
    pass


def _assert_no_holdout(cfg: AppConfig, bars: list[Bar]) -> None:
    cutoff = datetime.fromisoformat(cfg.backtest.holdout_start).replace(tzinfo=UTC)
    if bars and bars[-1].ts_utc >= cutoff:
        raise HoldoutViolation(
            f"sweep given bars reaching {bars[-1].ts_utc:%Y-%m-%d}, at/after the "
            f"holdout start {cfg.backtest.holdout_start}. The holdout is evaluated "
            "once, manually — never swept."
        )


def _log_trial(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(record, default=str) + "\n")


def total_trials(path: Path) -> int:
    if not path.exists():
        return 0
    with open(path) as f:
        return sum(1 for _ in f)


def run_sweep(
    cfg: AppConfig,
    factory: Callable[..., Strategy],
    param_grid: dict[str, list[Any]],
    bars: list[Bar],
) -> list[dict[str, Any]]:
    """Evaluate every combination in `param_grid`; returns per-trial results
    sorted by Sharpe, with the DSR of the best trial computed against the
    cumulative project-wide trial count."""
    _assert_no_holdout(cfg, bars)

    keys = sorted(param_grid)
    results: list[dict[str, Any]] = []
    for combo in itertools.product(*(param_grid[k] for k in keys)):
        params = dict(zip(keys, combo, strict=True))
        strat = factory(**params)
        r = run_backtest(cfg, [strat], bars)
        rets = daily_returns(r.equity_curve)
        sr_daily = sharpe(rets)  # annualized
        record = {
            "ts": datetime.now(tz=UTC).isoformat(),
            "strategy": strat.strategy_id,
            "params": params,
            "sharpe": sr_daily,
            "n_days": len(rets),
            "n_trades": len(r.trades),
            "final_equity": str(r.final_equity),
        }
        _log_trial(cfg.backtest.trial_log, record)
        results.append(record)

    results.sort(key=lambda x: (x["sharpe"] is not None, x["sharpe"]), reverse=True)
    n_total = total_trials(cfg.backtest.trial_log)
    best = results[0] if results else None
    if best and best["sharpe"] is not None and best["n_days"] > 2:
        best["dsr"] = deflated_sharpe(
            observed_sharpe_annual=best["sharpe"],
            n_obs=best["n_days"],
            n_trials=max(n_total, len(results)),
        )
        log.info(
            "best trial sharpe=%.2f DSR=%.3f (N=%d cumulative trials)",
            best["sharpe"],
            best["dsr"],
            n_total,
        )
    return results


def deflated_sharpe(
    observed_sharpe_annual: float,
    n_obs: int,
    n_trials: int,
    skew: float = 0.0,
    kurtosis: float = 3.0,
    periods_per_year: int = 252,
) -> float:
    """P(true Sharpe > 0) after correcting for multiple testing.

    Values near 1.0 = likely real; below ~0.95 = do not trust the sweep winner.
    """
    if n_obs < 3 or n_trials < 1:
        return 0.0
    sr = observed_sharpe_annual / math.sqrt(periods_per_year)  # per-period SR

    # Expected max SR of n_trials pure-noise strategies (Euler-Mascheroni form)
    gamma = 0.5772156649015329
    if n_trials > 1:
        z1 = _N.inv_cdf(1 - 1 / n_trials)
        z2 = _N.inv_cdf(1 - 1 / (n_trials * math.e))
        sr0 = math.sqrt(1 / (n_obs - 1)) * ((1 - gamma) * z1 + gamma * z2)
    else:
        sr0 = 0.0

    denom = math.sqrt(max(1e-12, 1 - skew * sr + (kurtosis - 1) / 4 * sr**2))
    z = (sr - sr0) * math.sqrt(n_obs - 1) / denom
    return _N.cdf(z)


def walk_forward(
    cfg: AppConfig,
    factory: Callable[..., Strategy],
    param_grid: dict[str, list[Any]],
    bars: list[Bar],
    fit_days: int = 126,
    test_days: int = 21,
) -> dict[str, Any]:
    """Rolling fit/test: pick best params on each fit window (by Sharpe),
    evaluate them on the following test window; aggregate out-of-sample stats."""
    _assert_no_holdout(cfg, bars)

    by_day: dict = {}
    for b in bars:
        by_day.setdefault(b.ts_utc.date(), []).append(b)
    days = sorted(by_day)
    oos_trades: list[dict] = []
    windows = 0
    i = fit_days
    keys = sorted(param_grid)
    while i + test_days <= len(days):
        fit_bars = [b for d in days[i - fit_days : i] for b in by_day[d]]
        test_bars = [b for d in days[i : i + test_days] for b in by_day[d]]
        best_params, best_sr = None, -math.inf
        for combo in itertools.product(*(param_grid[k] for k in keys)):
            params = dict(zip(keys, combo, strict=True))
            r = run_backtest(cfg, [factory(**params)], fit_bars)
            sr = sharpe(daily_returns(r.equity_curve))
            _log_trial(
                cfg.backtest.trial_log,
                {
                    "ts": datetime.now(tz=UTC).isoformat(),
                    "walk_forward_fit": True,
                    "params": params,
                    "sharpe": sr,
                },
            )
            if sr is not None and sr > best_sr:
                best_sr, best_params = sr, params
        if best_params is not None:
            r_test = run_backtest(cfg, [factory(**best_params)], test_bars)
            oos_trades.extend(r_test.trades)
        windows += 1
        i += test_days

    pnls = [float(t["pnl"]) for t in oos_trades]
    return {
        "windows": windows,
        "oos_trades": len(oos_trades),
        "oos_net_pnl": sum(pnls),
        "oos_expectancy": (sum(pnls) / len(pnls)) if pnls else 0.0,
    }
